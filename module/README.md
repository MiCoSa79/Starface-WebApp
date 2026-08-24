# STARFACE CallBlocker-Modul

Anrufblocker-Baustein für STARFACE 10.x — weist Anrufe unerwünschter
Rufnummern ab. Die Blocklist liegt **auf der Anlage** als Datei
`blocklist.txt` im Instanz-Ordner.

## Inhalt

```
module/
├── CallBlocker.sfm      # Fertiges Modul (JAR: META-INF/MANIFEST.MF + module-descriptor.xml + Klassen)
├── module-descriptor.xml # Modul-Beschreibung (Quelle für build_sfm.py)
├── build_sfm.py         # Baut die .sfm im STARFACE-10-JAR-Format
├── classes/             # Einzelne .class-Dateien (Fallback: GUI-Upload als Ressourcen)
└── src/                 # Java-Quellen (Kompilierung gegen STARFACE-10-Klassen)
```

> ⚠️ **WICHTIG (STARFACE 10.x):** Die `.sfm` ist ein **JAR**, kein nackter Zip!
> STARFACE öffnet sie als `JarFile` und verlangt `META-INF/MANIFEST.MF` mit
> `ObjectId=<Modul-UUID>` und `StarfaceModule_SpecVersion: 5`. Fehlt das Manifest,
> bricht der Import mit **„Modul konnte nicht importiert werden: Manifest fehlt!“** ab
> (auch wenn `module-descriptor.xml` korrekt im Root liegt).

| Datei | Zweck |
|---|---|
| `CallBlocker.class` | Call-Processing-Baustein (in Anrufroute einhängen) |
| `ListGet.class` | RPC-Entrypoint: Liste lesen |
| `ListAdd.class` | RPC-Entrypoint: Nummern hinzufügen |
| `ListRemove.class` | RPC-Entrypoint: Nummern entfernen |
| `ListManager.class` | Gemeinsame Datei-Logik (blocklist.txt) |

## Einbau auf der Anlage

### Variante A — Modul-Library (.sfm)

1. Admin-UI → **Module** → Modul-Library → **Importieren** → `CallBlocker.sfm` wählen.
2. Instanz anlegen: Name z. B. **CallBlocker** (der Instanzname wird nicht
   beim XML-RPC-Aufruf benötigt, ist aber für die Übersicht wichtig).
3. Baustein verwenden: Anrufroute der Ziel-Gruppe/-Nummer öffnen →
   **Components → Public → CallBlocker → CallBlocker** einfügen.
   Stage ist `PostTargetDetermination` (Ziel ist bekannt, Anruf noch nicht verbunden).
4. RPC-Entrypoints: Im Modul-Editor pro Funktion (`ListGet`/`ListAdd`/`ListRemove`)
   im ersten Tab **„Rpc Entrypoints“** freigeben.
5. `blocklist.txt` im Instanz-Ordner anlegen:
   `/var/starface/module/instances/repo/<InstanzID>/res/blocklist.txt`
   (eine Nummer pro Zeile; `#` = Kommentar).

### Variante B — Einzelklassen (Weg A aus SFWiki)

1. Modul-Editor → **Resources** → `classes/*.class` einzeln hochladen → **Apply**.
2. Funktionen `ListGet`, `ListAdd`, `ListRemove` als eigene Bausteine anlegen
   (Baustein-Name = Klassenname), RPC-Entrypoints freigeben.
3. `CallBlocker` in die Anrufroute einhängen (siehe oben).

## blocklist.txt-Format

Eine Nummer oder Wildcard pro Zeile:

```
+491512345678    # exakte Nummer (E.164)
+49*             # beginnt mit +49 (national kürzbar)
+49160*          # Vorwahl
2??              # beginnt mit 2, genau 2 weitere Ziffern
????             # genau 4 Ziffern
```

## Verhalten

- Treffer: Anruf wird abgewiesen (`hangup`) und ein Logeintrag erzeugt:
  `BLOCKED: Anruf von <Nummer> abgewiesen (Blocklist)`.
- Kein Treffer: Das Modul tut **nichts** — die Route läuft unverändert weiter.
- Wichtig: Bei Nicht-Treffer wird nie `answer()`/`parkCall()` aufgerufen.

## Kompilieren (bei Änderungen an src/)

```bash
javac -proc:none -cp "WEB-INF/classes:WEB-INF/lib/*" -d out src/*.java
```

STARFACE 10.x läuft mit **Java 21** (Klassen-Version 65) — ein JDK 8
reicht nicht aus. Die kompilierten Klassen ohne `package` (Default-Package),
damit der Modul-Editor sie als `Klassenname.class` direkt lädt.

## .sfm neu packen (nach src/-Änderungen)

```bash
# 1) kompilieren (oben), Ergebnis nach classes/ kopieren
# 2) Modul neu bauen (JAR-Format mit Manifest):
python3 build_sfm.py
# erzeugt module/CallBlocker.sfm und spiegelt nach ../app/modules/CallBlocker.sfm
```

Verifikation (Import-Pfad von STARFACE 10.x, mit JDK 21):

```bash
java -cp /tmp SfmCheck module/CallBlocker.sfm   # JarFile.getManifest() != null; SpecVersion<=5; ObjectId!
```

