"""Shops, die nur über ihre Suchseite abgefragt werden (CFS, IdoSell, eigene Systeme, PrestaShop, SmartWeb)"""

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..basis import ANY_SIZE_RX, norm, plain
from ..preise import parse_price
from ..zustand import SOLD_RX, ld_products
from .gemeinsam import item


def cfs_run(http, shop, base, queries):
    items, n, urls = [], 0, set()
    for q in queries:
        for page in range(1, 6):
            txt = http.get(f"{base}/catalogsearch/result/", {"q": q, "p": page}, want="text")
            if not txt:
                break
            soup = BeautifulSoup(txt, "html.parser")
            new = 0
            for el in soup.select(".product-item"):
                a = el.select_one('a[href$=".html"]')
                img = el.find("img")
                title = (img.get("alt") if img else "") or (a.get_text(" ", strip=True) if a else "")
                if not a or not title:
                    continue
                url = a["href"] if a["href"].startswith("http") else base + a["href"]
                if url in urls:
                    continue
                urls.add(url)
                new += 1
                pr = el.select_one(".price")
                src = (img.get("src") or img.get("data-src") or "") if img else ""
                items.append(item("direkt", shop, url, title, title,
                                  pr.get_text(strip=True) if pr else "", src))
            n += new
            if new == 0:
                break
    return items, n


def smartweb_run(http, shop, base, queries, currency="DKK"):
    """SmartWeb-Shops (z. B. ReShirt): interne Such-Schnittstelle /json/products"""
    items, n, urls = [], 0, set()
    for q in queries:
        for page in range(1, 6):
            data = http.get(f"{base}/json/products", {
                "currencyIso": currency, "field": "search", "filter": "{}", "id": q,
                "limit": 48, "orderBy": "-Id", "page": page})
            prods = (data or {}).get("products") or []
            if isinstance(prods, dict):
                prods = list(prods.values())
            if not prods:
                break
            n += len(prods)
            for p in prods:
                if str(p.get("Soldout")).lower() == "true":
                    continue
                handle = p.get("Handle") or ""
                url = base + handle if handle.startswith("/") else handle
                if not url or url in urls:
                    continue
                urls.add(url)
                title = p.get("Title") or ""
                price = ""
                pr = p.get("Prices") or []
                if isinstance(pr, list) and pr and isinstance(pr[0], dict):
                    price = f"{pr[0].get('PriceMinWithVat', pr[0].get('PriceMin', ''))} {currency}"
                imgs = p.get("Images") or []
                img = (base + imgs[0]) if imgs and isinstance(imgs[0], str) and imgs[0].startswith("/") else ""
                items.append(item("direkt", shop, url, title, title, price, img))
            if len(prods) < 48:
                break
    return items, n


def idosell_run(http, shop, base, queries, matcher, max_pages=6):
    """IdoSell (z. B. classic-shirts.com): Suche zeigt nur Verfügbares, 50 pro Seite, Blättern per counter.
    Bei Sammelangeboten ("Multiple Sizes") stehen die noch verfügbaren Größen nur auf der Produktseite"""
    items, n, urls = [], 0, set()
    for q in queries:
        for page in range(max_pages):
            txt = http.get(f"{base}/search.php", {"text": q, "counter": page}, want="text")
            if not txt:
                break
            tiles = BeautifulSoup(txt, "html.parser").select("div.product[data-product_id]")
            n += len(tiles)
            for el in tiles:
                a = el.select_one("a.product__name")
                if not a or not a.get("href"):
                    continue
                url = urljoin(base + "/", a["href"])
                title = a.get_text(" ", strip=True)
                desc, detail = "", None
                if url not in urls and not matcher.labels(title) and matcher.needs_detail(title):
                    detail = http.get(url, want="text") or ""     # Code steht nur auf der Produktseite
                    for tag in BeautifulSoup(detail, "html.parser").find_all("script", type="application/ld+json"):
                        try:
                            desc = desc or " ".join(plain(p.get("description")) for p in ld_products(json.loads(tag.string or "")))
                        except ValueError:
                            pass
                if url in urls or not matcher.labels(title, desc=desc):
                    continue
                urls.add(url)
                pr = el.select_one("strong.price")
                price = (pr.find(string=True, recursive=False) or "").strip() if pr else ""
                img = el.select_one("img")
                src = urljoin(base + "/", img.get("src", "")) if img and img.get("src") else ""
                size_text = title
                if not ANY_SIZE_RX.search(norm(title)):
                    detail = detail if detail is not None else (http.get(url, want="text") or "")
                    sizes = [x.get_text(strip=True) for x in
                             BeautifulSoup(detail, "html.parser").select(".projector_sizes__name")]
                    size_text = " ".join(sizes) or "__keine__"
                items.append(item("direkt", shop, url, title, size_text, price, src, pruefen=True, desc=desc))
            if len(tiles) < 50:
                break
    return items, n


def html_run(http, shop, base, queries, matcher, cfg):
    """Allgemeine Anbindung über Such-Ergebnisseiten (z. B. Gambio, eigene Shopsysteme), konfiguriert
    in shops.yaml: suche (URL mit {q}), link (CSS-Selektor der Produktlinks), optional groessen (CSS
    der Größen-Auswahl auf der Produktseite). Produktseiten werden nur für passende Titel geladen"""
    from urllib.parse import quote_plus
    items, n, urls = [], 0, set()
    for q in queries:
        txt = http.get(base + cfg["suche"].format(q=quote_plus(q)), want="text")
        if not txt:
            continue
        links = BeautifulSoup(txt, "html.parser").select(cfg["link"])
        n += len(links)
        for a in links:
            url = urljoin(base + "/", a.get("href", ""))
            title = re.sub(r"\s*€\s*[\d.,]+.*$", "", a.get("title") or a.get_text(" ", strip=True)).strip()
            if not title or url in urls or not matcher.labels(title):
                continue
            urls.add(url)
            page = http.get(url, want="text") or ""
            soup = BeautifulSoup(page, "html.parser")
            desc, img, price, avail = "", "", "", []
            for tag in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(tag.string or "")
                except ValueError:
                    continue
                for prod in ld_products(data):
                    desc = desc or plain(prod.get("description"))
                    im = prod.get("image")
                    img = img or (im[0] if isinstance(im, list) and im else im if isinstance(im, str) else "")
                    offers = prod.get("offers") or []
                    for o in offers if isinstance(offers, list) else [offers]:
                        if isinstance(o, dict):
                            if o.get("availability"):
                                avail.append(str(o["availability"]))
                            if o.get("price") and not price:
                                price = f"{o['price']} {o.get('priceCurrency') or ''}".strip()
            if avail and all(SOLD_RX.search(x) for x in avail):
                continue
            text = re.sub(r"\s+", " ", soup.get_text(" "))
            if not price:   # erster Preis über 0 (Seiten zeigen oft einen leeren Warenkorb "€ 0,00")
                for m in re.finditer(r"€\s?[\d.]+,\d{2}|[\d.]+,\d{2}\s?€", a.get_text(" ", strip=True) + " " + text):
                    if (parse_price(m.group(0))[0] or 0) > 0:
                        price = m.group(0)
                        break
            sizes = [o.get_text(" ", strip=True) for o in soup.select(cfg["groessen"])] if cfg.get("groessen") else []
            if not sizes:
                m = re.search(r"(?i)(?:size|taglia|grö(?:ß|ss)e|talla|taille)\s*:\s*(\S{1,12})", text)
                sizes = [m.group(1)] if m else []
            size_text = " ".join(sizes) if sizes else title
            if not img:
                og = soup.find("meta", property="og:image")
                img = og.get("content", "") if og else ""
            cond = re.search(r"(?i)(?:condizioni|condition|zustand)\s*:\s*([a-z ]{3,20})", text)
            items.append(item("direkt", shop, url, title, size_text, price, urljoin(base + "/", img) if img else "",
                              desc=f"{desc} {'Condition: ' + cond.group(1) if cond else ''}".strip()))
    return items, n


def prestashop_run(http, shop, base, queries, matcher, search_path="/szukaj"):
    """PrestaShop 1.7+: Suche liefert JSON, Größe steht erst auf der Produktseite"""
    items, n, urls = [], 0, set()
    for q in queries:
        for page in range(1, 4):
            http.s.headers.update({"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
            data = http.get(base + search_path, {"controller": "search", "s": q, "page": page})
            http.s.headers.pop("X-Requested-With", None)
            http.s.headers["Accept"] = "*/*"
            prods = (data or {}).get("products") or []
            if not prods:
                break
            n += len(prods)
            for p in prods:
                url, title = p.get("url") or "", p.get("name") or ""
                if not url or url in urls or not matcher.labels(title):
                    continue
                urls.add(url)
                page_html = http.get(url, want="text") or ""
                soup = BeautifulSoup(page_html, "html.parser")
                sizes = [e.get_text(" ", strip=True) for e in
                         soup.select(".product-variants .radio-label, .product-variants option, "
                                     ".product-variants .input-color + span")]
                if soup.select_one(".product-unavailable, #product-availability .product-unavailable"):
                    continue
                img = ((p.get("cover") or {}).get("large") or {}).get("url", "")
                items.append(item("direkt", shop, url, title, " ".join(sizes) or title, p.get("price", ""), img))
            pag = (data or {}).get("pagination") or {}
            if page >= int(pag.get("pages_count") or 1):
                break
    return items, n
