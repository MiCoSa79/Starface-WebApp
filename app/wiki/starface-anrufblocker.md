---
title: STARFACE Anrufblocker (Modul + Verwaltungs-Web-App)
description: Anrufblocker-Modul (Blacklist-Anrufabweisung) + Multi-User-Web-App zur Listenpflege — Architektur, Betrieb, Versionshistorie.
updated: 2026-08-25
---

# STARFACE Anrufblocker

**Status: umgesetzt und live.** Modul **v28** (Anruf-Block E2E bestanden, Logbeleg
`BLOCKED: Anruf von ... abgewiesen`) + Web-App, GitHub-Repo `MiCoSa79/Starface-WebApp`,
CI → Docker Hub (`micosa79/starface-webapp`), Port 8895.

Zwei Komponenten, die zusammen unerwünschte Anrufe (Spam/Werbung) abweisen:

1. **STARFACE-Modul „Anrufblocker"**: Ein Call-Processing-Modulbaustein
   (`IAGIJavaExecutable`) mit eingebauter Rufnummern-Blacklist. Eingehende Anrufe
   werden gegen die Liste geprüft; bei Treffer wird der Anruf abgewiesen und ein
   Logeintrag erzeugt. Die Liste liegt als **textList-ListResource in der
   Modul-Instanz** (Tab „Geblockte Rufnummern" im Instanz-Editor, vom Nutzer
   explizit so gewünscht, nichts extern).
2. **Verwaltungs-Web-App** (Multi-User): pflegt die Blacklists über die
   XML-RPC-API der Anlagen — ohne je auf die Anlage aufgeschaltet zu werden.
   Mehrere STARFACE-Anlagen, Benutzer-Login, TOTP-2FA, Rechteverwaltung.

Entwicklungs-Grundlage: Community-Doku von SI-Solutions (wiki.si-solutions.ch,
GitHub-Mirror `Fabian95qw/SFWiki`) — Details siehe
[[starface-modul-designer]].

## Funktionsweise Modul (Stand v28)

- **Einstieg:** AGI-Kernel-Entrypoint („on all incoming calls") auf einer
  Private-Wrapper-Funktion `CallBlockerEntry` — die Java-Funktion `CallBlocker`
  bekommt die Blocklist als `@InputVar Blocklist` (`VariableType.LIST`,
  `List<String>`) per Descriptor-Verdrahtung (`valueByReference` auf die
  Modul-Ebene-Variable `GUI_GEBLOCKTE_RUFNUMMERN`).
- **Prüfung:** `GetCaller2`-Baustein → `callerSignallingNumber` → **foreach**
  über die Blocklist → pro Eintrag der **Original-Baustein `SimpleMatch`**
  (RAW-Vergleich, keine Normalisierung — exakt die Semantik des Referenzmoduls
  „Blacklist v64").
- **Abweisen:** Bei Treffer `Hangup`-Baustein (ohne Channel) + `Log2`-Log
  `BLOCKED: Anruf von <Nummer> abgewiesen`. Bei Nicht-Treffer bleibt die Route
  unangetastet.
- **Wichtig (Live-Befund):** Die Anlage liefert die Caller-ID im **0049-Format**
  — Muster `*49...` decken das über die `*`-Wildcard ab
  (Logbeleg: `BLOCKLIST-MATCH: Muster '*491627876643' traf auf '00491627876643'`).

## Web-App: Architektur

- **Stack:** FastAPI + SQLite + Jinja2, Docker-Container auf ZimaOS hinter NPM
  (ZimaHost-IP:Port, nicht Container-IP). Schlank, Backup = eine DB-Datei.
- **Sicherheit:** Passwörter bcrypt; Sessions HttpOnly; Login-Rate-Limit;
  **2FA = TOTP** (Authenticator-kompatibel) + 10 Einmal-Backup-Codes;
  Anlagen-Zugangsdaten **verschlüsselt** in der DB (Fernet, Master-Key nur im
  Container via Env); erster Admin-Account beim ersten Container-Start aus
  Env-Variablen.
- **API-Zugriff serverseitig:** Der Server macht die XML-RPC-Calls — Browser-CORS
  würde Direktzugriffe auf die Anlage blockieren; Zugangsdaten bleiben im Server.
- **Oberfläche:** Listen-Anzeige, Nummern hinzufügen (mehrere auf einmal) /
  ändern / löschen, Verbindungstest-Button pro Anlage, Modul-Download-Seite,
  Admin-Wiki (diese Seiten), Footer mit Versionsnummer, Passwort-Änderung
  (Admin für alle, User nur selbst), KITS-Logo.
- **XML-RPC-Auth (versionsabhängig):**
  - **STARFACE 10+:** JWT via OAuth (Authorization Code Flow mit PKCE oder
    Password Grant, `/auth/realms/pbx/oauth2/token`, `client_id=rest-client`,
    Login-ID + Passwort + Client-Secret aus Admin-UI → Server → Status →
    REST-API); Refresh-Token wird automatisch verwendet.
  - **≤ 9.x:** Legacy-Token `Login:sha512(Login + "*" + sha512(Passwort))`
    (das `*` ist ein Zeichen, kein Operator).
- **DB-Schema:** `installations` (inkl. `is_starface10` = Login-Methode,
  `module_instance_name` = XML-RPC-Präfix `[Instanzname].[EntryPoint]`),
  `users`, `access` (Rechte pro Anlage), `oauth_auths`, `modules`.

## Betrieb (Web-App)

- Container: ZimaOS, Port 8895, Image `micosa79/starface-webapp:latest`.
  **Update nur per `docker compose pull && docker compose up -d`** — ein alter
  Container zeigt altes Verhalten.
- **Versionierung:** Die CI vergibt bei **jedem** Push automatisch ein neues
  `v0.0.x`-Tag — auch reine Wiki-Updates erhöhen die Nummer. Der aktuelle
  Feature-Stand steht im Versionsregister unten.
- **Stolperstein docker-compose:** `./config.json:/app/config.json` nur mounten,
  wenn die Datei existiert — sonst Container-Crash (Fehler in v0.0.18). Keine
  persönlichen Daten in der compose-Datei (Beispielwerte für FERNET_KEY/ADMIN_*).
- Admin-Bereich unter `/admin` (ab v0.0.3 Topbar-Link). Erster Admin wird beim
  ersten Start aus `ADMIN_USERNAME`/`ADMIN_PASSWORD` angelegt.
- Versionsnummer im Footer aus `APP_VERSION`-Env (CI-Docker-Build-Arg).
- Letzter Admin kann nicht entlassen werden („Es muss immer mindestens ein
  Admin geben").

## Modul-Entwicklung: Verweise

- [[starface-modul-designer]] — Anleitung: Bausteine, Descriptor, XML-RPC, Stolpersteine.
- [[starface-modul-paketierung]] — `.sfm` als JAR bauen (Manifest, ObjectId, SpecVersion).

## Versionshistorie (kompakt)

### Modul

| Version | Datum | Inhalt |
|---|---|---|
| v28 | 2026-08-25 | **Blacklist-v64-Muster:** GetCaller2 → foreach über Modul-Liste → SimpleMatch → Hangup + Log2; Entrypoint-Wrapper `CallBlockerEntry` (Modul-Ebene-Variable per UUID, exakt Blacklists Verodrahtung). **LIVE-TEST BESTANDEN.** |
| v27 | 2026-08-25 | Logging NUR über **Log2** (einziger dokumentierter Log-Baustein); Log4J-Fallback entfernt. |
| v26 | 2026-08-25 | Logs auf **Log2**-Baustein umgestellt (Modul-/Instanz-Log) + Log4J-Fallback. |
| v25 | 2026-08-25 | Diagnose-Logs je Anrufschritt (RAW-Nummer, normalisiert, Muster, Vergleichsergebnis). |
| v24 | 2026-08-25 | Anruf-Vergleich auf **Original-SimpleMatch** umgestellt (wie Blacklist v64); selbstgebaute Wildcard-Logik entfernt. Bytecode-Beweis: `pattern = RegExpUtil.convertSimpleRegexpToJava(pattern)`, `text.matches(pattern)`; `*` = 0..n, `?` = genau 1, kompletter Match. |
| v23 | 2026-08-25 | **ListAdd-Overwrite-Fix:** anhängen statt ersetzen (load → deduplizieren → save volle Liste). |
| v22 | 2026-08-25 | **textList-Sync über ListResource-ID aus `variable.getValue()`** — blocklist.txt komplett entfernt; Zwei-Richtungs-Sync (WebApp ↔ Instanz-Editor) bestanden. |
| v21 | 2026-08-25 | Tab-Sync über textList (falscher Schlüssel: Variablenname statt Resource-ID) — WIDERSPRUCH, in v22 korrigiert. |
| v16 | 2026-08-24 | Tab im kanonischen STARFACE-10-Format nach Designer-Export; `GUI_GEBLOCKTE_RUFNUMMERN`, textList ohne resourceKeys, defaultValue Pflicht. |
| v14 | 2026-08-24 | Feature: Tab „Geblockte Nummern" in der Modul-Instanz (inputGUITabs + textList). |
| v13 | 2026-08-24 | Anruf-E2E-Fix: Format-Normalisierung + führende Stern-Wildcard (Anlage liefert `0049...`). |
| v12 | 2026-08-24 | **Import-Fehler ROOT CAUSE:** Wrapper-Output-`<value>` geleert (jedes nicht-leere Output-value = Variablen-Referenz, `ExecutableObject.validate()`); `verify_descriptor_refs.py` etabliert. |
| v8 | 2026-08-24 | RPC-Wrapper-Funktionen nach XmlMonitoring-Muster (Parameter kommen sonst nicht an) + `<double>`-Parser-Fix. |
| v4 | 2026-08-24 | Korrekter Instanz-Pfad `IRuntimeEnvironment.getInstanceDataDir()` statt `getenv(STARFACE_MODULE_ID)` + Logging. |

Modul-Historie v4–v28 vollständig (inkl. UUIDs und Commit-Hashes) im Repo
`module/` und im Hermes-Wiki; hier die fachlichen Kernpunkte.

### Web-App

| Version | Inhalt |
|---|---|
| v0.0.133 | **Kiosk-Footer-Fix: `&hideLogo` blendet den sticky „Powered by Grafana“-Footer aus** (Commit `9e44f1b`, Tag verifiziert `v0.0.133`): Nutzer-Screenshots (scrollbarer Kiosk) zeigten den Branding-Footer unten rechts fest am Viewport klebend — er „scrollt mit“ und hängt mitten im Bild. Root Cause: PR **grafana/grafana#115202** („Add Grafana branding footer when in kiosk mode“, merged 2026-01-24) verankert den Footer absichtlich im Kiosk-Modus; offizielles Opt-out = URL-Param **`hideLogo`** (auch `hideLogo=true`/`1`; `=false`/`0` erzwingt Anzeige). Fix: alle 4 WebApp-Links + Global-Datalink `&kiosk=1` → `&kiosk=1&hideLogo`; E2E 16/16 (Assertions jetzt auf `kiosk=1&hideLogo`, sonst Substring-Lücke); Screenshot-Beweis: `kiosk=1&hideLogo` → kein Footer. Live-Deploy Global **v9** (11 Panels, `hide: 2` unverändert, Datalink verifiziert). |
| v0.0.131 | **Grafana-13-Fix: `kiosk=tv` → `kiosk=1` (Kiosk ging gar nicht mehr):** Nutzer: „Link aus der Starface-WebApp → immer noch das komplette Dashboard.“ Befund (nicht geraten, JS-Beweis aus dem Bundle der laufenden Grafana **v13.2.0**, Chunk `6540…`): `setKioskModeFromUrl` akzeptiert als URL-Werte NUR noch `"1"`/`true` → `KioskMode.Full`; `"tv"`/`"full"`/leer werden im switch nicht mehr gematcht → **kein Kiosk-Modus** (seit dem Nav-Umbau in Grafana 13 entfernt; `getKioskUrlValue` kennt nur noch `Full`). Fix: alle 4 WebApp-Link-Stellen (dashboard/monitoring/admin) + Global-Datalink auf `&kiosk=1` (= Vollbild-Kiosk, `chromeless`, obere Leiste samt Toolbar weg). E2E 16/16 grün; Global-Dashboard live deployed (Version 8; 11 Panels + `hide:2` unverändert, Datalink verifiziert). **Nutzer-Aktion:** WebApp-Image auf Board auf v0.0.131 ziehen (stop/rm/rmi + up -d). |
| v0.0.126 | **Titel-Kosmetik fuer Direktaufruf (Nachtrag zu v0.0.125):** Nutzer-PC-Screenshot zeigte den Dashboard-Titel mit unaufgeloestem Variable-Platzhalter `${installation}` — tritt beim Grafana-Direktzugriff ohne `?var-installation=` auf. Fix: Titel fest auf **STARFACE Anlagen-Detail**, Installation wandert in die Beschreibung (`Anlage: ${installation}`) — live deployt (Version 3). Hinweis: Volle Grafana-Oberflaeche beim Direktzugriff (Root/Liste) ist gewollt (Admin-Arbeitsplatz); die Kiosk-Ansicht (`?kiosk=tv` → ab v0.0.131 `?kiosk=1`) gilt nur fuer die Links aus der WebApp. |
| v0.0.125 | **TV-Kiosk-Modus (obere Leiste auch weg):** Nutzer-Screenshot zeigte: bei `?kiosk` bleibt die obere Grafana-Leiste (Zeitleiste, Refresh, Suche) sichtbar und klebt beim Scrollen als Balken mitten im Dashboard. Fix: alle 4 WebApp-Links + Global-Datalink auf `?kiosk=tv` — blendet die Dashboard-Toolbar zusaetzlich aus (Live-Deploy Global v7, Datalink verifiziert). "Powered by Grafana"-Badge unten rechts: Grafana-Standard, nicht abschaltbar. |
| v0.0.124 | **Kiosk-Sicherheit: Anlagen-Umstellung verhindert:** Nutzer meldete, dass im Kiosk-Modus oben rechts die Anlage umgestellt werden kann → jeder sähe alle Anlagen. Fix: Die `installation`-Variable ist in allen 3 Dashboards auf **versteckt** gesetzt (`hide: 2`, per API live gepatcht, Versionen 2/5/6) — das Anlagen-Dropdown ist aus dem Dashboard-View entfernt, die WebApp-Links setzen `?var-installation=<Anlage>` aber weiterhin korrekt. Damit sieht jeder Klick-User nur die per `can_read` freigegebene Anlage. **Grenze (ehrlich):** Wer die URL manuell auf `var-installation=<andere Anlage>` ändert, kann diese weiterhin sehen (Anon-Viewer bewusst offen) — harte Trennung bräuchte anon-aus + Grafana-User je WebApp-Account (separates Vorhaben). |
| v0.0.123 | **Kiosk-Modus für alle Grafana-Dashboard-Links:** Alle WebApp-Links (Startseiten-Karten, Monitoring-Zeilen, „Admin-Übersicht" auf Monitoring- UND Admin-Seite) hängen `&kiosk` an die Grafana-URL → Grafana zeigt **nur das Dashboard** (Sidebar + obere Navigation ausgeblendet, Zeitraum bleibt `from=now-6h&to=now`). Datalink im Global-Dashboard (`deploy/grafana/telefonie-monitoring.json`, „Anlage öffnen") ebenfalls um `&kiosk` ergänzt — **Deploy mit Service-Account-Token ausstehend** (Token nur transient in Prozess-Env, nie persistiert; Security-Regel). **Bewusst KEIN „Share external Link"/Public Dashboard:** (1) Public Dashboards unterstützen keine `var-installation`-Template-Variablen → Anlagen-Detail (je Anlage gefiltert) wäre unmöglich; (2) API-Zugriff ohne persistenten Token nicht möglich. Kiosk erreicht dasselbe Ziel (Dashboard pur) einheitlich für alle 3 Dashboards. E2E-Tests prüfen `kiosk` in allen gerenderten Links (16/16 grün, Live-Check der kiosk-URLs extern: 200/200/200). |
| v0.0.122 | **Admin-Übersicht-Link (Grafana `starface-admin-uebersicht`):** Nachgeholt aus der Ursprungs-Anforderung „Ein Dashboard nur für Admins" — der Link war bisher NIE in der WebApp. Jetzt: (1) Monitoring-Seite zeigt Admins einen Button **„Admin-Übersicht"** (Diagramm-SVG, neben „Zurück zum Admin", nur `{% if user.is_admin %}`); (2) Admin-Seite → Karte **Einstellungen** zeigt **„Grafana Admin-Übersicht öffnen"** (neben dem Basis-URL-Formular). Beide öffnen `{grafana_base}/d/starface-admin-uebersicht/` in neuem Tab; UIDs via Template-Kontext (`grafana_admin_uid`) aus den Routen `/monitoring` + `/admin`. E2E-Tests 13+14 (Admin sieht Link auf Monitoring, Bob nicht; /admin enthält Link). **Zum Öffnen ohne Login nötig: Anonymous-Viewer in Grafana aktivieren** (`GF_AUTH_ANONYMOUS_ENABLED=true` + `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer` im Stack-Compose, lokale Secrets-Datei — nicht im Repo) — Sonst 401 und Links führen auf die Login-Seite. |
| v0.0.121 | **Admin-Einstellung „Grafana-Basis-URL“:** Die externe Domäne, unter der Grafana erreichbar ist (z. B. NPM-Subdomain `https://monitoring.meiser.family`), ist nicht mehr nur Compose-Env — ein Admin hinterlegt sie in der WebApp: neue Sektion **Einstellungen** auf `/admin` (Formular nach der Anlagen-Tabelle), POST `/admin/settings`, gespeichert in neuer `settings`-Tabelle (key/value, `init_db`-Migration). Priorität bei der Link-Generierung (Startseite + Monitoring): **Admin-Einstellung > Env `GRAFANA_BASE_URL` > Default `http://10.0.25.60:8894`** — zentral in `_grafana_base()`, wirkt sofort (ohne Container-Restart); Feld leer = Fallback. `_get_setting`/`_set_setting`/`_grafana_base`-Helper. E2E-Tests 11+12 (Domäne wirkt auf Dashboard + Monitoring + Formularwert; Leeren → Fallback-IP). |
| v0.0.120 | **Monitoring-Seite für alle eingeloggten Benutzer + rechtebasierte Grafana-Links:** neue Route `/monitoring` (statt `/admin/monitoring`, das darauf redirectet) — zeigt nur Anlagen mit `can_read` (Admins: alle), inkl. gefilterter API `/api/monitoring/status` (vorher ungefiltert für jeden Login). Je Anlage ein dezenter Icon-Button (SVG-Liniensymbol) → Grafana-Detail-Dashboard (`/d/starface-anlage-detail/?var-installation=<Name>`); Basis-URL über neue Env `GRAFANA_BASE_URL` (Default `http://10.0.25.60:8894`). Nav-Link „Monitoring" für alle eingeloggten User (war Admin-only). Leere Liste differenziert (Admin: Sammler-Hinweis; User: Hinweis auf fehlende Lese-Rechte). **Nachbesserung (gleiche Feature-Version, neue Pushes = neue CI-Tags):** Grafana-Icon-Link **auch auf der Dashboard-Startseite** (Karten-Kopf rechts, dezenter SVG-Button, gleiche Detail-URL; Route reicht `grafana_base`/`grafana_uid` durch; Rechte wie gehabt über den bestehenden `can_read`/Admin-Filter — sichtbare Karte = leseberechtigt); „Zurück"-Link auf `/monitoring` führt für Nicht-Admins aufs Dashboard statt auf den toten Admin-Link. E2E-Tests `tmp_tests/monitoring_rechte_e2e.py` (12 Checks: Admin/Bob/Eve, Redirect, API, Nav, Dashboard-Karten+Links). |
| v0.0.119 | **Provider-Status-Parsing robust + Modul TelefonieMonitoring v4:** Root-Cause „trotz v3 immer getrennt“ = Provider-Name aus den Wire-Settings (`register=>user:pass@host:port/…`) enthält ein `=` → WebApp-Split „Name=Status“ am ersten `=` brach den Status (`>…=Registered` statt `Registered`). Modul v4 gibt jetzt saubere `user@host=State`-Namen aus (`matchRegistryLine`, Name nie aus configName) — entfernt zugleich das SIP-Kennwort aus InfluxDB-Daten (Security). WebApp splittet defensiv am letzten `=` (`rsplit` in `build_points` + `_provider_summary`); Regressionstests für „=`“-im-Namen ergänzt. Beweis per Parser-Simulation exakt gegen das Anlagen-Log → beide Provider grün. |
| v0.0.118 | **Modul TelefonieMonitoring v3 + WebApp-Status-Fix:** STARFACE setzt eine `dnsmgr`-Spalte in `sip show registry` → Status stand in Spalte 5 statt 4, Username in Spalte 3 — Modul erkennt State/User jetzt spalten-unabhängig (`extractState`/`registryUser`/`registryHost`, Registered-Token-Scan), ordnet nicht gematchte Zeilen per Reihenfolge zu und übernimmt Restzeilen direkt; behebt „alle Provider getrennt“ trotz verbunden (bewiesen gegen echtes Cloud-Log). WebApp wertet zusätzlich `Registered…`-Präfix-Toleranz. |
| v0.0.117 | **Provider-Badge-Text eindeutig:** rot zählt die GETRENNTEN Provider („Provider getrennt (2 von 2)") statt „verbunden/Zähler" (0/2 war missverständlich), grün mit Anzahl („Alle Provider verbunden (2)"). |
| v0.0.115 | **Monitoring-Seite: Provider-Status-Badges** — statt kryptischer Zeilen je Anlage ein grünes „Alle Provider verbunden" (alle `Registered`), rotes „Provider getrennt (x/y)" mit Details im Tooltip, graues „Keine Provider" ohne Daten; Auswertung zentral in `monitoring._provider_summary` (auch in der Status-API). |
| v0.0.111 | base.html: Wiki-Link nur für Admins (Route `/wiki` ist Admin-only — Nicht-Admins sehen keine toten Links). |
| v0.0.110 | **Gemeinsames Base-Layout `base.html`:** Header/Nav/Fußzeile zentral, alle 11 Seiten auf `{% extends "base.html" %}` umgestellt (Monitoring-Link jetzt auf ALLEN Seiten); login/otp ohne Nav, Anlagen-Bearbeiten mit vollem Gerüst. |
| v0.0.109 | **Monitoring-Statusseite `/admin/monitoring`:** Sammler-Status (Läufe, Points, Intervall, Fehler rot) + letzte Werte je Installation; Auto-Refresh 15 s; Nav-Link (vorher nur JSON-API). |
| v0.0.108 | TelefonieMonitoring v2: Modul-Import-Fix (Call-Output-Variablen ohne `OUT_`-Präfix — exakt Java-Feldnamen). |
| v0.0.107 | Feld **Monitoring-Modul-Instanz** (`monitoring_instance_name`, getrennt vom CallBlocker-Feld) in den Anlagen-Stammdaten. |
| v0.0.105 | **Telefonie-Monitoring:** STARFACE-Modul + WebApp-Sammler → InfluxDB (Grafana), Status in WebApp/API. |
| v0.0.97 | **Comboboxen mit Suchfeld** in den Rechte-Dropdowns (User + Anlage: keine Vorauswahl, gleich breit & breiter; Filter-Anlage suchbar, behält „Alle Anlagen“); Tabellen **standardmäßig eingeklappt**; Guard: Recht ohne Auswahl → Meldung statt 422. |
| v0.0.96 | **Admin-Listen filterbar + einklappbar:** Anlagen (Name + URL ab 3 Zeichen, Version-Dropdown), Benutzer (Name), Rechte (Benutzer + Anlage); „N von M“-Zähler; Zustand pro Tabelle gespeichert. |
| v0.0.95 | Scrollbar-Stil (Dark Design) app-weit vereinheitlicht. |
| v0.0.94 | Wiki-Scrollbars an Dark Design angeglichen. |
| v0.0.93 | **Dieses Admin-Wiki unter `/wiki`:** Markdown-Seiten, automatischer Index, TOC mit Ankern, interne Wikilinks, Volltextsuche; XSS-sicher via markdown-it-py; E2E-Tests. |
| v0.0.92 | **Dashboard-Badge-Fix:** zeigte immer „v9" — Route übergab `is10`, Template las `is_starface10` (Jinja2-Undefined = falsy, Bug seit Initial-Commit); + Regressionstest `badge_e2e.py`. |
| v0.0.78 | API-Doku im WebApp-Layout (Template mit Gruppen-Menü + Suche, nur Admins, Route statt Standalone-HTML). |
| v0.0.73 | Blocklist-Ändern-Button pro Eintrag (Inline-Formular, verlustfreier Update via ListAdd+ListRemove); E2E-Tests etabliert (`tmp_tests/`). |
| v0.0.71 | Leeres Blocklist-Formular abgefangen (Frontend-Validierung + Backend-Default, kein Pydantic-422). |
| v0.0.56–v0.0.52 | Modul-Themen: Instanzname-Feld `module_instance_name` + RPC-Präfix `[Instanzname].[EntryPoint]`; Passwortschutz fix (`writeHash=sha1(id)` — leerer writeHash ⇒ IMMER gesperrt); Versionierung `version=3`; RPC-Entrypoints im Descriptor. |
| v0.0.48 | Dashboard-Verbindungstest als Popup statt neuer Seite. |
| v0.0.44–v0.0.40 | **v10-OAuth-Implementierung:** Authorization Code Flow mit PKCE (Rest-Client), Basic-Auth 400-Fix, URL → https:// automatisch. |
| v0.0.38 | Korrekte `noLicenseId`-Formel `sha1Hex(id+lastChangedTime+"STARFACE")` — Lizenz behoben. |
| v0.0.35–v0.0.33 | Download-Dateiname mit Hash; Modul-Seite mit Versionierung + `Cache-Control: no-store` (iOS-Safari-Cache!); **`.sfm` als JAR mit MANIFEST.MF** („Manifest fehlt!" behoben). |
| v0.0.29–v0.0.31 | iOS-Zoom-Fix (echte Inputs `font-size:16px` — Vorsicht: blindes Regex-Replace trifft nur die erste, unsichtbare `#nav-open`-Checkbox); a11y-Labels (`<label for>` statt aria-label). |
| v0.0.19–v0.0.27 | Mobile-Responsive + PWA (Hamburger, sw.js, Manifest); Safe-Area-Insets (iOS Notch — nur EINMAL zählen); PWA-Icons (quadratischer Stern); Header-Logo-Folge (KITS-Logo bleibt, Nutzerwunsch). |
| v0.0.15–v0.0.18 | Modul-Verwaltung (Admin-Download-Seite für .sfm, Scanner `_scan_modules()`); einheitliches Nav-Menü + Admin-Badge; docker-compose vervollständigt; Footer-Puffer. |
| v0.0.9–v0.0.14 | Logo (KITS), Admin-Rollen-Editor (Letzter-Admin-Schutz), Footer fixiert + Version, Passwort-Reset zurück zum Admin. |
| v0.0.6–v0.0.8 | 2-Schritt-Login (Login → 2FA), 2FA-Setup + Backup-Codes, Favicon/Icons. |
| v0.0.1–v0.0.5 | Erster Push: FastAPI-Grundgerüst, Login, TOTP, Admin, Blocklist, Docker. |

## Roadmap / Offene Punkte

- **[Modul] Persistenz nach Anlagen-Neustart:** ListResource über
  `instance-config.xml` nach Reboot verifizieren (Tab + WebApp).
- **[WebApp] optional:** Blockier-Protokoll (Log-Ausgabe) über die API anzeigen —
  entscheiden, falls Datenschutz relevant wird.
