#!/usr/bin/env python3
"""Fake-XML-RPC-Server: simuliert die STARFACE-Anlage + CallBlocker-Modul
für E2E-Tests der Starface-WebApp (ListGet/ListAdd/ListRemove).
"""
import json
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE = {"list": [], "fail_add": False, "fail_remove": False, "calls": []}


class FakeXMLRPC(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if ".well-known/openid-configuration" in self.path:
            cfg = {
                "token_endpoint": f"http://{self.headers.get('Host')}/auth/realms/pbx/protocol/openid-connect/token",
                "authorization_endpoint": f"http://{self.headers.get('Host')}/auth/realms/pbx/protocol/openid-connect/auth",
            }
            self._send(json.dumps(cfg).encode(), "application/json")
        else:
            self._send(b"{}", "application/json")

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln).decode("utf-8", "replace")
        if "/oauth2/token" in self.path or "/openid-connect/token" in self.path or "grant_type" in body:
            self._send(json.dumps({"access_token": "fake-token", "refresh_token": "fake-refresh",
                                   "expires_in": 3600}).encode(), "application/json")
            return
        if "/xml-rpc" not in self.path:
            self._send(b"{}", "application/json")
            return
        root = ET.fromstring(body)
        mn = root.findtext(".//methodName") or ""
        method = mn.split(".")[-1]
        num = None
        for member in root.findall(".//member"):
            if member.findtext("name") == "INPUT_NUMMERN":
                num = (member.findtext("value/string") or "").strip()
        FAKE["calls"].append({"method": method, "num": num})

        if method == "ListGet":
            resp = ("<methodResponse><params><param><value><string>"
                    + ",".join(FAKE["list"])
                    + "</string></value></param></params></methodResponse>")
        elif method == "ListAdd":
            FAKE["calls"][-1]["ok"] = not FAKE["fail_add"]
            if not FAKE["fail_add"] and num:
                FAKE["list"].append(num)
            resp = ("<methodResponse><params><param><value><double>"
                    + ("0" if FAKE["fail_add"] else "1")
                    + "</double></value></param></params></methodResponse>")
        elif method == "ListRemove":
            FAKE["calls"][-1]["ok"] = not FAKE["fail_remove"]
            if not FAKE["fail_remove"] and num and num in FAKE["list"]:
                FAKE["list"].remove(num)
            resp = ("<methodResponse><params><param><value><double>"
                    + ("0" if FAKE["fail_remove"] else "1")
                    + "</double></value></param></params></methodResponse>")
        else:
            resp = "<methodResponse><params><param><value><string>?</string></value></param></params></methodResponse>"
        self._send(resp.encode("utf-8"), "text/xml")


def start_fake() -> str:
    """Startet den Fake-Server, gibt die Basis-URL zurück."""
    FAKE["list"].clear()
    FAKE["calls"].clear()
    FAKE["fail_add"] = False
    FAKE["fail_remove"] = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeXMLRPC)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"
