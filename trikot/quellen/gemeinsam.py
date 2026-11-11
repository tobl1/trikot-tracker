"""Gemeinsames Artikelformat aller Anbindungen"""

import re


def item(source, shop, url, title, size_text, price="", image="", extra="", desc="", **more):
    return {"source": source, "shop": shop, "url": url, "title": title.strip(),
            "size_text": size_text or "", "price": price, "image": image or "",
            "match_text": f"{title} {extra}".strip(), "desc": desc or "", **more}


def page_failed(http, data):
    """Seite beim Blättern kam mit Fehler statt leer zurück (403, 429, 5xx): merken, der Katalog ist dann unvollständig.
    Football & Vintage Amsterdam (11.11.2026): Seite 2 mit 403, der Run nahm 100 statt 657 Produkte als ganzen Bestand"""
    if data is None and getattr(http, "last_status", None) not in (None, 200, 400, 404):
        http.abgebrochen = http.last_status


SIZE_ATTR_RX = re.compile(r"size|grosse|groesse|taille|talla|maat|rozmiar|storrelse|koko|tamanho|taglia")
