"""E2E-Tests Passkeys / WebAuthn (F58, Option B mit C-Schalter).

Geprüft werden:
1. Ohne WEBAUTHN-Konfiguration: options -> 503, Login-Seite ohne Passkey-UI
2. Mit Konfiguration: options-Format (challenge/rpId/userVerification) + Login-UI
3. register/options ohne Session -> 401
4. Happy-Path: Registrierung (Fake-Attestation) -> Liste -> Passkey-Login
   (Fake-Assertion) -> Session-Cookie gesetzt
5. Replay-Schutz: gleiche Assertion-Nutzung -> 401 (counter-Monotonie)
6. C-Schalter: PASSWORD_LOGIN_ENABLED=False -> /api/login 403, Login-JS hidden

Aufruf: python3 tmp_tests/passkeys_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.dirname(__file__))
import webauthn_fake as wf  # noqa: E402

DB = "/tmp/passkeys_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ["WEBAUTHN_RP_ID"] = "webapp.example"
os.environ["WEBAUTHN_ORIGIN"] = "https://webapp.example"
os.environ["WEBAUTHN_RP_NAME"] = "STARFACE WebApp Test"
os.environ.pop("WEBAUTHN_PASSWORDLOGIN", None)
os.environ.pop("FERNET_KEY", None)

import sqlite3  # noqa: E402
import main as app_main  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

app_main.init_db()
conn = sqlite3.connect(DB)
import bcrypt  # noqa: E402
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.commit()
conn.close()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200 and r.json()["status"] == "ok"

FAIL = []
def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)

# ── 1) Ohne Konfiguration: 503 + keine Passkey-UI ─────────────────────
app_main.WEBAUTHN_RP_ID = ""
app_main.WEBAUTHN_ORIGIN = ""
r = c.post("/api/passkey/login/options")
check("1: options ohne Konfiguration -> 503", r.status_code == 503, str(r.status_code))
c.cookies.clear()  # Login-Seite ohne Session rendern (302-Redirect vermeiden)
html = c.get("/").text
check("1: Login-Seite ohne Passkey-UI (JS-Flag false)", "const __pkEnabled = false;" in html,
      "passkeyCard vorhanden, Flag erwartet false")
app_main.WEBAUTHN_RP_ID = "webapp.example"
app_main.WEBAUTHN_ORIGIN = "https://webapp.example"

# ── 2) Mit Konfiguration: Options-Format + Login-UI ───────────────────
r = c.post("/api/passkey/login/options")
j = r.json()
check("2: options -> 200", r.status_code == 200, str(r.status_code))
check("2: challenge/rpId/userVerification vorhanden",
      j.get("challenge") and j.get("rpId") == "webapp.example" and j.get("userVerification") == "preferred",
      str(sorted(j.keys())))
c.cookies.clear()  # Login-Seite ohne Session rendern
html = c.get("/").text
check("2: Login-Seite mit Passkey-UI", "passkeyCard" in html and "passkeyBtn" in html)
check("2: C-Schalter-Signal im JS (Passwort sichtbar)", "const __pkPassword = true;" in html)

# ── 3) Registrierung ohne Session -> 401 ──────────────────────────────
c.cookies.clear()
r = c.post("/api/passkey/register/options")
check("3: register/options ohne Session -> 401", r.status_code == 401, str(r.status_code))

# ── 4) Happy-Path: Registrierung + Passkey-Login ──────────────────────
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200
r = c.post("/api/passkey/register/options")
j = r.json()
check("4: register/options -> 200", r.status_code == 200, str(r.status_code))
key = wf.new_ec_key()
cd, att, cred_id, pk_cbor = wf.register_attestation("webapp.example", "https://webapp.example",
                                                    j["challenge"], key)
cred = {
    "id": wf._b64u(cred_id), "rawId": wf._b64u(cred_id), "type": "public-key",
    "response": {"clientDataJSON": cd, "attestationObject": att},
}
r = c.post("/api/passkey/register/verify", json={"credential": cred, "device_name": "Test-Gerät"})
check("4: register/verify -> ok", r.status_code == 200 and r.json().get("status") == "ok",
      f"{r.status_code} {r.text[:120]}")
r = c.get("/api/passkey/list")
check("4: Liste enthält 1 Gerät", r.status_code == 200 and len(r.json().get("passkeys") or []) == 1, r.text[:120])

c.cookies.clear()
r = c.post("/api/passkey/login/options")
j = r.json()
assertion = wf.login_assertion("webapp.example", "https://webapp.example", j["challenge"], key)
assertion_cred = {
    "id": wf._b64u(cred_id), "rawId": wf._b64u(cred_id), "type": "public-key",
    "response": assertion,
}
r = c.post("/api/passkey/login/verify", json={"credential": assertion_cred})
check("4: Passkey-Login -> ok + Session-Cookie", r.status_code == 200 and r.json().get("status") == "ok"
      and c.cookies.get(app_main.SESSION_COOKIE), f"{r.status_code} {r.text[:120]}")

# ── 5) Replay-Schutz: gleicher sign_count erneut -> 401 ───────────────
c.cookies.clear()
r = c.post("/api/passkey/login/options")
j = r.json()
assertion2 = wf.login_assertion("webapp.example", "https://webapp.example", j["challenge"], key, sign_count=1)
r = c.post("/api/passkey/login/verify", json={"credential": {
    "id": wf._b64u(cred_id), "rawId": wf._b64u(cred_id), "type": "public-key",
    "response": assertion2}})
check("5: Replay (gleicher counter) -> 401", r.status_code == 401, f"{r.status_code} {r.text[:120]}")

# ── 6) C-Schalter: Passwort-Login aus ─────────────────────────────────
app_main.PASSWORD_LOGIN_ENABLED = False
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
check("6: Passwort-Login deaktiviert -> 403", r.status_code == 403, str(r.status_code))
html = c.get("/").text
check("6: Login-JS signalisiert Passwort hidden", "const __pkPassword = false;" in html)
app_main.PASSWORD_LOGIN_ENABLED = True

# ── 7) Bitwarden-Stil: Signatur bereits DER (70 B) → Login muss klappen ──
c.cookies.clear()
r = c.post("/api/passkey/login/options")
j = r.json()
assertion3 = wf.login_assertion("webapp.example", "https://webapp.example", j["challenge"], key, sign_count=2)
assertion3["signature"] = app_main._raw_to_der_b64(assertion3["signature"])  # RAW→DER, wie Bitwarden liefert
r = c.post("/api/passkey/login/verify", json={"credential": {
    "id": wf._b64u(cred_id), "rawId": wf._b64u(cred_id), "type": "public-key",
    "response": assertion3}})
check("7: Login mit DER-Signatur (Bitwarden-Stil) -> ok", r.status_code == 200 and r.json().get("status") == "ok",
      f"{r.status_code} {r.text[:120]}")

print()
print("ERGEBNIS:", f"{len(FAIL)} FAIL" if FAIL else "ALLE PASSKEY-TESTS OK")
sys.exit(1 if FAIL else 0)
