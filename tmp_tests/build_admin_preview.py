#!/usr/bin/env python3
"""Baut die Admin-Previews (F62-Split: anlagen/benutzer/rechte/grundeinstellungen)
mit Testdaten für den CDP-Browser-Test."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))  # noqa

from jinja2 import Environment, FileSystemLoader  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = Path("/opt/data/admin-preview")
OUT.mkdir(exist_ok=True)

env = Environment(loader=FileSystemLoader(str(REPO / "app" / "templates")))

inst = [
    SimpleNamespace(id=1, name="Hauptstandort Eppelborn", url="https://pbx.meiser.de", is_starface10=True),
    SimpleNamespace(id=2, name="Produktion", url="https://10.0.25.60:4444", is_starface10=True),
    SimpleNamespace(id=3, name="Testumgebung", url="https://test.pbx.internal", is_starface10=False),
    SimpleNamespace(id=4, name="Filiale Saarbrücken", url="https://filiale-sb.pbx.de", is_starface10=False),
    SimpleNamespace(id=5, name="Archiv", url="https://old.pbx.meiser.de", is_starface10=False),
]
users = [
    SimpleNamespace(id=1, username="admin", is_admin=True, otp_secret=None, otp_confirmed=True),
    SimpleNamespace(id=2, username="anna.kraemer", is_admin=False, otp_secret="S3CRET", otp_confirmed=True),
    SimpleNamespace(id=3, username="bernd.schmitt", is_admin=False, otp_secret="PEND", otp_confirmed=False),
]
access = [
    SimpleNamespace(user_id=1, installation_id=1, can_read=True, can_write=True),
    SimpleNamespace(user_id=3, installation_id=2, can_read=True, can_write=True),
    SimpleNamespace(user_id=3, installation_id=4, can_read=True, can_write=False),
    SimpleNamespace(user_id=2, installation_id=2, can_read=True, can_write=False),
]
request = SimpleNamespace(query_params={})
common = dict(
    user=SimpleNamespace(username="admin", is_admin=True, id=1),
    version="v1.0.54-preview",
    request=request,
)
pages = [
    ("anlagen", dict(active="anlagen", installations=inst)),
    ("benutzer", dict(active="benutzer", users=users)),
    ("rechte", dict(active="rechte", users=users, installations=inst, access=access)),
    ("grundeinstellungen", dict(active="grundeinstellungen",
                                module_update_base_url_value="", module_update_base_fallback="")),
]
for name, extra in pages:
    ctx = {**common, **extra}
    html = env.get_template(f"{name}.html").render(**ctx)
    out = OUT / f"{name}_preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"OK: {out} ({len(html) // 1024} KB)")
