#!/usr/bin/env python3
"""Smoke-Test: Dashboard-Badge is_starface10 (v9 vs. v10+) gegen die echte App.

Muster aus tmp_tests/e2e_update.py: Env-Admin, TestClient, POST /admin/installations.
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))

_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_badge_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["APP_VERSION"] = "v0.0.92-test"

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ok = 0
def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        sys.exit(1)

with TestClient(main.app) as c:
    # 1) Login (Env-Admin)
    r = c.post("/api/login", data={"username": "admin", "password": "testpass123"})
    j = r.json()
    check("Login", j.get("status") == "ok", str(j))

    # 2) Zwei Anlagen: eine v10 (is_starface10=1), eine v9 (0)
    r = c.post("/admin/installations", data={
        "name": "Testanlage v10", "url": "https://nfr-test.starface-cloud.com",
        "auth_id": "u", "auth_pass": "p", "client_secret": "s", "is_starface10": "1"})
    check("Anlage v10 angelegt", r.status_code < 400, str(r.status_code))
    r = c.post("/admin/installations", data={
        "name": "Altanlage v9", "url": "https://alt.starface-cloud.com",
        "auth_id": "u", "auth_pass": "p", "client_secret": "s", "is_starface10": "0"})
    check("Anlage v9 angelegt", r.status_code < 400, str(r.status_code))

    # DB-Stand direkt prüfen (is_starface10 korrekt persistiert?)
    db = main._db()
    rows = db.execute("SELECT name, is_starface10 FROM installations ORDER BY name").fetchall()
    db.close()
    flags = {row["name"]: row["is_starface10"] for row in rows}
    check("DB: v10-Anlage hat is_starface10=1", flags.get("Testanlage v10") == 1, str(flags))
    check("DB: v9-Anlage hat is_starface10=0", flags.get("Altanlage v9") == 0, str(flags))

    # 3) Dashboard: Badges prüfen
    r = c.get("/dashboard")
    html = r.text
    check("Dashboard 200", r.status_code == 200, str(r.status_code))
    v10_badge = re.search(r'Testanlage v10.*?badge">v10\+<', html, re.S)
    v9_badge = re.search(r'Altanlage v9.*?badge">v9<', html, re.S)
    check("v10-Anlage zeigt v10+", v10_badge is not None,
          "(Badge im HTML suchen)")
    check("v9-Anlage zeigt v9", v9_badge is not None,
          "(Badge im HTML suchen)")

    # Ausgabe aller Karten fürs Protokoll
    print("\nDashboard-Karten:")
    for name, info in re.findall(r'<div class="card">.*?<h3>(.*?)</h3>.*?<div class="info">(.*?)</div>', html, re.S):
        b = re.search(r'class="badge">([^<]+)<', info)
        print(f"  {name}: {info.split('<')[0].strip()} → Badge {b.group(1) if b else '?'}")

print(f"\n{ok} Checks grün")
sys.exit(0)
