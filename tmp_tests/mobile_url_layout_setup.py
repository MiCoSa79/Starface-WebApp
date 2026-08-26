#!/usr/bin/env python3
"""Test-Setup: isolierte DB mit Admin-User + Test-Anlage für Mobile-Layout-Test."""
import os, sys, sqlite3, bcrypt, shutil

DB = "/tmp/mobile_test/test.db"
shutil.rmtree("/tmp/mobile_test", ignore_errors=True)
os.makedirs("/tmp/mobile_test", exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER", "MODULE_UPDATE_BASE_URL"):
    os.environ.pop(var, None)

sys.path.insert(0, "/opt/data/profiles/axel/Projekte/Starface-WebApp/repo/app")
import main
main.init_db()

conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO installations (name,url,auth_id,auth_pass,module_instance_name,monitoring_instance_name,is_starface10) VALUES (?,?,?,?,?,?,?)",
             ("TestAnlage", "https://pbx.example.de", "0001", "secret", "mod1", "mon1", 1))
conn.commit()
conn.close()
print("DB ready:", DB)
