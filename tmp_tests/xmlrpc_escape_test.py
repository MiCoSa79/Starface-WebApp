#!/usr/bin/env python3
"""Tests XML-Escaping im XML-RPC-Body (Bug: signedUrl mit ?& brach das Parsen an der Anlage).

Prüft:
1. _xml_escape ersetzt &, <, >
2. _xmlrpc erzeugt einen XML-PARSBAREN Body, der escaped ist (kein rohes '&expires')
3. Der Body-Parsbarkeit-Test per xml.etree (Strict)
"""
import base64, os, sys, importlib

sys.path.insert(0, "app")

def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (" | " + detail if detail else ""))
    if not ok:
        sys.exit(1)

DB = "/tmp/xml_escape_test.db"
if os.path.exists(DB):
    os.remove(DB)
os.environ["STARFACE_DB"] = DB
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"0" * 32).decode()
os.environ.pop("MODULE_UPDATE_BASE_URL", None)
os.environ.pop("UPDATE_SIGNING_SECRET", None)

import main as app_main

# --- 1. _xml_escape unit ----------------------------------------------------
check("_xml_escape &,<,>", app_main._xml_escape('a&b<c>d') == 'a&amp;b&lt;c&gt;d',
      app_main._xml_escape('a&b<c>d'))
check("_xml_escape leer", app_main._xml_escape('') == '')

# --- 2. _xmlrpc mit signierter URL (echter Body via gemockter POST) ---------
captured = {}

def fake_post(url, content=None, **kw):
    captured["url"] = url
    captured["body"] = content if isinstance(content, str) else (content or b"")
    raise RuntimeError("STOP")

import httpx
httpx.post = fake_post

signed = "https://www.sub.example.de/modules/Deployment-Modul.sfm?md5=abcxyz&expires=1234567890"
try:
    app_main._xmlrpc("https://anlage.example/xml-rpc", "jwt123",
                     "Ping", {"signedUrl": signed, "updateToken": ""},
                     instance_name="Deployment-Modul")
except RuntimeError as e:
    if "STOP" not in str(e):
        raise

body = captured.get("body", b"")
body = body.decode() if isinstance(body, bytes) else str(body)
check("Body enthält escaped &amp;expires", "&amp;expires" in body, body[:260])
check("Body enthält KEIN rohes &expires", "&expires" not in body)
check("methodName = Deployment-Modul.Ping", "Deployment-Modul.Ping" in body)

import xml.etree.ElementTree as ET
ET.fromstring(body)  # wirft bei ungültigem XML
check("Body ist gültiges XML (parsbar)", True)

# --- 3. Regression: normale Strings bleiben unverändert ----------------------
captured2 = {}

def fake_post2(url, content=None, **kw):
    captured2["body"] = content
    raise RuntimeError("STOP")

httpx.post = fake_post2
try:
    app_main._xmlrpc("https://anlage.example/xml-rpc", "jwt",
                     "GetStats", {"key": "normal"})
except RuntimeError as e:
    if "STOP" not in str(e):
        raise
b2 = captured2["body"]
b2 = b2.decode() if isinstance(b2, bytes) else str(b2)
check("Normal-String bleibt", "normal" in b2 and "&amp;" not in b2)

print("ERGEBNIS: ALLE XMLRPC-ESCAPE-TESTS OK")
