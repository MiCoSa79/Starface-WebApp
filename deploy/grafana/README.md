# deploy/grafana — Grafana-Dashboard „STARFACE Telefonie-Monitoring“

Versionierte Quelle für das Grafana-Dashboard **`starface-telefonie-monitoring`**
(Titel: „STARFACE Telefonie-Monitoring“, Schema-Version 39, Grafana 11.x).

## Enthalten

- `telefonie-monitoring.json` — **Global-Dashboard** „STARFACE Telefonie-Monitoring“ (UID `starface-telefonie-monitoring`): Übersicht je Anlage, Provider-Status-Table **mit Datalinks** (Spalte `installation` klickbar → Detail-Dashboard), Zeitverläufe.
- `anlage-detail.json` — **Detail-Dashboard je Anlage** (UID `starface-anlage-detail`, Titel „STARFACE Anlage: ${installation}"): RAM %, Load 1/5, CPU-Kerne, Provider verbunden + Provider-Detail-Table, Verläufe — alles für die per URL gewählte Anlage (`?var-installation=<Name>`).
- `admin-uebersicht.json` — **Admin-Dashboard** (UID `starface-admin-uebersicht`): alle Anlagen — Stat „Anlagen gesamt“, „Anlagen mit Provider-Ausfall“ (FLUX-reduce über letzte `registered`-Werte je Anlage), „Provider getrennt gesamt“, Tabellen (Ausfälle je Anlage rot, RAM %, Load 1) + Verläufe. **Nur für Grafana-Admins gedacht** (Folder-Rechte; aktuell hat ohnehin nur der Admin Zugang).

## Datenquellen (InfluxDB-Bucket `telefonie`, org `starface`)

| Measurement | Tags | Felder |
|---|---|---|
| `system` | `installation`, `host` | `mem_total/mem_free/mem_available/buffers/cached/swap_cached/active/inactive` (int, kB), `load1/load5/load15` (float), `procs_running/procs_total`, `cpu_cores`, `version` |
| `providers` | `installation`, `provider` (Format `user@host`) | `registered` (1/0), `status` (String) |

Alle Größen sind pro Poll (default 60 s) gemessene Momentanwerte (keine kumulativen Zähler).

## Bereitstellung

Zwei Wege:

### a) API (sofort wirksam, kein Neustart)

```bash
# Datasource-UID ermitteln:
curl -H "Authorization: Bearer <TOKEN>" http://10.0.25.60:8894/api/datasources
# In JSON im Repo ist der Platzhalter ${DS_INFLUXDB} — beim Upload durch die echte UID ersetzen.
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d @/tmp/payload.json http://10.0.25.60:8894/api/dashboards/db
# payload.json: {"dashboard": {…json mit echter UID…}, "overwrite": true}
```

Deploy-Skripte (lokal, nicht im Repo): `/opt/data/tmp/tmp_grafana_deploy2.py`
(baut Variablen-Default aus tagValues, setzt die UID, lädt hoch und validiert
anschließend ALLE Panel-Queries gegen `/api/ds/query`).

### b) Provisioning (reproduzierbar, erfordert Grafana-Neustart)

1. Datei nach `/DATA/AppData/starface-webapp/grafana-provisioning/dashboards/` kopieren.
2. Falls noch nicht vorhanden, `dashboards.yml` in `…/grafana-provisioning/dashboards/`:
   ```yaml
   apiVersion: 1
   providers:
     - name: 'starface'
       orgId: 1
       folder: ''
       type: file
       disableDeletion: false
       updateIntervalSeconds: 60
       options:
         path: /etc/grafana/provisioning/dashboards
   ```
3. Grafana-Container neu starten (`docker restart grafana` bzw. über ZimaOS).
   → Achtung: Provisioning überschreibt das API-deployed Dashboard (Version wird von
   der Datei übernommen; API-Änderungen danach gehen verloren, solange die Datei liegt).

## Dashboards im Überblick

| Dashboard | UID | Zweck | Link |
|---|---|---|---|
| Global | `starface-telefonie-monitoring` | Übersicht + Provider-Status + Verläufe, klickbare Anlagen-Zeilen | `/d/starface-telefonie-monitoring/` |
| Anlage (Detail) | `starface-anlage-detail` | Eine Anlage im Detail (Variable `installation`) | `/d/starface-anlage-detail/?var-installation=<Name>` |
| Admin-Übersicht | `starface-admin-uebersicht` | ALLE Anlagen, Ausfall-Zählung, nur Admins | `/d/starface-admin-uebersicht/` |

**Datalinks:** Im Global- und Admin-Dashboard ist die Spalte `installation` als Klick-Link
konfiguriert (Cell-Typ `link`, URL `/d/starface-anlage-detail/anlage-detail?var-installation=${__value.raw}&from=now-6h&to=now`).

**Rechte-/Sichtbarkeits-Modell (Stand 2026-08-25):** Grafana kennt die WebApp-Benutzer und
deren `access`-Rechte (can_read/can_write) nicht. Aktuell hat nur der Grafana-Admin Zugang
(plus Service-Account). Die rechtebasierte Link-Anzeige („nur Anlagen mit Leserecht") ist als
**WebApp-Erweiterung** geplant (Monitoring-Seite für Benutzer mit Leserecht + gefilterte
„Grafana öffnen"-Links) — separates Release.

## Wartungshinweise

- **Template-Variable `installation`**: Query = `schema.tagValues(bucket: "telefonie", tag: "installation")`.
  Default wird beim Deploy per API auf den ersten Wert gesetzt; beim Provisioning
  wählt Grafana den ersten Wert beim Laden.
- **FLUX-Syntax**: Typkonvertierung NUR mit benanntem Argument, z. B. `float(v: r.mem_total)`
  — `float(r.mem_total)` ist in InfluxDB-FLUX ein Kompilierfehler („expected comma in
  property list“). Dasselbe gilt für `int(v: …)`, `string(v: …)`.
- **Provider-Namen**: Measurement `providers`-Tag `provider` = `user@host` (sauber, ohne
  Kennwort — Modul v4). `registered` ist 1/0 → für Step-Charts/Schwellen.
- Änderungen hier + WebApp-Wiki + Hermes-Wiki pflegen (Wiki-Pflicht).
