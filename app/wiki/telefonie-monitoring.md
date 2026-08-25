---
title: Projekt Telefonie-Monitoring + Grafana
description: Geplante Erweiterung des Stacks um Grafana (Port 8894) und InfluxDB — Admins visualisieren STARFACE-Anlagendaten über die WebApp als Sammler. Stand: Projektplan + docker-compose-Vorlage, Umsetzung ausstehend.
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
- `grafana/dashboards/README.md` — Ablageort für Dashboard-JSONs (noch keins)

## Umsetzung (später, in dieser Reihenfolge)

1. **STARFACE-Modul** bauen nach Baurezept ([[starface-modul-designer]]): Designer-Funktion(en) `getMonitoringData` → rpcEntryPoint `GetMonitoringData` (Wrapper-Muster aus [[module-reverse-engineering]])
2. **WebApp-Sammler**: Cron-Task pollt Modul (JWT-Auth), schreibt Messpunkte nach InfluxDB (`measurement=starface`)
3. **Grafana-Dashboard(s)** provisionieren
4. **ZimaOS-Deploy**: `docker compose up -d` (Stack), NPM-Route `10.0.25.60:8894` → grafana (Proxy-Regeln wie WebApp: Websockets, `client_max_body_size 500m`)
5. Compose-Prüfung (Skill) + Wiki/Push

## ZimaOS-Hinweis (Deploy-Vorbereitung)

Die ZimaOS-UI nutzt das **CasaOS-compose-Format** (x-casaos-Block, Ingress-Ports, Bind-Mounts unter `/DATA/AppData/*`) — deutlich anders als die Repo-`docker-compose.yml`. Die fertige ZimaOS-Datei (mit ECHTEN Zugangsdaten, daher nur lokal!) liegt unter `/opt/data/profiles/axel/starface-webapp-compose-zimaos.yaml` (Details: Hermes-Wiki-Entity telefonie-monitoring.md). Drei Platzhalter vor dem ersten Start ersetzen: InfluxDB-Passwort, InfluxDB-Token (an 3 Stellen identisch), Grafana-Passwort. Grafana-Datasource-Provisioning unter `/DATA/AppData/starface-webapp/grafana-provisioning/datasources/influxdb.yml` ablegen (Vorlage im Repo, secret-frei).

## Offene Punkte

- InfluxDB-Python-Client als neue WebApp-Dependency (CI-Build erweitern → Tagging-Folge)
- Welche Messwerte zuerst? Vorschlag: Telefone online, SIP-Provider, Lizenzauslastung, Backups, Log-Fehler
- Modul-Test nur über produktive Anlage (kein SSH; Admin-UI, Instanz-Log, Designer-Export)
