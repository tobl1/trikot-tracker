"""WooCommerce Store API"""

import html

from ..basis import norm
from .gemeinsam import SIZE_ATTR_RX, item


def woo_to_item(shop, p):
    if not p.get("is_in_stock", True):
        return None
    title = html.unescape(p.get("name") or "")
    size_terms, has_size_attr = [], False
    for a in p.get("attributes") or []:
        if SIZE_ATTR_RX.search(norm(a.get("name") or a.get("taxonomy") or "")):
            has_size_attr = True
            size_terms += [t.get("name", "") for t in a.get("terms") or []]
    size_text = " ".join(size_terms) if has_size_attr and size_terms else title
    pr = p.get("prices") or {}
    price = pr.get("price")
    try:
        price = f"{int(price) / 10 ** int(pr.get('currency_minor_unit', 2)):.2f} {pr.get('currency_code', '')}"
    except (TypeError, ValueError):
        price = str(price or "")
    imgs = p.get("images") or []
    img = imgs[0].get("src", "") if imgs else ""
    desc = (p.get("short_description") or "") + " " + (p.get("description") or "")
    ctx = " ".join([c.get("name", "") for c in p.get("categories") or []] + [t.get("name", "") for t in p.get("tags") or []]
                   + [str(p.get("slug") or "").replace("-", " ")])
    return item("direkt", shop, p.get("permalink") or "", title, size_text, price.strip(), img, desc=desc, ctx=ctx)


def woo_recent(http, shop, endpoint, per_page=100):
    """Neueste Artikel (Drop-Run: 100, Neuheiten-Radar: weniger)"""
    data = http.get(endpoint, {"per_page": per_page, "orderby": "date", "order": "desc"})
    data = data if isinstance(data, list) else []
    return [it for it in (woo_to_item(shop, p) for p in data) if it], len(data)


def woo_endpoint(http, base):
    for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        data = http.get(base + path, {"per_page": 1})
        if isinstance(data, list):
            return base + path
    return None


def woo_run(http, shop, endpoint, queries=None):
    items, n = [], 0
    runs = [{"search": q} for q in queries] if queries else [{}]
    for extra in runs:
        for page in range(1, 61):
            data = http.get(endpoint, {"per_page": 100, "page": page, **extra})
            if not isinstance(data, list) or not data:
                break
            n += len(data)
            for p in data:
                it = woo_to_item(shop, p)
                if it:
                    items.append(it)
            if len(data) < 100:
                break
    return items, n
