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


# ---------------------------------------------------------------------------
# Ehrliche Quellenwerte, sicheres Speichern, Postausgang
# ---------------------------------------------------------------------------
import trikot.melden  # noqa: E402
import trikot.quellen  # noqa: E402
import trikot.speicher  # noqa: E402
from trikot.lauf import stock_collapse  # noqa: E402


def run_shop_mit(monkeypatch, http, shop):
    monkeypatch.setattr(trikot.quellen, "Http", lambda *a, **k: http)
    return trikot.quellen.run_shop(shop, "full", M, {}, {})


def test_run_shop_meldet_sperre_statt_keine_produkte(monkeypatch):
    http = FakeHttp([])
    http.codes[403] = 2                     # Shop blockt Server-Adressen
    items, st = run_shop_mit(monkeypatch, http, {"name": "CFS", "url": "https://cfs.co.uk", "plattform": "cfs"})
    assert items == [] and st["fehler"].startswith("gesperrt (HTTP 403)")


def test_run_shop_keine_produkte_mit_codes(monkeypatch):
    http = FakeHttp([])
    http.codes[404] = 1
    _, st = run_shop_mit(monkeypatch, http, {"name": "CFS", "url": "https://cfs.co.uk", "plattform": "cfs"})
    assert st["fehler"] == "keine Produkte erhalten (HTTP 404 ×1)"


def test_run_shop_ok_mit_hinweis(monkeypatch):
    http = FakeHttp([("/catalogsearch/result/", CFS_PAGE)])
    http.codes[404] = 3                      # einzelne tote Links sind kein Fehler, aber sichtbar
    items, st = run_shop_mit(monkeypatch, http, {"name": "CFS", "url": "https://cfs.co.uk", "plattform": "cfs"})
    assert items and st["fehler"] == "" and st["info"] == "HTTP 404 ×3"


def test_bestandseinbruch_dreimal_dann_echt():
    c = {}
    assert stock_collapse(c, "VFA", 25000, 24000) == ""                      # normal
    assert stock_collapse(c, "VFA", 9000, 25000).startswith("Bestandseinbruch: 9000 statt 25000")
    assert stock_collapse(c, "VFA", 9000, 25000).startswith("Bestandseinbruch")
    assert stock_collapse(c, "VFA", 9000, 25000) == ""                         # 3. Mal: gilt als echt
    assert stock_collapse({}, "Klein", 10, 80) == ""                           # kleine Shops nicht prüfen
    c = {"VFA": 1}
    assert stock_collapse(c, "VFA", 24000, 25000) == "" and "VFA" not in c     # erholt: Zähler weg


def test_kaputte_datei_bricht_ab(tmp_path):
    f = tmp_path / "seen.json"
    f.write_text('{"a": 1', encoding="utf-8")                                    # abgeschnitten
    with pytest.raises(trikot.speicher.DatenFehler):
        trikot.speicher.load_json(f, {}, strict=True)
    assert trikot.speicher.load_json(f, {"leer": True}) == {"leer": True}       # unkritische Dateien: Standard
    assert trikot.speicher.load_json(tmp_path / "fehlt.json", [], strict=True) == []


def test_speichern_ohne_zwischendatei(tmp_path):
    f = tmp_path / "x" / "status.json"
    trikot.speicher.save_json(f, {"b": 2, "a": 1})
    assert json.loads(f.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    assert not list(f.parent.glob("*.tmp"))


def test_postausgang(tmp_path, monkeypatch):
    monkeypatch.setattr(trikot.speicher, "OUTBOX_FILE", tmp_path / "postausgang.json")
    trikot.melden.POSTAUSGANG.clear()
    trikot.melden.push("🔥 Thiago · Shop", "Text", 5, "https://x", "https://img", ["fire"])
    trikot.melden.push("⚽ 2 neue Treffer", "Text", 3)
    assert trikot.melden.save_outbox() == 2 and not trikot.melden.POSTAUSGANG
    saved = json.loads((tmp_path / "postausgang.json").read_text(encoding="utf-8"))
    assert [e["title"] for e in saved] == ["🔥 Thiago · Shop", "⚽ 2 neue Treffer"]
    from cryptography.hazmat.primitives.asymmetric import ec
    from trikot import webpush
    key = ec.generate_private_key(ec.SECP256R1())
    st = {"push_abos": {"a": {"blob": webpush.seal_abo({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "x", "auth": "y"}},
                                                       webpush.public_key_b64(key)), "seit": "1"}}}
    monkeypatch.setattr(trikot.melden.webpush, "send", lambda s, msg, k: 201 if msg["title"].startswith("🔥") else 500)
    sent, left, dropped, problems = trikot.melden.send_outbox(st, key)
    assert (sent, left, dropped) == (1, 1, 0)                                    # einer klappt, einer bleibt
    left = json.loads((tmp_path / "postausgang.json").read_text(encoding="utf-8"))
    assert [e["title"] for e in left] == ["⚽ 2 neue Treffer"]
    left[0]["zeit"] = "2020-01-01T00:00:00+00:00"                               # zu alt: verwerfen
    (tmp_path / "postausgang.json").write_text(json.dumps(left), encoding="utf-8")
    assert trikot.melden.send_outbox(st, key)[:3] == (0, 0, 1)


def test_probelauf_schreibt_nichts_in_den_postausgang(capsys):
    trikot.melden.POSTAUSGANG.clear()
    trikot.melden.push("Titel", "Text", dry=True)
    assert not trikot.melden.POSTAUSGANG and "[PUSH p3] Titel" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Neuheiten-Radar
# ---------------------------------------------------------------------------
import datetime as _dt  # noqa: E402

from trikot.lauf import radar_due, radar_job, radar_shops  # noqa: E402


def test_radar_kleine_seiten_weiterblaettern_nur_wenn_alles_neu():
    t = tracker.now()
    neu = lambda i: shopify_prod(f"Shirt {i}", f"h{i}", [var("XL")], published=(t - _dt.timedelta(minutes=i)).isoformat())
    page1 = [neu(i) for i in range(40)]                           # alle 40 neuer als die letzte Prüfung
    page2 = [neu(i) for i in range(40, 80)]
    http = FakeHttp([("/products.json", lambda p: {"products": page1 if p["page"] == 1 else page2})])
    items, n = tracker.shopify_newest(http, "Shop", "https://s.com", "EUR", since=t - _dt.timedelta(minutes=50))
    assert n == 80 and len(http.calls) == 2 and all(c[1]["limit"] == 40 for c in http.calls)
    http = FakeHttp([("/products.json", lambda p: {"products": page1})])
    tracker.shopify_newest(http, "Shop", "https://s.com", "EUR", since=t - _dt.timedelta(minutes=10))
    assert len(http.calls) == 1                                   # Seite reicht schon bis zur letzten Prüfung


def test_radar_faellig_und_auswahl():
    t = tracker.now()
    assert radar_due({}, t)
    assert not radar_due({"radar_zeit": (t - _dt.timedelta(minutes=10)).isoformat()}, t)
    assert radar_due({"radar_zeit": (t - _dt.timedelta(minutes=30)).isoformat()}, t)
    shops = [{"name": "A", "url": "https://a.com"}, {"name": "B", "url": "https://b.com/"},
             {"name": "C", "url": "https://c.com", "plattform": "wix"}, {"name": "D", "url": "https://d.com", "sperren": "ja"},
             {"name": "E", "url": "https://e.com"}, {"name": "F", "url": "https://f.com", "plattform": "cfs"}]
    platforms = {"https://a.com": "shopify", "https://b.com": "woo:https://b.com/wp-json/wc/store/v1/products",
                 "https://d.com": "shopify", "https://e.com": "unbekannt"}
    assert [s["name"] for s in radar_shops(shops, platforms)] == ["A", "B"]
    job = radar_job({"name": "A", "url": "https://a.com"}, {"A": t.isoformat()})
    assert job["_seit"] == t and radar_job({"name": "X", "url": "x"}, {})["_seit"] is None


def test_run_shop_radar_spart_waehrungsabfrage(monkeypatch):
    http = FakeHttp([("/products.json", {"products": [shopify_prod("2019/20 Bayern Munich Thiago #6 (XL)", "t", [var("Default Title")])]})])
    shop = {"name": "VFA", "url": "https://vfa.com", "_seit": None}
    items, st = run_shop_mit_modus(monkeypatch, http, shop, "radar", {"https://vfa.com": "shopify"}, {"https://vfa.com": "EUR"})
    assert len(items) == 1 and items[0]["price"] == "79.99 EUR" and st["fehler"] == ""
    assert not any("cart.js" in u for u, _ in http.calls)        # gemerkte Währung genügt


def run_shop_mit_modus(monkeypatch, http, shop, mode, platforms, currencies):
    monkeypatch.setattr(trikot.quellen, "Http", lambda *a, **k: http)
    return trikot.quellen.run_shop(shop, mode, M, platforms, currencies)


def test_token_erinnerung():
    from trikot.lauf import token_reminder
    end = _dt.date.fromisoformat(tracker.CRON_TOKEN_ABLAUF)
    assert token_reminder(end - _dt.timedelta(days=60)) == []
    assert "läuft am" in token_reminder(end - _dt.timedelta(days=10))[0][1]
    assert "abgelaufen" in token_reminder(end + _dt.timedelta(days=1))[0][1]


def test_shop_mit_passwortseite(monkeypatch):
    http = FakeHttp([])
    http.codes[401] = 1
    _, st = run_shop_mit(monkeypatch, http, {"name": "Kick It", "url": "https://k.de", "plattform": "cfs"})
    assert st["fehler"].startswith("geschlossen (Passwortseite")


def test_thiago_immer_mit_push():
    from trikot.lauf import stays_silent
    thiago, hsv = {"labels": ["Thiago"]}, {"labels": ["HSV 1990-2016"]}
    assert not stays_silent(thiago, False, True, set())              # neue Quelle: Thiago trotzdem einzeln
    assert stays_silent(hsv, False, True, set())                      # andere: still, Sammelnachricht
    assert stays_silent(hsv, False, False, {"HSV 1990-2016"})        # neue Kategorie: still
    assert not stays_silent(hsv, False, False, set())
    assert stays_silent(thiago, True, False, set())                   # Erstlauf: alles still


# Meldungen vom 05.10.2026 (VFA: Hose, Trainingsshirt, falsches Größen-Schlagwort; trikotcult "drittes Trikot")
def test_vfa_produktart_short_ist_hose():
    assert M.type_excluded("Short") and M.type_excluded("Shorts") and not M.type_excluded("Maillot")


def test_beschreibung_training_und_hose():
    from trikot.zustand import desc_excluded
    assert desc_excluded("Etat : Excellent Taille : XL Le maillot en détail : Maillot d'entrainement porté par les Blaugrana",
                         "2009/10 - Barcelone (XL)") == "Beschreibung: Trainingsshirt"
    assert desc_excluded("Etat : Neuf Le short en détail : Short en excellent état", "2008/09 - Barcelone (XL)") == "Beschreibung: Hose"
    assert desc_excluded("Etat : Excellent Le maillot en détail : Maillot domicile porté par Messi", "2009/10 - Barcelone (XL)") == ""


def test_groesse_im_titel_schlaegt_schlagwort():
    p = shopify_prod("2009/10 - Barcelone (L)", "b", [var("Default Title")], tags=["Taille XL"])
    assert not passt(tracker.shopify_to_item("VFA", "https://vfa.com", p))
    p = shopify_prod("2009/10 - Barcelone (XL)", "b", [var("Default Title")], tags=["Taille XL"])
    assert passt(tracker.shopify_to_item("VFA", "https://vfa.com", p))
    p = shopify_prod("Real Madrid drittes Trikot 2012/13 - M", "r", [var("Default Title")], tags=["XL"])
    assert tracker.shopify_to_item("Trikotcult", "https://t.de", p)["size_text"] == "Real Madrid drittes Trikot 2012/13 - M"
    p = shopify_prod("FC Barcelona Heimtrikot 2009/10", "f", [var("Default Title")], tags=["XL"])   # ohne Größe im Titel
    assert passt(tracker.shopify_to_item("Trikotcult", "https://t.de", p))


def test_drittes_trikot_ist_third():
    assert {l for l, _ in M.labels("Liverpool FC drittes Trikot 2022/23 - XL")} == {"Liverpool Third 2022/23"}
    assert {l for l, _ in M.labels("Liverpool FC Heimtrikot 2022/23 - XL")} == set()
    assert {l for l, _ in M.labels("Chamarra Brasil 94 2006")} == set()


# ---------------------------------------------------------------------------
# Prüfen vor dem Push
# ---------------------------------------------------------------------------
import trikot.pruefung  # noqa: E402
from trikot.pruefung import hold_unchecked  # noqa: E402


def entry(url, **kw):
    e = {"url": url, "title": "2009-10 BARCELONA SHIRT XL", "labels": ["Barça 2008-2013"], "prios": ["hoch"],
         "last": "T", "shop": "Classic-Shirts", "pruefen": True}
    e.update(kw)
    return e


def test_ungepruefte_treffer_warten_auf_die_seitenpruefung():
    ts = tracker.now().isoformat()
    a = entry("https://classic-shirts.com/a")                                  # Prüfung gescheitert (z. B. 429)
    b = entry("https://classic-shirts.com/b", geprueft=ts)                     # geprüft: sofort pushen
    c = entry("https://topbinz.co.uk/c", pruef_fehler=403)                     # gesperrt: nicht prüfbar, pushen
    d = entry("https://vfa.com/products/d", pruefen=False)                     # Shopify direkt: keine Prüfung nötig
    out = hold_unchecked([a, b, c, d], {}, ts)
    assert out == [b, c, d] and a["push_offen"] == ts and c["ungeprueft"] and "ungeprueft" not in b


def test_zurueckgehaltene_werden_spaeter_freigegeben_oder_verworfen():
    t0 = (tracker.now() - _dt.timedelta(hours=2)).isoformat()
    ts = tracker.now().isoformat()
    ok = entry("https://x/ok", push_offen=t0, geprueft=ts)
    weg = entry("https://x/weg", push_offen=t0, geprueft=ts, aussortiert="Hersteller Official")
    noch = entry("https://x/noch", push_offen=t0)
    alt = entry("https://x/alt", push_offen=(tracker.now() - _dt.timedelta(hours=30)).isoformat())
    seen = {e["url"]: e for e in (ok, weg, noch, alt)}
    out = hold_unchecked([], seen, ts)
    assert out == [ok, alt] and alt["ungeprueft"]
    assert "push_offen" not in weg and noch["push_offen"] == t0


def test_seitenpruefung_zaehlt_fehler_und_sortiert_aus(monkeypatch):
    ts = tracker.now().isoformat()
    official = """<script type="application/ld+json">{"@type": "Product", "description": "CONDITION: 8/10",
    "brand": {"name": "Official"}, "offers": [{"availability": "InStock"}]}</script>"""

    class H(FakeHttp):
        def get(self, url, params=None, want="json"):
            self.last_status = {"ok": 200, "voll": 429, "weg": 404}[url.rsplit("/", 1)[1]]
            return official if self.last_status == 200 else None
    monkeypatch.setattr(trikot.pruefung, "Http", lambda *a, **k: H([]))
    seen = {k: entry(f"https://classic-shirts.com/{k}", last=ts) for k in ("ok", "voll", "weg")}
    n, fails = trikot.pruefung.enrich(seen, ts, 10, M)
    assert n == 3 and seen["ok"]["aussortiert"] == "Hersteller Official" and seen["ok"]["geprueft"] == ts
    assert seen["voll"]["pruef_fehler"] == 429 and "geprueft" not in seen["voll"]
    assert seen["weg"]["verkauft"] == ts
    assert dict(fails["classic-shirts.com"]) == {429: 1, 404: 1}


# ---------------------------------------------------------------------------
# Vereinsfilter mit Kontext (Schlagwörter, Produktart, Produktadresse)
# ---------------------------------------------------------------------------
def test_vereinsfilter_nutzt_schlagwoerter():
    p = shopify_prod("Thiago #6 Away Shirt XL", "away-shirt-thiago-6", [var("Default Title")], tags=["Liverpool", "Premier League"])
    it = tracker.shopify_to_item("Shop", "https://s.com", p)
    assert {l for l, _ in M.labels(it["match_text"], ctx=it["ctx"])} == {"Thiago"}
    assert M.labels(it["match_text"]) == []                                  # ohne Kontext: Verein fehlt
    p = shopify_prod("Thiago #6 Away Shirt XL", "away-shirt-thiago-6", [var("Default Title")], tags=["PSG"])
    it = tracker.shopify_to_item("Shop", "https://s.com", p)
    assert M.labels(it["match_text"], ctx=it["ctx"]) == []                   # anderer Verein: weiter nein
    # Kontext ersetzt nie den Spielernamen und gilt nicht für Sondertrikots
    assert M.labels("Away Shirt 2021/22 XL", ctx="liverpool thiago") == []


def test_woo_kontext_aus_kategorien():
    p = woo_prod("Thiago Alcantara #6 Shirt", ["XL"])
    p["categories"] = [{"name": "FC Bayern München"}]
    it = tracker.woo_to_item("RB", p)
    assert {l for l, _ in M.labels(it["match_text"], ctx=it["ctx"])} == {"Thiago"}


# ---------------------------------------------------------------------------
# Gekappte Kataloge: Thiago-Vereine über Kollektionen
# ---------------------------------------------------------------------------
def test_kollektionen_der_thiago_vereine():
    terms = M.high_team_terms()
    assert {"bayern", "liverpool", "barcelone", "espagne"} <= set(terms)
    cols = [{"handle": "fc-barcelone-tous-les-maillots", "title": "FC Barcelone", "products_count": 6844},
            {"handle": "bayern-munichtouslesmaillots", "title": "Bayern Munich", "products_count": 3572},
            {"handle": "france-tous-les-maillots", "title": "France", "products_count": 23341},
            {"handle": "juventus-tous-les-maillots", "title": "Juventus", "products_count": 4449},
            {"handle": "espagne", "title": "Espagne", "products_count": 1577}]
    http = FakeHttp([("/collections.json", {"collections": cols})])
    assert tracker.shopify_collections(http, "https://vfa.com", terms) == [
        "fc-barcelone-tous-les-maillots", "bayern-munichtouslesmaillots", "espagne"]


def test_gekappter_katalog_liest_kollektionen(monkeypatch):
    big = [shopify_prod(f"Shirt {i}", f"h{i}", [var("XL")]) for i in range(250)]
    old = shopify_prod("2009/10 - Barcelone (XL)", "2009-10-barcelone-xl-3", [var("Default Title")])

    def products(p):
        return {"products": big}
    http = FakeHttp([("/collections.json", {"collections": [{"handle": "fc-barcelone", "title": "FC Barcelone",
                                                            "products_count": 1}]}),
                     ("/collections/fc-barcelone/products.json", lambda p: {"products": [old] if p["page"] == 1 else []}),
                     ("/products.json", products), ("/cart.js", {"currency": "EUR"}), ("/search", "")])
    items, st = run_shop_mit_modus(monkeypatch, http, {"name": "VFA", "url": "https://vfa.com"}, "full",
                                   {"https://vfa.com": "shopify"}, {})
    assert any(it["title"] == "2009/10 - Barcelone (XL)" for it in items)
    assert st["info"].startswith("Katalog bei 25000 gekappt, ältere Artikel per Kollektionen (1)")


# ---------------------------------------------------------------------------
# Warum Treffer, wackelige Angaben
# ---------------------------------------------------------------------------
def test_begruendung_und_groessenquelle():
    why = {}
    M.labels("2009/10 - Barcelone (XL)", why=why)
    assert why["Barça 2008-2013"] == "Team „barcelone“, Saison „2009/10“, Variante egal, ohne fremden Flock"
    why = {}
    M.labels("Thiago #6 Away Shirt XL", ctx="liverpool", why=why)
    assert why["Thiago"] == "Name „thiago“, Team laut Shop „liverpool“"
    p = shopify_prod("2012-13 Barcelona Home Shirt", "b", [var("Default Title")], tags=["XL"])
    assert tracker.shopify_to_item("S", "https://s.com", p)["size_src"] == "schlagwort"
    p = shopify_prod("2012-13 Barcelona Home Shirt (XL)", "b", [var("Default Title")])
    assert tracker.shopify_to_item("S", "https://s.com", p)["size_src"] == "titel"
    from trikot.berichte import doubt
    assert doubt({"groesse_quelle": "schlagwort"}).startswith("Größe nur aus einem Schlagwort")
    assert doubt({"push_offen": "t"}) == "Shop-Seite wird noch geprüft" and doubt({}) == ""


# Flock nur in der Beschreibung (trikotcult.de, 05.10.2026)
@pytest.mark.parametrize("desc,flock", [
    ("Heimtrikot Real Madrid aus der Saison 2023/24 in der Größe XL. Flock: Toni Kroos #8 + La Liga Badge Zustand: Sehr gut", "Toni Kroos #8"),
    ("Auswärtstrikot Hamburger SV aus der Saison 2008/09 in der Größe XL. Flock: Ruud van Nistelrooy #22 + Bundesliga Batch", "Ruud van Nistelrooy #22"),
    ("Heimtrikot Juventus Turin aus der Saison 2011/12 in der Größe L. Flock Arturo Vidal #22 Zustand: Sehr gut", "Arturo Vidal #22"),
    ("Atletico Madrid Heimtrikot. Flock: La Liga Badge Zustand: Sehr gut", ""),
    ("Flock: ohne Zustand: gut", ""),
    ("Etat : Excellent Joueurs : Henry, Touré, Iniesta, Abidal", ""),
])
def test_flock_aus_beschreibung(desc, flock):
    from trikot.zustand import desc_flock
    assert desc_flock(desc) == flock


def test_flock_aus_beschreibung_im_abgleich():
    from trikot.zustand import desc_flock
    title = "Hamburger SV Auswärtstrikot 2008/09 - XL"
    text = title + " " + desc_flock("Flock: Ruud van Nistelrooy #22 + Bundesliga Batch")
    assert {l for l, _ in M.labels(text)} >= {"HSV 1990-2016"}
    sonder = "FC Barcelona Heimtrikot 2011/12 - XL " + desc_flock("Flock: Xavi #6 + La Liga Badge Zustand: Sehr gut")
    assert M.labels(sonder) == []          # fremder Flock: kein Thiago-Sondertrikot



def test_postausgang_an_die_app(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    from trikot import webpush
    monkeypatch.setattr(trikot.speicher, "OUTBOX_FILE", tmp_path / "postausgang.json")
    key = ec.generate_private_key(ec.SECP256R1())
    sub = lambda n: {"endpoint": f"https://web.push.apple.com/{n}", "keys": {"p256dh": "x", "auth": "y"}}
    st = {"push_abos": {"a": {"blob": webpush.seal_abo(sub("iphone"), webpush.public_key_b64(key)), "seit": "1"},
                        "b": {"blob": webpush.seal_abo(sub("alt"), webpush.public_key_b64(key)), "seit": "2"}}}
    trikot.melden.POSTAUSGANG.clear()
    trikot.melden.push("🔥 Thiago", "Bayern 15/16", 5, "https://x")
    trikot.melden.push("✅ Push aus der App ist aktiv", "…", 4, nur_abo="a")
    trikot.melden.save_outbox()
    calls = []
    monkeypatch.setattr(trikot.melden.webpush, "send", lambda s, msg, k: calls.append((s["endpoint"], msg["title"])) or (410 if "alt" in s["endpoint"] else 201))
    sent, left, dropped, problems = trikot.melden.send_outbox(st, key)
    assert sent == 2 and left == 0
    assert ("https://web.push.apple.com/iphone", "✅ Push aus der App ist aktiv") in calls
    assert not any(t == "✅ Push aus der App ist aktiv" and "alt" in u for u, t in calls)
    assert "b" not in st["push_abos"] and problems[0][0] == "App-Push"           # erloschenes Abo ausgetragen


def test_schnellrun_ueberspringt_shopify(monkeypatch):
    http = FakeHttp([])
    items, st = run_shop_mit_modus(monkeypatch, http, {"name": "VFA", "url": "https://vfa.com"}, "priority",
                                   {"https://vfa.com": "shopify"}, {})
    assert items == [] and st["fehler"] == "" and http.calls == []          # keine einzige Anfrage
    assert "Radar" in st["info"]


# Topbinz (ShopWired): Neuheiten-Seite im Radar, 10 Sek. Pause laut robots.txt
TB_TILE = """<article class="item-box product-box" data-product-id="1"><h3 class="product-box-title item-box-title">
<a href="https://www.topbinzfootballshirts.co.uk/bayern-munich-thiago-6-2015-16-home-shirt-xl">Bayern Munich Thiago #6 2015/16 Home Shirt - XL</a></h3>
<span class="price">£95.00</span></article>"""
TB_PAGE = """<script type="application/ld+json">{"@type": "Product", "offers": {"price": "95.00", "priceCurrency": "GBP",
"availability": "https://schema.org/InStock"}, "image": "https://cdn.ecommercedns.uk/x.jpg"}</script>"""
TB = {"name": "Topbinz", "url": "https://www.topbinzfootballshirts.co.uk", "plattform": "html", "pause": 10,
      "suche": "/search/products?keywords={q}", "link": "article.product-box h3 a", "neu": "/new-in"}


def test_topbinz_radar_liest_nur_neuheiten(monkeypatch):
    made = []

    def fake(*a, **k):
        h = FakeHttp([("/new-in", TB_TILE), ("thiago-6-2015-16", TB_PAGE)])
        made.append(k.get("delay"))
        return h
    monkeypatch.setattr(trikot.quellen, "Http", fake)
    items, st = trikot.quellen.run_shop(TB, "radar", M, {}, {})
    assert made == [10.0] and len(items) == 1 and items[0]["price"] == "95.00 GBP" and passt(items[0])
    from trikot.lauf import radar_shops
    assert [s["name"] for s in radar_shops([TB], {})] == ["Topbinz"]


def test_preissenkung_in_originalwaehrung():
    from trikot.lauf import price_drop
    assert price_drop("£100.00", "£80.00") == 20
    assert price_drop("100.00 EUR", "97.00 EUR") == 0          # unter 5 %
    assert price_drop("£100.00", "120.00 EUR") == 0            # andere Währung: nicht vergleichen
    assert price_drop("79.99 EUR", "89.99 EUR") == 0           # teurer
    assert price_drop("", "50 EUR") == 0


def test_shop_wieder_offen():
    from trikot.lauf import reopened
    closed = {}
    zu = {"name": "Kick It Vintage", "fehler": "geschlossen (Passwortseite, HTTP 401), z. B. vor einem Drop", "produkte": 0}
    assert reopened(closed, [zu], "t1") == [] and closed == {"Kick It Vintage": "t1"}
    assert reopened(closed, [zu], "t2") == [] and closed == {"Kick It Vintage": "t1"}      # bleibt beim ersten Mal
    schnell = {"name": "Kick It Vintage", "fehler": "", "produkte": 0}                       # z. B. Schnell-Run ohne Shopify
    assert reopened(closed, [schnell], "t3") == []
    offen = {"name": "Kick It Vintage", "fehler": "", "produkte": 40}
    assert reopened(closed, [offen], "t4") == [("Kick It Vintage", "t1")] and closed == {}
