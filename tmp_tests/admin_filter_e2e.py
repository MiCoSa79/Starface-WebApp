#!/usr/bin/env python3
"""E2E-Smoke-Test: Admin-Tabellen-Filter + Collapse (HTML-Struktur, F62-Split).

Seit F62 (Admin-Aufteilung) liegen die Bereiche auf eigenen Seiten:
/ = Anlagen (Startseite), /benutzer, /rechte (+ /grundeinstellungen).
Die JS-Logik selbst wird durch tmp_tests/admin_filter_cdp.mjs gegen echtes
Chrome getestet; dieser Test sichert die gerenderte Struktur über den
FastAPI-Stack (Filterfelder, Dropdowns, Collapse-Buttons, Counter).
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.join(REPO, "tmp_tests"))

_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_test_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet  # noqa: E402
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["APP_VERSION"] = "v1.0.53-test"

import main  # noqa: E402
from fake_starface import FAKE, start_fake  # noqa: E402

FAKE_URL = start_fake()

ok = 0


def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        sys.exit(1)


from fastapi.testclient import TestClient  # noqa: E402

with TestClient(main.app) as c:
    c.follow_redirects = False  # Starlette 0.27

    # Login
    r = c.post("/api/login", data={"username": "admin", "password": "testpass123"})
    check("Login", r.json().get("status") == "ok")
    check("Session-Cookie", bool(c.cookies.get("sf_webapp_session")))

    # Anlage anlegen (2x für Counter-Test)
    for i in range(2):
        r = c.post("/admin/installations", data={
            "name": f"FilterTest {i+1}",
            "url": FAKE_URL,
            "auth_id": "rest-client-headless",
            "auth_pass": "x",
            "client_secret": "y",
            "module_instance_name": "CallBlocker",
            "is_starface10": 1 if i == 0 else 0,
        })
        check(f"Anlage {i+1} angelegt", r.status_code in (200, 303))
    # Benutzer anlegen
    r = c.post("/admin/users", data={"username": "filter.tester", "password": "pw12345", "is_admin": "0"})
    check("Benutzer angelegt", r.status_code in (200, 303))

    html_inst = c.get("/anlagen").text     # Anlagen-Übersicht (seit F64 eigene Seite)
    html_users = c.get("/benutzer").text
    html_access = c.get("/rechte").text
    html_settings = c.get("/grundeinstellungen").text

    # ── Struktur-Checks je Bereich ───────────────────────────────
    check("Anlagen-Wrap", 'class="tbl-wrap" data-wrap="inst"' in html_inst)
    check("Benutzer-Wrap", 'data-wrap="users"' in html_users)
    check("Rechte-Wrap", 'data-wrap="access"' in html_access)

    btns = re.findall(r"data-collapse=\"(\w+)\"", html_inst + html_users + html_access)
    check("3 Collapse-Buttons (inst/users/access)", btns == ["inst", "users", "access"], str(btns))

    check("Chevron-SVG", (html_inst + html_users).count("<svg") >= 2 and 'class="chev"' in (html_inst + html_users))
    check("Grundeinstellungen: kein Collapse nötig", "data-collapse" not in html_settings)

    # Anlagen: Name (col 1), URL (col 2), Version (col 3) — nur auf /
    check("Filter Name", 'data-filter="tbl-inst" data-col="1"' in html_inst)
    check("Filter URL", 'data-filter="tbl-inst" data-col="2"' in html_inst)
    check("Filter Version-Dropdown", 'data-filter="tbl-inst" data-col="3"' in html_inst)
    check("Dropdown-Placeholder", "Alle Versionen" in html_inst)
    # Benutzer + Rechte
    check("Filter Benutzer", 'data-filter="tbl-users" data-col="1" data-minlen="3"' in html_users)
    check("Filter Rechte-User", 'data-filter="tbl-access" data-col="0" data-minlen="3"' in html_access)
    check("Filter Rechte-Anlage", 'data-filter="tbl-access" data-col="1"' in html_access)
    # Counter mit Jinja-Werten
    m = re.search(r'data-count="inst">(\d+) von (\d+)<', html_inst)
    check("Counter Anlagen", m and m.group(1) == "2" and m.group(2) == "2", html_inst[m.start():m.start()+60] if m else "kein Counter")
    m = re.search(r'data-count="users">(\d+) von (\d+)<', html_users)
    check("Counter Benutzer (Admin + tester)", m and m.group(1) == "2" and m.group(2) == "2", "kein Counter" if not m else "")
    # JS-Engine als externe Datei eingebunden (static/admin.js, F62)
    js_src = open(os.path.join(REPO, "app/static/admin.js"), encoding="utf-8").read()
    check("JS initCollapse in admin.js", "function initCollapse" in js_src and "function initTableFilters" in js_src)
    check("JS initComboboxes in admin.js", "function initComboboxes" in js_src)
    check("admin.js eingebunden", html_inst.count('src="/static/admin.js?v=') >= 1)
    for name, page in (("Startseite", html_inst), ("Benutzer", html_users), ("Rechte", html_access), ("Einstellungen", html_settings)):
        check(f"keine Fehlerbox ({name})", 'class="msg-err' not in page)

    # ── Comboboxen (nur /rechte) ─────────────────────────────────
    check("3 Comboboxen", html_access.count('class="cb" data-cb=') >= 3)
    check("Combobox User", 'data-cb="access_user_id"' in html_access)
    check("Combobox Anlage", 'data-cb="access_installation_id"' in html_access)
    check("Combobox Filter-Anlage", 'data-cb="f-access-inst"' in html_access)
    check("Platzhalter-Option User", '<option value="" selected>— Benutzer wählen —</option>' in html_access)
    check("Platzhalter-Option Anlage", '<option value="" selected>— Anlage wählen —</option>' in html_access)
    check("3 Suchfelder in Combos", html_access.count('class="cb-search"') == 3)

    # ── Guard: Recht ohne Auswahl (leere Combobox abschicken) ─────
    r = c.post("/admin/access", data={"user_id": "", "installation_id": "", "can_read": "1"})
    check("Guard: 303 statt 422", r.status_code == 303, f"status={r.status_code}")
    check("Guard: Redirect mit ?err=missing", r.headers.get("location", "").endswith("/rechte?err=missing"), r.headers.get("location", ""))
    gu = c.get("/rechte?err=missing").text
    check("Fehlermeldung gerendert", "Bitte Benutzer und Anlage für das Recht auswählen." in gu)

print(f"\n{ok} Checks grün")
