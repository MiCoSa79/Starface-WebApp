"""F111 (v1.0.115): Startseite-Gesamtmonitoring erweitert.

Axels Anforderungen (30.08.):
- „Die Fußzeile ist wieder nicht fixiert" → Root Cause: 6 Templates definierten
  `.footer { position: fixed }` lokal (base/password/wiki/blocklist/modules/api_doku)
  → gewann gegen die F98-Sticky-Regel (admin.css margin-top:auto) → Footer klebte
  beim Scrollen über dem Inhalt. Fix: lokale fixed-Regeln entfernt.
- „Ergänze auf der Startseite eine Tabelle mit geplanten Updates" →
  Spalten Anlage / URL / Version IST / Update auf / Datum und Uhrzeit.
- „Ergänze eine Tabelle mit aktuell laufende Updates" →
  Spalten Anlage / URL / Version IST / Update auf / Startzeitpunkt.

Aufbau: TestClient ohne Scheduler-Daemon (ANLAGEN_UPDATE_TICK=86400).
"""
import os
import sys
import shutil
import sqlite3
import re
from datetime import datetime, timedelta, timezone
import bcrypt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from fastapi.testclient import TestClient  # noqa: E402

os.environ["STARFACE_DB"] = "/tmp/startseite_f111_test/test.db"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["FERNET_KEY"] = "5H4d2Qf3LyJ8xP6mN0bVcRzTkKwYhG1A7uEoI3sWnXq="
os.environ["MONITORING_ALPHA_PERIOD"] = "0"
os.environ["ANLAGEN_UPDATE_TICK"] = "86400"  # Daemon tickt nicht während des Tests
os.environ["ANLAGEN_UPDATE_CHECK_INTERVAL"] = "3600"
os.environ["ANLAGEN_UPDATE_CHECK_TIMEOUT"] = "3600"

DB = os.environ["STARFACE_DB"]
try:
    shutil.rmtree(os.path.dirname(DB))
except OSError:
    pass
os.makedirs(os.path.dirname(DB), exist_ok=True)

import main as app_main  # noqa: E402
from main import init_db  # noqa: E402
try:
    from timeutil import utc_iso_zu_lokal_anzeige  # noqa: E402
except ImportError:
    from app.timeutil import utc_iso_zu_lokal_anzeige  # noqa: E402

init_db()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name
          + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


# ── Footer-Fix-Checks (Dateien direkt lesen — CSS ist Datei-Wahrheit) ────────
with open(os.path.join(REPO, "app", "templates", "base.html"), encoding="utf-8") as f:
    BASE = f.read()
with open(os.path.join(REPO, "app", "static", "admin.css"), encoding="utf-8") as f:
    ADM_CSS = f.read()

check("F1 base.html: keine lokale .footer fixed-Regel mehr",
      ".footer { position: fixed" not in BASE and "footer { position: fixed" not in BASE)
check("F2 base.html: admin.css wird global geladen (Sticky-Basis vorhanden)",
      'href="/static/admin.css?=' in BASE or 'href="/static/admin.css?v=' in BASE)
check("F3 admin.css: .footer position:fixed + bottom:0 (am Sichtbereich-Unterrand)",
      re.search(r"\.footer\s*\{[^}]*position:\s*fixed[^}]*bottom:\s*0", ADM_CSS, re.S) is not None)
check("F4 admin.css: body ist Flex-Column mit 100dvh-Minimum",
      re.search(r"body\s*\{[^}]*display:\s*flex", ADM_CSS) is not None
      and re.search(r"min-height:\s*100dvh", ADM_CSS) is not None)
for tpl in ("password.html", "wiki.html", "blocklist.html", "modules.html",
            "api_doku.html"):
    with open(os.path.join(REPO, "app", "templates", tpl), encoding="utf-8") as f:
        check(f"F5 {tpl}: keine lokale .footer fixed-Regel mehr",
              ".footer { position: fixed" not in f.read())

# ── Daten-Setup ──────────────────────────────────────────────────────────────
def seed_user(pw="secret"):
    ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
               ("admin", ph, 1))
    db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
               ("normal", ph, 0))
    db.commit()
    db.close()


def seed_anlagen():
    db = sqlite3.connect(DB)
    rows = [
        # id 1: Alpha — mit Monitoring-Instanz (echter GetStats-Weg wäre möglich)
        ("Alpha", "https://anlage1.sub.example.de", "TelefonieMonitoring"),
        # id 2: Beta — für laufendes Update (IST kommt aus dem Log)
        ("Beta", "https://anlage2.sub.example.de", "TelefonieMonitoring"),
        # id 3: Gamma — OHNE Monitoring-Instanz → IST „—“ (echter Code-Weg)
        ("Gamma", "https://anlage3.sub.example.de", ""),
    ]
    for name, url, mon in rows:
        db.execute("INSERT INTO installations"
                   " (name, url, monitoring_instance_name, deployer_instance_name,"
                   "  deployer_token, is_starface10, oauth_client)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (name, url, mon, "Deployer", "tok", 1, "rest-client"))
    db.commit()
    db.close()


def add_plan(installation_id, version, minutes_from_now=120):
    at = (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
          ).replace(microsecond=0).isoformat()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO anlagen_update_plans"
               " (installation_id, version, update_url, scheduled_at)"
               " VALUES (?,?,?,?)",
               (installation_id, version, "http://updates.example/u.sfm", at))
    db.commit()
    db.close()
    return at


def add_running_log(installation_id, version_vor, version_nach):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO anlagen_update_log"
               " (installation_id, quelle, version_vor, version_nach,"
               "  angestossen_um, status)"
               " VALUES (?,?,?,?,?,?)",
               (installation_id, "direkt", version_vor, version_nach, at, "pruefen"))
    db.commit()
    db.close()
    return at


seed_user()
seed_anlagen()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "secret"})
assert r.status_code == 200 and r.json().get("status") == "ok", r.text

# Echte _anlagen_version für den Ohne-Instanz-Fall weiterverwenden; nur den
# RPC-Weg der Alpha-Anlage deterministisch faken (kein Netz im Test).
_real_anlagen_version = app_main._anlagen_version


def fake_anlagen_version(row):
    if "anlage1" in (row.get("url") or ""):
        return "10.0.2.0"
    return _real_anlagen_version(row)  # ohne Instanz → „—“ ohne RPC


app_main._anlagen_version = fake_anlagen_version

# ── 1) Geplante-Updates-Tabelle (F111) ───────────────────────────────────────
plan_at = add_plan(1, "10.0.3.0", minutes_from_now=120)          # Alpha → geplant
running_at = add_running_log(2, "10.0.1.0", "10.0.2.0")            # Beta → läuft
add_plan(3, "10.0.4.0", minutes_from_now=300)                    # Gamma → ohne Instanz

r = c.get("/")
html = r.text
check("1.1 GET / als Admin liefert Gesamt-Monitoring",
      r.status_code == 200 and "Gesamt-Monitoring" in html,
      f"status={r.status_code}")
check("1.2 Sektion 'Geplante Updates' vorhanden",
      "<h2>Geplante Updates</h2>" in html)
check("1.3 Alpha-Zeile: Anlagenname",
      f">Alpha<" in html, "Alpha fehlt")
check("1.4 Alpha-Zeile: URL",
      "https://anlage1.sub.example.de" in html)
check("1.5 Alpha-Zeile: Version IST (mock-geliefert)",
      ">10.0.2.0<" in html)
check("1.6 Alpha-Zeile: Update auf 10.0.3.0",
      ">10.0.3.0<" in html)
check("1.7 Alpha-Zeile: Datum und Uhrzeit (lokale Zeit)",
      utc_iso_zu_lokal_anzeige(plan_at) in html,
      f"erwartet {utc_iso_zu_lokal_anzeige(plan_at)}")
check("1.8 Gamma-Zeile: IST ist '—' (keine Monitoring-Instanz, echter Pfad)",
      f">Gamma<" in html
      and re.search(r">Gamma<.*?</td>\s*<td class=\"codes\">[^<]*</td>\s*<td>—</td>",
                    html, re.S) is not None,
      "Gamma-Zeile mit IST '—' nicht gefunden")

# ── 2) Laufend-Updates-Tabelle (F111) ────────────────────────────────────────
check("2.1 Sektion 'Aktuell laufende Updates' vorhanden",
      "<h2>Aktuell laufende Updates</h2>" in html)
check("2.2 Beta-Zeile: Anlagenname",
      f">Beta<" in html)
check("2.3 Beta-Zeile: Version IST = version_vor aus dem Log (10.0.1.0)",
      ">10.0.1.0<" in html)
check("2.4 Beta-Zeile: Update auf 10.0.2.0",
      ">10.0.2.0<" in html)
check("2.5 Beta-Zeile: Startzeitpunkt (lokale Zeit)",
      utc_iso_zu_lokal_anzeige(running_at) in html,
      f"erwartet {utc_iso_zu_lokal_anzeige(running_at)}")

# ── 3) Leerzustände ──────────────────────────────────────────────────────────
db = sqlite3.connect(DB)
db.execute("DELETE FROM anlagen_update_plans")
db.execute("DELETE FROM anlagen_update_log")
db.commit()
db.close()

r = c.get("/")
html = r.text
check("3.1 Leerzustand Geplant: 'Keine geplanten Updates.'",
      "Keine geplanten Updates." in html)
check("3.2 Leerzustand Laufend: 'Keine laufenden Updates.'",
      "Keine laufenden Updates." in html)
check("3.3 Leerzustand: Tabellenkopfzeilen bleiben sichtbar",
      "Datum und Uhrzeit" in html and "Startzeitpunkt" in html)

# ── 4) Nicht-Admin kommt weiterhin NICHT auf die Startseite ──────────────────
c2 = TestClient(app_main.app)
r2 = c2.post("/api/login", data={"username": "normal", "password": "secret"})
assert r2.status_code == 200 and r2.json().get("status") == "ok", r2.text
r3 = c2.get("/")
check("4.1 Normaluser: GET / redirectet auf /anlagen",
      bool(r3.history) and "/anlagen" in r3.history[0].headers.get("location", ""),
      f"history={[h.headers.get('location') for h in r3.history]}")

# ── 5) Footer-Semantik (F111-Nachtrag v1.0.116: fixiert am Viewport-Unterrand) ─
base_html = open(os.path.join(REPO, "app/templates/base.html"), encoding="utf-8").read()
admin_css = open(os.path.join(REPO, "app/static/admin.css"), encoding="utf-8").read()
check("5.1 base.html: keine Inline-'.footer { position: fixed'-Regel mehr",
      ".footer { position: fixed" not in base_html)
check("5.2 admin.css .footer: position:fixed + bottom:0 (klebt am Sichtbereich)",
      re.search(r"\.footer\s*\{[^}]*position:\s*fixed[^}]*bottom:\s*0",
                admin_css, re.S) is not None)
check("5.3 admin.css .footer: z-index: 50 (über Inhalt, unter Dialogen)",
      "z-index: 50" in admin_css)
_tpls = [os.path.join(REPO, "app/templates", t) for t in
         ("base.html", "admin_monitoring.html", "installation_monitoring.html",
          "blocklist.html", "api_doku.html", "modules.html", "monitoring.html",
          "password.html", "wiki.html")]
_miss = [os.path.basename(t) for t in _tpls
         if "calc(72px + env(safe-area-inset-bottom, 0px))"
         not in open(t, encoding="utf-8").read()]
check("5.4 Container-Unterkante calc(72px+safe-area) in allen 9 Templates (kein Overlay)",
      not _miss, f"fehlt in: {_miss or '-'}")
_mon = open(os.path.join(REPO, "app/templates/admin_monitoring.html"),
            encoding="utf-8").read()
check("5.5 Kiosk: Footer im Vollbild weiterhin ausgeblendet",
      "body.kiosk .header-wrap, body.kiosk .footer { display: none; }" in _mon)

print()
if FAILS:
    print(f"FEHLGESCHLAGEN: {len(FAILS)} Check(s) rot — {FAILS}")
    sys.exit(1)
print(f"ALLE {17 + 5} CHECKS OK (f111 Startseite + Footer-Semantik v1.0.116)")
sys.exit(0)
