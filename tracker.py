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
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
STATUS_FILE = STATE_DIR / "status.json"
REPORT_FILE = ROOT / "TREFFER.md"

TZ = ZoneInfo("Europe/Berlin")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TIMEOUT = 25
DELAY = 1.0              # Pause zwischen zwei Anfragen an denselben Shop
MAX_WORKERS = 8          # so viele Shops parallel
MAX_PUSH = 20            # max. Einzel-Pushes pro Lauf, Rest als Sammelnachricht
REPORT_HOURS = 36        # wie lange ein Treffer ohne Neusichtung in TREFFER.md bleibt

FYJ_API = "https://www.findyourjersey.org/api/jerseys"
FYJ_SIZES = ["XL", "XXL"]


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
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(phrase)) + r"(?![a-z0-9])")


def any_rx(phrases):
    return [word_rx(p) for p in (phrases or []) if norm(p)]


def hit(rxs, text):
    return any(r.search(text) for r in rxs)


SIZE_RX = re.compile(r"(?<![a-z0-9])(xxl|2xl|xl|xx-large|x-large|xx large|x large|extra large)(?![a-z0-9])")
ANY_SIZE_RX = re.compile(r"(?<![a-z0-9])(xxs|xs|s|m|l|xl|xxl|2xl|3xl|xxxl|small|medium|large|"
                         r"x-large|xx-large|\d{2,3}\s?cm|yxl|yl|ym|ys|xlb|lb|mb|sb)(?![a-z0-9])")

VARIANT_WORDS = {
    "home": ["home", "heim", "heimtrikot", "local", "thuis", "domicile", "casa", "1st"],
    "away": ["away", "auswarts", "auswartstrikot", "visitante", "uit", "exterieur", "trasferta", "2nd"],
    "third": ["third", "3rd", "ausweich", "ausweichtrikot", "tercera", "troisieme", "terza"],
}
VARIANT_RX = {k: any_rx(v) for k, v in VARIANT_WORDS.items()}


def season_rxs(season):
    m = re.match(r"^(\d{4})/(\d{2})$", season.strip())
    if not m:
        return []
    s = int(m.group(1))
    e = s + 1
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
            })

    def excluded(self, text):
        return hit(self.exclude, text)

    def size_ok(self, size_text, full_text):
        st = norm(size_text)
        if not SIZE_RX.search(st):
            return False
        return not (hit(self.kids, st) or hit(self.kids, full_text))

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

    def labels(self, text):
        """Gibt [(label, prio)] zurück, ohne Größenprüfung."""
        t = norm(text)
        if not t or self.excluded(t):
            return []
        out = []
        for p in self.players:
            if not hit(p["suche"], t) or hit(p["aus"], t):
                continue
            if p["vereine"] and not hit(p["vereine"], t):
                continue
            out.append((p["name"], p["prio"]))
        for k in self.kits:
            if not hit(k["verein"], t):
                continue
            if (k["saisons"] or k["jahre"]) and not (hit(k["saisons"], t) or hit(k["jahre"], t)):
                continue
            if not self._variant_ok(k, t):
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
class Http:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
        self.last = 0.0
        self.count = 0

    def get(self, url, params=None, want="json"):
        for attempt in range(3):
            wait = DELAY - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.count += 1
            try:
                r = self.s.get(url, params=params, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(3)
                continue
            if r.status_code == 429:
                time.sleep(15 * (attempt + 1))
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


def item(source, shop, url, title, size_text, price="", image="", extra=""):
    return {"source": source, "shop": shop, "url": url, "title": title.strip(),
            "size_text": size_text or "", "price": price, "image": image or "",
            "match_text": f"{title} {extra}".strip()}


# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------
SIZE_ATTR_RX = re.compile(r"size|grosse|groesse|taille|talla|maat|rozmiar|storrelse|koko|tamanho|taglia")


def shopify_to_item(shop, base, p, cents=False):
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
    return item("direkt", shop, url, title, size_text, str(price or ""), img)


def shopify_full(http, shop, base):
    items, n = [], 0
    for page in range(1, 41):
        data = http.get(f"{base}/products.json", {"limit": 250, "page": page})
        prods = (data or {}).get("products") or []
        if not prods:
            break
        n += len(prods)
        for p in prods:
            it = shopify_to_item(shop, base, p)
            if it:
                items.append(it)
        if len(prods) < 250:
            break
    return items, n


def shopify_search(http, shop, base, queries, matcher):
    items, n, handles = [], 0, set()
    for q in queries:
        data = http.get(f"{base}/search/suggest.json", {
            "q": q, "resources[type]": "product", "resources[limit]": 10,
            "resources[options][unavailable_products]": "hide"})
        prods = (((data or {}).get("resources") or {}).get("results") or {}).get("products") or []
        n += len(prods)
        for p in prods:
            h = p.get("handle") or urlparse(p.get("url", "")).path.rstrip("/").split("/")[-1]
            if not h or h in handles or not matcher.labels(p.get("title", "")):
                continue
            handles.add(h)
            full = http.get(f"{base}/products/{h}.js")
            if full:
                it = shopify_to_item(shop, base, full, cents=True)
                if it:
                    items.append(it)
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
    return item("direkt", shop, p.get("permalink") or "", title, size_text, price.strip(), img)


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


def fyj_run(http, matcher, priority):
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
                    if r.get("isReissue"):
                        title += " (Reissue)"
                    extra = " ".join(str(x) for x in (r.get("player"), r.get("team")) if x)
                    price = f"{r.get('currentValue') or ''} {r.get('currency') or ''}".strip()
                    items.append(item("fyj", r.get("sourceType") or "FYJ", r.get("sourceUrl") or "",
                                      title, r.get("size") or "", price, r.get("imageUrl"), extra))
                if len(rows) < 200:
                    break
    return items, n


def run_shop(shop, mode, matcher, platforms):
    name, base = shop["name"], shop["url"].rstrip("/")
    plat = (shop.get("plattform") or "auto").lower()
    http = Http()
    t0 = time.time()
    status = {"name": name, "plattform": plat, "produkte": 0, "treffer_roh": 0, "fehler": ""}
    try:
        if plat == "aus":
            status["fehler"] = "deaktiviert"
            return [], status
        if plat == "cfs":
            qs = matcher.queries(only_high=(mode == "priority"))
            items, n = cfs_run(http, name, base, qs)
            status.update(plattform="cfs", produkte=n)
            return items, status
        if plat == "auto":
            known = platforms.get(base)
            if mode == "full" or not known:
                data = http.get(f"{base}/products.json", {"limit": 1})
                if isinstance(data, dict) and "products" in data:
                    known = "shopify"
                else:
                    ep = woo_endpoint(http, base)
                    known = ("woo:" + ep) if ep else "unbekannt"
                platforms[base] = known
            plat = known
        status["plattform"] = plat.split(":")[0]
        if plat == "shopify":
            items, n = (shopify_full(http, name, base) if mode == "full"
                        else shopify_search(http, name, base, matcher.queries(True), matcher))
        elif plat.startswith("woo:"):
            ep = plat[4:]
            items, n = woo_run(http, name, ep, None if mode == "full" else matcher.queries(True))
        else:
            status["fehler"] = "Shopsystem nicht automatisch erkannt"
            return [], status
        status["produkte"] = n
        if n == 0 and mode == "full":
            status["fehler"] = "keine Produkte erhalten"
        return items, status
    except Exception as e:  # ein kaputter Shop soll nie den ganzen Lauf stoppen
        status["fehler"] = f"{type(e).__name__}: {str(e)[:120]}"
        return [], status
    finally:
        status["sekunden"] = round(time.time() - t0, 1)
        status["anfragen"] = http.count


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


def push_label(entry):
    return ", ".join(entry["labels"])


def is_high(entry):
    return "hoch" in entry.get("prios", [])


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------
def write_report(seen, statuses, mode, fyj_status):
    cutoff = now() - dt.timedelta(hours=REPORT_HOURS)
    current = [e for e in seen.values()
               if dt.datetime.fromisoformat(e["last"]) >= cutoff]
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
        lines += [f"## {lab} ({len(es)})", "", "| Trikot | Größe | Preis | Shop | seit |",
                  "|---|---|---|---|---|"]
        for e in es:
            t = e["title"].replace("|", "/")
            size = (e.get("size") or "").replace("|", "/")[:25]
            first = dt.datetime.fromisoformat(e["first"]).astimezone(TZ)
            lines.append(f"| [{t}]({e['url']}) | {size} | {e.get('price', '')} | {e['shop']} | {first:%d.%m.} |")
        lines.append("")
    lines += ["## Quellen-Status", "", "| Quelle | System | Produkte | Anfragen | Hinweis |", "|---|---|---|---|---|"]
    for s in ([fyj_status] if fyj_status else []) + sorted(statuses, key=lambda s: (not s["fehler"], s["name"])):
        lines.append(f"| {s['name']} | {s.get('plattform', '')} | {s.get('produkte', 0)} | "
                     f"{s.get('anfragen', '')} | {s.get('fehler') or 'ok'} |")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "priority", "test"], default="full")
    ap.add_argument("--dry-run", action="store_true", help="nichts senden, nur ausgeben")
    ap.add_argument("--only", help="nur Shops, deren Name diesen Text enthält (zum Testen)")
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
    platforms = status_store.setdefault("platforms", {})
    sources_ok = set(status_store.setdefault("sources_ok", []))
    first_run = not seen

    shops = shops_cfg.get("shops") or []
    if args.only:
        shops = [s for s in shops if args.only.lower() in s["name"].lower()]
    use_fyj = str(shops_cfg.get("fyj", "an")).lower() in ("an", "true", "ja", "on") and not args.only

    lock = threading.Lock()
    results, statuses, fyj_status = [], [], None
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_shop, s, args.mode, matcher, platforms): s for s in shops}
        fyj_fut = None
        if use_fyj:
            def fyj_job():
                http = Http()
                t0 = time.time()
                st = {"name": "FindYourJersey", "plattform": "fyj", "produkte": 0, "fehler": ""}
                try:
                    its, n = fyj_run(http, matcher, args.mode == "priority")
                    st["produkte"] = n
                    if n == 0 and args.mode == "full":
                        st["fehler"] = "keine Daten erhalten (Schnittstelle geändert oder gesperrt?)"
                    return its, st
                except Exception as e:
                    st["fehler"] = f"{type(e).__name__}: {str(e)[:120]}"
                    return [], st
                finally:
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
    new_entries, silent_sources = [], []
    for src_name, its, st in results:
        works = args.mode == "full" and st.get("produkte", 0) > 0 and not st.get("fehler")
        fresh_source = works and src_name not in sources_ok
        if works:
            sources_ok.add(src_name)
        if fresh_source and not first_run:
            silent_sources.append(src_name)
        for it in its:
            labs = matcher.labels(it["match_text"])
            if not labs or not matcher.size_ok(it["size_text"], norm(it["match_text"])):
                continue
            if not it["url"]:
                continue
            key = canon_url(it["url"])
            size = SIZE_RX.search(norm(it["size_text"]))
            entry = seen.get(key)
            if entry:
                entry["last"] = ts
                entry["labels"] = sorted(set(entry["labels"]) | {l for l, _ in labs})
                entry["prios"] = sorted(set(entry.get("prios", [])) | {p for _, p in labs})
                if it["source"] == "direkt":      # direkte Daten sind aktueller als FYJ
                    entry.update(price=it["price"] or entry.get("price", ""), shop=it["shop"])
                continue
            entry = {"title": it["title"], "url": it["url"], "shop": it["shop"],
                     "price": it["price"], "image": it["image"],
                     "size": size.group(0).upper() if size else "",
                     "labels": sorted({l for l, _ in labs}), "prios": sorted({p for _, p in labs}),
                     "first": ts, "last": ts, "via": it["source"]}
            seen[key] = entry
            if not first_run and not fresh_source:
                new_entries.append(entry)

    # Benachrichtigen
    repo = os.environ.get("GITHUB_REPOSITORY")
    report_url = f"https://github.com/{repo}/blob/main/TREFFER.md" if repo else None
    if first_run:
        cur = [e for e in seen.values() if e["last"] == ts]
        high = [e for e in cur if is_high(e)]
        for e in sorted(high, key=lambda e: e["first"])[:15]:
            push(topic, f"🔥 {push_label(e)} · {e['shop']}",
                 f"{e['title']}\nGröße {e['size']} · {e['price']}", 4, e["url"], e["image"],
                 ["fire"], args.dry_run)
        push(topic, "🚀 Trikot-Tracker gestartet",
             f"Erstlauf: {len(cur)} Treffer in XL/XXL, davon {len(high)} mit hoher Priorität. "
             "Ab jetzt kommen nur noch neue Trikots.", 3, report_url, None, ["rocket"], args.dry_run)
    else:
        new_entries.sort(key=lambda e: (not is_high(e), e["title"]))
        for e in new_entries[:MAX_PUSH]:
            high = is_high(e)
            push(topic, f"{'🔥' if high else '⚽'} {push_label(e)} · {e['shop']}",
                 f"{e['title']}\nGröße {e['size']} · {e['price']}",
                 5 if high else 3, e["url"], e["image"], ["fire" if high else "soccer"], args.dry_run)
        rest = new_entries[MAX_PUSH:]
        if rest:
            push(topic, f"➕ {len(rest)} weitere neue Treffer",
                 "\n".join(f"• {push_label(e)}: {e['title']}" for e in rest[:25]),
                 3, report_url, None, ["heavy_plus_sign"], args.dry_run)
        if silent_sources and args.mode == "full":
            push(topic, "ℹ️ Neue Quellen eingebunden",
                 f"Erstmals erfolgreich abgefragt: {', '.join(silent_sources)}. "
                 "Deren aktueller Bestand steht ohne Einzel-Push in TREFFER.md.",
                 2, report_url, None, ["information_source"], args.dry_run)

    # Aufräumen: Einträge, die 60 Tage nicht mehr gesehen wurden, vergessen
    old = now() - dt.timedelta(days=60)
    seen = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v["last"]) >= old}

    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    status_store["sources_ok"] = sorted(sources_ok)
    status_store["last_run"] = {"mode": args.mode, "time": ts}
    if args.mode == "full":
        status_store["last_full"] = ts
    STATUS_FILE.write_text(json.dumps(status_store, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    write_report(seen, statuses, args.mode, fyj_status)

    ok = sum(1 for s in statuses if not s["fehler"])
    print(f"Fertig ({args.mode}): {ok}/{len(statuses)} Shops ok, FYJ: "
          f"{(fyj_status or {}).get('fehler') or 'ok' if fyj_status else 'aus'}, "
          f"{len(new_entries)} neue Treffer, Erstlauf: {first_run}")
    for s in statuses:
        if s["fehler"]:
            print(f"  - {s['name']}: {s['fehler']}")


if __name__ == "__main__":
    main()
