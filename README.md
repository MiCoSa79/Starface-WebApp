name: Starface-WebApp

Verwaltungs-Web-App für das STARFACE Anrufblocker-Modul.

- **Python 3.11 / FastAPI + SQLite + Jinja2**
- **Multi-User mit TOTP-2FA und RBAC**
- **XML-RPC-Client** zu STARFACE-Anlagen (ListGet, ListAdd, ListRemove)
- **Docker-Container** (Port 8895)
- **Automatischer CI-Build** (GitHub Actions → Docker Hub)

## Aufbau

```
Starface-WebApp/
├── app/                    # FastAPI-Anwendung
│   ├── main.py             # Hauptanwendung (FastAPI-Server)
│   ├── requirements.txt    # Python-Abhängigkeiten
│   ├── models.py           # SQLite-Modell (Benutzer, Anlagen, Listen)
│   ├── auth.py             # Login, TOTP-2FA, Session, bcrypt
│   ├── routes.py           # Route-Handler (Anlagen, Listen, API)
│   └── templates/          # Jinja2-Templates (HTML-Oberfläche)
├── Dockerfile              # Container-Definition
├── docker-compose.yml      # Lokaler Start (Port 8895)
├── .github/workflows/      # CI/CD (Build + Push)
├── releases/               # STARFACE-Modul (.sfm, .class)
│   ├── starface-callblocker-1.0.0.sfm
│   └── install.md
└── README.md
```

## Schnelleinstieg (lokal)

```bash
# Container starten
docker compose up --build -d

# Health-Check
curl http://localhost:8895/health
```

## Docker auf ZimaOS

```bash
# Im Projektverzeichnis:
docker compose up --build -d

# Container stoppen/entfernen
docker compose down
```

## STARFACE-Modul (CallBlocker)

Das Modul `.sfm` ist im `releases/`-Ordner enthalten. Einbau im Modul-Editor:
1. Modul-Instanz erstellen (Name: z. B. `CallBlocker`)
2. Baustein `CallBlocker` aus der Modul-Library laden (`.sfm` importieren)
3. Baustein in Anrufroute der Ziel-Gruppe einhängen
4. RPC Entrypoints (ListGet, ListAdd, ListRemove) aktivieren
5. Blocklist-Datei im Instanz-Ordner anlegen:
   `/var/starface/module/instances/repo/<InstanzID>/res/blocklist.txt`

Die Web-App verwaltet diese Datei serverseitig via XML-RPC.

## Wiki

Detaillierte Dokumentation: `/opt/data/profiles/axel/wiki/entities/starface-anrufblocker.md`