"""Those Days (thosedays.com): Marktplatz für Sammler aus Europa, Echtheit laut Seite von Those Days geprüft.

Die Seite baut alles per Skript auf (im HTML stehen keine Angebote, die Adressen nennen weder Größe noch Flock). Deshalb
wie ein normaler Besucher mit einem unsichtbaren Browser (Playwright, Chromium): Übersicht mit Filter XL/XXL, neueste
zuerst, nach unten scrollen, bis alles geladen ist (24 Karten je Nachladen), Karten ablesen. Bilder, Schriften und Videos
werden nicht geladen (weniger Last für die Seite). robots.txt erlaubt alles. Die interne Datenschnittstelle der Seite wird
bewusst nicht benutzt (Recherche 19. und 24.11.2026, siehe CLAUDE.md)

Gesamt-Run: alles (24.11.2026: 1.684 Trikots in XL/XXL, ca. 70 Nachladungen). Schnell-Run: nur die neuesten (MAX_FAST).
Drop-Run und Radar: nicht (Browserstart zu teuer für alle 15 Minuten)"""

import re

from .gemeinsam import item

LISTE = "/browse?size=XL,XXL&sort=newest"
MAX_FULL = 120        # Nachladungen im Gesamt-Run (je 24 Karten), Sicherung gegen Endlosschleifen
MAX_FAST = 4          # Schnell-Run: ca. 100 neueste
PAUSE_MS = 1500       # zwischen zwei Nachladungen

# Karte: <a href="/listing/…"> mit Bild-Block und Text-Block: <p>Titel</p> <div><span>Größe</span><span>Zustand</span></div>
# <p><span>€159</span><span>.99</span></p>, reduziert <div><p><span>€75</span><span>.96</span></p><span>€94.95</span><span>-20%</span></div>
CARDS_JS = """() => [...document.querySelectorAll('a[href*="/listing/"]')].map(a => {
  const info = a.lastElementChild || a;
  const ps = info.querySelectorAll(':scope > p');
  const tagDiv = info.querySelector(':scope > div');
  const tags = tagDiv ? [...tagDiv.querySelectorAll('span')].map(s => s.innerText.trim()) : [];
  // Preis: alle übrigen Spans in Reihenfolge (reduziert steckt er eine Ebene tiefer: <div><p>€75 .96</p> €94.95 -20%</div>)
  const prices = [...info.querySelectorAll('span')].filter(s => !(tagDiv && tagDiv.contains(s))).map(s => s.innerText.trim());
  const img = a.querySelector('img');
  return {href: a.href, title: ps[0] ? ps[0].innerText.trim() : '', tags, prices, img: img ? (img.currentSrc || img.src || '') : ''};
})"""


def card_price(prices):
    """['€159', '.96', '€199.95', '-20%'] -> '159.96 EUR' (aktueller Preis, nicht der durchgestrichene)"""
    if not prices:
        return ""
    first = prices[0]
    if len(prices) > 1 and re.fullmatch(r"[.,]\d{1,2}", prices[1]):
        first += prices[1].replace(",", ".")
    m = re.search(r"\d[\d.,]*", first)
    return f"{m.group(0).replace(',', '')} EUR" if m and "€" in first else first


def card_item(shop, c):
    """Karte -> Artikel. tags: [Größe, Zustand]"""
    if not c.get("href") or not c.get("title"):
        return None
    size = c["tags"][0] if c.get("tags") else ""
    cond = c["tags"][1].title() if len(c.get("tags") or []) > 1 else ""
    title = re.sub(r"\s*#TD-\d+\s*$", "", c["title"])           # interne Nummer "#TD-10575" weg
    title = re.sub(r"\[\s*(#?\d{1,2})\s+([^\]]+)\]", r"\2 \1", title)   # "[#10 TOTTI]" -> "TOTTI #10" (Flock)
    img = c.get("img") if str(c.get("img") or "").startswith("https://") else ""
    return item("direkt", shop, c["href"].split("?")[0], title, size, card_price(c.get("prices")), img,
                desc=f"Condition: {cond}" if cond else "", fyj_condition=cond)


def thosedays_run(shop, base, mode):
    """Gibt (Artikel, Zahl der Karten) zurück. Ohne installierten Browser: RuntimeError (der Run läuft weiter)"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Browser (Playwright) nicht installiert") from e
    loads = MAX_FULL if mode == "full" else MAX_FAST
    cards = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(locale="de-DE")
            page.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "font", "media") else r.continue_())
            page.goto(base + LISTE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('a[href*="/listing/"]', timeout=45000)
            text = page.inner_text("body")
            m = re.search(r"(\d[\d,.]*)\s+shirts", text, re.I)
            total = int(re.sub(r"[,.]", "", m.group(1))) if m else 0
            n, still = 0, 0
            for _ in range(loads):
                n_now = page.locator('a[href*="/listing/"]').count()
                if total and n_now >= total:
                    break
                still = still + 1 if n_now == n else 0
                if still >= 3:          # dreimal nichts nachgekommen: Ende
                    break
                n = n_now
                page.mouse.wheel(0, 20000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(PAUSE_MS)
            cards = page.evaluate(CARDS_JS)
        finally:
            browser.close()
    seen, items = set(), []
    for c in cards:
        it = card_item(shop, c)
        if it and it["url"] not in seen:
            seen.add(it["url"])
            items.append(it)
    return items, len(cards)
