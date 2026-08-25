#!/usr/bin/env python3
"""verify_wiki_refs.py — Prüfung der Wiki-Quelltexte in app/wiki/.

Garantiert, dass der Wiki-Quelltext keine toten oder versteckten Verweise
auf andere Wiki-Artikel enthält (Nutzer-Anforderung):

1. Jeder Wikilink [[ziel]] / [[ziel|Text]] muss als .md-Datei im selben
   Ordner (app/wiki/) existieren — sonst Fehler.
2. Keine HTML-Kommentare, die Wiki-Verweise verstecken
   (<!-- ... [[...]] ... --> bzw. <!-- ... /wiki/ ... -->).
3. Jede Seite braucht valides Mini-Frontmatter: title, description,
   updated (YYYY-MM-DD).

Aufruf:  python3 scripts/verify_wiki_refs.py
Exit-Code 0 = sauber, 1 = Fehler gefunden. Pfad app/wiki relativ zum Repo-Root.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WIKI = REPO / "app" / "wiki"

WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
HIDDEN_RE = re.compile(r"<!--[\s\S]*?(?:\[\[|/wiki/)")
FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)

errors = []


def err(msg: str, file: Path) -> None:
    errors.append(f"{file.relative_to(REPO)}: {msg}")


def check_file(p: Path) -> None:
    text = p.read_text(encoding="utf-8")
    front = FRONT_RE.match(text)
    if not front:
        err("FEHLER: kein YAML-Frontmatter (--- title/description/updated ---)", p)
        body = text
    else:
        meta = {}
        for line in front.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"').strip("'")
        for key in ("title", "description", "updated"):
            if not meta.get(key):
                err(f"FEHLER: Frontmatter-Feld '{key}' fehlt oder ist leer", p)
        if meta.get("updated") and not re.match(r"^\d{4}-\d{2}-\d{2}$", meta["updated"]):
            err(f"FEHLER: 'updated' ist kein Datum (YYYY-MM-DD): {meta['updated']}", p)
        body = text[front.end():]

    # Tote Wikilinks: Ziel muss als .md existieren
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if not (WIKI / f"{target}.md").is_file():
            err(f"FEHLER: toter Wikilink [[{target}]] — Datei app/wiki/{target}.md fehlt", p)

    # Versteckte Verweise (HTML-Kommentare mit Wiki-Inhalten)
    for m in HIDDEN_RE.finditer(text):
        snippet = m.group(0)[:80].replace("\n", " ")
        err(f"FEHLER: versteckter Verweis in HTML-Kommentar: {snippet!r}", p)

    # Aufgeräumte Wikilinks: kein überflüssiges Leerzeichen im Ziel
    for m in WIKILINK_RE.finditer(body):
        if m.group(1).startswith(" ") or m.group(1).endswith(" "):
            err(f"FEHLER: Wikilink mit Leerzeichen im Ziel: [[{m.group(1)}]]", p)


def main() -> int:
    if not WIKI.is_dir():
        print(f"FEHLER: {WIKI} existiert nicht")
        return 1
    files = sorted(WIKI.glob("*.md"))
    if not files:
        print("FEHLER: keine .md-Dateien in app/wiki/")
        return 1
    for p in files:
        check_file(p)
    if errors:
        print(f"verify_wiki_refs: {len(errors)} Problem(e):")
        for e in errors:
            print("  -", e)
        return 1
    print(f"verify_wiki_refs: OK — {len(files)} Seite(n), alle Verweise sauber")
    return 0


if __name__ == "__main__":
    sys.exit(main())
