---
title: STARFACE WebApp — Gesamtdokumentation & Versionshistorie
description: Die WebApp selbst: Architektur, Betrieb, Routen, Konventionen und die vollständige Versionshistorie (v0.0.1–v0.0.198, aus Git-Tags).
updated: 2026-08-28
---

# STARFACE WebApp

Multi-User-Verwaltungs-WebApp für STARFACE-Installationen: Anlagen-Verwaltung (OAuth),
CallBlocker-Pflege, Telefonie-Monitoring (Grafana/InfluxDB), Modul-Verwaltung und
Modul-Updates (Deployment-Modul). Repo `MiCoSa79/Starface-WebApp`, Image
`micosa79/starface-webapp` (Docker Hub), CI taggt bei **jedem** Push automatisch
`v0.0.x` (auch reine Doku-Commits). Container auf ZimaOS hinter NPM, Port 8895.

## Architektur

- **Stack:** FastAPI + SQLite (Bewegungsdaten in InfluxDB) + Jinja2-Templates + Service-Worker (PWA).
- **Auth:** Session-Cookie + 2FA (TOTP) + **Passkeys (WebAuthn, optional, F58)**,
  Rollen Admin/User, OAuth2-Authorization-Code-Flow
  je STARFACE-Anlage (Token verschlüsselt per Fernet in der DB).
- **Import-Muster (Container):** App-Module liegen unter `/app/app/` — Zwei-Wege-Import
  `try: from main import ... except ImportError: from app.main import ...` in allen App-Teilen.
- **Module im Repo:** `module-deployment/` (Deployment-Modul; Modul-Tags historisch `ud-vN` bis v7, ab v8 `dm-vN`),
  `module-monitoring/` (TelefonieMonitoring, Tags `vN`), CallBlocker (Tags `vN`) —
  Build via `build_sfm.py`, Spiegel nach `app/modules/` (SOLL-Versionen, mtime-Cache).
- **Update-Server:** nginx-Service `module-updates` (Port 8896) mit Secure-Link-Signaturen
  (`updatesign.py`, `UPDATE_SIGNING_SECRET` nur Env), Domain `<update-server>` (im Admin hinterlegbar).
- **Tests:** `tmp_tests/<name>.py` mit eigenem `check()`-Muster (kein pytest);
  Fakes/Zweige für Container-Importe; E2E via TestClient.

## Routen (Stand v0.0.190)

| Bereich | Routen |
|---|---|
| Dashboard/Login | `/`, `/dashboard`, `/api/login`, `/api/2fa/verify`, `/password`, `/logout`, `/oauth/callback` |
| Monitoring | `/monitoring`, `/api/monitoring/status`, `/admin/monitoring`, `/health`, `/version` |
| Anlagen | `/admin/installations` (+ `/…/{id}`, `/edit`, `/delete`, `/test-conn`, `/oauth-start`) |
| Modul-Updates | `/admin/updates` (+ `/push`, `/push-all`, `/ping`), Anlagen-RPC `[Instanz].UpdateFromUrl` |
| Modul-Verwaltung | `/admin/modules` (+ `/…/{id}/download`) |
| Users/System | `/admin/users` (+ role/delete/totp-*), `/admin/settings`, `/admin/access`, `/admin` |
| Wiki/API-Doku | `/wiki`, `/wiki/search`, `/wiki/{wiki_page}`, `/admin/api-doku`, `/sw.js` |
| CallBlocker | `/installation/{id}/blocklist` (+ add/remove/update), `/installation/{id}/test` |

**Stand 26.08. (F37/F38, v0.0.190):** Sammel-Buttons je Anlage auf der Modul-Updates-Seite (`POST /admin/updates/push-all`, Modi `install`/`update`) — Details [modul-auto-update](modul-auto-update.md). Modul-Seite: Download-Button **Icon-only**; neue Spalte **„Dokumentation“** (PDF-Badge → `/static/docs/<Modul>.pdf`: CallBlocker v30, TelefonieMonitoring v9, Deployment-Modul v8; Generator `app/scripts/generate_modul_pdfs.py` — nach Versions-Änderungen neu ausführen). Statusmeldungen auf der Modul-Updates-Seite mit **OK-Button** ausblendbar.

**Stand 26.08. (F42, v0.0.196):** **Mobile-Fix Admin-URL-Felder** — auf Handys waren beide URL-Eingabefelder (Grafana-Basis-URL + Update-Server-Basis-URL) **380 px hoch**: das Inline-`flex:1 1 380px` wurde in der Mobile-`column`-Flexbox (`.form-row { flex-direction: column }`) als **Höhe** interpretiert (flex-basis wirkt auf die Hauptachse). Fix: CSS-Klasse `.url-field` (`flex: 1 1 380px; font-size:16px;` Desktop) + Media-Query-Override `.url-field { flex: 1 1 auto; min-height: 44px; }` (Mobile) — Inline-Styles entfernt. Beweis: Headless-Chrome-CDP-Test `tmp_tests/mobile_url_layout_cdp.mjs` (390×844): Höhe 380→44 px, Touch-Höhe 44 px, font-size 16 px (iOS-Zoom), Desktop-Breite ≥380 px bleibt.

**Stand 27.08. (F44, v0.0.198):** **Drittanbietermodule** — Admins können auf der Modul-Seite echte Drittanbieter-`.sfm`-Pakete hochladen (ZIP mit `module-descriptor.xml` → Name/Version/Vendor werden automatisch ausgelesen, keine Tippfehler). Neue Spalte `source` in der `modules`-Tabelle (`own`/`third_party`), Speicherung unter `<data>/modules` (persistentes Volume); Spiegel + `versions.json` inkludieren die Pakete, sodass sie über die **Update-Seite je Anlage mit dem Deployment-Modul eingespielt/aktualisiert** werden können (Badge „Drittanbieter“). Die **Monitoring-Karte** zeigt Drittanbietermodule nur, wenn sie auf der Anlage installiert sind UND in der WebApp hinterlegt wurden (Filter `filter_third_party_missing` — keine Fehlanzeigen für noch nicht verteilte Pakete). Modul-Seite: zwei Tabellen („Verfügbare Module — eigene“ / „Drittanbietermodule“) + Upload-/Löschen-Aktionen; Download aus `<data>/modules` (identische Sicherheitskette: Dateiname aus DB, keine Pfad-Traversal). Test: `tmp_tests/third_party_modules_test.py` (43 Checks) + Suite grün.

**Stand 27.08. (F45, v0.0.200):** **Mehr Bildschirmbreite + stabile Aktions-Buttons** (Axel: „Nutze mehr von der Breite des Bildschirms“, Screenshot Modul-Updates: Buttons der Xml-Monitoring-Zeile rutschten untereinander). Die Seitenbreite ist **Inline-CSS je Template** (keine zentrale CSS-Datei): `.container { max-width: … }` war 900/960/1100/720 px je Seite → einheitlich **1400 px** (9 Templates: `admin_updates`, `modules`, `monitoring`, `admin`, `base`, `wiki`, `api_doku`, `dashboard`, `blocklist`); **Login (`password.html`) bleibt bewusst schmal (520 px)**. Aktions-Zellen der Modul-Tabellen: `td form { display:flex; gap:8px; flex-wrap:nowrap; white-space:nowrap }` → Buttons („Installation anstoßen“ + „Download-Test (Ping)“ u. a.) bleiben auf Desktop **immer nebeneinander**; nur ≤640 px (`@media`) wieder `wrap` (Mobile). Regressionstest: `tmp_tests/admin_layout_width_test.py` (**19 Checks**: 1400 px auf allen Inhaltsseiten, keine alten Schmalklassen, Login 520 px, nowrap/wrap-Regeln).

## Wo stehen welche Details?

| Thema | Artikel |
|---|---|
| Modul-Updates/Deployment-Modul (T1–T7) | [modul-auto-update](modul-auto-update.md) |
| CallBlocker-Modul (inkl. älterer WebApp-Historie) | [starface-anrufblocker](starface-anrufblocker.md) |
| Telefonie-Monitoring (Modul + Grafana) | [starface-telefonie-monitoring](starface-telefonie-monitoring.md) |
| Admin Power Pack-RE (Import-API-Grundlage) | [admin-power-pack-re](admin-power-pack-re.md) |
| Modul-Paketierung/Designer | [starface-modul-paketierung](starface-modul-paketierung.md), [starface-modul-designer](starface-modul-designer.md) |

## Design-Anforderung (OFFEN, 26.08. — F35)

- **Axel:** Die WebApp-Seite wird zunehmend unübersichtlich → **Redesign erforderlich**.
- Weitere Infos folgen; bis dahin kein Umbau, keine Layout-/Stack-Entscheidung (Hermes-Wiki log.md F35).

## Roadmap / Geplante Features (27.08. — Axel)

1. **Tenant-Verwaltung** — Mandanten/Organisationen in der WebApp; Verwaltung ausschließlich durch eine **Super-Admin**-Rolle (Hinweis Axel).
2. **Lizenzverwaltung für Module** — Lizenzen **tenant-basiert** (je Mandant je Modul) **und** für die STARFACE-WebApp selbst (**Super-Admins**).

## Versionierung & Docker-Kanäle (ab v1.0.0, F57)

- **Git-Tags:** `v1.0.0` … `v1.0.x` — Auto-Bump bei jedem Push auf main (Guard: bereits mit vX.Y.Z getaggter Commit wird nicht erneut gebumpt). Historische `v0.0.1`–`v0.0.211` bleiben bestehen.
- **Docker-Kanäle** (`micosa79/starface-webapp`):
  - `nightly` + `v1.0.x` — bei **jedem Push auf main** (Entwicklungsstand). Der ZimaOS-Stack läuft auf `nightly`, damit Axel neue Entwicklungsreleases automatisch ziehen und testen kann.
  - `latest` + `v1.0.x` — **nur bei Freigabe durch Axel**: Chat an Hermes „vX.Y.Z als latest veröffentlichen“ → Hermes setzt/moved den Git-Tag `release-latest` auf den Stand → CI baut `latest`.
  - **Keine Datums-Tags** mehr (Altbestand `2026-08-25`, `2026-08-26`, `2026-08-27` wird nach Hub-Löschung entfernt; Workflow erzeugt keine neuen).

## Versionshistorie (vollständig, aus Git-Tags)

Quelle: `git for-each-ref refs/tags/v0.0.*` — Stichworte = Commit-Subject.

| Version | Commit | Änderung |
|---|---|---|
| v1.0.10 | (27.08.) | fix: Passkey-Entfernen committete nie (execute auf Conn A, commit auf Conn B → offene Transaktion blockierte DB dauerhaft → „database is locked" auch beim Logout-500); busy_timeout 30 s — Hash folgt im nächsten Code-Commit |
| v1.0.9 | `be3b2be` | Härtung: WAL-Journal + busy_timeout — Wurzel des Logout-500 war in Wahrheit die offene Transaktion aus dem Entfernen-Bug (v1.0.10) |
| v1.0.8 | `b8b11fb` | fix(F58): „Zurück"-Link der Passkey-Seite auf `/admin` korrigiert (GET `/admin/users` existiert nicht → 405) |
| v1.0.7 | `1975fdd` | docs(wiki): F58-Historie v1.0.3–v1.0.6 nachgezogen (cbor2-Fix, Login-Optik, Browser-Dekodierung) |
| v1.0.6 | `e0dcb8e` | fix(F58): WebAuthn-Options-Dekodierung — challenge/user.id als Byte-Arrays für create/get (Browser-DOMException „Invalid 'user.id' length") |
| v1.0.5 | `f27d83c` | ui(F58): Passkey-Login in die Login-Karte integriert (Optik, UX-Feedback „nicht provisorisch") |
| v1.0.4 | `6f4966b` | docs(wiki): Recherche Anlagen-Updates (paralleler Commit, keine App-Änderung) |
| v1.0.3 | `87fff6c` | fix(F58): cbor2 explizit in requirements — fehlte im Container → FIDO2_OK=False („Passkeys nicht konfiguriert") |
| v1.0.2 | `4ae79d9` | F58: Passkeys/WebAuthn (B mit C-Schalter) — fido2 2.2, Conditional UI, Geräteverwaltung, WEBAUTHN_PASSWORDLOGIN=0 (C-Schalter) |
| v1.0.0 | `cf713f2` | chore(versioning): Kanal-Modell — nightly + v1.0.x bei jedem Push, latest nur via release-latest-Tag (Freigabe Axel), keine Datums-Tags mehr (F57) |
| v0.0.209 | `9ed26cf` | docs(wiki): Roadmap — Tenant-Verwaltung (Super-Admin) + Lizenzverwaltung für Module (tenant-basiert) und WebApp (Super-Admins) (F54) |
| v0.0.208 | `5eb1c5d` | F53: Spiegel-Meldung vereinfacht — 'Update-Server-Spiegel aktiv — N Paket(e) vorhanden' (ohne Ordner /modules und Basis-URL) |
| v0.0.207 | `790cf49` | F52: Tooltips (CSS-Blasen im Seitendesign) für 'Fehlende Module installieren' + 'Module aktualisieren' (data-tip, Hover + Fokus) |
| v0.0.206 | `1a49081` | F51: Einzel-Push meldet 'Es ist bereits die aktuellste Version installiert' statt RPC, wenn IST == SOLL (IST-Abruf wie push-all, Fehlerfall unverändert) |
| v0.0.205 | `1e5af7b` | F50: Token-UI — Anzeigen/Verbergen (Eye-Toggle), Klartext-Anzeige mit Kopieren-Button nach Generierung + Beschreibung: identischer Token im Modul auf der Anlage (Reiter Sicherheit, Feld Update-Token) |
| v0.0.204 | `bc3b3c5` | F49: Mirror-Stale-Cleanup — verwaiste eigene Pakete (UpdateDeployer.sfm) werden beim Spiegeln aus data/modules entfernt, Drittanbieter bleiben |
| v0.0.203 | `88b1513` | F48: Token-Generator (64 Zeichen, 256 Bit) in den Anlagen-Einstellungen (POST /admin/api/generate-token, Admin-only) |
| v0.0.202 | `2d88943` | F47: Stale-Cleanup in _scan_modules — verwaiste eigene Module (UpdateDeployer-Zeile) werden entfernt |
| v0.0.201 | `0b63ef6` | F46: UpdateDeployer -> Deployment-Modul umbenannt (Modul v8/dm-v8, UI, PDF, Tests, Wiki) |
| v0.0.200 | `7a00ca1` | style(ui): Mehr Bildschirmbreite (1400px einheitlich) + Aktions-Buttons nie untereinander (F45) |
| v0.0.199 | `fd4d710` | docs(wiki): Versionsregister v0.0.197-v0.0.198 nachgezogen (F44) — Frontmatter updated |
| v0.0.198 | `e483a20` | feat(modules): Drittanbietermodule verwalten — Upload/Delete, zwei Tabellen, UpdateDeployer + Monitoring-Karte (F44) |
| v0.0.197 | `7b5a5d0` | docs(wiki): Versionsregister v0.0.183-v0.0.196 nachgezogen (F40/F41/F42) — Frontmatter updated ergänzt (verify_wiki_refs), PDF-Versionen v30/v9/v7, Mobile-Fix-F42-Stand |
| v0.0.196 | `96ac3c4` | feat(admin): Mobile-Fix URL-Eingabefelder — flex-basis 380px wurde in der column-Flexbox zur Höhe (380 px) → .url-field-Klasse + Media-Query-Override (44 px); Regressionstest mobile_url_layout_cdp.mjs (F42) |
| v0.0.195 | `374edbd` | feat(modules): alle 3 Module mit Passwortschutz neu gebaut (v30/v9/ud-v7, writeHash=sha1(id+pw), Env-Pflicht STARFACE_MODULE_PASSWORD) — F41 |
| v0.0.194 | `deec7df` | docs: GU_UPDATE_TOKEN — New-Guid-Variante gekennzeichnet als NICHT CLM-tauglich, CLM-Hinweis ergänzt |
| v0.0.193 | `52093d5` | docs: GU_UPDATE_TOKEN — PowerShell-Varianten (CLM-konform mit New-Guid + .NET-Base64) in UpdateDeployer-Doku |
| v0.0.192 | `306f7eb` | docs: Doku-Bereinigung — keine Meiser-Domains (außer Vendor), Beispiel-URLs neutral |
| v0.0.191 | `8ec5d43` | fix(updates): Meldetext 'Installation angestoßen' bei Erst-Installation — Einzel-Button + push-all install (F39) |
| v0.0.190 | `4319b11` | feat(modules): PDF-Dokumentation je Modul + Icon-Download; Statusmeldungen mit OK-Button (F38) |
| v0.0.189 | `6b133f8` | feat(updates): Sammel-Buttons je Anlage — 'Fehlende Module installieren' + 'Module aktualisieren' (push-all, F37) |
| v0.0.188 | `9c768c2` | docs(wiki): Design-Redesign der WebApp angemeldet (F35, OFFEN) |
| v0.0.187 | `f842c4b` | feat(webapp): Button 'Installation anstoßen' bei nicht installiertem Modul, sonst 'Update anstoßen' |
| v0.0.186 | `0024f60` | docs(wiki): Ausblick Grafana-Ablösung durch WebApp-Dashboards (F33, Entscheidung offen) |
| v0.0.185 | `8186b5e` | docs(wiki): Instanz-Anlage programmatisch geprüft — machbar, nicht gebaut (F32) |
| v0.0.184 | `5528a47` | docs(wiki): Erst-Import-Fähigkeit von importModule verifiziert (Axel-Einwand, F31) |
| v0.0.183 | `4825e5a` | docs(wiki): eigener Artikel für die WebApp selbst — vollständige Versionshistorie v0.0.1–v0.0.182 aus Git-Tags |
| v0.0.182 | `d533412` | docs(wiki): Version (IST) auf Modul-Updates-Seite — v0.0.180 (Commit 7864072) |
| v0.0.181 | `7864072` | feat(updates): Version (IST) auf Modul-Updates-Seite — frischer GetModuleStatus-Abruf |
| v0.0.180 | `66e1e82` | feat(updatedeployer): T7 v6 — Auto-Restart aller aktiven Instanzen nach Import |
| v0.0.179 | `4596c0b` | docs(wiki): T6 LIVE-Test bestanden — Self-Update 4→5 mit Token (21:32 CEST) |
| v0.0.178 | `23411d6` | docs(wiki): T6 v4/v5 + GUI-Tab 'Sicherheit' — Abnahme 27.08. (v0.0.178) |
| v0.0.177 | `e15c696` | docs(wiki): T6 v2/v3 gebaut — Abnahme-Anleitung 27.08. |
| v0.0.176 | `5b3097e` | modul(updatedeployer): v2 UpdateFromUrl — signierter Download + ModuleRegistry.importModule, Instanz-Token-Schutz (GU_UPDATE_TO... |
| v0.0.175 | `5b075e5` | docs(wiki): P1 FINAL — Download-Test ok (HTTP 200, 4210 bytes), T5 abgenommen |
| v0.0.174 | `6c3c1ac` | docs(wiki): P1-Fortschritt v0.0.164-173 + Import-/XML-Escaping-Lehren; Vendor-Konvention |
| v0.0.173 | `738fa53` | fix(updates): XML-Escaping im XML-RPC-Body (& in signedUrl) — Anlagen-Parse-Fehler behoben |
| v0.0.172 | `72b6720` | fix(imports): module_updates Zwei-Wege-Import (Container /app/app) — Boot-Crash gefixt; Boot-Starttest permanent |
| v0.0.171 | `b5f97a1` | fix(updates): module_updates top-level mit Fallback (Container /app/app) — Routen nutzen globales Modul |
| v0.0.170 | `de79c7f` | fix(updates): /admin/updates Import-Fallback monitoring -> app.monitoring (Container-500) |
| v0.0.169 | `a22fa99` | ui(updates): Nav-Link 'Modul-Updates' in der Admin-Leiste |
| v0.0.168 | `d964f44` | feat(updates): 'Download-Test (Ping)' Button in Admin-UI — P1-Beweis ohne Credential-Export (T5-UI); fix: sqlite3.Row.get in pu... |
| v0.0.167 | `817ad55` | fix(updates): UpdateDeployer Vendor 'Axel Meiser - Kraemer IT' (Konvention) |
| v0.0.166 | `c514278` | feat(updates): UpdateDeployer v1 PingChannel — Kanal-Beweis-Modul (T5) |
| v0.0.165 | `e177fd4` | feat(updates): Admin-UI 'Modul-Updates' — Deployer-Felder, Push-Route, Statuszeile (T4) |
| v0.0.164 | `455a1f0` | feat(updates): UpdateDeployer-Anbindung — signierte URL + UpdateFromUrl-RPC (T3) |
| v0.0.163 | `fb35467` | fix(admin): Badge-Text nennt html-Root statt data/modules-Ordner (P5) |
| v0.0.162 | `6b4e7e9` | fix(admin): Update-Server-URL mit eigenem Speichern-Button; Badge liest html-Root |
| v0.0.161 | `d13aa2f` | docs(wiki): Task-5-Live-Abnahme + versions.json-Root-Fix (Abnahmetabelle, P2 erledigt) |
| v0.0.160 | `b34e94d` | fix(updates): versions.json in den html-Root schreiben statt nach modules/ |
| v0.0.159 | `752c103` | docs(update): Basis-URL nur als Admin-Einstellung — keine MODULE_UPDATE_BASE_URL-Env im Stack |
| v0.0.158 | `1f301d0` | docs(wiki): Abnahme Task 2 komplett - 410 + Signatur-Durchlauf verifiziert (echtes Secret) |
| v0.0.157 | `e29be95` | feat(update): WebApp-Spiegel mirror.py + versions.json + Admin-Einstellung module_update_base_url (Task 3) |
| v0.0.156 | `971ba79` | docs(wiki): Abnahmetest Task 2 - secure_link 403-Checks bestanden (direkt + NPM) |
| v0.0.155 | `754936e` | feat(update): nginx-updates.conf fuer secure_link module-updates + ZimaOS-Testskript |
| v0.0.154 | `45e4746` | feat(update): nginx config als envsubst-Template für Stack-Service module-updates (Task 4 vorgezogen) |
| v0.0.153 | `60d0898` | feat(update): signierte Download-URLs (nginx secure_link) — Signatur-Bibliothek + Tests TDD |
| v0.0.152 | `754936e` | feat(update): nginx-updates.conf fuer secure_link module-updates + ZimaOS-Testskript |
| v0.0.151 | `60d0898` | feat(update): signierte Download-URLs (nginx secure_link) — Signatur-Bibliothek + Tests TDD |
| v0.0.150 | `60d0898` | feat(update): signierte Download-URLs (nginx secure_link) — Signatur-Bibliothek + Tests TDD |
| v0.0.149 | `7dcb6a1` | test(monitoring): SFM-Fakes neu gepackt (identischer Inhalt, frischer ZIP-Timestamp) |
| v0.0.148 | `17045e0` | refactor(monitoring): Diagnose-Block 'Rohdaten GetModuleStatus' entfernt (Befund abgeschlossen) |
| v0.0.147 | `48ab113` | test(monitoring): Fakes mit rpcEntryPoint (provides) — repräsentativ für echte Descriptoren |
| v0.0.146 | `9039513` | fix(monitoring): ROOT CAUSE 'Nicht installiert' — moduleJson liegt unter members, Abgleich las Top-Level (immer None) |
| v0.0.145 | `376753d` | fix(monitoring): Diagnose-Route holt volle installations-Zeile (SELECT *) — 'Kein Token' war KeyError auf fehlenden Auth-Spalten |
| v0.0.144 | `b95c373` | docs(wiki): Modul-Status-Befund-Fortschreibung — GetModuleStatus-Fault durch ZimaOS-Logs widerlegt (status=200 + komplette Modu... |
| v0.0.143 | `62ef6da` | feat(module): TelefonieMonitoring v7 — moduleDiag-Diagnose (rohe Registry-Daten, getVersion-Beweis) über laufenden GetStats-Pfa... |
| v0.0.142 | `749b40d` | fix(module): TelefonieMonitoring v6 — GetModuleStatus-Fault 'No item with that key' beheben (ModuleRegistry.getInstances4Module... |
| v0.0.141 | `cd7a0b7` | feat v0.0.141: Admin-Diagnose-Rohdaten-Endpoint GetModuleStatus (Befund: 'Nicht installiert' trotz eingerichtetem Modul v5) |
| v0.0.140 | `a810bf7` | fix v0.0.140: 'zu alt'-Meldung nennt GetModuleStatus-Exporteur (v5) statt erstes SOLL-Modul (v28) |
| v0.0.139 | `d283c27` | docs: Feature-Version korrigiert v0.0.137->v0.0.138 (CI-Tag des Feature-Commits 16f56e5); 137 war der fake_getstats-Nachtrag de... |
| v0.0.138 | `16f56e5` | modul v5 + webapp: Modul-Status-Abgleich auf der Monitoring-Seite (GetModuleStatus) |
| v0.0.137 | `8ca3b2c` | test: Fake-GetStats-Server fuer Monitoring-Live-Beweis (Fehlerbox verschwindet) |
| v0.0.136 | `ed531eb` | v0.0.136: Monitoring-Fehlerbox verschwindet, sobald Fehler nicht mehr besteht + Auftrittszeit Europe/Berlin |
| v0.0.135 | `c5d6ac9` | Monitoring-Auto-Refresh (15s) + Dashboard-Fehlalarm-Fix + Design-Umbau |
| v0.0.134 | `8b26553` | Wiki: Kiosk-Footer-Fix v0.0.133 dokumentiert (hideLogo) |
| v0.0.133 | `9e44f1b` | Grafana-13-Kiosk: hideLogo ergaenzt — sticky 'Powered by Grafana'-Footer (PR grafana#115202, Kiosk-Branding seit Jan 2026) per ... |
| v0.0.132 | `c55e65b` | Wiki: Grafana-13-Kiosk-Fix dokumentiert (kiosk=1, Historie v0.0.131) |
| v0.0.131 | `be27e89` | Grafana 13 Fix: kiosk=tv -> kiosk=1 (v13.2 akzeptiert nur noch '1'/'true' als Kiosk-URL-Wert, 'tv'/'full' entfernt -> Dashboard... |
| v0.0.130 | `5bdb95f` | v0.0.126: Titel fester 'STARFACE Anlagen-Detail', Installation als Untertitel (Direktaufruf ohne var zeigt keinen rohen Platzha... |
| v0.0.129 | `74247eb` | v0.0.125: TV-Kiosk - Links auf ?kiosk=tv (obere Grafana-Leiste ausgeblendet) + Datalink live |
| v0.0.128 | `5542c3a` | v0.0.124: Kiosk-Sicherheit - installation-Variable auf hide:2 in allen 3 Grafana-Dashboards (Anlagen-Dropdown entfernt, Links f... |
| v0.0.127 | `955ce28` | v0.0.123: Kiosk-Modus für alle Grafana-Dashboard-Links |
| v0.0.126 | `79cd9d8` | v0.0.122: Admin-Uebersicht-Link (starface-admin-uebersicht) auf Monitoring (nur Admin) + Admin-Einstellungen-Karte; Tests 16/16 |
| v0.0.125 | `a487e46` | v0.0.121: Admin-Einstellung Grafana-Basis-URL (settings-Tabelle, /admin Einstellungen, Prioritaet Admin-Env-Default in _grafana... |
| v0.0.124 | `5c51d31` | v0.0.120 (Nachtrag): Grafana-Dashboard-Link auch auf Dashboard-Startseite je Anlagen-Karte (Icon-Button rechts, rechtegefiltert... |
| v0.0.123 | `a502cae` | v0.0.120: Monitoring-Seite /monitoring fuer alle eingeloggten User, rechtebasiert (can_read; Admins alle) + Grafana-Detail-Link... |
| v0.0.122 | `860a027` | Grafana: 3 Dashboards (Global mit Datalinks, Detail je Anlage via Variable, Admin-Uebersicht mit Ausfall-Zaehlung) - alle 30 Pa... |
| v0.0.121 | `06214a7` | Grafana-Dashboard 'STARFACE Telefonie-Monitoring' (deploy/grafana/, 11 Panels): via Admin-API deployed, alle 8 Panel-Queries ge... |
| v0.0.120 | `d8464b6` | App-Wiki: v0.0.119 + Modul v4 in Versionsregister nachgezogen (starface-anrufblocker.md) |
| v0.0.119 | `95266ab` | TelefonieMonitoring v4 + WebApp rsplit: Root-Cause 'immer getrennt' = Provider-Name aus Wire-Settings ('register=>user:pass@hos... |
| v0.0.118 | `527f665` | Monitoring-Status-Fix: Modul v3 (dnsmgr-Spalte in sip show registry - State/User spalten-unabhaengig erkannt, bewiesen gegen ec... |
| v0.0.117 | `c9488f3` | Monitoring: Provider-Badge-Text eindeutig - rot zaehlt getrennte Provider (x von y), gruen mit Anzahl; Render-Test angepasst |
| v0.0.116 | `00c21a9` | App-Wiki: Versionshistorie (Modul v1/v2 + Web-App v0.0.105-v0.0.115) im Monitoring-Artikel wie beim Anrufblocker; Projektplan-S... |
| v0.0.115 | `c9b9be6` | Monitoring-Seite: Provider-Status als Badge (gruen=alle Registered, rot=Provider getrennt mit Details im Tooltip, grau=keine Da... |
| v0.0.114 | `fcc7bcb` | Footer: Versionsnummer global (TEMPLATES.env.globals['version']) - fehlte auf Routen ohne version-Uebergabe (z.B. /admin/monito... |
| v0.0.113 | `b01b27b` | App-Wiki: Versionsverweis im modul-designer-Artikel aktualisiert (v0.0.97 -> v0.0.112, Base-Layout+Monitoring) |
| v0.0.112 | `5a8663f` | App-Wiki: Versionsregister im Anrufblocker-Artikel um v0.0.105-v0.0.111 ergaenzt (Monitoring-Stack, Statusseite, Base-Layout) |
| v0.0.111 | `d4d7edd` | base.html: Wiki-Link nur fuer Admins (Route /wiki ist admin-only, Nicht-Admins sehen keine toten Links) |
| v0.0.110 | `7b6ee15` | Templates: gemeinsames base.html (Header/Nav/Footer zentral, Monitoring-Link jetzt auf ALLEN Seiten) - alle 11 Seiten auf exten... |
| v0.0.109 | `77beb66` | Admin: Monitoring-Statusseite (/admin/monitoring) mit Sammler-Status + letzten Werten je Installation; Nav-Link in allen Templa... |
| v0.0.108 | `00a6354` | TelefonieMonitoring v2: functionCall-Output-Namen an Java-Output-Feldnamen angeglichen (fix: Import-Fehler 'Output variable not... |
| v0.0.107 | `3ef44fc` | Edit Anlage: eigenes Feld 'Monitoring-Modul-Instanz' fuer den Sammler |
| v0.0.106 | `c5ae22c` | Wiki: Admin-Seite starface-telefonie-monitoring (Modul-Import + Sammler-Betrieb) + Test 6 Seiten |
| v0.0.105 | `d9cfc15` | Telefonie-Monitoring v1: Module + WebApp-Sammler (InfluxDB) |
| v0.0.104 | `a159aa2` | docs(wiki): ZimaOS-Hinweis für Telefonie-Monitoring-Stack (CasaOS-Format, Token-Platzhalter, Provisioning-Pfad) |
| v0.0.103 | `fcb81d6` | feat(ops): Stack-Vorlage Telefonie-Monitoring — docker-compose um Grafana (8894) + InfluxDB (intern) erweitert, .env.example + ... |
| v0.0.102 | `95a4e24` | docs(wiki): XML Monitoring v152 Vollanalyse — Descriptor-Verdrahtung (Lifecycle-Ketten, GUI-Variablen, RPC-Wrapper), CheckMk/XM... |
| v0.0.101 | `32b0a7a` | docs(wiki): neues Projekt 'Module - Reverse Engineering' — XML Monitoring v152 komplett rekonstruiert (Checkmk-/XML-Output, DI-... |
| v0.0.100 | `d1ce136` | docs(webapp-wiki): Tagging-Hinweis (jeder Push = neues v0.0.x-Tag) im Betriebs-Abschnitt |
| v0.0.99 | `3c7cc5c` | docs(webapp-wiki): Versionsregister bis v0.0.97 + Verweis v0.0.92→v0.0.97 in starface-modul-designer |
| v0.0.98 | `9abdbd6` | feat(admin): Comboboxen mit Suchfeld für Rechte-Dropdowns (User/Anlage/Filter, ab 3 Zeichen, keine Vorauswahl, gleiche Breite) ... |
| v0.0.97 | `8159c91` | feat(admin): Tabellen-Filter (Name/URL/Version ab 3 Zeichen, Dropdowns) + Einklappen mit localStorage — inkl. CDP-Browser-Test ... |
| v0.0.96 | `2bf6b31` | style(all): Scrollbars app-weit einheitlich ans Dark-Design angepasst (WebKit + Firefox) — wie im Wiki |
| v0.0.95 | `8d40d9f` | style(wiki): Scrollbars an das Dark-Design anpassen (WebKit + Firefox) — dezente runde Thumbs statt nativer heller Balken |
| v0.0.94 | `9ab0669` | feat(wiki): Admin-Wiki (Stufe 3) — Markdown-Renderer mit TOC, Wikilinks, Volltextsuche; 3 Seiten (Anrufblocker, Modul-Designer,... |
| v0.0.93 | `e996b9a` | test(dashboard): Regressionstest Badge v9/v10+ (badge_e2e.py) — Deckt Key-Mismatch is10/is_starface10 ab |
| v0.0.92 | `02ff541` | fix(dashboard): Badge zeigte immer v9 — Route übergab 'is10', Template las 'is_starface10' (seit Initial-Commit) |
| v0.0.91 | `e467cc4` | modul v28: CallBlocker nach Blacklist-v64-Muster — GetCaller → foreach SimpleMatch → Hangup + Log |
| v0.0.90 | `8f6cf9c` | webapp: Header/Menü vereinheitlicht — api_doku an Standard angeglichen, password api-doku-Link ergänzt |
| v0.0.89 | `f715f16` | webapp: Header + Menü fixiert (sticky .header-wrap) auf allen Seiten |
| v0.0.88 | `e93e846` | v27: Logging NUR über dokumentierten Log2-Baustein — getLog() raus |
| v0.0.87 | `5e880de` | v26: Logs in das MODUL-Log umgestellt (Log2-Baustein statt nur Log4J) |
| v0.0.86 | `e25cd0a` | v25: Diagnose-Logs — jeder Schritt im Anrufpfad wird geloggt |
| v0.0.85 | `ee2350d` | webapp: API-Referenz-Seite — Favicon ergänzt + Fußzeile fixiert (wie dashboard/blocklist/admin) |
| v0.0.84 | `597b372` | v24: Anruf-Blockierung via STARFACE-SimpleMatch-Baustein statt selbstgebautem Matcher |
| v0.0.83 | `12a42b9` | fix(module): v23 — ListAdd hängt Nummern an statt Liste zu überschreiben |
| v0.0.82 | `8489104` | feat(blocklist): Ändern-Button pro Eintrag + Route /blocklist/update (v0.0.73) |
| v0.0.81 | `8fe98d6` | fix(repo): module-descriptor.xml (v22) wiederhergestellt — Quelldatei wurde bei der sfm-Verifikation versehentlich gelöscht |
| v0.0.80 | `1ee13b9` | fix(modul): textList-Sync über ListResource-ID aus variable.getValue() (Editor-Weg, bytecode-bewiesen aus MultiValueConfig/Conf... |
| v0.0.79 | `9cb1506` | fix(modul): Tab-Sync über textList-ListResource (getListResource/setValues) statt Variable — bytecode-bewiesen aus MultiValueCo... |
| v0.0.78 | `6e3d526` | feat(admin): API-Doku als WebApp-Template mit Gruppen-Menü + Suche; API-Doku-Link in allen Navs (Admin); Standalone-HTML entfer... |
| v0.0.77 | `22e364f` | feat(admin): STARFACE-API-Doku (323 Funktionen, standalone HTML) unter /admin/api-doku — nur Admins (v0.0.72) |
| v0.0.76 | `048b78a` | fix(modul): textList-Eintraege via Variable.setPossibleValues(List) statt setValue(String) — v19 enthielt alten Bytecode (javac... |
| v0.0.75 | `37c3844` | fix(modul): textList-Sync setzt LIST-Wert (java.util.List) statt String — Widget rendert nun die Einträge (v19) |
| v0.0.74 | `43325c5` | modul v18: Sync über Instanz-inputVars (setInputValue/getInputVar) statt findVisibleVariable (Sichtliste leer bei accessRights=... |
| v0.0.73 | `85c7268` | modul v17: Sync-Diagnose — ID-Fallback + Log aller sichtbaren Instanz-Variablen bei Nichtfinden (commit c76ccdb-Nachfolger) |
| v0.0.72 | `ece2713` | fix(ui): Leeres Blocklist-Formular abfangen — Frontend-Validierung (trim-Check + Meldung) + Backend-Default statt Pydantic-422 ... |
| v0.0.71 | `ece2713` | fix(ui): Leeres Blocklist-Formular abfangen — Frontend-Validierung (trim-Check + Meldung) + Backend-Default statt Pydantic-422 ... |
| v0.0.70 | `c76ccdb` | Modul v17: Persist-Sync — blocklist.txt → Instanz-Konfig (InvocationInfo.getModuleInstance + Variable.setValue + ModuleInstance... |
| v0.0.69 | `5264ff4` | Modul v16: Tab 'Geblockte Rufnummern' im kanonischen STARFACE-10-Format (aus Designer-Export abgeleitet): GUI-Variable GUI_GEBL... |
| v0.0.68 | `e91eab6` | Modul v15: fix inputGUITabs-Feldformat (DATEV-konform: defaultValue/elements/listName/propertyName-ResourceKeys) — behebt Fehle... |
| v0.0.67 | `232a11f` | Modul v14: feature — Tab 'Geblockte Nummern' in Modul-Instanz (Descriptor inputGUITabs + GUI_BLOCKED_NUMBERS-List-Variable); Sy... |
| v0.0.66 | `bcda280` | Modul v13: fix(CallBlocker) Nummern-Format-Normalisierung (0049/+49/0/49 gleichwertig) + fuehrende Stern-Wildcard (*49...) + Bl... |
| v0.0.65 | `9a07d45` | Modul v12: fix: Wrapper-Output-"<value>" Defaults geleert — Root Cause 'Variable referenced in variable OUTPUT_ANZAHL not found' |
| v0.0.64 | `c1110eb` | Modul v11: wrapper outputVars names NUMMERN/ANZAHL → INPUT_NUMMERN/OUTPUT_ANZAHL — vermeidet STARFACE-Konflikt mit Java-Funktio... |
| v0.0.63 | `cf12687` | Modul v10: fix: Wrapper outputVars names NUMMERN/ANZAHL → INPUT_NUMMERN/OUTPUT_ANZAHL — behebt 'Variable referenced in variable... |
| v0.0.62 | `91911da` | Modul v9: fix: functionCall variable valueByReference false → true — behebt Import-Fehler 'Variable referenced in variable ANZA... |
| v0.0.61 | `32d0478` | Modul v8: RPC-Wrapper-Funktionen nach XmlMonitoring-Muster — rpcEntryPoints zeigen auf Designer-Wrapper (ListGetRpc/ListAddRpc/... |
| v0.0.60 | `c75710d` | Debug: RAW-XML-Antwort von STARFACE im Docker-Log |
| v0.0.59 | `d655cd7` | Fix: _xmlrpc() fehlender return-Statement — NoneType-Crash beim Laden der Blocklist |
| v0.0.58 | `b265b87` | Debug: Print XML-RPC-Antwort in Docker-Log beim Speichern |
| v0.0.57 | `45f2537` | Modul v7: Neu kompiliert mit JDK 21 — frische .class-Dateien im .sfm |
| v0.0.56 | `c865e33` | Modul v6: rpcEntryPoints ListGet/ListAdd/ListRemove im Descriptor — Import ohne manuelle Freigabe |
| v0.0.55 | `5175580` | Modul v5: Firmenmuster-Umbau — Bausteine + Call-Processing-Entrypoint automatisch im Descriptor |
| v0.0.54 | `ce709f8` | feat(module): CallBlocker v4 — Sichtbarkeit + korrekter Instanz-Pfad |
| v0.0.53 | `ed3d15c` | fix(rpc): XML-RPC-Faults erkennen statt verschlucken — keine falschen Erfolgsmeldungen mehr (v0.0.53) |
| v0.0.52 | `ccd889c` | feat(module): module_instance_name Feld + RPC-Präfix [Instanzname].[EntryPoint] (v0.0.52) |
| v0.0.51 | `de15830` | fix(module): writeHash=sha1(id) statt leer — Passwortschutz wirklich behoben (v0.0.51) |
| v0.0.50 | `8e0a23b` | fix(module): v0.0.50 — Version=2, writeHash leer, entryPoints leer (v0.0.49 rpcEntryPoint-Code entfernt) |
| v0.0.49 | `3c1a41d` | feat(module): RPC-Entrypoints im Descriptor (v0.0.49) |
| v0.0.48 | `f33b3ea` | feat(dashboard): Verbindungstest als Popup statt neuer Seite (v0.0.48) |
| v0.0.47 | `cc19ce6` | revert(auth): Password Grant mit rest-client-headless (Primärweg) — OIDC/Authorization-Code-Flow deaktiviert |
| v0.0.46 | `f9b1ffe` | fix(auth): OAuth-Endpoints aus OIDC-Discovery + Scope pbx-login (v0.0.46) |
| v0.0.45 | `eee8f44` | fix(auth): OAuth-Flow Fehler behoben — kein 500 mehr (v0.0.45) |
| v0.0.44 | `278ce1b` | feat(auth): Authorization Code Flow mit PKCE für rest-client (v0.0.45) |
| v0.0.43 | `abb2ac5` | fix(auth): Basic-Auth ohne client_id im Body (400-Fix) + Secret-Fehler-Erkennung (v0.0.43) |
| v0.0.42 | `85d28ad` | fix(auth): v10 OAuth sauber — kein v9-Fallback, Refresh-Token-Persistenz (v0.0.42) |
| v0.0.41 | `3bdcf75` | fix(auth): v10 OAuth mit Basic-Auth + Legacy-Fallback (v0.0.41) |
| v0.0.40 | `fbc76f6` | fix(url): _ensure_url in starface_token + _xmlrpc — URL ohne http(s) wird zu https:// |
| v0.0.39 | `c963445` | feat(admin): Edit-Installation + Test-Conn (v0.0.39) |
| v0.0.38 | `e9396e1` | fix(module): korrekte noLicenseId-Formel + writeHash leer — Lizenz & Passwortschutz (v0.0.38) |
| v0.0.37 | `3a89b6d` | fix(module): noLicenseId in Descriptor — 'Unzureichende Modullizenz' behoben |
| v0.0.36 | `cec9e39` | fix(modules): URL-Level Cache-Busting für Download (v0.0.36) |
| v0.0.35 | `958bdea` | fix(modules): eindeutiger Download-Dateiname mit Datei-Hash (v0.0.35) |
| v0.0.34 | `ea16593` | feat(modules): Versionierung auf Modul-Seite + Download-Cache-Fix (v0.0.34) |
| v0.0.33 | `49490e8` | fix(module): .sfm im STARFACE-10-JAR-Format — META-INF/MANIFEST.MF (ObjectId + StarfaceModule_SpecVersion=5) fehlte; Import bra... |
| v0.0.32 | `0900ae9` | fix(a11y): autocomplete-Attribute an allen Formularfeldern — Chrome-Issue 'An element doesn't have an autocomplete attribute' weg |
| v0.0.31 | `6995eb2` | fix(a11y): ECHTE Label-Verknüpfung statt aria-label — Chrome 'No label associated' erfordert label[for] (sr-only, 13 Felder) |
| v0.0.30 | `aaed37f` | fix(a11y): Formularfelder mit Labels verknüpft — DevTools 'No label associated with a form field' weg (aria-label, 13 Felder) |
| v0.0.29 | `8eb01b0` | Fix: iOS-Zoom — echte Inputs/Textareas auf font-size:16px (v0.0.28 traf nur nav-open-Checkbox) |
| v0.0.28 | `3b12e5e` | Mobile-Fix: iOS-Zoom verhindern — alle Inputs font-size:16px |
| v0.0.27 | `a9b30a3` | PWA-Icons: quadratisches STARFACE-Stern-Icon (icon-192/512, apple-touch-icon) |
| v0.0.26 | `f30bd01` | Revert: Header/Login-Logo wieder Krämer (kits-logo.png), nur Favicon+PWA-Icon STARFACE |
| v0.0.25 | `dfb45bd` | Header-Logo: STARFACE-Markensymbol (icon-192) statt breiter Wortmarke (logo.svg) |
| v0.0.24 | `df25981` | Favicon: STARFACE-Icon statt Krämer-Logo (logo.svg, favicon.ico, apple-touch-icon) |
| v0.0.23 | `243736e` | Mobile admin: Tabellen-Buttons klein lassen, Formular-Buttons auf volle Breite |
| v0.0.22 | `26af919` | Mobile: Safe-Area nur EINMAL zählen — html-Padding entfernt, Footer-Bottom ergänzt |
| v0.0.21 | `e58c815` | Mobile: Safe-Area Fix — html padding-top + topbar padding in Media Query |
| v0.0.20 | `d1617b9` | Mobile: Safe-Area-Insets für iOS Notch/Dynamic Island |
| v0.0.19 | `815a240` | Mobile-Responsive + PWA-Fähigkeit (Hamburger-Menü, Service Worker) |
| v0.0.18 | `fb6c26e` | docker-compose.yml vervollständigt: ENV-Variablen + Docker-Hub-Image :latest |
| v0.0.17 | `24cdd03` | Einheitliches Nav-Menü + Admin-Badge auf allen Seiten |
| v0.0.16 | `32181de` | Module-Link in allen Topbars ergaenzt (Admin sichtbar) |
| v0.0.15 | `73ed0b9` | Modul-Verwaltung: Admin-Seite zum Download der .sfm-Dateien (Variante A) |
| v0.0.14 | `9ca86b1` | Footer: kein Verdecken auf allen Seiten (einheitlich 60px Puffer) |
| v0.0.13 | `809aaf9` | Admin-PW-Reset: Redirect zurück zum Admin + Footer verdeckt Rechte-Liste nicht mehr |
| v0.0.12 | `a362e72` | Passwort-Funktion neu strukturiert: Header-Link nur eigenes PW, Admin-Reset in User-Liste |
| v0.0.11 | `4ebfd1d` | Login-Name zurück auf 'STARFACE WebApp' (nur Logo war beauftragt) |
| v0.0.10 | `b14e6d0` | Footer (Version) auf allen Seiten + Passwortänderung (Admin für alle, User nur selbst) |
| v0.0.9 | `dadb63c` | Logo (kraemer-it.de) + Admin-Rollen-Änderung mit Letzter-Admin-Schutz |
| v0.0.8 | `6d2ff31` | Dashboard-Footer fixiert am unteren Bildschirmrand (position: fixed) |
| v0.0.7 | `f2176fe` | Dashboard: Versionsnummer in der Fußzeile (APP_VERSION-Env) |
| v0.0.6 | `bebdfa7` | Login: 2-Schritt-Flow nach Atlas-Muster (AJAX + pending_token) |
| v0.0.5 | `814b76b` | Fix: 2FA-Setup Route GET statt POST + Pillow in Requirements |
| v0.0.4 | `4b4561b` | Favicon + App-Icons: offizielles STARFACE-Logo |
| v0.0.3 | `8f01fab` | Dashboard: Admin-Link in Topbar + 'Anlage hinzufügen'-Button + Empty-State-Hinweis |
| v0.0.2 | `13f87b5` | README: lokalen Wiki-Pfad durch module/README.md-Verweis ersetzt |
| v0.0.1 | `801e7e6` | Initial: STARFACE CallBlocker Modul + Verwaltungs-WebApp |

> Legende/Details: Lange Fachtexte zu Monitoring (v0.0.119 ff.) stehen im Hermes-Wiki
> ([[telefonie-monitoring]]-Entity), zu Updates (v0.0.164 ff.) in [modul-auto-update](modul-auto-update.md).

## Passkeys / WebAuthn (F58)

**Stand (2026-08-28): umgesetzt — Option „B mit C-Schalter"** (Passkey als zusätzliche
Login-Methode; Passwort-Login per Env-Flag abschaltbar).

### Funktionsumfang
- **Login:** „Mit Passkey anmelden" auf der Login-Seite plus **Conditional UI**
  (Autofill-Vorschlag) — passwortlos über Windows Hello, Face ID, Fingerabdruck
  oder Sicherheitsschlüssel (Discoverable Credentials, keine Usernamen-Eingabe).
- **Verwaltung:** Admin → Benutzerliste → „Passkeys" (je Benutzer): Geräte-Liste,
  hinzufügen (mit Gerätename), löschen (Widerruf).
- **Sicherheit:** ES256 (attestation `none`), challenge single-use + 5-Min-TTL,
  `sign_count`-Monotonie (Replay-Schutz), Origin-Check gegen `WEBAUTHN_ORIGIN`.
- **C-Schalter:** `WEBAUTHN_PASSWORDLOGIN=0` → Passwort-Login deaktiviert
  (Login-Seite zeigt nur noch Passkey; `/api/login` → 403). Erst mindestens einen
  Passkey registrieren, dann Flag setzen — sonst Lockout-Sperre (503 mit Hinweis).

### Konfiguration (Env)
```yaml
WEBAUTHN_RP_ID: <domain>                # z. B. webapp.example.de (ohne Protokoll)
WEBAUTHN_ORIGIN: https://<domain>       # muss exakt der Browser-URL entsprechen
WEBAUTHN_RP_NAME: STARFACE WebApp        # optional, Anzeigename im Authenticator
WEBAUTHN_PASSWORDLOGIN: "1"              # "0" = nur noch Passkey-Login (C)
```
**Abhängigkeiten:** `fido2==2.2.1` **und `cbor2`** (explizit in requirements.txt — ohne cbor2
setzt die App `FIDO2_OK=False` → „Passkeys sind nicht konfiguriert." (v1.0.3-Fix).
**Browser-Format:** Server liefert `challenge`/`user.id` als Base64URL; das JS dekodiert sie zu
Byte-Arrays, bevor es `navigator.credentials.create/get` aufruft (v1.0.6-Fix — sonst
DOMException „Invalid 'user.id' length").

### Technik
- Bibliothek: **fido2 2.2 (Yubico)** in `requirements.txt`; nur Verifikation,
  Options-JSON erzeugt die App selbst (WebAuthn-Level-2-Struktur).
- fido2 2.2/OpenSSL erwartet ES256-Signaturen in **DER-Form** — die App wandelt
  RAW r||s (Browser) → DER (`_raw_to_der_b64`).
- **Hinweis:** Passkeys funktionieren nur über **HTTPS** (NPM-Domain). Ohne
  `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` bleibt das Feature deaktiviert
  (kein Button, API 503) — der C-Schalter blockt dann mit 503 statt Lockout.
- Testabdeckung: `tmp_tests/passkeys_test.py` (14 Checks, echter Krypto-Flow mit
  Software-Authenticator `tmp_tests/webauthn_fake.py` inkl. Replay-Schutz).

