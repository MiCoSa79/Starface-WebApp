---
title: Modul-Auto-Update — Architektur & Umsetzungsplan (Update-Server im Stack)
description: Design für automatisches Modul-Install/Update über die WebApp — Update-Server (nginx:alpine) als 4. Docker-Stack-Service, signierte zeitbegrenzte URLs (secure_link), zentrales Updater-Modul. Entscheidungen F1–F3, Vorbereitung A1–A6, offene Punkte.
updated: 2026-08-26
---

# Modul-Auto-Update — Architektur & Umsetzungsplan

**Status:** 🛠 geplant — Umsetzungsplan liegt unter `profiles/axel/.hermes/plans/2026-08-26_152327-update-server-module-updates.md` (Hermes-Wiki), **noch nichts umgesetzt**. Grundlangen-RE: [[admin-power-pack-re]].

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

```
ZimaOS-Stack ───┐
├─ starface-webapp ─ :8895   spiegelt app/modules/*.sfm + versions.json → data/modules
├─ grafana ────────── :8894
├─ influxdb (intern)
└─ module-updates ─── :8896  nginx:alpine, secure_link, read-only
      ▲ NPM: https://modulupdate.meiser.family → :8896
      STARFACE-Anlage lädt .sfm selbst (Pull) / WebApp schiebt per XML-RPC (Push-Fallback)
```

## Vorbereitung durch den Nutzer (A1–A6, vor Task 1)

| # | Aufgabe | Detail |
|---|---|---|
| A1 | **Netz-Test (kritisch)** | Anlage muss `https://modulupdate.meiser.family` erreichen; Test vom Anlagen-Netz aus; ggf. Fritzbox-DNS-Eintrag → ZimaOS |
| A2 | DNS | `modulupdate.meiser.family` (mind. intern; öffentlich + Port-Forward 443 optional) |
| A3 | NPM-Host | `modulupdate.meiser.family` → `10.0.25.60:8896`, Let's Encrypt |
| A4 | Secret | `openssl rand -hex 32` → `<UPDATE_SIGNING_SECRET>` in Stack (nicht committen) |
| A5 | Ordner | `/DATA/AppData/starface-webapp/data/modules` vorab anlegen |
| A6 | Dateien | aktuelle `.sfm` in `app/modules/` bestätigen |

## Umsetzung (5 Tasks, TDD — Details im Plan-Dokument)

1. **Signatur-Bibliothek** `app/updatesign.py` (+ Tests) — `secure_link`-kompatible URLs (base64url ohne Padding, `MD5(expires + uri + secret)`, Vektor-geprüft)
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
