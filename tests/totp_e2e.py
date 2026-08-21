#!/usr/bin/env python3
"""E2E-Test: Zwei-Schritt-Login (User+Pass → TOTP) der Starface-WebApp.

Verwendung (vom Repo-Root, Server läuft mit frischer DB):
    BASE_URL=http://127.0.0.1:8000 ADMIN_USER=admin ADMIN_PASS=test1234 \
        python tests/totp_e2e.py

Erwartete Ausgabe — alle Zeilen beginnen mit "OK":
    OK 1  Login-Seite: Schritt 1 (User/Pass), kein OTP-Feld initial
    OK 2  falsche Zugangsdaten -> 401
    OK 3  Login ohne 2FA -> sofort Session-Cookie
    OK 4  Dashboard mit Session erreichbar
    OK 5  2FA aktivieren + bestätigen
    OK 6  Login mit 2FA -> 2fa_required + pending_token, KEINE Session
    OK 7  falscher TOTP-Code -> 401 "Code ungültig"
    OK 8  korrekter TOTP-Code -> Session
    OK 9  Dashboard nach 2FA-Login erreichbar

Erfordert: frisches STARFACE_DB (oder DB ohne TOTP), Admin aus ENV.
"""
import os
import re
import sys
import time
import json
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "test1234")

failures = []


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

    def post_json(path, data, cookies=None):
        cj = cookies if cookies is not None else http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            BASE + path, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            r = op.open(req)
            return r.status, json.loads(r.read().decode()), cj
        except urllib.error.HTTPError as e:
            payload = e.read().decode()
            try:
                return e.code, json.loads(payload), cj
            except Exception:
                return e.code, {"message": payload[:200]}, cj

    # 1. Login-Seite: Schritt 1, kein OTP-Feld sichtbar
    html = urllib.request.urlopen(BASE + "/").read().decode()
    check(1, "Login-Seite: Schritt 1, OTP-Feld versteckt",
          "loginForm" in html and 'id="otpForm" class="hidden"' in html)

    # 2. Falsche Zugangsdaten -> 401
    code, data, _ = post_json("/api/login", {"username": ADMIN_USER, "password": "falsch"})
    check(2, "falsche Zugangsdaten -> 401",
          code == 401 and data.get("status") == "error")

    # 3. Login ohne 2FA -> sofort Session
    code, data, cj = post_json("/api/login",
                               {"username": ADMIN_USER, "password": ADMIN_PASS})
    check(3, "Login ohne 2FA -> Session-Cookie",
          code == 200 and data.get("status") == "ok" and len(list(cj)) == 1)

    # 4. Dashboard erreichbar
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    html = op.open(BASE + "/dashboard").read().decode()
    check(4, "Dashboard mit Session erreichbar", "Anlagen" in html)

    # 5. 2FA für admin aktivieren (Setup + Confirm mit Admin-Session)
    html = op.open(BASE + "/admin/users/1/totp-setup").read().decode()
    m = re.search(r"Geheimer Schlüssel: ([A-Z0-9]+)", html)
    if not m:
        check(5, "2FA-Setup (Secret/QR)", False)
        sys.exit(1)
    secret = m.group(1)
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        body = urllib.parse.urlencode({"code": totp.now()}).encode()
        req = urllib.request.Request(
            BASE + "/admin/users/1/totp-confirm", data=body, method="POST")
        op.open(req)
        check(5, "2FA-Setup + Bestätigung", True)
    except Exception as e:
        check(5, f"2FA-Setup + Bestätigung ({e})", False)
        sys.exit(1)

    # 6. Login mit aktiver 2FA -> 2fa_required + pending_token, KEINE Session
    code, data, cj2 = post_json("/api/login",
                                {"username": ADMIN_USER, "password": ADMIN_PASS})
    token = data.get("pending_token") if isinstance(data, dict) else None
    check(6, "Login mit 2FA -> 2fa_required ohne Session",
          code == 200 and data.get("status") == "2fa_required" and bool(token)
          and len(list(cj2)) == 0)

    # 7. Falscher TOTP-Code -> 401
    code, data, _ = post_json("/api/2fa/verify",
                              {"pending_token": token, "code": "000000"})
    check(7, "falscher TOTP-Code -> 401", code == 401)

    # 8. Korrekter TOTP-Code -> Session
    code, data, cj4 = post_json("/api/2fa/verify",
                                {"pending_token": token, "code": totp.now()})
    check(8, "korrekter TOTP-Code -> Session",
          code == 200 and data.get("status") == "ok" and len(list(cj4)) == 1)

    # 9. Dashboard nach 2FA-Login
    op4 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj4))
    html = op4.open(BASE + "/dashboard").read().decode()
    check(9, "Dashboard nach 2FA-Login", "Anlagen" in html)

    if failures:
        print(f"\n{len(failures)} Test(s) fehlgeschlagen: {failures}")
        sys.exit(1)
    print("\nAlle Tests bestanden.")


if __name__ == "__main__":
    main()
