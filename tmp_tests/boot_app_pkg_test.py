#!/usr/bin/env python3
"""Boot-Starttest: main.py aus Container-Perspektive importierbar?

Simuliert den Container-Import-Pfad: nur repo-root auf PYTHONPATH, dann
`import app.main` (uvicorn lädt die App als `app.main:app`). Deckt die
Zirkel-Falle ab (F20/F21/F22: app-interne Module via Zwei-Wege-Import).

Voraussetzung lokal: app/-Verzeichnis als (Namespace-)Paket → funktioniert
ohne __init__.py (Python 3.3+).
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = ""):
    global CHECKS
    CHECKS += 1
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else "  | " + detail))
    if not ok:
        FAIL.append(name)


env = dict(os.environ)
env["PYTHONPATH"] = BASE          # Container: nur der App-Root, NICHT app/
env["STARFACE_DB"] = "/tmp/boot_app_pkg_test.db"
if os.path.exists(env["STARFACE_DB"]):
    os.remove(env["STARFACE_DB"])

r = subprocess.run([sys.executable, "-c", "import app.main"],
                   env=env, capture_output=True, text=True, timeout=120,
                   cwd=BASE)

ok = r.returncode == 0
check("Boot: import app.main (Container-Sicht) ohne Fehler", ok,
      (r.stderr or r.stdout)[-400:])

# Zirkel-Falle direkt prüfen: Fallback 'from app.module_updates ...' ok
if ok:
    r2 = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.modules.pop('module_updates', None); "
         "sys.modules['module_updates'] = None; "
         "from app import module_updates; "
         "print('FB-OK', callable(module_updates.ping_channel), "
         "callable(module_updates.push_update))"],
        env=env, capture_output=True, text=True, timeout=120, cwd=BASE)
    fb_ok = r2.returncode == 0 and "FB-OK True True" in r2.stdout
    check("Boot: Fallback app.module_updates -> ping/push nutzbar", fb_ok,
          (r2.stderr or r2.stdout)[-300:])

print()
if FAIL:
    print("FEHLGESCHLAGEN:", ", ".join(FAIL))
    sys.exit(1)
print(f"ERGEBNIS: BOOT-TEST OK ({CHECKS}/{CHECKS})")
