"""E2E-Test „Mein Konto“ (Menü-Umbau, Selbstbedienung).

Geprüft:
1. Nav (base.html): Admin sieht „Administration“-Dropdown + „Mein Konto“;
   Normaluser sieht KEIN Administration-Dropdown und keinen Wiki-Link.
2. GET /konto: 200, Marker (Mein Konto / Passwort ändern / 2FA / Passkeys),
   ohne Login Redirect.
3. GET /password: ohne uid -> Redirect /konto#sicherheit; mit uid (Admin,
   Fremduser) -> 200 im Admin-Reset-Modus.
4. POST /konto/password: falsches aktuelles PW -> pw_err=wrong; korrekt ->
   pw_ok=1 und Login mit neuem Passwort funktioniert.
5. 2FA-Self-Service: setup (Re-Auth) -> QR+Secret; confirm falscher Code ->
   fa_err=code; korrekter Code -> fa=done + Backup-Codes einmalig; zweiter
   GET -> Codes weg (einmalig); disable (Re-Auth) -> fa=off, DB leer.
6. Passkeys: /api/passkey/list liefert eigene Keys; /konto zeigt Tabelle.

Aufruf: .venv/bin/python tmp_tests/konto_e2e.py
"""
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/konto_e2e/test.db"
if os.path.exists(os.path.dirname(DB)):
    shutil.rmtree(os.path.dirname(DB))
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "WEBAUTHN_PASSWORDLOGIN"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

import bcrypt
import pyotp

app_main.init_db()
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("axel", bcrypt.hashpw(b"pw456", bcrypt.gensalt()).decode(), 0))
conn.commit()
conn.close()

c = TestClient(app_main.app)
c.follow_redirects = False  # Starlette 0.27 hartkodiert True

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def login(u, p):
    r = c.post("/api/login", data={"username": u, "password": p})
    return r.status_code == 200 and r.json().get("status") == "ok"


# ── 1) Auth-Guards ─────────────────────────────────────────────
r = c.get("/konto")
check("GET /konto ohne Login -> Redirect", r.status_code == 303, str(r.status_code))

# ── 2) Admin-Login, Nav, Seiten ────────────────────────────────
check("Login admin", login("admin", "pw123"))
r = c.get("/dashboard")
check("GET /dashboard -> 200", r.status_code == 200, str(r.status_code))
nav_admin = r.text
check("Admin-Nav zeigt Administration-Dropdown", "<summary>Administration" in nav_admin)
check("Admin-Nav zeigt Benutzer-Dropdown", "Mein Konto" in nav_admin)
check("Admin-Nav hat keinen flachen Passwort-Link mehr",
      'href="/password"' not in nav_admin)

r = c.get("/konto")
check("GET /konto (Admin) -> 200", r.status_code == 200, str(r.status_code))
for marker in ("Mein Konto", "Passwort ändern", "Zwei-Faktor-Authentifizierung", "🔑 Passkeys", "Profil"):
    check(f"konto.html Marker '{marker}'", marker in r.text)

r = c.get("/password")
check("GET /password ohne uid -> Redirect /konto#sicherheit",
      r.status_code == 303 and "/konto#sicherheit" in r.headers.get("location", ""),
      f"{r.status_code} {r.headers.get('location')}")

r = c.get("/password", params={"uid": "2"})  # Admin-Reset für axel (Fremduser)
check("GET /password?uid=2 (Admin-Reset) -> 200",
      r.status_code == 200 and "Passwort zurücksetzen" in r.text,
      str(r.status_code))

# ── 3) Passwort Self-Service ───────────────────────────────────
r = c.post("/konto/password", data={"password": "falsch", "new_password": "neu123", "confirm": "neu123"})
check("Konto-PW: falsches altes PW -> pw_err=wrong",
      r.status_code == 303 and "pw_err=wrong" in r.headers.get("location", ""),
      f"{r.status_code} {r.headers.get('location')}")
r = c.post("/konto/password", data={"password": "falsch", "new_password": "a", "confirm": "b"})
check("Konto-PW: nomatch -> pw_err=nomatch",
      r.status_code == 303 and "pw_err=nomatch" in r.headers.get("location", ""),
      str(r.status_code))
r = c.post("/konto/password", data={"password": "pw123", "new_password": "neu123", "confirm": "neu123"})
check("Konto-PW: korrekt -> pw_ok=1",
      r.status_code == 303 and "pw_ok=1" in r.headers.get("location", ""),
      f"{r.status_code} {r.headers.get('location')}")
conn = sqlite3.connect(DB)
row = conn.execute("SELECT password_hash FROM users WHERE id=1").fetchone()
conn.close()
check("Konto-PW: Hash in DB geändert",
      row and bcrypt.checkpw(b"neu123", row[0].encode()))

# ── 4) 2FA Self-Service ────────────────────────────────────────
conn = sqlite3.connect(DB)
row = conn.execute("SELECT otp_secret, otp_confirmed FROM users WHERE id=1").fetchone()
conn.close()
check("2FA initial inaktiv", row[0] is None and row[1] == 0)

r = c.post("/konto/2fa/setup", data={"password": "falsch"})
check("2FA setup ohne korrektes PW -> fa_err=pw",
      r.status_code == 303 and "fa_err=pw" in r.headers.get("location", ""),
      r.headers.get("location"))
r = c.post("/konto/2fa/setup", data={"password": "neu123"})
check("2FA setup -> fa=setup",
      r.status_code == 303 and "fa=setup" in r.headers.get("location", ""),
      r.headers.get("location"))
r = c.get("/konto")
check("2FA: QR + Secret nach setup sichtbar",
      "data:image/png;base64," in r.text and "Geheimer Schlüssel:" in r.text)
conn = sqlite3.connect(DB)
row = conn.execute("SELECT otp_secret, otp_confirmed, backup_codes FROM users WHERE id=1").fetchone()
conn.close()
secret = row[0]
check("2FA: Secret gesetzt, unbestätigt, Backup-Codes generiert",
      bool(secret) and row[1] == 0 and row[2] and len(row[2].split(",")) == 10)

r = c.post("/konto/2fa/confirm", data={"code": "000000"})
check("2FA confirm falscher Code -> fa_err=code",
      r.status_code == 303 and "fa_err=code" in r.headers.get("location", ""),
      r.headers.get("location"))
r = c.post("/konto/2fa/confirm", data={"code": pyotp.TOTP(secret).now()})
check("2FA confirm korrekter Code -> fa=done",
      r.status_code == 303 and "fa=done" in r.headers.get("location", ""),
      r.headers.get("location"))
r = c.get("/konto")
check("2FA: Backup-Codes einmalig angezeigt", r.text.count('class="codes"') == 1)
r = c.get("/konto")
check("2FA: Backup-Codes beim 2. Aufruf weg (einmalig)", r.text.count('class="codes"') == 0)
r = c.get("/konto")
check("2FA: Status aktiv nach confirm", "status on\">aktiv" in r.text or "2FA ist derzeit <span class=\"status on\">aktiv" in r.text)

r = c.post("/konto/2fa/disable", data={"password": "falsch"})
check("2FA disable ohne korrektes PW -> fa_err=pw",
      r.status_code == 303 and "fa_err=pw" in r.headers.get("location", ""),
      r.headers.get("location"))
r = c.post("/konto/2fa/disable", data={"password": "neu123"})
check("2FA disable -> fa=off",
      r.status_code == 303 and "fa=off" in r.headers.get("location", ""),
      r.headers.get("location"))
conn = sqlite3.connect(DB)
row = conn.execute("SELECT otp_secret, otp_confirmed, backup_codes FROM users WHERE id=1").fetchone()
conn.close()
check("2FA: deaktiviert = alles leer", row[0] is None and row[1] == 0 and row[2] is None)

# ── 5) Login mit neuem Passwort ────────────────────────────────
check("Login mit neuem Passwort", login("admin", "neu123"))

# ── 6) Normaluser: Nav ohne Administration ─────────────────────
check("Login axel", login("axel", "pw456"))
r = c.get("/dashboard")
check("Normaluser-Dashboard -> 200", r.status_code == 200, str(r.status_code))
check("Normaluser sieht KEIN Administration", "<summary>Administration" not in r.text)
check("Normaluser sieht KEINEN Wiki-Link", ">Wiki<" not in r.text)
check("Normaluser sieht Mein Konto", "Mein Konto" in r.text)
r = c.get("/konto")
check("Normaluser /konto -> 200", r.status_code == 200, str(r.status_code))
check("Normaluser-Rolle 'Benutzer'", ">Benutzer<" in r.text)
check("Passkeys-Liste leer (Marker)", "Noch keine Passkeys registriert." in r.text)
r = c.get("/api/passkey/list")
check("/api/passkey/list liefert []", r.status_code == 200 and r.json() == {"passkeys": []},
      r.text[:120])
r = c.get("/password", params={"uid": "1"})
check("Normaluser darf /password?uid=1 NICHT (Redirect /konto)",
      r.status_code == 303 and "/konto" in r.headers.get("location", ""),
      f"{r.status_code} {r.headers.get('location')}")

print()
print("── Nachprüfung Admin-2FA-Ruhe (zuvor: Self-Service-Flow) ──")
check("Re-Login admin", login("admin", "neu123"))
r = c.get("/admin/users/1/totp-setup")
check("Admin-2FA-Route weiterhin ok (fremdes Setup)", r.status_code == 200 and "2FA" in r.text, str(r.status_code))

print()
if FAIL:
    print(f"❌ {len(FAIL)} FAIL(s): {', '.join(FAIL)}")
    sys.exit(1)
print("✅ Alle Checks bestanden.")
