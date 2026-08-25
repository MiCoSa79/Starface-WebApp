---
title: Module - Reverse Engineering (XML Monitoring v152)
description: Reverse-Engineering des STARFACE-Firmenmoduls XmlMonitoring_v152.sfm — komplette Rekonstruktion (Checkmk-/XML-Output, DI-Lebenszyklus, Descriptor-Verdrahtung, dynamische XML-RPC) + Bauanleitung für eigene Monitoring-Module.
updated: 2026-08-25
---

# Module - Reverse Engineering: XML Monitoring v152

**Projektzweck:** Firmenmodule (`.sfm`) systematisch sezieren und als Vorlage für eigene Module nutzen.

**Analyse:** 2026-08-25, javap (JDK 21) + CFR 0.152. Alle 15 Root-Klassen + 15 Jar-Klassen + Descriptor-Verdrahtung rekonstruiert. Das Modul (o-byte/Hermstedt) liefert STARFACE-Monitoringdaten als **Checkmk-Text**, als **XML**, über **XML-RPC** und macht einen **täglichen Lizenz-Check** (olm.o-byte.com, Produkt `olm-10065`).

## Architektur (3 Ebenen)

| Ebene | Inhalt |
|---|---|
| 13 Funktionen im `.sfm`-Root | IBaseExecutable-Adapter (InitDI, GetMonitoringOutput, RegisterXmlRpcEndpoint, CheckLicense …) |
| 15 Dienste in `starface_xml-2.1.1-jar-with-dependencies.jar` | CheckMkComponent, XmlComponent, StarfaceAccessor(Bean), StarfaceDbAccessor(Bean), ConfigurationService(Bean), LogService(Bean), Mail(Connection|Builder)Component, Modelle |
| `license-module-5.0.1-jar-with-dependencies.jar` | obfuskierte LicenseClient-API → olm.o-byte.com |

## Descriptor-Verdrahtung

Klassen als `<function id="Klassenname"><implementationFile>Klasse.class</implementationFile></function>` (Import registriert automatisch — Firmenmuster). 9 Designer-Wrapper (UUID-Ziele) steuern den Ablauf:

- **__activate** (InstanceActivated/Created/SystemStarted): `__checkLicense` → `InitDI` → `changeConfig` → `RegisterXmlRpcEndpoint` (nur `isActiveDirectoryEnabled`, auth=false) → Log
- **__deactivate**: RemoveVariable(___licenseDelay) → `ClearCache` → `UnregisterXmlRpcEndpoint` → `ClearDI` → Log
- **__timer** (timerEntryPoint „DailyLicenseCheck", täglich): Guard-Variable `___licenseDelay` + **Random-Delay** (`delayedForkedFunctionCall`) → `__checkLicenseTask` → `__checkLicense`
- **__checkLicense**: `CheckLicense` mit productNo=`olm-10065`, productVersion=`2.1` + GUI-Variablen (offlineMode, licenseFile, ignoreStarfaceVersion, ignoreCloud)
- **changeConfig**: `InstanceInitialized` → `ChangeConfiguration` (Log-Strings/Alter) → `SetEmailConfiguration`

**RPC-Entrypoints** (statisch, Ziel = Wrapper-UUID — exakt unser CallBlocker-Muster):

```
GetMonitoringData    → Wrapper: if2 (useLocalChecks==true) → GetMonitoringOutputCheckMk
                      else → GetMonitoringOutput        → out data
GetMonitoringDataXML → GetMonitoringOutputXML          → out data
```

Der RPC-Aufrufer wählt per `useLocalChecks` zwischen Text- und CheckMk-Variante. Zusätzlich existiert ein **dynamischer Weg** (`RegisterXmlRpcEndpoint`): macht jede Designer-Funktion zur Laufzeit zur RPC `"<Instanzname>.<Name>"` (mit/ohne Auth) — hier nur für `isActiveDirectoryEnabled` genutzt. Beide Wege sind valide.

## GUI-Variablen (Modulebene, per valueByReference verdrahtet)

Fax-Queue WARN/CRIT = **5/10**, Cache-Timeout = **50 s**, Support- & PBX-Log-Fehlerstring + Alter (leer = OK, **5 min**), Offline-Lizenz (useOffline=false, licenseFile), ignoreStarfaceVersion/Cloud = false, E-Mail: Recipient leer, mailResultTimeout = **0** (aus), Transmissions/Tag = **2**.

## Caching (Module-Scope, Key-Sätze 0–5 Text / 10–15 CheckMk / 20–25 XML)

+0 Timestamp (cacheTimeout) · +1 Output · +2 Initial-Hardware-ID (Vergleich gegen `recomputeHardwareId`) · +3 Mail-Zeitpunkt · +4 Mail-Result · +5 Tageszähler (count/dayOfMonth). Update-Check zusätzlich mit 1-Tage-TTL.

## Funktionsweise im Detail

- **InitDI/ClearDI**: o-byte-DependencyInjector pro Instanz (Spring-Bohnen + ClassFinder `/var/starface/module/modules/repo/<ModuleID>`); ClearDI löscht auch `/usr/lib/check_mk_agent/`
- **CheckMkComponent**: baut ein **lokales Agent-Skript** `/usr/lib/check_mk_agent/local/localchecks` (echo $'…' + chmod via ExecuteAsRoot-Skript-Wrapper) und ersetzt im Output die Sektion `<<<local>>>…<<<starface>>>`. Lokale Checks (Checkmk-Format `STATUS "Name" key=value;warn;crit;min;max`): Update (Major→2), Version, Full/Light-User, iQueues (SQL), Terminal-Server, App-Premium, Lizenzeventual, Modul-Instanzen, Log-Status, Telefone offline, Hardware-ID, Fax-Queue (faxstat), Backups (SQL), SIP-Provider, E-Mail-Server + Testmail
- **XmlComponent**: `<local>…<entry key…><status/name/value/string>` mit RAM-Auslastung (MemTotal/MemAvailable), Update, Version, Telefone, Backups (+Zeit), SIP-Provider
- **E-Mail**: Testmail über **Original-Baustein** `de.vertico.starface.module.core.runtime.functions.net.Email` (Betreff „Xml-Monitoring - mail check"); Server-Test via MultiPartEmail+Transport mit kompletter STARFACE-Mailkonfig (externer SMTP/OAuth2/POP-before-SMTP/TLS/STARTTLS)
- **DB**: direkte JDBC-Verbindung `jdbc:postgresql://localhost/asterisk` (asterisk/asterisk, nur lokal auf der Anlage); Backups über `backup_log JOIN backup_schedules` (letzter Lauf je Standort), Queue-Counts
- **Log-Status**: ReversedLinesFileReader rückwärts über `/var/log/starface/support.log` + `/var/log/asterisk/full`, Zeitfilter (Alter), Fehlerstring-Suche → OK/ERROR/UNKNOWN
- **Lizenz**: SHA-256-Hardware-ID (STARFACE-ID + MACs), Online/Offline gegen olm.o-byte.com; für eigene Module nicht nutzbar (fremde Server)

## Bauanleitung (eigenes Monitoring-Modul)

1. Klassen als `.class` in die `.sfm` + `<implementationFile>` im Descriptor (kein manueller Upload)
2. Ausgabe-Adapter nach o-byte-Schema: `getMonitoringOutput(env, faxWarning, faxCritical)` + Cache-Keys; Text-/XML-Format wie oben
3. Datenquellen: STARFACE-Komponenten (MonitoringComponent, LicenseComponent, PersonAndAccountHandler, ModuleRegistry, `GetStarfaceVersion`-Baustein), lesendes Direkt-SQL, Shell via `Execute4`/`ExecuteAsRoot`, Logdateien rückwärts
4. E-Mail-Test immer über den Original-`Email`-Baustein
5. RPC: statische Descriptor-`rpcEntryPoint`s auf **Designer-Wrapper** (UUID-targetId, valueByReference-GUI-Variablen) — dynamische Registrierung nur bei Bedarf
6. Tages-Jobs: timerEntryPoint + Random-Delay + Guard-Variable
7. Logging über `Log2`-Baustein; alle Schwellen als GUI-Variablen (Modulebene)

## Lessons

Beide RPC-Wege (statisch + dynamisch) im selben Modul produktiv verifiziert; Wrapper-UUID-Verdrahtung über Modul-Ebene = exakt die CallBlocker-v28-Technik; Hardware-ID-/Cache-Muster direkt übernehmbar.

## Offene Punkte

MonitoringComponent-Output (vcloud-intern), MailComponent-OAuth-Details, rpcEntryPoint-`<type>`-Default, obfuskierte LicenseClient-Algorithmen — nicht Bestandteil des .sfm bzw. nicht prüfbar (kein SSH zur Anlage).
