"""Web Push direkt an die Dashboard-App (iPhone ab iOS 16.4, App vom Homebildschirm), ohne Fremddienst.

Ablauf: Die App abonniert Pushes mit dem öffentlichen VAPID-Schlüssel, verschlüsselt das Abo mit demselben
Schlüssel (ECDH + HKDF + AES-GCM, siehe docs/index.html) und schickt es als GitHub-Issue (Label "push").
Der Run legt das verschlüsselte Abo in status.json ab (öffentlich, aber nur mit dem geheimen VAPID-Schlüssel
lesbar). Verschickt wird im Workflow-Schritt "Pushes senden": Inhalt nach RFC 8291 (aes128gcm) verschlüsselt,
Absender per VAPID (RFC 8292) signiert. Der geheime Schlüssel steht nur im GitHub-Secret VAPID_PRIVATE_KEY"""

import base64
import hashlib
import json
import os
import time
from urllib.parse import urlparse

import http_ece
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ABO_SALT = b"trikot-tracker-1"     # muss zu docs/index.html passen
ABO_INFO = b"trikot-push-abo"
VAPID_SUB = "https://tobl1.github.io/trikot-tracker/"   # Absender-Angabe (Pflicht bei VAPID), keine Mailadresse


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def private_key(pem=None):
    pem = pem or os.environ.get("VAPID_PRIVATE_KEY", "")
    return serialization.load_pem_private_key(pem.encode(), None) if pem.strip() else None


def public_key_b64(key):
    """Öffentlicher Schlüssel im Format, das die App braucht (applicationServerKey)"""
    return b64u(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def _abo_key(shared):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ABO_SALT, info=ABO_INFO).derive(shared)


def open_abo(blob, key):
    """Verschlüsseltes Abo aus der App ("v1.<ephemeral>.<iv>.<daten>") entschlüsseln -> dict oder None"""
    try:
        version, eph, iv, data = blob.strip().split(".")
        if version != "v1":
            return None
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(eph))
        plain = AESGCM(_abo_key(key.exchange(ec.ECDH(), peer))).decrypt(unb64u(iv), unb64u(data), None)
        sub = json.loads(plain)
        return sub if sub.get("endpoint", "").startswith("https://") and sub.get("keys") else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    except Exception:   # z. B. falscher Schlüssel (InvalidTag)
        return None


def seal_abo(sub, public_b64):
    """Gegenstück zur App (nur für Tests): Abo so verschlüsseln, wie es docs/index.html tut"""
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(public_b64))
    eph = ec.generate_private_key(ec.SECP256R1())
    iv = os.urandom(12)
    data = AESGCM(_abo_key(eph.exchange(ec.ECDH(), peer))).encrypt(iv, json.dumps(sub).encode(), None)
    raw = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return f"v1.{b64u(raw)}.{b64u(iv)}.{b64u(data)}"


def abo_id(sub):
    return hashlib.sha256(sub["endpoint"].encode()).hexdigest()[:16]


def vapid_header(endpoint, key):
    """Authorization-Header nach RFC 8292: JWT (ES256), gültig 12 Std., plus öffentlicher Schlüssel"""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(endpoint))
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": origin, "exp": int(time.time()) + 12 * 3600, "sub": VAPID_SUB}).encode())
    r, s = utils.decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{claims}.{sig}, k={public_key_b64(key)}"


def encrypt(sub, payload):
    """Inhalt für genau dieses Abo verschlüsseln (RFC 8291, aes128gcm)"""
    return http_ece.encrypt(payload, private_key=ec.generate_private_key(ec.SECP256R1()),
                            dh=unb64u(sub["keys"]["p256dh"]), auth_secret=unb64u(sub["keys"]["auth"]),
                            version="aes128gcm")


def send(sub, message, key, ttl=24 * 3600):
    """Eine Push an ein Abo schicken. message: {"title", "body", "url"}. Gibt den HTTP-Status zurück
    (201 = angenommen, 404/410 = Abo erloschen, in der App neu aktivieren)"""
    body = encrypt(sub, json.dumps(message, ensure_ascii=False).encode())
    headers = {"Authorization": vapid_header(sub["endpoint"], key), "TTL": str(ttl), "Urgency": "high",
               "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream"}
    try:
        return requests.post(sub["endpoint"], data=body, headers=headers, timeout=20).status_code
    except requests.RequestException:
        return 0
