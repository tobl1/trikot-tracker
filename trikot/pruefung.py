"""Seitenprüfung: Treffer auf der Shop-Seite nachprüfen (verkauft? Zustand? Hersteller?)"""

import concurrent.futures as cf
import datetime as dt
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


def enrich(seen, ts, budget, matcher):
    """FYJ-Treffer auf der Shop-Seite prüfen: verkauft? Zustand? Neue zuerst, dann die ältesten Prüfungen"""
    due = dt.timedelta(days=RECHECK_DAYS)
    cand = [e for e in seen.values()
            if e["last"] == ts and (e.get("via") == "fyj" or e.get("pruefen")) and not e.get("verkauft")
            and "ebay." not in e["url"]
            and (not e.get("geprueft") or e.get("pruef_v") != CHECK_VERSION
                 or now() - dt.datetime.fromisoformat(e["geprueft"]) > due)]
    cand.sort(key=lambda e: (bool(e.get("geprueft")), not is_high(e), e.get("geprueft") or ""))
    by_host = {}
    for e in cand[:budget]:
        by_host.setdefault(urlparse(e["url"]).netloc, []).append(e)

    def work(entries):
        http = Http(SHOPIFY_GATE if "/products/" in entries[0]["url"] else None)
        for e in entries:
            try:
                res = check_page(http, e["url"])
            except requests.RequestException:
                res = None
            if res is None:
                continue
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
    return min(len(cand), budget)
