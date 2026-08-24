"""STARFACE WebApp — Verwaltungs-Web-App für das Anrufblocker-Modul.

FastAPI + SQLite + Jinja2. Multi-User mit TOTP-2FA, Anlagenverwaltung
(mehrere STARFACE-Anlagen), Rufnummernlisten-Pflege via XML-RPC
(ListGet, ListAdd, ListRemove), Zugangsdaten verschlüsselt (Fernet).

Port: 8000 (Docker, Container-intern) → Host: 8895
"""

import hashlib
import os
import re
import secrets
import sqlite3
import time
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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
            is_starface10 INTEGER DEFAULT 1,
            oauth_access TEXT,
            oauth_refresh TEXT,
            oauth_expires INTEGER
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
        CREATE TABLE IF NOT EXISTS modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            version TEXT DEFAULT '',
            description TEXT DEFAULT '',
            file_hash TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_mtime TEXT DEFAULT '',
            app_version TEXT DEFAULT '',
            build_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Migration (v0.0.34+): bestehende DBs um Modul-Versionierungs-Spalten erweitern
    cols = [r[1] for r in conn.execute("PRAGMA table_info(modules)").fetchall()]
    for col, ddl in (("file_hash", "TEXT DEFAULT ''"),
                     ("file_size", "INTEGER DEFAULT 0"),
                     ("file_mtime", "TEXT DEFAULT ''"),
                     ("app_version", "TEXT DEFAULT ''"),
                     ("build_date", "TEXT DEFAULT ''")):
        if col not in cols:
            conn.execute(f"ALTER TABLE modules ADD COLUMN {col} {ddl}")
    # Migration (v0.0.42): OAuth-Token-Spalten an installations
    icols = [r[1] for r in conn.execute("PRAGMA table_info(installations)").fetchall()]
    for col, ddl in (("oauth_access", "TEXT DEFAULT ''"),
                     ("oauth_refresh", "TEXT DEFAULT ''"),
                     ("oauth_expires", "INTEGER DEFAULT 0")):
        if col not in icols:
            conn.execute(f"ALTER TABLE installations ADD COLUMN {col} {ddl}")
    conn.commit()
    conn.close()
    _scan_modules()


def _scan_modules():
    """Scannt app/modules/*.sfm und pflegt die DB (INSERT + UPDATE).

    Pro Datei werden Version/Beschreibung aus module-descriptor.xml sowie
    Datei-Hash, Größe, mtime und die ausliefernde WebApp-Version gespeichert —
    so ist auf der Modul-Seite erkennbar, wann/womit eine .sfm aktualisiert
    wurde (bestehende Zeilen werden bei Änderung GEUPDATED, nicht nur initial
    angelegt)."""
    modules_dir = os.path.join(os.path.dirname(__file__), "modules")
    if not os.path.isdir(modules_dir):
        return
    app_version = os.environ.get("APP_VERSION", "dev")
    build_date = os.environ.get("BUILD_DATE", "")
    conn = _db()
    for fname in sorted(os.listdir(modules_dir)):
        if not fname.endswith(".sfm"):
            continue
        name = os.path.splitext(fname)[0]
        path = os.path.join(modules_dir, fname)
        version, description = _module_meta(path)
        st = os.stat(path)
        file_hash = _file_md5(path)
        file_mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(st.st_mtime))
        row = conn.execute("SELECT id FROM modules WHERE name = ?", (name,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO modules (name, filename, version, description, "
                "file_hash, file_size, file_mtime, app_version, build_date) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (name, fname, version, description, file_hash, st.st_size,
                 file_mtime, app_version, build_date))
        else:
            conn.execute(
                "UPDATE modules SET filename=?, version=?, description=?, "
                "file_hash=?, file_size=?, file_mtime=?, app_version=?, "
                "build_date=? WHERE name=?",
                (fname, version, description, file_hash, st.st_size,
                 file_mtime, app_version, build_date, name))
    conn.commit()
    conn.close()


def _file_md5(path: str) -> str:
    """MD5-Hash einer Datei (stabil, ohne die Datei komplett in den RAM zu laden)."""
    import hashlib as _hl
    h = _hl.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _module_meta(path: str) -> tuple:
    """Liest version + description aus module-descriptor.xml einer .sfm-Datei."""
    import zipfile as _zip
    try:
        with _zip.ZipFile(path) as z:
            if "module-descriptor.xml" not in z.namelist():
                return "", ""
            desc = z.read("module-descriptor.xml").decode("utf-8", "ignore")
        ver = re.search(r'version="([^"]+)"', desc)
        dsc = re.search(r'<description>([^<]+)</description>', desc)
        return (ver.group(1) if ver else "", dsc.group(1).strip() if dsc else "")
    except Exception:
        return "", ""


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

def _ensure_url(url: str) -> str:
    """Sichert Protokoll: falls ohne http(s), versuche https:// zuerst."""
    url = url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def _legacy_token(url: str, auth_id: str, auth_pass: str) -> str:
    """Legacy v9-Token (v10 akzeptiert ihn ebenfalls)."""
    inner = hashlib.sha512(auth_pass.encode()).hexdigest()
    return auth_id + ":" + hashlib.sha512((auth_id + "*" + inner).encode()).hexdigest()


def starface_token(url: str, auth_id: str, auth_pass: str, client_secret: str,
                   is_starface10: bool,
                   oauth_access: str = "", oauth_refresh: str = "",
                   oauth_expires: int = 0) -> tuple:
    """Liefert (access_token, refresh_token, expires_ts) für XML-RPC.

    v10 (is_starface10=True): OAuth2 Password Grant gegen
      /auth/realms/pbx/oauth2/token (client_id=rest-client-headless).
      KEIN Legacy-Fallback (v9-Auth verschwindet mit Version 11)!
      Erst Basic-Auth-Header (Secret NUR im Header, client_id NICHT im Body),
      dann Form-Fields (client_id + client_secret im Body).
      Refresh-Token wird bei Ablauf automatisch verwendet.
    ≤9 (is_starface10=False): Legacy-Token Login:sha512(Login+"*"+sha512(PW)).
    """
    url = _ensure_url(url)
    if not is_starface10:
        inner = hashlib.sha512(auth_pass.encode()).hexdigest()
        token = auth_id + ":" + hashlib.sha512((auth_id + "*" + inner).encode()).hexdigest()
        return token, "", 0
    import base64
    import time

    def _oauth(data: dict, headers: dict) -> dict:
        r = httpx.post(f"{url}/auth/realms/pbx/oauth2/token", data=data,
                       headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()

    now = int(time.time())
    # 1) Gültiges Access-Token (5 min) wiederverwenden
    if oauth_access and oauth_expires and now < oauth_expires - 30:
        return oauth_access, oauth_refresh, oauth_expires
    # 2) Refresh-Token (6 h) → neuen Access holen
    if oauth_refresh:
        try:
            j = _oauth({
                "grant_type": "refresh_token",
                "refresh_token": oauth_refresh,
                "client_id": "rest-client-headless",
            }, {"Authorization": "Basic " + base64.b64encode(
                f"rest-client-headless:{client_secret}".encode()).decode()})
            return j.get("access_token", ""), j.get("refresh_token", oauth_refresh), \
                now + int(j.get("expires_in", 300))
        except Exception:
            pass  # Refresh fehlgeschlagen → neu einloggen
    # 3) Frischer Password Grant
    if not client_secret:
        raise RuntimeError(
            "Client-Secret fehlt in der WebApp! Unter Admin → Anlage bearbeiten "
            "das Client-Secret aus Admin-UI → Server → Status → REST-API eintragen.")
    errors = []
    # Variante A: Basic-Auth-Header (client_id NUR im Header, NICHT im Body)
    try:
        j = _oauth({
            "grant_type": "password",
            "scope": "login",
            "username": auth_id,
            "password": auth_pass,
        }, {"Authorization": "Basic " + base64.b64encode(
            f"rest-client-headless:{client_secret}".encode()).decode()})
        access = j.get("access_token", "")
        if not access:
            raise RuntimeError("kein access_token in Antwort")
        return access, j.get("refresh_token", ""), now + int(j.get("expires_in", 300))
    except Exception as e:
        errors.append(f"Basic-Auth: {e}")
    # Variante B: Form-Fields (client_id + client_secret im Body)
    try:
        j = _oauth({
            "client_id": "rest-client-headless",
            "client_secret": client_secret,
            "grant_type": "password",
            "scope": "login",
            "username": auth_id,
            "password": auth_pass,
        }, {})
        access = j.get("access_token", "")
        if not access:
            raise RuntimeError("kein access_token in Antwort")
        return access, j.get("refresh_token", ""), now + int(j.get("expires_in", 300))
    except Exception as e:
        errors.append(f"Form-Fields: {e}")
    raise RuntimeError(
        "OAuth2-Login fehlgeschlagen. Prüfen auf der Anlage: "
        "(1) Benutzer hat das Recht „API Zugriff mit OAuth Password Grant“ "
        "(Admin-UI → Benutzer → Rechte), "
        "(2) Client-Secret ist das AKTUELLE aus Admin-UI → Server → Status → REST-API, "
        "(3) Auth-ID ist die Login-ID (z. B. 0001) und Passwort korrekt. "
        + " | ".join(errors))


def _get_token(inst) -> str:
    """OAuth-Token für eine Installation holen und Refresh/Expiry persistieren."""
    access, refresh, expires = starface_token(
        inst["url"], _decrypt(inst["auth_id"]), _decrypt(inst["auth_pass"]),
        _decrypt(inst["client_secret"]), bool(inst["is_starface10"]),
        _decrypt(inst["oauth_access"]) if inst["oauth_access"] else "",
        _decrypt(inst["oauth_refresh"]) if inst["oauth_refresh"] else "",
        int(inst["oauth_expires"] or 0))
    conn = _db()
    conn.execute(
        "UPDATE installations SET oauth_access=?, oauth_refresh=?, oauth_expires=? WHERE id=?",
        (_encrypt(access) if access else inst["oauth_access"],
         _encrypt(refresh) if refresh else inst["oauth_refresh"],
         expires, inst["id"]))
    conn.commit()
    conn.close()
    return access


def _xmlrpc(url: str, token: str, method: str, params: dict = None) -> dict:
    """Führt einen XML-RPC-Call gegen die STARFACE aus."""
    url = _ensure_url(url)
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
        f"{url}/xml-rpc?de.vertico.starface.jwt={quote(token)}",
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

# Statische Dateien (Favicon, Icons, Logo)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# ─────────────────────────────────────────────────────────────
# Passwort ändern (selbst + Admin für andere)
# ─────────────────────────────────────────────────────────────

@app.get("/password", response_class=HTMLResponse)
async def password_page(request: Request):
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/")
    target_uid = request.query_params.get("uid")
    target_name = ""
    target_mode = False
    if target_uid and user["is_admin"] and int(target_uid) != user["user_id"]:
        # Admin öffnet Passwort-Formular für einen anderen User
        conn = _db()
        target = conn.execute("SELECT id, username FROM users WHERE id = ?", (int(target_uid),)).fetchone()
        conn.close()
        if target:
            target_mode = True
            target_name = target["username"]
    return TEMPLATES.TemplateResponse("password.html",
                                      {"request": request, "user": user,
                                       "target_uid": target_uid,
                                       "target_name": target_name,
                                       "target_mode": target_mode,
                                       "active": "password",
                                       "version": os.environ.get("APP_VERSION", "dev")})


@app.post("/password")
async def password_change(request: Request,
                          password: str = Form(""),
                          new_password: str = Form(...),
                          confirm: str = Form(...),
                          target_uid: int = Form(0)):
    """Passwort ändern. User ändert eigenes, Admin ändert beliebig
    (ohne das aktuelle Passwort des Ziel-Users zu kennen)."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/dashboard")

    if new_password != confirm:
        if user["is_admin"] and target_uid and target_uid != user["user_id"]:
            return RedirectResponse("/admin?pw_err=nomatch", status_code=303)
        return RedirectResponse("/dashboard?pw_err=nomatch", status_code=303)

    if user["is_admin"] and target_uid and target_uid != user["user_id"]:
        # Admin setzt Passwort eines anderen Users neu — kein aktuelles Passwort nötig.
        # Redirect zurück zum Admin-Bereich.
        target = target_uid
        if not new_password:
            return RedirectResponse("/admin?pw_err=empty", status_code=303)
        conn = _db()
        target_row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (target,)).fetchone()
        if not target_row:
            conn.close()
            return RedirectResponse("/admin?pw_err=notfound", status_code=303)
        new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, target))
        conn.commit()
        conn.close()
        return RedirectResponse("/admin?pw_ok=1", status_code=303)

    # Eigenes Passwort ändern (User oder Admin): aktuelles Passwort prüfen
    conn = _db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?", (user["user_id"],)).fetchone()
    conn.close()
    if not row or not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return RedirectResponse("/dashboard?pw_err=wrong", status_code=303)

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn = _db()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (new_hash, user["user_id"]))
    conn.commit()
    conn.close()
    return RedirectResponse("/dashboard?pw_ok=1", status_code=303)


# ─────────────────────────────────────────────────────────────
# Auth-Routen
# ─────────────────────────────────────────────────────────────

# TTL für den pending-AUTH-Token (5 Minuten, wie in Atlas)
PENDING_2FA_TTL = 300
# Maximum falsche Versuche
PENDING_2FA_MAX_ATTEMPTS = 5
# TOTP-Bereich (±30s, wie in Atlas)
OTP_WINDOW = 1

# In-Memory-Speicher für 2fa-pending-Token (entspricht Atlas app.state.pending_2fa)
pending_2fa: dict = {}


def _clean_pending():
    """Löscht abgelaufene pending-Tokens."""
    now = time.time()
    expired = [t for t, d in pending_2fa.items() if d["expires"] < now]
    for t in expired:
        pending_2fa.pop(t, None)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if verify_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/dashboard")
    return TEMPLATES.TemplateResponse("login.html", {"request": request})


@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Stufe 1: Benutzername + Passwort. Wenn TOTP aktiv → pending_token."""
    conn = _db()
    user = conn.execute(
        "SELECT id, username, is_admin, otp_secret, otp_confirmed, password_hash FROM users "
        "WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return JSONResponse(
            {"status": "error", "message": "Falsche Zugangsdaten"}, status_code=401)

    _clean_pending()

    if user["otp_secret"] and user["otp_confirmed"]:
        token = secrets.token_urlsafe(32)
        pending_2fa[token] = {
            "user_id": user["id"],
            "username": user["username"],
            "expires": time.time() + PENDING_2FA_TTL,
            "attempts": 0,
        }
        return JSONResponse({"status": "2fa_required", "pending_token": token})

    # Kein TOTP → sofort Session erstellen
    sid = create_session(user["id"])
    resp = JSONResponse({"status": "ok", "is_admin": bool(user["is_admin"])})
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_LIFETIME)
    return resp


@app.post("/api/2fa/verify")
async def login_2fa_verify(pending_token: str = Form(...), code: str = Form(...)):
    """Stufe 2: TOTP prüfen → Session erstellen."""
    _clean_pending()
    pending = pending_2fa.get(pending_token)
    if not pending or pending["expires"] < time.time():
        pending_2fa.pop(pending_token, None)
        return JSONResponse(
            {"status": "error", "message": "Anmeldung abgelaufen"}, status_code=401)

    conn = _db()
    user = conn.execute(
        "SELECT id, username, is_admin, otp_secret, otp_confirmed FROM users "
        "WHERE id = ?", (pending["user_id"],)).fetchone()
    conn.close()

    if not user or not user["otp_secret"] or not user["otp_confirmed"]:
        pending_2fa.pop(pending_token, None)
        return JSONResponse(
            {"status": "error", "message": "2FA ist nicht mehr aktiv"}, status_code=401)

    totp = pyotp.TOTP(user["otp_secret"])
    if not totp.verify(code, valid_window=OTP_WINDOW):
        pending["attempts"] += 1
        if pending["attempts"] >= PENDING_2FA_MAX_ATTEMPTS:
            pending_2fa.pop(pending_token, None)
            return JSONResponse(
                {"status": "error", "message": "Zu viele Fehlversuche"}, status_code=401)
        return JSONResponse({"status": "error", "message": "Code ungültig"}, status_code=401)

    pending_2fa.pop(pending_token, None)
    sid = create_session(user["id"])
    resp = JSONResponse({"status": "ok", "is_admin": bool(user["is_admin"])})
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_LIFETIME)
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
                                      {"request": request, "user": user,
                                       "installations": rows,
                                       "active": "dashboard",
                                       "version": os.environ.get("APP_VERSION", "dev")})


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
                                       "active": "admin",
                                       "OTP_ISSUER": "STARFACE-WebApp",
                                       "version": os.environ.get("APP_VERSION", "dev")})


@app.get("/sw.js")
async def service_worker():
    """Service Worker im Root-Scope (PWA-Offline-Assets)."""
    return FileResponse(Path(__file__).parent / "static" / "sw.js",
                        media_type="application/javascript")


@app.get("/admin/modules", response_class=HTMLResponse)
async def admin_modules_page(request: Request):
    """Admin-Seite: Liste aller .sfm-Module mit Download-Button."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    modules = conn.execute("SELECT * FROM modules ORDER BY name").fetchall()
    conn.close()
    return TEMPLATES.TemplateResponse("modules.html",
                                      {"request": request, "user": user,
                                       "modules": modules,
                                       "active": "modules",
                                       "version": os.environ.get("APP_VERSION", "dev")})


@app.get("/admin/modules/{module_id}/download")
async def admin_module_download(request: Request, module_id: int):
    """Download einer .sfm-Datei (nur Admins). Dateiname kommt aus der DB
    (Whitelist), nie direkt aus der URL → kein Pfad-Traversal."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")

    conn = _db()
    mod = conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
    conn.close()
    if not mod:
        return RedirectResponse("/admin/modules", status_code=303)

    modules_dir = Path(__file__).parent / "modules"
    file_path = (modules_dir / mod["filename"]).resolve()
    # Sicherheit: Datei muss wirklich im modules-Verzeichnis liegen
    if not file_path.is_file() or modules_dir.resolve() not in file_path.parents:
        return RedirectResponse("/admin/modules?err=missing", status_code=303)

    # Eindeutiger Download-Name mit Datei-Hash (v0.0.35): verhindert, dass im
    # Download-Ordner eine gleichnamige alte .sfm importiert wird (iOS Safari
    # ergänzt sonst " (1)" oder behält die alte Datei gleichen Namens).
    dl_name = mod["filename"]
    file_hash = mod["file_hash"] or ""
    if file_hash:
        base = os.path.splitext(mod["filename"])[0]
        dl_name = f"{base}_{file_hash[:8]}.sfm"

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=dl_name,
        # v0.0.34 Router/NPM cached Download trotz no-store — Inkognito
        #  arbeitete. Starke Header + Template ändert Download-URL mit
        # ?cache=<Hash> für URL-Level Cache-Busting (v0.0.36).
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        })


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


@app.get("/admin/installations/{inst_id}/edit", response_class=HTMLResponse)
async def admin_installation_edit_page(request: Request, inst_id: int):
    """Bearbeitungsseite für eine Anlage."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    if not inst:
        conn.close()
        return RedirectResponse("/admin", status_code=303)
    # Daten entschlüsseln für die Form (zum Bearbeiten)
    inst_data = dict(inst)
    inst_data["auth_id"] = _decrypt(inst["auth_id"])
    inst_data["auth_pass"] = _decrypt(inst["auth_pass"])
    inst_data["client_secret"] = _decrypt(inst["client_secret"])
    conn.close()
    return TEMPLATES.TemplateResponse("edit_installation.html",
        {"request": request, "user": user, "inst": inst_data,
         "active": "admin", "version": os.environ.get("APP_VERSION", "dev")})


@app.post("/admin/installations/{inst_id}")
async def admin_installation_update(request: Request, inst_id: int,
                                    name: str = Form(...),
                                    url: str = Form(...),
                                    auth_id: str = Form(""),
                                    auth_pass: str = Form(""),
                                    client_secret: str = Form(""),
                                    is_starface10: int = Form(1)):
    """Update einer bestehenden Anlage."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")
    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    if not inst:
        conn.close()
        return RedirectResponse("/admin", status_code=303)
    # Nur aktualisieren wenn Feld nicht leer
    new_auth_id = _encrypt(auth_id) if auth_id else inst["auth_id"]
    new_auth_pass = _encrypt(auth_pass) if auth_pass else inst["auth_pass"]
    new_client_secret = _encrypt(client_secret) if client_secret else inst["client_secret"]
    conn.execute(
        "UPDATE installations SET name=?, url=?, auth_id=?, auth_pass=?, client_secret=?, is_starface10=? WHERE id=?",
        (name, url, new_auth_id, new_auth_pass, new_client_secret, bool(is_starface10), inst_id))
    conn.commit()
    conn.close()
    _log_event(inst_id, user["user_id"], "installation_update", name)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/installations/{inst_id}/test-conn")
async def admin_installation_test_conn(request: Request, inst_id: int):
    """Testet Verbindung + Token zu einer STARFACE-Anlage (AJAX, JSON)."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return JSONResponse({"ok": False, "message": "Nicht autorisiert"}, status_code=403)
    conn = _db()
    inst = conn.execute("SELECT * FROM installations WHERE id=?", (inst_id,)).fetchone()
    conn.close()
    if not inst:
        return JSONResponse({"ok": False, "message": "Installation nicht gefunden"})
    try:
        url = inst["url"]
        token = _get_token(inst)
        result = _xmlrpc(url, token, "ListGet")
        count = len(result.get("values", []))
        return JSONResponse({"ok": True, "message": f"Verbunden, {count} Nummern in der Blocklist"})
    except Exception as e:
        return JSONResponse({"ok": False, "message": f"Verbindung fehlgeschlagen: {e}"})


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


@app.post("/admin/users/{uid}/role")
async def admin_user_role(request: Request, uid: int, is_admin: int = Form(0)):
    """Adminrolle vergeben/entziehen — der letzte verbleibende Admin 
    kann nie entlassen werden (Schutz wie in Atlas)."""
    user = verify_session(request.cookies.get(SESSION_COOKIE))
    if not user or not user["is_admin"]:
        return RedirectResponse("/dashboard")

    want_admin = 1 if is_admin == 1 else 0
    conn = _db()
    row = conn.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        conn.close()
        return RedirectResponse("/admin?role_err=notfound", status_code=303)
    current = row["is_admin"]
    if want_admin == current:
        conn.close()
        return RedirectResponse("/admin", status_code=303)

    if want_admin == 0:
        # Schutz: Es muss immer mindestens ein Admin aktiv bleiben (wie Atlas)
        admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
        if admin_count <= 1:
            conn.close()
            return RedirectResponse("/admin?role_err=lastadmin", status_code=303)

    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (want_admin, uid))
    conn.commit()
    conn.close()
    _log_event(None, user["user_id"], "user_role", f"{row['username']}->{'admin' if want_admin else 'user'}")
    return RedirectResponse("/admin", status_code=303)


# ─────────────────────────────────────────────────────────────
# 2FA (TOTP) — Admin-Bereich
# ─────────────────────────────────────────────────────────────

@app.get("/admin/users/{uid}/totp-setup")
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
                                       "secret": secret, "qr_data_uri": qr_data_uri,
                                       "version": os.environ.get("APP_VERSION", "dev")})


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
        token = _get_token(inst)
        result = _xmlrpc(inst["url"], token, "ListGet")
        numbers = [v for v in result["values"] if v.strip()]
    except Exception as e:
        error = f"Verbindung fehlgeschlagen: {e}"

    return TEMPLATES.TemplateResponse("blocklist.html",
                                      {"request": request, "user": user, "inst": inst,
                                       "numbers": numbers, "error": error,
                                       "can_write": acc["can_write"],
                                       "active": "blocklist",
                                       "version": os.environ.get("APP_VERSION", "dev")})


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
        token = _get_token(inst)
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
        token = _get_token(inst)
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
        token = _get_token(inst)
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
