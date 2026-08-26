"""UpdateDeployer-Anbindung (Phase 2, T3): WebApp orchestriert Modul-Updates.

Die WebApp baut eine signierte, zeitbegrenzte Download-URL (updatesign.py,
nginx secure_link) und ruft auf der STARFACE den UpdateDeployer-RPC auf:

    [Instanz].UpdateFromUrl(moduleName, signedUrl, targetVersion[, updateToken])

Damit steckt im Modul selbst NIE eine Update-URL und NIE ein Secret —
die Basis-URL kommt aus der Admin-Einstellung `module_update_base_url`,
das Signatur-Secret aus der Env `UPDATE_SIGNING_SECRET` (nie in UI/DB).
"""
import os

from main import _module_update_base, _xmlrpc
from updatesign import build_signed_url


def _signing_secret() -> str:
    return os.environ.get("UPDATE_SIGNING_SECRET", "")


def build_update_payload(module_name: str, signed_url: str, target_version: str,
                         update_token: str = "") -> dict:
    """RPC-Payload für UpdateFromUrl (updateToken nur setzen, wenn konfiguriert)."""
    payload = {
        "moduleName": module_name,
        "signedUrl": signed_url,
        "targetVersion": target_version,
    }
    if update_token:
        payload["updateToken"] = update_token
    return payload


def push_update(inst: dict, token: str, *, module_name: str, filename: str,
                target_version: str, update_token: str = "",
                instance_name: str | None = None) -> dict:
    """Stößt ein Modul-Update auf der Anlage an (UpdateFromUrl).

    inst:  installations-Zeile der WebApp-DB (url, deployer_instance_name)
    token: OAuth-Token der Anlage (aus _get_token)
    Liefert {"status": "ok"} oder {"status": "error", "message": ...}.
    """
    base = _module_update_base()
    if not base:
        return {"status": "error",
                "message": "Kein Update-Kanal konfiguriert (module_update_base_url leer)."}
    secret = _signing_secret()
    if not secret:
        return {"status": "error",
                "message": "UPDATE_SIGNING_SECRET nicht gesetzt."}
    inst_name = instance_name or (inst.get("deployer_instance_name") or "")
    if not inst_name:
        return {"status": "error",
                "message": "Keine Deployer-Instanz konfiguriert (deployer_instance_name)."}
    signed = build_signed_url(base, secret, path_prefix=f"/modules/{filename}")
    payload = build_update_payload(module_name, signed, target_version, update_token)
    try:
        res = _xmlrpc(inst["url"], token, "UpdateFromUrl", payload,
                      instance_name=inst_name)
        return {"status": "ok", "message": "ok", "raw": res.get("raw", "")[:200]}
    except RuntimeError as e:  # XML-RPC-Fault u. ä. → kontrollierter Fehler
        return {"status": "error", "message": str(e)}
