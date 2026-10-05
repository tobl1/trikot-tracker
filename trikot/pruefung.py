"""Seitenprüfung: Treffer auf der Shop-Seite nachprüfen (verkauft? Zustand? Hersteller?)"""

import concurrent.futures as cf
import datetime as dt
from collections import Counter
import threading
import json
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .basis import CHECK_VERSION, MAX_WORKERS, RECHECK_DAYS, hit, is_high, norm, now, plain
from .netz import Http, SHOPIFY_GATE
from .zustand import SOLD_RX, condition_info, desc_excluded, ld_products


def check_page(http, url):
    """Produktseite: {'verfuegbar': True/False/None, 'desc': str} oder None bei Fehler"""
    txt = http.get(url, want="text")
    if not txt:
        return None
    soup = BeautifulSoup(txt, "html.parser")
    avail, desc, brand = [], "", ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for prod in ld_products(data):
            desc = desc or plain(prod.get("description"))
            b = prod.get("brand")
            brand = brand or plain(b.get("name") if isinstance(b, dict) else b)
            offers = prod.get("offers") or []
            for o in offers if isinstance(offers, list) else [offers]:
                if isinstance(o, dict) and o.get("availability"):
                    avail.append(str(o["availability"]))
    if not desc:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        desc = plain(meta.get("content")) if meta else ""
    ok = None
    if avail:
        ok = any(not SOLD_RX.search(a) for a in avail)
    return {"verfuegbar": ok, "desc": desc, "marke": brand}


PUSH_WAIT_HOURS = 24   # so lange wartet ein Treffer höchstens auf eine erfolgreiche Seitenprüfung


def needs_check(e):
    """Treffer, deren Shop-Seite vor dem Push geprüft wird: FYJ-Treffer und Such-Shops (Verfügbarkeit, Hersteller,
    Beschreibung stehen nur auf der Seite). Shopify, Woo und Wix liefern das direkt; eBay ist so nicht prüfbar"""
    return bool(e.get("via") == "fyj" or e.get("pruefen")) and "ebay." not in e["url"]


def enrich(seen, ts, budget, matcher):
    """Treffer auf der Shop-Seite prüfen: verkauft? Hersteller? Zustand? Zurückgehaltene Pushes zuerst, dann neue,
    dann die ältesten Prüfungen. Gibt (Zahl der Versuche, {Host: Counter(Status)} der gescheiterten) zurück"""
    due = dt.timedelta(days=RECHECK_DAYS)
    cand = [e for e in seen.values()
            if needs_check(e) and not e.get("verkauft") and (e["last"] == ts or e.get("push_offen"))
            and (e.get("push_offen") or not e.get("geprueft") or e.get("pruef_v") != CHECK_VERSION
                 or now() - dt.datetime.fromisoformat(e["geprueft"]) > due)]
    cand.sort(key=lambda e: (not e.get("push_offen"), bool(e.get("geprueft")), not is_high(e), e.get("geprueft") or ""))
    by_host = {}
    for e in cand[:budget]:
        by_host.setdefault(urlparse(e["url"]).netloc, []).append(e)
    fails, lock = {}, threading.Lock()

    def work(entries):
        http = Http(SHOPIFY_GATE if "/products/" in entries[0]["url"] else None)
        host = urlparse(entries[0]["url"]).netloc
        for e in entries:
            try:
                res = check_page(http, e["url"])
            except requests.RequestException:
                res = None
            if res is None:
                code = http.last_status or "Verbindung"
                e["pruef_fehler"] = code
                with lock:
                    fails.setdefault(host, Counter())[code] += 1
                if code == 404:
                    e["verkauft"] = ts   # Produktseite weg: Artikel nicht mehr da
                continue
            e.pop("pruef_fehler", None)
            e["geprueft"], e["pruef_v"] = ts, CHECK_VERSION
            if res["verfuegbar"] is False:
                e["verkauft"] = ts
            if res["marke"] and hit(matcher.brand_ex, norm(res["marke"])):
                e["aussortiert"] = f"Hersteller {res['marke']}"
            elif desc_excluded(res["desc"], e["title"]):
                e["aussortiert"] = desc_excluded(res["desc"], e["title"])
            grade, note = condition_info(e["title"], res["desc"])
            if grade:
                e["zustand"] = grade
            if note:
                e["zustand_notiz"] = note

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(work, by_host.values()))
    return min(len(cand), budget), fails


def hold_unchecked(new_entries, seen, ts):
    """Prüfen vor dem Push: neue Treffer, deren Seite noch nicht geprüft werden konnte, zurückhalten (push_offen,
    nächster Run prüft sie zuerst); zurückgehaltene, die inzwischen geprüft sind, freigeben. Gesperrte Seiten
    (401/403) sind nicht prüfbar: sofort pushen, markiert. Nach PUSH_WAIT_HOURS ohne Prüfung ebenso.
    Gibt die Treffer zurück, die jetzt gepusht werden"""
    out = []
    for e in new_entries:
        if needs_check(e) and e.get("geprueft") != ts and e.get("pruef_fehler") not in (401, 403):
            e["push_offen"] = ts
        else:
            if needs_check(e) and e.get("geprueft") != ts:
                e["ungeprueft"] = True
            out.append(e)
    for e in seen.values():
        held = e.get("push_offen")
        if not held or held == ts:
            continue
        if e.get("verkauft") or e.get("aussortiert") or e.get("teuer"):
            e.pop("push_offen")                         # hat sich erledigt, keine Push
        elif e.get("geprueft") and e["geprueft"] >= held:
            e.pop("push_offen")
            out.append(e)
        elif e.get("pruef_fehler") in (401, 403) or \
                now() - dt.datetime.fromisoformat(held) > dt.timedelta(hours=PUSH_WAIT_HOURS):
            e.pop("push_offen")
            e["ungeprueft"] = True
            out.append(e)
    return out
