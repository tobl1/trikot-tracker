"""Lightspeed eCom (C-Series), z. B. We Love Football Shirts: jede Seite liefert mit ?format=json ihre Daten"""

import re

from .gemeinsam import item, page_failed

LIGHTSPEED_PAGE_CAP = 100   # 10.000 Artikel (We Love Football Shirts: 4.484 am 02.11.2026)
VARIANT_SIZE_RX = re.compile(r"(?i)^(?:size|maat|grösse|größe|taille)\s+(.+)$")


def lightspeed_to_item(shop, p):
    if not p.get("available", True):
        return None
    title = p.get("title") or ""
    # Artikelcode mit Verein, Ausrüster, Variante, Saison, Flock, Größe: "FC_Barcelona_Nike_2025-2026_Supercopa_#10_
    # Yamal_XL(*BNWT)". Der Titel nennt nur Verein und Größe, die Saison steht nur hier und in der Beschreibung
    # Sternchen raus: "(*BNWT)" ergäbe mit "*BNWT" im Titel ein Sternchen-Wort, das als Flock gälte
    code = (p.get("code") or "").replace("_", " ").replace("*", "")
    # Größe aus der Variante ("Size XL"), sie stimmt mit Code und Beschreibung überein; der Titel irrt manchmal
    # ("Senegal (XL)" bei Variante und Code M, 02.11.2026)
    m = VARIANT_SIZE_RX.match((p.get("variant") or "").strip())
    size_text = m.group(1) if m else title
    pr = p.get("price") or {}
    price = f"{pr.get('price_incl') or pr.get('price') or ''} {(pr.get('currency') or 'EUR').upper()}".strip()
    img = re.sub(r"/\d+x\d+x\d/", "/600x600x2/", p.get("image") or "") if isinstance(p.get("image"), str) else ""
    return item("direkt", shop, p.get("url") or "", title, size_text, price, img, extra=code,
                desc=p.get("description") or "", ctx=(p.get("brand") or {}).get("title", ""))


def lightspeed_run(http, shop, base, pages=None, limit=100, lang="en"):
    """Ganze Kollektion, neueste zuerst (Drop-Run/Radar: nur die erste Seite)"""
    items, n = [], 0
    for page in range(1, (pages or LIGHTSPEED_PAGE_CAP) + 1):
        data = http.get(f"{base}/{lang}/collection/page{page}.ajax", {"format": "json", "limit": limit})
        prods = (data or {}).get("products") if isinstance(data, dict) else None
        prods = list(prods.values()) if isinstance(prods, dict) else prods or []
        if not prods:
            if page > 1:
                page_failed(http, data)
            break
        n += len(prods)
        items += [it for it in (lightspeed_to_item(shop, p) for p in prods) if it]
        if page >= int(data.get("pages") or 0):
            break
    return items, n
