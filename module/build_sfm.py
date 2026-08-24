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


def main() -> None:
    module_id = read_module_id(DESCRIPTOR)
    classes = sorted(
        f for f in os.listdir(CLASSES_DIR) if f.endswith(".class")
    )
    if not classes:
        sys.exit("FEHLER: keine .class-Dateien in classes/")

    manifest = MANIFEST_TEMPLATE.format(module_id=module_id)

    # 1) Descriptor laden und rpcEntryPoint-Elemente einfügen
    import xml.etree.ElementTree as _ET
    tree = _ET.parse(DESCRIPTOR)
    root = tree.getroot()
    entry_points = root.find("entryPoints")
    # Prüfen ob rpcEntryPoints schon existieren (sonst beim nächsten Build doppelt)
    existing = entry_points.findall("rpcEntryPoint") if entry_points is not None else []
    rpc_classes = ["ListGet", "ListAdd", "ListRemove"]
    if not existing:
        import uuid as _uuid
        for cls_name in rpc_classes:
            if cls_name not in classes:
                continue
            eid = str(_uuid.uuid4())
            rpc_ep = _ET.SubElement(entry_points, "rpcEntryPoint")
            rpc_ep.set("id", eid)
            rpc_ep.set("name", cls_name)
            fr = _ET.SubElement(rpc_ep, "functionReference")
            fr.set("targetDomainId", module_id)
            fr.set("targetId", str(_uuid.uuid4()))
            fr.set("targetName", cls_name)
            fr.set("targetVersion", "0")
            tp = _ET.SubElement(rpc_ep, "type")
            tp.text = "XMLRPC_auth"
        tree.write(DESCRIPTOR, encoding="UTF-8", xml_declaration=True)

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
