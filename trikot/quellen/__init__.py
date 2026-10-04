"""Shop-Anbindungen: Abfrage eines Shops je nach Plattform und Plattform-Erkennung"""

import time

from ..basis import SHOPIFY_PAGE_CAP
from ..netz import Http, SHOPIFY_GATE
from ..rhythmus import rhythm
from .shopify import shopify_currency, shopify_full, shopify_recent, shopify_search
from .suchseiten import cfs_run, html_run, idosell_run, prestashop_run, smartweb_run
from .wix import WIX_STORES_APP, wix_run
from .woo import woo_endpoint, woo_recent, woo_run


def run_shop(shop, mode, matcher, platforms, currencies):
    name, base = shop["name"], shop["url"].rstrip("/")
    plat = (shop.get("plattform") or "auto").lower()
    http = Http()
    t0 = time.time()
    status = {"name": name, "plattform": plat, "produkte": 0, "fehler": "", "info": ""}
    try:
        if plat == "aus":
            status["fehler"] = "deaktiviert" + (f" ({shop['hinweis']})" if shop.get("hinweis") else "")
            return [], status
        if mode == "priority" and str(shop.get("schnellcheck", "ja")).lower() in ("nein", "false", "no", "aus"):
            status["info"] = "nur im Gesamtlauf"
            return [], status
        if plat == "fyj":
            status["plattform"] = "über FYJ"
            status["fehler"] = ""
            status["info"] = "wird über FindYourJersey abgedeckt"
            return [], status
        if plat == "smartweb":
            items, n = smartweb_run(http, name, base, matcher.queries(only_high=(mode == "priority")),
                                    shop.get("waehrung", "DKK"))
            status.update(produkte=n)
            return items, status
        if plat == "html":
            items, n = html_run(http, name, base, matcher.queries(only_high=(mode == "priority")), matcher, shop)
            status.update(produkte=n)
            return items, status
        if plat == "wix":
            items, n = wix_run(http, name, base)
            status.update(produkte=n)
            return items, status
        if plat == "idosell":
            items, n = idosell_run(http, name, base, matcher.queries(only_high=(mode == "priority")), matcher)
            status.update(produkte=n)
            return items, status
        if plat == "prestashop":
            items, n = prestashop_run(http, name, base, matcher.queries(only_high=(mode == "priority")),
                                      matcher, shop.get("suchpfad", "/szukaj"))
            status.update(produkte=n)
            return items, status
        if plat == "cfs":
            qs = matcher.queries(only_high=(mode == "priority"))
            items, n = cfs_run(http, name, base, qs)
            status.update(plattform="cfs", produkte=n)
            return items, status
        if plat == "auto":
            known = platforms.get(base)
            http.gate = SHOPIFY_GATE   # die Erkennung fragt zuerst Shopify-Pfade ab
            if mode == "full" or not known or known == "unbekannt":
                data = http.get(f"{base}/products.json", {"limit": 1})
                if isinstance(data, dict) and "products" in data:
                    detected = "shopify"
                else:
                    ep = woo_endpoint(http, base)
                    detected = ("woo:" + ep) if ep else "unbekannt"
                if detected == "unbekannt" and known and known != "unbekannt":
                    detected = known   # vermutlich nur ein Aussetzer, bekannte Plattform behalten
                known = platforms[base] = detected
            plat = known
            if plat != "shopify":
                http.gate = None
        status["plattform"] = plat.split(":")[0]
        if plat == "shopify":
            cur = shop.get("waehrung") or currencies.get(base, "")
            if not shop.get("waehrung"):   # jedes Mal, die Währung hängt vom Markt (Land) ab
                cur = shopify_currency(http, base) or cur
                currencies[base] = cur
            if mode == "drop":
                items, n = shopify_recent(http, name, base, cur)
            elif mode == "full":
                stamps = []
                items, n = shopify_full(http, name, base, currency=cur, stamps=stamps)
                status["rhythmus"] = rhythm(stamps)
                if n == 0 and not http.limited:   # manche Shops sperren products.json: erst Collection, dann Suche
                    items, n = shopify_full(http, name, base, "/collections/all/products.json", cur)
                if n == 0 and not http.limited:
                    items, n = shopify_search(http, name, base, matcher.queries(), matcher, cur)
                    status["info"] = "nur Suche (products.json gesperrt)"
                elif n >= SHOPIFY_PAGE_CAP * 250 and not http.limited:
                    # Shopify liefert max. 100 Seiten (neueste zuerst), ältere Artikel nur per Suche
                    known_urls = {it["url"] for it in items}
                    extra, _ = shopify_search(http, name, base, matcher.queries(), matcher, cur)
                    items += [it for it in extra if it["url"] not in known_urls]
                    status["info"] = f"Katalog bei {n} gekappt, ältere Artikel per Suche"
            else:
                items, n = shopify_search(http, name, base, matcher.queries(True), matcher, cur, pages=1)
        elif plat.startswith("woo:") and mode == "drop":
            items, n = woo_recent(http, name, plat[4:])
        elif plat.startswith("woo:"):
            ep = plat[4:]
            items, n = woo_run(http, name, ep, None if mode == "full" else matcher.queries(True))
        else:
            # Sperre (403/401) ehrlich benennen statt "nicht erkannt", z. B. Shops, die Rechenzentrums-IPs blocken
            status["fehler"] = blocked_text(http) or "Shopsystem nicht automatisch erkannt"
            return [], status
        status["produkte"] = n
        return items, status
    except Exception as e:  # ein kaputter Shop soll nie den ganzen Lauf stoppen
        status["fehler"] = f"{type(e).__name__}: {str(e)[:120]}"
        return [], status
    finally:
        if not status["fehler"] and plat not in ("aus", "fyj"):
            if http.limited:
                status["fehler"] = f"unvollständig, {http.limited}x gedrosselt (HTTP 429)"
            elif status["produkte"] == 0 and blocked_text(http):
                status["fehler"] = blocked_text(http)
            elif status["produkte"] == 0 and mode == "full":
                status["fehler"] = "keine Produkte erhalten" + (f" ({codes_text(http)})" if http.codes else "")
        if http.codes and not status["fehler"]:
            status["info"] = "; ".join(x for x in (status.get("info"), codes_text(http)) if x)
        status["sekunden"] = round(time.time() - t0, 1)
        status["anfragen"] = http.count


def codes_text(http):
    """'HTTP 404 ×3, 403 ×1': Antworten außer 200, häufigste zuerst"""
    return "HTTP " + ", ".join(f"{c} ×{n}" for c, n in http.codes.most_common())


def blocked_text(http):
    """Text, wenn der Shop uns gesperrt hat (403/401), sonst leer"""
    code = 403 if http.codes.get(403) else 401 if http.codes.get(401) else None
    return f"gesperrt (HTTP {code}), blockt vermutlich Server-Adressen" if code else ""


def detect_platform(base):
    """Shopsystem eines Kandidaten erkennen (je eine Anfrage): shopify, woo, wix oder unbekannt"""
    http = Http(SHOPIFY_GATE)
    data = http.get(f"{base}/products.json", {"limit": 1})
    if isinstance(data, dict) and "products" in data:
        return "shopify"
    http.gate = None
    if woo_endpoint(http, base):
        return "woo"
    tokens = http.get(f"{base}/_api/v1/access-tokens")
    if ((tokens or {}).get("apps") or {}).get(WIX_STORES_APP):
        return "wix"
    return "unbekannt"
