---
title: Projekt Telefonie-Monitoring + Grafana
description: Umgesetzte Erweiterung des Stacks um Grafana (Port 8894) und InfluxDB — die WebApp-Statusseite + Sammler schreiben per XML-RPC nach InfluxDB, Grafana visualisiert (Dashboard deployed 2026-08-25). Stand: live.
updated: 2026-08-25
---

# Projekt: Telefonie-Monitoring + Grafana (WebApp-Stack)

**Status: Umgesetzt** (LIVE seit 2026-08-25 — Betriebsanleitung siehe [[starface-telefonie-monitoring]]; diese Seite ist der ursprüngliche Projektplan). Ziel: STARFACE-Anlagendaten (analog zum sezierten Firmenmodul `XmlMonitoring_v152`) in Grafana visualisieren — die WebApp sammelt per XML-RPC und schreibt nach InfluxDB; Grafana liest daraus.

## Architektur (mit Nutzer abgestimmt, 2026-08-25)

| Dienst | Rolle | Port (Host) | Erreichbarkeit |
|---|---|---|---|
| `starface-webapp` | bestehender Sammler (FastAPI), holt Modul-Daten, schreibt InfluxDB | 8895 → 8000 | öffentlich (NPM) |
| `grafana` | Dashboards für Admins | **8894** → 3000 | öffentlich (NPM), Login via .env-Passwort |
| `influxdb` | Zeitreihen-DB (Org `starface`, Bucket `telefonie`) | – | **nur intern** (Dienstname `influxdb:8086`) |

Entscheidungen: **ein docker-compose-Stack** (ein `up -d`, geteilte Volumes), **keine Integration in den WebApp-Container** (Image-Größe, Update-Kopplung, gemeinsamer Restart, Sicherheit), Secrets ausschließlich in `.env` (gitignored; Vorlage `.env.example`).

## Im Repo angelegt (Commit-Referenz siehe Hermes-Wiki log.md)

- `docker-compose.yml` — Dienste `grafana` + `influxdb` ergänzt; WebApp-Dienst unverändert (Name, Port, Volume) → **bestehende Instanz läuft beim Wechsel weiter**
- `.env.example` — `INFLUXDB_ADMIN_PASSWORD`, `INFLUXDB_TOKEN`, `GRAFANA_ADMIN_PASSWORD`
- `grafana/provisioning/datasources/influxdb.yml` — automatische Datasource (Flux, Bucket telefonie, Token aus ENV)
- `deploy/grafana/telefonie-monitoring.json` — **Grafana-Dashboard „STARFACE Telefonie-Monitoring“** (UID `starface-telefonie-monitoring`, 11 Panels; deployed via API, Version 3, 2026-08-25)
- `deploy/grafana/README.md` — Bereitstellungs-Anleitung (API + Provisioning), Messwert-Schema, FLUX-Pitfalls

## Umsetzung (später, in dieser Reihenfolge)

1. **STARFACE-Modul** bauen nach Baurezept ([[starface-modul-designer]]): Designer-Funktion(en) `getMonitoringData` → rpcEntryPoint `GetMonitoringData` (Wrapper-Muster aus [[module-reverse-engineering]])
2. **WebApp-Sammler**: Cron-Task pollt Modul (JWT-Auth), schreibt Messpunkte nach InfluxDB (`measurement=starface`)
3. **Grafana-Dashboard(s)** provisionieren
4. **ZimaOS-Deploy**: `docker compose up -d` (Stack), NPM-Route `10.0.25.60:8894` → grafana (Proxy-Regeln wie WebApp: Websockets, `client_max_body_size 500m`)
5. Compose-Prüfung (Skill) + Wiki/Push

## Grafana-Dashboard (deployed 2026-08-25)

- **Aufbau** (UID `starface-telefonie-monitoring`, Schema 39): Row „Übersicht“ (Stat: RAM-Auslastung %, Load 1, Provider verbunden, Letzter Poll — je Template-Variable `installation`), Row „Provider-Status (alle Anlagen)“ (Table: Installation/Provider/registered/letzter Poll, grün/rot hinterlegt) und Row „Zeitverläufe“ (Time-Series: RAM % je Anlage, Load 1/5/15 je Anlage, Provider 0/1-Step-Series).
- **Queries:** FLUX gegen Bucket `telefonie` (`system`: mem_* in kB → %, load1/5/15; `providers`: `registered` 1/0, Tag `provider` = `user@host`). Variable `installation` = `schema.tagValues(bucket: "telefonie", tag: "installation")`, Default per API gesetzt.
- **Einspielung** (Stand 2026-08-25): per Admin-Service-Account-Token (Editor-Rolle) → `/api/dashboards/db`, überwrite; alle Panel-Queries gegen `/api/ds/query` validiert (8/8 OK, Live-Daten vorhanden). Detail-Anleitung in `deploy/grafana/README.md`.
- **`float(v: …)`-Regel:** FLUX-Typkonvertierung nur mit benanntem Argument (`float(v: r.mem_total)`); `float(r.mem_total)` ist ein Kompilierfehler.

## ZimaOS-Hinweis (Deploy-Vorbereitung)

Die ZimaOS-UI nutzt das **CasaOS-compose-Format** (x-casaos-Block, Ingress-Ports, Bind-Mounts unter `/DATA/AppData/*`) — deutlich anders als die Repo-`docker-compose.yml`. Die fertige ZimaOS-Datei (mit ECHTEN Zugangsdaten, daher nur lokal!) liegt unter `/opt/data/profiles/axel/starface-webapp-compose-zimaos.yaml` (Details: Hermes-Wiki-Entity telefonie-monitoring.md). Drei Platzhalter vor dem ersten Start ersetzen: InfluxDB-Passwort, InfluxDB-Token (an 3 Stellen identisch), Grafana-Passwort. Grafana-Datasource-Provisioning unter `/DATA/AppData/starface-webapp/grafana-provisioning/datasources/influxdb.yml` ablegen (Vorlage im Repo, secret-frei).

## Offene Punkte

- **v4-Import auf der Anlage** (TelefonieMonitoring.sfm v4 → STARFACE-Admin, Instanz neu speichern) — danach Statusseite grün + saubere `user@host`-Providernamen in Grafana
- **InfluxDB-Bucket `telefonie`:** alte `providers`-Points (vor v0.0.119) enthalten rohe Wire-Settings-Strings mit SIP-Anmeldedaten → bereinigen/rotiert werden
- Dashboard-Verfeinerung (z. B. CPU-Auslastung, Alerts, mehr Anlagen) nach Bedarf
