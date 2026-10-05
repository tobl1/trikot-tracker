"""GitHub-Issues aus dem Dashboard: Meldungen, Preisalarme, Shop aufnehmen"""

import hashlib
import os
import re

import requests
import yaml

from . import speicher
from .basis import TIMEOUT, domain
from .preise import to_eur


FLAG_RX = re.compile(r"(?im)^(grund|id|kommentar)\s*:\s*(.*)$")


def parse_flag(body):
    """Issue-Text aus dem Dashboard -> {'grund', 'id', 'kommentar'} oder None"""
    found = {k.lower(): v.strip() for k, v in FLAG_RX.findall(body or "")}
    return found if found.get("grund") and found.get("id") else None


def apply_flags(seen, status_store, ts):
    """Im Dashboard gemeldete Treffer (GitHub-Issues mit Label "flag") übernehmen und Issues schließen.
    Nur Issues des Repo-Inhabers zählen (öffentliches Repo). Gibt die Zahl neuer Meldungen zurück"""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or (repo or "").split("/")[0]
    flags = status_store.setdefault("flags", {})
    new = 0
    if token and repo:
        api = f"https://api.github.com/repos/{repo}/issues"
        hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        # Alle Meldungen lesen, auch geschlossene: so geht nichts verloren, falls ein Run nach dem
        # Schließen nicht speichern konnte (passiert am 04.10.2026)
        issues = []
        for page in range(1, 6):
            try:
                batch = requests.get(api, params={"labels": "flag", "state": "all", "per_page": 100, "page": page},
                                     headers=hdr, timeout=TIMEOUT).json()
            except (requests.RequestException, ValueError):
                break
            if not isinstance(batch, list) or not batch:
                break
            issues += batch
            if len(batch) < 100:
                break
        for iss in issues:
            if (iss.get("user") or {}).get("login") != owner:
                continue
            f = parse_flag(iss.get("body"))
            if not f:
                continue
            if f["id"] not in flags:
                flags[f["id"]] = {"grund": f["grund"].lower(), "kommentar": f.get("kommentar", ""),
                                  "zeit": ts, "issue": iss.get("number"), "titel": (iss.get("title") or "")[:120]}
                new += 1
            if iss.get("state") != "open":
                continue
            e = seen.get(f["id"])
            msg = (f"Übernommen: Treffer ist ab sofort ausgeblendet ({f['grund']})." if e else
                   "Übernommen, der Treffer war schon nicht mehr in der Liste.")
            try:
                requests.post(f"{api}/{iss['number']}/comments", json={"body": msg}, headers=hdr, timeout=TIMEOUT)
                requests.patch(f"{api}/{iss['number']}", json={"state": "closed"}, headers=hdr, timeout=TIMEOUT)
            except requests.RequestException:
                pass
    for key, f in flags.items():
        e = seen.get(key)
        if not e:
            continue
        if f["grund"].startswith("ausverkauft"):
            e.setdefault("verkauft", f["zeit"])
        elif f["grund"] == "juckt nicht":   # im Dashboard ausgeblendet: auf allen Geräten weg, keine Regel-Meldung
            e["aussortiert"] = "Ausgeblendet (juckt nicht)"
        else:
            e["aussortiert"] = f"Gemeldet: {f['grund']}" + (f" ({f['kommentar']})" if f.get("kommentar") else "")
    return new


def owner_issues(label, state="open"):
    """Issues des Repo-Inhabers mit diesem Label (öffentliches Repo: nur eigene zählen)"""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return [], None
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
    api = f"https://api.github.com/repos/{repo}/issues"
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    out = []
    for page in range(1, 6):
        try:
            batch = requests.get(api, params={"labels": label, "state": state, "per_page": 100, "page": page},
                                 headers=hdr, timeout=TIMEOUT).json()
        except (requests.RequestException, ValueError):
            break
        if not isinstance(batch, list) or not batch:
            break
        out += [i for i in batch if (i.get("user") or {}).get("login") == owner]
        if len(batch) < 100:
            break
    return out, (api, hdr)


def check_alarms(seen, status_store, ts, rates, mode, notify):
    """Preisalarm für Favoriten (GitHub-Issues mit Label "alarm"): Push bei Preissenkung, bei
    Verkauf/Verschwinden Push und Issue schließen. Geschlossene Issues = Alarm beendet"""
    issues, api = owner_issues("alarm")
    if api is None:
        return
    alarms = status_store.setdefault("alarme", {})
    open_ids = set()
    for iss in issues:
        f = parse_flag(iss.get("body"))
        if not f:
            continue
        open_ids.add(f["id"])
        a = alarms.setdefault(f["id"], {"issue": iss["number"], "seit": ts})
        e = seen.get(f["id"])
        if not e:
            continue
        eur = to_eur(e.get("price"), rates)
        if eur and a.get("eur") is None:
            a["eur"] = eur
        elif eur and a.get("eur") and eur < a["eur"] - 0.5:
            notify(f"📉 Preis gesunken · {e['shop']}",
                   f"{e['title']}\n{a['eur']:.2f} € → {eur:.2f} € (Größe {e.get('size', '')})", 4, e["url"])
            a["eur"] = eur
        gone = e.get("verkauft") or (mode == "full" and e.get("weg"))
        if gone:
            notify(f"🔕 Favorit nicht mehr verfügbar · {e['shop']}", e["title"], 3, e["url"])
            hdr = api[1]
            try:
                requests.post(f"{api[0]}/{iss['number']}/comments", headers=hdr, timeout=TIMEOUT,
                              json={"body": "Der Artikel ist verkauft oder nicht mehr gelistet, Alarm beendet."})
                requests.patch(f"{api[0]}/{iss['number']}", headers=hdr, timeout=TIMEOUT, json={"state": "closed"})
            except requests.RequestException:
                pass
            open_ids.discard(f["id"])
    for k in list(alarms):
        if k not in open_ids:
            del alarms[k]


def add_shops_from_issues():
    """Issues mit Label "shop" (aus dem Fundgrube-Knopf): Shop in die Datei shops_fundgrube.yaml auf dem
    Daten-Zweig eintragen (nicht in shops.yaml, die bleibt Code) und Issue schließen"""
    issues, api = owner_issues("shop")
    if api is None or not issues:
        return 0
    known = {domain(s["url"]) for s in speicher.load_shops().get("shops") or []}
    extra = speicher.load_extra_shops()
    added = 0
    for iss in issues:
        f = dict(re.findall(r"(?im)^(url|plattform)\s*:\s*(\S+)", iss.get("body") or ""))
        url, plat = f.get("url", ""), f.get("plattform", "auto").lower()
        if not url.startswith("http"):
            continue
        if domain(url) not in known:
            shop = {"name": domain(url).split(".")[0].replace("-", " ").title(), "url": url.rstrip("/"),
                    "schnellcheck": "nein", "quelle": f"Fundgrube, Issue #{iss['number']}"}
            if plat == "wix":
                shop["plattform"] = "wix"
            extra.append(shop)
            known.add(domain(url))
            added += 1
        try:
            requests.post(f"{api[0]}/{iss['number']}/comments", headers=api[1], timeout=TIMEOUT,
                          json={"body": "Aufgenommen, der Shop läuft ab dem nächsten Gesamt-Run direkt (nur nachts)."})
            requests.patch(f"{api[0]}/{iss['number']}", headers=api[1], timeout=TIMEOUT, json={"state": "closed"})
        except requests.RequestException:
            pass
    if added:
        speicher.save_text(speicher.SHOPS_EXTRA_FILE, yaml.safe_dump(extra, allow_unicode=True, sort_keys=False))
    return added


ABO_RX = re.compile(r"(?im)^abo\s*:\s*(v1\.[A-Za-z0-9_\-.]+)\s*$")


def collect_push_abos(status_store, ts):
    """Issues mit Label "push" (aus der App, Einstellungen): verschlüsseltes Abo merken, Issue schließen.
    Gibt die IDs der neuen Abos zurück (die bekommen eine Bestätigungs-Push)"""
    issues, api = owner_issues("push")
    if api is None or not issues:
        return []
    abos = status_store.setdefault("push_abos", {})
    new = []
    for iss in issues:
        m = ABO_RX.search(iss.get("body") or "")
        if m:
            aid = hashlib.sha256(m.group(1).encode()).hexdigest()[:16]
            if aid not in abos:
                abos[aid] = {"blob": m.group(1), "seit": ts, "issue": iss["number"]}
                new.append(aid)
        try:
            requests.post(f"{api[0]}/{iss['number']}/comments", headers=api[1], timeout=TIMEOUT,
                          json={"body": "Push für die App ist eingerichtet, die Bestätigung kommt gleich nach diesem Run."
                                if m else "Kein gültiges Abo gefunden, bitte in der App erneut aktivieren."})
            requests.patch(f"{api[0]}/{iss['number']}", headers=api[1], timeout=TIMEOUT, json={"state": "closed"})
        except requests.RequestException:
            pass
    return new
