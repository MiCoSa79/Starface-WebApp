---
title: Backup vor Anlagen-Update (FR-001) — Konzept
description: Feature-Request (01.09.2026, wartet auf Freigabe): „Backup jetzt“ je Anlage anstoßen + herunterladen bzw. per SFTP ablegen (REST /server/backups/actions/run → state → files); erfolgreiches Backup als Pflicht-Voraussetzung vor jedem UpdateFromUrl. Machbarkeit am SDK verifiziert (STARFACE 10.0.2.5).
updated: 2026-09-01
---

# Backup vor Anlagen-Update (FR-001)

> **Status:** Konzept — wartet auf Freigabe durch Axel (kein Code, Stand 01.09.2026)
> **Machbarkeit:** am SDK der Anlage verifiziert (STARFACE 10.0.2.5, `starface-api.yaml` + Bytecode)
> **Detaillierte Version mit offenen Fragen:** `app/docs/feature-requests/FR-001-backup-vor-update.md` im Repo

## 1. Problem / Nutzen

1. Die WebApp stößt heute Anlagen-Modul-Updates an (`anlagen_update_plans` → `_run_due_plans` → `UpdateFromUrl` an das Deployer-Modul), **ohne vorher ein Backup der Anlage zu erstellen**. Ein Fehl-Update kann die Anlage in einen defekten Zustand bringen — ein Rollback geht dann nur über ein manuell gemachtes Backup.
2. Axel möchte außerdem **jederzeit per Klick** ein Backup einer Anlage anstoßen und **herunterladen** bzw. **in eine SFTP/FTP-Ablage legen** können.

## 2. Faktenlage (belegt)

| Fakt | Nachweis |
|---|---|
| Offizielle REST-API „Server/Backups": `PUT /server/backups/actions/run` (startet Job, 202 + `backupJobId`), `GET /server/backups/state/{id}` (progress 0.0–1.0, status, error), `GET /server/backups/files/{id}` (Download; Datei wird danach gelöscht, außer `keepBackupAfterDownload=true`), `PUT /server/backups/actions/restore` | `starface-api.yaml` Z. 3088–3250 |
| Auth: OAuth2-Password-Grant (`rest-client-headless`), Admin-Recht für „Server/Backups" | bestehendes App-Muster |
| Die Anlage kennt **kein klassisches FTP (Port 21)**; eingebaute Ziele: `HDD, USB, SD, MAIL, SMB, SFTP, DROPBOX` | `BackupLocationBean$Type` (javap) |
| Der ad-hoc-REST-Job schreibt **immer lokal auf die HDD** der Anlage — kein Ziel-Parameter; SFTP als Anlagen-Ziel nur über konfigurierte Zeitpläne (Admin-UI Update & Backup) | `BackupRunConfigurationRest` |
| Backup-Engine = Spring-Bean: `BackupManager.executeBackup(BackupScheduleBean, BackupProgressObserver)` → auch aus Modulcode aufrufbar (Bytecode-Beweis, live unverifiziert) | `de.vertico.starface.db.backup.BackupManager` |
| ⚠️ Verwechslungsfalle: Power-Pack-RPC `EXPORT_INSTANCE_BACKUP` = **nur Modul-Instanz-Konfig**, nicht System-Backup (.sar) | Firmenmodul-RE |

**Architektur-Konsequenz:** Zuverlässiger Weg aus der WebApp = **REST-Job → Download → eigener Transport** (SFTP/FTP durch die WebApp selbst).

## 3. Anforderung A — „Backup jetzt" + Download/SFTP (WebApp)

1. Button **„Backup jetzt"** je Anlage (Anlagen-Detailseite + Anlagen-Updates-Seite, SVG-Icon, bestehendes Design).
2. `_get_token(inst)` (bestehende OAuth-Funktion) → `PUT {anlage}/api/server/backups/actions/run` mit `{storeCdrData: true, storeVoiceboxAnnounces: true, storeChatHistory: true}`.
3. `202` → `backupJobId`; Status-Polling `GET /server/backups/state/{id}` (Interval ~3 s, Timeout konfigurierbar, Default 15 min).
4. `SUCCESS` → `GET /server/backups/files/{id}?keepBackupAfterDownload=true` → `.sar` in konfiguriertes Ablage-Verzeichnis (Docker-Volume `backups/`).
5. Optional: **SFTP/FTP-Upload** durch die WebApp (paramiko/ftplib) an konfigurierte Ziele (Zugangsdaten via Env/Secret — nie in DB-Klartext).
6. Protokoll in neuer Tabelle `anlagen_backup_log` + Anzeige auf Anlagen-Detailseite (bestehendes Tabellen-Design).
7. Fehlerfälle: Job `FAILED` → Fehlermeldung mit `error`-Text + Retry; Download-Fehler sichtbar; Timeout → Meldung „Status unbekannt, bitte später prüfen".

## 4. Anforderung B — Backup-Pflicht vor Update

In `app/anlagen_update_scheduler.py` → `_run_due_plans` pro fälligem Plan **VOR** `execute_anlagen_update(...)`:

1. Backup-Job anstoßen (gleiche REST-Funktion wie A).
2. Auf `SUCCESS` pollen (Timeout konfigurierbar, Default 5 min).
3. Flag `backup_required` je Plan (Default **true**) — Entscheidung Axel: Hard-Pflicht global oder pro Anlage abschaltbar (offene Frage 1).
4. **`SUCCESS` → Update starten** (bestehender Ablauf inkl. F105-IST-Version). **`FAILED`/Timeout → KEIN Update**, Plan → `error` (Result: „Update abgebrochen: Backup fehlgeschlagen (<detail>)"), Eintrag in `anlagen_update_log`, kein Endlos-Retry (F108-Muster).
5. Update-Log-Eintrag verknüpft das Backup (jobId/Datei) → „Rollback möglich: Backup <datei> vom <zeit>".

```
Plan fällig (status=planned)
  ├─ backup_required? ── nein → UpdateFromUrl (bestehendes Verhalten)
  └─ ja
       ├─ REST run → jobId → poll state
       │    ├─ SUCCESS → UpdateFromUrl → Log mit Backup-Referenz
       │    └─ FAILED/Timeout → Plan → error, KEIN Update, Log-Grund
```

## 5. UI-Regeln (Konsistenz)

- Vorhandene Tabellen/Buttons/Badges/Zurück-Links prüfen und übernehmen.
- Runde Buttons: SVG-Icons (Composer-Set), **keine Emoji**; Status-Buttons nie disabled.
- Mobil: Drawer statt Sidebar, bestehende Kiosk-/Responsive-Regeln.

## 6. Tests (TDD)

- **Fake-REST-Server** `fake_rest_backup.py` (run/state/files mit konfigurierbarem Verlauf: sofort ok, langsam, FAILED, 401).
- **Scheduler:** backup ok → Update läuft; FAILED → kein Update + Plan `error` + Log-Grund; Timeout → kein Update; `backup_required=false` → unverändert; 401/Transportfehler → sauberer Fehlerpfad.
- **HTTP-Tests:** „Backup jetzt"-Route (Anstoß, Status, Download in Ablage, Log).
- **E2E/CDP:** Button sichtbar/klickbar, Status-Anzeige, Fehler sichtbar.
- Regression: komplette Suite + E2E-Wächter grün vor Push.

## 7. Abgrenzung

- Kein Restore-UI (nur Hinweis: REST-`restore`-Endpoint existiert und wird bei Bedarf genutzt).
- Kein STARFACE-Server-Update.
- Kein Anlagen-seitiges SFTP-Ziel-Management über die WebApp (Location-Konfiguration bleibt Admin-UI der Anlage).

## 8. Offene Fragen (Antworten von Axel zur Freigabe)

1. Backup-Pflicht: Hard-Pflicht global oder pro Anlage/Plan abschaltbar (empfohlen)?
2. Ablage: Nur lokaler Download in der WebApp, oder automatisch per SFTP/FTP weiterleiten (SFTP präferiert)?
3. SFTP-Ziel-Daten in der WebApp pflegen (Secrets via Env) — oder reicht der Anlagen-Zeitplan-Ansatz?
4. Aufbewahrung: „Letzte 3 je Anlage behalten", Datei nach Download löschen/behalten?
5. „Backup jetzt"-Button nur Detailseite + Updates-Seite, oder auch Gesamtmonitoring?
6. Timeout-Defaults 15 min / 5 min ok?

---

Verwandt: [[anlagen-update-deployment]] · [[modul-auto-update]] · [[starface-webapp]]
