---
title: Modul-Auto-Update — Architektur & Umsetzungsplan (Update-Server im Stack)
description: Design für automatisches Modul-Install/Update über die WebApp — Update-Server (nginx:alpine) als 4. Docker-Stack-Service, signierte zeitbegrenzte URLs (secure_link), zentrales Updater-Modul. Entscheidungen F1–F4, Vorbereitung A1–A6, offene Punkte.
updated: 2026-08-26
---

# Modul-Auto-Update — Architektur & Umsetzungsplan

**Status:** ✅ **Task 1 umgesetzt (26.08.):** Signatur-Bibliothek `app/updatesign.py` + Tests (8/8 grün, Vektor-geprüft). Vorbereitung A1–A4 + A6 erledigt (A1 via externem check-host.net-Beweis — Anlagen sind Cloud-Anlagen). Offen: Task 2 (nginx-Config) bis Task 5. Umsetzungsplan: `profiles/axel/.hermes/plans/2026-08-26_152327-update-server-module-updates.md` (Hermes-Wiki). Grundlagen-RE: [[admin-power-pack-re]].

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
├─ starface-webapp ─ :8895   spiegelt app/modules/*.sfm + versions.json → data/modules
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

## Umsetzung (5 Tasks, TDD — Details im Plan-Dokument)

1. ✅ **Signatur-Bibliothek** `app/updatesign.py` (+ `tmp_tests/test_updatesign.py`) — `secure_link`-kompatible URLs (`_nginx_md5`, `build_signed_url`, `parse_parts`), 2 Known-Vektoren von Hand + Roundtrip/TTL/URI-Differenz, 8/8 grün; Suite unverändert grün (module_status_test, error_box_test, monitoring_rechte_e2e 17/17, module_status_live)
2. **nginx-Config** `nginx-updates.conf` — `secure_link`, `limit_req`, read-only, 403/410/200-Verhalten lokal getestet (Docker-Testcontainer)
3. **WebApp-Spiegel** `mirror_modules()` beim Startup — `.sfm` aus Image → `data/modules` + `versions.json` im `is`-Schema (MD5 je Datei)
4. **Stack-Patch (Kopie!)** — Service `module-updates`, Env `UPDATE_SIGNING_SECRET` + `MODULE_UPDATE_BASE_URL`; `docker compose config` validieren (Skill docker-compose-pruefung)
5. **Deploy + Abnahme** — 403 ohne Token / 200 mit frischer Signatur / WebApp-Log „mirror ok“; Rollback = nur neue Service-Definition zurück

## Offene Punkte

- **P1:** Anlage → Update-Domäne ungetestet; Fallback = Base64-Push (Phase 1 trotzdem baubar)
- **P2:** `secure_link`-`$uri`-Normalisierung → im Roundtrip-Test gegen echten nginx absichern
- **P3:** Tomcat-`maxPostSize` (>5-MB-Base64-Pakete) nur beim Push-Weg relevant — ggf. `ARC`-Kompression (Admin-Power-Pack-Muster)
- **P4:** Phasen 2/3: zentrales Updater-Modul (RPCs `GetModuleVersions`/`UpdateModule`/`UpdateAll` + `importModule`), optional GUI-Tab-Button — separater Plan nach Freigabe

## Abgrenzung

Hermes-Wiki hält die ausführliche Fassung (Entscheidungslogik F1–F3, Risiko-Tabelle, vollständiger Plan inkl. Code-Snippets): `profiles/axel/wiki/entities/admin-power-pack-re.md`.
