"""Render-/Unit-Test: Provider-Badges auf der Monitoring-Seite (temporär)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("STARFACE_DB", "/tmp/tpl_refactor_test.db")
os.environ.setdefault("APP_VERSION", "v9.9.9-TEST")

from monitoring import _provider_summary

# 1) Unit-Tests _provider_summary
cases = [
    ("alle verbunden", "Glasfunk=Registered\nSIP-Trunk=Registered", dict(count=2, connected=2, all_ok=True, has_data=True), 0),
    ("einer down", "Glasfunk=Registered\nSIP-Trunk=Not registered", dict(count=2, connected=1, all_ok=False, has_data=True), 1),
    ("leer", "", dict(count=0, connected=0, all_ok=False, has_data=False), 0),
    ("Nur Name ohne =", "Kryptisch", dict(count=0, has_data=False), 0),
    ("Registered mit Zusatz", "Glasfunk=Registered (2 devices)", dict(count=1, connected=1, all_ok=True, has_data=True), 0),
    ("Name mit = (altes Wire-Settings-Format)", "register=>user:geheim@host:5060/1=Registered", dict(count=1, connected=1, all_ok=True, has_data=True), 0),
]
for label, raw, exp, exp_disc in cases:
    r = _provider_summary(raw)
    ok = all(r[k] == v for k, v in exp.items()) and len(r["disconnected"]) == exp_disc
    print(f"{'OK ' if ok else 'FAIL'} {label}: count={r['count']} connected={r['connected']} all_ok={r['all_ok']} disc={r['disconnected']}")
    assert ok

# 2) Render-Test monitoring.html (alle 3 Badge-Fälle)
from main import TEMPLATES
status = {
    "running": True, "interval": 60, "influx_url": "http://x", "influx_bucket": "telefonie",
    "influx_configured": True, "last_run": 1787664390, "last_error": None,
    "total_runs": 42, "total_writes": 13,
    "installations": {
        "Hauptanlage": {"systemName": "main01", "systemVersion": "10.2", "points": 9,
                        "ts": 1787664390, "providers": "Glasfunk=Registered\nSIP-Trunk=Registered",
                        "provider_summary": _provider_summary("Glasfunk=Registered\nSIP-Trunk=Registered")},
        "Filiale": {"systemName": "fil01", "systemVersion": "10.2", "points": 9,
                    "ts": 1787664390, "providers": "Glasfunk=Not registered",
                    "provider_summary": _provider_summary("Glasfunk=Not registered")},
        "Neu": {"systemName": "neu01", "systemVersion": "", "points": 4, "ts": 1787664390,
                "providers": "", "provider_summary": _provider_summary("")},
    },
}
html = TEMPLATES.env.get_template("monitoring.html").render(
    user={"username": "admin", "is_admin": True}, active="monitoring", status=status)
for marker in ["Alle Provider verbunden (2)", "Provider getrennt (1 von 1)", "Keine Provider"]:
    print(f"{'OK ' if marker in html else 'FAIL'} enthaelt: {marker}")
    assert marker in html
print("Badge-count:", html.count('class="badge badge-green"'), "gruen /",
      html.count('class="badge badge-red"'), "rot /",
      html.count('class="badge badge-gray"'), "grau")
print("\nALLE RENDER-TESTS OK")
