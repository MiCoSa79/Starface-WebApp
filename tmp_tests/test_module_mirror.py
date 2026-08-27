"""Tests für den Update-Server-Spiegel: mirror_modules() + versions.json.

Geprüft werden:
1. mirror_modules: kopiert NUR .sfm aus dem Image-Ordner (kaputte Dateien ignoriert),
   idempotent (2. Lauf überschreibt sauber, keine Duplikate), schreibt versions.json
   ins Ziel (nginx-html-Root = data/modules + versions.json daneben).
2. versions.json-Schema (is-Muster aus Plan/RE):
   {modules: [{moduleName, versions: [{moduleVersion, ring, downloadUrl, md5, compatibility}]}]}
   - moduleVersion/compatibility aus module-descriptor.xml (version-/specVersion-Attribut)
   - md5 = MD5-Hex der .sfm-Datei
   - downloadUrl = base_url (normalisiert ohne trailing /) + /modules/<datei>.sfm
3. base_url leer -> relativ "/modules/<datei>.sfm" (nur lokal erreichbar).

Aufruf: python3 tmp_tests/test_module_mirror.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

FAIL = []

def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)

# ---------------------------------------------------------------- Vorbereitung
SRC = os.path.join(tempfile.gettempdir(), "mirror_fakes_src")
ROOT = os.path.join(tempfile.gettempdir(), "mirror_fakes_root")
DST = os.path.join(ROOT, "modules")   # wie Produktion: dst = html-Root/modules
for d in (SRC, ROOT):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)

def make_sfm(path, name, version, spec="5", vendor="Axel Meiser - Kraemer IT"):
    desc = (f"<?xml version='1.0' encoding='UTF-8'?>\n<module id=\"uuid-{name}\" "
            f"name=\"{name}\" specVersion=\"{spec}\" vendor=\"{vendor}\" version=\"{version}\">"
            f"<noLicenseId>x</noLicenseId></module>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/MANIFEST.MF",
                   f"Manifest-Version: 1.0\r\nObjectId: uuid-{name}\r\nStarfaceModule_SpecVersion: {spec}\r\n")
        z.writestr("module-descriptor.xml", desc)

make_sfm(os.path.join(SRC, "TelefonieMonitoring.sfm"), "TelefonieMonitoring", "7")
make_sfm(os.path.join(SRC, "CallBlocker.sfm"), "CallBlocker", "28")
with open(os.path.join(SRC, "kaputt.sfm"), "w") as f:  # kein ZIP -> muss ignoriert werden
    f.write("kein zip")

import mirror

# ------------------------------------------------- 1. mirror_modules-Grundlagen
result = mirror.mirror_modules(SRC, DST, "https://modulupdates.meiser.family")
copied = sorted(os.listdir(DST))

check("kopiert: beide .sfm im Ziel",
      "TelefonieMonitoring.sfm" in copied and "CallBlocker.sfm" in copied, str(copied))
check("kaputte .sfm NICHT kopiert", "kaputt.sfm" not in copied, str(copied))
check("versions.json NICHT in modules/ (gehoert in den html-Root)",
      "versions.json" not in copied, str(copied))
root_files = os.listdir(ROOT)
check("versions.json im html-ROOT neben modules/",
      "versions.json" in root_files, str(root_files))

# ------------------------------------------------- 2. versions.json-Schema
with open(os.path.join(ROOT, "versions.json")) as fh:
    manifest = json.load(fh)
mods = {m["moduleName"]: m for m in manifest.get("modules", [])}

check("Manifest: genau 2 Module", len(mods) == 2, str(list(mods)))
check("Manifest: TelefonieMonitoring v7 + spec5",
      mods["TelefonieMonitoring"]["versions"][0]["moduleVersion"] == "7"
      and mods["TelefonieMonitoring"]["versions"][0]["compatibility"] == "5",
      json.dumps(mods.get("TelefonieMonitoring")))
check("Manifest: CallBlocker v28 + ring stable",
      mods["CallBlocker"]["versions"][0]["moduleVersion"] == "28"
      and mods["CallBlocker"]["versions"][0]["ring"] == "stable",
      json.dumps(mods.get("CallBlocker")))
check("Manifest: downloadUrl = base + /modules/<datei>",
      mods["CallBlocker"]["versions"][0]["downloadUrl"]
      == "https://modulupdates.meiser.family/modules/CallBlocker.sfm",
      mods["CallBlocker"]["versions"][0].get("downloadUrl"))

# ------------------------------------------------- 3. MD5 + Idempotenz
real_md5 = hashlib.md5(open(os.path.join(SRC, "CallBlocker.sfm"), "rb").read()).hexdigest()
check("Manifest: md5 = echter Datei-MD5",
      mods["CallBlocker"]["versions"][0]["md5"] == real_md5,
      mods["CallBlocker"]["versions"][0].get("md5"))
second = mirror.mirror_modules(SRC, DST, "https://modulupdates.meiser.family")
check("idempotent: 2. Lauf gleicher Manifest-Inhalt (keine Duplikate)",
      second == manifest, "Manifeste unterscheiden sich")
# Legacy-Cleanup: frühere (falsche) Version lag in modules/ — muss weg
legacy = os.path.join(DST, "versions.json")
with open(legacy, "w") as fh:  # Fake-Legacy anlegen
    fh.write("{}")
third = mirror.mirror_modules(SRC, DST, "https://modulupdates.meiser.family")
check("Legacy modules/versions.json wird beim Lauf entfernt",
      not os.path.exists(legacy), legacy)

# ------------------------------------------------- 4. base_url-Normalisierung
no_base = mirror.mirror_modules(SRC, DST, "")
u = json.load(open(os.path.join(ROOT, "versions.json")))["modules"][0]["versions"][0]["downloadUrl"]
check("base_url leer -> relativer Pfad", u == "/modules/CallBlocker.sfm" or u == "/modules/TelefonieMonitoring.sfm", u)
slashed = mirror.mirror_modules(SRC, DST, "https://modulupdates.meiser.family/")
u2 = json.load(open(os.path.join(ROOT, "versions.json")))["modules"][0]["versions"][0]["downloadUrl"]
check("trailing slash normalisiert (kein //)", "//modules/" not in u2 and u2.startswith("https://modulupdates.meiser.family/modules/"), u2)

# ------------------------------------------------- 5. Stale-Cleanup (F49)
# Verwaistes EIGENES Paket im Ziel (Quelle im Image weg, z. B. Umbenennung
# UpdateDeployer -> Deployment-Modul) muss entfernt werden; Drittanbieter
# (anderer Vendor) bleiben unangetastet.
make_sfm(os.path.join(DST, "UpdateDeployer.sfm"), "UpdateDeployer", "7")            # eigen: Vendor Axel Meiser - Kraemer IT
make_sfm(os.path.join(DST, "AdminPowerPack.sfm"), "AdminPowerPack", "20260205", vendor="Fluxpunkt")
mirror.mirror_modules(SRC, DST, "")
check("Stale-Cleanup: verwaistes eigenes Paket (UpdateDeployer.sfm) entfernt",
      not os.path.exists(os.path.join(DST, "UpdateDeployer.sfm")))
check("Stale-Cleanup: Drittanbieter-Paket bleibt",
      os.path.exists(os.path.join(DST, "AdminPowerPack.sfm")))
man5 = json.load(open(os.path.join(ROOT, "versions.json")))
names5 = {m["moduleName"] for m in man5["modules"]}
check("Manifest nach Cleanup: AdminPowerPack drin, UpdateDeployer NICHT",
      "AdminPowerPack" in names5 and "UpdateDeployer" not in names5, str(names5))

shutil.rmtree(SRC, ignore_errors=True)
shutil.rmtree(ROOT, ignore_errors=True)

print()
print("ERGEBNIS:", f"{len(FAIL)} FAIL" if FAIL else "ALLE TESTS BESTANDEN")
sys.exit(1 if FAIL else 0)
