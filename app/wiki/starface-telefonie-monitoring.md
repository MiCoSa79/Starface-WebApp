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
