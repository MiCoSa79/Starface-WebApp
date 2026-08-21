"""STARFACE WebApp — Verwaltungs-Web-App für das Anrufblocker-Modul.

FastAPI + SQLite + Jinja2. Multi-User mit TOTP-2FA, Anlagenverwaltung
(mehrere STARFACE-Anlagen), Rufnummernlisten-Pflege via XML-RPC
(ListGet, ListAdd, ListRemove), Zugangsdaten verschlüsselt (Fernet).

Port: 8000 (Docker, Container-intern) → Host: 8895
"""

import hashlib
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import bcrypt
import httpx
import pyotp
from cryptography.fernet import Fernet
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# ─────────────────────────────────────────────────────────────
# Konfiguration (Env, vom Container gesetzt)
# ─────────────────────────────────────────────────────────────

DB_PATH = os.environ.get("STARFACE_DB", "/data/starface.db")
FERNET_KEY = os.environ.get("FERNET_KEY", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_COOKIE = "sf_webapp_session"
SESSION_LIFETIME = 8 * 3600  # Sekunden

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_FERNET = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def _encrypt(plain: str) -> str:
    if not _FERNET:
        return plain
    return "enc:" + _FERNET.encrypt(plain.encode()).decode()


def _decrypt(stored: str) -> str:
    if not _FERNET or not stored.startswith("enc:"):
        return stored
    return _FERNET.decrypt(stored[4:].encode()).decode()


# ─────────────────────────────────────────────────────────────
# Datenbank
# ─────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            otp_secret TEXT,
            backup_codes TEXT,
            otp_confirmed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS installations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            auth_id TEXT,
            auth_pass TEXT,
            client_secret TEXT,
            is_starface10 INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS access (
            user_id INTEGER NOT NULL,
            installation_id INTEGER NOT NULL,
            can_read INTEGER DEFAULT 0,
            can_write INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, installation_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            installation_id INTEGER,
            user_id INTEGER,
            action TEXT,
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────

def create_session(user_id: int) -> str:
    sid = secrets.token_urlsafe(48)
    expires = (datetime.utcnow() + timedelta(seconds=SESSION_LIFETIME)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _db()
    conn.execute("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?,?,?)",
                 (sid, user_id, expires))
    conn.commit()
    conn.close()
    return sid


def verify_session(sid: Optional[str]) -> Optional[dict]:
    if not sid:
        return None
    conn = _db()
    row = conn.execute(
        "SELECT u.id AS user_id, u.username, u.is_admin FROM sessions s "
        "JOIN users u ON s.user_id = u.id "
        "WHERE s.session_id = ? AND s.expires_at > ?",
        (sid, datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(sid: str):
    conn = _db()
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# Rechte
# ─────────────────────────────────────────────────────────────

def get_access(user_id: int, installation_id: int) -> dict:
    """Gibt {can_read, can_write} zurück. Admin hat überall Vollzugriff."""
    conn = _db()
    u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    a = conn.execute("SELECT can_read, can_write FROM access WHERE user_id=? AND installation_id=?",
                     (user_id, installation_id)).fetchone()
    conn.close()
    if u and u["is_admin"]:
        return {"can_read": True, "can_write": True, "is_admin": True}
    if a:
        return {"can_read": bool(a["can_read"]), "can_write": bool(a["can_write"]), "is_admin": False}
    return {"can_read": False, "can_write": False, "is_admin": False}


def _log_event(installation_id: Optional[int], user_id: int, action: str, detail: str = ""):
    conn = _db()
    conn.execute("INSERT INTO events (installation_id, user_id, action, detail) VALUES (?,?,?,?)",
                 (installation_id, user_id, action, detail))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# STARFACE-Zugriff (XML-RPC)
# ─────────────────────────────────────────────────────────────

def starface_token(url: str, auth_id: str, auth_pass: str, client_secret: str,
                   is_starface10: bool) -> str:
    """Liefert den XML-RPC-Auth-Token.

    10.x: OAuth2 Password Grant → JWT
    ≤9.x: Legacy-Token Login:sha512(Login+"*"+sha512(Passwort))
    """
    if is_starface10:
        r = httpx.post(
            f"{url.rstrip('/')}/auth/realms/pbx/oauth2/token",
            data={
                "client_id": "rest-client-headless",
                "grant_type": "password",
                "scope": "login",
                "username": auth_id,
                "password": auth_pass,
                "client_secret": client_secret,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("access_token", "")
    else:
        inner = hashlib.sha512(auth_pass.encode()).hexdigest()
        return auth_id + ":" + hashlib.sha512((auth_id + "*" + inner).encode()).hexdigest()


def _xmlrpc(url: str, token: str, method: str, params: dict = None) -> dict:
    """Führt einen XML-RPC-Call gegen die STARFACE aus.

    methodName = [Entrypoint-Name] (der Instanzname wird von STARFACE
    aus dem Session-Kontext der API aufgelöst).
    """
    params = params or {}
    members = "".join(
        f"<member><name>{k}</name><value><string>{v}</string></value></member>"
        for k, v in params.items()
    )
    body = (
        '<?xml version="1.0"?><methodCall>'
        f"<methodName>{method}</methodName>"
        f"<params><param><value><struct>{members}</struct></value></param></params>"
        "</methodCall>"
    )
    r = httpx.post(
        f"{url.rstrip('/')}/xml-rpc?de.vertico.starface.jwt={quote(token)}",
        content=body,
        headers={"Content-Type": "text/xml"},
        timeout=20,
    )
    r.raise_for_status()
    # Ergebnis: letztes <string> im Response (einfache Antworten)
    import re
    strings = re.findall(r"<string>(.*?)</string>", r.text, re.S)
    return {"raw": r.text, "values": strings}


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        conn = _db()
        exists = conn.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)).fetchone()
        if not exists:
            ph = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
            conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                         (ADMIN_USERNAME, ph, 1))
            conn.commit()
            print(f"[Starface-WebApp] Admin '{ADMIN_USERNAME}' angelegt")
        conn.close()
    yield


app = FastAPI(title="STARFACE WebApp", lifespan=lifespan)


# ─────────────────────────────────────────────────────────────
# Auth-Routen
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if verify_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/dashboard")
    return TEMPLATES.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request,
                username: str = Form(...),
                password: str = Form(...),
                otp_code: Optional[str] = Form(None)):
    conn = _db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return RedirectResponse("/?error=1", status_code=303)

    if user["otp_secret"] and user["otp_confirmed"]:
        if not otp_code or not pyotp.TOTP(user["otp_secret"]).verify(otp_code):
            return RedirectResponse("/?error=2", status_code=303)

    sid = create_session(user["id"])
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax",
                    max_age=SESSION_LIFETIME)
    return resp


@app.get("/logout")
async def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        delete_session(sid)
    resp = RedirectResponse("/")
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ─────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")

    conn = _db()
    installations = conn.execute("SELECT * FROM installations ORDER BY name").fetchall()
    conn.close()

    rows = []
    for inst in installations:
        acc = get_access(user["user_id"], inst["id"])
        if not acc["can_read"] and not acc["is_admin"]:
            continue  # keine Sicht auf diese Anlage
        rows.append({"id": inst["id"], "name": inst["name"], "url": inst["url"],
                     "is10": bool(inst["is_starface10"]), **acc})

    return TEMPLATES.TemplateResponse("dashboard.html",
                                      {"request": request, "user": user, "installations": rows})


# ─────────────────────────────────────────────────────────────
# Anlagen-Verwaltung (Admin)
# ─────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    installations = conn.execute("SELECT * FROM installations ORDER BY name").fetchall()
    users = conn.execute("SELECT id, username, is_admin, otp_confirmed FROM users ORDER BY username").fetchall()
    access = conn.execute("SELECT * FROM access").fetchall()
    conn.close()

    return TEMPLATES.TemplateResponse("admin.html",
                                      {"request": request, "user": user,
                                       "installations": installations,
                                       "users": users, "access": access,
                                       "OTP_ISSUER": "STARFACE-WebApp"})


@app.post("/admin/installations")
async def admin_installation_create(request: Request,
                                    name: str = Form(...),
                                    url: str = Form(...),
                                    auth_id: str = Form(""),
                                    auth_pass: str = Form(""),
                                    client_secret: str = Form(""),
                                    is_starface10: int = Form(1)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    conn.execute(
        "INSERT INTO installations (name, url, auth_id, auth_pass, client_secret, is_starface10) "
        "VALUES (?,?,?,?,?,?)",
        (name, url, _encrypt(auth_id), _encrypt(auth_pass), _encrypt(client_secret),
         bool(is_starface10)))
    conn.commit()
    conn.close()
    _log_event(None, user["user_id"], "installation_create", name)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/installations/{inst_id}/delete")
async def admin_installation_delete(request: Request, inst_id: int):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    conn.execute("DELETE FROM installations WHERE id = ?", (inst_id,))
    conn.execute("DELETE FROM access WHERE installation_id = ?", (inst_id,))
    conn.commit()
    conn.close()
    _log_event(inst_id, user["user_id"], "installation_delete", str(inst_id))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/access")
async def admin_access_set(request: Request,
                           user_id: int = Form(...),
                           installation_id: int = Form(...),
                           can_read: int = Form(0),
                           can_write: int = Form(0)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    conn.execute(
        "INSERT INTO access (user_id, installation_id, can_read, can_write) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id, installation_id) "
        "DO UPDATE SET can_read=excluded.can_read, can_write=excluded.can_write",
        (user_id, installation_id, bool(can_read), bool(can_write)))
    conn.commit()
    conn.close()
    _log_event(installation_id, user["user_id"], "access_set", f"u{user_id}")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/users")
async def admin_user_create(request: Request,
                            username: str = Form(...),
                            password: str = Form(...),
                            is_admin: int = Form(0)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    ph = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = _db()
    try:
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                     (username, ph, bool(is_admin)))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    _log_event(None, user["user_id"], "user_create", username)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/users/{uid}/delete")
async def admin_user_delete(request: Request, uid: int):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    if uid == user["user_id"]:
        return RedirectResponse("/admin", status_code=303)
    conn = _db()
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.execute("DELETE FROM access WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)


# ─────────────────────────────────────────────────────────────
# 2FA (TOTP) — Admin-Bereich
# ─────────────────────────────────────────────────────────────

@app.post("/admin/users/{uid}/totp-setup")
async def admin_totp_setup(request: Request, uid: int):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    secret = pyotp.random_base32()
    conn = _db()
    conn.execute("UPDATE users SET otp_secret=?, otp_confirmed=0, backup_codes=? WHERE id=?",
                 (secret, _gen_backup_codes(), uid))
    conn.commit()
    conn.close()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        f"user-{uid}", issuer_name="STARFACE-WebApp")
    # QR-Code lokal erzeugen (data-URI, kein externer Dienst)
    import base64 as _b64
    import io as _io
    import qrcode
    img = qrcode.make(uri)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    qr_data_uri = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
    return TEMPLATES.TemplateResponse("otp_setup.html",
                                      {"request": request, "user": user, "uid": uid,
                                       "secret": secret, "qr_data_uri": qr_data_uri})


@app.post("/admin/users/{uid}/totp-confirm")
async def admin_totp_confirm(request: Request, uid: int, code: str = Form(...)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    row = conn.execute("SELECT otp_secret, backup_codes FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row or not pyotp.TOTP(row["otp_secret"]).verify(code):
        return RedirectResponse(f"/admin?toter=1", status_code=303)
    conn = _db()
    conn.execute("UPDATE users SET otp_confirmed=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin?tot_ok=1&codes={row['backup_codes']}", status_code=303)


def _gen_backup_codes(n=10) -> str:
    return ",".join(secrets.token_hex(4).upper() for _ in range(n))


# ─────────────────────────────────────────────────────────────
# Blocklist-Routen
# ─────────────────────────────────────────────────────────────

@app.get("/installation/{inst_id}/blocklist", response_class=HTMLResponse)
async def blocklist_page(request: Request, inst_id: int):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")
    acc = get_access(user["user_id"], inst_id)
    if not acc["can_read"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    if not inst:
        return RedirectResponse("/dashboard")

    numbers = []
    error = ""
    try:
        token = starface_token(inst["url"], _decrypt(inst["auth_id"]), _decrypt(inst["auth_pass"]),
                               _decrypt(inst["client_secret"]), bool(inst["is_starface10"]))
        result = _xmlrpc(inst["url"], token, "ListGet")
        numbers = [v for v in result["values"] if v.strip()]
    except Exception as e:
        error = f"Verbindung fehlgeschlagen: {e}"

    return TEMPLATES.TemplateResponse("blocklist.html",
                                      {"request": request, "user": user, "inst": inst,
                                       "numbers": numbers, "error": error,
                                       "can_write": acc["can_write"]})


@app.post("/installation/{inst_id}/blocklist/add")
async def blocklist_add(request: Request, inst_id: int, numbers: str = Form(...)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")
    acc = get_access(user["user_id"], inst_id)
    if not acc["can_write"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    if not inst:
        return RedirectResponse("/dashboard")

    cleaned = [n.strip() for n in numbers.replace("\r", "").split("\n") if n.strip()]
    try:
        token = starface_token(inst["url"], _decrypt(inst["auth_id"]), _decrypt(inst["auth_pass"]),
                               _decrypt(inst["client_secret"]), bool(inst["is_starface10"]))
        for n in cleaned:
            _xmlrpc(inst["url"], token, "ListAdd", {"INPUT_NUMMERN": n})
        _log_event(inst_id, user["user_id"], "blocklist_add", f"{len(cleaned)} Nummern")
    except Exception as e:
        return RedirectResponse(f"/installation/{inst_id}/blocklist?error={quote(str(e))}",
                                status_code=303)
    return RedirectResponse(f"/installation/{inst_id}/blocklist?ok={len(cleaned)}",
                            status_code=303)


@app.post("/installation/{inst_id}/blocklist/remove")
async def blocklist_remove(request: Request, inst_id: int, number: str = Form(...)):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")
    acc = get_access(user["user_id"], inst_id)
    if not acc["can_write"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    if not inst:
        return RedirectResponse("/dashboard")

    try:
        token = starface_token(inst["url"], _decrypt(inst["auth_id"]), _decrypt(inst["auth_pass"]),
                               _decrypt(inst["client_secret"]), bool(inst["is_starface10"]))
        _xmlrpc(inst["url"], token, "ListRemove", {"INPUT_NUMMERN": number})
        _log_event(inst_id, user["user_id"], "blocklist_remove", number)
    except Exception as e:
        return RedirectResponse(f"/installation/{inst_id}/blocklist?error={quote(str(e))}",
                                status_code=303)
    return RedirectResponse(f"/installation/{inst_id}/blocklist?ok=1", status_code=303)


@app.get("/installation/{inst_id}/test")
async def installation_test(request: Request, inst_id: int):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")
    acc = get_access(user["user_id"], inst_id)
    if not acc["can_read"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    if not inst:
        return JSONResponse({"ok": False, "error": "unbekannt"})

    try:
        token = starface_token(inst["url"], _decrypt(inst["auth_id"]), _decrypt(inst["auth_pass"]),
                               _decrypt(inst["client_secret"]), bool(inst["is_starface10"]))
        result = _xmlrpc(inst["url"], token, "ListGet")
        n = len([v for v in result["values"] if v.strip()])
        return JSONResponse({"ok": True, "token_len": len(token), "entries": n})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "app": "STARFACE WebApp"})


@app.get("/version")
async def version():
    return JSONResponse({
        "app": "starface-webapp",
        "version": os.environ.get("APP_VERSION", "dev"),
        "build_date": os.environ.get("BUILD_DATE", "dev"),
    })
