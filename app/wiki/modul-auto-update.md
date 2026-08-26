---
title: Modul-Auto-Update — Architektur & Umsetzungsplan (Update-Server im Stack)
description: Design für automatisches Modul-Install/Update über die WebApp — Update-Server (nginx:alpine) als 4. Docker-Stack-Service, signierte zeitbegrenzte URLs (secure_link), zentrales Updater-Modul. Entscheidungen F1–F4, Vorbereitung A1–A6, offene Punkte.
updated: 2026-08-26
---

# Modul-Auto-Update — Architektur & Umsetzungsplan

**Status:** ✅ **Task 1 umgesetzt (26.08.):** Signatur-Bibliothek `app/updatesign.py` + Tests (8/8 grün, Vektor-geprüft). ✅ **Task 2 umgesetzt + vollständig abgenommen (26.08.):** nginx-Service `module-updates` live im Stack (403/410/Durchlauf über beide Pfade — Tabelle unten). ✅ **Task 3 umgesetzt (26.08.):** WebApp-Spiegel `app/mirror.py` + Admin-Einstellung `module_update_base_url` (Priorität Einstellung > Env > leer), 23+ Tests grün, Suite komplett grün. ✅ **Task 4 deployed (26.08., Axel):** Stack-Übertragung inkl. `UPDATE_SIGNING_SECRET` (WebApp-Env + Service), Admin-Einstellung gesetzt. ✅ **TASK 5 KOMPLETT ABGENOMMEN (26.08.):** v0.0.161 live → `https://modulupdates.meiser.family/versions.json` signiert → **200** (is-Schema, absolute downloadUrls), `.sfm` → 200 + ZIP, Schutz bleibt 403. **v0.0.162:** Admin-UI-Fix (eigener Speichern-Button je Feld, Teil-POST-Sicherheit, Spiegel-Badge liest versions.json im html-Root), Suite 14/14 grün. Umsetzungsplan: `profiles/axel/.hermes/plans/2026-08-26_152327-update-server-module-updates.md` (Hermes-Wiki). Grundlagen-RE: [[admin-power-pack-re]].

**Fortsetzung P1-Beweis (UpdateDeployer, 26.08.):**
- **v0.0.164/165:** Dienst `app/module_updates.py` (push_update, signierte URL → RPC `UpdateFromUrl`-Muster) + Admin-UI `/admin/updates` mit „Update pushen“ + Deployer-Feldern je Anlage (`deployer_instance_name`, `deployer_token` verschlüsselt).
- **v0.0.166/167:** Modul **UpdateDeployer v1 „PingChannel“** (Download-Beweis, read-only): `module-updatedeployer/`, Build via `build_sfm.py`; **Vendor: „Axel Meiser - Kraemer IT“** (nie MiCoSa79). Update-Server zeigt 3 Pakete (`versions.json` 200, `.sfm` 200/4210 B).
- **v0.0.168:** „Download-Test (Ping)“-Button — Ping-RPC über WebApp-Token (kein Credential-Export); **v0.0.169:** Nav-Link „Modul-Updates“.
- **v0.0.170–172 (Import-Fallen, im Container /app/app):** `monitoring`/`module_updates`/`updatesign` sind top-level NICHT auflösbar → **Zwei-Wege-Import-Muster** (`try import X / except from app import X`) ist für ALLE app-internen Module Pflicht; v0.0.171 war dadurch ein **Boot-Crash** (Zirkel `module_updates → from main import`); **permanenter Boot-Starttest** `tmp_tests/boot_app_pkg_test.py` (Container-Sicht) verhindert Wiederholung.
- **v0.0.173:** **XML-Escaping** im XML-RPC-Body (`_xml_escape`: `&`→`&amp;` …) — signedUrl mit `?md5=..&expires=..` brach das Anlagen-Parsing (WstxUnexpectedCharException); Test `tmp_tests/xmlrpc_escape_test.py` (Body-Parsbarkeits-Beweis).
- **✅ P1 FINAL (26.08., v0.0.173):** „UpdateDeployer: Download-Test ok — HTTP 200 (4210 bytes)“ live bestätigt (Testanlage). **T5 abgenommen.**
- **🛠 T6 gebaut (26.08. abends):** UpdateDeployer **v2** (Tag v2): `[Instanz].UpdateFromUrl(moduleName, signedUrl, targetVersion, updateToken)` — signierter Download + `ModuleRegistry.importModule(path, true)` + **GU_UPDATE_TOKEN-Instanz-Schutz** (F-C). WebApp-Button „Update anstoßen“ (POST /admin/updates/push) ist vorhanden. **v3** (Tag v3) = Self-Update-Zielpaket; Server-angebot in `app/modules/` ist v3 → im Image ab **v0.0.174**. Import-Paket für die Anlage: `UpdateDeployer_v2.sfm` (Uploads).
- **⏳ Abnahme (T6, 27.08.):** v2 importieren → Instanz `GU_UPDATE_TOKEN` setzen → WebApp-Anlage `deployer_token` = gleicher Wert → WebApp auf v0.0.174 → „Update anstoßen“ → erwartet `OK: UpdateDeployer v3 importiert`; Beweis: Modul-Version 3 in Anlagen-Registry/Status.

## Ziel

Admin kann aus der WebApp heraus **alle eigenen Module** (TelefonieMonitoring, CallBlocker …) auf der STARFACE-Anlage automatisch aktualisieren — ohne Admin-UI der Anlage, ohne manuellen `.sfm`-Import.

## Entscheidungen (mit Nutzer abgestimmt, 2026-08-26)

### F1: Download-Schutz → signierte, zeitbegrenzte URLs statt hartkodiertem Token
- Update-Server prüft HMAC-Signatur (nginx `secure_link`, Secret **nur in der WebApp-Env**).
- Kein Token im Modulcode: „verschlüsselt hardcoden“ wäre nur Bytecode-Obfuscation (im RE bewiesen reversibel) und schützt nicht gegen Modulbesitzer; Signatur ist rotierbar ohne Modul-Rebuild.

### F2: Trigger-Konzept → WebApp orchestriert (Phase 1), Anlagen-UI optional (Phase 2)
- Transport/Trigger getrennt: **Base64-Push** (WebApp → Modul) = nur WebApp-Trigger, nutzt die bewährte Netzrichtung (XML-RPC + JWT) — Phase 1-Fallback.
- **URL-Pull** (Modul lädt vom Update-Server) = WebApp-Trigger ✅, Anlagen-UI-Button ✅, Timer ✅ — erfordert Erreichbarkeit Anlage → Update-Domäne.
- Modul-UI-Button später als **Modul-GUI-Tab** (kein React-SPA wie beim Admin Power Pack).

### F3: Deployment → eigener Update-Server als 4. Service im bestehenden Stack
- `nginx:alpine` (offizielles Image, `secure_link` + `limit_req` eingebaut) — kein Eigenbau-Image, nur Config-Volume.
- Statisch + read-only; **kein** `x-casaos`-Eintrag (reiner Helper wie influxdb), Zugriff nur über NPM.

### F4: Update-Server-URL ist eine ADMIN-EINSTELLUNG (wie Grafana-Basis-URL v0.0.121)
- **Nicht hartcodiert** und nicht nur Env: Neue Einstellung `module_update_base_url` in der `settings`-Tabelle (Helper `_get_setting`/`_set_setting`, Admin-UI `/admin` → „Einstellungen").
- Priorität: **Admin-Einstellung > Env `MODULE_UPDATE_BASE_URL` > Default leer** (leer = kein Update-Kanal sichtbar/aktiv bis gesetzt).
- Die Einstellung steuert beides: die `downloadUrl` in `versions.json` UND die Signatur-Erzeugung (Task 1).
- Das Update-Modul (Phase 3) bekommt die URL stets von der WebApp übergeben — nie selbst fest verdrahtet.

```
ZimaOS-Stack ───┐
├─ starface-webapp ─ :8895   spiegelt app/modules/*.sfm → data/modules + versions.json → data/ (html-Root)
├─ grafana ────────── :8894
├─ influxdb (intern)
└─ module-updates ─── :8896  nginx:alpine, secure_link, read-only
      ▲ NPM: https://modulupdates.meiser.family → :8896
      STARFACE-Anlage lädt .sfm selbst (Pull) / WebApp schiebt per XML-RPC (Push-Fallback)
```

## Vorbereitung durch den Nutzer (A1–A6, vor Task 1)

| # | Aufgabe | Detail |
|---|---|---|
| A1 | **Netz-Test** ✅ | Cloud-Anlagen → öffentlicher Weg verifiziert (check-host.net, 5 Nodes weltweit: DNS → UDM/öffentl. IP → NPM → 502 = erwartet, da Backend fehlt) |
| A2 | DNS ✅ | `modulupdates.meiser.family` → öffentl. IP (`176.126.73.130`, UDM-Firewall) |
| A3 | NPM-Host ✅ | `modulupdates.meiser.family` → `10.0.25.60:8896`, Let's Encrypt + Force SSL |
| A4 | Secret ✅ | liegt vor (PowerShell `New-Guid`-Variante) → `<UPDATE_SIGNING_SECRET>` in Stack bei Task 4 (nicht committen) |
| A5 | Ordner | `/DATA/AppData/starface-webapp/data/modules` — optional, Docker legt an |
| A6 | Dateien ✅ | `app/modules/TelefonieMonitoring.sfm` + `CallBlocker.sfm` vorhanden |

## Abnahmetest (26.08. — nginx-Service live)

| Test | Direkt `10.0.25.60:8896` | NPM `https://modulupdates.meiser.family` |
|---|---|---|
| `versions.json` ohne Token | **403** ✅ | **403** ✅ |
| `/modules/Test.sfm` ohne Token | **403** ✅ | **403** ✅ |
| Gefälschte Signatur (`md5=gefälscht`) | **403** ✅ | **403** ✅ |
| **Abgelaufene Signatur** (expires −1h, echtes Secret) | **410** ✅ | **410** ✅ |
| **Gültige Signatur**, Datei fehlt (`__existiert_nicht__.sfm`) | — | **404** ✅ (= Prüfung läuft grün durch, nur Datei fehlt) |
| `versions.json` im html-ROOT (`/versions.json`) | — | vor Fix: **404** (Datei lag in `modules/`) → nach v0.0.161: **200** ✅ |
| Gültige Signatur auf `/modules/versions.json` | — | **200** ✅ (Beweis des Pfad-Bugs: Datei lag in `modules/`) |
| **Gültige Signatur → 200 + Inhalt** (`.sfm`) | — | **200** ✅ (TelefonieMonitoring v7 + CallBlocker v28, ZIP-Magic `PK` geprüft) |
| `/versions.json` ohne Token | — | **403** ✅ (Schutz bleibt aktiv) |

→ **Task 2 vollständig abgenommen:** 403 (keine/falsche Signatur), 410 (abgelaufen), Durchlauf (grün → 404 statt 403) — direkt und über NPM/SSL. **Task 5 komplett abgenommen (26.08.):** mit v0.0.161 live: `/versions.json` signiert → **200** (is-Schema, absolute downloadUrls aus der Admin-Einstellung), `.sfm` → 200 + ZIP, Schutz ohne Token weiterhin 403.

## Umsetzung (5 Tasks, TDD — Details im Plan-Dokument)

1. ✅ **Signatur-Bibliothek** `app/updatesign.py` (+ `tmp_tests/test_updatesign.py`) — `secure_link`-kompatible URLs (`_nginx_md5`, `build_signed_url`, `parse_parts`), 2 Known-Vektoren von Hand + Roundtrip/TTL/URI-Differenz, 8/8 grün; Suite unverändert grün (module_status_test, error_box_test, monitoring_rechte_e2e 17/17, module_status_live)
2. ✅ **nginx-Config** `deploy/nginx-updates.conf.template` — als envsubst-**Template** fürs offizielle nginx-Image (`default.conf.template` → ersetzt beim Start die Image-default.conf, `${UPDATE_SIGNING_SECRET}` aus `environment`); `secure_link` (403/410/200), `limit_req`, read-only. Mechanismus simuliert & verifiziert (Secret wird ersetzt, `$uri`/`$arg_md5` bleiben). ~~Testskript~~ → ersetzt durch **Stack-Integration** (Task 4 vorgezogen): nginx:alpine wird direkt als Service `module-updates` in den ZimaOS-Stack aufgenommen, Test = Deploy + Fern-Abnahme über 10.0.25.60:8896 (403 ohne Token sofort prüfbar; 410/200 nach Secret-Ablage in `/opt/data/.env` bzw. Task-3-Spiegel)
3. ✅ **WebApp-Spiegel** `app/mirror.py` — beim Startup kopiert er `.sfm` aus `app/modules` → `<data>/modules` (geteiltes Volume mit nginx) und schreibt `versions.json` im `is`-Schema (`moduleName`, `moduleVersion` aus dem `version`-Attribut der `module-descriptor.xml`, `ring=stable`, `downloadUrl` aus Admin-Einstellung `module_update_base_url`, `md5` je Datei) — **im html-ROOT (`<data>/versions.json`)**, NICHT in `modules/` (Fix `b34e94d`, v0.0.160); beim Lauf wird eine Legacy-`versions.json` in `modules/` entfernt. Fehler brechen den Containerstart nie (try/except + Log). Admin-UI: `/admin` hat das Feld **„Update-Server-Basis-URL“** (wie Grafana-Basis-URL — die Einstellung IST die einzige gesetzte Quelle, Env-Fallback `MODULE_UPDATE_BASE_URL` bleibt reine Code-Option und wird im Stack NICHT gesetzt), `/admin/modules` zeigt Spiegel-Badge (aktiv + Paketanzahl). Tests: `tmp_tests/test_module_mirror.py` (13 inkl. html-Root-Check, Legacy-Cleanup; Fake-.sfm-ZIPs inkl. kaputte Datei, Idempotenz, Schema, trailing-slash) + `tmp_tests/admin_settings_test.py` (11, Render admin.html/modules.html, POST speichert, Priorität) — Suite komplett grün (module_status_test, error_box_test, monitoring_rechte_e2e 17/17)
4. 🔄 **Stack-Patch (Kopie!)** — Service `module-updates` EINGEBAUT in `starface-webapp-compose-zimaos.yaml` (nginx:alpine, Port 8896, Env `UPDATE_SIGNING_SECRET`; Volumes: Host-`data` → html-Root ro, `update-server/` → `/etc/nginx/templates` ro); YAML + Service-Asserts validiert (uv+PyYAML). **Ausstehend: Übertragung auf ZimaOS + Deploy durch Axel** (Datei `default.conf.template` per Dateimanager ablegen, Stack ersetzen, `<UPDATE_SIGNING_SECRET>` an 2 Stellen ersetzen — WebApp-Env + Service). **Nur das Secret als Env** — die Basis-URL wird in den WebApp-Admin-Einstellungen gesetzt (wie die Grafana-Basis-URL), KEINE `MODULE_UPDATE_BASE_URL`-Env im Stack
5. **Deploy + Abnahme** — 403 ohne Token / 200 mit frischer Signatur / WebApp-Log „mirror ok“; Rollback = nur neue Service-Definition zurück

## Offene Punkte

- **P1:** Anlage → Update-Domäne ungetestet; Fallback = Base64-Push (Phase 1 trotzdem baubar)
- ~~**P2:** `secure_link`-`$uri`-Normalisierung~~ → ✅ erledigt: Live-Test 26.08. lieferte signierte 200er auf `modules/<datei>.sfm` und `modules/versions.json` über NPM/SSL
- **P3:** Tomcat-`maxPostSize` (>5-MB-Base64-Pakete) nur beim Push-Weg relevant — ggf. `ARC`-Kompression (Admin-Power-Pack-Muster)
- **P4:** Phasen 2/3: zentrales Updater-Modul (RPCs `GetModuleVersions`/`UpdateModule`/`UpdateAll` + `importModule`), optional GUI-Tab-Button — separater Plan nach Freigabe

## Abgrenzung

Hermes-Wiki hält die ausführliche Fassung (Entscheidungslogik F1–F3, Risiko-Tabelle, vollständiger Plan inkl. Code-Snippets): `profiles/axel/wiki/entities/admin-power-pack-re.md`.
