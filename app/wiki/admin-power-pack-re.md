---
title: Admin Power Pack v20260205 — Reverse Engineering (Self-Update-Mechanik)
description: RE-Befund des Fluxpunkt-Admin Power Pack — programmatische Modul-Import-API ModuleRegistry.importModule, öffentlicher Update-Server updates.sf-app.de, <Instanzname>.xmlrpc-RPC-Protokoll (Base64-JSON, JWT-Auth), versions-JSON-Schema. Basis für das WebApp-Modul-Auto-Update.
updated: 2026-08-26
---

# Admin Power Pack v20260205 — Reverse Engineering (Self-Update-Mechanik)

**Projektzweck:** Das Admin Power Pack (Fluxpunkt GmbH, Drittanbieter) als Referenz für **automatisches Modul-Install/Update** — Vorlage für die WebApp-Auto-Update-Funktion.

**Analyse:** 2026-08-26, SBOM: `Admin_Power_Pack_v20260205.sfm` (MD5 `0916ed71604e378e5d46adcce2e51638`). Werkzeuge: `javap` (JDK 21, String-/Methodref-Scan über alle 669 Klassen) + CFR 0.152 (gezielte Dekompilation ~25 Schlüsselklassen). Live-Verifikation gegen den echten Update-Server inklusive MD5-Abgleich. Vollständiges Doku-Material: Hermes-Wiki-Entity [[admin-power-pack-re]] + Skill-Reference `starface-modul-designer/references/admin-powerpack-self-update.md`.

## Kernbefunde

### 1. Es gibt eine programmatische Import-API (widerlegt frühere „KEINE API“-Annahme)
```java
ModuleRegistry.importModule(file.getAbsolutePath(), true);   // Bytecode-Beweis in obfuskierter Update-Engine (Klasse ix)
```
- Spring-Bean, **nur aus Modulcode heraus** aufrufbar — kein externer REST/XML-RPC-Endpoint.
- Install-Ablauf des Moduls: versions-JSON laden → Download `.sfm` → MD5-Check (`DigestUtils.md5Hex`) → **Instanz-Backup exportieren** → Instanzen stoppen → `importModule(path, true)` → Backup+Instanzen wiederherstellen → Temp-Datei löschen.

### 2. Öffentlicher Update-Server (live verifiziert)
- Manifest: `https://updates.sf-app.de/<moduleId>.json` — kein Auth, kompakter Cache (`FP_UPDATE_INFO_CACHE`, TTL ~47 h)
- Paket-CDN: `https://updates.sf-app.de/packages/*.sfm`
- **Verifikations-Beweis:** Die analysierte Datei (MD5 `0916ed71…`) matcht den `md5`-Eintrag des Live-Manifests für Version 20260205 exakt.
- Schema (`is`): `{moduleVersion, ring (ALPHA/BETA/REL/LTS), downloadUrl, md5, compatibility (SemVer-Range), incompatibility, forceUpdate, lastPaidUpdate (Paywall-Gate), multiInstanceSupport, cloudSupport, modern, importantMessage}`

### 3. RPC-Protokoll: ein Einstiegspunkt pro Instanz
- XML-RPC-Name: **`<Instanzname>.xmlrpc`** (RpcObjectRegistry + `DynamicRpcMethod`, registriert bei Instanz-Aktivierung)
- Request: `Map` mit `API_REQUEST` = **Base64(JSON `{actionName, data, accessToken}`)** → Auth via `JwtVerifierComponent.verifyAccessToken()` (version-adaptiv: 7.x `SimpleAuthTokenHolder`, 10.x `.accountId()`), Default-Permission ADMINISTRATION
- Response: `API_RESPONSE` = Base64(JSON), ab >1 KB `ARC`-komprimiert
- Registry (Auszug, ~90 Endpoints): `INSTALL_MODULE` (moduleId+version → installiert **jedes** Modul), `IMPORT_MODULE_FROM_FILE`, `GET_INSTALLED_MODULES`, `GET_BEST_MODULE_VERSIONS`, `REFRESH_BEST_MODULE_VERSIONS`, `UPSERT_MODULE_INSTANCE`, `GET_INSTANCES`, `CREATE/DELETE_INSTANCE`, `SET_INSTANCE_STATE`, `DELETE_MODULE`, `EXECUTE_ASTERISK_CLI_COMMAND`, Backup-RPCs, `GET_STARFACE_UPDATE_INFOS`/`EXECUTE_STARFACE_UPDATE` (STARFACE-**Server**-Update via `ServerUpdateHandler`, getrenntes System)

### 4. „Button in der Admin-Oberfläche“
- `frontend.zip` = React/Vite-SPA (OAuth via `oidc-client-ts`); wird beim Aktivieren entpackt + Marker `FP_MODULE_ID=<id>` in `/opt/tomcat/webapps/localhost/starface/js/config/standard.js` injiziert (Klasse `cA`) → Admin-UI zeigt das Modul-Frontend an.

### 5. Alles andere
- Backend `backend.jar` (676 obfuskatierte Klassen) wird zur Laufzeit aus `/var/starface/module/modules/repo/<id>/backend.jar` geladen (URLClassLoader, Cache in `ModuleRuntime.getSystemScopeVariables()` unter `classloader-<id>`).
- STARFACE-Partner-Cloud-Login (Portal + `licensemanager.starface.de/api/session` → API_KEY) für Partner-Modul-Listen — für uns irrelevant.

## Bedeutung für die WebApp

- Ein **zentrales Updater-Modul** kann ALLE Module installieren/updaten (bewiesen über `INSTALL_MODULE` mit beliebiger `moduleId`); Selbst-Update pro Modul ist nicht nötig.
- Fahrplan + Architektur-Entscheidungen: [[modul-auto-update]]
