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
  2. **Detail je Anlage** — „STARFACE Anlagen-Detail“ (UID `starface-anlage-detail`; seit v0.0.126 fester Titel, Anlagenname in der Beschreibung `Anlage: ${installation}` — kein roher Platzhalter mehr beim Direktaufruf): RAM %, Load 1/5, CPU-Kerne, Provider verbunden + Provider-Detail-Table, Verläufe; öffnet per Link `?var-installation=<Name>` — **ein** Dashboard für alle Anlagen (skaliert automatisch).
  3. **Admin-Übersicht** — „STARFACE Admin-Übersicht (alle Anlagen)“ (UID `starface-admin-uebersicht`, **nur Admins**): Stat „Anlagen gesamt“, **„Anlagen mit Provider-Ausfall“** (FLUX-reduce: letzte `registered`-Werte je Anlage, Summe < Anzahl ⇒ Ausfall) und „Provider getrennt gesamt“, Tabellen „Ausfälle je Anlage“ (rot markiert, klickbar), RAM %/Load 1 je Anlage + Verläufe.
- **Datalinks:** Cell-Link auf `installation` → `/d/starface-anlage-detail/anlage-detail?var-installation=${__value.raw}&from=now-6h&to=now` (Global + Admin).
- **Einspielung:** per Service-Account-Token (Editor) → `/api/dashboards/db`; **alle 30 Panel-Queries gegen /api/ds/query validiert** (9+11+10 OK). Anleitung: `deploy/grafana/README.md`.
- **FLUX-Pitfalls (dokumentiert):** `float(v: …)` statt `float(…)`; **nie `group()` über alle Felder eines Measurements** (int/float-Schema-Kollision) — vorher auf EIN `_field` filtern (z. B. `load1`).
- **Basis-URL konfigurierbar (WebApp v0.0.121):** Seit v0.0.121 kann der Admin die externe Grafana-Domäne in der WebApp hinterlegen (**Admin → Einstellungen → „Grafana-Basis-URL“**, z. B. `https://www.sub.example.de`). Priorität bei der Link-Generierung (Startseite + Monitoring): **Admin-Einstellung > Env `GRAFANA_BASE_URL` > Default `http://10.0.25.60:8894`** — Änderung wirkt sofort (kein Container-Restart, kein Compose-Edit nötig). Gespeichert in neuer `settings`-Tabelle (key/value); `_grafana_base()` zentral.
- **Kiosk-Parameter (WebApp v0.0.131 + v0.0.133, Grafana 13):** Seit Grafana 13 akzeptiert die URL-Auswertung (`setKioskModeFromUrl`) NUR noch `kiosk=1` (→ Vollbild-Kiosk, `chromeless`: Sidebar UND obere Leiste/Zeitleiste weg). Die früheren Werte `kiosk=tv`/`kiosk`/`kiosk=full` sind im Nav-Umbau entfernt und werden **still ignoriert** (Dashboard erscheint komplett). Seit v0.0.131 setzen alle WebApp-Links + Global-Datalink `&kiosk=1`. **Seit v0.0.133 zusätzlich `&hideLogo`:** Der sticky „Powered by Grafana“-Branding-Footer (Kiosk-Erfindung, PR grafana#115202, merged 2026-01-24) klebt im Kiosk am Viewport fest und „scrollt mit“ → mitten im Bild. Offizielles Opt-out ist der URL-Param `hideLogo` (`hideLogo=false`/`0` erzwingt die Anzeige). Zeitraum fest via `&from=now-6h&to=now` (kein Timepicker im Kiosk).
- **Kiosk-Sicherheit (WebApp v0.0.124):** Die `installation`-Variable ist in allen 3 Dashboards auf `hide: 2` gesetzt (live per API gepatcht, Versionen 2/5/6) — das Anlagen-Dropdown oben rechts im Kiosk-/Dashboard-View ist entfernt. Die WebApp setzt `?var-installation=<Anlage>` je Link → jeder Klick-User sieht nur die per `can_read` freigegebene Anlage; ein Umstellen im UI ist unmöglich. Grenze: manuelle URL-Änderung von `var-installation` bleibt fachlich möglich (Anon-Viewer offen) — harte Rechte-Trennung erfordert anon-aus + Grafana-User je WebApp-Account (optionales weiteres Vorhaben).
- **Auto-Refresh (WebApp v0.0.135):** Die Monitoring-Seite aktualisiert sich jetzt wirklich alle 15 s (vorher stand nur der Text im Template — Timer-Code fehlte). Implementierung: `setInterval(refreshMonitoring, 15000)` → `fetch('/api/monitoring/status')` → DOM-Update (Sammler-KV + Installationen-Tabelle via `tbody id="inst-rows"`, XSS-sicher per `textContent`; Grafana-Link je Zeile aus `data-ghref`-Basis + URL-Encode). Browser-Beweis: Headless-Chrome, 1 API-Call direkt nach Load, +1 nach 17 s, 0 Console-Fehler; E2E-Test 15 prüft die Marker.
- **Ist-Zustand = Frische-Fenster 10 min (WebApp v0.0.135):** Die Flag-/Zähler-Panels („Anlagen mit Provider-Ausfall“, „Provider getrennt (gesamt)“, „Provider aktiv“, Provider-Tabellen) bewerten jetzt `range(start: -10m)` statt des gewählten Dashboard-Zeitfensters. Grund: Serienbruch — die alten Provider-Serien (`register=>user@sip…:5060/<Call-ID>` mit flüchtigem Suffix, `register` ohne `@`, `30632@…`) werden nicht mehr beschrieben; ihre letzten `0`-Werte lagen im 6h-Fenster und lösten den Fehlalarm „Provider getrennt, obwohl verbunden“ aus. Veraltete Serien gelten nun als **„keine Daten“ (≠ getrennt)**; die Historie bleibt in den Verlaufs-Panels sichtbar (Legacy-Serien dort per `r.provider != "register" and not r.provider =~ /^register=>/` gefiltert).
- **Design-Umbau (WebApp v0.0.135, live Global v13 / Admin v8 / Detail v5):** „Letzter Poll“ wieder befüllt (`keep(_time)` ohne Zahlfeld = No data → `map(_value: _time/1e6 ms)` + Unit `dateTimeFromNow`); „Provider registriert/aktiv“ = EINE frische Zahl (2-Target-Chaos 4+6 entfernt); Tabellen mit `Status`-Spalte „Registriert/Getrennt“ (Farb-Mapping statt roher 1/0); RAM%-Tabelle im Global-Stil (`aggregateWindow(1m, last)` → `pivot(rowKey:_time)` → Ram-Formel, war None durch `group(installation)|>last()`-Schema-Kollision); „Provider-Status je Anlage“ mit Spalten Provider gesamt/registriert/Alles ok (Ja/Nein-Färbung); Verläufe RAM+Load nebeneinander (6+6), Provider-Status-Y-Achse fix 0..1.
- **Admin-Übersicht-Link (WebApp v0.0.122):** Monitoring-Seite zeigt Admins den Button **„Admin-Übersicht"**, Admin-Seite → Einstellungen → **„Grafana Admin-Übersicht öffnen"** — beide → `{base}/d/starface-admin-uebersicht/` (neuer Tab), UID `starface-admin-uebersicht`. Nicht-Admins sehen keinen der Links.
- **WICHTIG — Zugriff ohne Login:** Grafana war mit `GF_AUTH_ANONYMOUS_ENABLED=false` aufgesetzt → ALLE Dashboard-Links (Anlagen-Detail + Admin-Übersicht) liefen auf die Login-Seite (401). Fix im Stack-Compose (lokale Secrets-Datei, nicht im Repo): `GF_AUTH_ANONYMOUS_ENABLED: "true"` + `GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer`, dann `docker compose up -d grafana` (nur Grafana wird neu erstellt; Altdashboards/Provisioning bleiben). Sicherheitsmodell bleibt: wer die Links sieht, entscheidet die WebApp (`can_read`/Admin); anon-Viewer kann nur die 3 vorhandenen Dashboards lesen, sonst nichts.
- **Kiosk-Modus (WebApp v0.0.123):** Alle WebApp-Dashboard-Links hängen `&kiosk` an → Grafana zeigt nur das Dashboard ohne Sidebar/Menü (Zeitraum `from=now-6h&to=now` bleibt). Bewusst kein Public Dashboard/„Share external Link": Public Dashboards unterstützen KEINE `var-installation`-Variablen (Detail-Dashboard je Anlage unmöglich) und brauchen den Service-Account-Token. Datalink im Global-Dashboard („Anlage öffnen" → Detail) im Repo-JSON ebenfalls mit `&kiosk` — Deploy mit Token ausstehend.

## ZimaOS-Hinweis (Deploy-Vorbereitung)

Die ZimaOS-UI nutzt das **CasaOS-compose-Format** (x-casaos-Block, Ingress-Ports, Bind-Mounts unter `/DATA/AppData/*`) — deutlich anders als die Repo-`docker-compose.yml`. Die fertige ZimaOS-Datei (mit ECHTEN Zugangsdaten, daher nur lokal!) liegt unter `/opt/data/profiles/axel/starface-webapp-compose-zimaos.yaml` (Details: Hermes-Wiki-Entity telefonie-monitoring.md). Drei Platzhalter vor dem ersten Start ersetzen: InfluxDB-Passwort, InfluxDB-Token (an 3 Stellen identisch), Grafana-Passwort. Grafana-Datasource-Provisioning unter `/DATA/AppData/starface-webapp/grafana-provisioning/datasources/influxdb.yml` ablegen (Vorlage im Repo, secret-frei).

## Offene Punkte

- **Modul-Auto-Update (geplant, 2026-08-26):** Update-Server als 4. Stack-Service + zentrales Updater-Modul — Architektur & Plan: [[modul-auto-update]]
- **v4-Import auf der Anlage** (TelefonieMonitoring.sfm v4 → STARFACE-Admin, Instanz neu speichern) — danach Statusseite grün + saubere `user@host`-Providernamen in Grafana
- **InfluxDB-Bucket `telefonie`:** alte `providers`-Points (vor v0.0.119) enthalten rohe Wire-Settings-Strings mit SIP-Anmeldedaten → bereinigen/rotiert werden
- Dashboard-Verfeinerung (z. B. CPU-Auslastung, Alerts, mehr Anlagen) nach Bedarf
