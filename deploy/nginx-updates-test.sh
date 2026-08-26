#!/bin/bash
# nginx-updates-test.sh — Roundtrip-Test für die secure_link-Config (Task 2)
#
# Testet auf ZimaOS (Docker): ohne Signatur → 403 | abgelaufen → 410 | gültig → 200
# Signaturen werden VOR dem Test mit lokalem openssl berechnet (Feldreihenfolge
# exakt wie nginx: MD5("<expires><uri> <secret>") → base64url ohne Padding).
#
# Aufruf (ZimaOS-Shell, im Ordner mit nginx-updates.conf und modules/):
#   bash nginx-updates-test.sh
set -u

PORT=8896
SECRET="dev-test-secret"            # NUR Testwert; Produktiv-Sekret ersetzt Task 4
CNT="nginx-updates-test"
TESTDIR="$(mktemp -d /tmp/nginx-updates-test.XXXXXX)"
echo "Testordner: $TESTDIR"

cleanup() {
    echo; echo "── Aufräumen ──"
    docker rm -f "$CNT" >/dev/null 2>&1 || true
    rm -rf "$TESTDIR"
    echo "fertig (Container entfernt, Testordner gelöscht)."
}
trap cleanup EXIT

# ── 1. Testdaten (modul-Paket-Attrappe + Manifest) ──────────────────────────
mkdir -p "$TESTDIR/modules"
head -c 4096 /dev/urandom > "$TESTDIR/modules/DummyProbe_v1.sfm"
cat > "$TESTDIR/modules/versions.json" <<'JSON'
{"moduleName":"DummyProbe","versions":[{"moduleVersion":1,"ring":"LTS","downloadUrl":"https://modulupdates.meiser.family/modules/DummyProbe_v1.sfm","md5":"d41d8cd98f00b204e9800998ecf8427e"}]}
JSON

# ── 2. Secret in die nginx-Config einsetzen (nicht committen!) ───────────────
# Config liegt im selben Ordner wie dieses Skript (portabel: Repo-Checkout, /tmp nach curl …)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/nginx-updates.conf"
[ -f "$CONF" ] || { echo "FEHLER: $CONF nicht gefunden — Skript + nginx-updates.conf in denselben Ordner legen"; exit 1; }
sed "s|<UPDATE_SIGNING_SECRET>|$SECRET|g" "$CONF" > "$TESTDIR/nginx-updates.conf"
echo "Config mit Secret verdrahtet: $(grep -c 'secure_link_md5' "$TESTDIR/nginx-updates.conf") secure_link_md5-Zeile(n)"

# ── 3. Testcontainer starten ─────────────────────────────────────────────────
echo "Starte nginx:alpine Testcontainer auf Port $PORT …"
docker rm -f "$CNT" >/dev/null 2>&1 || true
docker run -d --name "$CNT" -p "$PORT:80" \
    -v "$TESTDIR/modules:/usr/share/nginx/html:ro" \
    -v "$TESTDIR/nginx-updates.conf:/etc/nginx/conf.d/default.conf:ro" \
    nginx:alpine >/dev/null || { echo "FEHLER: Container-Start"; exit 1; }
sleep 2

# ── 4. Signaturen berechnen (lokales openssl, exakt nginx-Schema) ───────────
sign() { # $1=expires $2=uri → base64url-md5
    printf '%s' "$1$2 $SECRET" | openssl dgst -md5 -binary | openssl base64 | tr -d '=\n' | tr '+/' '-_'
}
NOW="$(date +%s)"
EXP_OK=$((NOW + 300))                                  # gültig: +5 min
EXP_OLD=$((NOW - 60))                                  # abgelaufen: -60 s
SIG_MOD_OK="$(sign "$EXP_OK" "/modules/DummyProbe_v1.sfm")"
SIG_MOD_OLD="$(sign "$EXP_OLD" "/modules/DummyProbe_v1.sfm")"
SIG_VER_OK="$(sign "$EXP_OK" "/versions.json")"
SIG_VER_OLD="$(sign "$EXP_OLD" "/versions.json")"

# ── 5. Tests ─────────────────────────────────────────────────────────────────
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1"; }
pass=0; fail=0
t() { # $1=Name $2=erwartet $3=tatsächlich
    if [ "$2" = "$3" ]; then echo "OK   $1 (HTTP $3)"; pass=$((pass+1));
    else echo "FAIL $1 (erwartet $2, war $3)"; fail=$((fail+1)); fi
}

echo; echo "── Tests ──"
t "ohne Signatur       → 403"  403 "$(code "http://127.0.0.1:$PORT/modules/DummyProbe_v1.sfm")"
t "ohne Signatur ver.  → 403"  403 "$(code "http://127.0.0.1:$PORT/versions.json")"
t "abgelaufen          → 410"  410 "$(code "http://127.0.0.1:$PORT/modules/DummyProbe_v1.sfm?expires=$EXP_OLD&md5=$SIG_MOD_OLD")"
t "gültig (200+Bodysize) → 200" 200 "$(code "http://127.0.0.1:$PORT/modules/DummyProbe_v1.sfm?expires=$EXP_OK&md5=$SIG_MOD_OK")"
t "gültig versions.json → 200" 200 "$(code "http://127.0.0.1:$PORT/versions.json?expires=$EXP_OK&md5=$SIG_VER_OK")"
t "falsche Signatur     → 403" 403 "$(code "http://127.0.0.1:$PORT/modules/DummyProbe_v1.sfm?expires=$EXP_OK&md5=FALSCH")"

# ── 6. Gültiger Download: Inhalt verifizieren ────────────────────────────────
echo; echo "── Inhalts-Check (gültige URL) ──"
curl -s "http://127.0.0.1:$PORT/modules/DummyProbe_v1.sfm?expires=$EXP_OK&md5=$SIG_MOD_OK" -o "$TESTDIR/downloaded.sfm"
if cmp -s "$TESTDIR/modules/DummyProbe_v1.sfm" "$TESTDIR/downloaded.sfm"; then
    echo "OK   heruntergeladene Datei == Original (4096 Bytes)"; pass=$((pass+1));
else
    echo "FAIL Download-Inhalt weicht ab"; fail=$((fail+1));
fi

echo; echo "──────────────────────────────────────────────"
echo "ERGEBNIS: $pass OK, $fail FAIL"
[ "$fail" -eq 0 ] || exit 1
echo "Task-2-Verifikation BESTANDEN"
