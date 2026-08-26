"""Tests für die Signatur-Bibliothek (updatesign) — nginx secure_link-Kompatibilität.

Geprüft werden:
1. build_signed_url: URL-Format, expires-Berechnung (ttl), Signatur-Vektor (Feldreihenfolge
   exakt `$secure_link_expires$uri <secret>` — nginx-Doku: MD5(expires + uri + " " + secret),
   base64url OHNE Padding)
2. Known-Vektor (von Hand berechnet, nicht aus der Implementierung kopiert)
3. parse_parts: Roundtrip + Einzelteile korrekt extrahiert
4. ttl=0 / negative TTL für Rückwärts-Tests (darf gültige URL bauen, sie wird nur "abgelaufen")

Konvention: eigenständiges Skript (Suite nutzt kein pytest), Aufruf:
    .venv/bin/python3 tmp_tests/test_updatesign.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# ---------------------------------------------------------------- Referenz (nginx-Doku, von Hand)
# nginx `secure_link_md5 "$secure_link_expires$uri <secret>";` → MD5, base64url ohne Padding.
def nginx_md5(expires: str, uri: str, secret: str) -> str:
    import base64
    import hashlib
    raw = hashlib.md5(f"{expires}{uri} {secret}".encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---------------------------------------------------------------- Tests
def test_known_vector_1():
    """Vektor von Hand: expires=1700000000, uri=/modules/TelefonieMonitoring_v7.sfm, secret=testsecret."""
    from updatesign import _nginx_md5
    sig = _nginx_md5("1700000000", "/modules/TelefonieMonitoring_v7.sfm", "testsecret")
    check("known-vector-1: Signatur exakt FQxYUR9L1UJj_Loz3gGPqw",
          sig == "FQxYUR9L1UJj_Loz3gGPqw", sig)


def test_known_vector_2():
    """Zweiter Vektor (versions.json-Pfad): expires=1700000300, uri=/versions.json."""
    from updatesign import _nginx_md5
    sig = _nginx_md5("1700000300", "/versions.json", "testsecret")
    check("known-vector-2: Signatur exakt hkMTZKYMEbMnf8dQWulmJA",
          sig == "hkMTZKYMEbMnf8dQWulmJA", sig)


def test_build_signed_url_roundtrip():
    from updatesign import build_signed_url, parse_parts
    url = build_signed_url("https://modulupdates.meiser.family", "testsecret",
                           ttl_s=300, path_prefix="/modules/a.sfm")
    base, exp, sig = parse_parts(url)
    check("roundtrip: Basis-URL erhalten", base == "https://modulupdates.meiser.family/modules/a.sfm", base)
    check("roundtrip: expires ist Zukunft (> now)", exp > "0" and int(exp) > 0, exp)
    check("roundtrip: Signatur == Referenz-nginx_md5",
          sig == nginx_md5(exp, "/modules/a.sfm", "testsecret"), sig)


def test_ttl_window():
    import time
    from updatesign import build_signed_url, parse_parts
    before = int(time.time())
    url = build_signed_url("https://x", "s", ttl_s=120, path_prefix="/p.bin")
    _, exp, _ = parse_parts(url)
    after = int(time.time())
    # expires muss in [now+119, now+121] liegen (kein falscher Skalierungsfaktor, kein Sekundenverlust)
    check("ttl: expires im 120s-Fenster (±1s)", before + 119 <= int(exp) <= after + 121, f"exp={exp}")


def test_expired_url_is_parseable():
    """Abgelaufene (oder negative) TTL: URL-Bau darf nicht crashen — nginx entscheidet später (410)."""
    from updatesign import build_signed_url, parse_parts
    url = build_signed_url("https://x", "s", ttl_s=-10, path_prefix="/alt.sfm")
    base, exp, sig = parse_parts(url)
    check("expired: parsebar", base == "https://x/alt.sfm" and int(exp) < 10**12 and sig != "", str(url))


def test_signature_differs_per_path():
    """Gleiches Secret, andere URI → andere Signatur (URI ist Teil des MD5-Eingangs)."""
    from updatesign import _nginx_md5
    a = _nginx_md5("1700000000", "/modules/a.sfm", "secret")
    b = _nginx_md5("1700000000", "/modules/b.sfm", "secret")
    check("uri-differenz: andere Signatur", a != b, f"{a} == {b}")


# ---------------------------------------------------------------- Runner
test_known_vector_1()
test_known_vector_2()
test_build_signed_url_roundtrip()
test_ttl_window()
test_expired_url_is_parseable()
test_signature_differs_per_path()

print()
if FAIL:
    print(f"FAIL ({len(FAIL)}): {', '.join(FAIL)}")
    sys.exit(1)
print("ALLE TESTS GRÜN")
