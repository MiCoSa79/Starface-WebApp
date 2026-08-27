"""Update-Server-Spiegel: Modulpakete aus dem Image nach /data/modules spiegeln.

Kopiert alle ausgelieferten .sfm (app/modules) in den nginx-html-Root
(/data/modules im Stack) und schreibt daneben versions.json (is-Manifest im
Muster der Fluxpunkt-Analyse: {modules: [{moduleName, versions: [...]}]}).
Die downloadUrl zeigt auf die Update-URL-Basis; die Signatur (expires&md5)
ergänzt die WebApp zur Laufzeit über updatesign.build_signed_url().

Datenquelle je Paket: module-descriptor.xml (version-/specVersion-Attribut),
gleiche Konvention wie monitoring._module_expectations().
"""
import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile


def _read_module_info(path: str) -> dict | None:
    """Liest name/version/specVersion eines .sfm (ZIP) aus module-descriptor.xml.

    Gibt None zurück, wenn die Datei kein gültiges .sfm ist (kein ZIP oder
    kein Descriptor) — wird dann beim Spiegeln ignoriert.
    """
    try:
        with zipfile.ZipFile(path) as z:
            desc = z.read("module-descriptor.xml").decode("utf-8", "replace")
        root = ET.fromstring(desc)
    except Exception:
        return None
    return {
        "name": root.get("name", ""),
        "version": root.get("version", "0"),
        "specVersion": root.get("specVersion", ""),
        "vendor": root.get("vendor", ""),
    }


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_base(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def build_versions_json(sfm_files: list, base_url: str = "") -> dict:
    """Baut das versions.json-Manifest für die gegebenen .sfm-Dateien."""
    base = _normalize_base(base_url)
    modules = []
    for path in sorted(sfm_files):
        info = _read_module_info(path)
        fname = os.path.basename(path)
        # Ohne Base-URL nur relativer Pfad (lokal erreichbar, nicht von außen)
        url = f"/modules/{fname}" if not base else f"{base}/modules/{fname}"
        modules.append({
            "moduleName": info["name"] if info else fname,
            "versions": [{
                "moduleVersion": info["version"] if info else "0",
                "ring": "stable",
                "downloadUrl": url,
                "md5": _file_md5(path),
                "compatibility": info["specVersion"] if info else "",
            }],
        })
    return {"modules": modules}


def mirror_modules(src_dir: str, dst_dir: str, base_url: str = "") -> dict:
    """Spiegelt alle .sfm aus src_dir nach dst_dir und schreibt versions.json.

    - kopiert NUR .sfm-Dateien (andere/kaputte Dateien werden ignoriert)
    - überschreibt vorhandene Dateien (idempotent, keine Duplikate)
    - entfernt verwaiste EIGENE Pakete im Ziel (Vendor 'Axel Meiser - Kraemer IT',
      Quelle nicht mehr im Image — z. B. nach Umbenennung); Drittanbieter bleiben
    - versions.json landet im Ziel (nginx html-Root serviert beide)
    Returns das geschriebene Manifest.
    """
    os.makedirs(dst_dir, exist_ok=True)
    # versions.json gehört in den html-ROOT (/versions.json), NICHT nach modules/:
    # nginx serviert <html-Root>/versions.json und <html-Root>/modules/*.sfm
    html_root = os.path.dirname(dst_dir.rstrip(os.sep)) or os.sep
    sfm_files = []
    own_names = set()
    for fname in sorted(os.listdir(src_dir)):
        if not fname.endswith(".sfm"):
            continue
        own_names.add(fname)
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        try:
            shutil.copy2(src, dst)
            # gültiges .sfm (ZIP + Descriptor)? sonst wieder entfernen
            if _read_module_info(dst) is None:
                os.remove(dst)
                continue
            sfm_files.append(dst)
        except (OSError, zipfile.BadZipFile):
            continue
    # Stale-Cleanup (F49): verwaiste EIGENE Pakete aus dem Ziel entfernen.
    # Eigene Pakete tragen Vendor "Axel Meiser - Kraemer IT" und stammen
    # ausschließlich aus dem Image (own_names). Liegt im Ziel ein eigenes Paket,
    # dessen Quelle im Image nicht mehr existiert (Umbenennung/Abkündigung,
    # z. B. UpdateDeployer → Deployment-Modul), wird es gelöscht.
    # Drittanbieter (anderer Vendor) bleiben unangetastet.
    for fname in sorted(os.listdir(dst_dir)):
        if not fname.endswith(".sfm") or fname in own_names:
            continue
        extra = os.path.join(dst_dir, fname)
        info = _read_module_info(extra)
        if info is not None and info["vendor"] == "Axel Meiser - Kraemer IT":
            try:
                os.remove(extra)
            except OSError:
                continue
            print(f"[UpdateServer] Stale eigenes Paket entfernt: {fname}")
    # Drittanbieter-Module (Admin-Uploads der Modul-Seite) liegen als .sfm im
    # Zielverzeichnis, stammen aber NICHT aus dem Image → gehören ebenfalls ins
    # versions.json-Manifest (Deployment-Modul lädt sie über dieselbe signierte
    # URL). Nur gültige Pakete (ZIP + Descriptor) werden aufgenommen.
    for fname in sorted(os.listdir(dst_dir)):
        if not fname.endswith(".sfm") or fname in own_names:
            continue
        extra = os.path.join(dst_dir, fname)
        if _read_module_info(extra) is not None:
            sfm_files.append(extra)
    sfm_files = sorted(set(sfm_files))
    manifest = build_versions_json(sfm_files, base_url)
    with open(os.path.join(html_root, "versions.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    # Legacy aufräumen: erste Version (v0.0.157) schrieb versions.json fälschlich
    # nach modules/ — die Datei dort stammt von uns und wird entfernt.
    legacy = os.path.join(dst_dir, "versions.json")
    if os.path.exists(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass
    return manifest
