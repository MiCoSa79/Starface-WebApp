#!/usr/bin/env python3
"""
Verifikation der STARFACE-Referenz-Verdrahtung im module-descriptor.xml.

Repliziert ExecutableObject.validate() (Bytecode-verifiziert, STARFACE 10.0.2.5):
- Output-Variablen: JEDER nicht-leere <value> wird als Referenz aufgelöst
  (getVar: Match erst per id, dann per name in den sichtbaren Variablen).
  Kein Treffer -> VariableNotFoundError('name') -> Import bricht.
- Input-Variablen: nur wenn valueByReference=true UND value nicht leer.
- Sichtbar: eigene input/outputVars + input/outputVars des Parent.
"""
import sys
import xml.etree.ElementTree as ET

def norm(s):
    return (s or '').strip()

def get_var(vars_, key):
    """getVar(Collection, String): erst ID-Match, dann Name-Match."""
    key = norm(key)
    if not key:
        return None
    for v in vars_:
        if norm(v.get('id')) == key:
            return v
    for v in vars_:
        if norm(v.get('name')) == key:
            return v
    return None

def type_matches(a, b):
    """isAssignmentAllowed(FROM, TO, false) — hier: nur Gleichheit geprüft."""
    return a == b

def collect_vars(inputs, outputs):
    return (inputs or []) + (outputs or [])

def check_variable(v, where, visible, scope, errors):
    val = norm(v.findtext('.//value') if v.find('value') is not None else None)
    val = v.find('value')
    val_text = norm(val.text) if val is not None else None
    byref = v.get('valueByReference') == 'true'
    # Output-Semantik: immer prüfen; Input: nur bei byRef=true
    is_output = where.endswith('OUT')
    if (is_output and val_text) or (not is_output and byref and val_text):
        found = get_var(visible, val_text)
        if found is None:
            errors.append(f"{scope}: {where} '{v.get('name')}' (id={v.get('id')}) "
                          f"referenziert '{val_text}' — nicht auflösbar (→ VariableNotFoundError)")
        elif not type_matches(found.get('type'), v.get('type')):
            errors.append(f"{scope}: {where} '{v.get('name')}' Typ {v.get('type')} "
                          f"vs. Ziel '{found.get('name')}' Typ {found.get('type')}")

def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    errors = []
    funcs = root.findall('.//function')
    # ElementTree-find unterstützt KEIN '..' — Parent über echte Baum-Map lösen.
    parent_map = {c: p for p in root.iter() for c in p}
    for fn in funcs:
        fname = fn.get('name')
        is_wrapper = fn.find('children/functionCall') is not None
        is_java = fn.find('implementationFile') is not None
        if is_java and not is_wrapper:
            # Java-Funktionen: Variablen kommen aus den @InputVar/@OutputVar-
            # Annotationen, Descriptor-Defaults (value='0'/'false') werden von
            # der Validierung nicht geprüft (real beobachtet: Modul importierte
            # mit CallBlocker BlockStatus value='false' + ListAdd value='0').
            continue
        inputs = fn.find('inputVars').findall('variable') if fn.find('inputVars') is not None else []
        outputs = fn.find('outputVars').findall('variable') if fn.find('outputVars') is not None else []
        visible = collect_vars(inputs, outputs)
        # Parent (Modul bzw. Eltern-Funktion) input/output —
        # Referenzen können per id/name auf Variablen der Modulebene zeigen
        # (Blacklist-v64-Beweis: forEachInList list-value = UUID der
        # Modul-<inputVars>-Variable, accessRights=Read).
        pnode = None
        cnode = parent_map.get(fn)  # fn's parent ist <children> des Moduls/der Funktion
        gnode = parent_map.get(cnode) if cnode is not None else None
        pnode = gnode if gnode is not None and gnode.tag in ('module', 'function') else None
        if pnode is not None:
            pi = pnode.find('inputVars').findall('variable') if pnode.find('inputVars') is not None else []
            po = pnode.find('outputVars').findall('variable') if pnode.find('outputVars') is not None else []
            visible = visible + pi + po
        for v in inputs:
            check_variable(v, 'IN', visible, fname, errors)
        for v in outputs:
            check_variable(v, 'OUT', visible, fname, errors)
        if is_wrapper:
            for fc in fn.findall('children/functionCall'):
                ci = fc.find('inputVars').findall('variable') if fc.find('inputVars') is not None else []
                co = fc.find('outputVars').findall('variable') if fc.find('outputVars') is not None else []
                t = fc.find('target')
                tname = t.get('targetName') if t is not None else '?'
                for v in ci:
                    check_variable(v, 'C-IN', visible, f"{fname} → {tname}", errors)
                for v in co:
                    check_variable(v, 'C-OUT', visible, f"{fname} → {tname}", errors)
    if errors:
        print(f"FEHLER ({len(errors)}):")
        for e in errors:
            print(' -', e)
        sys.exit(1)
    print(f"OK: {len(funcs)} Funktionen geprüft, alle Referenzen auflösbar + typ-konsistent.")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'module/module-descriptor.xml')
