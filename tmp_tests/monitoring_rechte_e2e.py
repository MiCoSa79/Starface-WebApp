#!/usr/bin/env python3
"""E2E-Test v0.0.120/v1.0.55: /monitoring rechtebasiert (Admin alle, User nur can_read),
Detail-Link-Spalte je Anlage (eigenes Monitoring), /admin/monitoring-Seite (F59),
API-Filter, Nav-Sichtbarkeit, Grafana-frei (v1.0.55)."""
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

# 2) Admin: alle Anlagen + 2 Detail-Links, KEIN Grafana mehr (v1.0.55)
login("admin")
r = c.get("/monitoring")
assert r.status_code == 200, r.status_code
body = r.text
assert "Testanlage A" in body and "Testanlage B" in body, "Admin muss beide Anlagen sehen"
assert body.count('class="detail-dl"') == 2, f"Admin erwartet 2 Detail-Links, hat {body.count('detail-dl')}"
assert 'href="/monitoring/installations/' in body, "Detail-Link aufs native Monitoring fehlt"
assert "grafana" not in body.lower() and "hideLogo" not in body, "Grafana-Reste auf /monitoring (v1.0.55)"
ok += 1
print("2. Admin: beide Anlagen + 2 Detail-Links + grafana-frei  OK")

# 3) Bob (can_read nur A): nur A + 1 Link; B NICHT
login("bob")
r = c.get("/monitoring")
assert r.status_code == 200
body = r.text
assert "Testanlage A" in body, "Bob muss Anlage A sehen"
assert "Testanlage B" not in body, "Bob darf Anlage B NICHT sehen"
assert body.count('class="detail-dl"') == 1, f"Bob erwartet genau 1 Detail-Link, hat {body.count('detail-dl')}"
assert "/admin/monitoring" not in body, "Nav darf /admin/monitoring nicht mehr verlinken"
assert 'href="/monitoring"' in body, "Nav-Link /monitoring fehlt für Bob"
assert "grafana" not in body.lower(), "Grafana-Rest in Bob-Sicht"
ok += 1
print("3. Bob: nur Anlage A + exakt 1 Detail-Link + Nav  OK")

# 4) Eve (keine Rechte): leere Liste + Hinweis, 0 Links
login("eve")
r = c.get("/monitoring")
assert r.status_code == 200
body = r.text
assert "Testanlage A" not in body and "Testanlage B" not in body, "Eve darf keine Anlage sehen"
assert body.count('class="detail-dl"') == 0
assert "Lese-Rechte" in body, "Hinweis für User ohne Rechte fehlt"
ok += 1
print("4. Eve: keine Anlage, kein Link, Hinweis  OK")

# 5) /admin/monitoring ist seit v1.0.18 die Admin-Monitoring-Seite (F59):
#    Admin -> 200 mit Kennzahlen; User (nicht Admin) -> Redirect /dashboard
login("admin")
r = c.get("/admin/monitoring")
assert r.status_code == 200, r.status_code
assert "Admin-Monitoring" in r.text and "Anlagen mit Provider-Fehlern" in r.text, \
    "Admin-Monitoring-Kennzahlen fehlen"
ok += 1
login("bob")
r = c.get("/admin/monitoring")
assert r.status_code in (302, 307) and r.headers.get("location", "").rstrip("/") == "", \
    (r.status_code, r.headers.get("location"))
ok += 1
print("5. /admin/monitoring: Admin 200 (Kennzahlen) / User -> /  OK")

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

# 7) Nav: Monitoring-Link für alle eingeloggten User auf der Anlagen-Seite
login("eve")
r = c.get("/anlagen")
assert r.status_code == 200 and 'href="/monitoring"' in r.text, "Nav-Monitoring fehlt auf Anlagen-Seite"
ok += 1
print("7. Nav-Link /monitoring auf /anlagen für Eve  OK")

# 8) Admin: Startseite / = Admin-Monitoring (F64); Anlagen-Übersicht unter /anlagen
login("admin")
r = c.get("/")
assert r.status_code == 200, r.status_code
body = r.text
assert "Admin-Monitoring" in body and "Anlagen mit Provider-Fehlern" in body, \
    "Startseite (Admin) muss das Admin-Monitoring sein"
assert 'id="tbl-inst"' not in body, "Anlagen-Tabelle gehört nicht mehr auf die Startseite"
r = c.get("/anlagen")
assert r.status_code == 200, r.status_code
body = r.text
assert body.count("⚡ Test") == 2, "Admin erwartet 2 Test-Buttons auf /anlagen"
assert "Testanlage A" in body and "Testanlage B" in body, "Admin sieht nicht beide Anlagen"
assert "Anlage hinzufügen" in body, "Admin-Formular (Anlegen) fehlt auf /anlagen"
ok += 1
print("8. Admin / = Admin-Monitoring; /anlagen: 2 Anlagen-Zeilen + 2 Test-Buttons + Formular  OK")

# 9) Bob: / -> Redirect /anlagen; /anlagen: nur Anlage A (can_read), 1 Detail-Link
login("bob")
r = c.get("/")
assert r.status_code in (302, 307) and "/anlagen" in r.headers.get("location", ""), \
    f"Bob: / muss auf /anlagen zeigen, war {r.status_code} -> {r.headers.get('location')}"
r = c.get("/anlagen")
body = r.text
assert "Testanlage A" in body and "Testanlage B" not in body, "Bob sieht auf /anlagen die falsche Anlagenmenge"
assert body.count('class="detail-dl"') == 1, "Bob: genau 1 Detail-Link erwartet"
assert 'href="/monitoring/installations/1"' in body, "Detail-Link-Ziel (eigenes Monitoring) fehlt"
assert "grafana" not in body.lower(), "Grafana-Rest auf Anlagen-Seite (v1.0.55)"
assert "Anlage hinzufügen" not in body, "Bob darf kein Anlegen-Formular sehen"
assert body.count("⚡ Test") == 1, "Bob: genau 1 Test-Button (User-Route) erwartet"
ok += 1
print("9. Bob / -> /anlagen; 1 Zeile (nur can_read) + Detail-Link → /monitoring/installations/1  OK")

# 10) Eve /anlagen: keine Anlagen, keine Links, kein Formular
login("eve")
r = c.get("/anlagen")
body = r.text
assert "Testanlage" not in body and body.count('class="detail-dl"') == 0, "Eve darf keine Anlagen/Links sehen"
assert "Anlage hinzufügen" not in body, "Eve darf kein Formular sehen"
ok += 1
print("10. Eve /anlagen: 0 Anlagen, 0 Links, kein Formular  OK")

# 11) Alte Grafana-Einstellung ist wirkungslos (Feld existiert nicht mehr; POST wird ignoriert)
login("admin")
r = c.post("/admin/settings", data={"grafana_base_url": "https://monitoring.meiser.family"})
assert r.status_code == 303 and "set_ok=1" in r.headers.get("location", ""), (r.status_code, r.headers.get("location"))
login("bob")
r = c.get("/")
body = r.text
assert "grafana" not in body.lower() and "10.0.25.60" not in body, "Grafana darf nach Alt-POST nicht auftauchen"
r = c.get("/monitoring")
assert "grafana" not in r.text.lower(), "Monitoring darf nach Alt-POST kein Grafana zeigen"
login("admin")
r = c.get("/grundeinstellungen")
body = r.text
assert 'name="grafana_base_url"' not in body, "Grafana-URL-Feld muss aus Grundeinstellungen verschwunden sein"
ok += 1
print("11. Alt-POST grafana_base_url wirkungslos; Feld weg; keine Grafana-URLs  OK")

# 12) Alle Seiten grafana-frei (Auslieferungszustand) — auch nach Alt-POST oben
login("admin")
for path in ("/", "/anlagen", "/monitoring", "/grundeinstellungen", "/admin/monitoring"):
    r = c.get(path)
    assert r.status_code == 200, (path, r.status_code)
    assert "grafana" not in r.text.lower(), f"grafana-Rest auf {path}"
    assert "hideLogo" not in r.text, f"kiosk-Rest auf {path}"
ok += 1
print("12. /, /anlagen, /monitoring, /grundeinstellungen, /admin/monitoring grafana-frei  OK")

# 13) Kein Grafana-Admin-Übersicht-Link mehr (für Admin UND Bob)
login("admin")
r = c.get("/monitoring")
assert "starface-admin-uebersicht" not in r.text, "Grafana-Admin-Übersicht-Link darf nicht mehr existieren"
login("bob")
r = c.get("/monitoring")
assert "starface-admin-uebersicht" not in r.text, "Bob: kein Admin-Übersicht-Link"
ok += 1
print("13. Kein Grafana-Admin-Übersicht-Link mehr  OK")

# 14) Grundeinstellungen: nur noch Update-Server-Feld, KEIN Admin-Monitoring-Button
#     mehr (Admin-Monitoring ist seit F64 die Startseite — v1.0.58: Button entfernt)
login("admin")
r = c.get("/grundeinstellungen")
body = r.text
assert 'name="module_update_base_url"' in body, "Update-Server-Feld fehlt"
assert "Admin-Monitoring öffnen" not in body and 'href="/admin/monitoring"' not in body, \
    "Grundeinstellungen: Admin-Monitoring-Button muss weg sein (ist Startseite)"
assert "starface-admin-uebersicht" not in body, "Grafana-Rest?"
ok += 1
print("14. Grundeinstellungen: nur Update-URL-Feld, kein Admin-Monitoring-Button (Startseite), grafana-frei  OK")

# 15) Monitoring-Auto-Refresh: JS-Marker + tbody auf der Monitoring-Seite (Admin)
login("admin")
r = c.get("/monitoring")
body = r.text
assert r.status_code == 200, r.status_code
assert 'id="inst-rows"' in body, "tbody inst-rows fehlt (Auto-Refresh-Ziel)"
assert 'id="kv-running"' in body, "Sammler-Status-Badge id fehlt"
assert "setInterval(refreshMonitoring, 15000)" in body, "15s-Refresh-Timer fehlt"
assert "/api/monitoring/status" in body, "Refresh-fetch-URL fehlt"
assert "data-ghref=" not in body, "Grafana-Link-Basis (data-ghref) darf nicht mehr existieren"
ok += 1
print("15. Auto-Refresh-Marker (tbody, Timer 15s, fetch-URL) + grafana-frei  OK")

print(f"\nALLE {ok} TESTS OK")
os.remove(DB) if os.path.exists(DB) else None
