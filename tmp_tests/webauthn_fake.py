"""Minimaler Software-WebAuthn-Authenticator fuer Tests (Starface-WebApp F58).

Erzeugt Registration-/Assertion-Daten, die fido2 2.2 (Server-Verifikation)
akzeptiert: Registrierung mit Attestation-Format 'none', Login mit
ECDSA-P-256 (ES256) als rohe r||s-Signatur (kein DER).

Nutzung (in Tests):
    key = new_ec_key()
    cd_b64u, att_b64u, cred_id, pk_cbor = register_attestation(rp_id, origin, challenge_b64u, key)
    assertion = login_assertion(rp_id, origin, challenge_b64u, key)
"""
import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_bytes(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def cose_public_key(pub):
    pn = pub.public_numbers()
    return {1: 2, 3: -7, -1: 1, -2: pn.x.to_bytes(32, "big"), -3: pn.y.to_bytes(32, "big")}


def _sign_raw(key, data: bytes) -> bytes:
    der = key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def make_auth_data(rp_id: str, flags: int, sign_count: int, *, aaguid=None,
                   credential_id=None, cose_key=None) -> bytes:
    rp_hash = hashlib.sha256(rp_id.encode()).digest()
    parts = [rp_hash, bytes([flags]), int(sign_count).to_bytes(4, "big")]
    if aaguid is not None:
        parts += [aaguid, len(credential_id).to_bytes(2, "big"),
                  credential_id, cbor2.dumps(cose_key)]
    return b"".join(parts)


def make_client_data(typ: str, challenge_b64u: str, origin: str) -> bytes:
    return json.dumps(
        {"type": typ, "challenge": challenge_b64u, "origin": origin,
         "crossOrigin": False}, separators=(",", ":")).encode()


def register_attestation(rp_id: str, origin: str, challenge_b64u: str, key,
                         sign_count: int = 0):
    """→ (clientDataJSON_b64u, attestationObject_b64u, credential_id, public_key_cbor)"""
    pub = key.public_key()
    cred_id = os.urandom(16)
    cose = cose_public_key(pub)
    auth = make_auth_data(rp_id, 0x45, sign_count, aaguid=b"\x00" * 16,
                          credential_id=cred_id, cose_key=cose)
    cd = make_client_data("webauthn.create", challenge_b64u, origin)
    att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
    return _b64u(cd), _b64u(att), cred_id, cbor2.dumps(cose)


def login_assertion(rp_id: str, origin: str, challenge_b64u: str, key,
                    sign_count: int = 1, user_handle: bytes = b"\x01" * 16):
    """→ Assertion-Dict (Feldwerte base64url), direkt als credential['response'] nutzbar"""
    auth = make_auth_data(rp_id, 0x05, sign_count)
    cd = make_client_data("webauthn.get", challenge_b64u, origin)
    # Signiert wird die ROH-Nachricht authData||SHA256(clientDataJSON);
    # cryptography hasht intern — NICHT vorher hashen! Der Server (App)
    # wandelt RAW r||s → DER (fido2 2.2/ES256 erwartet DER).
    msg = auth + hashlib.sha256(cd).digest()
    der = key.sign(msg, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")  # raw r||s wie Browser
    return {"clientDataJSON": _b64u(cd), "authenticatorData": _b64u(auth),
            "signature": _b64u(sig), "userHandle": _b64u(user_handle)}
