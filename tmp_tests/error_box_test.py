"""Render-/Unit-Test: last_error-Semantik + Fehlerbox auf der Monitoring-Seite.

Semantik (Nutzerwunsch): Der Fehler verschwindet, sobald er NICHT MEHR besteht
(erster fehlerfreier Poll-Zyklus loescht ihn); ein weiterbestehender Fehler wird
NIE automatisch weggeblendet. Dazu Zeitangabe des Fehlers (Europe/Berlin).
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("STARFACE_DB", "/tmp/error_box_test.db")
os.environ.setdefault("APP_VERSION", "v9.9.9-TEST")

# --- 1) status()-Semantik (Unit) ---
import monitoring
monitoring._state.update({
    "running": True, "last_run": time.time(), "total_runs": 5, "total_writes": 3,
    "last_values": {},
})

# frischer Fehler -> wird geliefert (inkl. ts fuer die Anzeige)
monitoring._state["last_error"] = {"msg": "Testanlage: timed out", "ts": time.time()}
st = monitoring.status()
assert st["last_error"] is not None and st["last_error"]["msg"] == "Testanlage: timed out"
assert st["last_error"]["ts"] > 0, "Fehler braucht Zeitstempel fuer die Anzeige"
print("OK  frischer Fehler wird mit {msg, ts} geliefert")

# ALTES dict (z.B. Loop haengt seit Stunden) -> bleibt sichtbar: Fehler besteht
# noch, es gab keinen fehlerfreien Zyklus danach. Kein TTL-Wegblenden!
old_ts = time.time() - 99999
monitoring._state["last_error"] = {"msg": "Testanlage: timed out", "ts": old_ts}
st = monitoring.status()
assert st["last_error"] == {"msg": "Testanlage: timed out", "ts": old_ts}, st
print("OK  weiterbestehender Fehler bleibt auch nach langer Zeit sichtbar (kein TTL)")

# undatiertes Altformat (String) -> None (nur durch collect_installations/Reset
# bzw. dict-Format ersetzt; ein String kann nicht datiert werden)
monitoring._state["last_error"] = "Testanlage: timed out"
assert monitoring.status()["last_error"] is None
print("OK  undatiertes Altformat (String) -> None")

# kein Fehler -> None
monitoring._state["last_error"] = None
assert monitoring.status()["last_error"] is None
print("OK  kein Fehler -> None")

# --- 2) Render-Test monitoring.html (Fehlerbox) ---
from main import TEMPLATES

base = {
    "running": True, "interval": 60, "influx_url": "http://x", "influx_bucket": "telefonie",
    "influx_configured": True, "last_run": 1787664390, "last_error": None,
    "total_runs": 42, "total_writes": 13,
    "installations": {},
}
user = {"username": "admin", "is_admin": True}

# 2a) dict-Fehler: Box + Zeitstempel-Marker (data-ts) + Meldung
st_dict = dict(base, last_error={"msg": "Testanlage: timed out", "ts": 1787664390})
html = TEMPLATES.env.get_template("monitoring.html").render(user=user, active="monitoring", status=st_dict)
assert 'id="err-slot"' in html, "err-slot fehlt"
assert html.count('class="errbox"') == 1, "genau 1 serverseitig gerenderte Fehlerbox erwartet"
assert "Letzter Fehler" in html and "Testanlage: timed out" in html, "Fehlertext fehlt"
assert 'data-ts="1787664390"' in html, "Fehler-Zeitstempel (data-ts) fehlt"
assert "Europe/Berlin" in html, "timeZone Europe/Berlin fehlt in fmtTs"
assert "renderError(document.getElementById('err-slot')" in html, "renderError-Aufruf im Refresh fehlt"
print("OK  dict-Fehler: Box + data-ts + Europe/Berlin + renderError-Aufruf gerendert")

# 2b) String-Fehler (defensiv): Box ohne Zeitstempel
st_str = dict(base, last_error="Testanlage: timed out")
html = TEMPLATES.env.get_template("monitoring.html").render(user=user, active="monitoring", status=st_str)
assert "Testanlage: timed out" in html, "String-Fehler muss defensiv gerendert werden"
assert 'data-ts="' not in html.replace('data-ts="1787664390"', ""), "String-Fehler darf keinen ts haben"
print("OK  String-Fehler defensiv ohne Zeitstempel gerendert")

# 2c) ohne Fehler: err-slot ist leer (keine serverseitig gerenderte errbox)
html = TEMPLATES.env.get_template("monitoring.html").render(user=user, active="monitoring", status=base)
assert 'id="err-slot"' in html, "err-slot muss immer existieren (Refresh-Ziel)"
assert html.count('class="errbox"') == 0, "ohne last_error darf keine Fehlerbox erscheinen"
assert '<div id="err-slot"></div>' in html, "err-slot muss leer gerendert werden"
print("OK  ohne Fehler: leerer err-slot, keine Fehlerbox")

# --- 3) E2E-Marker (Timer/Auto-Refresh bleibt intakt) ---
for marker in ["setInterval(refreshMonitoring, 15000)", "/api/monitoring/status",
               'id="inst-rows"', 'id="kv-running"', "hideLogo"]:
    assert marker in html, f"Marker fehlt: {marker}"
print("OK  Auto-Refresh-Marker unveraendert vorhanden")

print("\nALLE FEHLERBOX-TESTS OK")
