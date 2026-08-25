"""Markdown-Wiki-Renderer für die STARFACE WebApp.

Liest .md-Dateien aus app/wiki/ (liegt im Docker-Image, kein Volume) und
rendert sie XSS-sicher über markdown-it-py (html=False):

- Mini-Frontmatter: title, description, updated (YYYY-MM-DD)
- Wikilinks [[ziel]] / [[ziel|Text]] -> interne Links (/wiki/<ziel>),
  nur wenn das Ziel als .md-Datei existiert (Garantie: verify_wiki_refs.py)
- TOC (H1-H3) mit Anker-IDs im gerenderten HTML
- Volltextsuche für /wiki/search (Plain-Text aus dem gerenderten HTML)

Keine externen Abhängigkeiten außer markdown-it-py (in requirements.txt).
"""

import os
import re
from functools import lru_cache
from pathlib import Path

from markdown_it import MarkdownIt

WIKI_DIR = Path(__file__).resolve().parent / "wiki"

# commonmark + Tabellen; html=False macht das Rendering XSS-sicher
_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    .enable("table")
)

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_H_RE = re.compile(r"<h([1-6])>")
_TAG_RE = re.compile(r"<[^>]+>")
_HEX_ENT = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&#39;": "'", "&quot;": '"'}
_INLINE_RE = re.compile(
    r"(\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]|\[([^\]]+)\]\([^)]+\)|`([^`]+)`|\*\*([^*]+)\*\*)"
)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


# ─────────────────────────────────────────────────────────────
# Frontmatter
# ─────────────────────────────────────────────────────────────

def _parse_frontmatter(text):
    """Liefert (meta, body). meta hat title/description/updated (oder None)."""
    meta = {"title": None, "description": None, "updated": None}
    m = _FRONT_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            if key in meta:
                meta[key] = val.strip().strip('"').strip("'")
        body = text[m.end():]
    else:
        body = text
    return meta, body


# ─────────────────────────────────────────────────────────────
# Headings -> TOC + Anker-IDs
# ─────────────────────────────────────────────────────────────

def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "abschnitt")[:70]


def _clean_inline(text):
    """Entfernt Markdown-Inline-Syntax für TOC/meta (bold, code, links, wikilinks)."""
    def repl(m):
        if m.group(1).startswith("[["):
            return (m.group(3) or m.group(2)).strip()
        if m.group(4):
            return m.group(4)
        if m.group(5):
            return m.group(5)
        return m.group(6)
    return _INLINE_RE.sub(repl, text).strip()


def _extract_headings(text):
    """Gibt [(level, text, slug), ...] in Dokumentreihenfolge (1:1 zu <hN>-Tags)."""
    out = []
    seen = {}
    for line in text.splitlines():
        m = _HEAD_RE.match(line)
        if not m:
            continue
        clean = _clean_inline(m.group(2))
        slug = _slugify(clean)
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        out.append((len(m.group(1)), clean, slug))
    return out


def _inject_anchors(html, headings):
    """Ersetzt <hN> durch <hN id="slug"> — Reihenfolge ist 1:1 zu den Quell-Headings."""
    it = iter(headings)

    def repl(m):
        slug = ""
        try:
            slug = next(it)[2]
        except StopIteration:
            pass
        return f'<h{m.group(1)} id="{slug}">'

    return _H_RE.sub(repl, html)


# ─────────────────────────────────────────────────────────────
# Wikilinks
# ─────────────────────────────────────────────────────────────

def _resolve_wikilinks(text, known_slugs):
    """[[ziel]] / [[ziel|Text]] -> Markdown-Link. Unbekannte Ziele -> Code-Spanne (kein toter Link)."""
    def repl(m):
        target = m.group(1).strip()
        label = (m.group(2) or target).strip().replace("]", "\\]")
        if target in known_slugs:
            return f"[{label}](/wiki/{target})"
        return f"`{target}`"

    return _WIKILINK_RE.sub(repl, text)


# ─────────────────────────────────────────────────────────────
# Seiten lesen / rendern
# ─────────────────────────────────────────────────────────────

def _page_files():
    if not WIKI_DIR.is_dir():
        return []
    return sorted(WIKI_DIR.glob("*.md"))


def list_pages():
    """[{slug, title, description, updated}] — sortiert nach updated absteigend."""
    pages = []
    for p in _page_files():
        meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
        pages.append({
            "slug": p.stem,
            "title": meta["title"] or p.stem,
            "description": meta["description"] or "",
            "updated": meta["updated"] or "",
        })
    pages.sort(key=lambda x: x["updated"], reverse=True)
    return pages


@lru_cache(maxsize=32)
def render_page(slug):
    """Rendert eine Seite oder liefert None. Cache gilt pro Prozess (Image-Dateien statisch)."""
    p = WIKI_DIR / f"{slug}.md"
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    headings = _extract_headings(body)
    known = {pg["slug"] for pg in list_pages()}
    body = _resolve_wikilinks(body, known)
    html = _md.render(body)
    html = _inject_anchors(html, headings)
    return {
        "slug": slug,
        "title": meta["title"] or slug,
        "description": meta["description"] or "",
        "updated": meta["updated"] or "",
        "html": html,
        "toc": [{"level": lv, "text": tx, "slug": sl} for lv, tx, sl in headings if lv <= 3],
    }


# ─────────────────────────────────────────────────────────────
# Volltextsuche (für /wiki/search)
# ─────────────────────────────────────────────────────────────

def _plain_text(html):
    out = _TAG_RE.sub("", html)
    for k, v in _HEX_ENT.items():
        out = out.replace(k, v)
    return out


def search(q):
    """[{slug, title, snippet}] — Volltextsuche über alle Seiten (case-insensitiv)."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    results = []
    for pg in list_pages():
        page = render_page(pg["slug"])
        if not page:
            continue
        plain = _plain_text(page["html"])
        idx = plain.lower().find(q)
        title_hit = q in page["title"].lower()
        if idx == -1 and not title_hit:
            continue
        if title_hit:
            snippet = page["description"] or plain[:120]
        else:
            start = max(0, idx - 60)
            end = min(len(plain), idx + len(q) + 90)
            snippet = ("…" if start > 0 else "") + plain[start:end].strip() + ("…" if end < len(plain) else "")
        results.append({
            "slug": pg["slug"],
            "title": page["title"],
            "snippet": snippet,
            "updated": page["updated"],
        })
    results.sort(key=lambda r: r["title"].lower())
    return results[:20]
