"""Preise lesen und in Euro umrechnen (EZB-Kurse)"""

import re

import requests

from .basis import FX_API, TIMEOUT


CUR_CODE_RX = re.compile(r"\b([A-Z]{3})\b")   # ISO-Code, ob es einen Kurs gibt, prüft to_eur()
CUR_SYMBOLS = [("£", "GBP"), ("€", "EUR"), ("zł", "PLN"), ("$", "USD")]
NUM_RX = re.compile(r"\d[\d.,\s]*\d|\d")


def parse_price(s):
    """'£124.99', '79.35 GBP', '1.299,00 kr DKK' -> (Betrag, Währung) bzw. (None, '')"""
    s = str(s or "")
    m = CUR_CODE_RX.search(s.upper())
    cur = m.group(1) if m else next((c for sym, c in CUR_SYMBOLS if sym in s), "")
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


def to_eur(price, rates):
    amount, cur = parse_price(price)
    rate = rates.get(cur)
    return round(amount / rate, 2) if amount is not None and rate else None
