---
title: Anlagen-Updates über das Deployment-Modul — umgesetzt (dm-v10)
description: STARFACE-Server-/System-Updates über unser Deployment-Modul triggern — UMGSETZT in dm-v10 + WebApp (Anlagen-Updates-Seite, Scheduler, Europe/Berlin-Zeitzone). Weg belegt: LicenseComponent.fetchUpdates → ServerUpdateHandler-Kette → startUpdate. Risiken: Anlagen-Reboot, Dienste-Stopp, Session-Kickout.
updated: 2026-08-30
---

# Anlagen-Updates über das Deployment-Modul — ✅ umgesetzt (dm-v10)

**Status:** ✅ **UMGSETZT** — Deployment-Modul **v10** (RPCs `GetAnlagenUpdates` + `ExecuteAnlagenUpdate`) + WebApp-Administration „Anlagen-Updates“ (abfragen, sofort installieren, planen) + Scheduler + Zeitzone Europe/Berlin. Freigabe Axel (30.08.) nach Machbarkeitsbefund (27.08.).

**Kernfrage (Axel):** Kann das Deployment-Modul neben Modul-Updates auch **Anlagen-Updates** (STARFACE-Server-/System-Update) triggern?

**Kurzantwort:** **Ja, seit v10.** Produktiv belegt war der Weg schon (Fremdmodul Admin Power Pack, Fluxpunkt); umgesetzt ist er jetzt mit **eigenem** RPC-Paar am Deployment-Modul, **bewusst getrennt** vom Modul-Update-Flow (`UpdateFromUrl`).

## Bedienung (WebApp)

1. **Modul:** `Deployment-Modul.sfm` (v10) in der Anlage aktualisieren/importieren (Instanz + Token bleiben erhalten).
2. **WebApp → Administration → Anlagen-Updates** (neuer Menüpunkt im Admin-Dropdown).
3. **Tabelle aller Anlagen** (F95): Spalten Checkbox / Anlage / IST-Version (frisch via `GetStats`) / Aktion; Filterfelder über der Tabelle (Name + IST-Version, Wildcards `*` = beliebig, `?` = genau 1 Zeichen).
4. Zeilen-Button **„Updates abrufen“** = Einzelabruf; mehrere Anlagen per Checkbox anwählen → Button **„Updates für ausgewählte Anlagen abrufen“** → Tabelle zeigt NUR die **Schnittmenge** (Updates, die für ALLE gewählten Anlagen verfügbar sind). **Strenge Regel:** schlägt eine Anlage fehl, wird keine Schnittmenge berechnet, sondern eine Fehlerliste gezeigt.
5. **Installieren** = sofort ausführen (mit Bestätigungs-Warnung) oder **Planen** (datetime-local, Europe/Berlin) — im Bulk wirkt beides auf alle gewählten Anlagen.
6. „Geplante Updates“ unten: Status `planned → executed / error / missed / cancelled`, Abbrechen solange `planned`.

## Umgesetzte Bausteine (v10, 30.08.)

| Baustein | Details |
|---|---|
| RPC `GetAnlagenUpdates` (read-only) | `LicenseComponent.fetchUpdates(Final, GERMAN)` → JSON `{current, updates:[{version,date,type,url}]}`; kein Eingriff, nur Lesen |
| RPC `ExecuteAnlagenUpdate` | Validierung (Token; Zielversion **+ URL** gegen frische `fetchUpdates`-Liste) → Bean-Kette in **eigenem Thread mit 2 s Delay**, Antwort sofort VOR `logoutAll` |
| Bean-Kette (privat, nicht `prepareAndStartAutomaticUpdate`!) | `setLocale → setUpdateUri → setOldVersion → setUpdateInfo → setTargetVersion → logoutAll(SERVER_UPDATE) → shutdownServices → startUpdate` |
| RPC-Antwort | `GetAnlagenUpdates` liefert einen **JSON-String** (XML-RPC-String-Typ, z. B. `{"current":"10.0.1.7","count":1,"updates":[{...}]}`) mit description/changelog je Update — die WebApp parst die von xml.etree **aufgelöste** Antwort (`values[0]`); Regex über das rohe XML nur als Fallback (F93/F94: 500-Byte-Kappung → dann XML-Entities unaufgelöst → `json.loads` scheiterte → „Unerwartete Antwort“; Fehlermeldung zeigt bei Parsefehlern jetzt die Position: `→ Zeichen N: …`) |
| Scheduler | Daemon-Thread (30-s-Tick) in der WebApp; führt fällige Pläne aus; **`missed`** statt stillem Nachholen, wenn > 5 min überfällig (WebApp war down) |
| Zeitzone (Vorgabe Axel) | Planung in **Europe/Berlin** eingegeben, **immer UTC (ISO+00:00) gespeichert**, Scheduler vergleicht UTC, Anzeige zurück in Berlin — Sommer-/Winterzeit im Test abgesichert |
| DB | `anlagen_update_plans` (id, installation_id, version, update_url, scheduled_at, status, result, created_at) |

## Technischer Weg (javap-verifiziert, SDK 10.0.2.5)

```
1. Check:   LicenseComponent.fetchUpdates(LicenseComponent.Version$VersionType.Final, Locale.GERMAN)
            → List<UpdateInfo>  (UpdateInfo.url = DNF-Repo-URL, .version = Zielversion, .date, .availCode)
2. Execute (in OWN THREAD, 2 s Delay — eigener RPC-Prozess stirbt sonst am Logout):
            ServerUpdateHandler (Spring-Bean):
            setLocale → setUpdateUri(ui.getUrl()) → setOldVersion(Version.buildVersion())
            → setUpdateInfo(ui) → setTargetVersion(ui.getVersion().toString())
   →       SessionManager.logoutAll(LogoutServlet$LogoutType.SERVER_UPDATE)   // ALLE Sessions raus
   →       shutdownServices()   (Asterisk/XMPP/Federation/SystemCheck stoppen)
   →       startUpdate()        (→ UpdateController.startPart1 → DnfHelper: downloadUpdates/installUpdates,
                                 switchToUpdateserver, dnfUpdate, RPM_RESTART_SERVER_FILE → Reboot)
3. WICHTIG: prepareAndStartAutomaticUpdate(...) ist PRIVATE im SDK → Einzel-Setter-Kette (oben) nachbauen.
   Version.buildVersion() ist String; Version$VersionType liegt in de.starface.license.manager.ws.beans.license.
   Classpath-Beleg: ServerUpdateHandler + UpdateInfo aus sdk-libs/*.jar, de.vertico.starface.Version aus WEB-INF/classes.
```

## Offene Punkte / Abnahme

- [ ] Erst-Betrieb: Deployment-Modul v10 auf **Testanlage** importieren, RPCs über die neue Seite gegenprüfen (echte Anlage, echte Update-Liste)
- [ ] Bewusst NICHT automatisch: kein Update ohne expliziten Klick/Plan („Mach nix kaputt, was vorher funktionierte“)
- [ ] Bei `missed`: Termin in der WebApp neu planen (kein stilles Nachholen — Architektur-Entscheidung Option A)

## Risiken (Update = Eingriff in Produktion! — UI-Warnhinweis auf der Seite)

- **Gesamt-Reboot + Dienste-Stopp:** Asterisk/XMPP/Federation/SystemCheck gestoppt, Voicemail/Fax/var-data temporär verschoben, `sqldump` + DB-Upgrade → **alle Gespräche/Telefonie tot** während des Updates.
- **Session-Kickout:** `logoutAll(SERVER_UPDATE)` wirft Admins, Web-UI, Softphones und API-Clients raus — auch den aufrufenden RPC (deshalb Antwort-Vorab + 2-s-Delay-Thread).
- **Reihenfolge-Pflicht:** Setter vor `startPart1`; nur **ein** DNF-Download gleichzeitig (`downloadingInProgress`); `updateUri` muss erreichbares DNF-Repo passender Arch sein.
- **Getrennt halten:** Modul- vs. Anlagen-Update (`UpdateInfoWrapper.isSystemSoftwareUpdate()/isModuleSoftwareUpdate()`); `GetAnlagenUpdates` liefert bewusst nur den Final-Kanal (keine Beta-Spielereien in Produktion).

## Abgrenzung & Quellen

- Modul-Update-Flow (bestehend, ANLAGEN-getrennt): [[modul-auto-update]]
- Hermes-Wiki (ausführliche Fassung + Artefakt-Pfade): `profiles/axel/wiki/entities/deployment-modul-anlagen-update.md`
- Details Admin Power Pack (Fremdmuster): `profiles/axel/wiki/entities/admin-power-pack-re.md`
