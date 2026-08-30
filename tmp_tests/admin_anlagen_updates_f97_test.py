"""F97 — Updates einrichten: Rename-Titel + Alle-auswählen-Buttons + Ergebnis im Dialog (dlg=1).

Geprüft:
1. Seite/Überschrift heißen „Updates einrichten“ (nicht mehr „Anlagen-Updates“ als h2).
2. sel-all/sel-none-Buttons + initAuSelectAll/initAuDlg in admin.js.
3. fetch/fetch-bulk → Redirect mit dlg=1; GET mit dlg=1 rendert den Schnittmengen-
   block IN <dialog id="au-dlg"> (kein open-Attribut; data-dlg="1"); ohne dlg kein Dialog.
4. Aktionen im Dialog (execute/schedule) → Redirect ohne dlg (Dialog schließt).
5. Guard: Nicht-Admin 307.
"""
import json, os, sqlite3, sys
from datetime import datetime, timezone
from urllib.parse import quote
from starlette.testclient import TestClient

DB = "/tmp/admin_anlagen_updates_f97_test/test.db"
os.makedirs(os.path.dirname(DB), exist_ok=True)
if os.path.exists(DB):
    os.remove(DB)
os.environ["STARFACE_DB"] = DB          # VOR import main (DB_PATH fixiert beim Modul-Load)
os.environ["WEBAPP_SESSION_TTL_HOURS"] = "24"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import main as app_main
import module_updates

app_main.init_db()

import bcrypt
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("normal", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 0))
def add_inst(name, url):
    cur = conn.execute(
        "INSERT INTO installations (name, url, is_starface10, deployer_instance_name,"
        " deployer_token, oauth_client) VALUES (?,?,1,'Deployer','tok','rest-client')",
        (name, url))
    return cur.lastrowid
ID_A = add_inst("Alpha", "https://alpha.sub.example.de")
ID_B = add_inst("Beta", "https://beta.sub.example.de")
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

# ── RPC-Fake wie F95: GetAnlagenUpdates + ExecuteAnlagenUpdate + GetStats ──
FAKE_UPDATES = {}
def rpc_string(s):
    return ("<methodResponse><params><param><value><string>" + s
            + "</string></value></param></params></methodResponse>")
def fake_xmlrpc(url, token, method, payload=None, instance_name=None):
    if method == "GetAnlagenUpdates":
        _updates = [{"version": "10.0.3.0", "date": "2026-08-25", "type": "final",
                     "description": "x", "changelog": "y",
                     "url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"},
                    {"version": "10.0.2.8", "date": "2026-08-10", "type": "final",
                     "description": "x", "changelog": "y",
                     "url": "https://update.sub.example.de/stable/starface-10.0.2.8.rpm"}]
        data = json.dumps({"current": "10.0.2.5", "count": 2,
                           "updates": FAKE_UPDATES.get(url, _updates)})
        return {"raw": rpc_string(data), "values": [data], "members": {}}
    if method == "ExecuteAnlagenUpdate":
        return {"raw": rpc_string("OK: Update auf %s angestossen (Anlage startet den Update-Prozess)" % payload["version"])}
    if method == "GetStats":
        return {"raw": rpc_string("ok"), "members": {"systemVersion": "10.0.1.7"}, "values": []}
    raise AssertionError("unerwarteter RPC: " + method)
module_updates._xmlrpc = fake_xmlrpc
saved_token = app_main._get_token
app_main._get_token = lambda inst: "tok"   # F96-Pitfall: echter Token-Check scheitert ohne OAuth-Daten

# ── 1. Rename: Titel + Überschrift ────────────────────────────────────────────
r = c.get("/admin/anlagen-updates")
check("1a title: 'Updates einrichten'", '<title>STARFACE WebApp — Updates einrichten</title>' in r.text, r.text[:200])
h2 = r.text[r.text.find("<h2"):r.text.find("</h2>")] if "<h2" in r.text else ""
check("1b h2 = 'Updates einrichten'", "Updates einrichten" in h2, h2)
check("1c h2 NICHT mehr 'Anlagen-Updates'", "Anlagen-Updates" not in h2, h2)

# ── 2. Alle-auswählen-Buttons + JS ────────────────────────────────────────────
check("2a sel-all-Button", 'id="sel-all"' in r.text and 'id="sel-none"' in r.text, "")
check("2b data-select-Ziel", 'data-select="au-cb"' in r.text, "")
js = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "admin.js"), encoding="utf-8").read()
check("2c initAuSelectAll in admin.js", "initAuSelectAll" in js and "offsetParent" in js, "")
check("2d initAuDlg in admin.js", "function initAuDlg" in js and "showModal" in js, "")

# ── 3a. fetch-bulk → 303 mit dlg=1; folgende GET zeigt Dialog ─────────────────
r = c.post("/admin/anlagen-updates/fetch-bulk",
           data={"installation_ids": [str(ID_A), str(ID_B)]}, follow_redirects=False)
loc = r.headers.get("location", "")
check("3a fetch-bulk 303 + dlg=1", r.status_code == 303 and "dlg=1" in loc, loc[:120])
r2 = c.get(f"/admin/anlagen-updates?inst_ids={ID_A},{ID_B}&dlg=1")
check("3b Dialog im HTML", 'id="au-dlg"' in r2.text, "")
check("3c data-dlg=1 (JS öffnet)", 'data-dlg="1"' in r2.text, "")
check("3d kein hartes open-Attribut",
      '<dialog id="au-dlg"' in r2.text and 'id="au-dlg" open' not in r2.text, "")
dlg = r2.text[r2.text.find('<dialog'):r2.text.find('</dialog>')] if '<dialog' in r2.text else ""
check("3e Schnittmenge INNERHALB des Dialogs", "Schnittmenge" in dlg, "")
check("3f datetime-local (Planung) im Dialog", 'type="datetime-local"' in dlg, "")
check("3g installation_ids-Hiddens im Dialog", 'name="installation_ids"' in dlg, "")

# ── 3b. Fallback ohne dlg: Bereich direkt, KEIN Dialog ────────────────────────
r3 = c.get(f"/admin/anlagen-updates?inst_ids={ID_A},{ID_B}")
check("3h ohne dlg KEIN Dialog", 'au-dlg' not in r3.text, "")
check("3i ohne dlg: Schnittmenge direkt sichtbar", "Schnittmenge" in r3.text, "")

# ── 3c. Zeilen-fetch → 303 mit dlg=1 ──────────────────────────────────────────
r = c.post("/admin/anlagen-updates/fetch", data={"installation_id": str(ID_A)},
           follow_redirects=False)
loc = r.headers.get("location", "")
check("3j Zeilen-fetch 303 + dlg=1", r.status_code == 303 and "dlg=1" in loc, loc[:120])

# ── 4. Aktion aus dem Dialog → Redirect ohne dlg (Dialog schließt) ────────────
conn = sqlite3.connect(DB)
n_log0 = conn.execute("SELECT COUNT(*) FROM anlagen_update_log").fetchone()[0]
conn.close()
r = c.post("/admin/anlagen-updates/execute",
           data={"installation_ids": [str(ID_A), str(ID_B)], "version": "10.0.3.0",
                 "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"},
           follow_redirects=False)
loc = r.headers.get("location", "")
check("4a execute 303 ohne dlg", r.status_code == 303 and "dlg=1" not in loc, loc[:120])
conn = sqlite3.connect(DB)
n_log1 = conn.execute("SELECT COUNT(*) FROM anlagen_update_log").fetchone()[0]
conn.close()
check("4b execute legt Log je Anlage an", n_log1 == n_log0 + 2, f"{n_log0}->{n_log1} (2 Anlagen erwartet)")

# ── 5. Guard ──────────────────────────────────────────────────────────────────
c2 = TestClient(app_main.app)
c2.post("/api/login", data={"username": "normal", "password": "pw123"})
rr = c2.get("/admin/anlagen-updates", follow_redirects=False)
check("5a Guard GET 307", rr.status_code == 307, str(rr.status_code))
rr = c2.post("/admin/anlagen-updates/fetch-bulk", data={"installation_ids": ["1"]},
             follow_redirects=False)
check("5b Guard POST 307", rr.status_code == 307, str(rr.status_code))
app_main._get_token = saved_token

print("\nALLE F97-CHECKS OK" if not FAIL else f"\n{len(FAIL)} FAIL(S): {FAIL}")
sys.exit(0 if not FAIL else 1)
