"""Telefonie-Monitoring-Sammler.

Pollt das TelefonieMonitoring-Modul (RPC \"GetStats\") aller konfigurierten
STARFACE-Installationen per XML-RPC und schreibt die Werte nach InfluxDB.

Measurements:
  system     - Tags: installation, host - Felder: version, mem_total, mem_free,
               mem_available, buffers, cached, swap_cached, active, inactive,
               load1, load5, load15, procs_running, procs_total, cpu_cores
  providers  - Tags: installation, provider - Felder: registered (1/0), status

Konfiguration (ENV):
  INFLUXDB_URL     (default http://influxdb:8086)
  INFLUXDB_TOKEN   (Pflicht, sonst wird nur gepollt, nicht geschrieben)
  INFLUXDB_ORG     (default starface)
  INFLUXDB_BUCKET  (default telefonie)
  MONITORING_INTERVAL (Sekunden, default 60)
"""
import asyncio
import os
import time

try:
    from main import _db, _get_token, _xmlrpc
except ImportError:  # Container: app.main
    from app.main import _db, _get_token, _xmlrpc

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:  # Tests ohne InfluxDB-Paket
    InfluxDBClient = None
    Point = None
    WritePrecision = None
    SYNCHRONOUS = None

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "starface")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "telefonie")
INTERVAL = float(os.environ.get("MONITORING_INTERVAL", "60"))

_state = {
    "running": False,
    "last_run": None,
    "last_error": None,
    "last_values": {},
    "total_runs": 0,
    "total_writes": 0,
}


def _write_points(points):
    """Schreibt Points nach InfluxDB; ohne Token oder Paket -> 0 (kein Fehler)."""
    if not points or not InfluxDBClient or not INFLUXDB_TOKEN:
        return 0
    with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG,
                        timeout=10_000) as client:
        with client.write_api(write_options=SYNCHRONOUS) as api:
            api.write(bucket=INFLUXDB_BUCKET, record=points,
                      write_precision=WritePrecision.S)
    return len(points)


def build_points(inst_name: str, system_name: str, members: dict) -> list:
    """Baut InfluxDB-Points aus der GetStats-Antwort (members-dict)."""
    points = []
    p = Point("system").tag("installation", inst_name)
    if system_name:
        p = p.tag("host", system_name)
    version = members.get("systemVersion")
    if version:
        p = p.field("version", str(version))
    int_fields = {
        "mem_total": "memTotal", "mem_free": "memFree", "mem_available": "memAvailable",
        "buffers": "buffers", "cached": "cached", "swap_cached": "swapCached",
        "active": "active", "inactive": "inactive",
        "procs_running": "procsRunning", "procs_total": "procsTotal", "cpu_cores": "cpuCores",
    }
    for influx_key, member_key in int_fields.items():
        try:
            p = p.field(influx_key, int(members[member_key]))
        except (KeyError, TypeError, ValueError):
            pass
    for load_key, member_key in (("load1", "load1"), ("load5", "load5"), ("load15", "load15")):
        try:
            p = p.field(load_key, float(members[member_key]))
        except (KeyError, TypeError, ValueError):
            pass
    points.append(p)
    # SIP-Provider: Zeilen \"Name=Status\"
    prov_status = members.get("providerStatus") or ""
    for line in prov_status.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name, status = line.split("=", 1)
        pp = Point("providers") \
            .tag("installation", inst_name) \
            .tag("provider", name.strip()) \
            .field("registered", 1 if status.strip() == "Registered" else 0) \
            .field("status", status.strip())
        points.append(pp)
    return points


def collect_installations() -> int:
    """Ein Poll über alle Installationen mit gesetzter Modul-Instanz."""
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM installations WHERE monitoring_instance_name IS NOT NULL"
        " AND monitoring_instance_name != ''"
    ).fetchall()
    conn.close()
    writes = 0
    for inst in rows:
        name = inst["name"]
        try:
            token = _get_token(inst)
            result = _xmlrpc(inst["url"], token, "GetStats",
                             instance_name=inst["monitoring_instance_name"])
            members = result.get("members", {})
            system_name = str(members.get("systemName", ""))
            points = build_points(name, system_name, members)
            writes += _write_points(points)
            _state["last_values"][name] = {
                "systemName": system_name,
                "systemVersion": members.get("systemVersion", ""),
                "providers": members.get("providerStatus", ""),
                "points": len(points),
                "ts": time.time(),
            }
            print(f"[Monitoring] {name}: {len(points)} Points -> InfluxDB")
        except Exception as e:
            _state["last_error"] = f"{name}: {e}"
            print(f"[Monitoring] FEHLER {name}: {e}")
    return writes


async def run_loop():
    """Hintergrund-Loop (lifespan): pollt zyklisch alle Installationen."""
    _state["running"] = True
    print(f"[Monitoring] Sammler gestartet (Intervall {INTERVAL}s, Influx {INFLUXDB_URL})")
    while True:
        _state["last_run"] = time.time()
        _state["total_runs"] += 1
        try:
            _state["total_writes"] += collect_installations()
        except Exception as e:
            _state["last_error"] = str(e)
            print(f"[Monitoring] Loop-Fehler: {e}")
        await asyncio.sleep(INTERVAL)


def status() -> dict:
    """Status für die API-Route /api/monitoring/status."""
    return {
        "running": _state["running"],
        "interval": INTERVAL,
        "influx_url": INFLUXDB_URL,
        "influx_bucket": INFLUXDB_BUCKET,
        "influx_configured": bool(INFLUXDB_TOKEN),
        "last_run": _state["last_run"],
        "last_error": _state["last_error"],
        "total_runs": _state["total_runs"],
        "total_writes": _state["total_writes"],
        "installations": _state["last_values"],
    }
