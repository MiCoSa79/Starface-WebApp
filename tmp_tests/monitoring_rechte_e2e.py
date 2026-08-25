#!/usr/bin/env python3
"""E2E-Test v0.0.120: /monitoring rechtebasiert (Admin alle, User nur can_read),
Grafana-Link-Spalte je Anlage, /admin/monitoring-Redirect, API-Filter, Nav-Sichtbarkeit."""
import os, sys, sqlite3, tempfile

sys.path.insert(0, "app")

# frische DB
DB = tempfile.mktemp(suffix=".db")
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

app_main.init_db()  # echte Tabellen (users, installations, access, sessions, ...)

# --- Testdaten (in die echte Struktur) ---
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
import bcrypt

def mkuser(username, is_admin=0):
    conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
                 (username, bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), is_admin))
    return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]

admin_id = mkuser("admin", 1)
bob_id = mkuser("bob", 0)
eve_id = mkuser("eve", 0)

aid = conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES ('Testanlage A','http://pbx-a.invalid','MonA',1)").lastrowid
bid = conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES ('Testanlage B','http://pbx-b.invalid','MonB',1)").lastrowid
conn.execute("INSERT INTO access (user_id, installation_id, can_read, can_write) VALUES (?,?,1,0)", (bob_id, aid))
conn.commit()
conn.close()

# --- Fake-Status (monitoring.status()) ---
def fake_status():
    return {
        "running": True, "last_poll": 1725000000, "influx_configured": True,
        "installations": {
            "Testanlage A": {"systemName": "pbx-a", "systemVersion": "10.0.2.5", "points": 120,
                             "ts": 1725000000, "provider_summary": {"has_data": True, "all_ok": True, "count": 2}},
            "Testanlage B": {"systemName": "pbx-b", "systemVersion": "10.0.1.9", "points": 90,
                             "ts": 1724999900, "provider_summary": {"has_data": True, "all_ok": False, "count": 3,
                             "connected": 2, "disconnected": ["sip2@pbx-b"]}},
        },
        "last_error": None,
    }
app_main.monitoring.status = fake_status

c = TestClient(app_main.app)
c.follow_redirects = False  # Starlette 0.27: hartkodiert True

def login(username):
    r = c.post("/api/login", data={"username": username, "password": "pw123"})
    assert r.status_code == 200, (username, r.status_code, r.text)
    assert r.json()["status"] == "ok", (username, r.json())

ok = 0

# 1) Nicht eingeloggt → Redirect auf "/"
r = c.get("/monitoring")
assert r.status_code in (302, 307) and r.headers.get("location", "").rstrip("/") in ("", "/"), (r.status_code, r.headers.get("location"))
ok += 1
print("1. nicht eingeloggt -> Redirect  OK")

# 2) Admin: alle Anlagen + 2 Links
login("admin")
r = c.get("/monitoring")
assert r.status_code == 200, r.status_code
body = r.text
assert "Testanlage A" in body and "Testanlage B" in body, "Admin muss beide Anlagen sehen"
assert body.count('class="grafana-dl"') == 2, f"Admin erwartet 2 Icon-Buttons, hat {body.count('grafana-dl')}"
assert "var-installation=Testanlage+A" in body.replace("Testanlage%20A", "Testanlage+A") or "var-installation=Testanlage%20A" in body.replace("+", "%20") or "var-installation=Testanlage+A" in body, "URL-Encode des Anlagennamens im Link fehlt"
assert "starface-anlage-detail" in body and "kiosk=1&hideLogo" in body, "Grafana-UID oder kiosk fehlt im Link"
ok += 1
print("2. Admin: beide Anlagen + 2 Links + korrekte URL  OK")

# 3) Bob (can_read nur A): nur A + 1 Link; B NICHT
login("bob")
r = c.get("/monitoring")
assert r.status_code == 200
body = r.text
assert "Testanlage A" in body, "Bob muss Anlage A sehen"
assert "Testanlage B" not in body, "Bob darf Anlage B NICHT sehen"
assert body.count('class="grafana-dl"') == 1, f"Bob erwartet genau 1 Icon-Button, hat {body.count('grafana-dl')}"
assert "/admin/monitoring" not in body, "Nav darf /admin/monitoring nicht mehr verlinken"
assert 'href="/monitoring"' in body, "Nav-Link /monitoring fehlt für Bob"
ok += 1
print("3. Bob: nur Anlage A + exakt 1 Link + Nav  OK")

# 4) Eve (keine Rechte): leere Liste + Hinweis, 0 Links
login("eve")
r = c.get("/monitoring")
assert r.status_code == 200
body = r.text
assert "Testanlage A" not in body and "Testanlage B" not in body, "Eve darf keine Anlage sehen"
assert body.count('class="grafana-dl"') == 0
assert "Lese-Rechte" in body, "Hinweis für User ohne Rechte fehlt"
ok += 1
print("4. Eve: keine Anlage, kein Link, Hinweis  OK")

# 5) /admin/monitoring -> Redirect auf /monitoring
login("admin")
r = c.get("/admin/monitoring")
assert r.status_code in (302, 307) and r.headers.get("location", "").endswith("/monitoring"), (r.status_code, r.headers.get("location"))
ok += 1
print("5. /admin/monitoring -> /monitoring  OK")

# 6) API gefiltert: Bob nur A, Admin beide, ohne Login 401
login("bob")
r = c.get("/api/monitoring/status")
js = r.json()
assert set(js["installations"].keys()) == {"Testanlage A"}, js["installations"].keys()
ok += 1
login("admin")
r = c.get("/api/monitoring/status")
assert set(r.json()["installations"].keys()) == {"Testanlage A", "Testanlage B"}
ok += 1
c2 = TestClient(app_main.app)
c2.follow_redirects = False
r = c2.get("/api/monitoring/status")
assert r.status_code == 401
ok += 1
print("6. API: Bob nur A / Admin beide / ohne Login 401  OK")

# 7) Dashboard-Nav enthält Monitoring-Link für alle eingeloggten User
login("eve")
r = c.get("/dashboard")
assert r.status_code == 200 and 'href="/monitoring"' in r.text, "Nav-Monitoring fehlt auf Dashboard"
ok += 1
print("7. Nav-Link /monitoring auf /dashboard für Eve  OK")

# 8) Admin /dashboard: 2 Karten, je 1 grafana-dl-Link
login("admin")
r = c.get("/dashboard")
assert r.status_code == 200, r.status_code
body = r.text
assert body.count('class="card"') == 2, "Anzahl Karten != 2"
assert body.count('class="grafana-dl"') == 2, "Admin erwartet 2 Dashboard-Links auf /dashboard"
assert "Testanlage+A" in body.replace("Testanlage%20A", "Testanlage+A"), "urlencode des Anlagennamens fehlt im Dashboard-Link"
assert "starface-anlage-detail" in body, "Grafana-UID fehlt im Dashboard-Link"
ok += 1
print("8. Admin /dashboard: 2 Karten + 2 Links + korrekte URL  OK")

# 9) Bob /dashboard: nur Anlage A sichtbar (can_read), genau 1 Link
login("bob")
r = c.get("/dashboard")
body = r.text
assert "Testanlage A" in body and "Testanlage B" not in body, "Bob sieht auf /dashboard die falsche Anlagenmenge"
assert body.count('class="card"') == 1 and body.count('class="grafana-dl"') == 1, "Bob: Karten/Links-Anzahl falsch"
ok += 1
print("9. Bob /dashboard: 1 Karte + 1 Link (nur can_read)  OK")

# 10) Eve /dashboard: keine Karten, keine Links
login("eve")
r = c.get("/dashboard")
body = r.text
assert body.count('class="card"') == 0 and body.count('class="grafana-dl"') == 0, "Eve darf keine Karten/Links sehen"
ok += 1
print("10. Eve /dashboard: 0 Karten, 0 Links  OK")

# 11) Admin-Einstellung: Grafana-Basis-URL hinterlegen -> Links nutzen die Domäne
login("admin")
r = c.post("/admin/settings", data={"grafana_base_url": "https://monitoring.meiser.family"})
assert r.status_code == 303 and "set_ok=1" in r.headers.get("location", ""), (r.status_code, r.headers.get("location"))
r = c.get("/dashboard")
body = r.text
assert "https://monitoring.meiser.family/d/starface-anlage-detail/?var-installation=Testanlage+A" in body.replace("Testanlage%20A", "Testanlage+A"), "Dashboard-Link nutzt nicht die Admin-Domäne"
assert "10.0.25.60" not in body, "Fallback-IP darf nicht mehr auftauchen"
r = c.get("/monitoring")
assert "https://monitoring.meiser.family/d/starface-anlage-detail/" in r.text, "Monitoring-Link nutzt nicht die Admin-Domäne"
r = c.get("/admin")
body = r.text
assert 'value="https://monitoring.meiser.family"' in body, "Admin-Formular zeigt hinterlegte URL nicht"
ok += 1
print("11. Admin-Domäne wirkt auf Startseite + Monitoring + Formular  OK")

# 12) Feld leeren -> Fallback (Env -> Default-IP)
r = c.post("/admin/settings", data={"grafana_base_url": ""})
assert r.status_code == 303
r = c.get("/dashboard")
body = r.text
assert "10.0.25.60:8894/d/starface-anlage-detail/" in body, "Leerer Wert muss auf Fallback-URL zurücksetzen"
ok += 1
print("12. Leerer Wert -> Fallback-URL  OK")

# 13) Admin-Übersicht-Link: NUR Admin auf /monitoring, Bob nicht
login("admin")
r = c.get("/monitoring")
assert "starface-admin-uebersicht" in r.text and "kiosk=1&hideLogo" in r.text, "Admin-Übersicht-Link oder kiosk fehlt auf /monitoring"
login("bob")
r = c.get("/monitoring")
body = r.text
assert "starface-admin-uebersicht" not in body, "Bob darf den Admin-Übersicht-Link NICHT sehen"
ok += 1
print("13. Admin-Übersicht-Link nur für Admins (Monitoring)  OK")

# 14) Admin-Seite: Einstellungen-Karte enthält den Admin-Übersicht-Link
login("admin")
r = c.get("/admin")
body = r.text
assert "starface-admin-uebersicht" in body and "Grafana Admin-Übersicht öffnen" in body and "kiosk=1&hideLogo" in body, "Admin-Seite: Admin-Übersicht-Link/kiosk fehlt"
ok += 1
print("14. Admin-Seite: Admin-Übersicht-Link in Einstellungen  OK")

# 15) Monitoring-Auto-Refresh: JS-Marker + tbody auf der Monitoring-Seite (Admin)
login("admin")
r = c.get("/monitoring")
body = r.text
assert r.status_code == 200, r.status_code
assert 'id="inst-rows"' in body, "tbody inst-rows fehlt (Auto-Refresh-Ziel)"
assert 'id="kv-running"' in body, "Sammler-Status-Badge id fehlt"
assert "setInterval(refreshMonitoring, 15000)" in body, "15s-Refresh-Timer fehlt"
assert "/api/monitoring/status" in body, "Refresh-fetch-URL fehlt"
assert "data-ghref=" in body and "hideLogo" in body, "Refresh-Link-Basis (Grafana + kiosk/hideLogo) fehlt"
ok += 1
print("15. Auto-Refresh-Marker (tbody, Timer 15s, fetch-URL, kiosk-Link)  OK")

print(f"\nALLE {ok} TESTS OK")
os.remove(DB) if os.path.exists(DB) else None
