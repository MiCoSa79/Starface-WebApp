#!/usr/bin/env python3
"""Fake-STARFACE für den Monitoring-Live-Beweis: OIDC-Discovery + Password-Grant
+ flache XML-RPC-Struct-Antwort auf [Instanz].GetStats (identisch zur echten
Antwort des TelefonieMonitoring-Moduls, wie von _xmlrpc geparst)."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 18998

MEMBERS = [
    ("systemName", "string", "pbx-test"),
    ("systemVersion", "string", "10.0.1.7"),
    ("memTotal", "int", "4096"),
    ("memFree", "int", "2048"),
    ("memAvailable", "int", "3000"),
    ("procsRunning", "int", "3"),
    ("procsTotal", "int", "90"),
    ("cpuCores", "int", "4"),
    ("load1", "double", "0.1"),
    ("load5", "double", "0.2"),
    ("load15", "double", "0.15"),
    ("providerStatus", "string", "sip01@pbx-test=Registered"),
]


class FakeGS(BaseHTTPRequestHandler):
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
            host = self.headers.get("Host", f"127.0.0.1:{PORT}")
            cfg = {
                "token_endpoint": f"http://{host}/auth/realms/pbx/oauth2/token",
                "authorization_endpoint": f"http://{host}/auth/realms/pbx/protocol/openid-connect/auth",
            }
            self._send(json.dumps(cfg).encode(), "application/json")
        else:
            self._send(b"{}", "application/json")

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln).decode("utf-8", "replace")
        if "grant_type" in body or "/oauth2/token" in self.path:
            tok = {"access_token": "fake-token", "refresh_token": "fake-refresh", "expires_in": 3600}
            self._send(json.dumps(tok).encode(), "application/json")
            return
        if "/xml-rpc" not in self.path:
            self._send(b"{}", "application/json")
            return
        members = "".join(
            f"<member><name>{k}</name><value><{t}>{v}</{t}></value></member>"
            for k, t, v in MEMBERS
        )
        resp = (f"<methodResponse><params><param><value><struct>{members}"
                f"</struct></value></param></params></methodResponse>")
        self._send(resp.encode("utf-8"), "text/xml")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), FakeGS)
    print(f"FAKE-GETSTATS lauscht auf 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
