#!/usr/bin/env python3
"""Test-Setup: isolierte DB mit Admin- + Normaluser für Menü-Umbau-CDP-Test."""
import os, sys, sqlite3, bcrypt, shutil

DB = "/tmp/menu_test/test.db"
shutil.rmtree("/tmp/menu_test", ignore_errors=True)
os.makedirs("/tmp/menu_test", exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "WEBAUTHN_PASSWORDLOGIN"):
    os.environ.pop(var, None)

sys.path.insert(0, "/opt/data/profiles/axel/Projekte/Starface-WebApp/repo/app")
import main
main.init_db()

conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("axel", bcrypt.hashpw(b"pw456", bcrypt.gensalt()).decode(), 0))
conn.commit()
conn.close()
print("DB ready:", DB)
