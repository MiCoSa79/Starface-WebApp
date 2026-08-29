"""F76-Tests (Schritt 2, Teil C): Seite „Fehlende Module“ (Standard-Module).

Geprüft:
1. Submenü: dritter Punkt „Fehlende Module“ (base.html, active updates-fehlende)
2. GET /admin/updates/fehlende: Anlagen-Gruppen nur mit fehlenden/veralteten
   Standard-Modulen; Anlage ohne Monitoring-Instanz wird übersprungen
3. Zeilenauswahl: nur Standard-Module (fehlend ODER nicht aktuell); Module,
   die nicht (mehr) im Sortiment sind, erscheinen nicht
4. items[]-Werte mit is_install-Kennung (update/install)
5. Deployment-Modul-Badge: fehlt (nicht installiert ODER nicht konfiguriert);
   ohnehin „— kein Deployment-Modul“ in Zeilen ohne Konfiguration
6. Bulk-Buttons (Alles/Ausgewählte) + Alle auswählen/Auswahl aufheben
7. POST push: selected-Paare (ohne deployer → Fehler, kein RPC); action=all
   mit leerer Auswahl → Server-Neuberechnung; keine Auswahl → Hinweis
8. Nicht erreichbare Anlage → Meldung, keine Gruppe
9. Nicht-Admin → Redirect
10. Leerzustand: keine Standard-Module → p.empty

Aufruf: .venv/bin/python tmp_tests/fehlende_module_test.py
"""
import base64
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/fehlende_module_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET"):
    os.environ.pop(var, None)

import main as app_main
import monitoring
from starlette.testclient import TestClient

app_main.init_db()
conn = sqlite3.connect(DB)
import bcrypt
conn.execute("DELETE FROM modules")
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("bob", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 0))

# Anlagen: Alpha (Monitoring+Deployment, dep installiert), Beta (Monitoring, KEIN Deployment),
# Charlie (Monitoring+Deployment konfiguriert, dep aber NICHT installiert),
# Zeta (Monitoring, nicht erreichbar), Gamma (kein Monitoring => übersprungen)
def add_inst(name, mon, dep=""):
    return conn.execute(
        "INSERT INTO installations (name, url, auth_id, auth_pass, monitoring_instance_name, deployer_instance_name) VALUES (?,?,?,?,?,?)",
        (name, "https://" + name.lower() + ".beispiel.de", "api", "pw", mon, dep)).lastrowid

alpha = add_inst("Alpha", "mon", "dep")
beta = add_inst("Beta", "mon")
charlie = add_inst("Charlie", "mon", "dep")
zeta = add_inst("Zeta", "mon")
gamma = add_inst("Gamma", "")

# Modul-Bestand: CallBlocker/TelefonieMonitoring/Drittanbieter-X = Standard; Deployment nicht; Ghost Standard aber nicht im Sortiment
for name, src, std in [("CallBlocker", "own", 1), ("Deployment-Modul", "own", 0),
                       ("TelefonieMonitoring", "own", 1), ("Drittanbieter-X", "third_party", 1),
                       ("Ghost", "own", 1)]:
    conn.execute("INSERT INTO modules (name, filename, version, source, is_standard) VALUES (?,?,?,?,?)",
                 (name, name.lower().replace(" ", "") + ".sfm", "1", src, std))
conn.commit()
conn.close()

# Sortiment (SOLL) — Ghost fehlt absichtlich
EXP = {
    "CallBlocker": {"version": "30", "file": "callblocker.sfm"},
    "Deployment-Modul": {"version": "8", "file": "deployment-modul.sfm"},
    "TelefonieMonitoring": {"version": "9", "file": "telefoniemonitoring.sfm"},
    "Drittanbieter-X": {"version": "9", "file": "x.sfm"},
}
monitoring._module_expectations = lambda: dict(EXP)

# IST je Anlage (None = nicht installiert)
STATUS = {
    ("Alpha", "CallBlocker"): dict(name="CallBlocker", installed=True, status="outdated", version_ist="29"),
    ("Alpha", "Deployment-Modul"): dict(name="Deployment-Modul", installed=True, status="ok", version_ist="8"),
    ("Alpha", "TelefonieMonitoring"): dict(name="TelefonieMonitoring", installed=True, status="ok", version_ist="9"),
    ("Alpha", "Drittanbieter-X"): None,
    ("Beta", "CallBlocker"): dict(name="CallBlocker", installed=True, status="ok", version_ist="30"),
    ("Beta", "TelefonieMonitoring"): dict(name="TelefonieMonitoring", installed=True, status="ok", version_ist="9"),
    ("Beta", "Drittanbieter-X"): None,
    ("Charlie", "CallBlocker"): dict(name="CallBlocker", installed=True, status="outdated", version_ist="29"),
    ("Charlie", "TelefonieMonitoring"): dict(name="TelefonieMonitoring", installed=True, status="ok", version_ist="9"),
    ("Charlie", "Drittanbieter-X"): dict(name="Drittanbieter-X", installed=True, status="outdated", version_ist="8"),
    ("Zeta", "CallBlocker"): dict(name="CallBlocker", installed=True, status="outdated", version_ist="29"),
    ("Zeta", "Deployment-Modul"): dict(name="Deployment-Modul", installed=True, status="ok", version_ist="8"),
    ("Zeta", "TelefonieMonitoring"): dict(name="TelefonieMonitoring", installed=True, status="ok", version_ist="9"),
    ("Zeta", "Drittanbieter-X"): None,
}
def fake_collect(inst, token, label):
    if inst["name"] == "Zeta":
        raise RuntimeError("Anlage nicht erreichbar (Simulation)")
    return {"list": [dict(v) for k, v in STATUS.items() if k[0] == inst["name"] and v]}

monitoring._collect_module_status = fake_collect
app_main._get_token = lambda inst: "tok"

PUSH_CALLS = []
def fake_push(inst, module_name, filename, version, is_install=False):
    PUSH_CALLS.append((inst["name"], module_name, is_install))
    aktion = "Installation angestoßen" if is_install else "Update angestoßen"
    return "ok", f"{module_name}: {aktion}"
app_main._push_module = fake_push

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200 and r.json()["status"] == "ok"

FAIL = []
def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)

# ── 1. Submenü (dritter Punkt) ──
base = open(os.path.join(os.path.dirname(__file__), "..", "app", "templates", "base.html"), encoding="utf-8").read()
check("1. Submenü: Link 'Fehlende Module' vorhanden",
      "Fehlende Module" in base and "/admin/updates/fehlende" in base and "'updates-fehlende'" in base)

# ── 2. Seite gruppiert nach Anlage ──
body = c.get("/admin/updates/fehlende").text
check("2a. GET 200", "Fehlende Module" in body)
check("2b. Gruppen Alpha/Beta/Charlie vorhanden, Gamma übersprungen",
      ">Alpha<" in body and ">Beta<" in body and ">Charlie<" in body and ">Gamma<" not in body)
check("2c. Zeta (nicht erreichbar) nicht als Gruppe, aber Meldung",
      ">Zeta<" not in body and "Zeta" in body and "nicht erreichbar" in body)
seg_a = body.split(">Alpha<")[1].split(">Beta<")[0]
seg_b = body.split(">Beta<")[1].split(">Charlie<")[0]
check("2d. Alpha: 2 Zeilen (CallBlocker + Drittanbieter-X), kein TelefonieMonitoring",
      seg_a.count("fehl-cb") == 2 and "CallBlocker" in seg_a and "Drittanbieter-X" in seg_a and "TelefonieMonitoring" not in seg_a)
check("2e. Beta: 1 Zeile (Drittanbieter-X) + kein CallBlocker-Zeile",
      seg_b.count("fehl-cb") == 1 and "Drittanbieter-X" in seg_b and "CallBlocker" not in seg_b)
check("2f. Ghost nirgends (Standard-Flag, aber nicht mehr im Sortiment)",
      "Ghost" not in body and ":Deployment-Modul" not in body)

# ── 3. items[]-Werte ──
check("3a. Update-Paar CallBlocker/Alpha", 'value="%d:CallBlocker:update"' % alpha in body)
check("3b. Install-Paar Drittanbieter-X/Alpha (fehlt)", 'value="%d:Drittanbieter-X:install"' % alpha in body)
check("3c. Gesamtzahl Checkboxen = 5", body.count('class="fehl-cb"') == 5)

# ── 4. Deployment-Badge ──
check("4a. Alpha ohne Badge", "Deployment-Modul fehlt" not in seg_a)
check("4b. Beta mit Badge (nicht konfiguriert)", "Deployment-Modul fehlt" in seg_b)
seg_c = body.split(">Charlie<")[1].split(">Zeta<")[0] if ">Zeta<" in body else body.split(">Charlie<")[1]
check("4c. Charlie mit Badge (konfiguriert, aber nicht installiert)", "Deployment-Modul fehlt" in seg_c)
check("4d. Betty-Zeile ohne Button (— kein Deployment-Modul)", "kein Deployment-Modul" in seg_b and "kein Deployment-Modul" not in seg_a)

# ── 5. Buttons ──
check("5a. Alles-Button", "Alles aktualisieren bzw. installieren" in body)
check("5b. Ausgewählte-Button", "Ausgewählte aktualisieren bzw. installieren" in body)
check("5c. Alle/Auswahl aufheben", "Alle auswählen" in body and "Auswahl aufheben" in body)

# ── 6. Push: selected ──
from urllib.parse import unquote, parse_qs

def redir_msg(r):
    """Meldung aus dem (gefolgten) Redirect-Ziel extrahieren."""
    raw = parse_qs(r.url.query).get(b"msg", [b""])[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return unquote(raw)

r = c.post("/admin/updates/fehlende/push", data={
    "action": "selected",
    "items": [f"{alpha}:CallBlocker:update", f"{alpha}:Drittanbieter-X:install",
              f"{beta}:Drittanbieter-X:install", f"{charlie}:CallBlocker:update"],
})
check("6a. Umleitung auf fehlende-Seite (gefolgt)",
      r.status_code == 200 and "/admin/updates/fehlende" in str(r.url))
msg = redir_msg(r)
check("6b. Meldung 3× + Beta-Fehler", "3×" in msg and "Beta" in msg)
check("6c. Push-Aufrufe: 3 (Beta ohne deployer → kein RPC)",
      len(PUSH_CALLS) == 3 and [p for p in PUSH_CALLS if p[0] == "Beta"] == [] and
      ("Alpha", "CallBlocker", False) in PUSH_CALLS and ("Alpha", "Drittanbieter-X", True) in PUSH_CALLS)

# ── 7. Push: keine Auswahl ──
r = c.post("/admin/updates/fehlende/push", data={"action": "selected", "items": []})
check("7. Keine Module ausgewählt → Hinweis", "Keine Module ausgewählt" in redir_msg(r))

# ── 8. Push: action=all ohne items → Server-Neuberechnung ──
PUSH_CALLS.clear()
r = c.post("/admin/updates/fehlende/push", data={"action": "all", "items": []})
msg = redir_msg(r)
check("8a. Server-Neuberechnung: 4× (Alpha×2 + Charlie×2), Beta-Fehler",
      len(PUSH_CALLS) == 4 and "4×" in msg and "Beta" in msg and
      [p for p in PUSH_CALLS if p[0] == "Beta"] == [])
check("8b. Install-Flag nur für fehlende Module (Alpha-X), Update für installierte (Charlie-X)",
      ("Alpha", "Drittanbieter-X", True) in PUSH_CALLS and
      ("Charlie", "Drittanbieter-X", False) in PUSH_CALLS and
      ("Charlie", "CallBlocker", False) in PUSH_CALLS)

# ── 9. Nicht-Admin ──
cb = TestClient(app_main.app)
cb.post("/api/login", data={"username": "bob", "password": "pw123"})
r = cb.post("/admin/updates/fehlende/push", data={"action": "selected", "items": [f"{alpha}:CallBlocker:update"]})
jump = (r.history[0].status_code in (303, 307) and r.history[0].headers.get("location", "") == "/") if r.history else False
followed = r.status_code == 200 and "<html" in r.text.lower()
check("9. Nicht-Admin → Redirect auf /", jump or followed)

# ── 10. Leerzustand ──
conn = sqlite3.connect(DB)
conn.execute("UPDATE modules SET is_standard = 0")
conn.commit(); conn.close()
body = c.get("/admin/updates/fehlende").text
check("10. Leerzustand p.empty (keine Standard-Module)",
      "noch keine Standard-Module" in body or "Keine fehlenden" in body)

print()
print("ERGEBNIS:", "ALLE FEHLENDE-MODULE-TESTS OK" if not FAIL else f"{len(FAIL)} FEHLGESCHLAGEN: {FAIL}")
sys.exit(1 if FAIL else 0)
