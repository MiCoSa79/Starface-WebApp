"""F107 — 10-s-Auto-Refresh auf Geplante/Laufende/Durchgeführte Updates + 
Filter-Erhalt beim Reload.

Geprüft:
A. /admin/anlagen-updates/geplant rendert das Auto-Refresh-Script
   (setInterval ... 10000 ... location.reload) + Filter-Preserve (sessionStorage)
B. /admin/anlagen-updates/laufend: Auto-Refresh ohne Filter-Preserve-Codeschmutz
   (kein .tbl-filters → Guard; Refresh-Script trotzdem da)
C. /admin/anlagen-updates/durchgefuehrt: Auto-Refresh + Filter-Preserve
D. Kein Doppel-Refresh-Timer (location.reload genau 1× im Script-Block)

Aufruf: .venv/bin/python tmp_tests/admin_anlagen_updates_f107_test.py
"""
import base64
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_anlagen_updates_f107_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "pw123"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET"):
    os.environ.pop(var, None)

import main as app_main
import sqlite3
import bcrypt
app_main.init_db()
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.commit()
conn.close()
from starlette.testclient import TestClient

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("— " + detail) if detail and not cond else "")


c = TestClient(app_main.app)
c.post("/api/login", data={"username": "admin", "password": "pw123"})

for seite in ("geplant", "laufend", "durchgefuehrt"):
    r = c.get(f"/admin/anlagen-updates/{seite}")
    check(f"F107/{seite} Seite 200", r.status_code == 200, f"status={r.status_code}")
    h = r.text
    check(f"F107/{seite} Auto-Refresh-Script (setInterval+10000+reload)",
          "setInterval" in h and "10000" in h and "location.reload" in h)
    check(f"F107/{seite} genau 1 location.reload im Seiten-HTML",
          h.count("location.reload") == 1, f"count={h.count('location.reload')}")

# Filter-Preserve NUR auf Seiten mit .tbl-filters (geplant + durchgefuehrt)
for seite, hat in (("geplant", True), ("laufend", False), ("durchgefuehrt", True)):
    h = c.get(f"/admin/anlagen-updates/{seite}").text
    if hat:
        check(f"F107/{seite} Filter-Preserve (sessionStorage sf.admin.tabFilter)",
              "sessionStorage" in h and "sf.admin.tabFilter" in h and "beforeunload" in h
              and "dispatchEvent" in h)
        check(f"F107/{seite} Preserve-Key mit data-filter/data-col/daten-wildcard",
              "dataset.filter" in h and "dataset.col" in h and "dataset.wildcard" in h)
    else:
        check(f"F107/{seite} kein Filter-Preserve-Code (Guard .tbl-filters)",
              "location.reload" in h and "var filters = document.querySelectorAll" in h)

# Refresh-Intervall exakt 10000 ms
h = c.get("/admin/anlagen-updates/laufend").text
m = re.search(r",\s*(\d{4,5})\)\s*;\s*\}\)", h)
check("F107/Intervall 10000 ms im Script",
      bool(m) and m.group(1) == "10000", f"gefunden={m.group(1) if m else None}")

print(f"\nF107: {len(PASS)} ok, {len(FAIL)} fail")
sys.exit(1 if FAIL else 0)
