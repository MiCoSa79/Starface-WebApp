#!/usr/bin/env python3
"""Builds the STARFACE 10.x CallBlocker .sfm as a JAR archive.

STARFACE 10.x module packets are JAR files: JarFile.getManifest() MUST find
META-INF/MANIFEST.MF with at least:
    ObjectId                    = module UUID (must match <module id="...">)
    StarfaceModule_SpecVersion  = 5  (checked: <= 5, else import.incompatible.version)
plus the standard Manifest-Version: 1.0. Only then is the JAR extracted and
module-descriptor.xml loaded via ModulePersister.

Usage:
    python3 build_sfm.py
Output: module/CallBlocker.sfm (and copies to app/modules/CallBlocker.sfm)
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DESCRIPTOR = os.path.join(ROOT, "module-descriptor.xml")
CLASSES_DIR = os.path.join(ROOT, "classes")
OUT = os.path.join(ROOT, "CallBlocker.sfm")
MIRRORS = [
    os.path.join(ROOT, "..", "app", "modules", "CallBlocker.sfm"),
]

# Java stores the manifest uncompressed, first entry, CRLF line endings.
MANIFEST_TEMPLATE = (
    "Manifest-Version: 1.0\r\n"
    "Created-By: build_sfm.py (Hermes Agent)\r\n"
    "ObjectId: {module_id}\r\n"
    "StarfaceModule_SpecVersion: 5\r\n"
)


def read_module_id(path: str) -> str:
    text = open(path, encoding="utf-8").read()
    m = re.search(r'<module\b[^>]*\bid="([^"]+)"', text)
    if not m:
        sys.exit(f"FEHLER: keine id= in {path}")
    return m.group(1)


def bump_descriptor(path: str) -> None:
    """Erhöht Modulversion um 1, setzt lastChangedTime neu und berechnet
    noLicenseId + writeHash nach (Nutzer-Vorgabe: Version IMMER +1 bei Änderung).

    - version   = alte Version + 1
    - lastChangedTime = aktuelle Zeit (auf volle Stunde abgerundet, damit
      noLicenseId über Stunden stabil bleibt)
    - noLicenseId = sha1Hex(id + lastChangedTime + "STARFACE")   (Lizenzfreiheit)
    - writeHash   = sha1Hex(id + STARFACE_MODULE_PASSWORD)  (PFLICHT seit 2026-08-26,
      Axel-Vorgabe: Module IMMER mit Passwort schützen; Passwort aus Env
      STARFACE_MODULE_PASSWORD — nie hardcoden, nie committen. Fehlt es: Abbruch.
      checkWritePassword(pw) = Strings.equals(sha1Hex(id + pw), writeHash).)
    """
    import hashlib
    import time
    import xml.etree.ElementTree as ET

    tree = ET.parse(path)
    root = tree.getroot()
    try:
        version = int(root.get("version", "1")) + 1
    except ValueError:
        version = 2
    root.set("version", str(version))

    module_id = root.get("id")
    if not module_id:
        sys.exit("FEHLER: keine id= im Descriptor (bump)")
    now = int(time.time() * 1000)
    last = now - (now % 3600000)  # volle Stunde
    root.set("lastChangedTime", str(last))

    no_license = hashlib.sha1((module_id + str(last) + "STARFACE").encode()).hexdigest()
    password = os.environ.get("STARFACE_MODULE_PASSWORD", "")
    if not password:
        sys.exit("FEHLER: STARFACE_MODULE_PASSWORD (Env) fehlt — Module werden "
                 "NICHT ungeschützt gebaut (Axel-Vorgabe)!")

    # writeHash = sha1Hex(id + password): checkWritePassword(pw) =
    # Strings.equals(sha1Hex(id + pw), writeHash) → Modul nur mit Passwort
    # importierbar/bearbeitbar. Leer-Passwort (sha1Hex(id)) wäre offen.
    write_hash = hashlib.sha1((module_id + password).encode()).hexdigest()

    nl = root.find("noLicenseId")
    if nl is None:
        nl = ET.SubElement(root, "noLicenseId")
    nl.text = no_license
    wh = root.find("writeHash")
    if wh is None:
        wh = ET.SubElement(root, "writeHash")
    wh.text = write_hash

    tree.write(path, encoding="UTF-8", xml_declaration=True)
    print(f"    Modul-Version erhöht auf {version}, lastChangedTime={last}")


def main() -> None:
    if "--bump" in sys.argv:
        bump_descriptor(DESCRIPTOR)
    module_id = read_module_id(DESCRIPTOR)
    classes = sorted(
        f for f in os.listdir(CLASSES_DIR) if f.endswith(".class")
    )
    if not classes:
        sys.exit("FEHLER: keine .class-Dateien in classes/")

    manifest = MANIFEST_TEMPLATE.format(module_id=module_id)

    with zipfile.ZipFile(OUT, "w") as z:
        z.writestr(zipfile.ZipInfo("META-INF/MANIFEST.MF"), manifest,
                   compress_type=zipfile.ZIP_STORED)
        z.write(DESCRIPTOR, "module-descriptor.xml",
                compress_type=zipfile.ZIP_DEFLATED)
        for cls in classes:
            z.write(os.path.join(CLASSES_DIR, cls), cls,
                    compress_type=zipfile.ZIP_DEFLATED)

    # mirror into webapp payload dir
    for dst in MIRRORS:
        dst = os.path.normpath(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(OUT, "rb") as src_f, open(dst, "wb") as dst_f:
            dst_f.write(src_f.read())

    print(f"OK: {OUT} ({os.path.getsize(OUT)} B, ObjectId={module_id})")
    for dst in MIRRORS:
        print(f"    -> {os.path.normpath(dst)} ({os.path.getsize(dst)} B)")


if __name__ == "__main__":
    main()
