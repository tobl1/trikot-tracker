"""Benachrichtigungen (ntfy) und Textbausteine dafür"""

import datetime as dt
import os
import sys
import uuid

import requests

from . import speicher, webpush
from .basis import SIZE_RX, norm, now

OUTBOX_MAX_HOURS = 12   # ältere, nie verschickte Pushes verwerfen statt veraltet nachzuliefern

# Postausgang: Pushes eines Runs werden hier gesammelt und erst NACH dem Speichern verschickt
# (Workflow-Schritt "Pushes senden"). Scheitert das Speichern, geht nichts raus und der nächste Run
# meldet dieselben Treffer noch einmal richtig; nichts kommt doppelt, nichts geht verloren
POSTAUSGANG = []


def push(topic, title, message, prio=3, click=None, image=None, tags=None, dry=False, nur_abo=None):
    """Push vormerken (Probelauf: nur anzeigen). Das ntfy-Thema wird nie gespeichert.
    nur_abo: nur an dieses App-Abo (z. B. Bestätigung nach dem Aktivieren), nicht an ntfy"""
    entry = {"id": uuid.uuid4().hex, "zeit": now().isoformat(), "title": title[:250], "message": message[:3500],
             "prio": prio, "click": click or "", "image": image or "", "tags": tags or []}
    if nur_abo:
        entry["nur_abo"] = nur_abo
    if dry or not topic:
        print(f"[PUSH p{prio}] {title}\n    {message}\n    {click or ''}")
        return
    POSTAUSGANG.append(entry)


def send_now(topic, entry):
    """Einen Push an ntfy schicken; True, wenn ntfy ihn angenommen hat"""
    payload = {"topic": topic, "title": entry["title"], "message": entry["message"],
               "priority": entry.get("prio", 3), "tags": entry.get("tags") or []}
    if entry.get("click"):
        payload["click"] = entry["click"]
    if str(entry.get("image") or "").startswith("http"):
        payload["attach"] = entry["image"]
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    for attempt in range(3):
        try:
            r = requests.post(server, json=payload, timeout=20)
            if r.status_code == 200:
                return True
        except requests.RequestException as e:
            print("Push fehlgeschlagen:", e, file=sys.stderr)
    return False


def save_outbox():
    """Gesammelte Pushes zu den noch offenen aus früheren Runs legen und speichern"""
    if not POSTAUSGANG:
        return 0
    pending = speicher.load_json(speicher.OUTBOX_FILE, [])
    speicher.save_json(speicher.OUTBOX_FILE, pending + POSTAUSGANG)
    n = len(POSTAUSGANG)
    POSTAUSGANG.clear()
    return n


def app_abos(status_store, key):
    """Entschlüsselte App-Abos {id: abo}; doppelte (gleiches Gerät mehrfach aktiviert) nur einmal"""
    out, endpoints = {}, set()
    for aid, a in sorted((status_store.get("push_abos") or {}).items(), key=lambda kv: kv[1].get("seit", "")):
        sub = webpush.open_abo(a.get("blob", ""), key) if key else None
        if sub and sub["endpoint"] not in endpoints:
            out[aid] = sub
            endpoints.add(sub["endpoint"])
    return out


def send_outbox(topic, status_store=None, key=None):
    """Postausgang abarbeiten: an ntfy und an die App-Abos verschicken, Verschicktes austragen, Fehlgeschlagenes
    für den nächsten Run behalten, zu Altes verwerfen. Erloschene App-Abos (404/410) werden ausgetragen.
    Gibt (verschickt, offen, verworfen, Probleme) zurück"""
    pending = speicher.load_json(speicher.OUTBOX_FILE, [])
    if not pending:
        return 0, 0, 0, []
    abos = app_abos(status_store or {}, key)
    keep, sent, dropped, problems = [], 0, 0, []
    for e in pending:
        try:
            age = now() - dt.datetime.fromisoformat(e["zeit"])
        except (KeyError, ValueError):
            age = dt.timedelta(0)
        if age > dt.timedelta(hours=OUTBOX_MAX_HOURS):
            dropped += 1
            continue
        targets = {k: v for k, v in abos.items() if not e.get("nur_abo") or k == e["nur_abo"]}
        msg = {"title": e["title"], "body": e["message"], "url": e.get("click") or ""}
        app_ok = False
        for aid, sub in targets.items():
            code = webpush.send(sub, msg, key)
            app_ok = app_ok or code in (200, 201, 202)
            if code in (404, 410):   # Abo erloschen (z. B. App neu installiert): austragen
                (status_store.get("push_abos") or {}).pop(aid, None)
                abos.pop(aid, None)
                problems.append(("App-Push", "Abo erloschen und ausgetragen, in der App unter Einstellungen neu aktivieren"))
            elif code not in (200, 201, 202):
                problems.append(("App-Push", f"Push nicht angenommen (HTTP {code or 'Verbindung'})"))
        ntfy_ok = (not topic or e.get("nur_abo")) or send_now(topic, e)
        if ntfy_ok or app_ok:
            sent += 1
        else:
            keep.append(e)
    speicher.save_json(speicher.OUTBOX_FILE, keep)
    return sent, len(keep), dropped, problems


def short(e, shop=False):
    """Titel plus Größe (nur falls nicht schon im Titel) und optional Shop"""
    extra = [] if (e.get("size") and SIZE_RX.search(norm(e["title"]))) else [e.get("size", "")]
    if shop:
        extra.append(e["shop"])
    extra = [x for x in extra if x]
    return e["title"] + (f" ({', '.join(extra)})" if extra else "")


def detail_line(e):
    """Titel plus Zeile mit Größe, Preis, Zustand und ggf. Zustandsnotiz"""
    parts = [f"Größe {e['size']}", e.get("price", ""), f"Zustand {e['zustand']}" if e.get("zustand") else ""]
    text = e["title"] + "\n" + " · ".join(x for x in parts if x)
    if e.get("ungeprueft"):
        text += "\n(Shop-Seite ließ sich nicht prüfen, Angaben aus der Liste)"
    return text + (f"\n{e['zustand_notiz']}" if e.get("zustand_notiz") else "")


def push_label(entry):
    return ", ".join(entry["labels"])
