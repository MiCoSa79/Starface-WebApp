---
title: STARFACE-Modul-Paketierung (.sfm als JAR)
description: Wie ein STARFACE-10.x-Modulpaket (.sfm) korrekt gebaut wird — Manifest, ObjectId, SpecVersion, zusätzliche Dateien, Verifikation, Stolperfallen. Gültig für alle Module.
updated: 2026-08-24
---

# STARFACE-Modul-Paketierung (.sfm als JAR)

Wiederverwendbare Anleitung, wie ein STARFACE-10.x-Modulpaket (`.sfm`) korrekt
gebaut wird — **gültig für ALLE Module**, nicht nur den Anrufblocker
(Repro: 2026-08-24 am CallBlocker-Modul, Import-Fehler „Manifest fehlt!").

## Kernregel: `.sfm` ist ein JAR, kein nackter Zip

STARFACE 10.x importiert Module über `ModuleImporterExporter.preloadModule()`:

```java
JarFile jar = new JarFile(file);
Manifest m = jar.getManifest();        // liest META-INF/MANIFEST.MF
checkModuleManifest(m);                // wirft InvalidModuleException
JarUtil.extractJar(file, tmpDir);
ModulePersister.loadModule(tmpDir);    // liest module-descriptor.xml aus dem Root
```

Fehlt `META-INF/MANIFEST.MF` (typischer Fall: „nackter" Zip mit nur
`module-descriptor.xml` + Klassen), ist `getManifest()` = `null` →
**Import-Fehler „Modul konnte nicht importiert werden: Manifest fehlt!"**

## Manifest-Pflichtattribute (aus `checkModuleManifest`/`exportPacket`)

| Attribut | Wert | Prüfung |
|---|---|---|
| `Manifest-Version` | `1.0` | Standard, Java ergänzt es |
| `ObjectId` | Modul-UUID | **muss** gesetzt sein, sonst `error.import.unknown.module.id`; Wert = `id="…"` aus der module-descriptor.xml |
| `StarfaceModule_SpecVersion` | `5` | Integer, muss **≤ 5** sein, sonst `error.import.incompatible.version` (nicht integer: `invalid.version`) |

`exportPacket` setzt exakt `ObjectId` + `StarfaceModule_SpecVersion=5`; Java
ergänzt `Manifest-Version: 1.0`, `Created-By`, `Create-Date`.

## Zusätzliche Dateien im JAR-Root

- **`module-descriptor.xml`** — Pflicht (wird nach der Manifest-Prüfung via
  JAXB geladen). Regeln:
  - Root-Attribute (Reihenfolge wie echte Descriptoren):
    `lastChangedTime moduleType createTime id name specVersion vendor version`
    (`specVersion="5"`, `id` = UUID = `ObjectId` im Manifest, `vendor`,
    `version="1"` …)
  - `<resources/>` und `<entryPoints/>` bleiben **leer** (wenn Entrypoints nicht
    im Descriptor deklariert werden) — Klassen liegen im Root, RPC-Entrypoints
    werden im Modul-Editor freigegeben (1. Tab der Funktion)
  - `<noLicenseId>` PFLICHT + **korrekter Wert**:
    `sha1Hex(id + lastChangedTime + "STARFACE")` —
    `requiresLicense = !noLicenseId.equals(getDoNotLicenceHash())`
    (Module.class, specVersion≥5). Falscher/fehlender Wert → Instanz-Start
    blockt „Unzureichende Modullizenz".
  - `writeHash` = **`sha1Hex(id)`** setzen (Hash des leeren Passworts) —
    **NIE leer!** Bytecode-Beweis:
    `checkWritePassword(pw) = Strings.equals(sha1Hex(id+pw), writeHash)`;
    leerer writeHash ⇒ Modul bleibt gesperrt (real verifiziert)
- **`*.class`** — Baustein-Klassen im Default-Package (kein `package`!), damit
  der Modul-Editor `Klassenname.class` direkt lädt.

## Pack-Rezept (Python)

```python
import zipfile

manifest = (
    "Manifest-Version: 1.0\r\n"
    f"ObjectId: {MODULE_UUID}\r\n"          # == id= in module-descriptor.xml
    "StarfaceModule_SpecVersion: 5\r\n"
)
with zipfile.ZipFile("Modul.sfm", "w") as z:
    # Manifest: STORED + erster Eintrag + CRLF-Zeilenenden + End-Newline
    z.writestr(zipfile.ZipInfo("META-INF/MANIFEST.MF"), manifest,
               compress_type=zipfile.ZIP_STORED)
    z.write("module-descriptor.xml", compress_type=zipfile.ZIP_DEFLATED)
    for cls in ["MeinBaustein.class", ...]:
        z.write(cls, compress_type=zipfile.ZIP_DEFLATED)
```

Fertiges, getestetes Beispiel: `module/build_sfm.py` im Repo
`MiCoSa79/Starface-WebApp` (baut + verifiziert + spiegelt nach `app/modules/`).

## Verifikation (exakter STARFACE-Importpfad, JDK 21)

```java
JarFile jar = new JarFile(new File(args[0]));
Manifest m = jar.getManifest();            // != null verlangen!
m.getMainAttributes().getValue("StarfaceModule_SpecVersion");  // "5"
m.getMainAttributes().getValue("ObjectId");                    // UUID
```

Zusätzlich: Zip-Listing muss `META-INF/MANIFEST.MF` (erster Eintrag) +
`module-descriptor.xml` + `.class`-Dateien im Root zeigen (z. B.
`md5sum`-Vergleich der Datei gegen die Quelle). Der Import klappt nur, wenn
beide Prüfstufen (Manifest, JAXB-Descriptor) durchlaufen.

## Stolperfallen

1. **Nackter Zip** (= altes, falsches Format) → „Manifest fehlt!"
2. `StarfaceModule_SpecVersion > 5` → „incompatible version"
3. `ObjectId` leer/falsch → „unknown module id"; **muss** mit der `id` im
   Descriptor übereinstimmen
4. `.class` mit `package`-Anweisung → Verzeichnis im JAR, Modul-Editor findet
   sie nicht
5. Manifest mit LF statt CRLF oder als letzter/komprimierter Eintrag — meist ok,
   aber STORED + CRLF + erster Eintrag ist das von Java (JarOutputStream)
   erzeugte Format und damit maximal kompatibel
6. Gleiche URL + fehlender Cache-Header beim WebApp-Download → iOS Safari
   liefert gecachte alte Datei (Modul-Download in der WebApp seit v0.0.34
   `Cache-Control: no-store`)
7. **Kompilieren vor dem Packen:** `build_sfm.py` kompiliert NICHT — erst
   `javac -cp <WEB-INF/classes>:<WEB-INF/lib/*> -d classes src/*.java`
   (JDK 21), DANN `build_sfm.py`.

## Verwandt

- [[starface-modul-designer]] — Bausteine, Descriptor, XML-RPC, Stolpersteine.
- [[starface-anrufblocker]] — Anwendungsprojekt (CallBlocker.sfm, Build-Skript im Repo).
