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
import json
import os
import time
import zipfile
import xml.etree.ElementTree as ET

try:
    from main import _db, _get_token, _xmlrpc, DB_PATH
except ImportError:  # Container: app.main
    from app.main import _db, _get_token, _xmlrpc, DB_PATH

# Drittanbieter-Spiegel: <data>/modules (Admin-Uploads auf der Modul-Seite).
# Dieselbe Quelle wie _data_modules_dir() in main.py — Teil der SOLL-Signatur.
THIRD_PARTY_DIR = os.path.join(os.path.dirname(DB_PATH), "modules")

try:
    import httpx as _httpx
    _TRANSPORT_ERRS = tuple(
        c for c in (getattr(_httpx, "ConnectError", None), getattr(_httpx, "ReadError", None),
                    getattr(_httpx, "TimeoutException", None)) if c is not None)
except ImportError:
    _httpx = None
    _TRANSPORT_ERRS = ()

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

# Verzeichnis der ausgelieferten Module (.sfm) — Single Source of Truth für
# den SOLL-Abgleich (module-descriptor.xml -> version). Default: app/modules
MODULES_DIR = os.environ.get(
    "MODULES_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"),
)
_EXPECT_CACHE = {"sig": None, "data": {}}

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
    # SIP-Provider: Zeilen "Name=Status"
    prov_status = members.get("providerStatus") or ""
    for line in prov_status.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        # rsplit am LETZTEN '=': Namen duerfen kein '=' enthalten (Modul liefert
        # 'user@host=State'), aber defensiv gegen alte "register=>..."-Namen,
        # deren '=' den Status sonst verfaelschen wuerde.
        name, status = line.rsplit("=", 1)
        pp = Point("providers") \
            .tag("installation", inst_name) \
            .tag("provider", name.strip()) \
            .field("registered", 1 if status.strip() == "Registered" else 0) \
            .field("status", status.strip())
        points.append(pp)
    return points


def _classify_error(e) -> dict:
    """Ordnet einen Poll-Fehler einer Kategorie zu (Anzeige/Hinweistext).

    - unreachable: Verbindung zur Anlage scheitert (httpx.Connect/Read/Timeout,
      OSError/TimeoutError — z. B. DNS, TCP, Read-Timeout)
    - module:      XML-RPC-Fault aus _xmlrpc („STARFACE-Fehler: ...“) — das
                   Monitoring-Modul (oder die Instanz) ist nicht erreichbar
    - auth:        HTTP 401/403 (OIDC/XML-RPC) — Zugangsdaten/Token ungültig
    - error:       sonstiger Fehler (Originaltext)
    """
    if isinstance(e, _TRANSPORT_ERRS + (ConnectionError, TimeoutError, OSError)):
        return {"category": "unreachable", "msg": "Anlage nicht erreichbar"}
    low = str(e).lower()
    if "starface-fehler" in low:
        return {"category": "module",
                "msg": "Monitoring-Modul nicht installiert oder eingerichtet"}
    if _httpx is not None and isinstance(e, getattr(_httpx, "HTTPStatusError", ())) \
            and getattr(e, "response", None) is not None \
            and getattr(e.response, "status_code", 0) in (401, 403):
        return {"category": "auth",
                "msg": "Zugangsdaten/Token ungültig — Token der Anlage in der Installation prüfen"}
    return {"category": "error", "msg": str(e)}


def _module_expectations() -> dict:
    """SOLL-Module + -Versionen aus app/modules/*.sfm (module-descriptor.xml).

    Single Source of Truth: gleiche Quelle, die die Anlage beim Import bekommt
    (<module version="N">). Eigene Module (app/modules) + hinterlegte
    Drittanbieter (<data>/modules via _merge_third_party). Cache-Signatur =
    mtime-Signatur beider Verzeichnisse: gleiche Signatur liefert dasselbe
    Objekt (kein Re-Build), Uploads/Löschungen ändern den Spiegel -> frisch.
    """
    try:
        files = sorted(f for f in os.listdir(MODULES_DIR) if f.endswith(".sfm"))
    except OSError:
        return {}
    sig = {f: os.path.getmtime(os.path.join(MODULES_DIR, f)) for f in files}
    try:
        tp_files = sorted(f for f in os.listdir(THIRD_PARTY_DIR)
                          if f.endswith(".sfm"))
        tp_sig = {f: os.path.getmtime(os.path.join(THIRD_PARTY_DIR, f))
                  for f in tp_files}
    except OSError:
        tp_sig = {}
    sig = (sig, tp_sig)
    if sig == _EXPECT_CACHE["sig"]:
        return _EXPECT_CACHE["data"]
    expected = {}
    for f in files:
        try:
            with zipfile.ZipFile(os.path.join(MODULES_DIR, f)) as z:
                desc = z.read("module-descriptor.xml")
            root = ET.fromstring(desc)
            name = (root.get("name") or "").strip()
            ver = root.get("version")
            if not name or not ver:
                continue
            try:
                ver_i = int(ver)
            except ValueError:
                continue
            expected[name] = {
                "version": ver_i,
                "vendor": (root.get("vendor") or "").strip(),
                "file": f,
                "source": "own",
                "provides": sorted({
                    (ep.get("name") or "").strip()
                    for ep in root.findall(".//rpcEntryPoint")
                    if (ep.get("name") or "").strip()
                }),
            }
        except Exception:
            # kaputte .sfm ignorieren — andere Module bleiben pruefbar
            continue
    merged = _merge_third_party(expected)  # Drittanbieter aus der DB dazu
    _EXPECT_CACHE["sig"], _EXPECT_CACHE["data"] = sig, merged
    return merged


def _merge_third_party(expected: dict) -> dict:
    """Ergänzt hinterlegte Drittanbietermodule (modules.source='third_party').

    Quelle ist die WebApp-DB — nur Module, die ein Admin auf der Modul-Seite
    hochgeladen hat. Versionen werden in int gecastet (STARFACE-Modulversionen);
    unparsbare Einträge werden übersprungen. Eigene Module (app/modules) haben
    Vorrang, falls ein Name je kollidieren sollte (Upload-Seite verhindert das).
    """
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT name, filename, version, vendor FROM modules "
            "WHERE source = 'third_party'").fetchall()
        conn.close()
    except Exception:
        return expected
    for r in rows:
        name = (r["name"] or "").strip()
        if not name:
            continue
        try:
            ver = int((r["version"] or "0").strip())
        except (TypeError, ValueError):
            continue
        expected.setdefault(name, {
            "version": ver,
            "vendor": (r["vendor"] or "Drittanbieter"),
            "file": r["filename"],
            "provides": [],
            "source": "third_party",
        })
    return expected


def _compare_modules(expected: dict, raw: str, *,
                     filter_third_party_missing: bool = False):
    """Vergleicht SOLL-Module (app/modules) mit der GetModuleStatus-Antwort.

    raw = JSON-String des Moduls:
        [{"id","name","version","vendor","instances":[{name,disabled}]}]
    Gibt pro erwartetem Modul einen Status-Eintrag zurueck oder None bei
    einer Fehlerantwort des Moduls ({"error": ...} oder unparsbar).
    """
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):  # Modul meldet internen Fehler
        return None
    installed = {}
    for m in data or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        try:
            ver = int(m.get("version", 0) or 0)
        except (TypeError, ValueError):
            ver = 0
        insts = m.get("instances") or []
        installed[m["name"]] = {
            "version": ver,
            "vendor": (m.get("vendor", "") or ""),
            "instances": [
                {"name": (i.get("name", "") if isinstance(i, dict) else ""),
                 "active": not bool(i.get("disabled", False))}
                for i in insts if isinstance(i, dict)
            ],
        }
    items = []
    for name, exp in expected.items():
        inst = installed.get(name)
        if inst is None:
            # Axel-Regel: Drittanbietermodule auf der Monitoring-Karte nur
            # anzeigen, wenn sie installiert sind (und hinterlegt — expected)
            if filter_third_party_missing and exp.get("source") == "third_party":
                continue
            items.append({
                "name": name, "installed": False, "current": False,
                "version_ist": None, "version_soll": exp["version"],
                "vendor": exp["vendor"], "instances": [],
                "source": exp.get("source", "own"),
                "status": "missing",
            })
            continue
        ver = inst["version"]
        status = "ok" if ver >= exp["version"] else "outdated"
        items.append({
            "name": name, "installed": True, "current": status == "ok",
            "version_ist": ver, "version_soll": exp["version"],
            "vendor": inst["vendor"], "instances": inst["instances"],
            "source": exp.get("source", "own"),
            "status": status,
        })
    return items


def _collect_module_status(inst, token, name, *,
                           filter_third_party_missing: bool = False) -> dict:
    """Ruft GetModuleStatus (Modul v5+) ab und gleicht mit den SOLL-Modulen ab.

    Rückgabe: {"ts", "error": None|{category,msg}, "list": [..]|None}
    - list None      → Status unbekannt (Modul nicht erreichbar/zu alt)
    - list == []     → keine Module erwartet (app/modules leer) → keine Anzeige
    - list == [..]   → Vergleichsliste (missing/outdated/ok je erwartetem Modul)
    """
    base = {"ts": time.time(), "error": None, "list": None}
    expected = _module_expectations()
    if not expected:
        return {**base, "list": []}
    try:
        mres = _xmlrpc(inst["url"], token, "GetModuleStatus",
                       instance_name=inst["monitoring_instance_name"])
    except Exception as e:
        if "starface-fehler" in str(e).lower():
            # GetStats lief, aber GetModuleStatus existiert nicht → Modul zu alt.
            # Update-Ziel ist IMMER das Modul, das GetModuleStatus exportiert
            # (TelefonieMonitoring) — nicht das erste erwartete Modul (CallBlocker)!
            tm = next((m for m in expected.values()
                       if "GetModuleStatus" in m.get("provides", [])), None)
            msg = "Monitoring-Modul-Version zu alt — GetModuleStatus fehlt"
            if tm:
                msg += f" (Update auf v{tm['version']} erforderlich)"
            return {**base, "error": {"category": "module", "msg": msg}}
        return {**base, "error": _classify_error(e)}
    items = _compare_modules(expected, (mres.get("members") or {}).get("moduleJson") or "",
                             filter_third_party_missing=filter_third_party_missing)
    if items is None:
        return {**base, "error": {"category": "module",
                "msg": "Modul-Status konnte nicht ausgewertet werden"}}
    return {**base, "list": items}


def _system_vals(members: dict) -> dict:
    """Zieht die Systemwerte für die Anlagen-Detail-Kacheln (F60) aus GetStats.

    Liefert nur Felder, die der Member wirklich enthält (int/float-Cast defensiv,
    analog build_points): load1/load5/load15, mem_total/mem_free/mem_available,
    cpu_cores.
    """
    out = {}
    for key, mkey in (("load1", "load1"), ("load5", "load5"), ("load15", "load15")):
        try:
            out[key] = float(members[mkey])
        except (KeyError, TypeError, ValueError):
            pass
    for key, mkey in (("mem_total", "memTotal"), ("mem_free", "memFree"),
                      ("mem_available", "memAvailable"), ("cpu_cores", "cpuCores")):
        try:
            out[key] = int(members[mkey])
        except (KeyError, TypeError, ValueError):
            pass
    return out


_HISTORY_CACHE = {}  # installation -> (ts, result)


def query_system_history(installation: str, minutes: int = 60,
                         cache_ttl: float = 15.0) -> dict:
    """Verlaufsdaten (letzte `minutes` Min.) aus dem system-Measurement (F60).

    Flux-Query: 1-Minuten-Mittel der Felder load1/load5/load15/mem_total/
    mem_free/mem_available, gepivotet auf Zeitzeilen. Ergebnis-Cache (15 s)
    entlastet InfluxDB bei den 10-s-Refreshes der Detail-Seiten.

    Rückgabe: {"rows": [{t, load1, ...}, ...]} oder {"error": str} — Aufrufer
    zeigt bei "error" einen Hinweis an (Kacheln funktionieren trotzdem).
    """
    now = time.time()
    hit = _HISTORY_CACHE.get(installation)
    if hit and now - hit[0] < cache_ttl:
        return hit[1]
    if not InfluxDBClient or not INFLUXDB_TOKEN:
        res = {"error": "InfluxDB nicht konfiguriert (INFLUXDB_TOKEN fehlt)"}
        _HISTORY_CACHE[installation] = (now, res)
        return res
    safe = installation.replace('"', '\\"')
    flux = (
        f'from(bucket: "{INFLUXDB_BUCKET}")\n'
        f'  |> range(start: -{int(minutes)}m)\n'
        '  |> filter(fn: (r) => r._measurement == "system")\n'
        f'  |> filter(fn: (r) => r.installation == "{safe}")\n'
        '  |> filter(fn: (r) => r._field == "load1" or r._field == "load5"'
        ' or r._field == "load15"\n'
        '      or r._field == "mem_total" or r._field == "mem_free"'
        ' or r._field == "mem_available")\n'
        '  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)\n'
        '  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
        '  |> keep(columns: ["_time", "load1", "load5", "load15", "mem_total",'
        ' "mem_free", "mem_available"])'
    )
    try:
        with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG,
                            timeout=10_000) as client:
            tables = client.query_api().query(flux)
        rows = []
        fields = ("load1", "load5", "load15", "mem_total", "mem_free", "mem_available")
        for table in tables:
            for rec in table.records:
                row: dict = {"t": int(rec.get_time().timestamp())}
                raw = rec.values
                for f in fields:
                    v = raw.get(f)
                    if v is not None:
                        row[f] = float(v)
                rows.append(row)
        rows.sort(key=lambda r: r["t"])
        res = {"rows": rows}
    except Exception as e:
        res = {"error": str(e)}
    _HISTORY_CACHE[installation] = (now, res)
    return res


def collect_installations() -> int:
    """Ein Poll über alle Installationen mit gesetzter Modul-Instanz."""
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM installations WHERE monitoring_instance_name IS NOT NULL"
        " AND monitoring_instance_name != ''"
    ).fetchall()
    conn.close()
    writes = 0
    errors = []  # (name, exception, ts) — letzter Fehler gewinnt, sonst Reset
    for inst in rows:
        name = inst["name"]
        vals = _state["last_values"].setdefault(name, {})
        try:
            token = _get_token(inst)
            result = _xmlrpc(inst["url"], token, "GetStats",
                             instance_name=inst["monitoring_instance_name"])
            members = result.get("members", {})
            system_name = str(members.get("systemName", ""))
            points = build_points(name, system_name, members)
            writes += _write_points(points)
            vals.update({
                "systemName": system_name,
                "systemVersion": members.get("systemVersion", ""),
                "providers": members.get("providerStatus", ""),
                "points": len(points),
                "ts": time.time(),
                # F60: Systemwerte für die Anlagen-Detail-Seite (Live-Kacheln CPU/RAM)
                "system": _system_vals(members),
            })
            # Modul-Status (nur wenn die App eigene Module ausliefert)
            vals["modules"] = _collect_module_status(
                inst, token, name, filter_third_party_missing=True)
            print(f"[Monitoring] {name}: {len(points)} Points -> InfluxDB")
        except Exception as e:
            errors.append((name, e, time.time()))
            print(f"[Monitoring] FEHLER {name}: {e}")
            cls = _classify_error(e)
            vals["modules"] = {
                "ts": time.time(),
                "error": cls,
                "list": None,
            }
    # Erfolgreicher Zyklus loescht den Fehler; Fehler tragen Zeitstempel (Anzeige + TTL)
    if errors:
        name, e, ts = errors[-1]
        cls = _classify_error(e)
        _state["last_error"] = {"msg": f"{name}: {e}", "ts": ts,
                                "category": cls["category"]}
    else:
        _state["last_error"] = None
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
            _state["last_error"] = {"msg": str(e), "ts": time.time()}
            print(f"[Monitoring] Loop-Fehler: {e}")
        await asyncio.sleep(INTERVAL)


def _provider_summary(raw: str) -> dict:
    """Parsed providerStatus-Zeilen ('Name=Status') zu einem Anzeige-Summary.

    Verbunden = Status exakt 'Registered' (wie bei build_points fürs providers-Measurement).
    """
    providers, disconnected = [], []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        # rsplit am LETZTEN '=': Namen duerfen kein '=' enthalten (Modul liefert
        # 'user@host=State'), aber defensiv gegen alte "register=>..."-Namen,
        # deren '=' den Status sonst verfaelschen wuerde.
        name, status = line.rsplit("=", 1)
        name_s = name.strip()
        status_s = status.strip()
        providers.append(name_s)
        if not status.strip().startswith("Registered"):
            disconnected.append(f"{name_s} ({status_s})")
    return {
        "count": len(providers),
        "connected": len(providers) - len(disconnected),
        "disconnected": disconnected,
        "all_ok": bool(providers) and not disconnected,
        "has_data": bool(providers),
    }


def status() -> dict:
    """Status für die API-Route /api/monitoring/status.

    last_error-Semantik: Er ist genau dann gesetzt, wenn der LETZTE Poll-Zyklus
    einen Fehler hatte (collect_installations resettet ihn bei vollem Erfolg).
    Ein sichtbarer Fehler "besteht" damit per Definition weiter und bleibt so
    lange stehen, bis ein Zyklus fehlerfrei durchläuft — es gibt KEIN
    automatisches Wegblenden nach Zeitablauf bei weiterbestehendem Fehler.
    Undatierte Alt-Format-Strings (ohne ts) können nicht datiert werden -> None.
    """
    le = _state["last_error"]
    if isinstance(le, dict) and le.get("msg"):
        last_error = le
    else:
        last_error = None
    return {
        "running": _state["running"],
        "interval": INTERVAL,
        "influx_url": INFLUXDB_URL,
        "influx_bucket": INFLUXDB_BUCKET,
        "influx_configured": bool(INFLUXDB_TOKEN),
        "last_run": _state["last_run"],
        "last_error": last_error,
        "total_runs": _state["total_runs"],
        "total_writes": _state["total_writes"],
        "installations": {
            name: {**vals, "provider_summary": _provider_summary(vals.get("providers", ""))}
            for name, vals in _state["last_values"].items()
        },
    }
