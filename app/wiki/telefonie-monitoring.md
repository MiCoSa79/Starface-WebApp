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

- **Drei Dashboards** (Quell-JSONs in `deploy/grafana/`, alle per API deployed & Query-validiert):
  1. **Global** — „STARFACE Telefonie-Monitoring“ (UID `starface-telefonie-monitoring`): Übersicht je Anlage (RAM %, Load 1, Provider registriert, Letzter Poll), Provider-Status-Table **mit Datalinks** (Anlagen-Zeile klickbar → Detail), Zeitverläufe (RAM %/Load/Provider 0/1).
  2. **Detail je Anlage** — „STARFACE Anlage: ${installation}“ (UID `starface-anlage-detail`): RAM %, Load 1/5, CPU-Kerne, Provider verbunden + Provider-Detail-Table, Verläufe; öffnet per Link `?var-installation=<Name>` — **ein** Dashboard für alle Anlagen (skaliert automatisch).
  3. **Admin-Übersicht** — „STARFACE Admin-Übersicht (alle Anlagen)“ (UID `starface-admin-uebersicht`, **nur Admins**): Stat „Anlagen gesamt“, **„Anlagen mit Provider-Ausfall“** (FLUX-reduce: letzte `registered`-Werte je Anlage, Summe < Anzahl ⇒ Ausfall) und „Provider getrennt gesamt“, Tabellen „Ausfälle je Anlage“ (rot markiert, klickbar), RAM %/Load 1 je Anlage + Verläufe.
- **Datalinks:** Cell-Link auf `installation` → `/d/starface-anlage-detail/anlage-detail?var-installation=${__value.raw}&from=now-6h&to=now` (Global + Admin).
- **Einspielung:** per Service-Account-Token (Editor) → `/api/dashboards/db`; **alle 30 Panel-Queries gegen /api/ds/query validiert** (9+11+10 OK). Anleitung: `deploy/grafana/README.md`.
- **FLUX-Pitfalls (dokumentiert):** `float(v: …)` statt `float(…)`; **nie `group()` über alle Felder eines Measurements** (int/float-Schema-Kollision) — vorher auf EIN `_field` filtern (z. B. `load1`).
- **Basis-URL konfigurierbar (WebApp v0.0.121):** Seit v0.0.121 kann der Admin die externe Grafana-Domäne in der WebApp hinterlegen (**Admin → Einstellungen → „Grafana-Basis-URL“**, z. B. `https://monitoring.meiser.family`). Priorität bei der Link-Generierung (Startseite + Monitoring): **Admin-Einstellung > Env `GRAFANA_BASE_URL` > Default `http://10.0.25.60:8894`** — Änderung wirkt sofort (kein Container-Restart, kein Compose-Edit nötig). Gespeichert in neuer `settings`-Tabelle (key/value); `_grafana_base()` zentral.
- **Admin-Übersicht-Link (WebApp v0.0.122):** Monitoring-Seite zeigt Admins den Button **„Admin-Übersicht"**, Admin-Seite → Einstellungen → **„Grafana Admin-Übersicht öffnen"** — beide → `{base}/d/starface-admin-uebersicht/` (neuer Tab), UID `starface-admin-uebersicht`. Nicht-Admins sehen keinen der Links.
- **WICHTIG — Zugriff ohne Login:** Grafana war mit `GF_AUTH_ANONYMOUS_ENABLED=false` aufgesetzt → ALLE Dashboard-Links (Anlagen-Detail + Admin-Übersicht) liefen auf die Login-Seite (401). Fix im Stack-Compose (lokale Secrets-Datei, nicht im Repo): `GF_AUTH_ANONYMOUS_ENABLED: "true"` + `GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer`, dann `docker compose up -d grafana` (nur Grafana wird neu erstellt; Altdashboards/Provisioning bleiben). Sicherheitsmodell bleibt: wer die Links sieht, entscheidet die WebApp (`can_read`/Admin); anon-Viewer kann nur die 3 vorhandenen Dashboards lesen, sonst nichts.

## ZimaOS-Hinweis (Deploy-Vorbereitung)

Die ZimaOS-UI nutzt das **CasaOS-compose-Format** (x-casaos-Block, Ingress-Ports, Bind-Mounts unter `/DATA/AppData/*`) — deutlich anders als die Repo-`docker-compose.yml`. Die fertige ZimaOS-Datei (mit ECHTEN Zugangsdaten, daher nur lokal!) liegt unter `/opt/data/profiles/axel/starface-webapp-compose-zimaos.yaml` (Details: Hermes-Wiki-Entity telefonie-monitoring.md). Drei Platzhalter vor dem ersten Start ersetzen: InfluxDB-Passwort, InfluxDB-Token (an 3 Stellen identisch), Grafana-Passwort. Grafana-Datasource-Provisioning unter `/DATA/AppData/starface-webapp/grafana-provisioning/datasources/influxdb.yml` ablegen (Vorlage im Repo, secret-frei).

## Offene Punkte

- **v4-Import auf der Anlage** (TelefonieMonitoring.sfm v4 → STARFACE-Admin, Instanz neu speichern) — danach Statusseite grün + saubere `user@host`-Providernamen in Grafana
- **InfluxDB-Bucket `telefonie`:** alte `providers`-Points (vor v0.0.119) enthalten rohe Wire-Settings-Strings mit SIP-Anmeldedaten → bereinigen/rotiert werden
- Dashboard-Verfeinerung (z. B. CPU-Auslastung, Alerts, mehr Anlagen) nach Bedarf
