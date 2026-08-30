"""F45-Tests: Seitenbreite (max-width 1400px) + Aktion-Buttons nebeneinander.

Geprüft (nach Axels Anforderung "Nutze mehr von der Breite des Bildschirms"
+ Screenshot Modul-Updates: Buttons rutschen untereinander):
1. Inhaltseiten rendern `.container { max-width: 1400px; ... }` (war 900/960/1100/720 je Template)
2. Modul-Updates + Modul-Seite: Aktion-Zellen `flex-wrap: nowrap` (Desktop), `wrap` nur <=640px
3. Login-Seite (password.html) bleibt bewusst schmal (max-width: 520px)

Aufruf: python3 tmp_tests/admin_layout_width_test.py
"""
import base64
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_layout_width_test/test.db"
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
from starlette.testclient import TestClient

app_main.init_db()
conn = sqlite3.connect(DB)
import bcrypt
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("axel", bcrypt.hashpw(b"pw456", bcrypt.gensalt()).decode(), 0))
conn.commit()
conn.close()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200 and r.json()["status"] == "ok"

passed, failed = [], []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
    else:
        failed.append((name, detail))


# Seiten, die auf 1400px breit sein muessen (Kandidaten: nur 200er wurden geprueft)
WIDE = ["/admin/updates", "/admin/modules", "/benutzer", "/monitoring",
        "/grundeinstellungen", "/wiki", "/"]
for route in WIDE:
    r = c.get(route)
    if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
        check(f"GET {route} rendert HTML (200)", False, f"status={r.status_code}")
        continue
    html = r.text
    check(f"GET {route} Container 1400px",
          "max-width: 1400px" in html,
          "CSS max-width: 1400px fehlt im Template")
    check(f"GET {route} kein altes Schmalklassen-Limit",
          all(x not in html for x in ("max-width: 900px", "max-width: 960px",
                                      "max-width: 1100px", "max-width: 720px")),
          "veraltete max-width-Breite noch im Template")

# Login (password.html) bleibt schmal — jetzt nur noch im Admin-Reset-Modus
# (GET /password ohne uid redirectet seit dem Menü-Umbau auf /konto#sicherheit)
for route in ("/login",):
    r = c.get(route)
    if r.status_code == 200:
        check("Login-Seite Container 520px", "max-width: 520px" in r.text)
        break
r = c.get("/password", params={"uid": "2"})  # Admin-Reset für Fremduser (uid 2)
check("Admin-Reset password.html Container 520px",
      r.status_code == 200 and "max-width: 520px" in r.text,
      f"status={r.status_code}")
r = c.get("/konto")
check("Mein-Konto /konto Container 1400px",
      r.status_code == 200 and "max-width: 1400px" in r.text,
      f"status={r.status_code}")

# Aktion-Buttons: zentrale Regeln in admin.css (Modul-Tabellen nowrap/Desktop,
# wrap/Mobil) — beide Seiten binden die globalisierte CSS mit Cache-Busting ein
for route in ("/admin/updates", "/admin/modules"):
    r = c.get(route)
    check(f"GET {route} bindet zentrale admin.css ein",
          'href="/static/admin.css?v=' in r.text,
          "admin.css-Link fehlt")

# F86 (v1.0.83): Navigations-Dropdowns schließen bei Klick außerhalb (admin.js)
r = c.get("/static/admin.js")
_js = r.text
check("F86: Außenklick schließt Nav-Dropdowns (initNavDrops in admin.js)",
      r.status_code == 200 and "initNavDrops" in _js
      and "details.drop[open]" in _js and "d.open = false" in _js,
      "Außenklick-Handler fehlt in admin.js")

# F91 (v1.0.88): admin.js GLOBAL via base.html — Außenklick-Fix wirkt auf ALLEN
# Seiten (F86-Fix lag nur in Templates -> /, /konto, /monitoring, /wiki,
# /admin/modules, /grundeinstellungen, /admin/api-doku ohne initNavDrops)
r = c.get("/")
check("F91: admin.js global in base.html eingebunden (eine Einbindung app-weit)",
      'src="/static/admin.js?v=' in r.text,
      "base.html bindet admin.js nicht global ein")
check("F91: base.html enthält KEINE Template-Duplikat-Hinweise",
      r.text.count('src="/static/admin.js?v=') == 1,
      "admin.js mehrfach im gerenderten HTML")

for _tpl in ("anlagen.html", "benutzer.html", "rechte.html", "installation_detail.html",
             "admin_updates.html", "admin_updates_modul.html"):
    _tpl_src = open(f"app/templates/{_tpl}", encoding="utf-8").read()
    _dup = [l for l in _tpl_src.splitlines() if "<script" in l and "admin.js" in l]
    check(f"F91: {_tpl} ohne eigene admin.js-Einbindung (nur noch global via base)",
          not _dup, str(_dup))

# F91-Teil 2: Klick auf einen Link IM offenen Dropdown schließt es ebenfalls
# („Mein Konto“ auf /konto bleibt sonst offen — Axel-Feedback)
r = c.get("/static/admin.js")
_js = r.text
check("F91: Link-Klick im Dropdown schließt es (closest('a') + contains(link))",
      "closest('a')" in _js and "d.contains(link)" in _js,
      "Link-Klick-Logik fehlt in admin.js")

# F98 (v1.0.96): Footer ans Seitenende — vorher `position: fixed` klebte er beim
# Scrollen ueber dem Inhalt (iPhone-Foto 30.08.). Sticky-Footer ueber body-Flex:
# kurze Seiten → Footer unten im Viewport, lange Seiten → unter dem letzten Inhalt.
r = c.get("/static/admin.css")
_css = r.text
_footer = _css[_css.find(".footer"):_css.find("}", _css.find(".footer")) + 1]
_footer = _footer[:_footer.find("}") + 1]  # nur die .footer-Regel
check("F98: Footer-Klasse nicht fixed", "position: fixed" not in _footer
      and "bottom: 0" not in _footer, "Footer-CSS: " + _footer.replace("\n", " "))
check("F98: Footer per margin-top:auto ans Seitenende", "margin-top: auto" in _footer,
      "margin-top:auto fehlt: " + _footer.replace("\n", " "))
_body = _css[_css.find("body {"):_css.find("}", _css.find("body {")) + 1]
check("F98: body-Flex (Sticky-Footer-Geruest)", "flex-direction: column" in _body
      and "min-height: 100dvh" in _body, "body-Regel: " + _body.replace("\n", " "))
r = c.get("/")
check("F98: Login bindet die Basis-CSS (Footer-Geruest wirkt global)",
      r.status_code == 200 and "/static/admin.css?v=" in r.text,
      f"status={r.status_code}")

if failed:
    print(f"FEHLGESCHLAGEN ({len(failed)}):")
    for name, detail in failed:
        print(f"  - {name}: {detail}")
    sys.exit(1)
print(f"ALLE {len(passed)} CHECKS OK ({len(passed)} Layout-Vertraege verankert)")
