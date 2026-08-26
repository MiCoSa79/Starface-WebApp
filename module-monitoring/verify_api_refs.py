#!/usr/bin/env python3
"""verify_api_refs.py — STARFACE-API-Regressionsschutz fuer Modul-Java-Klassen.

Erkennt die Falle 'Interface-Methode deklariert, aber in der Implementierung
nicht vorhanden': ModuleRegistry.getInstances4Module() steht im Interface, wird
von ModuleRegistryBase (Implementierung der Anlage) aber NICHT implementiert ->
Laufzeit-Fault 'No item with that key' auf der Anlage (Befund 2026-08-26,
Testanlage, Modul v5).

Ablauf:
  1. Kompiliert module-monitoring/src/*.java gegen die lokale STARFACE-
     Extraktion (/opt/data/starface-extract/webapps/localhost/starface/
     WEB-INF/classes + WEB-INF/lib/*).
  2. Listet per `javap -c -p` ALLE gerufenen de.vertico.starface-Methoden der
     Modul-Klassen auf (owner / name / JVM-Descriptor).
  3. Prueft je Aufruf: Owner-Klasse existiert in der Extraktion UND die Methode
     ist in der Owner-Klasse ODER in deren '*Base'-Implementierung vorhanden
     (nicht nur im Interface!).
  4. Selbsttest: die bekannte Nicht-Implementierung getInstances4Module MUSS
     als fehlend erkannt werden, sonst bricht das Skript selbst ab.

Usage:  python3 module-monitoring/verify_api_refs.py
Exit 0: alle gerufenen STARFACE-API-Methoden existieren in der Implementierung.
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
CLASSES = os.path.join(ROOT, "classes")
WEBINF = "/opt/data/starface-extract/webapps/localhost/starface/WEB-INF"
EXTRACT = os.path.join(WEBINF, "classes")
LIBS = os.path.join(WEBINF, "lib")
JAVAC = "/opt/data/jdk-21.0.6+7/bin/javac"
JAVAP = "/opt/data/jdk-21.0.6+7/bin/javap"

CALL_RE = re.compile(
    r"//\s*(?:Interface)?Method\s+(de/vertico/starface/[^\s:]+):(\S+)"
)
DESC_RE = re.compile(r"^\s*descriptor:\s*(\S+.*)$")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r


def build() -> None:
    # Alte .class-Dateien entfernen, damit keine stale/oertlichen Artefakte in
    # die Aufruf-Analyse einfliessen (anonyme $1-Klassen etc.).
    if os.path.isdir(CLASSES):
        shutil.rmtree(CLASSES)
    os.makedirs(CLASSES)
    cp = EXTRACT + os.pathsep + LIBS + "/*"
    r = run([JAVAC, "-encoding", "UTF-8", "-proc:none",
             "-cp", cp, "-d", CLASSES] +
            [os.path.join(SRC, f) for f in sorted(os.listdir(SRC))
             if f.endswith(".java")])
    if r.returncode != 0:
        sys.exit("FEHLER beim Kompilieren:\n" + r.stdout + r.stderr)


def called_methods(classfile):
    """{(owner, name, desc)} aller de.vertico-Aufrufe der Klasse."""
    r = run([JAVAP, "-c", "-p", "-classpath", CLASSES,
             os.path.splitext(os.path.basename(classfile))[0]])
    found = set()
    for line in r.stdout.splitlines():
        m = CALL_RE.search(line)
        if not m:
            continue
        owner_slash, desc = m.group(1), m.group(2)
        # owner_slash = "de/vertico/.../Klasse.Methode" — letzter Slash vor der
        # Klasse, letzter Punkt zwischen Klasse und Methode; javap quotet
        # Konstruktoren ("<init>"), die Quotes hier entfernen.
        slash = owner_slash.rfind("/")
        dot = owner_slash.rfind(".", slash + 1)
        cls = owner_slash[:dot].replace("/", ".")
        name = owner_slash[dot + 1:].strip('"')
        found.add((cls, name, desc))
    return found


def methods_of(cls):
    """{(name, desc)} der Klasse via javap -p -s; leere Menge wenn nicht da."""
    path = os.path.join(EXTRACT, cls.replace(".", "/") + ".class")
    if not os.path.exists(path):
        return None
    r = run([JAVAP, "-p", "-s", "-classpath", EXTRACT, cls])
    if r.returncode != 0:
        return set()
    base_name = cls.rsplit(".", 1)[-1]
    sigs = set()
    name, desc = None, None
    for line in r.stdout.splitlines():
        dm = DESC_RE.match(line)
        if dm:
            desc = dm.group(1).strip()
            if name:
                sigs.add((name, desc))
            continue
        tm = re.match(r"\s+(?:public|protected|private|abstract|static|final|synchronized)"
                      r"\s+([^()]*?)([A-Za-z_$][\w$]*?)\s*\(", line)
        if tm:
            # group(2) ist dank Lazy-Regex das letzte Token direkt vor "(" =
            # der Methodenname ("public de.vertico...Log2()" -> Log2)
            name = tm.group(2)
            # javap druckt Konstruktoren mit Klassennamen statt "<init>"
            if name == base_name:
                name = "<init>"
    return sigs


def hierarchy(cls, seen=None):
    """[cls, super, interfaces...] — Vererbungskette via javap-Kopf."""
    seen = seen or set()
    seen.add(cls)
    path = os.path.join(EXTRACT, cls.replace(".", "/") + ".class")
    if not os.path.exists(path):
        return []
    r = run([JAVAP, "-classpath", EXTRACT, cls])
    head = r.stdout.splitlines()[:4]
    line = next((l for l in head if "class " in l and "{" in l), "")
    result = [cls]
    m = re.search(r"extends\s+([\w.$]+)", line)
    if m:
        sup = m.group(1)
        if sup not in seen:
            result += hierarchy(sup, seen)
    m = re.search(r"implements\s+([\w.$,\s]+)", line)
    if m:
        for inf in re.split(r"[\s,]+", m.group(1)):
            if inf and inf not in seen:
                result += hierarchy(inf.replace("$", "."), seen)
    return result


def api_exists(owner, name, desc):
    """Existiert die Methode in der konkret ausgelieferten API?

    Strenge Regel fuer Kern-API (de.vertico...core.*): existiert eine
    '{owner}Base'-Klasse, zaehlt NUR die Basis-Implementierung — was nur in der
    abgeleiteten Klasse (z. B. Bean-/Proxy-Klasse) deklariert ist, gilt als
    NICHT verlaesslich (Falle getInstances4Module: nur in ModuleRegistry,
    nicht in ModuleRegistryBase -> Fault 'No item with that key').
    Ohne Base-Datei (model/runtime-Klassen) genuegt die Owner-Deklaration.
    """
    base_path = os.path.join(EXTRACT, owner.replace(".", "/") + "Base.class")
    if os.path.exists(base_path):
        base = methods_of(owner + "Base")
        if base is None:
            return None
        return (name, desc) in base
    # Ohne Base-Datei: Vererbungskette (super + interfaces) mit durchsuchen,
    # da javap nur die eigene Klasse zeigt (z. B. Module -> AbstractModule).
    for part in hierarchy(owner):
        sigs = methods_of(part)
        if sigs and (name, desc) in sigs:
            return True
    return False


def main() -> None:
    print("verify_api_refs: kompiliere Modul-Klassen ...")
    build()
    calls = set()
    for f in sorted(os.listdir(CLASSES)):
        if f.endswith(".class") and not f.startswith(("$", "ModuleStatus$")):
            calls |= called_methods(os.path.join(CLASSES, f))
    if not calls:
        sys.exit("FEHLER: keine de.vertico-Aufrufe gefunden")

    missing, ok = [], 0
    if os.environ.get("VR_DEBUG"):
        for owner, name, desc in sorted(calls):
            if owner.endswith("Log2") or owner.endswith("Execute4") or "ModuleRegistry" in owner:
                print(f"DBG {owner}.{name}{desc} -> {api_exists(owner, name, desc)}", file=sys.stderr)
    for owner, name, desc in sorted(calls):
        res = api_exists(owner, name, desc)
        if res is True:
            ok += 1
        elif res is None:
            missing.append(f"{owner}.{name}{desc}  (Klasse fehlt in Extraktion)")
        else:
            missing.append(f"{owner}.{name}{desc}  (nicht in Implementierung)")

    # Selbsttest: die bekannte Falle MUSS als fehlend erkannt werden.
    neg = api_exists("de.vertico.starface.module.core.ModuleRegistry",
                     "getInstances4Module", "(Ljava/lang/String;)Ljava/util/List;")
    if neg is not False:
        sys.exit(f"SELBSTTEST FEHLGESCHLAGEN: getInstances4Module wurde als {neg} erkannt")
    print("OK   Selbsttest: getInstances4Module (Interface-only) als FEHLEND erkannt")

    if missing:
        sys.exit("FEHLER — " + str(len(missing)) +
                 " API-Aufruf(e) existieren nicht in der Anlagen-Implementierung:\n  " +
                 "\n  ".join(missing))
    print(f"OK   {ok} gerufene STARFACE-API-Methoden alle in der Implementierung vorhanden")
    print("verify_api_refs: OK")


if __name__ == "__main__":
    main()
