---
title: Module - Reverse Engineering (XML Monitoring v152)
description: Reverse-Engineering des STARFACE-Firmenmoduls XmlMonitoring_v152.sfm — komplett rekonstruierte Funktionsweise (Checkmk-/XML-Monitoring-Output, DI-Lebenszyklus, dynamische XML-RPC), 15 Klassen im Detail, Lessons für eigene Module.
updated: 2026-08-25
---

# Module - Reverse Engineering: XML Monitoring v152

**Zweck:** Firmenmodul `XmlMonitoring_v152.sfm` (o-byte / Hermstedt) komplett per Bytecode-Analyse (javap + CFR) rekonstruiert — um zu verstehen, wie ein echtes STARFACE-Monitoring-Modul funktioniert, und um Muster für eigene Module zu übernehmen. Rohdaten (javap/CFR aller Klassen): `/opt/data/profiles/axel/wiki/assets/xmlmonitoring/`.

**Archiv:** 15 `.class`-Dateien (Designer-Funktions-Adapter) + `module-descriptor.xml` + 2 eingebettete JARs: `starface_xml-2.1.1-jar-with-dependencies.jar` (**die eigentliche Logik**: `CheckMkComponent`, `XmlComponent`, `StarfaceAccessor`, `StarfaceDbAccessor`, `ConfigurationService`, `LogServiceBean`, `MailConnectionComponent`) und `license-module-5.0.1-jar-with-dependencies.jar` (o-byte-Lizenz-API).

## Was das Modul macht

> STARFACE-Monitoringdaten **maschinenlesbar** bereitstellen: als **Checkmk-Agent-Text** (Sektionen `<<<name>>>`), als **XML-Dokument** und über **dynamisch registrierte XML-RPC-Methoden**. Überwacht: Backups, Fax-Queue, Telefon-/SIP-Peers, Log-Dateien, E-Mail-Server + Testversand, Hardware-ID-Änderungen, Modul-Instanzen, STARFACE-Version/Updates, Lizenzstand.

## Lebenszyklus (Init/Clear über DependencyInjector)

Jede Modul-Instanz hat einen eigenen `DependencyInjector` (Key: Instanz-UUID). Die Dienste (Spring-Bohnen + eigene Klassen) lädt `InitDI`:
`Logger, ModuleRegistry, LicenseComponent, PersonAndAccountHandler, OAuthSessionService, MailComponent` + `di.init(new ClassFinder("/var/starface/module/modules/repo/<ModuleID>"))`.

`InstanceInitialized` → Output `isInitialized = DependencyInjector.isUp(id)` · `ClearDI` → `CheckMkComponent.deleteDirAndFile()` (löscht `/usr/lib/check_mk_agent/local/localchecks`) + `di.close()` · `ClearCache` → leert alle Modul-Cache-Keys (0–5, 10–15).

## Die 15 Klassen (Kurzübersicht)

| Klasse | Aufgabe |
|---|---|
| `InitDI` | DependencyInjector pro Instanz hochfahren (Spring-Bohnen + ClassFinder) |
| `ClearDI` | Abbau: Checkmk-Skripte löschen + DI schließen |
| `InstanceInitialized` | Output `isInitialized` (DI-Status) |
| `ClearCache` | Modul-Cache komplett leeren |
| `ChangeConfiguration` | Log-Suchkonfiguration (`supportLogErrorString/Age`, `pbxLogErrorString/Age`) → `ConfigurationService.setConfig` |
| `SetEmailConfiguration` | `recipientAddress`, `mailResultTimeout`, `numberOfTransmissions` → `ConfigurationService.setEmailConfiguration` |
| `GetMonitoringOutput` | **Checkmk-Text-Generator** (Sektions-Pipeline, Cache 0–5) |
| `GetMonitoringOutputCheckMk` | Delegiert an `CheckMkComponent` (lokale Agent-Checks, Cache 10–15) |
| `GetMonitoringOutputXML` | Delegiert an `XmlComponent` (XML-Dokument, Cache 20–25) |
| `IsActiveDirectoryEnabled` | Output `activeDirectoryEnabled` (`ActiveDirectoryComponent.isActivated()`) |
| `RegisterXmlRpcEndpoint` (+ `$XmlRpcInvocation`) | **Dynamische XML-RPC-Registrierung** beliebiger Designer-Funktionen |
| `UnregisterXmlRpcEndpoint` | RPC-Methode wieder entfernen |
| `RegisterXmlRpcEndpoint$1` | Synthetische SwitchMap (Compiler-Artefakt) |
| `CheckLicense` | Online-Lizenzprüfung gegen `https://olm.o-byte.com` |

## Caching (alle drei Output-Varianten)

Modul-Scope-Cache, Timestamp + `cacheTimeout`: kein Timestamp → **fetchen** · älter als Timeout → **updaten** · sonst **Cache**. Keys: Text 0–5, Checkmk 10–15, XML 20–25 (Timestamp / Output / initiale Hardware-ID / Mail-Ts / Mail-Ergebnis / Mail-Zähler-Tag).

## Checkmk-Text-Sektionen (GetMonitoringOutput)

| Sektion | Inhalt |
|---|---|
| `starface_peers` / `starface_sip_provider` | Roh-Output der STARFACE-`MonitoringComponent` (startet sie bei Bedarf via `startInit()`) |
| `starface_backup` | SQL: `backup_locations` × `backup_log JOIN backup_schedules`, neuester Eintrag je Standort |
| `starface_faxqueue` | Shell `faxstat` (via System-Baustein `Execute4`): `faxqueue <count> <faxWarning> <faxCritical>` |
| `starface_hardware_id` | aktuelle vs. initiale Lizenz-Hardware-ID (Änderungserkennung) |
| `starface_all_peers_offline` | `ERROR`/`OK`: zählt registrierte Peers aus dem Roh-Output |
| `starface_support_log` / `starface_pbx_log` | Fehlerstring-Suche in `/var/log/starface/support.log` bzw. `/var/log/asterisk/full` |
| `starface_module_instances` | `instanzname:enabled` je Modul/Instanz (Module ≥ v1) |
| `email_server_connection_check` | `msConnectionStatus 0|1|2` (2 = DI down) |
| `email_transmission_check` | `msTransmissionStatus` — Testmail mit **Tageslimit** + **Timeout-Cache** |

`CheckMkComponent` legt zusätzlich **lokale Agent-Checks** an (`#!/bin/bash`, `/usr/lib/check_mk_agent/local/localchecks`) — Checkmk-Format `0 "Name" key=value Text`: Backup, Faxqueue, Hardware-ID, Logs, Mail, Module, Phones-offline, SIP, Version/Update, Lizenzen (full/light users, iQueues, app premium, TSP).

## XML-Format (GetMonitoringOutputXML)

```xml
<local>
  <entry key="…"><status>…</status><name>…</name><value>…</value><string>…</string></entry>
</local>
```

Zusätzlich Systemwerte: Speicher (`MemTotal`/`MemAvailable`), Festplattenauslastung (krit ≥ 90 %, Warn ≥ 70 %), STARFACE-Version (major/minor/build/revision), Update-Status, Backup-Status/-Zeit, Telefonstatus, SIP-Provider.

## Dynamische XML-RPC-Registrierung (Kernfund)

`RegisterXmlRpcEndpoint` — generischer Registrierer zur Laufzeit (aus dem Adressbuch-Modul geforkt):

- Inputs: `xmlRpcMethodName`, `moduleFunction` (Designer-Funktion), `authenticationNeeded` (Default true)
- Registriert `DynamicRpcMethod("<Instanzname>.<xmlRpcMethodName>", invocation)` — mit oder ohne `AccountAuthToken`-Auth
- `invoke(params[0] = Map)`: Werte per Name in lokale Namespace-Input-Vars → `FunctionExec.execute()` → Outputs typkonvertiert (`DATE_TIME→Date`, `NUMBER→double`, `STRING`, `BOOLEAN`, `LIST/MAP`→cast) als `LinkedHashMap` zurück
- `UnregisterXmlRpcEndpoint` räumt ab

**Bezug zum Anrufblocker:** Zwei valide Wege, Designer-Funktionen per XML-RPC erreichbar zu machen — (a) [statisch] Descriptor-`rpcEntryPoint` → Wrapper-Funktion (UUID-Ziel, unser CallBlocker-Weg; direkte Klassen-Ziele bekommen keine Parameter) oder (b) [dynamisch] solcher Registrier-Baustein (konfigurierbarer Methodenname + Auth-Flag je Registrierung). XmlMonitoring nutzt beides.

## Lizenzprüfung (CheckLicense)

`ModuleLicenseService("https://olm.o-byte.com", …, "/var/tmp", …)`: `hardwareId` = SHA-256(STARFACE-Hardware-ID + MACs aller Interfaces), Server-Lizenzkey, Licensee, Modul-/Instanzdaten, PBX-Version, vCloud-Status → `licensedFeatures` + `maxAllowedUsers`. Modi: `offlineMode` (Lizenzdatei), `ignoreCloud`/`ignoreStarfaceVersion`, Warnmail bei Problemen.

## Lessons für eigene Module

1. **Dünne Bausteine:** Eigene Dienste als Service-Schicht in eingebetteter Jar + pro-Instanz-DependencyInjector (UUID-keyed, `ClassFinder` lädt aus dem Modul-Repo) — Designer-Klassen bleiben Adapter.
2. **Cache-Schema:** Modul-Scope-Cache mit Integer-Keys + Timestamp/Timeout — für teure Abfragen übernehmenswert.
3. **Original-Bausteine instanziieren:** `Execute4` (Shell), Logging etc. aus Java-Code — deckt sich mit der CallBlocker-Philosophie (SimpleMatch/Log2 statt Eigenbau).
4. **SQL nur ohne BO-API:** `StarfaceDbAccessor` (DataSource) für Backup-/Fax-Queries.
5. **RPC dynamisch oder statisch:** je nach Bedarf konfigurierbarer Name/Auth vs. Descriptor-Entrypoints.

## Verknüpfungen

[[starface-anrufblocker]] · [[starface-modul-designer]] · Skill `starface-modul-designer` (Referenz `rpc-wrapper-funktionen.md`, Sektion „Firmenmodul-Muster") · Rohdaten: `/opt/data/profiles/axel/wiki/assets/xmlmonitoring/`

*Rekonstruiert am 2026-08-25 aus `XmlMonitoring_v152.sfm` (MD5 `8227308e…c817`) — Werkzeuge: javap (JDK 21) + CFR 0.152.*
