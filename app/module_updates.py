"""Deployment-Modul-Anbindung (Phase 2, T3): WebApp orchestriert Modul-Updates.

Die WebApp baut eine signierte, zeitbegrenzte Download-URL (updatesign.py,
nginx secure_link) und ruft auf der STARFACE den Deployment-Modul-RPC auf:

    [Instanz].UpdateFromUrl(moduleName, signedUrl, targetVersion[, updateToken])

Damit steckt im Modul selbst NIE eine Update-URL und NIE ein Secret —
die Basis-URL kommt aus der Admin-Einstellung `module_update_base_url`,
das Signatur-Secret aus der Env `UPDATE_SIGNING_SECRET` (nie in UI/DB).
"""
import json
import os

try:
    from main import _decrypt
except ImportError:
    from app.main import _decrypt

# Container-Import-Muster: Im Image liegen App-Module unter /app/app/ und sind
# NICHT top-level auflösbar (sys.path enthält nur /app). Deshalb Zwei-Wege-Import
# — exakt wie monitoring/mirror in main.py (siehe F20/F21 im Hermes-Wiki).
try:
    from main import _module_update_base, _xmlrpc
    from updatesign import build_signed_url
except ImportError:
    from app.main import _module_update_base, _xmlrpc
    from app.updatesign import build_signed_url


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
    inst_name = instance_name or str(dict(inst).get("deployer_instance_name") or "")
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


def _extract_response(raw: str, max_len: int = 500) -> str:
    """Extrahiert den ersten <string>-Wert aus einer XML-RPC-Response (Antwort-Text).

    max_len: Obergrenze für die Rückgabe. Kurze Modul-Meldungen (ping/push/
    execute) bleiben bei 500 — die Anlagen-Updates-Liste (GetAnlagenUpdates)
    übergibt explizit ein großes Limit, sonst würde das JSON mitten im Objekt
    abgeschnitten und json.loads schlüge fehl ("Unerwartete Antwort").
    """
    import re
    m = re.search(r"<string>(.*?)</string>", raw or "", re.DOTALL)
    return m.group(1)[:max_len] if m else (raw or "")[:min(max_len, 200)]


def ping_channel(inst: dict, token: str, *, filename: str,
                 instance_name: str | None = None) -> dict:
    """Download-Beweis (T5): [Instanz].Ping(signedUrl, \"\") — lädt die signierte Datei.

    inst:  installations-Zeile der WebApp-DB (url, deployer_instance_name)
    token: OAuth-Token der Anlage (aus _get_token)
    Liefert {\"status\": \"ok\", \"raw\": ..., \"response\": ...} oder
    {\"status\": \"error\", \"message\": ...}.
    """
    base = _module_update_base()
    if not base:
        return {"status": "error",
                "message": "Kein Update-Kanal konfiguriert (module_update_base_url leer)."}
    secret = _signing_secret()
    if not secret:
        return {"status": "error",
                "message": "UPDATE_SIGNING_SECRET nicht gesetzt."}
    inst_name = instance_name or str(dict(inst).get("deployer_instance_name") or "")
    if not inst_name:
        return {"status": "error",
                "message": "Keine Deployer-Instanz konfiguriert (deployer_instance_name)."}
    signed = build_signed_url(base, secret, path_prefix=f"/modules/{filename}")
    payload = {"signedUrl": signed, "updateToken": ""}
    try:
        res = _xmlrpc(inst["url"], token, "Ping", payload, instance_name=inst_name)
        raw = res.get("raw", "")[:1500]
        return {"status": "ok", "message": "ok", "raw": raw,
                "response": _extract_response(raw)}
    except RuntimeError as e:  # XML-RPC-Fault u. ä. → kontrollierter Fehler
        return {"status": "error", "message": str(e)}


def create_instance(inst: dict, token: str, *, module_name: str,
                    instance_name: str) -> dict:
    """Legt eine neue, sofort aktive Instanz eines Moduls auf der Anlage an.

    F79 (v1.0.76): RPC ``CreateInstance`` an das Deployment-Modul (dm-v9) —
    dieses übersetzt den Modulnamen in die Modul-ID (ModuleRegistry), prüft
    auf Namenskollision, legt die Instanz an, persistiert und aktiviert sie.

    inst:  installations-Zeile der WebApp-DB (url, deployer_instance_name)
    token: OAuth-Token der Anlage (aus _get_token)
    Liefert {"status": "ok", "raw": ..., "response": ...} oder
    {"status": "error", "message": ...}.
    """
    inst_name = str(dict(inst).get("deployer_instance_name") or "")
    if not inst_name:
        return {"status": "error",
                "message": "Keine Deployer-Instanz konfiguriert (deployer_instance_name)."}
    payload = {"moduleName": module_name, "instanceName": instance_name}
    try:
        res = _xmlrpc(inst["url"], token, "CreateInstance", payload,
                      instance_name=inst_name)
        raw = res.get("raw", "")
        response = _extract_response(raw)
        if response.startswith("ERROR"):
            return {"status": "error", "message": response}
        return {"status": "ok", "message": "ok", "raw": raw[:200],
                "response": response}
    except RuntimeError as e:  # XML-RPC-Fault u. ä. → kontrollierter Fehler
        return {"status": "error", "message": str(e)}


def _update_token(inst: dict) -> str:
    """Deployer-Token der Anlage im Klartext.

    Das WebApp-Formular speichert Secrets Fernet-versiegelt (enc:...).
    Klartext-Werte (z. B. Direkt-Inserts in Tests) bleiben unverändert.
    """
    v = str(dict(inst).get("deployer_token") or "")
    return _decrypt(v) if v.startswith("enc:") else v


def get_anlagen_updates(inst: dict, token: str, *,
                        instance_name: str | None = None) -> dict:
    """Fragt die verfügbaren STARFACE-Server-Updates der Anlage ab (dm-v10).

    RPC ``GetAnlagenUpdates`` an den Deployment-Modul-Deployer: das Modul
    liest LicenseComponent.fetchUpdates (Final-Kanal) und liefert JSON
    mit current-Version + updates-Liste. Read-only — es wird NICHTS
    verändert.

    inst:  installations-Zeile der WebApp-DB (url, deployer_instance_name,
           deployer_token)
    token: OAuth-Token der Anlage (aus _get_token)
    Liefert {"status": "ok", "data": {...}} oder
    {"status": "error", "message": ...}.
    """
    inst_name = instance_name or str(dict(inst).get("deployer_instance_name") or "")
    if not inst_name:
        return {"status": "error",
                "message": "Keine Deployer-Instanz konfiguriert (deployer_instance_name)."}
    payload = {"updateToken": _update_token(inst)}
    try:
        res = _xmlrpc(inst["url"], token, "GetAnlagenUpdates", payload,
                      instance_name=inst_name)
        raw = res.get("raw", "")
        # Volle Antwort: die Update-Liste (mit description/changelog je Update)
        # ist deutlich größer als die 500-Byte-Kappung für kurze Meldungen.
        response = _extract_response(raw, max_len=1_000_000)
        try:
            data = json.loads(response)
        except (ValueError, TypeError):
            return {"status": "error",
                    "message": f"Unerwartete Antwort: {response[:200]}",
                    "raw": raw[:200]}
        if isinstance(data, dict) and "error" in data:
            return {"status": "error", "message": str(data["error"]),
                    "raw": raw[:200]}
        return {"status": "ok", "data": data, "raw": raw[:250]}
    except RuntimeError as e:  # XML-RPC-Fault u. ä. → kontrollierter Fehler
        return {"status": "error", "message": str(e)}


def execute_anlagen_update(inst: dict, token: str, *, version: str,
                           update_url: str,
                           instance_name: str | None = None) -> dict:
    """Stößt ein STARFACE-Server-Update auf der Anlage an (dm-v10).

    RPC ``ExecuteAnlagenUpdate`` an den Deployment-Modul-Deployer: das Modul
    validiert Zielversion + URL gegen die frische Update-Liste und startet
    die Update-Pipeline (Session-Logout, DNF-Update, Reboot). Die Antwort
    kommt VOR dem Logout zurück; die Ausführung läuft auf der Anlage weiter.

    inst:  installations-Zeile der WebApp-DB (url, deployer_instance_name,
           deployer_token)
    token: OAuth-Token der Anlage (aus _get_token)
    version/update_url: aus der GetAnlagenUpdates-Liste (Anzeige)
    Liefert {"status": "ok", "message": ...} oder {"status": "error", ...}.
    """
    inst_name = instance_name or str(dict(inst).get("deployer_instance_name") or "")
    if not inst_name:
        return {"status": "error",
                "message": "Keine Deployer-Instanz konfiguriert (deployer_instance_name)."}
    payload = {"version": version, "updateUrl": update_url,
               "updateToken": _update_token(inst)}
    try:
        res = _xmlrpc(inst["url"], token, "ExecuteAnlagenUpdate", payload,
                      instance_name=inst_name)
        raw = res.get("raw", "")
        response = _extract_response(raw)
        if response.startswith("ERROR"):
            return {"status": "error", "message": response, "raw": raw[:200]}
        return {"status": "ok", "message": response, "raw": raw[:200]}
    except RuntimeError as e:  # XML-RPC-Fault u. ä. → kontrollierter Fehler
        return {"status": "error", "message": str(e)}
