# FR-001: Backup vor Anlagen-Update + Backup-Download/SFTP

- **Status:** Konzept — wartet auf Freigabe durch Axel (kein Code)
- **Erstellt:** 2026-09-01
- **Basis-Analyse:** STARFACE 10.0.2.5 SDK (Bytecode + `starface-api.yaml`, verifiziert 2026-09-01)
- **Ziel:** nächste Feature-Version nach Freigabe (dieser FR selbst = reiner Doku-Commit, `[skip ci]`, kein Tag)

---

## 1. Problem / Nutzen

1. Die WebApp stößt heute Anlagen-Modul-Updates an (`anlagen_update_plans` → `_run_due_plans` → `UpdateFromUrl` an das Deployer-Modul), **ohne vorher ein Backup der Anlage zu erstellen**. Ein Fehl-Update kann die Anlage in einen defekten Zustand bringen — ein Rollback geht dann nur über ein manuell gemachtes Backup.
2. Axel möchte außerdem **jederzeit per Klick** ein Backup einer Anlage anstoßen und **herunterladen** bzw. **in eine SFTP/FTP-Ablage legen** können.

## 2. Faktenlage (analysiert, belegt)

| Fakt | Nachweis |
|---|---|
| Offizielle REST-API „Server/Backups": `PUT /server/backups/actions/run` (startet Job, antwortet 202 + `backupJobId`), `GET /server/backups/state/{id}` (progress 0.0–1.0, status, error), `GET /server/backups/files/{id}` (Download; Datei wird danach gelöscht, außer `keepBackupAfterDownload=true`), `PUT /server/backups/actions/restore` (.sar als Multipart oder `serverBackupLocation`) | `starface-api.yaml` Z. 3088–3250; Schemas `BackupRunConfigurationRest` (nur `storeCdrData`/`storeVoiceboxAnnounces`/`storeChatHistory`), `BackupJobReferenceRest`, `BackupJobResultRest` |
| Auth: OAuth2-Password-Grant (`rest-client-headless`, Keycloak `/auth/realms/pbx/oauth2/token`), Admin-Recht für „Server/Backups" | bekanntes Muster der App (`references/oauth-anlage-verbindung.md`) |
| Die Anlage kennt **kein klassisches FTP (Port 21)** als Backup-Ziel; eingebaute Ziele (`BackupLocationBean$Type`, javap): `HDD, USB, SD, MAIL, SMB, SFTP, DROPBOX` | `de.vertico.starface.db.backup.BackupLocationBean` |
| Backup-Engine ist eine Spring-Bean: `BackupManager.executeBackup(BackupScheduleBean, BackupProgressObserver)` (javap: `@Lazy`, `@PreDestroy`, `startInit`) — aus Modulcode via `springApplicationContext().getBean(BackupManager.class)` aufrufbar (Bytecode-Beweis, **live noch unverifiziert**) | `de.vertico.starface.db.backup.BackupManager` |
| Der REST-Job (`actions/run`) schreibt **immer lokal auf die Anlage (HDD)** — die Run-Konfiguration hat **kein Ziel-Parameter**; der Download läuft über den Datei-Endpoint | `BackupRunConfigurationRest` |
| SFTP als **Ziel der Anlage selbst** funktioniert NUR über konfigurierte Backup-Zeitpläne (Admin-UI → Update & Backup → Speicherorte), nicht über den ad-hoc REST-Job | `BackupScheduleBean`/`BackupDataHandler` |
| ⚠️ Verwechslungsfalle: Admin-Power-Pack-RPC `EXPORT_INSTANCE_BACKUP` exportiert **nur Modul-Instanz-Konfiguration**, nicht das System-Backup (.sar) | Firmenmodul-RE |

**Konsequenz für die Architektur:** Der zuverlässige Weg aus der WebApp heraus ist **REST-Job → Download → eigener Transport** (SFTP/FTP durch die WebApp selbst). Der Weg „Anlage schreibt direkt nach SFTP" (Option B) braucht eine konfigurierte Location + ggf. ein eigenes Deployer-Modul bzw. Zeitplan-Auslösung — als Alternative dokumentiert, nicht primärer Ansatz.

## 3. Anforderung A — „Backup jetzt" + Download/SFTP (WebApp)

### Ablauf (pro Anlage, Button „Backup jetzt" auf Anlagen-Detailseite + Anlagen-Updates-Seite)

1. Anlage auswählen → Button „Backup jetzt" (SVG-Icon, bestehendes Button-Design).
2. WebApp: `_get_token(inst)` (bestehende OAuth-Funktion) → `PUT {anlage}/api/server/backups/actions/run` mit `{storeCdrData: true, storeVoiceboxAnnounces: true, storeChatHistory: true}`.
3. `202` → `backupJobId` speichern; Status-Polling `GET /server/backups/state/{id}` (Interval ~3 s, Timeout konfigurierbar, Default z. B. 15 min).
4. `progress == 1.0` / Status `SUCCESS` → `GET /server/backups/files/{id}?keepBackupAfterDownload=true` → Datei (`.sar`) wird in das konfigurierte Ablage-Verzeichnis geschrieben (Docker-Volume der WebApp, z. B. `backups/`).
5. Optional (Konfiguration): **SFTP/FTP-Upload** der Datei durch die WebApp (paramiko bzw. ftplib) an konfigurierte Ziele (Host, Port, Benutzer, Passwort via Env/Secret — **nie in die DB in Klartext**).
6. Protokollierung in neuer Tabelle `anlagen_backup_log` (Anlage, start, ende, status, jobId, datei, groesse, ziel, fehler) + Anzeige auf der Anlagen-Detailseite (bestehendes Tabellen-Design).
7. Fehlerfälle: Job `FAILED` → Fehlermeldung mit `error`-Text; Download-Fehler → Status sichtbar, Retry möglich; Timeout → Job bleibt am Leben (Anlage kann weiterlaufen), WebApp meldet „Status unbekannt, bitte später prüfen".

### REST-Request-Beispiel (Doku)

```
PUT https://<anlage>/api/server/backups/actions/run
Authorization: Bearer <oauth2-token>
{"storeCdrData": true, "storeVoiceboxAnnounces": true, "storeChatHistory": true}
→ 202 {"backupJobId": "…"}

GET https://<anlage>/api/server/backups/state/{backupJobId} → {"progress": 0.0…1.0, "status": "…", "error": "…"}
GET https://<anlage>/api/server/backups/files/{backupJobId}?keepBackupAfterDownload=true → <binary .sar>
```

## 4. Anforderung B — Erfolgreiches Backup als Voraussetzung für Update

### Eingriffspunkt

`app/anlagen_update_scheduler.py` → `_run_due_plans` → pro fälligem Plan **VOR** `execute_anlagen_update(...)`:

1. Backup-Job anstoßen (gleiche REST-Funktion wie Anforderung A).
2. Auf `SUCCESS` pollen (Timeout konfigurierbar; Default z. B. 300 s — der fällige Update-Plan darf nicht unendlich blockieren; mind. ein Hintergrund-Handler, wenn der Scheduler-Daemon nicht blockieren soll — Design-Entscheidung bei Umsetzung, Timeout-bewertet).
3. Variante A (empfohlen): Backup-Pflicht **je Plan** als Flag `backup_required` (Default **true**) — Admin kann im Update-Setup pro Anlage/Plan abwählen (z. B. Testanlagen).
   Variante B: globale Pflicht für alle Pläne (streng, kein Opt-out). — **Entscheidung Axel nötig (offene Frage 1).**
4. Ergebnis:
   - Backup `SUCCESS` → Update starten (bestehender Ablauf, inkl. F105-IST-Version-Timing).
   - Backup `FAILED`/Timeout → Plan wird **nicht** ausgeführt, Status `error` (Result-Text: „Update abgebrochen: Backup fehlgeschlagen (<detail>)"), Eintrag in `anlagen_update_log` mit Grund; der Plan bleibt NICHT `planned` (kein Endlos-Retry — wie F108: Plan-Zeile wird nach Ausführungsversuch entfernt) → Admin sieht im Log, warum.
5. Der Update-Log-Eintrag bekommt eine Verknüpfung zum erzeugten Backup (jobId/Datei) → „Rollback möglich: Backup <datei> vom <zeit>" auch ohne Restore-UI in dieser FR (Hinweis auf REST `restore`-Endpoint genügt).

### Ablaufdiagramm (Text)

```
Plan fällig (status=planned)
  ├─ backup_required? ── nein → UpdateFromUrl (bestehendes Verhalten)
  └─ ja
       ├─ REST run → jobId → poll state
       │    ├─ SUCCESS → UpdateFromUrl → Log mit Backup-Referenz
       │    └─ FAILED/Timeout → Plan → error, KEIN Update, Log-Grund
```

## 5. UI (Design-Konsistenz — Regeln beachten)

- Neue Bauteile zuerst prüfen: gibt es schon passende Tabellen/Buttons/Badges/Zurück-Links → übernehmen.
- Runde Buttons: SVG-Icons (Composer-Set), keine Emoji.
- Status-Buttons: nie disabled, nur Optik.
- „Backup jetzt"-Button an bestehenden Orten: Anlagen-Detailseite (Stammdaten-Bereich), Anlagen-Updates-Seite (pro Anlagen-Zeile?), ggf. Gesamtmonitoring.
- Kiosk/Mobil: bestehende Regeln (Drawer statt Sidebar).

## 6. Tests (TDD-Pflicht)

- **Fake-REST-Server:** `tmp_tests/fake_rest_backup.py` — beantwortet `run`/`state`/`files` mit konfigurierbarem Verlauf (sofort ok, langsam, FAILED, 401).
- **Scheduler-Tests (Backup-Pflicht):** backup ok → Update wird ausgeführt; backup FAILED → kein Update + Plan `error` + Log-Eintrag mit Grund; Timeout → kein Update; `backup_required=false` → Verhalten unverändert; 401/Transportfehler → sauberer Fehlerpfad.
- **HTTP-Tests:** „Backup jetzt"-Route (Anstoß, Job-Status, Download-Schreiben in Ablage, Log-Eintrag).
- **E2E/CDP:** Button sichtbar/klickbar, Status wird angezeigt, Fehler sichtbar.
- Regression: komplette Suite + E2E-Wächter grün (Pflicht vor Push).

## 7. Abgrenzung (bewusst NICHT in dieser FR)

- Kein Restore-UI (nur Nachweis „Restore-API existiert").
- Kein STARFACE-Server-Update (Systemupdate der Anlage ist getrenntes Thema).
- Kein Anlagen-seitiges SFTP-Ziel-Management über die WebApp (Location-Konfiguration bleibt Admin-UI der Anlage; WebApp-SFTP-Upload nur, falls Anforderung A Schritt 5 gewünscht).

## 8. Offene Fragen (Antworten von Axel zur Freigabe)

1. **Backup-Pflicht:** Hard-Pflicht global (Variante B) oder pro Anlage/Plan abschaltbar (Variante A, empfohlen)?
2. **Ablage nach Download:** Nur lokale Ablage im WebApp-Volume reicht, oder sollen Backups **automatisch** per SFTP/FTP weitergeschickt werden? (Wenn ja: Ziel je Anlage konfigurierbar? SFTP präferiert, klassisches FTP nur mit Hinweis „unsicher".)
3. **SFTP-Ziel-Daten:** Werden sie in der WebApp gepflegt (dann Env-Secret je Ziel) — oder reicht der Hinweis, die Anlage selbst könne per Admin-UI SFTP-Zeitpläne fahren (dann fragt die WebApp dort nichts ab)?
4. **Aufbewahrung:** Anzahl/Behaltedauer (z. B. „letzte 3 pro Anlage behalten, ältere löschen")? Datei nach Download löschen (`keepBackupAfterDownload=false`) oder behalten?
5. **„Backup jetzt" auch ohne Update-Kontext** überall sichtbar (auch Gesamtmonitoring), oder nur Detailseite + Updates-Seite?
6. **Timeout-Defaults:** Status-Poll 15 min, Update-Vorlauf 5 min — okay? (Konfigurierbar via Env.)
