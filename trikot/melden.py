"""Benachrichtigungen (ntfy) und Textbausteine dafür"""

import datetime as dt
import os
import sys
import uuid

import requests

from . import speicher
from .basis import SIZE_RX, norm, now

OUTBOX_MAX_HOURS = 12   # ältere, nie verschickte Pushes verwerfen statt veraltet nachzuliefern

# Postausgang: Pushes eines Runs werden hier gesammelt und erst NACH dem Speichern verschickt
# (Workflow-Schritt "Pushes senden"). Scheitert das Speichern, geht nichts raus und der nächste Run
# meldet dieselben Treffer noch einmal richtig; nichts kommt doppelt, nichts geht verloren
POSTAUSGANG = []


def push(topic, title, message, prio=3, click=None, image=None, tags=None, dry=False):
    """Push vormerken (Probelauf: nur anzeigen). Das ntfy-Thema wird nie gespeichert"""
    entry = {"id": uuid.uuid4().hex, "zeit": now().isoformat(), "title": title[:250], "message": message[:3500],
             "prio": prio, "click": click or "", "image": image or "", "tags": tags or []}
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


def send_outbox(topic):
    """Postausgang abarbeiten: verschicken, Verschicktes austragen, Fehlgeschlagenes für den nächsten Run
    behalten, zu Altes verwerfen. Gibt (verschickt, offen, verworfen) zurück"""
    pending = speicher.load_json(speicher.OUTBOX_FILE, [])
    if not pending:
        return 0, 0, 0
    keep, sent, dropped = [], 0, 0
    for e in pending:
        try:
            age = now() - dt.datetime.fromisoformat(e["zeit"])
        except (KeyError, ValueError):
            age = dt.timedelta(0)
        if age > dt.timedelta(hours=OUTBOX_MAX_HOURS):
            dropped += 1
        elif send_now(topic, e):
            sent += 1
        else:
            keep.append(e)
    speicher.save_json(speicher.OUTBOX_FILE, keep)
    return sent, len(keep), dropped


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
