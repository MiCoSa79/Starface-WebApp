#!/usr/bin/env python3
"""E2E-Test F59 (v1.0.18): Admin-Monitoring-Seite /admin/monitoring.

- 3 Kennzahlen: Anlagen eingerichtet (Karte 1), Anlagen mit Provider-Fehlern
  (Karte 2), fehlerhafte SIP-Trunks/Provider (Karte 3) — aus _admin_monitoring_summary
- Fehlerliste unter den Karten: nur Anlagen mit disconnected > 0
- Auto-Refresh: Countdown „aktualisiert sich automatisch in X s“ (5-s-Takt über
  1-s-Tick, Overlap-Schutz refreshBusy) + /api/monitoring/admin
- Rechte: Seite + API nur für Admins; User -> /dashboard; Gäste -> /
- Grafana-Link bleibt (paralleler Betrieb); Admin-Seite verlinkt auf die neue Seite
"""
import os, sys, sqlite3, tempfile

sys.path.insert(0, "app")

DB = tempfile.mktemp(suffix=".db")
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

app_main.init_db()  # echte Tabellen (users, installations, access, sessions, ...)

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
# A = alle Provider ok; B = 1 Trunk weg; C = 2 Trunks weg; D = nie gepollt -> no_data
a_id = mk_inst("Anlage A", "http://pbx-a.invalid")
b_id = mk_inst("Anlage B", "http://pbx-b.invalid")
c_id = mk_inst("Anlage C", "http://pbx-c.invalid")
d_id = mk_inst("Anlage D", "http://pbx-d.invalid")
conn.commit()
conn.close()

# --- Fake Sammler-Status: exakt die Struktur von monitoring.status() ---
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
                         "provider_summary": {"has_data": True, "all_ok": True, "count": 2,
                                              "connected": 2, "disconnected": []}},
            "Anlage B": {"systemName": "pbx-b", "systemVersion": "10.0.1.9", "points": 90,
                         "ts": 1725000000,
                         "provider_summary": {"has_data": True, "all_ok": False, "count": 3,
                                              "connected": 2,
                                              "disconnected": ["SIP-Trunk 1 (Unregistered)"]}},
            "Anlage C": {"systemName": "pbx-c", "systemVersion": "10.0.0.1", "points": 60,
                         "ts": 1724999900,
                         "provider_summary": {"has_data": True, "all_ok": False, "count": 4,
                                              "connected": 2,
                                              "disconnected": ["T-Online (Unregistered)",
                                                               "SIP-Partner (NotRegistered)"]}},
        },
    }
app_main.monitoring.status = fake_status

c = TestClient(app_main.app)
c.follow_redirects = False  # Starlette 0.27: hartkodiert True

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


# 1) Nicht eingeloggt -> Redirect auf /dashboard (Konvention Admin-Routen)
r = c.get("/admin/monitoring")
check("ohne Login -> Redirect /dashboard",
      r.status_code in (302, 307) and r.headers.get("location", "").endswith("/dashboard"),
      f"{r.status_code} {r.headers.get('location')}")

# 2) User (nicht Admin) -> Redirect /dashboard
login("bob")
r = c.get("/admin/monitoring")
check("User -> Redirect /dashboard",
      r.status_code in (302, 307) and r.headers.get("location", "").endswith("/dashboard"),
      f"{r.status_code} {r.headers.get('location')}")

# 3) Admin -> 200 + Kennzahlen + Fehlerliste + Refresh-Marker + Grafana
login("admin")
r = c.get("/admin/monitoring")
check("/admin/monitoring 200", r.status_code == 200, str(r.status_code))
body = r.text
check("Titel Admin-Monitoring", "Admin-Monitoring" in body)
check("K1 Anlagen eingerichtet = 4", 'id="kpi-total">4</div>' in body)
check("K2 Anlagen mit Provider-Fehlern = 2", 'id="kpi-failed-inst">2</div>' in body)
check("K3 fehlerhafte SIP-Trunks/Provider = 3", 'id="kpi-failed-trunks">3</div>' in body)
check("Fehlerliste: Anlage B", "Anlage B" in body)
check("Fehlerliste: Anlage C", "Anlage C" in body)
check("Fehlerliste: Trunk SIP-Trunk 1 (Unregistered)", "SIP-Trunk 1 (Unregistered)" in body)
check("Fehlerliste: Trunk T-Online (Unregistered)", "T-Online (Unregistered)" in body)
check("Fehlerliste: Trunk SIP-Partner (NotRegistered)", "SIP-Partner (NotRegistered)" in body)
check("ok-Anlage A NICHT in Fehlerliste", "Anlage A" not in body)
check("no-data-Hinweis (Anlage D)", "1 Anlage(n) ohne Monitoring-Daten" in body)
check("Verbunden-Badge B (2 von 3)", ">2 von 3 verbunden</span>" in body,
      "erwartet: >2 von 3 verbunden</span>")
check("Edit-Link Anlage B", f"/admin/installations/{b_id}/edit" in body)
check("Edit-Link Anlage C", f"/admin/installations/{c_id}/edit" in body)
check("Countdown-Element #refresh-countdown", 'id="refresh-countdown"' in body)
check("Countdown-Text 'automatisch in X s'", "aktualisiert sich automatisch in" in body)
check("Refresh-Takt 10s ueber 1s-Tick (kein 15000 mehr)", "REFRESH_INTERVAL_S = 10" in body and "15000" not in body)
check("Initialer Countdown-Wert 10 (Kopf)", 'id="refresh-countdown" style="color:#bbb;">10' in body)
check("Initialer Countdown-Wert 10 (Kiosk)", 'id="refresh-countdown-kiosk-num" style="color:#bbb;">10' in body)
check("Countdown-Funktion updateRefreshCountdown", "function updateRefreshCountdown" in body)
check("Overlap-Schutz refreshBusy", "refreshBusy" in body)
check("InfluxDB-Hinweis komplett entfernt (Normal- und Kiosk-Modus)", "sum-influx" not in body and "InfluxDB:" not in body)
check("Kein .kiosk-hide-Rest im Template", "kiosk-hide" not in body)
check("Kiosk-Refresh-Countdown vorhanden", 'id="refresh-countdown-kiosk-num"' in body)
check("Kiosk-Countdown an InfluxDB-Stelle (Sammler-Zeile)", '<span class="kiosk-countdown">Aktualisiert in' in body)
check("Kiosk-Countdown inline via body.kiosk .kiosk-countdown", "body.kiosk .kiosk-countdown" in body)
check("Kiosk-Auto-Scroll (Axel): Admin-Seite — nur Kiosk + Zyklus + Stop bei Rückkehr", all(x in body for x in (
    'Kiosk-Auto-Scroll, Admin-Monitoring',
    'if (document.body.classList.contains(\'kiosk\')) start(); else stop();',
    'await sleep(3000)', 'smoothTo(maxY, 6000)')))
check("Refresh-API /api/monitoring/admin", "/api/monitoring/admin" in body)
check("Grafana-Admin-Link (parallel)", "Grafana Admin-Übersicht" in body)
check("Grafana-Detail-Link Anlage B", f"/d/starface-anlage-detail/?var-installation=Anlage%20B" in body)

# 4) API /api/monitoring/admin (Admin): exakte Kennzahlen
r = c.get("/api/monitoring/admin")
check("API 200", r.status_code == 200, str(r.status_code))
js = r.json()
check("API total=4", js["total"] == 4, str(js.get("total")))
check("API failed_inst=2", js["failed_inst"] == 2, str(js.get("failed_inst")))
check("API failed_trunks=3", js["failed_trunks"] == 3, str(js.get("failed_trunks")))
check("API no_data=1", js["no_data"] == 1, str(js.get("no_data")))
check("API items=3 (nur gepollte)", len(js["items"]) == 3, str(len(js.get("items", []))))
by_name = {it["name"]: it for it in js["items"]}
check("API item B disconnected_count=1", by_name.get("Anlage B", {}).get("disconnected_count") == 1,
      str(by_name.get("Anlage B")))
check("API item C disconnected_count=2", by_name.get("Anlage C", {}).get("disconnected_count") == 2,
      str(by_name.get("Anlage C")))
check("API running/last_run durchgereicht", js.get("running") is True and js.get("last_run") == 1725000100,
      str(js.get("running")))

# 5) API ohne Login -> 401
c2 = TestClient(app_main.app)
c2.follow_redirects = False
r = c2.get("/api/monitoring/admin")
check("API ohne Login 401", r.status_code == 401, str(r.status_code))

# 6) Full-Screen/Kiosk-Modus (v1.0.20, Axel-Wunsch): Header/Footer/Browser-UI ausblendbar
check("Vollbild-Button #fs-btn", 'id="fs-btn"' in body)
check("Vollbild-Beenden-Button #fs-exit", 'id="fs-exit"' in body)
check("Kiosk-CSS blendet Header aus", "body.kiosk .header-wrap" in body)
check("Kiosk-CSS blendet Footer aus", "body.kiosk .footer" in body)
check("Kiosk-CSS blendet Seitenkopf aus", "body.kiosk .monitor-head" in body)
check("Enter-Funktion enterAdminFs", "function enterAdminFs" in body)
check("Exit-Funktion exitAdminFs", "function exitAdminFs" in body)
check("Kiosk-URL-Start ?kiosk=1", "get('kiosk') === '1'" in body)
check("ESC/Fullscreenchange-Beenden", "function fullscreenchange" in body or "fullscreenchange" in body)
check("Auto-Hide-CSS .fs-hidden", ".fs-hidden" in body)
check("Auto-Hide-Einblendung fsShow", "function fsShow" in body)
check("Auto-Hide-Timer 2500ms", "2500" in body and "setTimeout" in body)
check("Auto-Hide via Mausbewegung", "addEventListener('mousemove', fsWake)" in body)
check("Auto-Hide via Touch", "addEventListener('touchstart', fsWake)" in body)

# 7) Admin-Seite verlinkt auf die neue Seite (Einstieg)
r = c.get("/admin")
check("/admin 200 (Admin)", r.status_code == 200, str(r.status_code))
check("/admin verlinkt Admin-Monitoring", 'href="/admin/monitoring"' in r.text)

print(f"\n{checks - fails}/{checks} Checks OK")
sys.exit(1 if fails else 0)
