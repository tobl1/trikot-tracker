"""Benachrichtigungen (ntfy) und Textbausteine dafür"""

import os
import sys

import requests

from .basis import SIZE_RX, norm


def push(topic, title, message, prio=3, click=None, image=None, tags=None, dry=False):
    payload = {"topic": topic, "title": title[:250], "message": message[:3500],
               "priority": prio, "tags": tags or []}
    if click:
        payload["click"] = click
    if image and image.startswith("http"):
        payload["attach"] = image
    if dry or not topic:
        print(f"[PUSH p{prio}] {title}\n    {message}\n    {click or ''}")
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        requests.post(server, json=payload, timeout=20)
    except requests.RequestException as e:
        print("Push fehlgeschlagen:", e, file=sys.stderr)


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
    return text + (f"\n{e['zustand_notiz']}" if e.get("zustand_notiz") else "")


def push_label(entry):
    return ", ".join(entry["labels"])
