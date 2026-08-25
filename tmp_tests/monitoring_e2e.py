#!/usr/bin/env python3
"""Tests für den Telefonie-Monitoring-Sammler (members-Parsing + InfluxDB-Points).

Kein InfluxDB-Server nötig: _write_points wird ohne Token nie aufgerufen.
Aufruf: .venv/bin/python tmp_tests/monitoring_e2e.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

try:
    from app import monitoring
    from app.main import _xmlrpc_value
except ImportError:
    import monitoring
    from main import _xmlrpc_value

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# 1. _xmlrpc_value: Typ-Konvertierung
check("_xmlrpc_value string", _xmlrpc_value(ET.fromstring("<value><string>abc</string></value>").find("string")) == "abc")
check("_xmlrpc_value int", _xmlrpc_value(ET.fromstring("<value><int>42</int></value>").find("int")) == 42)
check("_xmlrpc_value double", _xmlrpc_value(ET.fromstring("<value><double>0.25</double></value>").find("double")) == 0.25)
check("_xmlrpc_value boolean", _xmlrpc_value(ET.fromstring("<value><boolean>1</boolean></value>").find("boolean")) is True)

# 2. build_points aus GetStats-typischen members
members = {
    "systemName": "pbx-kraemer",
    "systemVersion": "10.0.2.5",
    "memTotal": 16384000, "memFree": 4096000, "memAvailable": 8192000,
    "buffers": 1024000, "cached": 4096000, "swapCached": 0,
    "active": 8192000, "inactive": 4096000,
    "load1": "0.12", "load5": "0.34", "load15": "0.56",
    "procsRunning": 2, "procsTotal": 201, "cpuCores": 8,
    "providerStatus": "providerA=Registered\nproviderB=Not registered",
    "providerNames": "providerA;providerB",
}
points = monitoring.build_points("Kraemer", members.get("systemName", ""), members)
check("build_points: 3 Points (system + 2 provider)", len(points) == 3, f"len={len(points)}")
lp = [p.to_line_protocol() for p in points]
sys_line = [l for l in lp if l.startswith("system")][0]
check("system: Tags installation+host", "installation=Kraemer" in sys_line and "host=pbx-kraemer" in sys_line, sys_line)
check("system: Version-String-Feld", 'version="10.0.2.5"' in sys_line, sys_line)
check("system: mem_total", "mem_total=16384000" in sys_line, sys_line)
check("system: load1 float", "load1=0.12" in sys_line, sys_line)
check("system: cpu_cores", "cpu_cores=8" in sys_line, sys_line)
prov_reg = [l for l in lp if l.startswith("providers") and "providerA" in l]
prov_not = [l for l in lp if l.startswith("providers") and "providerB" in l]
check("providerA: registered=1", bool(prov_reg) and "registered=1" in prov_reg[0], prov_reg)
check("providerB: registered=0", bool(prov_not) and "registered=0" in prov_not[0], prov_not)
# rsplit-Regression: Name mit '=' (altes \"register=>...\"-Format) darf den Status nicht verfaelschen
prov_eq = [p.to_line_protocol() for p in monitoring.build_points("Kraemer", "pbx", {"providerStatus": "register=>user:geheim@host:5060/1=Registered"}) if p.to_line_protocol().startswith("providers")]
check("build_points rsplit: '=' im Namen", bool(prov_eq) and "registered=1" in prov_eq[0], prov_eq)

# 3. members-Parsing des _xmlrpc-Antwortformats (GetStats-Struct)
xml = """<?xml version="1.0"?><methodResponse><params><param><value><struct>
  <member><name>systemName</name><value><string>pbx-kraemer</string></value></member>
  <member><name>memTotal</name><value><int>16384000</int></value></member>
  <member><name>load1</name><value><string>0.12</string></value></member>
  <member><name>procsRunning</name><value><int>2</int></value></member>
  <member><name>providerStatus</name><value><string>providerA=Registered&#10;providerB=Not registered</string></value></member>
</struct></value></param></params></methodResponse>"""
root = ET.fromstring(xml)
members_parsed = {}
for member in root.iter("member"):
    name_el = member.find("name")
    if name_el is None or not name_el.text or not name_el.text.strip():
        continue
    for cand in member.iter():
        if cand is member:
            continue
        if cand.tag in ("string", "int", "i4", "boolean", "double") and cand.text and cand.text.strip():
            members_parsed[name_el.text.strip()] = _xmlrpc_value(cand)
            break
check("members: systemName", members_parsed.get("systemName") == "pbx-kraemer", str(members_parsed))
check("members: memTotal int", members_parsed.get("memTotal") == 16384000, str(members_parsed.get("memTotal")))
check("members: load1 string", members_parsed.get("load1") == "0.12")
check("members: providerStatus mit Zeilenumbruch",
      members_parsed.get("providerStatus") == "providerA=Registered\nproviderB=Not registered")

# 4. status() ohne Token -> keine Fehler, Configured-Flag false
s = monitoring.status()
check("status: influx_configured False ohne Token", s["influx_configured"] is False)
check("status: bucket telefonie", s["influx_bucket"] == "telefonie")

print()
if FAIL:
    print("FEHLER:", ", ".join(FAIL))
    sys.exit(1)
print("ALLE TESTS OK")
