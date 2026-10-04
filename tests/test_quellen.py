"""Vertragstests für die Shop-Anbindungen: jede Anbindung bekommt Beispieldaten im Format des echten Shops
(Shopify-JSON, WooCommerce-Store-API, Magento-HTML, IdoSell-HTML, Wix-GraphQL, JSON-LD) und muss daraus die
richtigen Artikel lesen. Ohne Netz: FakeHttp liefert die Antworten. Fällt hier etwas um, ist eine Anbindung kaputt"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tracker  # noqa: E402

M = tracker.Matcher(yaml.safe_load((ROOT / "watchlist.yaml").read_text(encoding="utf-8")))


class FakeHttp:
    """Antwortet nach Regeln (URL-Teilstring, optional Prüffunktion auf die Parameter) statt echter Abrufe"""
    def __init__(self, routes):
        self.routes = routes          # [(teilstring, antwort oder funktion(params) -> antwort)]
        self.calls = []
        self.count = self.limited = 0
        self.codes = Counter()
        self.gate = None
        self.s = type("S", (), {"headers": {}})()

    def _answer(self, url, params):
        self.calls.append((url, params))
        self.count += 1
        for key, val in self.routes:
            if key in url:
                return val(params or {}) if callable(val) else val
        return None

    def get(self, url, params=None, want="json"):
        return self._answer(url, params)

    def post(self, url, json=None, headers=None):
        return self._answer(url, json)


def labels(it):
    return {l for l, _ in M.labels(it["match_text"], it.get("fyj_reissue", False), it.get("desc", ""))}


def passt(it):
    return bool(labels(it)) and M.size_ok(it["size_text"], tracker.norm(it["match_text"]))


# ---------------------------------------------------------------------------
# Shopify
# ---------------------------------------------------------------------------
def shopify_prod(title, handle, variants, tags=(), published="2026-10-04T10:00:00+02:00", body="", typ="Shirt"):
    return {"title": title, "handle": handle, "product_type": typ, "tags": list(tags), "body_html": body,
            "published_at": published, "images": [{"src": "//cdn.shopify.com/s/files/x.jpg"}], "variants": variants}


def var(title, available=True, price="79.99", o1=None):
    return {"title": title, "available": available, "price": price, "option1": o1 or title}


def test_shopify_einzelstueck_groesse_aus_titel_und_tag():
    p = shopify_prod("2019/20 - Bayern Munich - Thiago #6", "bayern-1920-thiago", [var("Default Title")], tags=["XL"],
                     body="<p>Condition: 9/10 very good</p>")
    it = tracker.shopify_to_item("VFA", "https://vfa.com", p, currency="EUR")
    assert it["url"] == "https://vfa.com/products/bayern-1920-thiago"
    assert it["image"] == "https://cdn.shopify.com/s/files/x.jpg"
    assert it["price"] == "79.99 EUR" and it["typ"] == "Shirt"
    assert passt(it) and labels(it) == {"Thiago"}
    assert tracker.condition_info(it["title"], it["desc"])[0] == "9/10"


def test_shopify_groessen_varianten_nur_verfuegbare_zaehlen():
    p = shopify_prod("2012-13 Barcelona Home Shirt", "barca-1213", [var("M"), var("XL", available=False)])
    it = tracker.shopify_to_item("Shop", "https://s.com", p)
    assert it["size_text"] == "__keine__" and not passt(it)          # XL ausverkauft, nur M da
    p["variants"][1]["available"] = True
    it = tracker.shopify_to_item("Shop", "https://s.com", p)
    assert it["size_text"] == "XL" and passt(it)
    assert tracker.shopify_to_item("Shop", "https://s.com", shopify_prod("x", "x", [var("XL", available=False)])) is None


def test_shopify_full_blaettert_und_sammelt_zeitstempel():
    page1 = [shopify_prod(f"Shirt {i}", f"h{i}", [var("XL")]) for i in range(250)]
    page2 = [shopify_prod("2012-13 Barcelona Home Shirt (XL)", "barca", [var("Default Title")])]
    http = FakeHttp([("/products.json", lambda p: {"products": page1 if p["page"] == 1 else page2 if p["page"] == 2 else []})])
    stamps = []
    items, n = tracker.shopify_full(http, "Shop", "https://s.com", currency="GBP", stamps=stamps)
    assert n == 251 and len(stamps) == 251 and len(http.calls) == 2   # Seite 2 hat < 250 Artikel: Schluss
    assert any(passt(it) for it in items)


def test_shopify_recent_stoppt_bei_alten_artikeln():
    old = "2020-01-01T10:00:00+00:00"
    page1 = [shopify_prod(f"Shirt {i}", f"h{i}", [var("XL")], published=old if i == 249 else tracker.now().isoformat())
             for i in range(250)]
    http = FakeHttp([("/products.json", lambda p: {"products": page1})])
    items, n = tracker.shopify_recent(http, "Shop", "https://s.com")
    assert n == 250 and len(http.calls) == 1


def test_shopify_suche_vorfilter_ueber_handle():
    page = '<a href="/products/2012-13-barcelona-home-shirt-thiago-11-xl">x</a><a href="/products/random-cap">y</a>'
    js = {"title": "2012-13 Barcelona Home Shirt Thiago #11 (XL)", "handle": "2012-13-barcelona-home-shirt-thiago-11-xl",
          "variants": [{"title": "Default Title", "available": True, "price": 8999, "option1": "Default Title"}],
          "images": ["//cdn.shopify.com/y.jpg"], "type": "Shirt"}
    http = FakeHttp([("/search", page), (".js", js)])
    items, n = tracker.shopify_search(http, "Shop", "https://s.com", ["thiago"], M, "EUR")
    assert n == 2 and len(items) == 1
    assert items[0]["price"] == "89.99 EUR" and passt(items[0])
    assert not any("random-cap" in u for u, _ in http.calls if u.endswith(".js"))   # Mütze nicht nachgeladen


# ---------------------------------------------------------------------------
# WooCommerce
# ---------------------------------------------------------------------------
def woo_prod(name, sizes, in_stock=True, price="12999"):
    return {"name": name, "permalink": "https://w.com/p/" + name.replace(" ", "-").lower(), "is_in_stock": in_stock,
            "attributes": [{"name": "Size", "terms": [{"name": s} for s in sizes]}],
            "prices": {"price": price, "currency_code": "EUR", "currency_minor_unit": 2},
            "images": [{"src": "https://w.com/i.jpg"}], "description": "<p>Zustand: 8/10</p>"}


def test_woo_groesse_preis_bestand():
    it = tracker.woo_to_item("RB", woo_prod("Bayern 2013/14 Thiago #6 Shirt", ["XL"]))
    assert it["price"] == "129.99 EUR" and it["size_text"] == "XL" and passt(it)
    assert tracker.woo_to_item("RB", woo_prod("x", ["XL"], in_stock=False)) is None
    assert not passt(tracker.woo_to_item("RB", woo_prod("Bayern 2013/14 Thiago #6 Shirt", ["L"])))


def test_woo_run_blaettert():
    full = [woo_prod(f"Shirt {i}", ["XL"]) for i in range(100)]
    http = FakeHttp([("/wc/store", lambda p: full if p.get("page") == 1 else [woo_prod("Spain 2010 Home Shirt Thiago", ["XXL"])])])
    items, n = tracker.woo_run(http, "RB", "https://w.com/wp-json/wc/store/v1/products")
    assert n == 101 and any(passt(it) for it in items)


# ---------------------------------------------------------------------------
# Classic Football Shirts (Magento-Suchseite)
# ---------------------------------------------------------------------------
CFS_PAGE = """<ol><li class="product-item"><a href="/2020-21-liverpool-away-shirt-thiago-6-8-10-xl-liva1.html">
<img alt="2020-21 Liverpool Away Shirt Thiago #6 - 8/10 - (XL)" src="https://cfs.img/a.jpg"></a>
<span class="price">£89.99</span></li>
<li class="product-item"><a href="/2015-16-psg-home-shirt-t-silva-2-m.html"><img alt="2015-16 PSG Home Shirt T.Silva #2 (M)"></a></li></ol>"""


def test_cfs_suche_liest_titel_preis_bild():
    http = FakeHttp([("/catalogsearch/result/", CFS_PAGE)])
    items, n = tracker.cfs_run(http, "CFS", "https://cfs.co.uk", ["thiago"])
    assert n == 2 and len(http.calls) == 2              # Seite 2 liefert nichts Neues: Schluss
    thiago = [it for it in items if passt(it)]
    assert len(thiago) == 1 and thiago[0]["price"] == "£89.99"
    assert thiago[0]["url"] == "https://cfs.co.uk/2020-21-liverpool-away-shirt-thiago-6-8-10-xl-liva1.html"
    assert tracker.condition_info(thiago[0]["title"], "")[0] == "8/10"


# ---------------------------------------------------------------------------
# Classic-Shirts (IdoSell)
# ---------------------------------------------------------------------------
IDO_SEARCH = """<div class="product" data-product_id="1"><a class="product__name" href="/product-eng-1-2013-14-bayern.html">
2013-14 BAYERN MUNCHEN *THIAGO* SHIRT</a><strong class="price">£54.99<span>x</span></strong><img src="/img/1.jpg"></div>
<div class="product" data-product_id="2"><a class="product__name" href="/product-eng-2-cap.html">BAYERN CAP</a></div>"""
IDO_DETAIL = """<div class="projector_sizes__name">L</div><div class="projector_sizes__name">XL</div>"""


def test_idosell_sammelangebot_groesse_von_produktseite():
    http = FakeHttp([("/search.php", IDO_SEARCH), ("product-eng-1", IDO_DETAIL)])
    items, n = tracker.idosell_run(http, "Classic-Shirts", "https://classic-shirts.com", ["thiago"], M)
    assert n == 2 and len(items) == 1
    it = items[0]
    assert it["size_text"] == "L XL" and it["price"] == "£54.99" and it["pruefen"] and passt(it)
    assert it["image"] == "https://classic-shirts.com/img/1.jpg"


# ---------------------------------------------------------------------------
# Wix (neuer Katalog V3: Kategorie "All Products" suchen)
# ---------------------------------------------------------------------------
def test_wix_v3_sucht_kategorie_all_products():
    prod = {"id": "1", "name": "Spain 2010 Away Shirt", "urlPart": "spain-2010-away", "price": 95, "currency": "EUR",
            "isInStock": True, "media": [{"url": "abc.jpg"}], "options": [{"title": "Size", "selections": [{"value": "XL"}]}],
            "description": '{"nodes":[{"textData":{"text":"Condition: Excellent"}}]}'}

    def post(body):
        if "categories" in body.get("query", ""):
            return {"data": {"catalog": {"categories": {"list": [{"id": "c1", "name": "Shirts"}, {"id": "c9", "name": "All Products"}]}}}}
        lst = [prod] if body["variables"]["cid"] == "c9" else []
        return {"data": {"catalog": {"category": {"productsWithMetaData": {"totalCount": len(lst), "list": lst}}}}}
    http = FakeHttp([("access-tokens", {"apps": {tracker.WIX_STORES_APP: {"instance": "tok"}}}), ("storefront-web/api", post)])
    items, n = tracker.wix_run(http, "089kits", "https://www.089kits.de")
    assert n == 1 and len(items) == 1
    it = items[0]
    assert it["url"] == "https://www.089kits.de/product-page/spain-2010-away" and it["price"] == "95 EUR"
    assert it["image"] == "https://static.wixstatic.com/media/abc.jpg" and passt(it)
    assert tracker.condition_info(it["title"], it["desc"])[0] == "Excellent"


# ---------------------------------------------------------------------------
# Eigene Shopsysteme (Such-Ergebnisseite + Produktseite mit JSON-LD)
# ---------------------------------------------------------------------------
HTML_CFG = {"suche": "/suche?q={q}", "link": "a.product-url", "groessen": "select.size option"}
HTML_SEARCH = """<a class="product-url" href="/p/thiago-bayern">Adidas FC Bayern Trikot 6 Thiago Alcantara 2015/16 heim € 99,99</a>
<a class="product-url" href="/p/schal">FC Bayern Schal</a>"""
HTML_PRODUCT = """<script type="application/ld+json">{"@type": "Product", "description": "Zustand: sehr gut",
"image": ["/img/t.jpg"], "offers": {"price": "99.99", "priceCurrency": "EUR", "availability": "https://schema.org/InStock"}}</script>
<select class="size"><option>XL</option></select>"""
HTML_SOLD = HTML_PRODUCT.replace("InStock", "OutOfStock")


def test_html_anbindung():
    http = FakeHttp([("/suche", HTML_SEARCH), ("/p/thiago-bayern", HTML_PRODUCT)])
    items, n = tracker.html_run(http, "Originaltrikot", "https://ot.de", ["thiago"], M, HTML_CFG)
    assert n == 2 and len(items) == 1
    it = items[0]
    assert it["title"] == "Adidas FC Bayern Trikot 6 Thiago Alcantara 2015/16 heim"   # Preis abgeschnitten
    assert it["price"] == "99.99 EUR" and it["size_text"] == "XL" and it["image"] == "https://ot.de/img/t.jpg"
    assert passt(it)
    http = FakeHttp([("/suche", HTML_SEARCH), ("/p/thiago-bayern", HTML_SOLD)])
    assert tracker.html_run(http, "Originaltrikot", "https://ot.de", ["thiago"], M, HTML_CFG)[0] == []   # verkauft


# ---------------------------------------------------------------------------
# FindYourJersey
# ---------------------------------------------------------------------------
def fyj_row(desc, url, reissue="false", size="XL"):
    return {"description": desc, "sourceUrl": url, "isReissue": reissue, "size": size, "currentValue": 50,
            "currency": "GBP", "sourceType": "retailer", "imageUrl": "https://i/x.jpg", "player": None, "team": "x"}


def test_fyj_filtert_marktplaetze_direkte_shops_und_zaehlt_nachbauten(monkeypatch):
    rows = [fyj_row("2013-14 Bayern Thiago #6 Shirt XL", "https://www.kitshop.com/a"),
            fyj_row("2013-14 Bayern Thiago #6 Shirt XL (Reissue)", "https://www.kitshop.com/b", reissue="true"),
            fyj_row("Thiago Bayern Trikot", "https://www.ebay.de/itm/1"),
            fyj_row("Thiago Bayern Trikot", "https://vfa.com/products/x")]
    tracker.FYJ_DOMAIN_STATS.clear()
    http = FakeHttp([("findyourjersey", lambda p: rows if p.get("page") == 1 and p.get("search") == "thiago" else [])])
    m = tracker.Matcher({"spieler": [{"name": "Thiago", "suche": ["thiago"], "prioritaet": "hoch"}]})
    items, n = tracker.fyj_run(http, m, True, skip_domains={"vfa.com"})
    assert {it["url"] for it in items} == {"https://www.kitshop.com/a", "https://www.kitshop.com/b"}
    # XL und XXL werden einzeln abgefragt, doppelte Zeilen fasst erst die Auswertung über die URL zusammen
    assert [it["fyj_reissue"] for it in items] == [False, True, False, True]   # "true" kommt als Text
    assert tracker.FYJ_DOMAIN_STATS["kitshop.com"] == [4, 2]               # XL und XXL abgefragt: doppelt gezählt


# ---------------------------------------------------------------------------
# Seitenprüfung (verkauft? Hersteller?)
# ---------------------------------------------------------------------------
def test_check_page_json_ld():
    page = """<script type="application/ld+json">{"@graph": [{"@type": "Product", "description": "CONDITION: 8/10",
    "brand": {"name": "Official"}, "offers": [{"availability": "http://schema.org/OutOfStock"}]}]}</script>"""
    res = tracker.check_page(FakeHttp([("x.com", page)]), "https://x.com/p")
    assert res == {"verfuegbar": False, "desc": "CONDITION: 8/10", "marke": "Official"}
    assert tracker.check_page(FakeHttp([]), "https://x.com/p") is None   # Seite nicht erreichbar
