"""Wix Stores (öffentliche Shop-Schnittstelle, alter und neuer Katalog)"""

import json
import re

from ..basis import norm, plain
from .gemeinsam import SIZE_ATTR_RX, item


WIX_STORES_APP = "1380b703-ce81-ff05-f115-39571d94dfcd"
WIX_ALL = "00000000-000000-000000-000000000001"   # "Alle Produkte" im alten Katalog; neuer Katalog (V3) hat eigene IDs
WIX_ALL_NAMES = re.compile(r"(?i)^(all products|alle produkte|alle artikel|tous les produits|todos los productos|"
                           r"tutti i prodotti|alle producten|all)$")
WIX_CATS = "{ catalog { categories(limit: 100) { list { id name } } } }"
WIX_QUERY = """query getProducts($offset: Int, $limit: Int, $cid: String!) { catalog {
 category(categoryId: $cid) {
 productsWithMetaData(limit: $limit, offset: $offset, onlyVisible: true) { totalCount list {
 id name urlPart price currency isInStock productType description media { url }
 options { title selections { description value } } } } } } }"""


def wix_run(http, shop, base, max_pages=120):
    """Wix Stores: öffentliche Shop-Schnittstelle, die auch die Shop-Seite für "Mehr laden" nutzt.
    Anonymer Besucher-Schlüssel aus /_api/v1/access-tokens, dann 100 Produkte pro Abfrage"""
    tokens = http.get(f"{base}/_api/v1/access-tokens")
    inst = (((tokens or {}).get("apps") or {}).get(WIX_STORES_APP) or {}).get("instance")
    if not inst:
        return [], 0
    api, hdr = f"{base}/_api/wix-ecommerce-storefront-web/api", {"Authorization": inst}

    def fetch(cid, offset):
        data = http.post(api, headers=hdr, json={"query": WIX_QUERY, "operationName": "getProducts",
                                                 "variables": {"offset": offset, "limit": 100, "cid": cid}})
        return ((((data or {}).get("data") or {}).get("catalog") or {}).get("category") or {}) \
            .get("productsWithMetaData") or {}

    first = fetch(WIX_ALL, 0)
    cats = [WIX_ALL]
    if not first.get("list"):
        # Neuer Wix-Katalog: Kategorie "All Products" suchen, sonst alle Kategorien zusammennehmen
        lst = ((((http.post(api, headers=hdr, json={"query": WIX_CATS}) or {}).get("data") or {})
                .get("catalog") or {}).get("categories") or {}).get("list") or []
        all_cat = [c["id"] for c in lst if WIX_ALL_NAMES.match((c.get("name") or "").strip())]
        cats = all_cat[:1] or [c["id"] for c in lst]
        first = None
    items, n, seen_ids = [], 0, set()
    for cid in cats:
        for page in range(max_pages):
            block = first if (first is not None and cid == WIX_ALL and page == 0) else fetch(cid, page * 100)
            prods = block.get("list") or []
            key = lambda p: p.get("id") or p.get("urlPart")
            items += wix_items(shop, base, [p for p in prods if key(p) not in seen_ids])
            seen_ids |= {key(p) for p in prods}
            n += len(prods)
            if len(prods) < 100 or (page + 1) * 100 >= (block.get("totalCount") or 0):
                break
    return items, n


def wix_text(desc):
    """Beschreibung: neuer Wix-Katalog liefert Rich-Text als JSON ("textData": {"text": ...}), alter HTML"""
    if isinstance(desc, str) and desc.lstrip().startswith("{"):
        try:
            data = json.loads(desc)
        except ValueError:
            return plain(desc)
        out = []

        def walk(x):
            if isinstance(x, dict):
                if isinstance(x.get("textData"), dict):
                    out.append(str(x["textData"].get("text") or ""))
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        return " ".join(out)
    return plain(desc)


def wix_items(shop, base, prods):
    items = []
    for p in prods:
        if not p.get("isInStock") or not p.get("urlPart"):
            continue
        sizes, grade = [], ""
        for o in p.get("options") or []:
            title = norm(o.get("title"))
            vals = [x.get("description") or x.get("value") or "" for x in o.get("selections") or []]
            if "youth" in title or "kid" in title:
                sizes += ["youth"] + vals           # Kindergröße, wird über die Ausschlüsse aussortiert
            elif SIZE_ATTR_RX.search(title):
                sizes += vals
            elif "condition" in title and vals:
                grade = vals[0]
        media = (p.get("media") or [{}])[0].get("url") or ""
        img = media if media.startswith("http") else (f"https://static.wixstatic.com/media/{media}" if media else "")
        price = f"{p.get('price')} {p.get('currency') or ''}".strip() if p.get("price") is not None else ""
        items.append(item("direkt", shop, f"{base}/product-page/{p['urlPart']}", p.get("name") or "",
                          f"{p.get('name') or ''} {' '.join(sizes)}", price, img,
                          desc=f"{p.get('name') or ''} {wix_text(p.get('description'))}",   # Zustand teils im Titel
                          typ=p.get("productType") if p.get("productType") not in ("physical", None) else "",
                          fyj_condition=grade))
    return items
