#!/usr/bin/env python3
"""E2E-Smoke-Test: Admin-Tabellen-Filter + Collapse (HTML-Struktur).

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
os.environ["APP_VERSION"] = "v0.0.96-test"

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

    html = c.get("/admin").text

    # ── Struktur-Checks ───────────────────────────────────────────
    check("Anlagen-Wrap", 'class="tbl-wrap" data-wrap="inst"' in html)
    check("Benutzer-Wrap", 'data-wrap="users"' in html)
    check("Rechte-Wrap", 'data-wrap="access"' in html)

    btns = re.findall(r'data-collapse="(\w+)"', html)
    check("3 Collapse-Buttons", btns == ["inst", "users", "access"], str(btns))

    check("Chevron-SVG", html.count("<svg") >= 3 and 'class="chev"' in html)

    # Anlagen: Name (col 1), URL (col 2), Version (col 3)
    check("Filter Name", 'data-filter="tbl-inst" data-col="1"' in html)
    check("Filter URL", 'data-filter="tbl-inst" data-col="2"' in html)
    check("Filter Version-Dropdown", 'data-filter="tbl-inst" data-col="3"' in html)
    check("Dropdown-Placeholder", 'Alle Versionen' in html)
    # Benutzer + Rechte
    check("Filter Benutzer", 'data-filter="tbl-users" data-col="1" data-minlen="3"' in html)
    check("Filter Rechte-User", 'data-filter="tbl-access" data-col="0" data-minlen="3"' in html)
    check("Filter Rechte-Anlage", 'data-filter="tbl-access" data-col="1"' in html)
    # Counter mit Jinja-Werten
    m = re.search(r'data-count="inst">(\d+) von (\d+)<', html)
    check("Counter Anlagen", m and m.group(1) == "2" and m.group(2) == "2", html[m.start():m.start()+60] if m else "kein Counter")
    m = re.search(r'data-count="users">(\d+) von (\d+)<', html)
    check("Counter Benutzer (Admin + tester)", m and m.group(1) == "2" and m.group(2) == "2", "kein Counter" if not m else "")
    # JS-Engine vorhanden
    check("JS initCollapse", "function initCollapse" in html and "function initTableFilters" in html)
    check("keine Fehlerbox", 'class="msg-err' not in html)

print(f"\n{ok} Checks grün")
