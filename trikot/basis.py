"""Grundlagen: Konstanten, Text-Normalisierung, Größen- und Saison-Erkennung, kleine Helfer"""

import datetime as dt
import html
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent   # Projektordner (trikot/ liegt darin)
ERROR_KEEP_DAYS = 30
FUNDGRUBE_DAYS = 7            # so oft (Tage) die Fundgrube im Gesamt-Run auswerten
FUNDGRUBE_MAX = 15            # höchstens so viele Kandidaten prüfen
FUNDGRUBE_MAX_REISSUE = 15    # ab so viel Prozent Nachbauten (laut FYJ) nicht empfehlen
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
ENRICH_BUDGET = {"full": 400, "priority": 25, "drop": 25}   # max. Seitenprüfungen pro Lauf
NOTE_LEN = 160               # Länge der Zustandsnotiz
FALLBACK_SKIP_HOURS = {"full": 20, "priority": 5.5}   # GitHub-Zeitplan überspringt, wenn schon gelaufen (Schnell-Runs alle 6 h)
RUN_HISTORY = 400            # so viele Läufe merken (Eingangsverlauf; mit Radar ca. 30 Runs am Tag)
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
RADAR_MIN = 25               # Neuheiten-Radar höchstens so oft (Minuten); cron-job.org startet alle 15 Min.
RADAR_LIMIT = 40             # so viele neueste Artikel pro Shop und Radar-Abruf (Seite)
# Schlüssel, mit dem cron-job.org die Runs startet (GitHub, fein-granular, 1 Jahr gültig, angelegt ca. 04.10.2026).
# Ab 30 Tage vorher steht im Fehler-Log eine Erinnerung; nach dem Erneuern hier das neue Ablaufdatum eintragen
CRON_TOKEN_ABLAUF = "2027-10-04"
EINBRUCH_MIN = 100           # Bestandseinbruch erst ab so vielen Produkten beim letzten Gesamt-Run prüfen
EINBRUCH_ANTEIL = 0.5        # unter diesem Anteil des letzten Bestands gilt es als Einbruch
EINBRUCH_RUNS = 3            # so viele Gesamt-Runs in Folge, dann ist der kleinere Bestand echt


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
XXL_WORDS = {"xxl", "2xl", "xx-large", "xx large"}


def short_size(text):
    """Größe einheitlich kurz: "X-LARGE"/"Extra Large" -> XL, "2XL"/"XX-Large" -> XXL (Dashboard, Filter, Dubletten)"""
    m = SIZE_RX.search(norm(text or ""))
    if not m:
        return text or ""
    return "XXL" if m.group(1) in XXL_WORDS else "XL"


ANY_SIZE_RX = re.compile(r"(?<![a-z0-9])(xxs|xs|s|m|l|xl|xxl|2xl|3xl|xxxl|small|medium|large|"
                         r"x-large|xx-large|\d{2,3}\s?cm|yxl|yl|ym|ys|xlb|lb|mb|sb)(?![a-z0-9])")
# Sternchen-Wörter wie "*WINFIELD*" (classic-shirts) sind Beflockungen, außer diese Zusätze
STAR_RX = re.compile(r"\*([^*]{2,40})\*")
STAR_TAGS = re.compile(r"(?i)^(bnwt|bnib|bnwot|bnip|w/ ?tags|with tags|mint|new|rare|signed|autographed|player issue|"
                       r"match worn|match issue|sample|prototype|ls|l/s|long ?sleeve|basic|retro|vintage|university|"
                       r"academy|academie|training|staff)$")
# Rückennummer im Titel: "#10", "# 10", "No. 10", "Nr 10", "Number 10"
FLOCK_NUM_RX = re.compile(r"#\s?\d{1,2}(?!\d)|(?<![a-z0-9])(no|nr|num|number)\.?\s?\d{1,2}(?![\d/])"
                          r"|(?<![a-z0-9])n\s\d{1,2}(?![\d/])")   # "N°7" wird normalisiert zu "n 7"
VARIANT_WORDS = {
    "home": ["home", "heim", "heimtrikot", "local", "thuis", "domicile", "casa", "1st"],
    "away": ["away", "auswarts", "auswartstrikot", "visitante", "uit", "exterieur", "trasferta", "2nd"],
    "third": ["third", "3rd", "ausweich", "ausweichtrikot", "drittes", "dritte", "tercera", "troisieme", "terza", "derde"],
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


def domain(url):
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def plain(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    return re.sub(r"\s+", " ", text).strip()


def is_high(entry):
    return "hoch" in entry.get("prios", [])
