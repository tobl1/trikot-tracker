"""Gemeinsames Artikelformat aller Anbindungen"""

import re


def item(source, shop, url, title, size_text, price="", image="", extra="", desc="", **more):
    return {"source": source, "shop": shop, "url": url, "title": title.strip(),
            "size_text": size_text or "", "price": price, "image": image or "",
            "match_text": f"{title} {extra}".strip(), "desc": desc or "", **more}


SIZE_ATTR_RX = re.compile(r"size|grosse|groesse|taille|talla|maat|rozmiar|storrelse|koko|tamanho|taglia")
