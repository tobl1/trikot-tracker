"""Shopify: products.json, Suchseite, Währung"""

import datetime as dt
import re

from ..basis import ANY_SIZE_RX, RADAR_LIMIT, SHOPIFY_PAGE_CAP, SIZE_RX, norm, now
from .gemeinsam import item


def shopify_currency(http, base):
    """products.json enthält keine Währung, /cart.js schon"""
    data = http.get(f"{base}/cart.js")
    cur = (data or {}).get("currency") if isinstance(data, dict) else None
    return cur if isinstance(cur, str) and len(cur) == 3 else ""


def shopify_to_item(shop, base, p, cents=False, currency=""):
    title = p.get("title") or ""
    handle = p.get("handle") or ""
    url = f"{base}/products/{handle}"
    imgs = p.get("images") or []
    img = ""
    if imgs:
        img = imgs[0]["src"] if isinstance(imgs[0], dict) else imgs[0]
        if img.startswith("//"):
            img = "https:" + img
    variants = p.get("variants") or []
    avail = [v for v in variants if v.get("available")]
    if not avail:
        return None

    def opts(v):
        return [x for x in (v.get("option1"), v.get("option2"), v.get("option3")) if x]

    single_default = len(variants) == 1 and norm(variants[0].get("title")) in ("default title", "")
    has_size_variants = not single_default and any(
        ANY_SIZE_RX.search(norm(x)) for v in variants for x in opts(v))
    if has_size_variants:
        # Größe steckt in den Varianten: nur verfügbare XL/XXL-Varianten zählen
        size_vals = [x for v in avail for x in opts(v) if SIZE_RX.search(norm(x))]
        size_text = " ".join(size_vals) or "__keine__"
    else:
        # Einzelstück: Größe steht im Titel oder in einem Größen-Tag
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        size_tags = [t for t in tags if SIZE_RX.search(norm(t)) and len(norm(t)) <= 20]
        size_text = title + " " + " ".join(size_tags)
    price = avail[0].get("price")
    if price is not None and cents:
        price = f"{int(price) / 100:.2f}"
    price = f"{price} {currency}".strip() if price not in (None, "") else ""
    desc = p.get("body_html") or p.get("description") or ""
    # Produktart ("Tracktop", "Reissue", "Goal Keeper" ...) nur für Ausschlüsse, nicht fürs Matching
    return item("direkt", shop, url, title, size_text, price, img, desc=desc,
                typ=p.get("product_type") or p.get("type") or "")


def shopify_full(http, shop, base, path="/products.json", currency="", stamps=None):
    items, n = [], 0
    for page in range(1, SHOPIFY_PAGE_CAP + 1):
        data = http.get(f"{base}{path}", {"limit": 250, "page": page})
        prods = (data or {}).get("products") or []
        if not prods:
            break
        n += len(prods)
        for p in prods:
            if stamps is not None:
                stamps.append(p.get("published_at") or p.get("created_at") or "")
            it = shopify_to_item(shop, base, p, currency=currency)
            if it:
                items.append(it)
        if len(prods) < 250:
            break
    return items, n


def shopify_recent(http, shop, base, currency="", days=3, max_pages=3):
    """Drop-Run: products.json liefert die neuesten zuerst, daher reichen die ersten Seiten"""
    items, n = [], 0
    since = now() - dt.timedelta(days=days)
    for page in range(1, max_pages + 1):
        data = http.get(f"{base}/products.json", {"limit": 250, "page": page})
        prods = (data or {}).get("products") or []
        n += len(prods)
        old = False
        for p in prods:
            it = shopify_to_item(shop, base, p, currency=currency)
            if it:
                items.append(it)
            try:
                old = old or dt.datetime.fromisoformat(p.get("published_at") or p.get("created_at")) < since
            except (TypeError, ValueError):
                pass
        if old or len(prods) < 250:
            break
    return items, n


def shopify_newest(http, shop, base, currency="", since=None, limit=RADAR_LIMIT, max_pages=3):
    """Neuheiten-Radar: nur die neuesten Artikel (products.json liefert die neuesten zuerst), kleine Seiten.
    Weiterblättern nur, wenn die ganze Seite neuer ist als die letzte Radar-Prüfung (dann kam mehr dazu)"""
    items, n = [], 0
    for page in range(1, max_pages + 1):
        data = http.get(f"{base}/products.json", {"limit": limit, "page": page})
        prods = (data or {}).get("products") or []
        n += len(prods)
        oldest = None
        for p in prods:
            it = shopify_to_item(shop, base, p, currency=currency)
            if it:
                items.append(it)
            try:
                d = dt.datetime.fromisoformat(str(p.get("published_at") or p.get("created_at")))
                oldest = d if oldest is None or d < oldest else oldest
            except ValueError:
                pass
        if len(prods) < limit or since is None or oldest is None or oldest <= since:
            break
    return items, n


def shopify_search(http, shop, base, queries, matcher, currency="", pages=2):
    """Shopify-Suchseite (/search) statt suggest.json: suggest liefert max. 10 unscharfe Treffer
    (bei VFA für "thiago" nur T. Silva). Vorfilter über den Handle, Details per /products/<handle>.js.
    Shops mit nichtssagenden Handles (z. B. nur Ziffern) werden so nicht gefunden, die deckt der
    Gesamtlauf über products.json ab"""
    items, n, handles = [], 0, set()
    for q in queries:
        for page in range(1, pages + 1):
            txt = http.get(f"{base}/search", {"q": q, "type": "product", "options[prefix]": "last",
                                              "page": page}, want="text")
            if not txt:
                break
            found = list(dict.fromkeys(re.findall(r"/products/([a-z0-9][a-z0-9_-]*)", txt)))
            n += len(found)
            for h in found:
                if h in handles:
                    continue
                handles.add(h)
                if not matcher.labels(h.replace("-", " ").replace("_", " ")):
                    continue
                full = http.get(f"{base}/products/{h}.js")
                if full:
                    it = shopify_to_item(shop, base, full, cents=True, currency=currency)
                    if it:
                        items.append(it)
            if len(found) < 12:
                break
    return items, n
