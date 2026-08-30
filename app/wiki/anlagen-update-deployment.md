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
2. **WebApp → Administration → Anlagen-Updates ▸ → „Updates einrichten“** (Seite heißt so seit F97).
3. **Tabelle aller Anlagen** (F95): Spalten Checkbox / Anlage / IST-Version (frisch via `GetStats`) / Aktion; Filterfelder über der Tabelle (Name + IST-Version, Wildcards `*` = beliebig, `?` = genau 1 Zeichen); Buttons **„Alle auswählen“/„Auswahl aufheben“** (F97: wählen nur die gefilterten/sichtbaren Anlagen).
4. Zeilen-Button **„Updates abrufen“** = Einzelabruf; mehrere Anlagen per Checkbox anwählen → Button **„Updates für ausgewählte Anlagen abrufen“** → Tabelle zeigt NUR die **Schnittmenge** (Updates, die für ALLE gewählten Anlagen verfügbar sind). **Strenge Regel:** schlägt eine Anlage fehl, wird keine Schnittmenge berechnet, sondern eine Fehlerliste gezeigt.
5. **F97: Das Abruf-Ergebnis erscheint im Dialog** (`?dlg=1`): `<dialog id="au-dlg">` mit „Installieren“ (sofort) und „Planen“ (datetime-local, Europe/Berlin) im Dialog selbst — große Listen scrollen innerhalb des Dialogs (`dialog.dlg.wide`), nach der Aktion schließt er; ohne `dlg`-Parameter wird der Bereich weiterhin unter der Tabelle gerendert (Fallback).
6. **Jeder Anstoß** (Installieren ODER ausgeführter Plan) legt einen Eintrag in `anlagen_update_log` an — sichtbar unter **„Laufende Updates“** (Prüfung läuft) bzw. **„Durchgeführte Updates“** (mit Urteil).
7. **Geplante Updates** (eigene Seite): Folge der Pläne nach Zeitpunkt (nächstes fälliges oben), Filter, **Abbrechen** solange `planned` (`planned → cancelled`), erledigte Einträge **löschbar** (never planned → nur abbrechen).
8. **Erfolgsprüfung (F96):** RPC-„ok“ heißt nur „angestoßen“. Ein Update gilt erst als **erfolgreich**, wenn die IST-Version der Anlage per `GetStats` == Zielversion ist (früher Abbruch sofort beim Check); Prüfbeginn +5 Min nach Anstoß, dann alle 60 s, 60-Min-Timebox → `erfolgreich` / `fehlgeschlagen` (Anlage war erreichbar, Ziel nie erreicht — Detail nennt die letzte gesehene Version) / `unbekannt` (Anlage im gesamten Zeitraum nicht erreichbar — bewusst kein Fehlurteil, die PBX startet beim Update neu).

## Umgesetzte Bausteine (v10, 30.08.)

| Baustein | Details |
|---|---|
| RPC `GetAnlagenUpdates` (read-only) | `LicenseComponent.fetchUpdates(Final, GERMAN)` → JSON `{current, updates:[{version,date,type,url}]}`; kein Eingriff, nur Lesen |
| RPC `ExecuteAnlagenUpdate` | Validierung (Token; Zielversion **+ URL** gegen frische `fetchUpdates`-Liste) → Bean-Kette in **eigenem Thread mit 2 s Delay**, Antwort sofort VOR `logoutAll` |
| Bean-Kette (privat, nicht `prepareAndStartAutomaticUpdate`!) | `setLocale → setUpdateUri → setOldVersion → setUpdateInfo → setTargetVersion → logoutAll(SERVER_UPDATE) → shutdownServices → startUpdate` |
| RPC-Antwort | `GetAnlagenUpdates` liefert einen **JSON-String** (XML-RPC-String-Typ, z. B. `{"current":"10.0.1.7","count":1,"updates":[{...}]}`) mit description/changelog je Update — die WebApp parst die von xml.etree **aufgelöste** Antwort (`values[0]`); Regex über das rohe XML nur als Fallback (F93/F94: 500-Byte-Kappung → dann XML-Entities unaufgelöst → `json.loads` scheiterte → „Unerwartete Antwort“; Fehlermeldung zeigt bei Parsefehlern jetzt die Position: `→ Zeichen N: …`) |
| Scheduler | Daemon-Thread (30-s-Tick) in der WebApp; führt fällige Pläne aus; **`missed`** statt stillem Nachholen, wenn > 5 min überfällig (WebApp war down) |
| Zeitzone (Vorgabe Axel) | Planung in **Europe/Berlin** eingegeben, **immer UTC (ISO+00:00) gespeichert**, Scheduler vergleicht UTC, Anzeige zurück in Berlin — Sommer-/Winterzeit im Test abgesichert |
| DB | `anlagen_update_plans` (id, installation_id, version, update_url, scheduled_at, status, result, created_at **+ `ausgefuehrt_um`** F96-Migration) + **`anlagen_update_log`** (F96: quelle `direkt|plan`, plan_id, version_vor, version_nach, angestossen_um, status `pruefen/erfolgreich/fehlgeschlagen/unbekannt`, bestaetigt_um, version_zuletzt, zuletzt_um, detail) |
| Erfolgsprüfung (F96) | `_verify_open_logs` im Scheduler-Tick: alle Logs mit `pruefen`; Bremse +5 Min (Env `ANLAGEN_UPDATE_CHECK_START_DELAY`), Takt 60 s (`ANLAGEN_UPDATE_CHECK_INTERVAL`), Abbruch bei Ist==Ziel (`GetStats`), Timebox 60 Min (`ANLAGEN_UPDATE_CHECK_TIMEOUT`) → `erfolgreich`/`fehlgeschlagen`/`unbekannt`; robuster Takt über `zuletzt_um`, alle Ableitungen aus `angestossen_um` (übersteht Container-Neustarts) |

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
