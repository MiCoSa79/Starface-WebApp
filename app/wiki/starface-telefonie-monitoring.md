---
title: STARFACE Telefonie-Monitoring (Modul + WebApp-Sammler)
description: Modul TelefonieMonitoring (Systemmetriken + SIP-Provider-Status) und WebApp-Sammler nach InfluxDB — Import- und Betriebsanleitung für Admins.
updated: 2026-08-26
---

# STARFACE Telefonie-Monitoring

Der Stack (WebApp + InfluxDB) sammelt System- und SIP-Provider-Daten
der STARFACE-Anlage. **Seit v1.0.55 (28.08.) ohne Grafana** — die WebApp visualisiert die
InfluxDB-Daten nativ (Anlagen-Detail- und Admin-Monitoring-Seite); die Grafana-Abschnitte
dieser Anleitung sind historisch (Stand 2026-08-26/28). Das STARFACE-Modul **TelefonieMonitoring**
liefert die Daten per XML-RPC, die WebApp pollt sie und schreibt sie nach InfluxDB.

## 1. Modul installieren

1. WebApp → Admin → **Module** → Modul **TelefonieMonitoring.sfm** herunterladen.
2. STARFACE-Admin-UI → Module → **Modul-Library** → Importieren → Datei auswählen.
   (Import prüft Manifest + Descriptor automatisch; das Modul ist lizenzfrei, keine Passwort-Sperre.)
3. Aus dem importierten Modul eine **Modul-Instanz** anlegen (z. B. Name `TelefonieMonitoring`)
   und **starten** — Instanz-Log zeigt beim ersten Abruf die Rohdaten der Provider-Liste.

## 2. Installation in der WebApp konfigurieren

Damit der Sammler die Anlage pollt, braucht die Installation ein **Modul-Instanz-Feld**:

1. WebApp → Admin → **Anlagen** → Installation bearbeiten.
2. Feld **Monitoring-Modul-Instanz** = Instanzname aus Schritt 1 (z. B. `TelefonieMonitoring`).
   (Das CallBlocker-Feld „Module Instance Name" bleibt davon unberührt — der Sammler nutzt
   sein eigenes Feld `monitoring_instance_name`.)
3. Verbindung testen (⚡ Test-Conn) — muss grün sein.
4. Nur Installationen mit gesetztem Instanz-Namen werden gepollt.
5. **Status prüfen:** WebApp → Admin → **Monitoring** (Nav, aktualisiert sich alle 15 s) — `Poll-Läufe` steigt, `Points geschrieben` > 0, Tabelle zeigt Hostname/Version/Provider; bei Problemen zeigt das rote Feld den exakten Fehler (auch als JSON unter `/api/monitoring/status`).

## 3. Datenfluss & Messwerte

Der Sammler (Hintergrund-Loop, Intervall 60 s) ruft `GetStats` per XML-RPC (JWT) auf
und schreibt in den InfluxDB-Bucket `telefonie`:

| Measurement | Tags | Felder |
|---|---|---|
| `system` | installation, host | version, mem_total, mem_free, mem_available, buffers, cached, swap_cached, active, inactive, load1, load5, load15, procs_running, procs_total, cpu_cores |
| `providers` | installation, provider | registered (0/1), status |

- **Anlagenname** = Hostname der Anlage (kein Modul-Instanzname).
- **StARFACE-Version** kommt aus dem System-Baustein `GetStarfaceVersion`.
- **Provider-Status** stammt aus `sip show registry` (Asterisk-CLI); nicht eingetragene
  konfigurierte Provider werden als `Not registered` gemeldet.

## 4. Konfiguration (ENV)

| Variable | Default | Zweck |
|---|---|---|
| `INFLUXDB_URL` | `http://influxdb:8086` | InfluxDB-Endpunkt |
| `INFLUXDB_TOKEN` | — | Schreib-Token (Bucket `telefonie`) |
| `INFLUXDB_ORG` | `starface` | InfluxDB-Organisation |
| `INFLUXDB_BUCKET` | `telefonie` | Bucket |
| `MONITORING_INTERVAL` | `60` | Poll-Intervall in Sekunden |

Status-Abfrage (Admin-Session): `GET /api/monitoring/status` — letzter Poll, Fehler,
letzte Werte pro Installation.

## 5. Fehlersuche

- **Status-Route**: `last_error` zeigt Poll-Fehler (Token, RPC, InfluxDB) als
  `{"msg": ..., "ts": ...}`. **Semantik (seit v0.0.136):** Der Fehler verschwindet
  automatisch, sobald ein Poll-Zyklus komplett fehlerfrei durchläuft (letzter
  erfolgreicher Poll ist dann neuer als der Fehler) — ein **weiterbestehender**
  Fehler wird nie nach Zeitablauf weggeblendet, sondern bleibt mit seiner
  Auftrittszeit (Europe/Berlin, Sommer-/Winterzeit automatisch) stehen.
- **Modul-Log** (STARFACE Admin → Module → Instanzen → Log): Rohwerte von
  `getRegisterForProviderLines()` + `sip show registry` beim ersten Lauf.
- **Grafana**: Datasource `InfluxDB` (Bucket `telefonie`) muss grün sein.

## 6. Modul-Status-Abgleich (Monitoring-Seite, ab v0.0.138 / Modul v5)

> **Seit v1.0.58 (F65): Die Karte ist von `/monitoring` GEPARKT** (kommt später woanders
> hin, z. B. eigene Seite/Admin-Bereich). Der Datenfluss ist unverändert: Der Sammler pollt
> `GetModuleStatus` weiter im 60-s-Takt in den Cache, `/api/monitoring/status` liefert
> `modules` weiter und die Detail-Seiten nutzen es weiter. Der komplette Karten-Aufbau
> (HTML + JS + CSS + Refresh-Anbindung) ist dokumentiert in der Skill-Referenz
> `modul-status-karte-geparkt-v158.md` — Wiedereinbau = kopieren + Test-Marker reaktivieren.

Die Monitoring-Seite zeigt pro Anlage den Status **der in der WebApp ausgelieferten „eigenen" Module**:

1. **SOLL-Module** liest die WebApp automatisch aus `app/modules/*.sfm` (jede gelieferte `.sfm` = ein erwartetes Modul; SOLL-Version = `module-descriptor.xml` → `version`). Aktuell: `CallBlocker` v30 + `TelefonieMonitoring` **v9** (F41: Passwortschutz writeHash=sha1(id+PW); davor F34: Vendor „Axel Meiser - Kraemer IT“, Monitoring ohne Modul-Log).
2. **IST-Zustand** je Anlage kommt aus dem neuen RPC-Entrypoint `GetModuleStatus` (Modul v7+): JSON-Liste aller installierten Module (Name, Version, Vendor) mit ihren Instanzen (aktiv/deaktiviert) — Quelle ist die interne `ModuleRegistry` der Anlage (eingebaute Module ohne Version/Vendor werden übersprungen). **Achtung API-Falle (Befund 26.08.):** `ModuleRegistry.getInstances4Module()` ist nur im Interface deklariert, fehlt in der Implementierung (`ModuleRegistryBase`) → Laufzeit-Fault „No item with that key"; v6 nutzt `getInstalledInstances()` + `getModuleId()`-Filter. Schutz: `module-monitoring/verify_api_refs.py`. **Diagnose seit v7:** der laufende `GetStats`-Pfad liefert zusätzlich den Output `moduleDiag` (rohe Registry-Daten inkl. `version` je Modul — der `Module.getVersion()`-Beweis); die Diagnose-Route zeigt ihn als `stats_diag`.
3. **Anzeige** als Karte „Modul-Status": je Anlage/Modul ein Badge — **Aktuell** (IST = SOLL), **Update verfügbar** (IST < SOLL, z. B. v27 → v28), **Nicht installiert** (Modul fehlt auf der Anlage) oder **Keine aktive Instanz** (installiert, aber keine Instanz läuft). Zusätzlich Version „IST → SOLL" und die Instanzen mit (aktiv)/(deaktiviert). Seit F44 (v0.0.198) zählen hinterlegte **Drittanbietermodule** zum SOLL: angezeigt werden sie auf der Karte nur, wenn sie auf der Anlage installiert sind (Badge „Drittanbieter").
4. **Fehlerbilder:**
   - Monitoring-Modul fehlt/nicht eingerichtet (XML-RPC-Fault bei `GetStats`) → Hinweis **„Monitoring-Modul nicht installiert oder eingerichtet"** je Anlage.
   - Modul zu alt (GetStats ok, `GetModuleStatus` fehlt) → „Monitoring-Modul-Version zu alt — GetModuleStatus fehlt (Update auf v7 erforderlich)".
   - Anlage nicht erreichbar (Transportfehler) → „Anlage nicht erreichbar".
   - falsche Zugangsdaten (HTTP 401/403) → „Zugangsdaten/Token ungültig".

Die Karte aktualisiert sich über den bestehenden 15-s-Refresh; ohne ausgelieferte Module (`app/modules` leer) wird sie ausgeblendet.

## Versionshistorie (kompakt)

### Modul (TelefonieMonitoring.sfm)

| Version | Datum | Inhalt |
|---|---|---|
| v8 | 2026-08-26 | **Vendor + Logging (Axel-Vorgabe, F34):** Vendor überall „Axel Meiser - Kraemer IT“; **ALLE Modul-Log-Einträge entfernt** (meminfo/loadavg-Fehler, moduleDiag, getRegisterForProviderLines, „sip show registry“-Rohdaten + `rc`, ModuleStatus-Exception-Log via Log2) — tote `log()`-Methode + Log2/Collections-Imports raus. Datenfluss unverändert (GetStats/GetModuleStatus per XML-RPC); Format-/Fehler-Check läuft ausschließlich WebApp-seitig. Tag `v8`. |
| v7 | 2026-08-26 | **Diagnose-Output `moduleDiag` (getVersion-Beweis):** `SystemStatsMonitor` (der nachweislich laufende GetStats-Pfad) liefert zusätzlich `moduleDiag` — rohe ModuleRegistry-Daten OHNE Filter: `modulesTotal`, `instancesTotal` sowie je Modul `id/name/version/vendor` (auch eingebaute, `version` kann `null` sein) + Instanzen (`name/disabled`); nutzt `ModuleRegistry.getModules()` + `Module.getVersion()/getVendor()/getId()/getName()` + `getInstalledInstances()`/`getModuleId()` — per `verify_api_refs.py` (17/17) gegen die Implementierung belegt, Bytecode-Beweis (javap: `Module.getVersion:()J`) erbracht. Bei Registry-Fehler: `{"error":…}` + Log2. Descriptor: Java-Funktion + GetStatsRpc-Wrapper + Call-Mapping (UUID `d17e96ae-…`). Zweck: den getVersion()-Beweis liefern, den der GetModuleStatus-Fault ("No item with that key") verweigert. Tag `v7`. |
| v5 | 2026-08-26 | **Modul-Status-Abgleich (GetModuleStatus):** neuer RPC-Entrypoint `GetModuleStatus` (XMLRPC_auth) → Java-Funktion `ModuleStatus` (`module-monitoring/src/ModuleStatus.java`): liest die `ModuleRegistry` (eingebaute Module gefiltert: `version==0` && Vendor leer) und liefert JSON-Array `[{id,name,version,vendor,instances:[{name,disabled}]}]`; bei Fehler `{"error":…}` + Log2. Descriptor: Java-Funktion + Wrapper `GetModuleStatusRpc` + `rpcEntryPoint` (Muster wie `GetStats`); `verify_descriptor_refs.py` 4 Funktionen OK. Tag `v5`. Datengrundlage für die Modul-Status-Karte der WebApp (v0.0.138). |
| v4 | 2026-08-25 | **Status-Name-Fix + Security:** `providerStatus`-Namen sind jetzt `user@host` statt der rohen Wire-Settings-Zeile (`register=>user:pass@host:port/…`) — die enthielt ein `=` (brach das WebApp-Format „Name=Status“ → fälschlich „getrennt“ trotz Registered) und das SIP-Passwort (wäre als InfluxDB-Tag/Feld gelandet). Parser liefert `306326@sip.iks-computer.de=Registered`. |
| v3 | 2026-08-25 | **dnsmgr-Spalten-Fix:** STARFACE schiebt in `sip show registry` eine `dnsmgr`-Spalte ein (State in Spalte 5 statt 4) — Status wird jetzt spalten-unabhängig per „Registered“-Token-Scan erkannt (`extractState`), User/Port robust extrahiert; bewiesen gegen das echte Cloud-Log der Anlage. |
| v2 | 2026-08-25 | **Import-Fix:** Alle 36 Call-Output-Variablen im Descriptor ohne `OUT_`-Präfix (exakt die Java-Feldnamen von `SystemStatsMonitor`) — vorher „Output variable not found … Signatur geändert“ beim Import; `verify_descriptor_refs.py` validiert die Namen jetzt automatisch (Negativtest am alten Descriptor etabliert). **IMPORT-BEREIT**, von der STARFACE-Installation akzeptiert. |
| v1 | 2026-08-25 | Erstversion: Systemmetriken (Speicher, Load, Prozesse, CPU-Kerne, Starface-Version) + SIP-Provider-Status (`sip show registry`) über RPC-Wrapper `GetStats` (XmlMonitoring-Muster, JWT-Auth); Import scheiterte am Signatur-Mismatch der Output-Variablen → v2. |

### Web-App (Sammler + Statusseite)

| Version | Datum | Inhalt |
|---|---|---|
| v0.0.148 | 2026-08-26 | **Aufräumen: Diagnose-Block „Rohdaten GetModuleStatus" entfernt** (Befund abgeschlossen, Karte zeigt „Aktuell" für beide Module): UI-Block in `monitoring.html` (Details/Select/Button/Pre + JS-Handler) und Endpoint `GET /api/monitoring/module-status-raw` + `stats_diag`-Logik in `main.py` entfernt; Test-Checks der Diagnose-Route aus `module_status_live.py` entfernt. Der Produktivpfad `_collect_module_status` (monitoring.py) bleibt unverändert. Suite: `module_status_test` + `module_status_live` + `monitoring_rechte_e2e` 17/17 + `error_box_test` grün. Damit ist der Modul-Status-Abgleich v0.0.138–v0.0.145 sauber abgeschlossen: Fault (v5/v6-Ära) → v7 + Diagnose (v0.0.143) → „Kein Token"-Route-Fix (v0.0.144) → ROOT CAUSE `members`-Struktur (v0.0.145) → grüne Karte (v0.0.146/147-Deploy). |
| v0.0.145 | 2026-08-26 | **ROOT CAUSE „Nicht installiert" trotz Installation gefunden (Struktur-Fehler, Modul-Status-Abgleich):** GetModuleStatus-Auswertung las `mres["moduleJson"]` auf **Top-Level**, die echte `_xmlrpc`-Antwort (main.py) ist aber `{"raw","values","members"}` → `moduleJson` lag **unter `members`** → `mres.get("moduleJson")` war **immer `None`** → `_compare_modules(expected, None)` → leere IST-Liste → alle Module *„Nicht installiert"* — obwohl die Anlage korrekt antwortete (Logs: 200, volle Liste; `stats_diag` zeigt `TelefonieMonitoring` v7 mit Instanzen Monitoring+TestMonitoring, `CallBlocker` v28 mit Anrufblocker-Test — **beide installiert + aktiv, Namen exakt wie SOLL**). GetStats las dagegen bereits korrekt `result.get("members")` — nur GetModuleStatus nicht. **Fix:** beide Lesestellen (monitoring.py `_collect_module_status`, main.py Diagnose-Route `raw`) auf `(mres.get("members") or {}).get("moduleJson")`. **Regression:** Test-Fakes liefern jetzt die echte `members`-Struktur (vorher flaches `{"moduleJson": …}` → maskierte den Bug seit v0.0.138) — der alte Code würde damit rot. **Namensform widerlegt:** Anlage führt Module exakt unter Descriptor-Namen (`TelefonieMonitoring`, `CallBlocker`), kein Anzeigename-Mismatch. Suite: `module_status_test` + `module_status_live` (Diagnose-Route raw=INSTALLED_OK) + `monitoring_rechte_e2e` 17/17 + `error_box_test` grün. Erwartung nach Deploy: Karte zeigt **Aktuell** für beide Module (IST v28/v7 = SOLL v28/v7). |
| v0.0.144 | 2026-08-26 | **Fix Diagnose-Route „Kein Token“ (Kurzschluss mit Namens-Befund):** `/api/monitoring/module-status-raw` selektierte nur `name,url,monitoring_instance_name` → der echte `_get_token(row)` fand die Auth-Spalten (`auth_id`, `client_secret`, `oauth_*`) nicht → KeyError → `token=None` → Dauerfehler „Kein Token fuer die Anlage verfuegbar“, obwohl der Poll (volles `SELECT *`) längst mit Token lief. Fix: Route nutzt `SELECT *` (wie Poll). Regression im Test: Der bisherige `_get_token`-Lambda-Mock maskierte den Spaltenfehler → neuer Fake prüft `inst.keys()` auf alle Auth-Spalten. **Nebenbefund:** `compare_modules` sucht SOLL-Namen exakt (`TelefonieMonitoring`, `CallBlocker`); die Anlage führt die Module aber möglicherweise unter Anzeigenamen („Telefonie-Monitoring“) → „Nicht installiert“ trotz Installation — Abgleich über **Modul-ID** statt Name ist der geplante Fix. Tests: `module_status_live` (inkl. Regression, Diagnose-Route zeigt `raw=INSTALLED_OK`), `module_status_test`, `monitoring_rechte_e2e`, `error_box_test` — alle grün. |
| v0.0.143 | 2026-08-26 | **Diagnose für den persistierenden GetModuleStatus-Fault (Modul v7):** Diagnose-Route `/api/monitoring/module-status-raw` führt zusätzlich `GetStats` live aus und zeigt `stats_diag` (der neue Modul-Output `moduleDiag`, geparst): rohe ModuleRegistry-Daten inkl. `Module.getVersion()`-Werte je Modul — der getVersion()-Beweis. Liefert die Anlage kein `moduleDiag` (`stats_diag: null`) = alte Instanz-Konfiguration (Befund). Zwischenstand 26.08. 13:30: Fault „No item with that key“ persistiert **nach** v6 (Interface/Impl-Fix reichte nicht; kein Log-Eintrag, String in keiner Klasse/keinem JAR der Extraktion, EntryPoint per faultCode-5-Test nachweislich registriert, Descriptor v5↔v6 strukturell identisch; Verdacht: veraltete Instanz „Monitoring“ aus v5-Ära → offener Test: Instanz löschen+neu anlegen). `GetModuleStatus` bekommt **keinen Parameter** (Descriptor-`inputVars` leer, WebApp sendet nur ein leeres Struct — GetStats identisch und läuft ⇒ Parameterspur widerlegt). Tests: `module_status_test` + `module_status_live` + `monitoring_rechte_e2e` (17/17) + `error_box_test` grün. **UPDATE 26.08. ~14:05 (ZimaOS-Logs, `[DEBUG _xmlrpc]`):** GetModuleStatus antwortet **status=200 mit KOMPLETTER Modul-Liste** (len≈8808 B, moduleJson mit id/name/version/vendor/instances) für BOTH „Monitoring“ UND die neue Instanz „TestMonitoring“ — **Fault überwunden** (der v7-Import baute die Instanz-Konfiguration neu auf). GetStats len≈14827 B (vorher 1810) ⇒ **`moduleDiag` wird live mitgeliefert** — getVersion-Beweis in der Antwort. Die Karte meldet weiterhin „Nicht installiert“ ⇒ `_compare_modules` findet CallBlocker/TelefonieMonitoring **in der Anlagen-Liste nicht** → Modul-Namen aus Logs extrahieren (`grep -oP '&quot;name&quot;:&quot;\K[^&]+' | sort -u`), offen: sind die Module in der Anlagen-Registry überhaupt registriert (Import als Modul?). |
| v0.0.142 | 2026-08-26 | **Root Cause identifiziert (Modul v6):** `ModuleRegistry.getInstances4Module(id)` ist nur im Interface deklariert, in der Implementierung (`ModuleRegistryBase`) nicht vorhanden → Laufzeit-Fault „No item with that key"; v6 nutzt `getInstalledInstances()` + `getModuleId()`-Filter. Neuer Schutz `verify_api_refs.py` (prüft jede Modul-API-Referenz gegen die extrahierte Implementierung, blockiert die Falle per Selbsttest). **Hinweis:** Der Fault persistierte danach weiter (siehe v0.0.143 — die „Root Cause behoben“-Annahme vom selben Tag wurde durch weitere Beweise widerlegt). |
| v0.0.140 | 2026-08-26 | **Fix „zu alt“-Meldung:** Anlage mit altem Monitoring-Modul (GetStats ok, GetModuleStatus-Fault) zeigt jetzt „Update auf v5 erforderlich“ — vorher fälschlich v28 (Fehlerzweig nahm `next(iter(expected))` = erstes SOLL-Modul/CallBlocker). Fix: `_module_expectations` liest `<rpcEntryPoint>`-Namen (`provides`), Fehlerzweig wählt das Modul, das `GetModuleStatus` exportiert; ohne provides keine Versions-Klammer. Live-Beweis PBX-ALT + Unit-Checks grün. |
| v0.0.138 | 2026-08-26 | **Modul-Status-Abgleich (eigene Module):** pro Installation wird nach `GetStats` zusätzlich `GetModuleStatus` (Modul v5) abgefragt und mit den SOLL-Modulen der App (`app/modules/*.sfm`, `module-descriptor.xml` → Version) verglichen — Anzeige als Karte **„Modul-Status (eigene Module)“** je Anlage/Modul: Badge Aktuell / Update verfügbar / Nicht installiert / Keine aktive Instanz, Version „IST → SOLL“ (z. B. v27 → v28), Instanz-Status (aktiv/deaktiviert). Fehler-Klassifikation `_classify_error`: XML-RPC-Fault → **„Monitoring-Modul nicht installiert oder eingerichtet“** (Kategorie `module`), Transportfehler → „Anlage nicht erreichbar“ (`unreachable`), HTTP 401/403 → auth; Modul zu alt → „…zu alt — GetModuleStatus fehlt (Update auf v5 erforderlich)“. Schlüssel `list` (Jinja-`m.items`-Kollision umgangen); Server-Render + JS `renderModuleRows` im 15-s-Refresh; Karte ausgeblendet ohne ausgelieferte Module. Tests: `module_status_test.py` (~50) + Live-Beweis `module_status_live.py`; Suite komplett grün. |
| v0.0.136 | 2026-08-26 | **Fehlerbox-Semantik + Zeitangabe:** `last_error` wird beim ersten komplett fehlerfreien Poll-Zyklus gelöscht (ein „Letzter Fehler“ verschwindet, sobald er **nicht mehr besteht** — auch wenn er Minuten alt ist) und bei weiterbestehendem Fehler **nie** nach Zeitablauf ausgeblendet (bleibt mit aktuellem Zeitstempel stehen). Fehler tragen jetzt `{"msg", "ts"}` — die Box zeigt die Auftrittszeit, alle Zeiten der Monitoring-Seite explizit `Europe/Berlin` (Sommer-/Winterzeit automatisch via `timeZone`). |
| v0.0.135 | 2026-08-25 | **Monitoring-Auto-Refresh (15 s):** Seitentext „aktualisiert sich alle 15 s“ war nur Text ohne Timer — jetzt `setInterval(refreshMonitoring, 15000)` + fetch `/api/monitoring/status` + DOM-Update (Browser-Beweis). Gleichzeitig Dashboard-Fehlalarm „Provider getrennt obwohl verbunden“ behoben (Ist-Panels nutzen 10-Minuten-Frische-Fenster statt 6h; Ursache: Serienbruch toter Legacy-Serien im Fenster) + Design-Umbau aller 3 Dashboards. |
| v0.0.120 | 2026-08-25 | **Monitoring für alle eingeloggten Benutzer + rechtebasierte Grafana-Links:** Route `/monitoring` statt admin-only, Anlagen-Filter nach `can_read` (Admin: alle), API `/api/monitoring/status` gefiltert, dezenter SVG-Icon-Button je Anlage → `starface-anlage-detail` (auch auf Dashboard-Karten), `/admin/monitoring` redirectet, Nav-Link für alle. |
| v0.0.119 | 2026-08-25 | **Provider-Parsing robust:** `_provider_summary` und `build_points` splitten am **letzten** `=` (rsplit) — Namen dürfen kein `=` brechen mehr den Status (Defense-in-Depth zu Modul v4, das ohnehin saubere `user@host`-Namen liefert); Regressionstests für „`=` im Namen“ ergänzt. |
| v0.0.118 | 2026-08-25 | **Registered-Präfix-Toleranz:** Status-Verbunden-Check als `startswith("Registered")` (deckt „Registered (2 devices)“-Varianten ab); Modul v3-Download. |
| v0.0.117 | 2026-08-25 | **Badge-Text eindeutig:** Roter Badge zählt Getrennte — „Provider getrennt (x von y)“ statt mehrdeutigem „0/2“. |
| v0.0.116 | 2026-08-25 | App-Wiki-Versionshistorie + Doku. |
| v0.0.115 | 2026-08-25 | **Provider-Status-Badges** auf `/admin/monitoring`: grün „Alle Provider verbunden“, rot „Provider getrennt (x/y)“ mit Details, grau „Keine Provider“; Auswertung zentral in `monitoring._provider_summary` (auch in der Status-API). |
| v0.0.109 | 2026-08-25 | **Statusseite `/admin/monitoring`:** Sammler-Status (Poll-Läufe, Points, Intervall, Fehler rot) + letzte Werte je Installation, Auto-Refresh 15 s; Nav-Link. |
| v0.0.108 | 2026-08-25 | Modul v2 (siehe oben) — WebApp stellt die korrigierte `.sfm` zum Download bereit. |
| v0.0.107 | 2026-08-25 | Feld **Monitoring-Modul-Instanz** in den Anlagen-Stammdaten (getrennt vom CallBlocker-Feld) — Voraussetzung, damit der Sammler die Anlage pollt. |
| v0.0.105 | 2026-08-25 | **Sammler:** Poll-Loop (GetStats je Installation mit Instanzname), Messwerte nach InfluxDB (Measurements `system`/`providers`), Status-JSON `/api/monitoring/status`; Stack Grafana + InfluxDB im Docker-Compose. |

## Ausblick (Entscheidung offen, 2026-08-26 — nichts gebaut): Grafana durch WebApp-Dashboards ablösen?

Axel: „Grafana-Dashboards gefallen mir nicht — brauchen wir Grafana überhaupt? Könnten wir eigene Monitoring-Dashboards im WebApp-Design bauen?" → **Ja, machbar + empfohlen, mit Aufgabenteilung:** InfluxDB (Bucket `telefonie`) bleibt als Speicher, nur Grafana als Anzeige-Schicht wird ersetzt; die WebApp liest dieselben Zeitreihen per Flux und rendert selbst (ECharts/uPlot, WebApp-Look, PWA/handy-tauglich, 15-s-Refresh vorhanden). Kern-Anspruch: Zeitverlauf-Diagnose („Provider getrennt obwohl verbunden“) und die Kern-Panels der 3 Dashboards (Global v13/Admin v8/Detail v5) 1:1 abbilden; Schrittweise mit Abnahme, Grafana bleibt bis dahin im Stack. Vollständige Analyse (Aufwand, Prozess, Optionen): Hermes-Wiki log.md F33 + Entity telefonie-monitoring.
