"""F76-Tests (Schritt 2+3, Teil C+D): Seite „Standard-Module“ + Detailseiten-Ausnahmen.

Umbenannt von „Fehlende Module“ → „Standard-Module“ (Axel, v1.0.73):
- Route /admin/updates/standard (+303-Redirect der alten URL /admin/updates/fehlende)
- Menü-Label „Standard-Module“, active updates-standard

Neu (F76/3):
- Detailseite /installation/{id}: Standard-Spalte in der Modul-Tabelle
  (Badge „Standard“/„Ausnahme“) + POST /installation/{id}/module/standard
- module_default_overrides-Tabelle: Ausnahme = Standard-Modul, das auf DIESER
  Anlage nicht zwingend sein muss → verschwindet aus der Standard-Module-Seite.

Geprüft:
1.  Umbenennung: Menüpunkt/Label, alte URL → 303 auf neue, active updates-standard
2.  GET /admin/updates/standard: Gruppen (Alpha 2, Beta 1, Charlie 2), Badges,
    „kein Deployment-Modul“, Checkboxen, items-Values, Ghost nirgends
3.  Push: selected (3 ok + Beta-Fehler), keine Auswahl, all (Server-Rechen 4),
    install-/update-Flags, Dedup
4.  Detailseite: Standard-Badges (3 ×, Deployment-Modul ohne), „—“ für nicht-
    Standard; Ausnahme setzen → „Ausnahme“-Badge; Nicht-Standard → ok:false;
    Admin-Guard (307); POST auf unbekannte Anlage → 404
5.  Override-Wirkung: Ausnahme CallBlocker/Alpha → Zeile weg aus Standard-Seite
    (GET und Server-Fallback „action=all“), nach Aufheben wieder da
6.  Leerzustände + Nicht-Admin (GET Standard-Seite) → 307
"""
import os
import sqlite3
import sys
import base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["STARFACE_DB"] = "/tmp/standard_module_test/test.db"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "pw123"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET"):
    os.environ.pop(var, None)

DB = os.environ["STARFACE_DB"]
import shutil
shutil.rmtree(os.path.dirname(DB), ignore_errors=True)
os.makedirs(os.path.dirname(DB), exist_ok=True)

import main as app_main
from starlette.testclient import TestClient

# Mock-Konfiguration ---------------------------------------------------------
EXP = {
    "CallBlocker": {"version": "30", "file": "callblocker.sfm"},
    "Deployment-Modul": {"version": "8", "file": "deployment-modul.sfm"},
    "TelefonieMonitoring": {"version": "9", "file": "telefoniemonitoring.sfm"},
    "Drittanbieter-X": {"version": "9", "file": "x.sfm"},
}
# Ghost: is_standard=1 in der DB, aber NICHT im Sortiment (gelöschte Datei) → nirgends

STATUS = {
    ("Alpha", "CallBlocker"): {"name": "CallBlocker", "installed": True, "status": "outdated", "version_ist": "29"},
    ("Alpha", "Deployment-Modul"): {"name": "Deployment-Modul", "installed": True, "status": "ok", "version_ist": "8"},
    ("Alpha", "TelefonieMonitoring"): {"name": "TelefonieMonitoring", "installed": True, "status": "ok", "version_ist": "9"},
    ("Alpha", "Drittanbieter-X"): {"name": "Drittanbieter-X", "installed": False},
    ("Beta", "CallBlocker"): {"name": "CallBlocker", "installed": True, "status": "ok", "version_ist": "30"},
    ("Beta", "Deployment-Modul"): None,
    ("Beta", "TelefonieMonitoring"): {"name": "TelefonieMonitoring", "installed": True, "status": "ok", "version_ist": "9"},
    ("Beta", "Drittanbieter-X"): None,
    ("Charlie", "CallBlocker"): {"name": "CallBlocker", "installed": True, "status": "outdated", "version_ist": "29"},
    ("Charlie", "Deployment-Modul"): None,
    ("Charlie", "TelefonieMonitoring"): {"name": "TelefonieMonitoring", "installed": True, "status": "ok", "version_ist": "9"},
    ("Charlie", "Drittanbieter-X"): {"name": "Drittanbieter-X", "installed": True, "status": "outdated", "version_ist": "8"},
    # Zeta: Anlage fällt in _collect_module_status mit Exception → „nicht erreichbar“
    ("Zeta", "CallBlocker"): {"name": "CallBlocker", "installed": True, "status": "ok", "version_ist": "30"},
}

import monitoring
monitoring._module_expectations = lambda: dict(EXP)
PUSH_CALLS = []

def fake_collect(inst, token, label):
    if inst["name"] == "Zeta":
        raise RuntimeError("boom")
    st = {"list": []}
    for key, it in STATUS.items():
        if key[0] == inst["name"] and it:
            st["list"].append(dict(it))
    return st

monitoring._collect_module_status = fake_collect
app_main._get_token = lambda inst: "tok"
app_main._push_module = lambda inst, module_name, filename, version, is_install=False: (
    PUSH_CALLS.append((inst["name"], module_name, is_install)) or ("ok", "ok")
)
monitoring._xmlrpc = lambda *a, **k: {}


def setup_db():
    app_main.init_db()
    conn = sqlite3.connect(DB)
    import bcrypt
    conn.execute("DELETE FROM modules")
    conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                 ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
    conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                 ("bob", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 0))
    modules = [
        ("CallBlocker", "own", "30", "callblocker.sfm", 1),
        ("TelefonieMonitoring", "own", "9", "telefoniemonitoring.sfm", 1),
        ("Deployment-Modul", "own", "8", "deployment-modul.sfm", 0),
        ("Drittanbieter-X", "third_party", "9", "x.sfm", 1),
        ("Ghost", "own", "1", "ghost.sfm", 1),
    ]
    for m in modules:
        conn.execute("INSERT INTO modules (name, source, version, filename, is_standard) VALUES (?,?,?,?,?)", m)
    for name, url, mon, dep in [("Alpha", "https://alpha.beispiel.de", "mon", "dep"),
                                ("Beta", "https://beta.beispiel.de", "mon", ""),
                                ("Charlie", "https://charlie.beispiel.de", "mon", "dep"),
                                ("Gamma", "https://gamma.beispiel.de", "", ""),
                                ("Zeta", "https://zeta.beispiel.de", "mon", "dep")]:
        conn.execute("INSERT INTO installations (name, url, auth_id, auth_pass, monitoring_instance_name, deployer_instance_name) VALUES (?,?,?,?,?,?)",
                     (name, url, "api", "pw", mon, dep))
    conn.commit()
    conn.close()

setup_db()

checks = 0
def check(name, cond, detail=""):
    global checks
    checks += 1
    tag = "OK " if cond else "FAIL"
    print(f"{tag} {checks}: {name}" + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        raise SystemExit(1)

c = TestClient(app_main.app)
c.post("/api/login", data={"username": "admin", "password": "pw123"})

# ── 1. Umbenennung ──
r = c.get("/admin/updates/standard")
body = r.text
check("1a. Neue Seite 200", r.status_code == 200)
check("1b. Titel 'Standard-Module'", "Standard-Module" in body and "Fehlende Module" not in r.text
      and "Standard-Module, die auf Anlagen fehlen" in body)
check("1c. Menüpunkt-Label + Link 'Standard-Module'", 'href="/admin/updates/standard"' in body
      and ">Standard-Module<" in body)
check("1d. Kein altes Menü-Label mehr", ">Fehlende Module<" not in body)
r2 = c.get("/admin/updates/fehlende")
jump = (r2.history and r2.history[0].status_code == 303
        and "/admin/updates/standard" in r2.history[0].headers.get("location", ""))
check("1e. Alte URL → 303 auf /admin/updates/standard", bool(jump))

# ── 2. Seite ──
seg_a = body.split(">Alpha<")[1].split(">Beta<")[0]
seg_b = body.split(">Beta<")[1].split(">Charlie<")[0]
seg_c = body.split(">Charlie<")[1] if ">Charlie<" in body else ""
check("2a. Gamma übersprungen (kein Monitoring) + Zeta nur Fehlerhinweis",
      ">Gamma<" not in body and "nicht erreichbar" in body)
check("2b. Alpha: 2 Zeilen (CallBlocker outdated + Drittanbieter-X fehlt)",
      ">CallBlocker<" in seg_a and ">Drittanbieter-X<" in seg_a and ">TelefonieMonitoring<" not in seg_a)
check("2c. Alpha ohne Deployment-Badge, Beta mit",
      "Deployment-Modul fehlt" not in seg_a and "Deployment-Modul fehlt" in seg_b)
check("2d. Zeilen-Checkboxen je Gruppe", seg_a.count('class="std-cb"') == 2
      and seg_b.count('class="std-cb"') == 1 and seg_c.count('class="std-cb"') == 2)
check("2e. Beta: kein Deployment-Modul (kein Button), Alpha/Charlie mit Button",
      "kein Deployment-Modul" in seg_b and "kein Deployment-Modul" not in seg_a
      and "Update anstoßen" in seg_a and "Installieren" in seg_a)
check("2f. Ghost nirgends (Standard-Flag, aber nicht im Sortiment)",
      "Ghost" not in body and ":Deployment-Modul" not in body)
check("2g. items-Values install/update", 'value="1:CallBlocker:update"' in body
      and 'value="1:Drittanbieter-X:install"' in body and 'value="3:CallBlocker:update"' in body)
check("2h. Gesamtzahl Checkboxen = 5 + Alles-Zähler (5)",
      body.count('class="std-cb"') == 5 and "Alles aktualisieren bzw. installieren (5)" in body)
check("2i. Buttons: Alle/Auswahl aufheben + Ausgewählte",
      "Alle auswählen" in body and "Auswahl aufheben" in body
      and "Ausgewählte aktualisieren bzw. installieren" in body)

# ── 3. Push ──
from urllib.parse import unquote, parse_qs

def redir_msg(r):
    raw = parse_qs(r.url.query).get(b"msg", [b""])[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return unquote(raw)

PUSH_CALLS.clear()
r = c.post("/admin/updates/standard/push", data={
    "action": "selected",
    "items": ["1:CallBlocker:update", "1:Drittanbieter-X:install",
              "2:Drittanbieter-X:install", "3:CallBlocker:update"],
})
check("3a. selected: 3 ok, Beta als Fehler ohne Push",
      len(PUSH_CALLS) == 3 and "3× Update/Installation angestoßen" in redir_msg(r)
      and "Beta" in redir_msg(r) and "kein Deployment-Modul" in redir_msg(r))
check("3b. Push-Flags: install nur bei fehlendem Modul",
      ("Alpha", "Drittanbieter-X", True) in PUSH_CALLS and ("Alpha", "CallBlocker", False) in PUSH_CALLS)
r = c.post("/admin/updates/standard/push", data={"action": "selected", "items": []})
check("3c. Keine Auswahl → Hinweis", "Keine Module ausgewählt" in redir_msg(r))
PUSH_CALLS.clear()
r = c.post("/admin/updates/standard/push", data={"action": "all", "items": []})
check("3d. all ohne JS: Server-Neuberechnung = 4 pushes (Alpha 2, Charlie 2; Beta Fehler)",
      len(PUSH_CALLS) == 4 and "4× Update/Installation angestoßen" in redir_msg(r)
      and "Beta" in redir_msg(r))

# ── 4. Detailseite: Standard-Spalte + Overrides ──
rd = c.get(f"/installation/1")
dbody = rd.text
check("4a. Detailseite lädt (Admin, can_read)", rd.status_code == 200 and "Modul-Status" in dbody)
check("4a2. Standard-Spalten-Header ist da", ">Standard</th>" in dbody)
check("4b. 3 Standard-Badges (CallBlocker, TelefonieMonitoring, Drittanbieter-X)",
      dbody.count(">Standard</span>") == 3)
dep_row = dbody.split('id="tbl-mod"')[1].split("</table>")[0].split(">Deployment-Modul<")[1].split("</tr>")[0]
check("4c. Deployment-Modul ohne Standard-Badge (Zelle '—')",
      ">Standard</span>" not in dep_row and ">—<" in dep_row)
check("4d. Kein 'Ausnahme'-Badge vor Toggle", ">Ausnahme</span>" not in dbody)
r = c.post("/installation/1/module/standard", json={"module": "CallBlocker", "active": True})
check("4e. Ausnahme setzen → ok", r.status_code == 200 and r.json().get("ok") is True)
dbody = c.get("/installation/1").text
check("4f. Detailseite zeigt 'Ausnahme' für CallBlocker",
      ">Ausnahme</span>" in dbody and "Ausnahme aufheben" in dbody)
r = c.post("/installation/1/module/standard", json={"module": "Deployment-Modul", "active": True})
check("4g. Nicht-Standard-Modul → abgelehnt", r.status_code == 400 and r.json().get("ok") is False)
r = c.post("/installation/999/module/standard", json={"module": "CallBlocker", "active": True})
check("4h. Unbekannte Anlage → 404", r.status_code == 404)
cb = TestClient(app_main.app)
cb.post("/api/login", data={"username": "bob", "password": "pw123"})
r = cb.post("/installation/1/module/standard", json={"module": "CallBlocker", "active": True})
jump = (r.history and r.history[0].status_code in (303, 307)
        and r.history[0].headers.get("location", "") == "/") if r.history else False
check("4i. Nicht-Admin → Redirect /", bool(jump) or (r.status_code == 200 and "/" in str(r.url)))

# ── 5. Override-Wirkung auf die Standard-Module-Seite ──
body2 = c.get("/admin/updates/standard").text
seg_a2 = body2.split(">Alpha<")[1].split(">Beta<")[0]
check("5a. Ausnahme CallBlocker/Alpha → 1 Zeile statt 2 (Drittanbieter-X bleibt)",
      seg_a2.count('class="std-cb"') == 1 and ">CallBlocker<" not in seg_a2
      and ">Drittanbieter-X<" in seg_a2)
PUSH_CALLS.clear()
r = c.post("/admin/updates/standard/push", data={"action": "all", "items": []})
check("5b. Server-Fallback respektiert Ausnahme (kein CallBlocker/Alpha-Push)",
      ("Alpha", "CallBlocker", False) not in PUSH_CALLS and len(PUSH_CALLS) == 3)
r = c.post("/installation/1/module/standard", json={"module": "CallBlocker", "active": False})
check("5c. Ausnahme aufheben → ok", r.status_code == 200 and r.json().get("ok") is True)
body3 = c.get("/admin/updates/standard").text
seg_a3 = body3.split(">Alpha<")[1].split(">Beta<")[0]
check("5d. Nach Aufheben wieder 2 Zeilen", seg_a3.count('class="std-cb"') == 2)

# ── 6. Leerzustände + Guards ──
conn = sqlite3.connect(DB)
conn.execute("UPDATE modules SET is_standard = 0")
conn.commit()
conn.close()
leer = c.get("/admin/updates/standard").text
check("6a. Leerzustand: keine Standard-Module festgelegt", "noch keine Standard-Module festgelegt" in leer)
conn = sqlite3.connect(DB)
conn.execute("UPDATE modules SET is_standard = 1")
conn.commit()
conn.close()
cbg = TestClient(app_main.app)
cbg.post("/api/login", data={"username": "bob", "password": "pw123"})
r = cbg.get("/admin/updates/standard")
jump = (r.history and r.history[0].status_code in (303, 307)
        and r.history[0].headers.get("location", "") == "/") if r.history else False
check("6b. GET als Nicht-Admin → Redirect /", bool(jump))

print(f"\nERGEBNIS: ALLE STANDARD-MODULE-TESTS OK ({checks} Checks)")
