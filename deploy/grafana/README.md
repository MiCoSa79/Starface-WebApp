# deploy/grafana — Grafana-Dashboard „STARFACE Telefonie-Monitoring“

Versionierte Quelle für das Grafana-Dashboard **`starface-telefonie-monitoring`**
(Titel: „STARFACE Telefonie-Monitoring“, Schema-Version 39, Grafana 11.x).

## Enthalten

- `telefonie-monitoring.json` — komplettes Dashboard (11 Panels/Zeilen), UID `starface-telefonie-monitoring`.

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
