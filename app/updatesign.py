"""Signierte Download-URLs für den nginx `secure_link`-Update-Server (module-updates).

nginx-Konfiguration (Task 2/4):
    secure_link $arg_md5,$arg_expires;
    secure_link_md5 "$secure_link_expires$uri <UPDATE_SIGNING_SECRET>";

Signatur-Algorithmus exakt nach nginx-Doku:
    MD5("<expires><$uri> <secret>")   # Feldreihenfolge ist entscheidend!
    → base64url OHNE Padding

Die URL-Query trägt `expires` und `md5`; `$uri` der nginx-location muss dem `path_prefix`
entsprechen, für den die Signatur erzeugt wurde (Pitfall: Pfad-Normalisierung, siehe Plan).
"""
import base64
import hashlib
import time
import urllib.parse


def _nginx_md5(expires: str, uri: str, secret: str) -> str:
    """nginx secure_link-Signatur: base64url(MD5(expires + uri + ' ' + secret)) ohne Padding."""
    raw = hashlib.md5(f"{expires}{uri} {secret}".encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_signed_url(base_url: str, secret: str, ttl_s: int = 300,
                     path_prefix: str = "/modules/") -> str:
    """Baut eine zeitbegrenzte Download-URL für nginx secure_link.

    base_url:   Basis ohne Pfad (z. B. "https://www.sub.example.de")
    secret:     gemeinsames Secret (Update-Signatur)
    ttl_s:      Gültigkeit in Sekunden (Default 300 = 5 min)
    path_prefix:$uri, für den die Signatur gilt (Default "/modules/") — MUSS der
                nginx-location entsprechen
    """
    expires = str(int(time.time()) + ttl_s)
    sig = _nginx_md5(expires, path_prefix, secret)  # uri = $uri der nginx-location
    return f"{base_url}{path_prefix}?expires={expires}&md5={sig}"


def parse_parts(url: str):
    """Zerlegt eine signierte URL in (base, expires, md5).

    base = Scheme + Netloc + Pfad (ohne Query); expires/md5 als String (oder "" wenn fehlt).
    Dient Tests/Diagnose — die eigentliche Validierung macht nginx.
    """
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    return (f"{parts.scheme}://{parts.netloc}{parts.path}",
            query.get("expires", ""),
            query.get("md5", ""))
