"""T3-Tests: WebApp-Update-Dienst module_updates.py (Phase 2 UpdateDeployer).

Geprüft:
1. build_update_payload(): Payload-Struktur (ohne/mit updateToken)
2. push_update(): Fehlerpfade (kein Kanal, kein Secret, keine Instanz)
3. push_update(): Erfolg — RPC-Aufruf exakt [instanz].UpdateFromUrl mit
   signierter URL (expires/md5 korrekt für filenamen-Pfad)
4. RuntimeError (Fault) im RPC → {"status":"error"} ohne Crash

Aufruf: python3 tmp_tests/test_module_updates.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/test_module_updates/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
# UPDATE_SIGNING_SECRET wird bewusst NICHT gesetzt — „kein Secret“-Pfad wird
# explizit getestet, danach erst für den Erfolgspfad gesetzt.
for var in ("FERNET_KEY", "TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET"):
    os.environ.pop(var, None)

import module_updates as mu


def check(name, cond, detail=""):
    if not cond:
        print(f"FAIL {name} {detail}")
        sys.exit(1)
    print(f"OK   {name}")


# --- 1. Payload-Struktur -------------------------------------------------
p = mu.build_update_payload("TelefonieMonitoring", "https://x/modules/TM_v7.sfm?e=m", "v7")
check("payload ohne Token", p == {
    "moduleName": "TelefonieMonitoring",
    "signedUrl": "https://x/modules/TM_v7.sfm?e=m",
    "targetVersion": "v7",
}, repr(p))

p2 = mu.build_update_payload("CallBlocker", "https://x/cb.sfm", "v28", update_token="tok123")
check("payload mit Token", p2.get("updateToken") == "tok123" and p2["moduleName"] == "CallBlocker",
      repr(p2))

# --- 2. Fehlerpfade ------------------------------------------------------
os.environ.pop("MODULE_UPDATE_BASE_URL", None)
inst = {"url": "https://anlage.example", "id": 1, "deployer_instance_name": "UpdateDeployer"}

r = mu.push_update(inst, "tok", module_name="M", filename="M.sfm", target_version="v1")
check("Fehler: kein Kanal", r["status"] == "error" and "Kanal" in r["message"], repr(r))

os.environ["MODULE_UPDATE_BASE_URL"] = "https://modulupdates.meiser.family"
r = mu.push_update(inst, "tok", module_name="M", filename="M.sfm", target_version="v1")
check("Fehler: kein Secret", r["status"] == "error" and "SIGNING_SECRET" in r["message"], repr(r))

os.environ["UPDATE_SIGNING_SECRET"] = "testsecret"

# --- 3. Erfolg: RPC exakt + Signatur korrekt ------------------------------
captured = {}

def fake_xmlrpc(url, token, method, params=None, instance_name=None):
    captured["url"] = url
    captured["token"] = token
    captured["method"] = method
    captured["params"] = params or {}
    captured["instance_name"] = instance_name
    return {"raw": "<methodResponse>ok</methodResponse>", "values": ["imported"]}

mu._xmlrpc = fake_xmlrpc

r = mu.push_update(inst, "oauthtok", module_name="TelefonieMonitoring",
                   filename="TelefonieMonitoring_v7.sfm", target_version="v7",
                   update_token="tok123")
check("Erfolg-Status", r["status"] == "ok", repr(r))
check("RPC-Methode exakt", captured["method"] == "UpdateFromUrl", captured["method"])
check("Instanz-Präfix", captured["instance_name"] == "UpdateDeployer",
      captured.get("instance_name"))
check("Token durchgereicht", captured["params"].get("updateToken") == "tok123",
      repr(captured.get("params")))
check("URL-Basis", captured["params"]["signedUrl"].startswith(
    "https://modulupdates.meiser.family/modules/TelefonieMonitoring_v7.sfm?expires="),
    captured["params"]["signedUrl"])

from updatesign import _nginx_md5, parse_parts
base, expires, md5 = parse_parts(captured["params"]["signedUrl"])
check("Signatur für filenamen-Pfad", md5 == _nginx_md5(
    expires, "/modules/TelefonieMonitoring_v7.sfm", "testsecret"), md5)

# --- 4. Fault → kontrollierter Fehler -------------------------------------
def fault_xmlrpc(*a, **k):
    raise RuntimeError("STARFACE-Fehler: No item with that key")

mu._xmlrpc = fault_xmlrpc
r = mu.push_update(inst, "tok", module_name="M", filename="M_v1.sfm",
                   target_version="v1", instance_name="D")
check("Fault → error-Status", r["status"] == "error" and "No item" in r["message"], repr(r))

# --- 5. Kein Instanzname → Fehler -----------------------------------------
r = mu.push_update({"url": "https://x", "deployer_instance_name": ""}, "tok",
                   module_name="M", filename="M.sfm", target_version="v1")
check("Fehler: keine Instanz", r["status"] == "error" and "Instanz" in r["message"], repr(r))

print("\nERGEBNIS: ALLE MODULE-UPDATES-TESTS OK")
