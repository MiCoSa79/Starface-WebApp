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

# F101: Einzige bewusst schmale Karte ist der Login (Auth-Dialog, 400 px);
# alle Inhaltsseiten (auch Admin-Reset password.html) nutzen das 1400er-Muster.
for route in ("/login",):
    r = c.get(route)
    if r.status_code == 200:
        check("Login-Seite bleibt Auth-Karte (400 px, kein 1400-Container)",
              "max-width: 400px" in r.text and "max-width: 1400px" not in r.text,
              f"status={r.status_code}")
        break
r = c.get("/password", params={"uid": "2"})  # Admin-Reset für Fremduser (uid 2)
check("Admin-Reset password.html nutzt 1400-Muster (keine 520px-Lokalregel)",
      r.status_code == 200 and "max-width: 520px" not in r.text,
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

# F99 (v1.0.97): Anlagen-Aktions-Buttons — die lokale .actions-inline
# a/button-Regel (0,1,1: padding 6x12, display:inline-block, ohne Zentrierung)
# ueberschrieb die globalen .btn-* (0,1,0: 8x14, inline-flex, center) → Buttons
# unterschiedlich gross, Icons ⚡/✎ linksbuendig (iPhone-Foto 30.08.). Fix:
# kollidierende Regel entfernt, .actions-inline spiegelt die .btn-Basis.
r = c.get("/anlagen")
_anl = r.text
check("F99: anlagen.html ohne .actions-inline a/button-Kollision",
      ".actions-inline a, .actions-inline button" not in _anl
      and ".actions-inline a.detail-dl" in _anl,
      "kollidierende Regel steht noch im anlagen.html-<style>")
check("F99: .actions-inline spiegelt .btn-Basis (wrap + rechts, jetzt global)",
      "flex-wrap: wrap" in _css and "justify-content" in _css and ".actions-inline" in _css,
      "globale .actions-inline-Regel unvollstaendig")
check("F99: Container-Bodenabstand inkl. iPhone-Safe-Area",
      "padding-bottom: calc(32px + env(safe-area-inset-bottom, 0px))" in _css,
      "admin.css .container-padding-bottom fehlt")
check("F99: Mobile-Vollbreiten-MQ nimmt Link-Buttons in Tabellenzellen aus (a <button>)",
      "container table a.btn-secondary" in _css and "container table a.btn-danger" in _css
      and "container table button" in _css,
      "admin.css Zellen-Ausnahme nur fuer <button>, nicht fuer a.btn-*?")
r = c.get("/benutzer")
check("F100: Benutzer-Aktionszelle im actions-inline-Muster (anlagen.html)",
      r.status_code == 200 and '<span class="actions-inline">' in r.text and "white-space:nowrap" in r.text,
      f"status={r.status_code}")
check("F100: .actions-inline global in admin.css",
      ".actions-inline {" in _css and "flex-wrap: wrap" in _css,
      "globale actions-inline-Regel fehlt")
check("F100: form-row-Buttons mobil kompakt (align-self:flex-start)",
      ".form-row .btn-primary" in _css and "align-self: flex-start" in _css,
      "form-row-Kompaktregel fehlt")

# ── F101: PC-Breite einheitlich wie /anlagen (1400) + Kiosk vollbreit ──
from pathlib import Path as _Path
def _tpl(rel):
    return (_Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")

_pw   = _tpl("app/templates/password.html")
_edit = _tpl("app/templates/edit_installation.html")
_adm  = _tpl("app/templates/admin_monitoring.html")
_inst = _tpl("app/templates/installation_monitoring.html")

check("F101: password.html nutzt globales 1400-Muster (keine 520px-Lokalregel)",
      "max-width: 520px" not in _pw and 'class="container"' in _pw,
      "password.html: Lokal-520-Regel noch da oder container fehlt")
check("F101: edit_installation.html nutzt Container-Muster (keine 600px-Karte)",
      "max-width: 600px" not in _edit and 'class="container"' in _edit,
      "edit_installation.html: 600px-Karte/ohne container")
check("F101: Kiosk-Modus vollbreit — Admin-Monitoring (max-width:100%)",
      "body.kiosk .container { max-width: 100%" in _adm,
      "admin_monitoring Kiosk-Breite fehlt")
check("F101: Kiosk-Modus vollbreit — Detail-Monitoring (max-width:100%)",
      "body.kiosk .container { max-width: 100%" in _inst,
      "installation_monitoring Kiosk-Breite fehlt")
check("F101: Kiosk-Safe-Area-Padding gesetzt (beide Seiten)",
      "12px + env(safe-area-inset-bottom" in _adm and "12px + env(safe-area-inset-bottom" in _inst,
      "Kiosk-Safe-Area-Padding fehlt")

# ── F102: Abruf-Dialog (Anlagen-Updates) auf dem PC breit — .dlg.wide war nie definiert ──
_bulk = _tpl("app/templates/_au_bulk.html")
_einz = _tpl("app/templates/_au_einzel.html")
check("F102c: dialog.dlg.wide = breite Dialog-Variante (0,2,1 > Basis 0,1,1; width:max-content)",
      "dialog.dlg.wide { max-width: min(96vw, 1200px); width: max-content; }" in _css,
      "dialog.dlg.wide-Regel fehlt — .dlg.wide (0,1,0) verliert gegen dialog.dlg max-width:420 (0,1,1), Dialog bleibt schmal")
check("F102c: Datumsauswahl VOLL sichtbar (170px — 145 schnitt Minuten+Icon ab)",
      '.dlg.wide input[type="datetime-local"] { width: 170px; }' in _css,
      ".dlg.wide-Datumsfeld-Kompaktregel fehlt/veraltet (145=abgeschnitten)")
check("F102: Tabellen im .dlg.wide nutzen die volle Dialogbreite",
      ".dlg.wide table { width: 100%; }" in _css,
      ".dlg.wide table-Regel fehlt")
check("F102: Aktionszellen nowrap (F75-Muster) — eine Zeile fuer Buttons+Datum",
      '.dlg.wide .au-aktion { white-space: nowrap;' in _css
      and 'class="au-aktion"' in _bulk and 'class="au-aktion"' in _einz,
      ".au-aktion-Regel/Klasse fehlt (Buttons stapeln sich)")
check("F102: Mobil-Umbruch der Aktionszelle (MQ <=640) — kein Dialog-Scroll",
      "@media (max-width: 640px) {" in _css and ".au-aktion { white-space: normal; }" in _css,
      "Mobil-nowrap-Aufhebung fehlt")
_au = _tpl("app/templates/admin_anlagen_updates.html")
check("F102: Popup-Kopf: X-Schließen (SVG) statt 'Schließen'-Button",
      'class="dlg-close-x"' in _au and ">Schließen<" not in _au and "au-dlg-close" in _au,
      "Dialog-Kopf: dlg-close-x fehlt oder 'Schließen'-Button noch da")
check("F102: X-Schließen stylbar (admin.css dlg-close-x + Kopf-Flex)",
      ".dlg-close-x {" in _css and ".au-dlg-head {" in _css,
      "dlg-close-x/au-dlg-head CSS fehlt")
check("F103: Einzel-Partial ohne Seiten-Hinweis (Ergebnis NUR im Popup)",
      "elif not dlg" not in _einz and "Bitte oben eine Anlage auswählen" not in _einz,
      "_au_einzel: Seiten-Hinweis noch da — Seitenansicht existiert seit F103 nicht mehr")
check("F103: Updates-Seite = nur Dialog (keine elif-Seitenansicht, kein Geplant-Block)",
      "{% if (bulk or installations) and dlg %}" in _au
      and "{% elif bulk %}" not in _au
      and '<h2 class="tbl-head">Geplante Updates' not in _au,
      "Seite rendert noch Ergebnis-/Geplant-Bereiche (soll nur das Popup)")

if failed:
    print(f"FEHLGESCHLAGEN ({len(failed)}):")
    for name, detail in failed:
        print(f"  - {name}: {detail}")
    sys.exit(1)
print(f"ALLE {len(passed)} CHECKS OK ({len(passed)} Layout-Vertraege verankert)")
