"""Web Push ohne Netz: Abo-Verschlüsselung (App -> Tracker), Inhaltsverschlüsselung (RFC 8291), VAPID-Signatur"""
import json
import sys
from pathlib import Path

import http_ece
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trikot import webpush  # noqa: E402

KEY = ec.generate_private_key(ec.SECP256R1())
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()


def device():
    """Simuliertes iPhone: eigenes Schlüsselpaar und auth-Geheimnis wie bei pushManager.subscribe()"""
    dev = ec.generate_private_key(ec.SECP256R1())
    raw = dev.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    sub = {"endpoint": "https://web.push.apple.com/QAbc123", "keys": {"p256dh": webpush.b64u(raw), "auth": webpush.b64u(auth)}}
    return dev, auth, sub


def test_abo_hin_und_zurueck():
    _, _, sub = device()
    key = webpush.private_key(PEM)
    blob = webpush.seal_abo(sub, webpush.public_key_b64(key))
    assert blob.startswith("v1.") and "apple" not in blob             # Abo ist nicht lesbar
    assert webpush.open_abo(blob, key) == sub
    assert webpush.open_abo(blob, ec.generate_private_key(ec.SECP256R1())) is None   # falscher Schlüssel
    assert webpush.open_abo("kaputt", key) is None


def test_inhalt_nur_fuers_geraet_lesbar():
    dev, auth, sub = device()
    body = webpush.encrypt(sub, json.dumps({"title": "🔥 Thiago", "body": "Bayern 2015/16"}).encode())
    plain = http_ece.decrypt(body, private_key=dev, auth_secret=auth, version="aes128gcm")
    assert json.loads(plain)["title"] == "🔥 Thiago"


def test_vapid_signatur_gueltig():
    header = webpush.vapid_header("https://web.push.apple.com/QAbc123", KEY)
    t = header.split("t=")[1].split(",")[0]
    head, claims, sig = t.split(".")
    raw = webpush.unb64u(sig)
    der = utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    KEY.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))   # wirft bei Fehler
    c = json.loads(webpush.unb64u(claims))
    assert c["aud"] == "https://web.push.apple.com" and c["sub"].startswith("https://")
    assert header.endswith("k=" + webpush.public_key_b64(KEY))
