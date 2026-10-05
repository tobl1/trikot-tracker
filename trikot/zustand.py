"""Zustand (8/10, BNWT ...), Verfügbarkeit und Beschreibung aus Produktseiten"""

import re

from .basis import NOTE_LEN, norm, plain


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


# Beschreibung verrät Training oder Hose, obwohl der Titel nichts sagt (VFA: "2009/10 - Barcelone (XL)" mit
# "Maillot d'entrainement porté par …" bzw. "Le short en détail"; Meldungen vom 05.10.2026)
DESC_TRAINING_RX = re.compile(r"(?<![a-z])(maillot d entrainement|maillot entrainement|maillot d entrainements|"
                              r"training shirt|training top|training jersey|trainingsshirt|trainingstrikot|"
                              r"camiseta de entrenamiento|camiseta entrenamiento|maglia da allenamento|"
                              r"maglia allenamento|koszulka treningowa)(?![a-z])")
DESC_SHORTS_RX = re.compile(r"(?<![a-z])(le short en detail|short domicile|short exterieur|short en excellent|"
                            r"pantalon corto|pantalones cortos|pantaloncino|pantaloncini)(?![a-z])")


def desc_excluded(desc, title=""):
    """Grund, warum die Beschreibung den Artikel ausschließt (Training, Hose, kein Trikot), sonst "" """
    t = norm(plain(desc))
    if not t:
        return ""
    if DESC_TRAINING_RX.search(t):
        return "Beschreibung: Trainingsshirt"
    if DESC_SHORTS_RX.search(t):
        return "Beschreibung: Hose"
    if desc_not_jersey(desc, title):
        return "Beschreibung: kein Trikot (T-Shirt/Jacke)"
    return ""


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
