"""eBay über die offizielle Browse API, eigener Bereich in der App, getrennt von den Shops (seit 08.10.2026).

Suche: Sofortkauf (auch Auktionen mit Sofort-Kaufen), Versand nach Deutschland, Standort EU, UK oder Ukraine, nur in der
Trikot-Kategorie. Treffer wie bei den Shops über den Matcher, Größe aus dem Titel oder dem Merkmal "Größe" des Angebots
(Einzelabruf, gemerkt). Radar alle EBAY_RADAR_MIN Minuten (neueste Angebote), nachts im Gesamt-Run alles.

Lizenz (eBay API License Agreement), daraus folgt der Aufbau:
- eBay-Inhalte nicht veröffentlichen (§9.7, §17): Zustand verschlüsselt (Schlüssel aus dem Secret EBAY_CLIENT_SECRET),
  App-Daten je Gerät verschlüsselt (Geräteschlüssel aus der App, Issue mit Label "ebay"). Im öffentlichen Repo und in
  den Logs steht nichts Lesbares, nur Anzahlen
- angezeigte Angebote höchstens 6 Std. alt (§8.1c): EBAY_REFRESH_H, die App blendet Älteres aus
- beendete Angebote löschen (§8.1b): kein "weg"-Vermerk wie bei Shops, der Eintrag fliegt raus
- keine Nutzerdaten (§8.2.1): Verkäufer nur beim Abruf geprüft (Bewertungen), nie gespeichert"""

import base64
import datetime as dt
import hashlib
import json
import os
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import speicher
from .basis import ANY_SIZE_RX, SIZE_RX, TIMEOUT, is_high, norm, now, short_size
from .preise import to_eur

API = "https://api.ebay.com"
SCOPE = "https://api.ebay.com/oauth/api_scope"
BASE_FILTER = "buyingOptions:{FIXED_PRICE},deliveryCountry:DE"
# Standorte: EU über eBay.de, UK über eBay.co.uk, Ukraine über eBay.de. Kategorie = Elternknoten "Fußball-Trikots"
# (DE 179288) bzw. "Football Shirts" (UK 53597), per Taxonomie-Schnittstelle ermittelt am 08.10.2026.
# "CONTINENTAL_EUROPE" bewusst nicht: enthält auch GB und UA, die getrennt laufen
WHERE = {
    "EU": {"market": "EBAY_DE", "cat": "179288", "filter": "itemLocationRegion:EUROPEAN_UNION"},
    "UK": {"market": "EBAY_GB", "cat": "53597", "filter": "itemLocationCountry:GB"},
    "UA": {"market": "EBAY_DE", "cat": "179288", "filter": "itemLocationCountry:UA"},
}
EBAY_RADAR_MIN = 30        # Radar: neueste Angebote je Suche und Standort
EBAY_REFRESH_H = 4         # Treffer spätestens so oft einzeln bestätigen (Lizenz: angezeigt höchstens 6 Std. alt)
EBAY_SHOW_H = 6            # die App zeigt nur Treffer, die vor höchstens so vielen Stunden bestätigt wurden
EBAY_DAY_LIMIT = 4500      # eBay erlaubt 5.000 Abrufe am Tag
FULL_PAGES = 20            # Gesamt-Run: höchstens 20 x 200 Angebote je Suche und Standort
SIZE_LOOKUPS = {"full": 300, "drop": 60}   # Einzelabrufe für die Größe pro Run
REFRESH_LOOKUPS = 80       # Einzelabrufe zum Bestätigen pro Run
SIZE_ASPECTS = ("röße", "size", "taglia", "talla", "taille", "rozmiar", "maat", "storlek", "størrelse")
STATE_SALT, STATE_INFO = b"ttt-ebay-state-1", b"zustand"
DEVICE_SALT, DEVICE_INFO = b"ttt-ebay-1", b"ttt-ebay-dashboard"   # muss zu docs/index.html passen
ZOLL_PAUSCHALE = 3.0       # EU-Zoll je Warenart bis 150 € seit 01.07.2026 (Verordnung (EU) 2026/382)
ZOLL_SATZ = 0.12           # Textilien über 150 €
EUST = 0.19                # Einfuhrumsatzsteuer
ZOLL_GEBUEHR = 12.0        # geschätzte Abfertigungsgebühr des Paketdiensts über 150 €


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def secrets():
    cid, sec = os.environ.get("EBAY_CLIENT_ID", "").strip(), os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    return (cid, sec) if cid and sec else (None, None)


def _hkdf(ikm, salt, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


# ---------------------------------------------------------------------------------------------------------------
# Verschlüsselung
# ---------------------------------------------------------------------------------------------------------------
def seal_state(obj, secret):
    iv = os.urandom(12)
    data = AESGCM(_hkdf(secret.encode(), STATE_SALT, STATE_INFO)).encrypt(iv, json.dumps(obj).encode(), None)
    return {"v": 1, "iv": b64u(iv), "data": b64u(data)}


def open_state(blob, secret):
    """Zustand entschlüsseln; None, wenn er fehlt oder mit einem anderen Schlüssel verschlüsselt wurde"""
    try:
        plain = AESGCM(_hkdf(secret.encode(), STATE_SALT, STATE_INFO)).decrypt(unb64u(blob["iv"]), unb64u(blob["data"]), None)
        return json.loads(plain)
    except Exception:
        return None


def device_id(pub_b64):
    return hashlib.sha256(pub_b64.encode()).hexdigest()[:16]


def seal_for_device(pub_b64, obj):
    """Für ein Gerät verschlüsseln (ECDH P-256 + HKDF + AES-GCM, Gegenstück openEbay() in docs/index.html)"""
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(pub_b64))
    eph = ec.generate_private_key(ec.SECP256R1())
    key = _hkdf(eph.exchange(ec.ECDH(), peer), DEVICE_SALT, DEVICE_INFO)
    iv = os.urandom(12)
    raw = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"eph": b64u(raw), "iv": b64u(iv), "data": b64u(AESGCM(key).encrypt(iv, json.dumps(obj).encode(), None))}


def open_for_device(priv, sealed):
    """Nur für Tests: macht dasselbe wie die App"""
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(sealed["eph"]))
    key = _hkdf(priv.exchange(ec.ECDH(), peer), DEVICE_SALT, DEVICE_INFO)
    return json.loads(AESGCM(key).decrypt(unb64u(sealed["iv"]), unb64u(sealed["data"]), None))


# ---------------------------------------------------------------------------------------------------------------
# Schnittstelle
# ---------------------------------------------------------------------------------------------------------------
class Ebay:
    def __init__(self, client_id, secret, session=None):
        self.cid, self.secret = client_id, secret
        self.s = session or requests.Session()
        self.token, self.token_until = None, 0
        self.calls = 0
        self.errors = []

    def _auth(self):
        if self.token and time.time() < self.token_until - 120:
            return self.token
        r = self.s.post(f"{API}/identity/v1/oauth2/token", auth=(self.cid, self.secret), timeout=TIMEOUT,
                        data={"grant_type": "client_credentials", "scope": SCOPE})
        self.calls += 1
        r.raise_for_status()
        d = r.json()
        self.token, self.token_until = d["access_token"], time.time() + int(d.get("expires_in", 7200))
        return self.token

    def get(self, path, params=None, market="EBAY_DE"):
        """GET mit Wiederholung bei 429/5xx; liefert (Status, JSON oder {})"""
        for attempt in range(3):
            self.calls += 1
            try:
                r = self.s.get(f"{API}{path}", params=params, timeout=TIMEOUT, headers={
                    "Authorization": f"Bearer {self._auth()}", "X-EBAY-C-MARKETPLACE-ID": market,
                    "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=DE,zip=80331", "Accept-Language": "de-DE"})
            except requests.RequestException as e:
                if attempt == 2:
                    self.errors.append(type(e).__name__)
                    return 0, {}
                time.sleep(3 + 7 * attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {}
        return 0, {}

    def search(self, where, q, newest=False, offset=0):
        w = WHERE[where]
        params = {"q": q, "category_ids": w["cat"], "filter": f"{BASE_FILTER},{w['filter']}", "limit": 200, "offset": offset}
        if newest:
            params["sort"] = "newlyListed"
        status, d = self.get("/buy/browse/v1/item_summary/search", params, w["market"])
        if status != 200:
            self.errors.append(f"Suche {where} HTTP {status}")
        return status, d

    def item(self, item_id, where):
        return self.get(f"/buy/browse/v1/item/{item_id}", None, WHERE[where]["market"])


# ---------------------------------------------------------------------------------------------------------------
# Angebote auswerten
# ---------------------------------------------------------------------------------------------------------------
def seller_ok(s, cfg):
    sel = s.get("seller") or {}
    try:
        score = int(sel.get("feedbackScore") or 0)
        pct = float(sel.get("feedbackPercentage") or 0)
    except (TypeError, ValueError):
        return False
    return score >= int(cfg.get("min_bewertungen", 10)) and pct >= float(cfg.get("min_positiv", 97))


def summary_item(s, where):
    """Trefferliste -> schlanker Eintrag; None ohne Sofortkauf"""
    opts = s.get("buyingOptions") or []
    if "FIXED_PRICE" not in opts:
        return None
    pr = s.get("price") or {}
    ship = None
    for o in s.get("shippingOptions") or []:
        c = o.get("shippingCost") or {}
        if c.get("value") is not None:
            ship = f"{c['value']} {c.get('currency', '')}".strip()
            break
    legacy = s.get("legacyItemId") or ""
    url = f"https://www.ebay.{'co.uk' if where == 'UK' else 'de'}/itm/{legacy}" if legacy else s.get("itemWebUrl", "")
    return {"id": s.get("itemId", ""), "title": s.get("title", ""), "url": url,
            "image": (s.get("image") or {}).get("imageUrl", ""),
            "price": f"{pr.get('value', '')} {pr.get('currency', '')}".strip(), "versand": ship,
            "land": (s.get("itemLocation") or {}).get("country", ""), "zustand": s.get("condition", ""),
            "auktion": "AUCTION" in opts, "wo": where}


def item_size(detail):
    """Größe aus den Merkmalen des Einzelabrufs ("Größe: XL")"""
    for a in detail.get("localizedAspects") or []:
        if any(k in (a.get("name") or "").lower() for k in SIZE_ASPECTS):
            return str(a.get("value") or "")
    return ""


def still_available(detail):
    if not detail or "FIXED_PRICE" not in (detail.get("buyingOptions") or []):
        return False
    av = [a.get("estimatedAvailabilityStatus") for a in detail.get("estimatedAvailabilities") or []]
    return not av or any(x and x != "OUT_OF_STOCK" for x in av)


def landed(eur, land):
    """Geschätzter Endpreis inkl. Einfuhrabgaben für Angebote außerhalb der EU (UK, Ukraine)"""
    if eur is None or land not in ("GB", "UA"):
        return None
    if eur <= 150:
        return round(eur * (1 + EUST) + ZOLL_PAUSCHALE, 2)
    return round(eur * (1 + ZOLL_SATZ) * (1 + EUST) + ZOLL_GEBUEHR, 2)


def relist_key(title, price):
    return hashlib.sha256(f"{norm(title)}|{price}".encode()).hexdigest()[:16]


def id_key(item_id):
    return hashlib.sha256(str(item_id).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------------------------------------------
def state_path():
    return speicher.STATE_DIR / "ebay.json"


def app_path():
    return speicher.DATA_DIR / "ebay.json"


def due(status_store, mode, t_now):
    """Was steht an? {"suche": "voll"|"radar"|None, "bestaetigen": bool}"""
    if not secrets()[0]:
        return {"suche": None, "bestaetigen": False}
    st = status_store.get("ebay") or {}
    if mode == "full":
        return {"suche": "voll", "bestaetigen": True}
    if mode != "drop":
        return {"suche": None, "bestaetigen": False}
    last = st.get("radar")
    radar = not last or (t_now - dt.datetime.fromisoformat(last)).total_seconds() >= (EBAY_RADAR_MIN - 5) * 60
    stale = any((t_now - dt.datetime.fromisoformat(v)).total_seconds() > EBAY_REFRESH_H * 3600
                for v in (st.get("bestaetigt") or {}).values())
    return {"suche": "radar" if radar else None, "bestaetigen": stale}


def collect_devices(status_store, ts, issues_fn):
    """Geräteschlüssel aus der App (Issue mit Label "ebay", Zeile "ebay-key: <öffentlicher Schlüssel>")"""
    import re
    issues, api = issues_fn("ebay")
    devs = status_store.setdefault("ebay", {}).setdefault("geraete", {})
    new = 0
    for iss in issues or []:
        m = re.search(r"ebay-key:\s*([A-Za-z0-9_-]{80,100})", iss.get("body") or "")
        ok = False
        if m:
            try:
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(m.group(1)))
                ok = True
            except ValueError:
                pass
        if ok and device_id(m.group(1)) not in devs:
            devs[device_id(m.group(1))] = {"pub": m.group(1), "seit": ts}
            new += 1
        if api:
            try:
                requests.post(f"{api[0]}/{iss['number']}/comments", headers=api[1], timeout=TIMEOUT,
                              json={"body": "eBay ist für dieses Gerät freigeschaltet, die Angebote kommen mit dem nächsten Run."
                                    if ok else "Kein gültiger Schlüssel gefunden, bitte in der App erneut freischalten."})
                requests.patch(f"{api[0]}/{iss['number']}", headers=api[1], timeout=TIMEOUT, json={"state": "closed"})
            except requests.RequestException:
                pass
    return new


def run(mode, status_store, matcher, watch, rates, ts, notify, client=None, dry=False):
    """eBay-Teil eines Runs. notify(title, message, prio, click) verschickt Pushes. Gibt (Zusammenfassung, Probleme) zurück"""
    cid, secret = secrets()
    if not cid:
        return "", []
    t_now = dt.datetime.fromisoformat(ts)
    st = status_store.setdefault("ebay", {})
    todo = due(status_store, mode, t_now)
    if not todo["suche"] and not todo["bestaetigen"]:
        return "", []
    cfg = watch.get("ebay") or {}
    client = client or Ebay(cid, secret)
    day = ts[:10]
    used = {d: n for d, n in (st.get("abrufe") or {}).items() if d >= (t_now - dt.timedelta(days=7)).date().isoformat()}
    if used.get(day, 0) >= EBAY_DAY_LIMIT:
        return "eBay: Tageslimit erreicht", [("eBay", f"Tageslimit von {EBAY_DAY_LIMIT} Abrufen erreicht, Pause bis morgen")]

    blob = speicher.load_json(state_path(), None)
    state = open_state(blob, secret) if blob else None
    first = state is None   # erster Lauf oder Schlüssel geändert: Bestand still übernehmen
    state = state or {"treffer": {}, "groessen": {}, "gepusht": {}, "beendet": {}}
    hits, sizes = state["treffer"], state["groessen"]
    pg = watch.get("preisgrenze") or {}
    max_eur, no_limit = float(pg.get("max_eur") or 0), set(pg.get("ausnahmen") or [])
    problems, new_entries = [], []

    # 1) Suchen
    found, complete = {}, todo["suche"] == "voll"
    if todo["suche"]:
        searches = cfg.get("suchen") or []
        if todo["suche"] == "radar":
            searches = sorted(searches, key=lambda s: str(s.get("hoch", "")).lower() not in ("ja", "true"))
        for s in searches:
            for where in WHERE:
                pages = FULL_PAGES if todo["suche"] == "voll" else 1
                for page in range(pages):
                    status, d = client.search(where, s["q"], newest=todo["suche"] == "radar", offset=page * 200)
                    if status != 200:
                        complete = False
                        break
                    for summ in d.get("itemSummaries") or []:
                        if seller_ok(summ, cfg):
                            it = summary_item(summ, where)
                            if it and it["id"]:
                                found[it["id"]] = it
                    if (page + 1) * 200 >= int(d.get("total") or 0):
                        break
                else:
                    if todo["suche"] == "voll":
                        complete = False   # mehr als FULL_PAGES Seiten: nicht vollständig gesehen
        st["radar"] = ts

    # 2) Abgleich: Labels aus dem Titel, Größe aus dem Titel oder dem Merkmal (Einzelabruf, gemerkt)
    lookups = SIZE_LOOKUPS.get(mode, 60)
    for iid, it in found.items():
        why = {}
        labs = matcher.labels(it["title"], why=why)
        if not labs:
            continue
        size_text = it["title"]
        if not ANY_SIZE_RX.search(norm(it["title"])):
            if iid not in sizes and lookups > 0:
                lookups -= 1
                status, detail = client.item(iid, it["wo"])
                sizes[iid] = item_size(detail) if status == 200 else ""
            size_text = sizes.get(iid, "")
        if not matcher.size_ok(size_text, norm(it["title"])):
            continue
        size = SIZE_RX.search(norm(size_text))
        eur = to_eur(it["price"], rates)
        ship = to_eur(it["versand"], rates) if it["versand"] else None
        end = landed(eur, it["land"])
        total = (end if end is not None else eur or 0) + (ship or 0)
        labels = sorted({l for l, _ in labs})
        entry = hits.get(iid)
        if entry is None:
            entry = {"first": ts}
            hits[iid] = entry
            key = id_key(iid)
            relist = relist_key(it["title"], it["price"]) in state["beendet"]
            if first or key in state["gepusht"] or relist:
                entry["still"] = True
            else:
                new_entries.append(entry)
            state["gepusht"][key] = ts
        entry.update(it, labels=labels, prios=sorted({p for _, p in labs}), warum=why, last=ts,
                     size=short_size(size.group(0)) if size else "", eur=eur, versand_eur=ship, endpreis=end,
                     teuer=bool(max_eur and total > max_eur and not no_limit & set(labels)))

    # 3) Bestätigen bzw. löschen: Gesamt-Run alles, was die vollständige Suche nicht mehr lieferte; sonst, was älter als
    # EBAY_REFRESH_H ist. Beendet, verkauft oder ohne Sofortkauf -> Eintrag löschen (Lizenz §8.1b)
    budget = REFRESH_LOOKUPS if mode != "full" else 400
    for iid in list(hits):
        e = hits[iid]
        if e["last"] == ts:
            continue
        old = (t_now - dt.datetime.fromisoformat(e["last"])).total_seconds() > EBAY_REFRESH_H * 3600
        if not ((complete and todo["suche"] == "voll") or old) or budget <= 0:
            continue
        budget -= 1
        status, detail = client.item(iid, e["wo"])
        if status == 200 and still_available(detail):
            pr = detail.get("price") or {}
            if pr.get("value") is not None:
                e["price"] = f"{pr['value']} {pr.get('currency', '')}".strip()
                e["eur"] = to_eur(e["price"], rates)
                e["endpreis"] = landed(e["eur"], e.get("land"))
            e["last"] = ts
        elif status in (200, 404, 410):   # 200 = nicht mehr verfügbar, 404/410 = beendet
            state["beendet"][relist_key(e["title"], e["price"])] = ts
            del hits[iid]
            sizes.pop(iid, None)
    # Merklisten aufräumen: Größen nur für aktuelle Angebote, Hashes 60 bzw. 30 Tage
    keep = set(hits) | set(found)
    state["groessen"] = {k: v for k, v in sizes.items() if k in keep}
    cut60, cut30 = (t_now - dt.timedelta(days=60)).isoformat(), (t_now - dt.timedelta(days=30)).isoformat()
    state["gepusht"] = {k: v for k, v in state["gepusht"].items() if v >= cut60}
    state["beendet"] = {k: v for k, v in state["beendet"].items() if v >= cut30}

    # 4) Pushes: Thiago und Sondertrikots einzeln (max. 5), Rest gebündelt; zu teure nicht
    loud = [e for e in new_entries if not e["teuer"]]
    high = [e for e in loud if is_high(e)]
    for e in high[:5]:
        notify(f"🛒 eBay: {', '.join(e['labels'])}", f"{e['title']}\n{_price_line(e)} · {e['size']}", 5, e["url"])
    rest = [e for e in loud if e not in high[:5]]
    if rest:
        board = (os.environ.get("DASHBOARD_URL") or "").rstrip("/")
        notify(f"🛒 eBay: {len(rest)} neue Treffer",
               "\n".join(f"• {', '.join(e['labels'])}: {e['title'][:70]} ({_price_line(e)})" for e in rest[:8]), 3,
               f"{board}/#ebay" if board else None)

    # 5) Speichern: Zustand verschlüsselt, App-Daten je Gerät verschlüsselt
    state["init"] = True
    st["bestaetigt"] = {id_key(k): v["last"] for k, v in hits.items()}   # nur Zeitpunkte, für die Fälligkeit
    used[day] = used.get(day, 0) + client.calls
    st["abrufe"] = used
    st["treffer"] = len(hits)
    if not dry:
        speicher.save_json(state_path(), seal_state(state, secret))
        write_app(status_store, hits, ts)
    if client.errors:
        problems.append(("eBay", "; ".join(sorted(set(client.errors)))[:300]))
    summary = (f"eBay: {todo['suche'] or 'nur bestätigen'}, {len(found)} Angebote geprüft, {len(hits)} Treffer, "
               f"{len(new_entries)} neu, {client.calls} Abrufe (heute {used[day]})")
    return summary, problems


def _price_line(e):
    p = f"{e['eur']:.0f} €" if e.get("eur") is not None else e.get("price", "")
    if e.get("endpreis") is not None:
        p += f" (mit Zoll ≈ {e['endpreis']:.0f} €)"
    return p


def app_entry(e):
    return {"id": id_key(e["id"]), "titel": e["title"], "url": e["url"], "bild": e.get("image", ""), "preis": e["price"],
            "eur": e.get("eur"), "versand": e.get("versand_eur"), "endpreis": e.get("endpreis"), "land": e.get("land", ""),
            "zustand": e.get("zustand", ""), "auktion": e.get("auktion", False), "groesse": e.get("size", ""),
            "labels": e.get("labels", []), "hoch": "hoch" in (e.get("prios") or []), "teuer": e.get("teuer", False),
            "warum": "; ".join(f"{k}: {v}" for k, v in (e.get("warum") or {}).items()),
            "erst": e["first"], "bestaetigt": e["last"], "still": bool(e.get("still"))}


def write_app(status_store, hits, ts):
    """App-Daten (docs/ebay.json über den Dashboard-Workflow): für jedes freigeschaltete Gerät verschlüsselt"""
    devs = (status_store.get("ebay") or {}).get("geraete") or {}
    payload = {"stand": ts, "zeigen_h": EBAY_SHOW_H, "treffer": [app_entry(e) for e in hits.values()]}
    speicher.save_json(app_path(), {"stand": ts, "fuer": {kid: seal_for_device(d["pub"], payload) for kid, d in devs.items()}})
