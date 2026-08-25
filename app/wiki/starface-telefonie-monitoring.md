---
title: STARFACE Telefonie-Monitoring (Modul + WebApp-Sammler)
description: Modul TelefonieMonitoring (Systemmetriken + SIP-Provider-Status) und WebApp-Sammler nach InfluxDB — Import- und Betriebsanleitung für Admins.
updated: 2026-08-25
---

# STARFACE Telefonie-Monitoring

Der Stack (WebApp + Grafana + InfluxDB) sammelt System- und SIP-Provider-Daten
der STARFACE-Anlage und zeigt sie in Grafana. Das STARFACE-Modul **TelefonieMonitoring**
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

- **Status-Route**: `last_error` zeigt Poll-Fehler (Token, RPC, InfluxDB).
- **Modul-Log** (STARFACE Admin → Module → Instanzen → Log): Rohwerte von
  `getRegisterForProviderLines()` + `sip show registry` beim ersten Lauf.
- **Grafana**: Datasource `InfluxDB` (Bucket `telefonie`) muss grün sein.

## Versionshistorie (kompakt)

### Modul (TelefonieMonitoring.sfm)

| Version | Datum | Inhalt |
|---|---|---|
| v4 | 2026-08-25 | **Status-Name-Fix + Security:** `providerStatus`-Namen sind jetzt `user@host` statt der rohen Wire-Settings-Zeile (`register=>user:pass@host:port/…`) — die enthielt ein `=` (brach das WebApp-Format „Name=Status“ → fälschlich „getrennt“ trotz Registered) und das SIP-Passwort (wäre als InfluxDB-Tag/Feld gelandet). Parser liefert `306326@sip.iks-computer.de=Registered`. |
| v3 | 2026-08-25 | **dnsmgr-Spalten-Fix:** STARFACE schiebt in `sip show registry` eine `dnsmgr`-Spalte ein (State in Spalte 5 statt 4) — Status wird jetzt spalten-unabhängig per „Registered“-Token-Scan erkannt (`extractState`), User/Port robust extrahiert; bewiesen gegen das echte Cloud-Log der Anlage. |
| v2 | 2026-08-25 | **Import-Fix:** Alle 36 Call-Output-Variablen im Descriptor ohne `OUT_`-Präfix (exakt die Java-Feldnamen von `SystemStatsMonitor`) — vorher „Output variable not found … Signatur geändert“ beim Import; `verify_descriptor_refs.py` validiert die Namen jetzt automatisch (Negativtest am alten Descriptor etabliert). **IMPORT-BEREIT**, von der STARFACE-Installation akzeptiert. |
| v1 | 2026-08-25 | Erstversion: Systemmetriken (Speicher, Load, Prozesse, CPU-Kerne, Starface-Version) + SIP-Provider-Status (`sip show registry`) über RPC-Wrapper `GetStats` (XmlMonitoring-Muster, JWT-Auth); Import scheiterte am Signatur-Mismatch der Output-Variablen → v2. |

### Web-App (Sammler + Statusseite)

| Version | Datum | Inhalt |
|---|---|---|
| v0.0.119 | 2026-08-25 | **Provider-Parsing robust:** `_provider_summary` und `build_points` splitten am **letzten** `=` (rsplit) — Namen dürfen kein `=` brechen mehr den Status (Defense-in-Depth zu Modul v4, das ohnehin saubere `user@host`-Namen liefert); Regressionstests für „`=` im Namen“ ergänzt. |
| v0.0.118 | 2026-08-25 | **Registered-Präfix-Toleranz:** Status-Verbunden-Check als `startswith("Registered")` (deckt „Registered (2 devices)“-Varianten ab); Modul v3-Download. |
| v0.0.117 | 2026-08-25 | **Badge-Text eindeutig:** Roter Badge zählt Getrennte — „Provider getrennt (x von y)“ statt mehrdeutigem „0/2“. |
| v0.0.116 | 2026-08-25 | App-Wiki-Versionshistorie + Doku. |
| v0.0.115 | 2026-08-25 | **Provider-Status-Badges** auf `/admin/monitoring`: grün „Alle Provider verbunden“, rot „Provider getrennt (x/y)“ mit Details, grau „Keine Provider“; Auswertung zentral in `monitoring._provider_summary` (auch in der Status-API). |
| v0.0.109 | 2026-08-25 | **Statusseite `/admin/monitoring`:** Sammler-Status (Poll-Läufe, Points, Intervall, Fehler rot) + letzte Werte je Installation, Auto-Refresh 15 s; Nav-Link. |
| v0.0.108 | 2026-08-25 | Modul v2 (siehe oben) — WebApp stellt die korrigierte `.sfm` zum Download bereit. |
| v0.0.107 | 2026-08-25 | Feld **Monitoring-Modul-Instanz** in den Anlagen-Stammdaten (getrennt vom CallBlocker-Feld) — Voraussetzung, damit der Sammler die Anlage pollt. |
| v0.0.105 | 2026-08-25 | **Sammler:** Poll-Loop (GetStats je Installation mit Instanzname), Messwerte nach InfluxDB (Measurements `system`/`providers`), Status-JSON `/api/monitoring/status`; Stack Grafana + InfluxDB im Docker-Compose. |
