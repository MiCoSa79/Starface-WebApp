---
title: Anlagen-Updates über das Deployment-Modul — Machbarkeitsbefund & TODO
description: TODO (nicht freigegeben): STARFACE-Server-/System-Updates über unser Deployment-Modul triggern. Machbarkeitsprüfung abgeschlossen (27.08., 3 parallele Befunde) — Weg belegt (LicenseComponent.fetchUpdates → ServerUpdateHandler → startUpdate), Umsetzung offen. Risiken: Anlagen-Reboot, Dienste-Stopp, Session-Kickout.
updated: 2026-08-27
---

# Anlagen-Updates über das Deployment-Modul — TODO

**Status:** 🛠 **TODO — geprüft, machbar, NICHT umgesetzt** (Machbarkeitsbefund 27.08., Umsetzung erst nach Freigabe Axel — großer Eingriff: Anlagen-Update = Reboot + TK-Ausfall).

**Kernfrage (Axel):** Kann das Deployment-Modul neben Modul-Updates auch **Anlagen-Updates** (STARFACE-Server-/System-Update) triggern?

**Kurzantwort:** Heute **nein** (Modul v8 = reines Modul-Update), aber **technisch machbar und produktiv belegt**: Das Fremdmodul Admin Power Pack (Fluxpunkt) triggert Server-Updates exakt über die unten stehende Bean-Kette (`EXECUTE_STARFACE_UPDATE`). Offiziell gibt es **keinen** externen Trigger-Weg (nur GUI: Admin → Server → Status → „Jetzt suchen“, Auto-Backup, 2 Installationswege, Neustart).

## Befundlage (27.08., 3 parallele Recherchen — alle Belege in der Hermes-Entity [[deployment-modul-anlagen-update]]-Abschnitt Artefakte)

1. **Lokal (SDK 10.0.2.5 per javap):** Die komplette Update-Pipeline ist im SDK vorhanden und aus Modulcode ansteuerbar (Spring-Beans per `springApplicationContext().getBean(...)` — Muster vom Plattform-Baustein `CheckUpdateOption` bytecode-verifiziert). Es gibt **keinen** fertigen Designer-Baustein dafür; `CheckUpdateOption` (experimentell) prüft nur die Lizenz-Abdeckung einer Version, kein Trigger.
2. **Web (21 Quellen):** REST-API ohne Update-Endpunkte (STARFACEGmbH/rest-examples, 47 Pfade); `update.starface.de`-Protokoll nichtöffentlich; offizielles Modul „Update Helper“ (früher UpdateTool) nur für Major-Upgrades (6.4→7, USB-Stick, 4-GB-Download, Neustart-Bestätigung per Telefon/UI). Foren-Recherche teils blockiert → Lücke markiert.
3. **48 echte `.sfm` gescannt:** Außer Admin Power Pack kann **kein weiteres** Modul Anlagen-Updates triggern. XML-Monitoring (o-byte) ruft `fetchUpdates()` nur **lesend** auf („neues Major Release“-Hinweis). Auch die 10 STARFACE-Standardmodule aus dem VM-Extrakt: ohne Trigger.

## Technischer Weg (belegt, javap-Signaturen)

```
1. Check:   LicenseComponent.fetchUpdates(Version$VersionType, Locale) → List<UpdateInfo>
            (VersionType: Final|Beta|Internal|Preview; UpdateInfo.url = DNF-Repo-URL, .version = Zielversion)
2. Execute: ServerUpdateHandler (Spring-Bean @Component):
            setUpdateUri(url) → setOldVersion(Version.buildVersion()) → setUpdateInfo(info)
            → setTargetVersion(info.version.toString())
   →       SessionManager.logoutAll(LogoutServlet$LogoutType.SERVER_UPDATE)   // ALLE Sessions raus!
   →       shutdownServices()   (Asterisk/XMPP/Federation/SystemCheck stoppen)
   →       startUpdate()        (→ UpdateController.startPart1 → DnfHelper: downloadUpdates/installUpdates,
                                 switchToUpdateserver, dnfUpdate, RPM_RESTART_SERVER_FILE → Reboot)
3. Beta:    PbxConfigurationService.update().betaEnabled().setValue(true) VOR fetchUpdates(VersionType.Beta, …)
4. Timer:   eigener ScheduledExecutorService im Modul (Fluxpunkt-Key „starface-update-timer“ ist plattformfremd)
```

Muster 1:1 aus dem internen `ServerUpdateHandler.prepareAndStartAutomaticUpdate` (Bytecode). Classpath: `PbxConfigurationService`/`Version` kommen aus `lib/starface-ng-10.0.2.5.jar`.

## Umsetzungs-TODO (nach Freigabe)

- [ ] **Freigabe Axel** (Plan-Dokument + Risiko-Gespräch, Eingriff in laufenden Betrieb!)
- [ ] Deployment-Modul **v9**: neue `IBaseExecutable`-Klasse analog `UpdateFromUrl.java` (~50–120 Zeilen)
  - [ ] RPC `GetAnlagenUpdates` (read-only: Version/Datum/URL, Typ Final/Beta — Anzeige in WebApp)
  - [ ] RPC `ExecuteAnlagenUpdate` (Bean-Kette oben; **Antwort VOR `logoutAll` raus** bzw. separater Thread — eigene Session stirbt sonst)
- [ ] Descriptor: 2 `rpcEntryPoint`s (`XMLRPC_auth`) + Private-Wrapper-Funktionen (Firmenmuster)
- [ ] Build: Passwortschutz-Pflicht (F41, `writeHash = sha1(id + PW)`), Vendor „Axel Meiser - Kraemer IT“, manueller Tag `dm-v9` (vorher `git tag --list` prüfen!)
- [ ] WebApp: **separate** Ansicht/Buttons (bewusst ausgelöst) — NICHT in den bestehenden Modul-Update-Flow (`UpdateFromUrl`) integrieren
- [ ] Test-Konzept (Fake-XML-RPC / Testanlage), Abnahme wie gehabt (Wiki-Pflicht, CI-Tag)
- [ ] Doku: Modul-PDF + WebApp-Wiki + Hermes-Wiki (log.md, Entity, index.md)

## Risiken (Update = Eingriff in Produktion!)

- **Gesamt-Reboot + Dienste-Stopp:** Asterisk/XMPP/Federation/SystemCheck gestoppt, Voicemail/Fax/var-data temporär verschoben, `sqldump` + DB-Upgrade, Updateserver-Installation → **alle Gespräche/Telefonie tot** während des Updates.
- **Session-Kickout:** `logoutAll(SERVER_UPDATE)` wirft Admins, Web-UI, Softphones und API-Clients raus — auch den aufrufenden RPC.
- **Reihenfolge-Pflicht:** `updateUri/targetVersion/oldVersion/locale` müssen vor `startPart1` gesetzt sein; nur **ein** DNF-Download gleichzeitig (`downloadingInProgress`); `updateUri` muss erreichbares DNF-Repo passender Arch sein.
- **Beta-Flag** muss vor `fetchUpdates(Beta, …)` gesetzt sein.
- **Getrennt halten:** Modul- vs. Anlagen-Update (`UpdateInfoWrapper.isSystemSoftwareUpdate()/isModuleSoftwareUpdate()`).

## Abgrenzung & Quellen

- Hermes-Wiki (ausführliche Fassung + Artefakt-Pfade): `profiles/axel/wiki/entities/deployment-modul-anlagen-update.md`; Detail-RE Admin Power Pack (Abschnitt 6 „STARFACE-Server-Update“): `profiles/axel/wiki/entities/admin-power-pack-re.md`
- Modul-Update-Flow (bestehend, ANLAGEN-getrennt): [[modul-auto-update]]
