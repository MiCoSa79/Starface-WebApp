#!/usr/bin/env python3
"""E2E-Test F60 (v1.0.27): Anlagen-Detail-Monitoring /monitoring/installations/{id}.

- Zugriff: Admins + Benutzer mit can_read auf die Anlage (Axel-Vorgabe)
- Anlagen-Dropdown NUR wenn der Nutzer mehrere Anlagen sehen darf
- 3 Kacheln: SIP-Trunks x/x (grün=alle / rot=mind. einer nicht), CPU-Last 1/5/15,
  Speicher belegt/gesamt + %
- 3 Verlaufs-Graphen (letzte Stunde): CPU 1/5/15, RAM %, RAM Total — InfluxDB
  system-Measurement; Fallback-Hinweis bei history.error / leeren Zeilen
- Auto-Refresh 10-s-Takt mit Countdown + Kiosk-Modus (Muster Admin-Monitoring)
- Einstieg: neue Detail-Spalte auf /monitoring (id_by_name in Route-Kontext)
"""
from pathlib import Path
import os, sys, sqlite3, tempfile
from urllib.parse import urlparse

sys.path.insert(0, "app")

DB = tempfile.mktemp(suffix=".db")
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

app_main.init_db()

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
import bcrypt


def mkuser(username, is_admin=0):
    conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                 (username, bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), is_admin))
    return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]


def mk_inst(name, url):
    return conn.execute(
        "INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) "
        "VALUES (?,?,?,1)", (name, url, "Mon" + name)).lastrowid


admin_id = mkuser("admin", 1)
bob_id = mkuser("bob", 0)
# A = alles ok (2/2 Provider, Systemwerte, Historie); B = 1 Trunk weg, leere Historie;
# C = alte Modul-Version ohne Systemwerte, History-Fehler; D = nie gepollt
a_id = mk_inst("Anlage A", "http://pbx-a.invalid")
b_id = mk_inst("Anlage B", "http://pbx-b.invalid")
c_id = mk_inst("Anlage C", "http://pbx-c.invalid")
d_id = mk_inst("Anlage D", "http://pbx-d.invalid")
# bob darf nur Anlage A sehen
conn.execute("INSERT INTO access (user_id, installation_id, can_read, can_write) VALUES (?,?,1,0)",
             (bob_id, a_id))
conn.commit()
conn.close()

# --- Fake Sammler-Status: Struktur wie monitoring.status(); Systemwerte (F60) ---
def fake_status():
    return {
        "running": True,
        "interval": 60,
        "influx_url": "http://influxdb:8086",
        "influx_bucket": "telefonie",
        "influx_configured": True,
        "last_run": 1725000100,
        "last_error": None,
        "total_runs": 12,
        "total_writes": 340,
        "installations": {
            "Anlage A": {"systemName": "pbx-a", "systemVersion": "10.0.2.5", "points": 120,
                         "ts": 1725000100,
                         "system": {"load1": 0.42, "load5": 0.38, "load15": 0.35,
                                    "mem_total": 16777216, "mem_free": 4194304,
                                    "mem_available": 10066330, "cpu_cores": 8},
                         "provider_summary": {"has_data": True, "all_ok": True, "count": 2,
                                              "connected": 2, "disconnected": []},
                         # Modul-Status wie im Sammler-Cache (v1.0.36: Detail-Tabelle
                         # liest hieraus — KEIN eigener Anlagen-Abruf)
                         "modules": {"ts": 1725000100, "list": [
                             {"name": "CallBlocker", "installed": True, "current": True,
                              "version_ist": 30, "version_soll": 30,
                              "vendor": "Axel Meiser - Kraemer IT", "instances": [],
                              "source": "own", "status": "ok"},
                             {"name": "TelefonieMonitoring", "installed": True, "current": False,
                              "version_ist": 8, "version_soll": 9,
                              "vendor": "Axel Meiser - Kraemer IT", "instances": [],
                              "source": "own", "status": "outdated"},
                             {"name": "NichtInstalliert", "installed": False, "current": False,
                              "version_ist": None, "version_soll": 42,
                              "vendor": "X", "instances": [], "source": "own",
                              "status": "missing"},
                             {"name": "ThirdPartyConnector", "installed": True, "current": False,
                              "version_ist": 2, "version_soll": 3,
                              "vendor": "Example GmbH", "instances": [],
                              "source": "third-party", "status": "outdated"}]}},
            "Anlage B": {"systemName": "pbx-b", "systemVersion": "10.0.1.9", "points": 90,
                         "ts": 1725000000,
                         "system": {"load1": 1.85, "load5": 1.52, "load15": 1.31,
                                    "mem_total": 8388608, "mem_free": 1048576,
                                    "mem_available": 2097152, "cpu_cores": 4},
                         "provider_summary": {"has_data": True, "all_ok": False, "count": 3,
                                              "connected": 2,
                                              "disconnected": ["SIP-Trunk 1 (Unregistered)"]}},
            "Anlage C": {"systemName": "pbx-c", "systemVersion": "10.0.0.1", "points": 60,
                         "ts": 1724999900,
                         # kein "system": ältere Modul-Version -> CPU/RAM-Kachel '—'
                         "provider_summary": {"has_data": True, "all_ok": False, "count": 4,
                                              "connected": 2,
                                              "disconnected": ["T-Online (Unregistered)"]},
                         "modules": {"error": "GetModuleStatus: fault (Test)"}},
        },
    }
app_main.monitoring.status = fake_status


# --- Fake InfluxDB-Verlauf (query_system_history ist im Sammler gemockt) ---
def fake_history(installation, minutes=60, cache_ttl=15.0):
    if installation == "Anlage A":
        rows = []
        base = 1724999400
        for i in range(10):
            rows.append({"t": base + i * 60,
                         "load1": 0.4 + i * 0.02,
                         "load5": 0.38, "load15": 0.35,
                         "mem_total": 16777216.0, "mem_free": 4194304.0,
                         "mem_available": 10066330.0})
        return {"rows": rows}
    if installation == "Anlage B":
        return {"rows": []}
    return {"error": "influx: connection refused"}  # C und D


app_main.monitoring.query_system_history = fake_history

c = TestClient(app_main.app)
c.follow_redirects = False  # Starlette 0.27: hartkodiert True
TEMPLATE_SRC = (Path(__file__).resolve().parent.parent / "app" / "templates"
                / "installation_monitoring.html").read_text(encoding="utf-8")
tsrc = TEMPLATE_SRC

fails = 0
checks = 0


def check(name, cond, detail=""):
    global checks, fails
    checks += 1
    print(("OK  " if cond else "FAIL") + f" {name}")
    if not cond:
        fails += 1
        if detail:
            print("     " + detail)


def login(username):
    r = c.post("/api/login", data={"username": username, "password": "pw123"})
    assert r.status_code == 200, (username, r.status_code, r.text)
    assert r.json()["status"] == "ok", (username, r.json())


# 1) Nicht eingeloggt -> Redirect auf "/" (Konvention /monitoring-Routen)
r = c.get(f"/monitoring/installations/{a_id}")
check("ohne Login -> Redirect /",
      r.status_code in (302, 307) and urlparse(r.headers.get("location", "")).path == "/",
      f"{r.status_code} {r.headers.get('location')}")

# 2) Bob ohne Leserecht (Anlage B) -> 403
login("bob")
r = c.get(f"/monitoring/installations/{b_id}")
check("kein Leserecht -> 403", r.status_code == 403, str(r.status_code))

# 3) Bob mit Leserecht (Anlage A) -> 200, KEIN Dropdown (nur 1 sichtbare Anlage), Kacheln
r = c.get(f"/monitoring/installations/{a_id}")
check("Detail-Seite 200 (bob, Leserecht)", r.status_code == 200, str(r.status_code))
body = r.text
check("Titel mit Anlagenname", f"Monitoring: Anlage A" in body)
check("KEIN Dropdown wenn nur 1 Anlage sichtbar", 'id="inst-select"' not in body,
      "bob sieht nur Anlage A")
check("Zurueck-Link zur Uebersicht", 'href="/monitoring"' in body)
check("Kachel SIP vorhanden", 'id="kpi-sip-value"' in body)
check("Kachel CPU: drei Werte 1/5/15 (Axel)", all(x in body for x in ('id="kpi-cpu1"', 'id="kpi-cpu5"', 'id="kpi-cpu15"', 'class="kpi-multi-label">1 min', 'class="kpi-multi-label">5 min', 'class="kpi-multi-label">15 min', 'id="kpi-cpu-cores"')))
check("Kachel RAM vorhanden", 'id="kpi-mem-value"' in body)
check("Kachel-Titel SIP-Trunks/Provider", "SIP-Trunks/Provider" in body)
check("Kachel-Titel CPU-Last", "CPU-Last aktuell" in body)
check("Kachel-Titel Speicher", "Speicher-Auslastung" in body)
check("Graph CPU-Container", 'id="chart-cpu"' in body)
check("Graph RAM%-Container", 'id="chart-mem-pct"' in body)
check("Graph RAM-Total-Container", 'id="chart-mem-total"' in body)
check("Y-Achse RAM % immer bis 100 (Axel)", 'yFixedMax: 100' in body and 'floorYMax: 50' not in body)
check("90-%-Schwelle RAM % (Axel)", 'threshold: 90' in body and "'90 %'" in body)
check("90-%-Schwelle auch bei Speicher Total (Axel)", 'totMax ? kbToBytes(totMax * 0.9)' in body and "'90 % von Gesamt'" in body)
check("Gesamtspeicher-Linie nicht gestrichelt (Axel)", "color: '#9e9e9e', y:" in body and "dash: '6 4'" not in body)
check("90-%-Vermerk in Legende statt im Graph (Axel)", all(x in body for x in ("90 % kritisch", "90 % von Gesamt (kritisch)", 'class="dashline"')))
check("kein 90-%-Text mehr im SVG-Graph", "ttxt.textContent = opts.thresholdLabel" not in body)
check("Kiosk-Banner: Anlagen-Name + URL zentriert (Axel)", all(x in body for x in ('id="kiosk-name"', 'id="kiosk-url"', "kiosk-banner", "body.kiosk .kiosk-banner { display: block; }")))
check("Kiosk-Name in Rot wie Überschriften (Axel)", '.kiosk-name { font-size: 24px; font-weight: 700; color: #e94560;' in body)
check("Modul-Tabelle unten (Axel): Karte + Spalten im Template", all(x in tsrc for x in (
    'id="card-inst-modules"', '>Ist-Version</th>', '>Aktuellste Version</th>',
    'id="mod-tbl-own"', 'id="mod-tbl-third"', 'id="mod-rows-own"', 'id="mod-rows-third"',
    'id="mod-hint"', 'mod-badge')))
check("Modul-Tabelle: Spaltenkopf nur EINMAL (Drittanbieter ohne Kopf, Axel)", tsrc.count('>Ist-Version</th>') == 1)
check("Modul-Karte: volle Breite unter den Charts (Grid-Durchstich, Axel)", 'grid-column: 1 / -1' in body)
check("Modul-Gruppen: eigene oben, Drittanbieter unten (Axel)", all(x in body for x in (
    'Eigene Module', 'Drittanbietermodule', 'ThirdPartyConnector', 'mod-grp')))
check("Modul-Karte rendert: Tabelle mit Modulen (Anlage A)", all(x in body for x in ('id="card-inst-modules"', 'CallBlocker', 'TelefonieMonitoring', 'id="mod-rows-own"')))
check("Modul-Karte: nur installierte Module (Axel) — kein 'NichtInstalliert'", 'NichtInstalliert' not in body and '>42<' not in body)
check("Modul-Karte: outdated-Zeile rot + Badge 'Update verfügbar'", all(x in body for x in ('mod-outdated', 'Update verfügbar', '>8<')))
check("Modul-Refresh alle 5 min, nicht alle 10 s (Axel)", all(x in body for x in ('refreshModules', 'setInterval(refreshModules, 300000)', '/api/monitoring/modules/')))
check("Modul-Karte: Daten aus Sammler-Cache, kein separater Abruf (Axel)", 'kein separater Anlagen-Abruf' in body)
# Hinweis-Fall: Anlage C (modules.error im Poll)
login("admin")
rc_ = c.get(f"/monitoring/installations/{c_id}")
bc_ = rc_.text
check("Modul-Karte: RPC-Fehler -> Hinweis statt kaputt", 'id="mod-hint"' in bc_ and 'Keine Modul-Daten verfügbar' in bc_ and rc_.status_code == 200)

# --- API /api/monitoring/modules/{id}: Rechte + Struktur ---
login("admin")
rm = c.get(f"/api/monitoring/modules/{a_id}")
rj = {}
try: rj = rm.json()
except Exception: pass
check("API Modul-Liste 200 + ok:true + modules-Key", rm.status_code == 200 and rj.get("ok") is True and "modules" in rj)
check("API Modul-Liste: nur installierte (3 statt 4)", isinstance(rj.get("modules"), list) and len(rj.get("modules")) == 3)
check("API Modul-Liste: Drittanbieter getrennt lieferbar (source)", any(m.get("source") == "third-party" for m in (rj.get("modules") or [])))
check("Kacheln: 3 in einer Zeile, Normalmodus wie Kiosk (Axel)", 'grid-template-columns: repeat(3, minmax(0, 1fr))' in body)
rmc = c.get(f"/api/monitoring/modules/{c_id}")
rjc = {}
try: rjc = rmc.json()
except Exception: pass
check("API Modul-Liste: RPC-Fehler -> modules null (kein 500)", rmc.status_code == 200 and rjc.get("modules") is None)
login("bob")
rb = c.get(f"/api/monitoring/modules/{b_id}")
check("API Modul-Liste: bob ohne Recht auf B → 403", rb.status_code == 403)
check("Ueberschrift Letzte Stunde", "Letzte Stunde" in body)
check("INITIAL-JSON (Server-Render)", "var INITIAL" in body and '"name": "Anlage A"' in body)
check("INITIAL Systemwerte (load1)", '"load1": 0.42' in body)
check("INITIAL Systemwerte (mem_total kB)", '"mem_total": 16777216' in body)
check("INITIAL Provider (2/2)", '"connected": 2' in body and '"all_ok": true' in body)
check("INITIAL Historie vorhanden", '"rows"' in body and '"load5": 0.38' in body)
check("Countdown-Element #refresh-countdown", 'id="refresh-countdown"' in body)
check("Countdown-Text", "aktualisiert sich automatisch in" in body)
check("Refresh-Takt 10s", "REFRESH_INTERVAL_S = 10" in body)
check("Initialer Countdown 10 (Kopf)", 'id="refresh-countdown" style="color:#bbb;">10' in body)
check("Kiosk-Countdown-Element", 'id="refresh-countdown-kiosk-num"' in body)
check("Kiosk-Countdown initial 10", 'id="refresh-countdown-kiosk-num" style="color:#bbb;">10' in body)

# 4) /monitoring-Übersicht: Detail-Spalte vorhanden (bob sieht nur A)
r = c.get("/monitoring")
check("/monitoring 200 (bob)", r.status_code == 200, str(r.status_code))
check("Detail-Link Anlage A (bob)", f'href="/monitoring/installations/{a_id}"' in r.text)
check("KEIN Detail-Link Anlage B (bob)", f'href="/monitoring/installations/{b_id}"' not in r.text)

# 4b) renderRows (JS) baut die Detail-Zelle mit — Live-Bugs:
# v1.0.27: renderRows baute keine Detail-Zelle (Spalte rutschte, Grafana-Icon rückte in "Detail").
# v1.0.29(live): tojson im HTML-Attribut bracht das Attribut ("Anlage A" → data-idmap="{...)
#   → getAttribute lieferte '{' → JSON.parse-Fehler → idmap={} → Auge-Link ohne ID → 404 "Not Found".
# Fix: idmap als <script type="application/json"> (tojson ist dafür gedacht); der Test parst
# den JSON-Inhalt wirklich (String-Checks hätten den Attribut-Bug nie gefangen).
import json as _json, html as _html, re as _re
check("renderRows baut Detail-Zelle (tdDetail)", "var tdDetail" in r.text
      and "ad.href = '/monitoring/installations/'" in r.text)
check("renderRows No-Data-colSpan 8", "td0.colSpan = 8" in r.text)
check("idmap als script-Tag (kein data-idmap-Attribut)", 'data-idmap=' not in r.text
      and '<script type="application/json" id="inst-idmap">' in r.text)
check("renderRows liest idmap per getElementById",
      "getElementById('inst-idmap')" in r.text and "JSON.parse(idmapEl.textContent)" in r.text)
_m = _re.search(r'<script type="application/json" id="inst-idmap">(.*?)</script>', r.text, _re.S)
_idmap_ok = False
if _m:
    try:
        _idmap_data = _json.loads(_html.unescape(_m.group(1).strip()))
        _idmap_ok = isinstance(_idmap_data, dict) and _idmap_data.get("Anlage A") == a_id
    except Exception:
        _idmap_ok = False
check("idmap-JSON parst + enthält Anlage A (gefiltert)", _idmap_ok)

# 5) Admin: Dropdown vorhanden (4 Anlagen) + Kacheln ohne Systemdaten bei C
login("admin")
r = c.get(f"/monitoring/installations/{a_id}")
body = r.text
check("Dropdown vorhanden (Admin, 4 Anlagen)", 'id="inst-select"' in body and body.count("option value=") >= 4)
check("Dropdown-Option aktuelle Anlage selected", f'value="/monitoring/installations/{a_id}"' in body and "selected" in body)
r = c.get(f"/monitoring/installations/{c_id}")
check("Detail C 200 (Admin)", r.status_code == 200, str(r.status_code))
check("C: kein System -> INITIAL system null", '"system": null' in r.text,
      "ältere Modul-Version liefert keine Systemwerte")
check("C: History-Fehler im INITIAL", '"history": {"error"' in r.text or '"error": "influx' in r.text)

# 6) API /api/monitoring/detail/{id} (Admin)
r = c.get(f"/api/monitoring/detail/{a_id}")
check("API 200", r.status_code == 200, str(r.status_code))
js = r.json()
check("API provider 2/2 ok", js["provider"]["connected"] == 2 and js["provider"]["all_ok"] is True,
      str(js.get("provider")))
check("API system load1", js["system"]["load1"] == 0.42, str(js.get("system")))
check("API system mem_total", js["system"]["mem_total"] == 16777216)
check("API history 10 Zeilen", len(js["history"]["rows"]) == 10, str(len(js.get("history", {}).get("rows", []))))
check("API history row[0] Felder", js["history"]["rows"][0]["load5"] == 0.38 and
      js["history"]["rows"][0]["mem_available"] == 10066330.0)
check("API running/last_run durchgereicht", js.get("running") is True and js.get("last_run") == 1725000100)
r = c.get(f"/api/monitoring/detail/{b_id}")
js = r.json()
check("API B: history rows leer (Fallback)", js["history"]["rows"] == [], str(js.get("history")))
r = c.get(f"/api/monitoring/detail/{c_id}")
js = r.json()
check("API C: history.error", "error" in js["history"], str(js.get("history")))
check("API C: system fehlt (kein Fehler)", js.get("system") is None)
r = c.get(f"/api/monitoring/detail/99999")
check("API unbekannte Anlage 404", r.status_code == 404, str(r.status_code))

# 7) API-Rechte: ohne Login 401; bob ohne Recht auf B 403; bob mit Recht auf A 200
c2 = TestClient(app_main.app)
c2.follow_redirects = False
r = c2.get(f"/api/monitoring/detail/{a_id}")
check("API ohne Login 401", r.status_code == 401, str(r.status_code))
login("bob")
r = c.get(f"/api/monitoring/detail/{b_id}")
check("API bob ohne Recht -> 403", r.status_code == 403, str(r.status_code))
r = c.get(f"/api/monitoring/detail/{a_id}")
check("API bob mit Leserecht -> 200", r.status_code == 200, str(r.status_code))
check("API bob: provider ok", r.json()["provider"]["connected"] == 2)

# 8) Kiosk-/Vollbild-Modus (Muster v1.0.20–v1.0.26)
login("admin")
r = c.get(f"/monitoring/installations/{a_id}?kiosk=1")
body = r.text
check("Vollbild-Button #fs-btn", 'id="fs-btn"' in body)
check("Vollbild-Beenden #fs-exit", 'id="fs-exit"' in body)
check("Kiosk-CSS Header aus", "body.kiosk .header-wrap" in body)
check("Kiosk-CSS Footer aus", "body.kiosk .footer" in body)
check("Kiosk-CSS Seitenkopf aus", "body.kiosk .monitor-head" in body)
check("Kiosk-Countdown inline (Sammler-Zeile)", '<span class="kiosk-countdown">Aktualisiert in' in body)
check("Kiosk-Countdown-CSS", "body.kiosk .kiosk-countdown" in body)
check("Enter-Funktion enterDetailFs", "function enterDetailFs" in body)
check("Exit-Funktion exitDetailFs", "function exitDetailFs" in body)
check("Kiosk-URL-Start ?kiosk=1", "get('kiosk') === '1'" in body)
check("ESC/Fullscreenchange", "fullscreenchange" in body)
check("Auto-Hide .fs-hidden", ".fs-hidden" in body)
check("Auto-Hide fsShow/Timer 2500", "function fsShow" in body and "2500" in body)
check("Auto-Hide Mausbewegung/Touch", "addEventListener('mousemove', fsWake)" in body and
      "addEventListener('touchstart', fsWake)" in body)

# 9) Graphen-Zeichnung (Dark Design, kein CDN)
check("drawChart-Funktion", "function drawChart" in body)
check("CPU-Farben 1/5/15", "#4fc3f7" in body and "#ffca28" in body and "#ab47bc" in body)
check("RAM%-Farbe", "#ffa726" in body)
check("RAM-Total-Farben", "#9e9e9e" in body and "dash" in body)
check("Legend CPU", "1 min" in body and "5 min" in body and "15 min" in body)
check("Legend RAM Total", "gesamt" in body and "belegt" in body)
check("Chart-Legende aus SVG (eigenes Rendering, kein Chart.js)", "document.createElementNS" in body)

# 10) Admin: /monitoring hat Detail-Links für alle gepollten Anlagen
r = c.get("/monitoring")
check("/monitoring 200 (admin)", r.status_code == 200, str(r.status_code))
check("Detail-Spalte im Tabellenkopf", "<th style=\"width:56px;\">Detail</th>" in r.text)
check("Detail-Link Anlage A", f'href="/monitoring/installations/{a_id}"' in r.text)
check("Detail-Link Anlage B", f'href="/monitoring/installations/{b_id}"' in r.text)
check("Detail-Link Anlage C", f'href="/monitoring/installations/{c_id}"' in r.text)

print(f"\n{checks - fails}/{checks} Checks OK")
sys.exit(1 if fails else 0)
