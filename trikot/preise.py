"""Preise lesen und in Euro umrechnen (EZB-Kurse)"""

import re

import requests

from .basis import FX_API, TIMEOUT


CUR_CODE_RX = re.compile(r"\b([A-Z]{3})\b")
# nur echte Währungscodes: sonst wurde aus "Von 45,00 €" die Währung "VON", der Preis ließ sich nicht umrechnen und die
# Preisgrenze griff nicht (10.11.2026)
CUR_CODES = {"EUR", "GBP", "USD", "CHF", "DKK", "SEK", "NOK", "PLN", "CZK", "HUF", "RON", "BGN", "ISK", "UAH", "TRY",
             "AUD", "CAD", "NZD", "MXN", "BRL", "MYR", "IDR", "JPY", "CNY", "HKD", "SGD", "INR", "KRW", "THB", "ZAR",
             "AED", "ARS", "CLP", "COP", "RSD", "ILS", "PHP"}
CUR_SYMBOLS = [("£", "GBP"), ("€", "EUR"), ("zł", "PLN"), ("$", "USD")]
NUM_RX = re.compile(r"\d[\d.,\s]*\d|\d")


def parse_price(s):
    """'£124.99', '79.35 GBP', '1.299,00 kr DKK' -> (Betrag, Währung) bzw. (None, '')"""
    s = str(s or "")
    cur = next((c for c in CUR_CODE_RX.findall(s.upper()) if c in CUR_CODES), "") \
        or next((c for sym, c in CUR_SYMBOLS if sym in s), "")
    m = NUM_RX.search(s)
    if not m:
        return None, cur
    num = re.sub(r"\s", "", m.group(0))
    if "," in num and "." in num:
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        num = num.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".") if re.search(r",\d{1,2}$", num) else num.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
        num = num.replace(".", "")
    try:
        return float(num), cur
    except ValueError:
        return None, cur


def fetch_rates(status_store):
    """EZB-Kurse (1 EUR = x Fremdwährung) über frankfurter.dev, bei Fehler die zuletzt gemerkten"""
    try:
        r = requests.get(FX_API, params={"base": "EUR"}, timeout=TIMEOUT)
        data = r.json()
        if data.get("rates"):
            status_store["kurse"] = {"datum": data.get("date", ""), "rates": {**data["rates"], "EUR": 1.0}}
    except (requests.RequestException, ValueError):
        pass
    return status_store.get("kurse") or {"datum": "", "rates": {"EUR": 1.0}}


def effective_pg(pg, today=None):
    """Preisgrenze mit zeitweiser Erhöhung (preisgrenze.zeitweise {max_eur, bis}): bis einschließlich "bis" (deutsches
    Datum) gilt der höhere Wert als max_eur, danach wieder der normale. Gibt eine Kopie ohne "zeitweise" zurück"""
    import datetime as dt
    from zoneinfo import ZoneInfo
    pg = dict(pg or {})
    tmp = pg.pop("zeitweise", None) or {}
    today = today or dt.datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    if tmp.get("max_eur") and str(tmp.get("bis") or "0") >= today:
        pg["max_eur"] = max(float(pg.get("max_eur") or 0), float(tmp["max_eur"]))
        pg["zeitweise_bis"] = tmp.get("bis")
    return pg


def price_limit(labels, pg):
    """Preisgrenze für einen Treffer: eigene Grenze eines Labels aus preisgrenze.ausnahmen (0 = ohne Grenze),
    sonst max_eur. Ältere Form: Liste von Labels ohne Grenze"""
    base = float(pg.get("max_eur") or 0)
    exc = pg.get("ausnahmen") or {}
    if isinstance(exc, list):
        exc = {label: 0 for label in exc}
    own = [float(v or 0) for label, v in exc.items() if label in labels]
    if not own:
        return base
    return 0 if 0 in own else max(own + [base])


PCT_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")


def shop_discounts(shops, today=None):
    """Rabatt je Shop zum Einrechnen in den Euro-Preis (Nutzer 27.11.2026: "rechne die alle direkt rein"):
    laufende Aktion mit festem Prozentwert (aktion.prozent, zwischen "ab" und "bis" einschließlich, deutsches Datum) oder
    Neukunden-Rabatt (erster Prozentwert im Text von rabatt:, abschaltbar mit rabatt_einrechnen: nein). Rabatte werden
    nicht addiert, es zählt der höhere. Schlüssel: Shopname und Domain (FYJ-Treffer haben nur die Domain)"""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from .speicher import _host
    today = today or dt.datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    out = {}
    for s in shops:
        cands = []
        a = s.get("aktion")
        if isinstance(a, dict) and a.get("prozent") and str(a.get("ab") or "0") <= today <= str(a.get("bis") or "9999"):
            cands.append({"prozent": float(a["prozent"]), "art": "aktion", "text": a.get("text", "")})
        m = PCT_RX.search(str(s.get("rabatt") or ""))
        if m and str(s.get("rabatt_einrechnen", "ja")).lower() not in ("nein", "false", "no"):
            cands.append({"prozent": float(m.group(1).replace(",", ".")), "art": "neukunden", "text": s["rabatt"]})
        cands = [c for c in cands if 0 < c["prozent"] < 100]
        if cands:
            best = max(cands, key=lambda c: c["prozent"])
            out[s["name"]] = best
            out[_host(s["url"])] = best
    return out


def discount_for(entry, discounts):
    from .speicher import _host
    return discounts.get(_host(entry.get("url") or "")) or discounts.get(entry.get("shop") or "")


def net_eur(eur, disc):
    """Euro-Preis nach Rabatt (disc aus discount_for, None = ohne)"""
    return round(eur * (1 - disc["prozent"] / 100), 2) if eur is not None and disc else eur


def to_eur(price, rates):
    amount, cur = parse_price(price)
    rate = rates.get(cur)
    return round(amount / rate, 2) if amount is not None and rate else None
