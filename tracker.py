#!/usr/bin/env python3
"""
Trikot-Tracker
Sucht Vintage-Trikots aus der watchlist.yaml in Größe XL/XXL bei den Shops aus
shops.yaml sowie über FindYourJersey und meldet neue Treffer per ntfy-Push.

Modi:
  full      kompletter Durchlauf über alle Quellen (1x täglich)
  priority  nur Einträge mit prioritaet "hoch" über die Shop-Suchen (alle 3 Std.)
  test      schickt nur eine Test-Benachrichtigung

Lokal testen:  python tracker.py --mode full --dry-run
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
STATUS_FILE = STATE_DIR / "status.json"
REPORT_FILE = ROOT / "TREFFER.md"
DASHBOARD_FILE = ROOT / "docs" / "treffer.json"

TZ = ZoneInfo("Europe/Berlin")
BUY_COUNTRY = "DE"       # Preise/Währung so, wie ein Käufer in Deutschland sie sieht
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TIMEOUT = 25
DELAY = 2.0              # Pause zwischen zwei Anfragen an denselben Shop
MAX_WORKERS = 8          # so viele Shops parallel
SHOPIFY_PAGE_CAP = 100      # mehr Seiten liefert Shopify bei products.json nicht
SHOPIFY_INTERVAL = 2.0   # Mindestabstand zwischen zwei Shopify-Anfragen, über alle Shops zusammen
MAX_PUSH_HIGH = 5        # max. Einzel-Pushes (Thiago/Sondertrikots) pro Lauf, Rest gebündelt
REPORT_HOURS = 36        # wie lange ein Treffer ohne Neusichtung in TREFFER.md bleibt

FYJ_API = "https://www.findyourjersey.org/api/jerseys"
FYJ_SIZES = ["XL", "XXL"]
FX_API = "https://api.frankfurter.dev/v1/latest"
FYJ_MARKETPLACES = ("ebay.", "depop.", "vinted.", "etsy.")   # über FYJ nicht übernehmen
RECHECK_DAYS = 3             # FYJ-Treffer so oft auf der Shop-Seite nachprüfen (verkauft?)
CHECK_VERSION = 2            # erhöhen, wenn die Seitenprüfung mehr auswertet: dann wird alles neu geprüft
ENRICH_BUDGET = {"full": 150, "priority": 25, "drop": 25}   # max. Seitenprüfungen pro Lauf
NOTE_LEN = 160               # Länge der Zustandsnotiz
FALLBACK_SKIP_HOURS = {"full": 20, "priority": 4}   # GitHub-Zeitplan überspringt, wenn schon gelaufen
RUN_HISTORY = 120            # so viele Läufe für den Eingangsverlauf im Dashboard merken
RHYTHM_DAYS = 90             # Zeitraum für die Drop-Analyse
BATCH_GAP_MIN = 90           # Artikel mit höchstens so viel Abstand gehören zu einem Schub
BATCH_MIN = 8                # ab so vielen Artikeln ist ein Schub ein Drop
DROP_MIN_GAP_DAYS = 3        # Schübe fast täglich zählen als "laufend", nicht als Drops
DROP_MIN_SHARE = 0.5         # gemessener Drop zählt als Termin, wenn mind. so viele Schübe am selben Wochentag
DROP_WINDOW_MIN = 180        # so lange nach Drop-Beginn prüft der Drop-Run den Shop
DROP_LEAD_MIN = 15           # gemessene Drops: so viele Minuten vor der typischen Uhrzeit anfangen
DROP_DAY_SHARE = 0.25        # ein Wochentag wird Drop-Termin, wenn mind. so viele Schübe darauf fallen
DROP_DAY_MIN = 3             # und mindestens so viele Drops an diesem Wochentag
DROP_MAX_SPREAD_MIN = 120    # sehr große Streuung nicht unbegrenzt ins Fenster übernehmen
DROP_RECHECK_MIN = 25        # Mindestabstand zwischen zwei Drop-Prüfungen desselben Shops


# ---------------------------------------------------------------------------
# Text-Hilfen
# ---------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("ß", "ss").replace("ø", "o").replace("ł", "l").replace("æ", "ae")
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    s = re.sub(r"[^a-z0-9/#.\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def word_rx(phrase):
    # Danach darf eine Ziffer folgen ("#Thiago10"), aber kein Buchstabe ("rodri" ≠ "rodrigo")
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(phrase)) + r"(?![a-z])")


def any_rx(phrases):
    return [word_rx(p) for p in (phrases or []) if norm(p)]


def hit(rxs, text):
    return any(r.search(text) for r in rxs)


SIZE_RX = re.compile(r"(?<![a-z0-9])(xxl|2xl|xl|xx-large|x-large|xx large|x large|extra large)(?![a-z0-9])")
ANY_SIZE_RX = re.compile(r"(?<![a-z0-9])(xxs|xs|s|m|l|xl|xxl|2xl|3xl|xxxl|small|medium|large|"
                         r"x-large|xx-large|\d{2,3}\s?cm|yxl|yl|ym|ys|xlb|lb|mb|sb)(?![a-z0-9])")

# Sternchen-Wörter wie "*WINFIELD*" (classic-shirts) sind Beflockungen, außer diese Zusätze
STAR_RX = re.compile(r"\*([^*]{2,40})\*")
STAR_TAGS = re.compile(r"(?i)^(bnwt|bnib|bnwot|bnip|w/ ?tags|with tags|mint|new|rare|signed|autographed|player issue|"
                       r"match worn|match issue|sample|prototype|ls|l/s|long ?sleeve|basic|retro|vintage)$")

# Rückennummer im Titel: "#10", "# 10", "No. 10", "Nr 10", "Number 10"
FLOCK_NUM_RX = re.compile(r"#\s?\d{1,2}(?!\d)|(?<![a-z0-9])(no|nr|num|number)\.?\s?\d{1,2}(?![\d/])")

VARIANT_WORDS = {
    "home": ["home", "heim", "heimtrikot", "local", "thuis", "domicile", "casa", "1st"],
    "away": ["away", "auswarts", "auswartstrikot", "visitante", "uit", "exterieur", "trasferta", "2nd"],
    "third": ["third", "3rd", "ausweich", "ausweichtrikot", "tercera", "troisieme", "terza", "derde"],
}
VARIANT_RX = {k: any_rx(v) for k, v in VARIANT_WORDS.items()}


def season_rxs(season):
    m = re.match(r"^(\d{4})/(\d{2})$", season.strip())
    if not m:
        return []
    s = int(m.group(1))
    e = s // 100 * 100 + int(m.group(2))     # "2004/06" = 2004 bis 2006, "2010/11" = 2010 bis 2011
    if e <= s:
        e += 100
    s2, e2 = f"{s % 100:02d}", f"{e % 100:02d}"
    pats = [f"{s}/{e2}", f"{s}-{e2}", f"{s}/{e}", f"{s}-{e}", f"{s2}/{e2}", f"{s2}-{e2}",
            f"{s} {e2}", f"{s} {e}", f"{s}/ {e2}", f"{s} - {e2}", f"{s} / {e2}"]
    return [re.compile(r"(?<!\d)" + re.escape(p) + r"(?!\d)") for p in pats]


def year_rx(year):
    return re.compile(r"(?<!\d)" + re.escape(str(year)) + r"(?!\d)")


def canon_url(url):
    try:
        u = urlparse(url)
    except Exception:
        return url
    host = (u.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = u.path or "/"
    m = re.search(r"/products/([^/?#]+)", path)
    if m:
        path = "/products/" + m.group(1)
    return host + path.rstrip("/").lower()


def now():
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
class Matcher:
    def __init__(self, cfg):
        g = cfg.get("groessen") or {}
        self.kids = any_rx(g.get("ausschliessen"))
        self.exclude = any_rx(cfg.get("produkt_ausschluss"))
        self.players = []
        for p in cfg.get("spieler") or []:
            self.players.append({
                "name": p["name"],
                "prio": p.get("prioritaet", "normal"),
                "terms": p.get("suche") or [],
                "suche": any_rx(p.get("suche")),
                "aus": any_rx(p.get("ausschluss")),
                "vereine": any_rx(p.get("vereine")),
            })
        self.nachbau = any_rx(cfg.get("nachbau"))
        self.nachbau_ok = set(cfg.get("nachbau_erlaubt_fuer") or [])
        rf = cfg.get("repro_flock") or {}
        self.repro_muster = any_rx(rf.get("muster"))
        self.repro_labels = set(rf.get("labels") or [])
        self.brand_ex = any_rx(cfg.get("hersteller_ausschluss"))
        self.url_ex = {canon_url(u) for u in cfg.get("ausschluss_urls") or []}
        ff = cfg.get("fremdflock") or {}
        self.flock_ok = any_rx(ff.get("erlaubt"))
        self.flock_names = any_rx(ff.get("namen"))
        self.kits = []
        for k in cfg.get("sondertrikots") or []:
            var = k.get("varianten", "alle")
            if isinstance(var, str):
                var = [var]
            kombi = k.get("kombi") or {}
            self.kits.append({
                "name": k["name"],
                "prio": k.get("prioritaet", "normal"),
                "verein": any_rx(k.get("verein")),
                "verein_terms": k.get("verein") or [],
                "saisons": [r for s in (k.get("saisons") or []) for r in season_rxs(s)],
                "jahre": [year_rx(y) for y in (k.get("jahre") or [])],
                "varianten": [v.lower() for v in var],
                "stich": any_rx(k.get("stichwoerter")),
                "kombi_b": any_rx(kombi.get("begriffe")),
                "kombi_f": any_rx(kombi.get("farbe")),
                "queries": k.get("suchanfragen") or [],
                "fremdflock_egal": str(k.get("fremdflock", "")).lower() in ("egal", "pflicht"),
                "flock_pflicht": str(k.get("fremdflock", "")).lower() == "pflicht",
                "codes": any_rx(k.get("codes")),
                "aus": any_rx(k.get("ausschluss")),
            })

    def excluded(self, text):
        return hit(self.exclude, text)

    def type_excluded(self, typ):
        """Produktart des Shops ("Tracktop", "Reissue", "Nameset" ...)"""
        t = norm(typ)
        return hit(self.exclude, t) or hit(self.nachbau, t)

    def reissue(self, text):
        """Nachbau/Neuauflage (z. B. Nikes T90-Reissues von 2025), ohne Repro-Flock-Muster"""
        t = norm(text)
        return hit(self.nachbau, t) and not hit(self.repro_muster, t)

    def repro_flock(self, text):
        """Original-Trikot mit nachgedrucktem Flock?"""
        return hit(self.repro_muster, norm(text))

    def size_ok(self, size_text, full_text):
        st = norm(size_text)
        if not SIZE_RX.search(st):
            return False
        return not (hit(self.kids, st) or hit(self.kids, full_text))

    def foreign_flock(self, t, star=False):
        """Trikot mit Flock eines anderen Spielers (Thiago-Flock zählt nicht als fremd).
        star: Titel enthält ein Sternchen-Wort, das kein bekannter Zusatz ist (classic-shirts "*NAME*")"""
        if hit(self.flock_ok, t):
            return False
        if star:
            return True
        return bool(FLOCK_NUM_RX.search(t)) or hit(self.flock_names, t)

    def has_flock(self, t, star=False):
        """Irgendein Flock erkennbar: Rückennummer, Sternchen-Name, bekannter Spielername oder
        eine alleinstehende Rückennummer ("PORTUGAL 7 FIGO"), nicht Saison, Note oder Größe"""
        return bool(star or FLOCK_NUM_RX.search(t) or hit(self.flock_names, t) or hit(self.flock_ok, t)
                    or any(hit(p["suche"], t) for p in self.players)
                    or re.search(r"(?<![\d/.\-])\b([1-9]|[1-9]\d)\b(?![\d/.\-]|\s?(ans|years|jahre|/10))", t))

    def _variant_ok(self, kit, t):
        allowed = kit["varianten"]
        if "alle" in allowed:
            return True
        if any(hit(VARIANT_RX[v], t) for v in allowed if v in VARIANT_RX):
            return True
        others = [v for v in VARIANT_RX if v not in allowed]
        if any(hit(VARIANT_RX[v], t) for v in others):
            return False
        return "home" in allowed   # ohne Angabe ist es meist das Heimtrikot

    def labels(self, text, fyj_reissue=False, desc=""):
        """Gibt [(label, prio)] zurück, ohne Größenprüfung. Nachbauten nur als Repro-Flock für repro_labels.
        desc (Beschreibung) wird nur für Artikelcodes der Sondertrikots herangezogen"""
        t = norm(text)
        if not t or self.excluded(t):
            return []
        starred = [x.strip() for x in STAR_RX.findall(str(text)) if not STAR_TAGS.match(x.strip())]
        star = any(not hit(self.flock_ok, norm(x)) for x in starred)
        out = self._labels(t, norm(plain(desc)) if desc else "", star)
        if hit(self.nachbau, t) or fyj_reissue:
            allowed = set(self.nachbau_ok)
            if hit(self.repro_muster, t) or fyj_reissue:
                allowed |= self.repro_labels
            out = [(l, p) for l, p in out if l in allowed]
        return out

    def needs_detail(self, text):
        """Sondertrikot mit Artikelcodes: Verein und Saison passen, Variante fehlt im Titel. Dann lohnt
        es, die Beschreibung der Produktseite nachzuladen (z. B. classic-shirts nennt dort den Code)"""
        t = norm(text)
        for k in self.kits:
            if k["codes"] and hit(k["verein"], t) and (hit(k["saisons"], t) or hit(k["jahre"], t)) \
                    and not self._variant_ok(k, t):
                return True
        return False

    def _labels(self, t, d="", star=False):
        out = []
        for p in self.players:
            if not hit(p["suche"], t) or hit(p["aus"], t):
                continue
            if p["vereine"] and not hit(p["vereine"], t):
                continue
            out.append((p["name"], p["prio"]))
        for k in self.kits:
            if k["codes"] and hit(k["codes"], f"{t} {d}"):     # Artikelcode eindeutig, Variante egal
                if k["fremdflock_egal"] or not self.foreign_flock(t, star):
                    out.append((k["name"], k["prio"]))
                continue
            if not hit(k["verein"], t) or hit(k["aus"], t):
                continue
            if (k["saisons"] or k["jahre"]) and not (hit(k["saisons"], t) or hit(k["jahre"], t)):
                continue
            if not self._variant_ok(k, t):
                continue
            if not k["fremdflock_egal"] and self.foreign_flock(t, star):
                continue
            if k["flock_pflicht"] and not self.has_flock(t, star):
                continue
            if k["stich"] or k["kombi_b"]:
                ok = hit(k["stich"], t) or (hit(k["kombi_b"], t) and hit(k["kombi_f"], t))
                if not ok:
                    continue
            out.append((k["name"], k["prio"]))
        return out

    def queries(self, only_high=False):
        qs = []
        for p in self.players:
            if only_high and p["prio"] != "hoch":
                continue
            qs += p["terms"]
        for k in self.kits:
            if only_high and k["prio"] != "hoch":
                continue
            qs += k["queries"]
        seen, out = set(), []
        for q in qs:
            n = norm(q)
            if n and n not in seen:
                seen.add(n)
                out.append(q)
        return out

    def team_queries(self):
        out = []
        for k in self.kits:
            if k["verein_terms"]:
                q = k["verein_terms"][0]
                if q not in out:
                    out.append(q)
        return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class RateGate:
    """Gemeinsame Bremse über mehrere Shops. Shopify drosselt pro IP über alle Shops hinweg,
    8 Shops parallel mit je 1 Anfrage/Sek. ergeben nach ca. 1 Min. flächendeckend HTTP 429"""
    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            slot = max(time.time(), self.next)
            self.next = slot + self.interval
        time.sleep(max(0.0, slot - time.time()))

    def penalize(self, seconds):
        with self.lock:
            self.next = max(self.next, time.time() + seconds)


SHOPIFY_GATE = RateGate(SHOPIFY_INTERVAL)


class Http:
    def __init__(self, gate=None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
        # Shopify Markets: ohne das Cookie bekäme der GitHub-Server (USA) US-Preise in USD
        self.s.cookies.set("localization", BUY_COUNTRY)
        self.gate = gate
        self.last = 0.0
        self.count = 0
        self.limited = 0     # Anfragen, die trotz Wiederholung gedrosselt blieben (429)

    def post(self, url, json=None, headers=None):
        """POST mit derselben Pause und Wiederholung bei Drosselung wie get(); liefert JSON oder None"""
        for attempt in range(3):
            wait = DELAY - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.count += 1
            try:
                r = self.s.post(url, json=json, headers=headers, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(3)
                continue
            if r.status_code == 429:
                if attempt == 2:
                    self.limited += 1
                    return None
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            try:
                return r.json()
            except ValueError:
                return None
        return None

    def get(self, url, params=None, want="json"):
        attempts = 5 if self.gate else 3
        for attempt in range(attempts):
            wait = DELAY - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            if self.gate:
                self.gate.wait()
            self.last = time.time()
            self.count += 1
            try:
                r = self.s.get(url, params=params, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise
                time.sleep(3)
                continue
            if r.status_code == 429:
                if attempt == attempts - 1:
                    self.limited += 1
                    return None
                try:
                    pause = min(float(r.headers.get("Retry-After", 0)), 60)
                except ValueError:
                    pause = 0
                pause = max(pause, 15 * (attempt + 1))
                if self.gate:
                    self.gate.penalize(pause)   # alle Shops hinter der Bremse pausieren
                else:
                    time.sleep(pause)
                continue
            if r.status_code >= 500 and attempt < 2:
                time.sleep(5)
                continue
            if want == "json":
                if r.status_code != 200:
                    return None
                try:
                    return r.json()
                except ValueError:
                    return None
            return r.text if r.status_code == 200 else None
        return None


def item(source, shop, url, title, size_text, price="", image="", extra="", desc="", **more):
    return {"source": source, "shop": shop, "url": url, "title": title.strip(),
            "size_text": size_text or "", "price": price, "image": image or "",
            "match_text": f"{title} {extra}".strip(), "desc": desc or "", **more}


# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------
SIZE_ATTR_RX = re.compile(r"size|grosse|groesse|taille|talla|maat|rozmiar|storrelse|koko|tamanho|taglia")


def shopify_currency(http, base):
    """products.json enthält keine Währung, /cart.js schon"""
    data = http.get(f"{base}/cart.js")
    cur = (data or {}).get("currency") if isinstance(data, dict) else None
    return cur if isinstance(cur, str) and len(cur) == 3 else ""


def shopify_to_item(shop, base, p, cents=False, currency=""):
    title = p.get("title") or ""
    handle = p.get("handle") or ""
    url = f"{base}/products/{handle}"
    imgs = p.get("images") or []
    img = ""
    if imgs:
        img = imgs[0]["src"] if isinstance(imgs[0], dict) else imgs[0]
        if img.startswith("//"):
            img = "https:" + img
    variants = p.get("variants") or []
    avail = [v for v in variants if v.get("available")]
    if not avail:
        return None

    def opts(v):
        return [x for x in (v.get("option1"), v.get("option2"), v.get("option3")) if x]

    single_default = len(variants) == 1 and norm(variants[0].get("title")) in ("default title", "")
    has_size_variants = not single_default and any(
        ANY_SIZE_RX.search(norm(x)) for v in variants for x in opts(v))
    if has_size_variants:
        # Größe steckt in den Varianten: nur verfügbare XL/XXL-Varianten zählen
        size_vals = [x for v in avail for x in opts(v) if SIZE_RX.search(norm(x))]
        size_text = " ".join(size_vals) or "__keine__"
    else:
        # Einzelstück: Größe steht im Titel oder in einem Größen-Tag
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        size_tags = [t for t in tags if SIZE_RX.search(norm(t)) and len(norm(t)) <= 20]
        size_text = title + " " + " ".join(size_tags)
    price = avail[0].get("price")
    if price is not None and cents:
        price = f"{int(price) / 100:.2f}"
    price = f"{price} {currency}".strip() if price not in (None, "") else ""
    desc = p.get("body_html") or p.get("description") or ""
    # Produktart ("Tracktop", "Reissue", "Goal Keeper" ...) nur für Ausschlüsse, nicht fürs Matching
    return item("direkt", shop, url, title, size_text, price, img, desc=desc,
                typ=p.get("product_type") or p.get("type") or "")


def shopify_full(http, shop, base, path="/products.json", currency="", stamps=None):
    items, n = [], 0
    for page in range(1, SHOPIFY_PAGE_CAP + 1):
        data = http.get(f"{base}{path}", {"limit": 250, "page": page})
        prods = (data or {}).get("products") or []
        if not prods:
            break
        n += len(prods)
        for p in prods:
            if stamps is not None:
                stamps.append(p.get("published_at") or p.get("created_at") or "")
            it = shopify_to_item(shop, base, p, currency=currency)
            if it:
                items.append(it)
        if len(prods) < 250:
            break
    return items, n


def shopify_recent(http, shop, base, currency="", days=3, max_pages=3):
    """Drop-Run: products.json liefert die neuesten zuerst, daher reichen die ersten Seiten"""
    items, n = [], 0
    since = now() - dt.timedelta(days=days)
    for page in range(1, max_pages + 1):
        data = http.get(f"{base}/products.json", {"limit": 250, "page": page})
        prods = (data or {}).get("products") or []
        n += len(prods)
        old = False
        for p in prods:
            it = shopify_to_item(shop, base, p, currency=currency)
            if it:
                items.append(it)
            try:
                old = old or dt.datetime.fromisoformat(p.get("published_at") or p.get("created_at")) < since
            except (TypeError, ValueError):
                pass
        if old or len(prods) < 250:
            break
    return items, n


def shopify_search(http, shop, base, queries, matcher, currency="", pages=2):
    """Shopify-Suchseite (/search) statt suggest.json: suggest liefert max. 10 unscharfe Treffer
    (bei VFA für "thiago" nur T. Silva). Vorfilter über den Handle, Details per /products/<handle>.js.
    Shops mit nichtssagenden Handles (z. B. nur Ziffern) werden so nicht gefunden, die deckt der
    Gesamtlauf über products.json ab"""
    items, n, handles = [], 0, set()
    for q in queries:
        for page in range(1, pages + 1):
            txt = http.get(f"{base}/search", {"q": q, "type": "product", "options[prefix]": "last",
                                              "page": page}, want="text")
            if not txt:
                break
            found = list(dict.fromkeys(re.findall(r"/products/([a-z0-9][a-z0-9_-]*)", txt)))
            n += len(found)
            for h in found:
                if h in handles:
                    continue
                handles.add(h)
                if not matcher.labels(h.replace("-", " ").replace("_", " ")):
                    continue
                full = http.get(f"{base}/products/{h}.js")
                if full:
                    it = shopify_to_item(shop, base, full, cents=True, currency=currency)
                    if it:
                        items.append(it)
            if len(found) < 12:
                break
    return items, n


def woo_to_item(shop, p):
    if not p.get("is_in_stock", True):
        return None
    title = html.unescape(p.get("name") or "")
    size_terms, has_size_attr = [], False
    for a in p.get("attributes") or []:
        if SIZE_ATTR_RX.search(norm(a.get("name") or a.get("taxonomy") or "")):
            has_size_attr = True
            size_terms += [t.get("name", "") for t in a.get("terms") or []]
    size_text = " ".join(size_terms) if has_size_attr and size_terms else title
    pr = p.get("prices") or {}
    price = pr.get("price")
    try:
        price = f"{int(price) / 10 ** int(pr.get('currency_minor_unit', 2)):.2f} {pr.get('currency_code', '')}"
    except (TypeError, ValueError):
        price = str(price or "")
    imgs = p.get("images") or []
    img = imgs[0].get("src", "") if imgs else ""
    desc = (p.get("short_description") or "") + " " + (p.get("description") or "")
    return item("direkt", shop, p.get("permalink") or "", title, size_text, price.strip(), img, desc=desc)


def woo_recent(http, shop, endpoint):
    data = http.get(endpoint, {"per_page": 100, "orderby": "date", "order": "desc"})
    data = data if isinstance(data, list) else []
    return [it for it in (woo_to_item(shop, p) for p in data) if it], len(data)


def woo_endpoint(http, base):
    for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        data = http.get(base + path, {"per_page": 1})
        if isinstance(data, list):
            return base + path
    return None


def woo_run(http, shop, endpoint, queries=None):
    items, n = [], 0
    runs = [{"search": q} for q in queries] if queries else [{}]
    for extra in runs:
        for page in range(1, 61):
            data = http.get(endpoint, {"per_page": 100, "page": page, **extra})
            if not isinstance(data, list) or not data:
                break
            n += len(data)
            for p in data:
                it = woo_to_item(shop, p)
                if it:
                    items.append(it)
            if len(data) < 100:
                break
    return items, n


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


def domain(url):
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def fyj_run(http, matcher, priority, skip_domains=()):
    """FYJ nur als Lückenfüller: keine Marktplätze, keine Shops, die direkt abgefragt werden"""
    # FYJ-Suche mit einzelnen, markanten Wörtern (z. B. "vaart" statt "van der vaart"),
    # Feinfilterung passiert lokal. Für Sondertrikots werden die Teams komplett geholt.
    queries = []
    for p in matcher.players:
        if priority and p["prio"] != "hoch":
            continue
        for t in p["terms"]:
            w = norm(t).split()[-1] if norm(t) else ""
            if len(w) >= 4 and w not in queries:
                queries.append(w)
    if not priority:
        queries += [norm(q) for q in matcher.team_queries() if norm(q) not in queries]
    items, n = [], 0
    for q in queries:
        for size in FYJ_SIZES:
            for page in range(1, 11):
                data = http.get(FYJ_API, {"search": q, "sizes": size, "limit": 200, "page": page})
                rows = data if isinstance(data, list) else (data or {}).get("jerseys") or []
                if not rows:
                    break
                n += len(rows)
                for r in rows:
                    title = r.get("description") or ""
                    reissue = str(r.get("isReissue")).lower() == "true"   # kommt als Text "false"/"true"
                    dom = domain(r.get("sourceUrl") or "")
                    if not dom or dom in skip_domains or any(m in dom for m in FYJ_MARKETPLACES):
                        continue
                    extra = " ".join(str(x) for x in (r.get("player"), r.get("team")) if x)
                    price = f"{r.get('currentValue') or ''} {r.get('currency') or ''}".strip()
                    items.append(item("fyj", r.get("sourceType") or "FYJ", r.get("sourceUrl") or "",
                                      title, r.get("size") or "", price, r.get("imageUrl"), extra,
                                      fyj_condition=r.get("condition") or "", fyj_reissue=reissue))
                if len(rows) < 200:
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


WIX_STORES_APP = "1380b703-ce81-ff05-f115-39571d94dfcd"
WIX_ALL = "00000000-000000-000000-000000000001"   # "Alle Produkte" im alten Katalog; neuer Katalog (V3) hat eigene IDs
WIX_ALL_NAMES = re.compile(r"(?i)^(all products|alle produkte|alle artikel|tous les produits|todos los productos|"
                           r"tutti i prodotti|alle producten|all)$")
WIX_CATS = "{ catalog { categories(limit: 100) { list { id name } } } }"
WIX_QUERY = """query getProducts($offset: Int, $limit: Int, $cid: String!) { catalog {
 category(categoryId: $cid) {
 productsWithMetaData(limit: $limit, offset: $offset, onlyVisible: true) { totalCount list {
 id name urlPart price currency isInStock productType description media { url }
 options { title selections { description value } } } } } } }"""


def wix_run(http, shop, base, max_pages=120):
    """Wix Stores: öffentliche Shop-Schnittstelle, die auch die Shop-Seite für "Mehr laden" nutzt.
    Anonymer Besucher-Schlüssel aus /_api/v1/access-tokens, dann 100 Produkte pro Abfrage"""
    tokens = http.get(f"{base}/_api/v1/access-tokens")
    inst = (((tokens or {}).get("apps") or {}).get(WIX_STORES_APP) or {}).get("instance")
    if not inst:
        return [], 0
    api, hdr = f"{base}/_api/wix-ecommerce-storefront-web/api", {"Authorization": inst}

    def fetch(cid, offset):
        data = http.post(api, headers=hdr, json={"query": WIX_QUERY, "operationName": "getProducts",
                                                 "variables": {"offset": offset, "limit": 100, "cid": cid}})
        return ((((data or {}).get("data") or {}).get("catalog") or {}).get("category") or {}) \
            .get("productsWithMetaData") or {}

    first = fetch(WIX_ALL, 0)
    cats = [WIX_ALL]
    if not first.get("list"):
        # Neuer Wix-Katalog: Kategorie "All Products" suchen, sonst alle Kategorien zusammennehmen
        lst = ((((http.post(api, headers=hdr, json={"query": WIX_CATS}) or {}).get("data") or {})
                .get("catalog") or {}).get("categories") or {}).get("list") or []
        all_cat = [c["id"] for c in lst if WIX_ALL_NAMES.match((c.get("name") or "").strip())]
        cats = all_cat[:1] or [c["id"] for c in lst]
        first = None
    items, n, seen_ids = [], 0, set()
    for cid in cats:
        for page in range(max_pages):
            block = first if (first is not None and cid == WIX_ALL and page == 0) else fetch(cid, page * 100)
            prods = block.get("list") or []
            key = lambda p: p.get("id") or p.get("urlPart")
            items += wix_items(shop, base, [p for p in prods if key(p) not in seen_ids])
            seen_ids |= {key(p) for p in prods}
            n += len(prods)
            if len(prods) < 100 or (page + 1) * 100 >= (block.get("totalCount") or 0):
                break
    return items, n


def wix_text(desc):
    """Beschreibung: neuer Wix-Katalog liefert Rich-Text als JSON ("textData": {"text": ...}), alter HTML"""
    if isinstance(desc, str) and desc.lstrip().startswith("{"):
        try:
            data = json.loads(desc)
        except ValueError:
            return plain(desc)
        out = []

        def walk(x):
            if isinstance(x, dict):
                if isinstance(x.get("textData"), dict):
                    out.append(str(x["textData"].get("text") or ""))
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        return " ".join(out)
    return plain(desc)


def wix_items(shop, base, prods):
    items = []
    for p in prods:
        if not p.get("isInStock") or not p.get("urlPart"):
            continue
        sizes, grade = [], ""
        for o in p.get("options") or []:
            title = norm(o.get("title"))
            vals = [x.get("description") or x.get("value") or "" for x in o.get("selections") or []]
            if "youth" in title or "kid" in title:
                sizes += ["youth"] + vals           # Kindergröße, wird über die Ausschlüsse aussortiert
            elif SIZE_ATTR_RX.search(title):
                sizes += vals
            elif "condition" in title and vals:
                grade = vals[0]
        media = (p.get("media") or [{}])[0].get("url") or ""
        img = media if media.startswith("http") else (f"https://static.wixstatic.com/media/{media}" if media else "")
        price = f"{p.get('price')} {p.get('currency') or ''}".strip() if p.get("price") is not None else ""
        items.append(item("direkt", shop, f"{base}/product-page/{p['urlPart']}", p.get("name") or "",
                          f"{p.get('name') or ''} {' '.join(sizes)}", price, img,
                          desc=f"{p.get('name') or ''} {wix_text(p.get('description'))}",   # Zustand teils im Titel
                          typ=p.get("productType") if p.get("productType") not in ("physical", None) else "",
                          fyj_condition=grade))
    return items


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
            status["fehler"] = "Shopsystem nicht automatisch erkannt"
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
            elif status["produkte"] == 0 and mode == "full":
                status["fehler"] = "keine Produkte erhalten"
        status["sekunden"] = round(time.time() - t0, 1)
        status["anfragen"] = http.count


# ---------------------------------------------------------------------------
# Drop-Rhythmus (nur Shopify: products.json enthält published_at für den ganzen Katalog)
# ---------------------------------------------------------------------------
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def rhythm(stamps):
    """Wann stellt ein Shop neue Artikel ein? Schub = viele Artikel kurz hintereinander"""
    t = now()
    ds = []
    for x in stamps:
        try:
            d = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo and t - dt.timedelta(days=RHYTHM_DAYS) <= d <= t:
            ds.append(d)
    ds.sort()
    out = {"neu_7": sum(d >= t - dt.timedelta(days=7) for d in ds),
           "neu_30": sum(d >= t - dt.timedelta(days=30) for d in ds),
           "tage_30": len({d.astimezone(TZ).date() for d in ds if d >= t - dt.timedelta(days=30)}),
           "letzte": ds[-1].isoformat() if ds else ""}
    batches = []
    for d in ds:
        if batches and d - batches[-1][-1] <= dt.timedelta(minutes=BATCH_GAP_MIN):
            batches[-1].append(d)
        else:
            batches.append([d])
    big = [b for b in batches if len(b) >= BATCH_MIN]
    share = sum(len(b) for b in big) / len(ds) if ds else 0
    if not out["neu_30"]:
        out["typ"], out["text"] = "ruhig", f"seit 30 Tagen nichts Neues ({len(ds)} in {RHYTHM_DAYS} Tagen)"
        return out
    starts = [b[0].astimezone(TZ) for b in big]
    gaps = sorted((b - a).total_seconds() / 86400 for a, b in zip(starts, starts[1:]))
    gap = gaps[len(gaps) // 2] if gaps else 0
    if len(big) >= 2 and share >= 0.6 and gap >= DROP_MIN_GAP_DAYS:
        # pro Wochentag mit genug Schüben einen Termin (manche Shops droppen z. B. Di und Fr)
        termine = []
        for wd in range(7):
            dom = [s for s in starts if s.weekday() == wd]
            if len(dom) < DROP_DAY_MIN or len(dom) / len(big) < DROP_DAY_SHARE:
                continue
            mins = sorted(s.hour * 60 + s.minute for s in dom)
            med = mins[len(mins) // 2]
            recent = sorted(s.hour * 60 + s.minute for s in dom[-4:])
            shifted = len(dom) >= 6 and abs(recent[len(recent) // 2] - med) > 60
            if shifted:   # Uhrzeit hat sich zuletzt verschoben: die letzten Drops zählen
                med, mins = recent[len(recent) // 2], recent
            spread = (mins[(3 * len(mins)) // 4] - mins[len(mins) // 4]) // 2
            termine.append({"tag": WEEKDAYS[wd], "uhrzeit": med // 60, "minute": med % 60, "streuung_min": spread,
                            "anzahl": len(dom), "verschoben": shifted})
        termine.sort(key=lambda x: -x["anzahl"])
        top = termine[0] if termine else {"tag": WEEKDAYS[starts[-1].weekday()], "uhrzeit": starts[-1].hour,
                                           "minute": 0, "streuung_min": 0, "anzahl": 1, "verschoben": False}
        out.update(typ="drops", schuebe=len(big), abstand_tage=round(gap, 1), termine=termine,
                   wochentag=top["tag"], uhrzeit=top["uhrzeit"], minute=top["minute"],
                   anteil=round(sum(x["anzahl"] for x in termine) / len(big), 2),
                   letzter_schub=big[-1][0].isoformat())
        parts = [f"{x['tag']} gegen {x['uhrzeit']:02d}:{x['minute']:02d} (±{x['streuung_min']} Min., {x['anzahl']}x"
                 + (", zuletzt verschoben" if x["verschoben"] else "") + ")" for x in termine]
        out["text"] = (f"Drops etwa alle {gap:.0f} Tage: " + ("; ".join(parts) or "kein fester Wochentag")
                       + f"; {len(big)} Schübe in {RHYTHM_DAYS} Tagen, zuletzt {starts[-1]:%d.%m. %H:%M}")
    elif out["tage_30"] >= 8:
        out["typ"] = "laufend"
        out["text"] = (f"laufend: an {out['tage_30']} von 30 Tagen neue Artikel, "
                       f"{out['neu_7']} in 7 Tagen, {out['neu_30']} in 30 Tagen")
    else:
        out["typ"] = "unregelmäßig"
        out["text"] = (f"unregelmäßig: an {out['tage_30']} von 30 Tagen neue Artikel, "
                       f"{out['neu_30']} in 30 Tagen, zuletzt {ds[-1].astimezone(TZ):%d.%m.}")
    return out


def drop_slots(shop, status_store):
    """[(Wochentag 0-6, Stunde, Minute, Quelle, Fenster in Min.)]: fest aus shops.yaml plus gemessen"""
    slots = []
    for x in drop_specs(shop):
        slot = fixed_slot(x)
        if slot:
            slots.append((*slot, "fest", DROP_WINDOW_MIN))
    for q in (status_store.get("quellen") or {}).get("liste", []):
        r = q.get("rhythmus") or {}
        if q.get("name") != shop["name"] or r.get("typ") != "drops" or r.get("anteil", 0) < DROP_MIN_SHARE:
            continue
        termine = r.get("termine") or [{"tag": r["wochentag"], "uhrzeit": r["uhrzeit"],
                                        "minute": r.get("minute", 0), "streuung_min": r.get("streuung_min", 0)}]
        for x in termine:
            # etwas vor der typischen Zeit beginnen, bei großer Streuung entsprechend früher und länger
            early = DROP_LEAD_MIN + min(int(x.get("streuung_min", 0)), DROP_MAX_SPREAD_MIN)
            start = max(int(x["uhrzeit"]) * 60 + int(x.get("minute", 0)) - early, 0)
            slots.append((WEEKDAYS.index(x["tag"]), start // 60, start % 60, "gemessen", DROP_WINDOW_MIN + early))
    return slots


def drop_specs(shop):
    """Drop-Angaben aus shops.yaml; "täglich 18:00 Europe/London" wird zu sieben Wochentagen"""
    out = []
    for x in shop.get("drop") or []:
        m = re.match(r"(?i)t(ä|ae)glich\s+(.+)$", str(x).strip())
        out += [f"{d} {m.group(2)}" for d in WEEKDAYS] if m else [str(x)]
    return out


def fixed_slot(spec, ref=None):
    """'Fr 19:00' (deutsche Zeit) oder 'Fr 20:00 Pacific/Auckland' -> (Wochentag, Stunde, Minute) in deutscher
    Zeit, für die Woche um ref (Zeitumstellungen in beiden Ländern werden so automatisch berücksichtigt)"""
    m = re.match(r"(Mo|Di|Mi|Do|Fr|Sa|So)\s+(\d{1,2}):(\d{2})(?:\s+([A-Za-z_]+/[A-Za-z_]+))?$", str(spec).strip())
    if not m:
        return None
    wd, h, mi = WEEKDAYS.index(m.group(1)), int(m.group(2)), int(m.group(3))
    if not m.group(4):
        return wd, h, mi
    zone = ZoneInfo(m.group(4))
    local = (ref or now()).astimezone(zone)
    day = local - dt.timedelta(days=(local.weekday() - wd) % 7)
    berlin = day.replace(hour=h, minute=mi, second=0, microsecond=0).astimezone(TZ)
    return berlin.weekday(), berlin.hour, berlin.minute


def drop_calendar(shops, status_store):
    """Alle Drop-Termine fürs Dashboard: feste (shops.yaml) und gemessene (Rhythmus)"""
    rhythms = {q.get("name"): q.get("rhythmus") or {} for q in (status_store.get("quellen") or {}).get("liste", [])}
    out = []
    for shop in shops:
        if (shop.get("plattform") or "auto").lower() in ("aus", "fyj"):
            continue
        for x in drop_specs(shop):
            slot = fixed_slot(x)
            if slot:
                out.append({"shop": shop["name"], "tag": WEEKDAYS[slot[0]], "zeit": f"{slot[1]:02d}:{slot[2]:02d}",
                            "quelle": "fest"})
        r = rhythms.get(shop["name"]) or {}
        if r.get("typ") == "drops" and r.get("anteil", 0) >= DROP_MIN_SHARE:
            for x in r.get("termine") or []:
                out.append({"shop": shop["name"], "tag": x["tag"], "zeit": f"{x['uhrzeit']:02d}:{x['minute']:02d}",
                            "quelle": "gemessen", "streuung": x.get("streuung_min", 0), "anzahl": x.get("anzahl", 0),
                            "abstand": r.get("abstand_tage"), "verschoben": x.get("verschoben", False)})
    out.sort(key=lambda d: (WEEKDAYS.index(d["tag"]), d["zeit"], d["shop"]))
    return out


def drop_due(shop, status_store, t):
    """Fälliger Drop-Slot (Text) oder None. Fenster: ab Drop-Zeit DROP_WINDOW_MIN Minuten"""
    last = (status_store.get("drop_checks") or {}).get(shop["name"])
    if last and t - dt.datetime.fromisoformat(last) < dt.timedelta(minutes=DROP_RECHECK_MIN):
        return None
    local = t.astimezone(TZ)
    for wd, h, mi, src, window in drop_slots(shop, status_store):
        start = (local - dt.timedelta(days=(local.weekday() - wd) % 7)).replace(hour=h, minute=mi, second=0,
                                                                                 microsecond=0)
        if start > local:
            start -= dt.timedelta(days=7)
        if local - start <= dt.timedelta(minutes=window):
            return f"{WEEKDAYS[wd]} {h:02d}:{mi:02d} ({src})"
    return None


# ---------------------------------------------------------------------------
# Zustand und Verfügbarkeit
# ---------------------------------------------------------------------------
SCORE_RX = re.compile(r"(?<![\d/.,])(10|[1-9](?:[.,]5)?)\s*/\s*10(?![\d/])")   # 8/10, nicht 2009/10
NEW_TAG_RX = re.compile(r"(?<![a-z])(bnwt|bnwot|bnib|deadstock|brand new with tags|new with tags)(?![a-z])", re.I)
COND_KEY_RX = re.compile(r"(?i)(?<![a-z])(condition|zustand|stan|staat van het shirt|staat|estado|stato|used)\s*[:\-]")
SOLD_RX = re.compile(r"(?i)outofstock|soldout|discontinued")
COND_WORD_RX = re.compile(r"(?i)^(?:condition|zustand|stan|staat van het shirt|staat|estado|stato|used)\s*[:\-]\s*(mint|excellent|very good|good|fair|poor|"
                          r"used|new|like new|as new|perfect|great|average)(?![a-z])")


DESC_OTHER_RX = re.compile(r"(?<![a-z])(t-shirt|t shirt|tee-shirt|tee shirt|jacket|veste|track top|tracktop)(?![a-z])")
DESC_JERSEY_RX = re.compile(r"(?<![a-z])(maillot|jersey|trikot|camiseta|camisola|maglia|koszulka|shirt home|"
                            r"football shirt|match shirt|home shirt|away shirt|third shirt|kit)(?![a-z])")


TITLE_JERSEY_RX = re.compile(r"(?<![a-z-])(shirt|jersey|maillot|trikot|camiseta|maglia|koszulka)(?![a-z])")


def desc_not_jersey(desc, title=""):
    """Beschreibung spricht von T-Shirt/Jacke und nirgends von einem Trikot (z. B. VFA "Le t-shirt en détail").
    Nennt schon der Titel ein Trikot, hat er Vorrang (Beschreibungen erwähnen z. B. Trainer "Kenny Jackett")"""
    nt = norm(title)
    if TITLE_JERSEY_RX.search(nt) and not DESC_OTHER_RX.search(nt):
        return False
    t = norm(plain(desc))
    return bool(t and DESC_OTHER_RX.search(t) and not DESC_JERSEY_RX.search(t))


def below_min(grade, minimum):
    """'6/10' unter Mindestnote 7? Ohne Note oder ohne Vorgabe: nein"""
    m = re.match(r"(\d+(?:\.\d)?)/10$", grade or "")
    return bool(minimum and m and float(m.group(1)) < float(minimum))


def plain(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    return re.sub(r"\s+", " ", text).strip()


def condition_info(title, desc, fallback=""):
    """('8/10' | 'BNWT' | FYJ-Angabe wie 'Very Good' | '', Notiz ab 'Condition:' oder '')"""
    text = plain(desc)
    m = SCORE_RX.search(title) or SCORE_RX.search(text)
    if m:
        grade = m.group(1).replace(",", ".") + "/10"
    else:
        t = NEW_TAG_RX.search(f"{title} {text}")
        grade = t.group(1).upper() if t and len(t.group(1)) <= 9 else ("BNWT" if t else fallback)
    note = ""
    k = COND_KEY_RX.search(text)
    if k:
        w = COND_WORD_RX.search(text[k.start():])
        if w and (not grade or grade == fallback):
            grade = w.group(1).title()
        note = text[k.start():k.start() + NOTE_LEN]
        if len(text) > k.start() + NOTE_LEN:
            note = note.rsplit(" ", 1)[0] + " …"
    return grade, note


def ld_products(data):
    """alle schema.org-Product-Objekte aus JSON-LD (auch in @graph oder Listen)"""
    if isinstance(data, list):
        for x in data:
            yield from ld_products(x)
    elif isinstance(data, dict):
        typ = data.get("@type")
        if typ in ("Product", "ProductGroup") or (isinstance(typ, list) and "Product" in typ):
            yield data
        for key in ("@graph", "hasVariant"):
            if key in data:
                yield from ld_products(data[key])


def check_page(http, url):
    """Produktseite: {'verfuegbar': True/False/None, 'desc': str} oder None bei Fehler"""
    txt = http.get(url, want="text")
    if not txt:
        return None
    soup = BeautifulSoup(txt, "html.parser")
    avail, desc, brand = [], "", ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for prod in ld_products(data):
            desc = desc or plain(prod.get("description"))
            b = prod.get("brand")
            brand = brand or plain(b.get("name") if isinstance(b, dict) else b)
            offers = prod.get("offers") or []
            for o in offers if isinstance(offers, list) else [offers]:
                if isinstance(o, dict) and o.get("availability"):
                    avail.append(str(o["availability"]))
    if not desc:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        desc = plain(meta.get("content")) if meta else ""
    ok = None
    if avail:
        ok = any(not SOLD_RX.search(a) for a in avail)
    return {"verfuegbar": ok, "desc": desc, "marke": brand}


def enrich(seen, ts, budget, matcher):
    """FYJ-Treffer auf der Shop-Seite prüfen: verkauft? Zustand? Neue zuerst, dann die ältesten Prüfungen"""
    due = dt.timedelta(days=RECHECK_DAYS)
    cand = [e for e in seen.values()
            if e["last"] == ts and (e.get("via") == "fyj" or e.get("pruefen")) and not e.get("verkauft")
            and "ebay." not in e["url"]
            and (not e.get("geprueft") or e.get("pruef_v") != CHECK_VERSION
                 or now() - dt.datetime.fromisoformat(e["geprueft"]) > due)]
    cand.sort(key=lambda e: (bool(e.get("geprueft")), not is_high(e), e.get("geprueft") or ""))
    by_host = {}
    for e in cand[:budget]:
        by_host.setdefault(urlparse(e["url"]).netloc, []).append(e)

    def work(entries):
        http = Http(SHOPIFY_GATE if "/products/" in entries[0]["url"] else None)
        for e in entries:
            try:
                res = check_page(http, e["url"])
            except requests.RequestException:
                res = None
            if res is None:
                continue
            e["geprueft"], e["pruef_v"] = ts, CHECK_VERSION
            if res["verfuegbar"] is False:
                e["verkauft"] = ts
            if res["marke"] and hit(matcher.brand_ex, norm(res["marke"])):
                e["aussortiert"] = f"Hersteller {res['marke']}"
            elif desc_not_jersey(res["desc"], e["title"]):
                e["aussortiert"] = "Beschreibung: kein Trikot (T-Shirt/Jacke)"
            grade, note = condition_info(e["title"], res["desc"])
            if grade:
                e["zustand"] = grade
            if note:
                e["zustand_notiz"] = note

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(work, by_host.values()))
    return min(len(cand), budget)


# ---------------------------------------------------------------------------
# Benachrichtigung
# ---------------------------------------------------------------------------
def push(topic, title, message, prio=3, click=None, image=None, tags=None, dry=False):
    payload = {"topic": topic, "title": title[:250], "message": message[:3500],
               "priority": prio, "tags": tags or []}
    if click:
        payload["click"] = click
    if image and image.startswith("http"):
        payload["attach"] = image
    if dry or not topic:
        print(f"[PUSH p{prio}] {title}\n    {message}\n    {click or ''}")
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        requests.post(server, json=payload, timeout=20)
    except requests.RequestException as e:
        print("Push fehlgeschlagen:", e, file=sys.stderr)


def short(e, shop=False):
    """Titel plus Größe (nur falls nicht schon im Titel) und optional Shop"""
    extra = [] if (e.get("size") and SIZE_RX.search(norm(e["title"]))) else [e.get("size", "")]
    if shop:
        extra.append(e["shop"])
    extra = [x for x in extra if x]
    return e["title"] + (f" ({', '.join(extra)})" if extra else "")


def detail_line(e):
    """Titel plus Zeile mit Größe, Preis, Zustand und ggf. Zustandsnotiz"""
    parts = [f"Größe {e['size']}", e.get("price", ""), f"Zustand {e['zustand']}" if e.get("zustand") else ""]
    text = e["title"] + "\n" + " · ".join(x for x in parts if x)
    return text + (f"\n{e['zustand_notiz']}" if e.get("zustand_notiz") else "")


def push_label(entry):
    return ", ".join(entry["labels"])


def is_high(entry):
    return "hoch" in entry.get("prios", [])


# ---------------------------------------------------------------------------
# Preise
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Bericht und Dashboard
# ---------------------------------------------------------------------------
def current_entries(seen):
    """{Schlüssel: Eintrag} aller Treffer, die in den letzten REPORT_HOURS gesehen wurden"""
    cutoff = now() - dt.timedelta(hours=REPORT_HOURS)
    return {k: e for k, e in seen.items()
            if dt.datetime.fromisoformat(e["last"]) >= cutoff
            and not (e.get("verkauft") or e.get("weg") or e.get("aussortiert"))}


def write_dashboard(seen, status_store, mode, ts, watch_cfg, shops):
    """docs/treffer.json für das Dashboard auf GitHub Pages"""
    kurse = status_store.get("kurse") or {}
    rates = kurse.get("rates") or {"EUR": 1.0}
    items = []
    for key, e in current_entries(seen).items():
        items.append({
            "id": key, "titel": e["title"], "url": e["url"], "shop": e["shop"],
            "preis": e.get("price", ""), "eur": to_eur(e.get("price"), rates),
            "groesse": e.get("size", ""), "labels": e["labels"], "hoch": is_high(e),
            "zustand": e.get("zustand", ""), "notiz": e.get("zustand_notiz", ""), "bild": e.get("image", ""),
            "erst": e["first"], "zuletzt": e["last"], "via": e.get("via", ""),
            "still": bool(e.get("still")), "teuer": bool(e.get("teuer")), "repro": bool(e.get("repro")), "reissue": bool(e.get("reissue")),
        })
    quellen = status_store.get("quellen") or {}
    data = {"stand": ts, "modus": mode, "letzter_gesamtlauf": status_store.get("last_full", ""),
            "fyj_shops": status_store.get("fyj_shops") or {},
            "laeufe": status_store.get("laeufe") or [],
            "drops": drop_calendar(shops, status_store),
            "preisgrenze": (watch_cfg.get("preisgrenze") or {}),
            "kurse_datum": kurse.get("datum", ""), "treffer": items,
            "quellen": quellen.get("liste", []), "quellen_stand": quellen.get("zeit", "")}
    DASHBOARD_FILE.parent.mkdir(exist_ok=True)
    DASHBOARD_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_report(seen, sources, sources_time, mode):
    current = [e for e in current_entries(seen).values() if not e.get("teuer")]
    groups = {}
    for e in current:
        for lab in e["labels"]:
            groups.setdefault(lab, []).append(e)

    def gkey(lab):
        es = groups[lab]
        high = any(is_high(e) for e in es)
        return (0 if lab.startswith("Thiago") else 1 if high else 2, lab.lower())

    lines = ["# Trikot-Tracker", "",
             f"Stand: {now().astimezone(TZ):%d.%m.%Y %H:%M} Uhr ({mode}), "
             f"{len(current)} aktuelle Treffer in XL/XXL", ""]
    if not groups:
        lines += ["Aktuell keine Treffer.", ""]
    for lab in sorted(groups, key=gkey):
        es = sorted(groups[lab], key=lambda e: e["first"], reverse=True)
        lines += [f"## {lab} ({len(es)})", "", "| Trikot | Größe | Zustand | Preis | Shop | seit |",
                  "|---|---|---|---|---|---|"]
        for e in es:
            t = e["title"].replace("|", "/")
            size = (e.get("size") or "").replace("|", "/")[:25]
            first = dt.datetime.fromisoformat(e["first"]).astimezone(TZ)
            cond = (e.get("zustand") or "").replace("|", "/")
            lines.append(f"| [{t}]({e['url']}) | {size} | {cond} | {e.get('price', '')} | {e['shop']} | {first:%d.%m.} |")
        lines.append("")
    when = dt.datetime.fromisoformat(sources_time).astimezone(TZ) if sources_time else None
    lines += ["## Quellen-Status", "",
              f"Vom letzten Gesamt-Run ({when:%d.%m.%Y %H:%M} Uhr)" if when else "Vom aktuellen Run", "",
              "| Quelle | System | Produkte | Anfragen | Hinweis |", "|---|---|---|---|---|"]
    for s in sources:
        lines.append(f"| {s['name']} | {s.get('plattform', '')} | {s.get('produkte', 0)} | "
                     f"{s.get('anfragen', '')} | {s.get('fehler') or s.get('info') or 'ok'} |")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
FLAG_RX = re.compile(r"(?im)^(grund|id|kommentar)\s*:\s*(.*)$")


def parse_flag(body):
    """Issue-Text aus dem Dashboard -> {'grund', 'id', 'kommentar'} oder None"""
    found = {k.lower(): v.strip() for k, v in FLAG_RX.findall(body or "")}
    return found if found.get("grund") and found.get("id") else None


def apply_flags(seen, status_store, ts):
    """Im Dashboard gemeldete Treffer (GitHub-Issues mit Label "flag") übernehmen und Issues schließen.
    Nur Issues des Repo-Inhabers zählen (öffentliches Repo). Gibt die Zahl neuer Meldungen zurück"""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or (repo or "").split("/")[0]
    flags = status_store.setdefault("flags", {})
    new = 0
    if token and repo:
        api = f"https://api.github.com/repos/{repo}/issues"
        hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            issues = requests.get(api, params={"labels": "flag", "state": "open", "per_page": 100},
                                  headers=hdr, timeout=TIMEOUT).json()
        except (requests.RequestException, ValueError):
            issues = []
        for iss in issues if isinstance(issues, list) else []:
            if (iss.get("user") or {}).get("login") != owner:
                continue
            f = parse_flag(iss.get("body"))
            if not f:
                continue
            flags[f["id"]] = {"grund": f["grund"].lower(), "kommentar": f.get("kommentar", ""),
                              "zeit": ts, "issue": iss.get("number"), "titel": (iss.get("title") or "")[:120]}
            new += 1
            e = seen.get(f["id"])
            msg = (f"Übernommen: Treffer ist ab sofort ausgeblendet ({f['grund']})." if e else
                   "Übernommen, der Treffer war schon nicht mehr in der Liste.")
            try:
                requests.post(f"{api}/{iss['number']}/comments", json={"body": msg}, headers=hdr, timeout=TIMEOUT)
                requests.patch(f"{api}/{iss['number']}", json={"state": "closed"}, headers=hdr, timeout=TIMEOUT)
            except requests.RequestException:
                pass
    for key, f in flags.items():
        e = seen.get(key)
        if not e:
            continue
        if f["grund"].startswith("ausverkauft"):
            e.setdefault("verkauft", f["zeit"])
        else:
            e["aussortiert"] = f"Gemeldet: {f['grund']}" + (f" ({f['kommentar']})" if f.get("kommentar") else "")
    return new


def recently_done(status_store, mode):
    """Hat ein Run dieses Modus kürzlich stattgefunden? (Sperre für die GitHub-Rückfall-Zeitpläne)"""
    limit = FALLBACK_SKIP_HOURS.get(mode)
    if not limit:
        return False
    times = [l["zeit"] for l in status_store.get("laeufe") or [] if l.get("modus") == mode]
    if mode == "full" and status_store.get("last_full"):
        times.append(status_store["last_full"])
    return any(now() - dt.datetime.fromisoformat(t) < dt.timedelta(hours=limit) for t in times)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "priority", "drop", "test"], default="full")
    ap.add_argument("--dry-run", action="store_true", help="nichts senden, nur ausgeben")
    ap.add_argument("--only", help="nur Shops, deren Name diesen Text enthält (zum Testen)")
    ap.add_argument("--rueckfall", action="store_true",
                    help="Start über den GitHub-Zeitplan: nur laufen, wenn cron-job.org den Run nicht schon erledigt hat")
    args = ap.parse_args()

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic and not args.dry_run:
        sys.exit("NTFY_TOPIC fehlt (GitHub Secret anlegen) oder --dry-run verwenden.")

    if args.mode == "test":
        push(topic, "✅ Trikot-Tracker verbunden",
             "Wenn du das liest, funktionieren die Benachrichtigungen.", 4,
             tags=["white_check_mark"], dry=args.dry_run)
        return

    watch = yaml.safe_load((ROOT / "watchlist.yaml").read_text(encoding="utf-8"))
    shops_cfg = yaml.safe_load((ROOT / "shops.yaml").read_text(encoding="utf-8"))
    matcher = Matcher(watch)
    STATE_DIR.mkdir(exist_ok=True)
    seen = load_json(SEEN_FILE, {})
    status_store = load_json(STATUS_FILE, {"platforms": {}, "sources_ok": []})
    if args.rueckfall and recently_done(status_store, args.mode):
        print(f"Rückfall-Start übersprungen: {args.mode} lief schon vor kurzem (cron-job.org)")
        return
    platforms = status_store.setdefault("platforms", {})
    currencies = status_store.setdefault("currencies", {})
    sources_ok = set(status_store.setdefault("sources_ok", []))
    # Reissues (Nachbauten) werden seit 01.10.2026 nicht mehr erfasst; gezielt ausgeschlossene
    # Links und zu schlechter Zustand (min_zustand je Shop) fliegen sofort raus
    min_grade = {s["name"]: s["min_zustand"] for s in shops_cfg.get("shops") or [] if s.get("min_zustand")}
    seen = {k: v for k, v in seen.items()
            if "(Reissue)" not in v["title"] and k not in matcher.url_ex
            and not below_min(v.get("zustand", ""), min_grade.get(v["shop"]))}
    first_run = not seen

    shops = shops_cfg.get("shops") or []
    if args.only:
        shops = [s for s in shops if args.only.lower() in s["name"].lower()]
    # Meldungen aus dem Dashboard (GitHub-Issues) in jedem Run übernehmen
    new_flags = apply_flags(seen, status_store, now().isoformat()) if not args.dry_run else 0
    if new_flags:
        print(f"{new_flags} Meldung(en) aus dem Dashboard übernommen")
    if args.mode == "drop":
        # nur Shops, deren Drop gerade läuft; sonst sofort ohne jede Änderung beenden (außer es gab Meldungen)
        due = {s["name"]: drop_due(s, status_store, now()) for s in shops
               if (s.get("plattform") or "auto").lower() not in ("aus", "fyj")}
        shops = [s for s in shops if due.get(s["name"])]
        if not shops and not new_flags:
            print("Drop-Run: kein Drop fällig")
            return
        if shops:
            print("Drop-Run:", ", ".join(f"{s['name']} {due[s['name']]}" for s in shops))
    # Shops, die direkt abgefragt werden: deren FYJ-Daten ignorieren (direkt ist aktueller und genauer)
    # Ausnahme: Shops, die im letzten Gesamt-Run nicht funktioniert haben, deckt FYJ wieder ab
    failed = {q["name"] for q in (status_store.get("quellen") or {}).get("liste", []) if q.get("fehler")}
    direct_domains = {domain(s["url"]) for s in shops_cfg.get("shops") or []
                      if (s.get("plattform") or "auto").lower() not in ("fyj", "aus") and s["name"] not in failed}
    use_fyj = (str(shops_cfg.get("fyj", "an")).lower() in ("an", "true", "ja", "on") and not args.only
               and args.mode != "drop")

    flagged = set(status_store.get("flags") or {})
    # Neu angelegte Kategorien (Labels) beim ersten Gesamt-Run still übernehmen, sonst Push-Flut
    all_labels = {p["name"] for p in matcher.players} | {k["name"] for k in matcher.kits}
    known_labels = set(status_store.get("known_labels") or all_labels)   # erster Start: alles bekannt
    new_labels = all_labels - known_labels
    lock = threading.Lock()
    results, statuses, fyj_status = [], [], None
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_shop, s, args.mode, matcher, platforms, currencies): s for s in shops}
        fyj_fut = None
        if use_fyj:
            def fyj_job():
                http = Http()
                t0 = time.time()
                st = {"name": "FindYourJersey", "plattform": "fyj", "produkte": 0, "fehler": ""}
                try:
                    its, n = fyj_run(http, matcher, args.mode == "priority", direct_domains)
                    st["produkte"] = n
                    if n == 0 and args.mode == "full":
                        st["fehler"] = "keine Daten erhalten (Schnittstelle geändert oder gesperrt?)"
                    return its, st
                except Exception as e:
                    st["fehler"] = f"{type(e).__name__}: {str(e)[:120]}"
                    return [], st
                finally:
                    if http.limited and not st["fehler"]:
                        st["fehler"] = f"unvollständig, {http.limited}x gedrosselt (HTTP 429)"
                    st["anfragen"] = http.count
                    st["sekunden"] = round(time.time() - t0, 1)
            fyj_fut = ex.submit(fyj_job)
        for f in cf.as_completed(list(futs) + ([fyj_fut] if fyj_fut else [])):
            its, st = f.result()
            with lock:
                results.append((st["name"], its, st))
                if f is fyj_fut:
                    fyj_status = st
                else:
                    statuses.append(st)

    # Treffer auswerten
    ts = now().isoformat()
    rates = fetch_rates(status_store)["rates"]
    pg = watch.get("preisgrenze") or {}
    max_eur = float(pg.get("max_eur") or 0)
    no_limit = set(pg.get("ausnahmen") or [])

    def too_expensive(e):
        eur = to_eur(e.get("price"), rates)
        return bool(max_eur and eur and eur > max_eur and not no_limit & set(e["labels"]))
    new_entries = []
    counts = status_store.setdefault("counts", {})
    for src_name, its, st in results:
        works = args.mode == "full" and st.get("produkte", 0) > 0 and not st.get("fehler")
        n_now, n_prev = st.get("produkte", 0), counts.get(src_name, 0)
        # Neue Quelle ODER Bestand plötzlich viel größer (z. B. vorher abgeschnitten):
        # dann still übernehmen statt eine Flut an "neuen" Treffern zu melden
        jump = works and n_prev and n_now > n_prev * 1.3 and n_now - n_prev > 200
        fresh_source = works and (src_name not in sources_ok or jump)
        if args.mode != "full" and src_name not in sources_ok:
            fresh_source = True   # noch nie im Gesamt-Run gewesen: Bestand still übernehmen
        if works:
            sources_ok.add(src_name)
            counts[src_name] = n_now
        for it in its:
            if it.get("typ") and matcher.type_excluded(it["typ"]):
                continue
            if it["url"] and (canon_url(it["url"]) in matcher.url_ex or canon_url(it["url"]) in flagged):
                continue
            if it.get("desc") and it.get("source") == "direkt" and desc_not_jersey(it["desc"], it["title"]) \
                    and it.get("desc") != it.get("title"):
                continue
            if it.get("desc") and it.get("source") == "direkt" and matcher.repro_flock(it["desc"]):
                it["fyj_reissue"] = it["desc_repro"] = True   # wie FYJ-Reissue: nur Thiago/erlaubte Kategorien
            labs = matcher.labels(it["match_text"], it.get("fyj_reissue", False), it.get("desc", ""))
            if not labs or not matcher.size_ok(it["size_text"], norm(it["match_text"])):
                continue
            if not it["url"]:
                continue
            key = canon_url(it["url"])
            size = SIZE_RX.search(norm(it["size_text"]))
            grade, note = condition_info(it["title"], it.get("desc"), it.get("fyj_condition", ""))
            if below_min(grade, min_grade.get(it["shop"])):
                continue
            entry = seen.get(key)
            if entry:
                # Labels pro Lauf neu berechnen (sonst bleiben alte Regeln ewig hängen),
                # innerhalb eines Laufs aus mehreren Quellen zusammenführen
                if entry["last"] != ts:
                    entry["labels"], entry["prios"] = [], []
                entry["last"] = ts
                entry.pop("weg", None)
                entry["labels"] = sorted(set(entry["labels"]) | {l for l, _ in labs})
                entry["prios"] = sorted(set(entry["prios"]) | {p for _, p in labs})
                if it["source"] == "direkt":      # direkte Daten sind aktueller als FYJ
                    entry.update(price=it["price"] or entry.get("price", ""), shop=it["shop"], via="direkt")
                    if it.get("pruefen"):
                        entry["pruefen"] = True
                    entry.pop("verkauft", None)
                    if grade:
                        entry["zustand"] = grade
                    if note:
                        entry["zustand_notiz"] = note
                elif grade and not entry.get("zustand"):
                    entry["zustand"] = grade
                if it["source"] == entry.get("via"):
                    entry["title"] = it["title"]
                continue
            entry = {"title": it["title"], "url": it["url"], "shop": it["shop"],
                     "price": it["price"], "image": it["image"],
                     "size": size.group(0).upper() if size else "",
                     "labels": sorted({l for l, _ in labs}), "prios": sorted({p for _, p in labs}),
                     "first": ts, "last": ts, "via": it["source"]}
            if grade:
                entry["zustand"] = grade
            if note:
                entry["zustand_notiz"] = note
            if it.get("pruefen"):
                entry["pruefen"] = True
            if matcher.repro_flock(it["match_text"]) or it.get("desc_repro") \
                    or (it.get("fyj_reissue") and "Thiago" in entry["labels"]):
                entry["repro"] = True
            elif it.get("fyj_reissue") or matcher.reissue(it["match_text"]):
                entry["reissue"] = True
            seen[key] = entry
            if first_run or fresh_source or (new_labels and set(entry["labels"]) <= new_labels):
                entry["still"] = True   # ohne Push übernommen (Erstlauf, neue Quelle oder neue Kategorie)
            else:
                new_entries.append(entry)

    # Fundgrube: Shops, die nur über FYJ Treffer liefern (Kandidaten für direkte Anbindung)
    if args.mode == "full" and fyj_status and not fyj_status.get("fehler"):
        found = {}
        for e in seen.values():
            if e["last"] == ts and e.get("via") == "fyj" and not e.get("verkauft"):
                found[domain(e["url"])] = found.get(domain(e["url"]), 0) + 1
        old = status_store.get("fyj_shops") or {}
        status_store["fyj_shops"] = {d: {"treffer": c, "seit": (old.get(d) or {}).get("seit", ts)}
                                     for d, c in sorted(found.items(), key=lambda x: -x[1])}

    # Gesamtlauf: Treffer, die eine erfolgreich abgefragte Quelle nicht mehr liefert (verkauft oder
    # passt nach Regeländerung nicht mehr), sofort ausblenden statt erst nach REPORT_HOURS
    if args.mode == "full" and not args.only:
        ok_src = {st["name"] for _, _, st in results if not st.get("fehler")}
        for e in seen.values():
            src = "FindYourJersey" if e.get("via") == "fyj" else e["shop"]
            if e["last"] != ts and src in ok_src:
                e.setdefault("weg", ts)
            elif e["last"] == ts:
                e.pop("weg", None)

    # FYJ-Treffer auf der Shop-Seite prüfen (verkauft? Zustand?), neue zuerst, vor den Pushes
    checked = enrich(seen, ts, ENRICH_BUDGET.get(args.mode, 0), matcher)
    for e in seen.values():
        if e["last"] == ts:
            e["teuer"] = too_expensive(e)
    new_entries = [e for e in new_entries if not e.get("verkauft") and not e.get("teuer") and not e.get("aussortiert")]
    laeufe = status_store.setdefault("laeufe", [])
    laeufe.append({"zeit": ts, "modus": args.mode, "neu": len(new_entries),
                   "still": sum(1 for e in seen.values() if e["first"] == ts and e.get("still"))})
    del laeufe[:-RUN_HISTORY]

    # Benachrichtigen
    repo = os.environ.get("GITHUB_REPOSITORY")
    if os.environ.get("DASHBOARD_URL"):
        report_url = os.environ["DASHBOARD_URL"].rstrip("/") + "/#eingaenge"
    else:
        report_url = f"https://github.com/{repo}/blob/main/TREFFER.md" if repo else None
    if first_run:
        # Erstlauf: genau EINE Nachricht, alles andere steht in TREFFER.md
        cur = [e for e in seen.values() if e["last"] == ts]
        high = [e for e in cur if is_high(e)]
        lines = [f"• {push_label(e)}: {short(e)}" for e in high[:12]]
        more = f"\n… und {len(high) - 12} weitere" if len(high) > 12 else ""
        push(topic, f"🚀 Tracker gestartet: {len(cur)} Treffer",
             f"Davon {len(high)} Thiago/Sondertrikots:\n" + "\n".join(lines) + more +
             "\nAb jetzt kommen nur noch neue Trikots.",
             3, report_url, None, ["rocket"], args.dry_run)
    else:
        high = sorted([e for e in new_entries if is_high(e)], key=lambda e: e["title"])
        normal = sorted([e for e in new_entries if not is_high(e)], key=lambda e: e["title"])
        # Thiago & Sondertrikots einzeln (max. MAX_PUSH_HIGH), Rest gebündelt
        for e in high[:MAX_PUSH_HIGH]:
            push(topic, f"🔥 {push_label(e)} · {e['shop']}",
                 detail_line(e),
                 5, e["url"], e["image"], ["fire"], args.dry_run)
        bundle = high[MAX_PUSH_HIGH:] + normal
        if len(bundle) == 1:
            e = bundle[0]
            push(topic, f"⚽ {push_label(e)} · {e['shop']}",
                 detail_line(e),
                 3, e["url"], e["image"], ["soccer"], args.dry_run)
        elif bundle:
            push(topic, f"⚽ {len(bundle)} neue Treffer",
                 "\n".join(f"• {push_label(e)}: {short(e, shop=True)}"
                           for e in bundle[:20]) +
                 (f"\n… und {len(bundle) - 20} weitere" if len(bundle) > 20 else ""),
                 3, report_url, None, ["soccer"], args.dry_run)

    # Still übernommene Treffer (neue Shops, neue Kategorien): EINE Sammelnachricht statt Push-Flut
    silent = [e for e in seen.values() if e["first"] == ts and e.get("still")
              and not (e.get("verkauft") or e.get("teuer") or e.get("aussortiert"))]
    if silent and not first_run:
        silent.sort(key=lambda e: (not is_high(e), e["labels"], e["title"]))
        srcs = sorted({e["shop"] for e in silent})
        push(topic, f"🆕 {len(silent)} Treffer aus neuen Shops/Kategorien",
             f"Aus {len(srcs)} Quellen: {', '.join(srcs[:8])}{' …' if len(srcs) > 8 else ''}\n" +
             "\n".join(f"• {push_label(e)}: {short(e, shop=True)}" for e in silent[:15]) +
             (f"\n… und {len(silent) - 15} weitere" if len(silent) > 15 else ""),
             3, report_url, None, ["new"], args.dry_run)

    # Aufräumen: Einträge, die 60 Tage nicht mehr gesehen wurden, vergessen
    old = now() - dt.timedelta(days=60)
    seen = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v["last"]) >= old}

    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if args.mode == "full" and not args.only:
        status_store["known_labels"] = sorted(all_labels)
    elif "known_labels" not in status_store:
        status_store["known_labels"] = sorted(known_labels)
    if args.mode == "drop":
        status_store.setdefault("drop_checks", {}).update({s["name"]: ts for s in shops})
    status_store["sources_ok"] = sorted(sources_ok)
    status_store["last_run"] = {"mode": args.mode, "time": ts}
    run_sources = ([fyj_status] if fyj_status else []) + sorted(statuses, key=lambda s: (not s["fehler"], s["name"]))
    if args.mode == "full" and not args.only:
        status_store["last_full"] = ts
        # Quellen-Status des Gesamtlaufs merken, damit ihn der Schnellcheck nicht überschreibt
        status_store["quellen"] = {"zeit": ts, "liste": run_sources}
    STATUS_FILE.write_text(json.dumps(status_store, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    full_src = status_store.get("quellen") or {}
    if full_src:
        write_report(seen, full_src["liste"], full_src["zeit"], args.mode)
    else:
        write_report(seen, run_sources, "", args.mode)
    write_dashboard(seen, status_store, args.mode, ts, watch, shops_cfg.get("shops") or [])

    ok = sum(1 for s in statuses if not s["fehler"])
    print(f"Fertig ({args.mode}): {ok}/{len(statuses)} Shops ok, FYJ: "
          f"{(fyj_status or {}).get('fehler') or 'ok' if fyj_status else 'aus'}, "
          f"{len(new_entries)} neue Treffer, {checked} Seiten geprüft, Erstlauf: {first_run}")
    for s in statuses:
        if s["fehler"]:
            print(f"  - {s['name']}: {s['fehler']}")


if __name__ == "__main__":
    main()
