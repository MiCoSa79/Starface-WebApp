#!/usr/bin/env python3
"""E2E-Smoke-Test: Admin-Aufteilung F62 (Startseite = Anlagen).

Prüft: / dashboard-frei (Anlagen-Startseite), /admin + /dashboard -> Redirect /,
4 Seiten unter /benutzer, /rechte, /grundeinstellungen (Admin-only),
User-Sicht der Startseite (nur eigene Anlagen, kein Formular),
aktive Nav-Marker, Redirect-Ziele der POST-Handler.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))

_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_aufteilung_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet  # noqa: E402
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "pw123"
os.environ["APP_VERSION"] = "v1.0.54-test"

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def login(c, u, p):
    r = c.post("/api/login", data={"username": u, "password": p})
    return r.status_code == 200 and r.json().get("status") == "ok"


with TestClient(main.app) as c:
    c.follow_redirects = False  # Starlette 0.27

    # ── 1) Ohne Login ──────────────────────────────────────────
    r = c.get("/")
    check("Ohne Login: / -> Login-Seite", r.status_code == 200 and 'name="password"' in r.text, str(r.status_code))
    r = c.get("/dashboard")
    check("Ohne Login: /dashboard -> Redirect /", r.status_code in (303, 307) and r.headers.get("location", "").rstrip("/") == "", f"{r.status_code} {r.headers.get('location')}")
    r = c.get("/admin")
    check("Ohne Login: /admin -> Redirect /", r.status_code in (303, 307) and r.headers.get("location", "").rstrip("/") == "", f"{r.status_code} {r.headers.get('location')}")
    r = c.get("/benutzer")
    check("Ohne Login: /benutzer -> Redirect /", r.status_code in (303, 307), str(r.status_code))
    r = c.get("/rechte")
    check("Ohne Login: /rechte -> Redirect /", r.status_code in (303, 307), str(r.status_code))
    r = c.get("/grundeinstellungen")
    check("Ohne Login: /grundeinstellungen -> Redirect /", r.status_code in (303, 307), str(r.status_code))

    # ── 2) Admin: 4 Seiten + Nav ───────────────────────────────
    check("Login admin", login(c, "admin", "pw123"))
    r = c.get("/")
    check("GET / -> 200 (Startseite)", r.status_code == 200, str(r.status_code))
    body = r.text
    check("Startseite = Anlagen: Formular + Tabelle + Counter", "Anlage hinzufügen" in body and 'id="tbl-inst"' in body and "von" in body)
    check("Nav: KEIN Dashboard-Link", 'href="/dashboard"' not in body)
    check("Nav: Logo-Link (Anlagen) aktiv/verlinkt", 'class="logo-link"' in body and 'href="/"' in body)
    check("Nav: Administration-Dropdown", "<summary>Administration" in body)
    for route, marker in (("/benutzer", "tbl-users"), ("/rechte", "tbl-access"), ("/grundeinstellungen", "name=\"grafana_base_url\"")):
        r = c.get(route)
        check(f"GET {route} -> 200 (Admin)", r.status_code == 200, str(r.status_code))
        check(f"{route} rendert Bereich", marker in r.text, "(Marker fehlt)")
    # Aktive Marker
    r = c.get("/benutzer")
    check("Nav: /benutzer aktiv (Admin-Dropdown)", 'class="drop active"' in r.text or 'active</a>' in r.text.replace('">Benutzer', ' active">Benutzer'), "")

    # ── 3) Redirect-Verträge POST→Seite ────────────────────────
    r = c.post("/admin/installations", data={"name": "Testanlage A", "url": "https://nfr-test.starface-cloud.com",
                                             "auth_id": "u", "auth_pass": "p", "is_starface10": "1"})
    check("POST Anlage -> Redirect /", r.status_code in (303, 307) and r.headers.get("location", "").rstrip("/") == "", f"{r.status_code} {r.headers.get('location')}")
    r = c.post("/admin/users", data={"username": "bob", "password": "pw456", "is_admin": "0"})
    check("POST Benutzer -> Redirect /benutzer", r.status_code in (303, 307) and "/benutzer" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.post("/admin/access", data={"user_id": "2", "installation_id": "1", "can_read": "1"})
    check("POST Recht -> Redirect /rechte", r.status_code in (303, 307) and "/rechte" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.post("/admin/settings", data={"module_update_base_url": ""})
    check("POST Einstellung -> Redirect /grundeinstellungen?set_ok=1", r.status_code in (303, 307) and "/grundeinstellungen" in r.headers.get("location", "") and "set_ok=1" in r.headers.get("location", ""), r.headers.get("location", ""))

    # ── 4) User-Sicht ──────────────────────────────────────────
    check("Login bob", login(c, "bob", "pw456"))
    r = c.get("/benutzer")
    check("Bob: /benutzer -> Redirect /", r.status_code in (303, 307), str(r.status_code))
    r = c.get("/grundeinstellungen")
    check("Bob: /grundeinstellungen -> Redirect /", r.status_code in (303, 307), str(r.status_code))
    r = c.get("/")
    body = r.text
    check("Bob: Startseite zeigt nur eigene Anlage", "Testanlage A" in body, "")
    check("Bob: KEIN Anlegen-Formular", "Anlage hinzufügen" not in body)
    check("Bob: Grafana-Link + Blocklist in Zeile", 'class="grafana-dl"' in body and "/blocklist" in body)
    check("Bob: KEIN Administration-Dropdown", "<summary>Administration" not in body)

print()
if FAIL:
    print(f"❌ {len(FAIL)} FAIL(s): {', '.join(FAIL)}")
    sys.exit(1)
print("✅ Alle Checks bestanden.")
