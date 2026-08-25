#!/usr/bin/env python3
"""E2E-Test: Wiki (Admin-only) — Index, Seiten, Wikilinks, TOC, Suche, Nav.

Muster aus tmp_tests/badge_e2e.py: Env-Admin, TestClient mit lifespan
(Context-Manager), Form-Login. Läuft gegen die ECHTEN app/wiki/*.md-Dateien
im Repo (kein Fake).

Aufruf:  cd <repo> && .venv/bin/python tmp_tests/wiki_e2e.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))  # für: import main, import wiki_render

_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_wiki_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["APP_VERSION"] = "v0.0.93-test"

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ok = 0
def check(label, cond, detail=""):
    global ok
    ok += 1
    print(f"  {'✅' if cond else '❌'} {label}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        sys.exit(1)

# ─────────────────────────────────────────────────────────────
print("Wiki-E2E: Renderer-Ebene (wiki_render)")
import wiki_render  # noqa: E402

pages = wiki_render.list_pages()
check("Index listet genau 5 Seiten", len(pages) == 5, f"gefunden: {[p['slug'] for p in pages]}")
for p in pages:
    check(f"Frontmatter vollständig: {p['slug']}",
          bool(p["title"]) and bool(p["description"]) and bool(p["updated"]))

page = wiki_render.render_page("starface-anrufblocker")
check("anrufblocker rendert", page is not None and "<h2" in page["html"])
check("TOC vorhanden (>= 5 Einträge)", len(page["toc"]) >= 5, f"{len(page['toc'])} Einträge")
check("TOC-Anker-ID generiert",
      'id="funktionsweise-modul-stand-v28"' in page["html"])
check("Wikilink aufgelöst",
      'href="/wiki/starface-modul-designer"' in page["html"])
check("Kein roher Wikilink-Text im HTML", "[[starface" not in page["html"])
check("Unbekannter Wikilink wird kein toter Link",
      'href="/wiki/gibtsnicht"' not in page["html"])

rendered = wiki_render._md.render("<script>alert(1)</script>")
check("XSS-sicher: Script-Tag wird escaped",
      "&lt;script&gt;" in rendered and "<script>" not in rendered)

results = wiki_render.search("SimpleMatch")
check("Suche 'SimpleMatch' findet Designer-Seite",
      any(r["slug"] == "starface-modul-designer" for r in results))
check("Suche mit <2 Zeichen leer", wiki_render.search("x") == [])
check("Suche ohne Treffer leer", wiki_render.search("blxq9137") == [])

# ─────────────────────────────────────────────────────────────
print("Wiki-E2E: HTTP-Ebene (Admin vs. User)")
import sqlite3  # noqa: E402
import bcrypt as bc  # noqa: E402

# Starlette 0.27: TestClient erzwungen follow_redirects=True — Attribut nachträglich ausschalten
c = TestClient(main.app)
c.follow_redirects = False
with c:
    # ohne Login → Admin-Muster: Redirect /dashboard (dort → Login-Seite)
    r = c.get("/wiki")
    check("Ohne Login: /wiki → Redirect /dashboard",
          r.status_code in (303, 307) and "dashboard" in r.headers.get("location", ""),
          f"{r.status_code} -> {r.headers.get('location')}")
    r = c.get("/wiki/search?q=test")
    check("Ohne Login: /wiki/search → leere JSON-Ergebnisse",
          r.status_code == 200 and r.json() == {"results": []})

    # Normal-User (kein Admin) via direktem DB-Insert (läuft im TestClient-Kontext)
    conn = sqlite3.connect(_tmpdb)
    conn.execute("INSERT INTO users (username, password_hash, is_admin, otp_secret, otp_confirmed) VALUES (?, ?, 0, NULL, 0)",
                 ("normal", bc.hashpw(b"userpass123", bc.gensalt()).decode()))
    conn.commit()
    conn.close()

    c.post("/api/login", data={"username": "normal", "password": "userpass123"})
    r = c.get("/wiki")
    check("User ohne Admin: /wiki → Redirect /dashboard",
          r.status_code in (303, 307) and "dashboard" in r.headers.get("location", ""),
          f"{r.status_code} -> {r.headers.get('location')}")
    r = c.get("/dashboard")
    check("User: Dashboard ohne Wiki-Nav", 'href="/wiki"' not in r.text)
    r = c.get("/wiki/search?q=SimpleMatch")
    check("User ohne Admin: Suche → leere JSON-Ergebnisse",
          r.status_code == 200 and r.json() == {"results": []})
    c.get("/logout")

    # Admin (Env-Admin, durch lifespan angelegt)
    r = c.post("/api/login", data={"username": "admin", "password": "testpass123"})
    check("Admin-Login ok", r.status_code == 200 and r.json().get("status") == "ok", str(r.json()))

    r = c.get("/wiki")
    check("Admin: /wiki 200", r.status_code == 200)
    check("Admin: Index zeigt Seitenkarten",
          "Wissensdatenbank" in r.text and 'href="/wiki/starface-anrufblocker"' in r.text)
    check("Admin: 'Zuletzt geändert' im Index", "Zuletzt geändert" in r.text)
    check("Admin: Suchfeld vorhanden", 'id="wiki-q"' in r.text)

    r = c.get("/wiki/starface-anrufblocker")
    check("Admin: Seite 200", r.status_code == 200)
    check("Admin: TOC-Seitenleiste",
          "Inhalt" in r.text and 'href="#funktionsweise-modul-stand-v28"' in r.text)
    check("Admin: gerenderter Wikilink",
          'href="/wiki/starface-modul-designer"' in r.text)
    check("Admin: kein roher Wikilink-Text", "[[starface-modul-paketierung]]" not in r.text)
    check("Admin: Zurück-Link", "Zur Übersicht" in r.text)
    check("Admin: Footer-Version", "STARFACE WebApp v0.0.93-test" in r.text)

    r = c.get("/wiki/starface-modul-designer")
    check("Admin: Designer-Seite 200", r.status_code == 200 and "Modul Designer" in r.text)
    r = c.get("/wiki/gibtsnicht")
    check("Admin: unbekannte Seite → Redirect /wiki",
          r.status_code in (303, 307) and r.headers.get("location", "").endswith("/wiki"),
          f"status={r.status_code} location={r.headers.get('location')}")

    r = c.get("/wiki/search?q=Manifest")
    check("Admin: Suche JSON ok", r.status_code == 200)
    data = r.json().get("results", [])
    check("Admin: Suche 'Manifest' findet Paketierung-Seite",
          any(x["slug"] == "starface-modul-paketierung" for x in data),
          f"{[x['slug'] for x in data]}")

# ─────────────────────────────────────────────────────────────
print("Wiki-E2E: verify_wiki_refs.py (keine toten/versteckten Verweise)")
r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "verify_wiki_refs.py")],
                   capture_output=True, text=True)
check("verify_wiki_refs Exit 0", r.returncode == 0, r.stdout + r.stderr)
check("verify_wiki_refs Meldung OK", "alle Verweise sauber" in r.stdout)

# Negativtest: toter Wikilink MUSS erkannt werden (Modul frisch laden, WIKI umbiegen)
src = (Path(REPO) / "scripts" / "verify_wiki_refs.py").read_text(encoding="utf-8")
with tempfile.TemporaryDirectory() as tmp:
    bad = Path(tmp) / "x.md"
    bad.write_text("---\ntitle: T\nupdated: 2026-08-25\ndescription: D\n---\n\nSiehe [[gibtsnicht]]\n",
                   encoding="utf-8")
    ns = {"__name__": "vwr_neg", "__file__": str(Path(tmp) / "verify_wiki_refs.py")}
    exec(compile(src, "verify_wiki_refs.py", "exec"), ns)
    ns["WIKI"] = Path(tmp)
    out = ns["main"]()
    check("Negativtest: toter Wikilink → Exit 1", out == 1)

    # versteckter Verweis (HTML-Kommentar) MUSS erkannt werden
    bad.write_text("---\ntitle: T\nupdated: 2026-08-25\ndescription: D\n---\n\nText <!-- [[gibtsnicht]] --> mehr\n",
                   encoding="utf-8")
    out = ns["main"]()
    check("Negativtest: versteckter Verweis → Exit 1", out == 1)

print(f"\n{ok} Checks grün.")
sys.exit(0)
