#!/usr/bin/env python3
"""E2E-Test: TOTP-2FA-Flow der Starface-WebApp.

Verwendung (vom Repo-Root):
    BASE_URL=http://127.0.0.1:8000 ADMIN_USER=admin ADMIN_PASS=test1234 \
        python tests/totp_e2e.py

Erwartete Ausgabe — alle Zeilen beginnen mit "OK":
    OK 1  Login als Admin -> /dashboard
    OK 2  totp-setup GET -> QR + Secret
    OK 3  falscher Setup-Code -> /admin?toter=1
    OK 4  korrekter Setup-Code -> /admin?tot_ok=1&codes=...
    OK 5  Login mit falschem TOTP -> /?error=2 (keine Session)
    OK 6  Login mit korrektem TOTP -> /dashboard (Session)

Erfordert: frisches STARFACE_DB (oder DB ohne TOTP), Admin aus ENV.
"""
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "test1234")

failures = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect", headers, fp)


def check(num, label, cond):
    print(("OK  " if cond else "FAIL") + f" {num} {label}")
    if not cond:
        failures.append((num, label))


def wait_health():
    for _ in range(30):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    if not wait_health():
        print("FAIL Server nicht erreichbar:", BASE)
        sys.exit(1)

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj))

    def post(path, data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(BASE + path, data=body, method="POST")
        try:
            r = opener.open(req)
            return r.status, r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", "")

    # 1. Login als Admin
    code, loc = post("/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    check(1, "Login als Admin -> /dashboard", code == 303 and "dashboard" in loc)

    # 2. 2FA-Setup-Seite (GET): QR-Daten-URI + Secret
    try:
        body = opener.open(BASE + "/admin/users/1/totp-setup").read().decode()
        m = re.search(r"Geheimer Schlüssel: ([A-Z0-9]+)", body)
        check(2, "totp-setup GET -> QR + Secret",
              "data:image/png;base64" in body and bool(m))
        secret = m.group(1) if m else None
    except urllib.error.HTTPError as e:
        check(2, "totp-setup GET -> QR + Secret", False)
        secret = None

    if not secret:
        print("FAIL TOTP-Setup fehlgeschlagen")
        sys.exit(1)

    import pyotp
    totp = pyotp.TOTP(secret)

    # 3. Falscher Bestätigungscode -> /admin?toter=1
    code, loc = post("/admin/users/1/totp-confirm", {"code": "000000"})
    check(3, "falscher Setup-Code -> /admin?toter=1", code == 303 and "toter=1" in loc)

    # 4. Korrekter Bestätigungscode -> /admin?tot_ok=1&codes=...
    code, loc = post("/admin/users/1/totp-confirm", {"code": totp.now()})
    check(4, "korrekter Setup-Code -> Backup-Codes sichtbar",
          code == 303 and "tot_ok=1" in loc and "codes=" in loc)

    # 5. Login mit falschem TOTP -> /?error=2, keine Session
    cj2 = http.cookiejar.CookieJar()
    op2 = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj2))
    body = urllib.parse.urlencode(
        {"username": ADMIN_USER, "password": ADMIN_PASS, "otp_code": "000000"}).encode()
    req = urllib.request.Request(BASE + "/login", data=body, method="POST")
    try:
        op2.open(req)
        check(5, "Login falscher TOTP -> abgewiesen", False)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        check(5, "Login falscher TOTP -> /?error=2 ohne Session",
              "error=2" in loc and len(list(cj2)) == 0)

    # 6. Login mit korrektem TOTP -> /dashboard, Session gesetzt
    body = urllib.parse.urlencode(
        {"username": ADMIN_USER, "password": ADMIN_PASS, "otp_code": totp.now()}).encode()
    req = urllib.request.Request(BASE + "/login", data=body, method="POST")
    try:
        op2.open(req)
        check(6, "Login korrekter TOTP -> /dashboard", False)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        check(6, "Login korrekter TOTP -> /dashboard (Session)",
              "dashboard" in loc and len(list(cj2)) == 1)

    if failures:
        print(f"\n{len(failures)} Test(s) fehlgeschlagen: {failures}")
        sys.exit(1)
    print("\nAlle Tests bestanden.")


if __name__ == "__main__":
    main()
