"""Titel-Testfälle für das Matching. Ausführen: python -m pytest tests/"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tracker  # noqa: E402

M = tracker.Matcher(yaml.safe_load((ROOT / "watchlist.yaml").read_text(encoding="utf-8")))


def labels(text):
    return {l for l, _ in M.labels(text)}


def size_ok(title, size_text=None):
    return M.size_ok(size_text if size_text is not None else title, tracker.norm(title))


# (Titel, erwartete Labels; leere Menge = kein Treffer)
CASES = [
    # Spieler
    ("2013-14 Bayern Munich Away Shirt Thiago #6 (XL)", {"Thiago"}),
    ("2017-18 Bayern Munich Home Shirt Alcantara #6 XL", {"Thiago"}),
    ("2014-15 PSG Home Shirt Thiago Silva #2 (XL)", set()),
    ("2011-12 Inter Home Shirt Thiago Motta (XL)", set()),
    ("2021-22 Liverpool Home Shirt Thiago #6 (XL)", {"Thiago"}),
    ("2008-09 Liverpool Home Shirt Torres #9 (XL)", {"Torres (Fernando)"}),
    ("2007-08 Atletico Madrid Home Shirt F. Torres #9 XL", {"Torres (Fernando)"}),
    ("2010-11 Chelsea Home Shirt Torres #9 (XL)", set()),
    ("2021-22 Barcelona Away Shirt Ferran Torres XL", set()),
    ("2016-17 Liverpool Home Shirt Ferran Torres XL", set()),
    ("2005-06 Liverpool Away Shirt Alonso #14 (XXL)", {"Alonso (Xabi)"}),
    ("2018-19 Chelsea Home Shirt Marcos Alonso #3 (XL)", set()),
    ("2019-20 Real Madrid Home Shirt Marcos Alonso XL", set()),
    ("2008-09 Hamburger SV Home Shirt Olic #11 (XL)", {"Olić", "HSV 1990-2016"}),
    ("2009-10 HSV Home Shirt Olić #11 XL", {"Olić", "HSV 1990-2016"}),
    ("2010-11 Wolfsburg Home Shirt Olic XL", set()),
    ("2003-04 Arsenal Home Shirt Henry #14 (XL)", {"Henry"}),
    ("2008-09 Barcelona Home Shirt Henry #14 (XL)", set()),
    ("2010-11 Bayern Munich Home Shirt Robben #10 (XL)", {"Robben"}),
    ("2006-07 Chelsea Home Shirt Robben #16 (XL)", set()),
    ("2004-05 Lyon Home Shirt Juninho #8 (XL)", {"Juninho (Pernambucano)"}),
    ("2023-24 Man City Home Shirt Rodri #16 (XL)", {"Rodri"}),
    ("2023-24 Man City Home Shirt Rodrigo #16 (XL)", set()),
    ("2018-19 Spain Adidas Home Shirt #Thiago10 BNWT Size XL", {"Thiago"}),   # Name und Nummer zusammen
    ("2019-20 Ajax Home Shirt De Jong #21 (XL)", {"Frenkie de Jong"}),
    ("2014-15 Feyenoord Home Shirt Luuk de Jong (XL)", set()),
    ("2010-11 PSV Home Shirt Van der Vaart XL", {"Van der Vaart"}),
    # Sondertrikots
    ("2011-12 Barcelona Home Shirt (XL)", {"Barça 2008-2013"}),
    ("Barcelona 2010/2011 Away Shirt XL", {"Barça 2008-2013"}),
    ("2009-10 Barcelona Home Shirt (XL)", {"Barça 2008-2013"}),
    ("2021-22 Bayern Munich Oktoberfest Shirt (XL)", {"Bayern Wiesn 2021/22 (grün)"}),
    ("2021-22 Bayern Munich Green Fourth Shirt XL", {"Bayern Wiesn 2021/22 (grün)"}),
    ("2021-22 Bayern Munich Third Shirt XL", set()),
    ("2023-24 Bayern Munich Oktoberfest Shirt green (XL)", set()),
    ("2021-22 1860 Munchen Wiesn Trikot XL", set()),
    ("2021-22 Liverpool Away Shirt (XL)", {"Liverpool Away 2021/22"}),
    ("2021-22 Liverpool Shirt (XL)", set()),
    ("2022-23 Liverpool Third Shirt (XXL)", {"Liverpool Third 2022/23"}),
    ("2022-23 Liverpool Away Shirt (XXL)", set()),
    ("2010-11 Spain Home Shirt (XL)", {"Spanien 2010/2011"}),
    ("2014-15 Spain Away Shirt XL", {"Spanien 2014"}),
    ("2014-15 Spain Third Shirt XL", set()),
    # Produkt-Ausschlüsse
    ("2011-12 Barcelona Training Shirt (XL)", set()),
    ("2011-12 Barcelona Home Shorts (XL)", set()),
    ("2012-13 Barcelona Home Short Sleeve Shirt (XL)", {"Barça 2008-2013"}),
    # Neu (01.10.2026): Trainingsshirts in anderen Sprachen
    ("Spain 2014 Camisa de Treino Tam GG", set()),
    ("Barcelona 2011-12 Camiseta de Entrenamiento XL", set()),
    ("Barcelona 2011/12 Maglia Allenamento XL", set()),
    # Neu (01.10.2026): Sondertrikots nur ohne Flock oder mit Thiago-Flock
    ("2012/13 Barcelona Home Football Shirt (XL) Nike #10 Messi", set()),
    ("Barcelona 2011-2012 HOME 6 XAVI (XL)", set()),
    ("2010-11 Barcelona Away Shirt Villa #7 (XL)", set()),
    ("2010 Spain World Cup Home Shirt Torres #9 XL", set()),
    ("2021-22 Liverpool Away Shirt Salah #11 (XL)", set()),
    ("2012-13 Barcelona Home Shirt Thiago #11 (XL)", {"Thiago", "Barça 2008-2013"}),
    ("2010-11 Spain Home Shirt Alonso #14 (XL)", {"Alonso (Xabi)"}),
    ("2021-22 Liverpool Away Shirt Thiago #6 (XL)", {"Thiago", "Liverpool Away 2021/22"}),
    # Neu (01.10.2026): niederländische Titel (The Football Temple) und andere Sprachen
    ("Spanje 2010 Thuis Shirt (XL)", {"Spanien 2010/2011"}),
    ("Spanje 2014 Uit Shirt (XXL)", {"Spanien 2014"}),
    ("Spanje 2010 Thuis Shirt Iniesta #6 (XL)", set()),
    ("Spanje 2014 Thuis Shirt Thiago #6 (XL)", {"Thiago", "Spanien 2014"}),
    ("Barcelona 2012/2013 Uit Shirt (XL)", {"Barça 2008-2013"}),
    ("Barcelona 2012/2013 Uit Shirt Messi #10 (XL)", set()),
    ("Liverpool 2022/2023 Derde Shirt (XL)", {"Liverpool Third 2022/23"}),
    ("Liverpool 2022/2023 Uit Shirt (XL)", set()),
    ("Spanje 2010 Keeper Shirt Casillas (XL)", set()),
    ("Nederland 2018 Thuis Shirt De Jong #21 (XL)", {"Frenkie de Jong"}),
    ("Kroatië 2008 Thuis Shirt Olic #18 (XL)", {"Olić"}),
    ("Maillot Espagne 2010 Domicile XL", {"Spanien 2010/2011"}),
    ("Koszulka Hiszpania 2014 XL", {"Spanien 2014"}),
    ("2011-12 Barcelona Home Shirt Reissue (XL)", set()),
    ("Spain 2010 Home Remake Shirt XL", set()),
    ("2005-06 Liverpool Away Replica Shirt Alonso #14 (XL)", {"Alonso (Xabi)"}),
    # Neu (02.10.2026)
    ("2011-12 Barcelona SC Home Shirt - 5/10 - (XL)", set()),
    ("Barcelona S.C. 2012 Home Shirt XL", set()),
    ("1998/99 FC Barcelona Home Name Set Rivaldo #11 (Repro)", set()),
    ("1996/97 Chelsea Retro Home Shirt FA Cup Final (XL) Score Draw", set()),
    ("2012-13 Barcelona Home Shirt Thiago #11 with official name set (XL)", {"Thiago", "Barça 2008-2013"}),
    # Neu (04.10.2026): Repro-Flock nur für Thiago, sonst bleiben Nachbauten draußen
    ("2013-14 Bayern Munich Home Shirt Thiago #6 (XL) Repro Flock", {"Thiago"}),
    ("Maillot Barcelone 2012-2013 HOME 11 THIAGO flocage reproduction récente XL", {"Thiago", "Barça 2008-2013"}),
    ("2013-14 Bayern Munich Home Shirt Ribery #7 (XL) Repro Flock", set()),
    ("2015-16 Bayern Munich Thiago #6 Reissue (XL)", set()),
    ("1998/99 FC Barcelona Home Name Set Thiago #11 (Repro)", set()),
]


@pytest.mark.parametrize("title,expected", CASES)
def test_labels(title, expected):
    assert labels(title) == expected


@pytest.mark.parametrize("title,ok", [
    ("Shirt (XL)", True), ("Shirt (XXL)", True), ("Shirt 2XL", True), ("Shirt X-Large", True),
    ("Shirt XX-Large", True), ("Shirt Extra Large", True),
    ("Shirt (L)", False), ("Shirt 3XL", False), ("Shirt XXXL", False),
    ("Shirt Boys XL", False), ("Shirt YXL", False), ("Shirt XL enfant", False), ("Womens XL", False),
    # Neu (01.10.2026)
    ("LIVERPOOL #6 THIAGO 2020-2021 FOOTBALL SHIRT JERSEY THIRD NIKE ORIGINAL YOUNG XL", False),
    ("Koszulka damska Liverpool FC 2021/22 Away [XL]", False),
    ("Camisa Barcelona 2011 Feminina GG XL", False),
    ("Netherlands 2004/2005/2006 Away Football Shirt Childs XL", False),
    ("2004/06 - Pays-Bas (16 ans) XL", False),
])
def test_size(title, ok):
    assert size_ok(title) == ok


@pytest.mark.parametrize("title,desc,fallback,grade", [
    ("2006-07 Liverpool Away Shirt Alonso #14 - 6/10 - (XXL)", "", "", "6/10"),
    ("2013-14 Bayern Thiago XL", "CONDITION: 8/10 DESCRIPTION: SLIGHTY USED PRINTONGS", "Good", "8/10"),
    ("2010-11 Bayern Home XL", "Condition - 9,5/10 no flaws", "", "9.5/10"),
    ("2009/10 Barcelona Home Shirt XL", "<p>Condition: Excellent, small mark</p>", "Good", "Excellent"),
    ("2018-19 Spain Home Shirt #Thiago10 BNWT Size XL", "", "Excellent", "BNWT"),
    ("09/10 Barcelona Away", "", "Very Good", "Very Good"),      # Saison ist keine Note
    ("2010/11 Barcelona Home", "", "", ""),
])
def test_condition(title, desc, fallback, grade):
    assert tracker.condition_info(title, desc, fallback)[0] == grade


def _stamps(days_back, hour, count, spacing_min=2):
    base = tracker.now().astimezone(tracker.TZ).replace(hour=hour, minute=0, second=0, microsecond=0)
    return [(base - tracker.dt.timedelta(days=days_back) + tracker.dt.timedelta(minutes=i * spacing_min)).isoformat()
            for i in range(count)]


def test_rhythm_drops():
    stamps = [x for k in range(1, 85, 14) for x in _stamps(k, 18, 20)]
    r = tracker.rhythm(stamps)
    assert r["typ"] == "drops" and r["abstand_tage"] == 14 and r["uhrzeit"] == 18


def test_rhythm_laufend():
    stamps = [x for k in range(1, 60) for x in _stamps(k, 9 + k % 8, 2, spacing_min=240)]
    r = tracker.rhythm(stamps)
    assert r["typ"] == "laufend" and r["tage_30"] >= 28


def test_rhythm_ruhig():
    assert tracker.rhythm(_stamps(45, 12, 3))["typ"] == "ruhig"


def test_rhythm_taegliche_schuebe_sind_laufend():
    stamps = [x for k in range(1, 60) for x in _stamps(k, 10, 12)]
    assert tracker.rhythm(stamps)["typ"] == "laufend"


def test_condition_niederlaendisch():
    body = "Maat: XL<br>Seizoen: 2010<br>Stijl: Thuis Shirt<br>Merk: Nike<br>Staat van het shirt: 8/10"
    grade, note = tracker.condition_info("Spanje 2010 Thuis Shirt (XL)", body)
    assert grade == "8/10" and note.startswith("Staat van het shirt")


@pytest.mark.parametrize("typ,excluded", [
    ("Tracktop", True), ("Track jacket", True), ("Reissue", True), ("Goal Keeper", True),
    ("Shirt - Training", True), ("Vintage Football Scarf", True),
    ("Maillot", False), ("Football shirt", False), ("Shirt - Home", False), ("Jersey", False),
    ("Liverpool Shirts", False),
])
def test_product_type_exclusion(typ, excluded):
    assert M.type_excluded(typ) == excluded


def _berlin(y, mo, d, h, mi):
    return tracker.dt.datetime(y, mo, d, h, mi, tzinfo=tracker.TZ).astimezone(tracker.dt.timezone.utc)


def test_drop_due_fest():
    shop = {"name": "First 11 Shirts", "drop": ["Fr 19:00"]}
    # 02.10.2026 ist ein Freitag
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 2, 18, 50)) is None
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 2, 19, 5))
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 2, 21, 55))
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 2, 22, 5)) is None
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 3, 19, 5)) is None


def test_drop_due_gemessen_und_abstand():
    st = {"quellen": {"liste": [{"name": "Kickoff Vintage", "rhythmus": {
        "typ": "drops", "wochentag": "Do", "uhrzeit": 16, "anteil": 1.0}}]}}
    shop = {"name": "Kickoff Vintage"}
    t = _berlin(2026, 10, 1, 16, 20)
    assert tracker.drop_due(shop, st, t)
    st["drop_checks"] = {"Kickoff Vintage": (t - tracker.dt.timedelta(minutes=10)).isoformat()}
    assert tracker.drop_due(shop, st, t) is None        # gerade erst geprüft
    st["quellen"]["liste"][0]["rhythmus"]["anteil"] = 0.3
    st["drop_checks"] = {}
    assert tracker.drop_due(shop, st, t) is None        # Wochentag zu unsicher


@pytest.mark.parametrize("grade,minimum,below", [
    ("6/10", 7, True), ("5/10", 7, True), ("7/10", 7, False), ("9.5/10", 7, False),
    ("BNWT", 7, False), ("", 7, False), ("6/10", None, False),
])
def test_below_min(grade, minimum, below):
    assert tracker.below_min(grade, minimum) == below


def _drop_stamps(weeks, weekday, hhmm_list, count=12):
    """je Woche ein Schub am gegebenen Wochentag; hhmm_list[i] = Uhrzeit in Woche i (älteste zuerst)"""
    today = tracker.now().astimezone(tracker.TZ)
    out = []
    for i in range(weeks):
        back = (weeks - i) * 7 - ((weekday - today.weekday()) % 7)
        h, m = hhmm_list[i]
        base = (today - tracker.dt.timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
        out += [(base + tracker.dt.timedelta(minutes=2 * k)).isoformat() for k in range(count)]
    return out


def test_rhythm_genaue_uhrzeit():
    r = tracker.rhythm(_drop_stamps(10, 3, [(18, 40)] * 10))
    assert r["typ"] == "drops" and r["wochentag"] == "Do" and (r["uhrzeit"], r["minute"]) == (18, 40)
    assert "18:40" in r["text"] and not r["termine"][0]["verschoben"]


def test_rhythm_verschobene_uhrzeit():
    times = [(18, 0)] * 8 + [(20, 0)] * 4
    r = tracker.rhythm(_drop_stamps(12, 4, times))
    assert r["termine"][0]["verschoben"] and r["uhrzeit"] == 20


def test_rhythm_zwei_drop_tage_und_slots():
    stamps = _drop_stamps(8, 1, [(10, 58)] * 8) + _drop_stamps(8, 4, [(10, 58)] * 8)
    r = tracker.rhythm(stamps)
    assert r["typ"] == "drops" and sorted(x["tag"] for x in r["termine"]) == ["Di", "Fr"]
    st = {"quellen": {"liste": [{"name": "Football Finery", "rhythmus": r}]}}
    slots = tracker.drop_slots({"name": "Football Finery"}, st)
    assert sorted((tracker.WEEKDAYS[w], h, m) for w, h, m, *_ in slots) == [("Di", 10, 43), ("Fr", 10, 43)]


def test_recently_done():
    t = tracker.now()
    st = {"last_full": (t - tracker.dt.timedelta(hours=5)).isoformat(),
          "laeufe": [{"zeit": (t - tracker.dt.timedelta(hours=6)).isoformat(), "modus": "priority"}]}
    assert tracker.recently_done(st, "full")
    assert not tracker.recently_done(st, "priority")
    assert not tracker.recently_done(st, "drop")
    st["last_full"] = (t - tracker.dt.timedelta(hours=21)).isoformat()
    assert not tracker.recently_done(st, "full")


def test_fixed_slot_zeitzonen():
    berlin = lambda y, mo, d: tracker.dt.datetime(y, mo, d, 12, 0, tzinfo=tracker.TZ)
    # Fr 20:00 Neuseeland: Oktober (NZ Sommerzeit, DE Sommerzeit) = Fr 09:00 bei uns
    assert tracker.fixed_slot("Fr 20:00 Pacific/Auckland", berlin(2026, 10, 9)) == (4, 9, 0)
    # November (NZ Sommerzeit, DE Winterzeit) = Fr 08:00
    assert tracker.fixed_slot("Fr 20:00 Pacific/Auckland", berlin(2026, 11, 13)) == (4, 8, 0)
    # Mai (NZ Winterzeit, DE Sommerzeit) = Fr 10:00
    assert tracker.fixed_slot("Fr 20:00 Pacific/Auckland", berlin(2027, 5, 14)) == (4, 10, 0)
    assert tracker.fixed_slot("Sa 13:00") == (5, 13, 0)
    assert tracker.fixed_slot("Samstag 13 Uhr") is None


class _WixHttp:
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, want="json"):
        return {"apps": {tracker.WIX_STORES_APP: {"instance": "x"}}}

    def post(self, url, json=None, headers=None):
        self.calls += 1
        prods = [
            {"name": "adidas AC Milan 04/05 Home Jersey - Kaka #22 - XL - USED: Excellent", "urlPart": "milan-kaka",
             "price": 200.0, "currency": "USD", "isInStock": True, "productType": "physical",
             "media": [{"url": "abc~mv2.jpg"}], "options": [{"title": "Mens size", "selections": [{"description": "XL"}]}]},
            {"name": "Barcelona 2011/12 Home", "urlPart": "barca-kid", "price": 80.0, "currency": "USD", "isInStock": True,
             "media": [], "options": [{"title": "Youth size", "selections": [{"description": "XL"}]}]},
            {"name": "Sold shirt", "urlPart": "sold", "price": 1.0, "currency": "USD", "isInStock": False, "options": []},
        ]
        return {"data": {"catalog": {"category": {"productsWithMetaData": {"totalCount": 3, "list": prods}}}}}


def test_wix_run():
    items, n = tracker.wix_run(_WixHttp(), "Rare and Retro", "https://www.rareandretrosports.com")
    assert n == 3 and len(items) == 2
    kaka, kid = items
    assert kaka["url"] == "https://www.rareandretrosports.com/product-page/milan-kaka"
    assert kaka["image"] == "https://static.wixstatic.com/media/abc~mv2.jpg" and kaka["price"] == "200.0 USD"
    assert tracker.condition_info(kaka["title"], kaka["desc"])[0] == "Excellent"
    assert M.size_ok(kaka["size_text"], tracker.norm(kaka["match_text"]))
    assert not M.size_ok(kid["size_text"], tracker.norm(kid["match_text"]))   # Youth size raus


def test_parse_flag():
    body = "<!-- Hinweis -->\ngrund: unpassend\nid: classic-shirts.com/product-eng-1-x.html\nurl: https://x\n\nkommentar: nur Trainingsshirt\n"
    assert tracker.parse_flag(body) == {"grund": "unpassend", "id": "classic-shirts.com/product-eng-1-x.html",
                                        "kommentar": "nur Trainingsshirt"}
    assert tracker.parse_flag("irgendein Text") is None


def test_apply_flags_ohne_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    seen = {"a": {"labels": []}, "b": {"labels": []}}
    st = {"flags": {"a": {"grund": "ausverkauft", "zeit": "t"}, "b": {"grund": "unpassend", "kommentar": "Jacke", "zeit": "t"}}}
    assert tracker.apply_flags(seen, st, "t") == 0
    assert seen["a"]["verkauft"] == "t" and seen["b"]["aussortiert"] == "Gemeldet: unpassend (Jacke)"


def test_fyj_reissue_nur_thiago():
    assert {l for l, _ in M.labels("2013-14 Bayern Munich Thiago #6 XL", fyj_reissue=True)} == {"Thiago"}
    assert M.labels("2009-10 Bayern Munich Ribery #7 XL", fyj_reissue=True) == []


def test_type_excluded_nachbau():
    assert M.type_excluded("Reissue") and M.type_excluded("Nameset") and not M.type_excluded("Football shirt")


def test_repro_flock_kennzeichen():
    assert M.repro_flock("Maillot Barcelone 2012-2013 HOME 11 THIAGO flocage reproduction récente XL")
    assert M.repro_flock("2002-04 FC Bayern München Auswärtstrikot Makaay, Repro Flock")
    assert not M.repro_flock("2013-14 Bayern Munich Home Shirt Thiago #6 (XL)")
    assert {l for l, _ in M.labels("2015-16 Barcelone Home Vidal #22 XL")} == {"Vidal (Arturo)"}


@pytest.mark.parametrize("desc,other", [
    ("Etat : Excellent Taille : XL Equipementier : Adidas Le t-shirt en détail : T-shirt en excellent état.", True),
    ("Etat : Excellent Le maillot en détail : Maillot dans un superbe état", False),
    ("<p>Great condition home shirt with polo collar</p>", False),
    ("Vintage track jacket, size XL", True),
    ("Football shirt, comes with matching jacket zip", False),
    ("", False),
])
def test_desc_not_jersey(desc, other):
    assert tracker.desc_not_jersey(desc) == other


def test_desc_title_vorrang():
    d = "Millwall finished 9th under manager Kenny Jacket."
    assert not tracker.desc_not_jersey(d, "2010-11 Millwall '125 Year' Anniversary Shirt *BNIB* 5XL")
    assert tracker.desc_not_jersey("Le t-shirt en détail : T-shirt en excellent état", "2011/12 - Espagne (XL)")
    assert tracker.desc_not_jersey("Liverpool adidas T-Shirt", "2025-26 Liverpool adidas '95 T-Shirt *w/tags*")


def test_artikelcode_sondertrikot():
    title = "2022-23 LIVERPOOL SHIRT XXL"
    desc = "CONDITION: 9/10 DESCRIPTION: SPONSOR: STANDARD CHARTERED CODE: DM1835-377"
    assert M.labels(title) == []                       # ohne Variante im Titel: nein
    assert M.needs_detail(title)                       # aber Beschreibung nachladen lohnt
    assert {l for l, _ in M.labels(title, desc=desc)} == {"Liverpool Third 2022/23"}
    assert M.labels("2022-23 LIVERPOOL SALAH #11 SHIRT XXL", desc=desc) == [] or \
        "Liverpool Third 2022/23" not in {l for l, _ in M.labels("2022-23 LIVERPOOL SALAH #11 SHIRT XXL", desc=desc)}
    assert not M.needs_detail("2022-23 LIVERPOOL THIRD SHIRT XXL")   # Variante steht da, kein Nachladen
    assert not M.needs_detail("2019-20 LIVERPOOL SHIRT XXL")


@pytest.mark.parametrize("title,expected", [
    ("2022-23 LIVERPOOL *WINFIELD* SHIRT XL", set()),                       # Sternchen = fremder Flock
    ("2012-13 FC BARCELONA *BNWT* SHIRT XL", {"Barça 2008-2013"}),          # Zusatz, kein Flock
    ("2011-12 FC BARCELONA *THIAGO* SHIRT XL", {"Thiago", "Barça 2008-2013"}),
    ("2012-13 FC BARCELONA *PLAYER ISSUE* SHIRT XXL", {"Barça 2008-2013"}),
])
def test_sternchen_flock(title, expected):
    assert {l for l, _ in M.labels(title)} == expected


def test_drop_taeglich():
    shop = {"name": "Cult Kits", "drop": ["täglich 18:00 Europe/London"]}
    slots = tracker.drop_slots(shop, {})
    assert len(slots) == 7 and all((h, m) == (19, 0) for _, h, m, *_ in slots)   # 18 Uhr UK = 19 Uhr bei uns
    assert tracker.drop_due(shop, {}, _berlin(2026, 10, 6, 19, 30))


T90 = "Nike Total 90 (2004-06)"


@pytest.mark.parametrize("title,yes", [
    ("2004-06 Portugal Home Shirt Ronaldo #17 (XL)", True),
    ("2004-06 Holland Away Shirt (XXL)", False),                # nur beflockt
    ("2004-06 Holland Away Shirt Robben #11 (XXL)", True),
    ("Brazil 2004 Home Shirt Ronaldinho #10 XL", True),
    ("2004-05 Inter Milan Home Shirt Adriano #10 (XL)", True),
    ("2004-05 Juventus Away Shirt Del Piero #10 XL", True),
    ("2006-08 Brazil Home Shirt (XL)", False),                 # WM-2006-Trikot, anderes Template
    ("2005-06 Juventus Home Shirt (XL)", False),               # Vereine nur 2004/05
    ("Portugal 2004 Home Shirt (2025 Reissue) XL", False),     # Neuauflage ohne Flock
    ("Portugal 2004 Home Shirt Ronaldo #17 (2025 Reissue) XL", True),   # Neuauflage mit Flock
    ("2004 Netherlands Nike T90 Remake Shirt XL", False),
    ("2004-06 South Korea Home Shirt Park #7 (XL)", True),
    ("Mexico 2004 Away Jersey Borgetti #9 XL", True),
    ("2004-06 Croatia Home Shirt Kovac #10 (XL)", True),
    ("2004-05 Barcelona Home Shirt Ronaldinho #10 (XL)", True),
    ("2005-06 Barcelona Home Shirt (XL)", False),
    ("2004-06 Arsenal Home Shirt Henry #14 (XL)", True),
    ("2004-05 FC Porto Home Shirt Deco #10 (XL)", True),
    ("2004-05 FC Porto Home Shirt (XL)", False),
    ("BRASILE 2004 - RONALDO - HOME XL", True),                  # Name ohne Nummer zählt als Flock
    ("JUVENTUS 2004/05 - THURAM - HOME XL", True),
    ("2004-06 NETHERLANDS SHIRT XXL", False),
    ("2004 Porto Alegre Gremio Shirt XL", False),
    ("2004-05 Valencia Home Shirt Aimar #21 (XL)", True),         # Valencia nur beflockt
    ("2004-05 Valencia Home Shirt (XL)", False),
    ("2004-05 PSV Eindhoven Home Shirt *PARK* XL", True),
    ("2004-05 PSV Home Shirt XL", False),
    ("Australia 2004-06 Home Shirt Viduka 9 XL", True),
    ("Australia 2004-06 Home Shirt XL - 8/10", False),
    ("2004/05 Inter Milan Training Shirt XL", False),
    ("2004 GREECE UEFA EURO 2004 PORTUGAL SHIRT XL", False),
    ("Original Portugal Away Jersey 2002-2004 #11 Ronaldo - XL", False),
    ("Brazilië (wedstrijd gedragen) keepersshirt 2004 Heurelho Gomes XL", False),
])
def test_total90(title, yes):
    assert (T90 in {l for l, _ in M.labels(title)}) == yes


def test_saison_bereich():
    assert any(rx.search("2004-06 arsenal home") for rx in tracker.season_rxs("2004/06"))
    assert not any(rx.search("2004-05 arsenal home") for rx in tracker.season_rxs("2004/06"))
    assert any(rx.search("2010-11 home") for rx in tracker.season_rxs("2010/11"))


def test_neuauflage_kennzeichen():
    assert M.reissue("Portugal 2004 Home Shirt (2025 Reissue) XL")
    assert not M.reissue("2004-06 Portugal Home Shirt Figo #7 XL")
    assert M.labels("2015-16 Bayern Munich Thiago #6 Reissue (XL)") == []    # Thiago-Reissue bleibt raus


def test_wix_text_v3():
    d = '{"nodes":[{"type":"PARAGRAPH","nodes":[{"type":"TEXT","textData":{"text":"Zustand 9/10"}}]},' \
        '{"type":"PARAGRAPH","nodes":[{"type":"TEXT","textData":{"text":"Repro Flock"}}]}]}'
    txt = tracker.wix_text(d)
    assert "Zustand 9/10" in txt and M.repro_flock(txt)
    assert tracker.wix_text("<p>Condition: Excellent</p>") == "Condition: Excellent"


def test_flock_erkennung_nur_fuer_pflicht():
    # "blanco" (weiß) darf ein unbeflocktes Spanien-Sondertrikot nicht als fremd beflockt aussortieren
    assert {l for l, _ in M.labels("Camiseta España 2010 blanco XL")} == {"Spanien 2010/2011"}


@pytest.mark.parametrize("title,expected", [
    ("FC Barcelona 2011-12 Trainingsjacke (XXL) nike", set()),                     # Meldung #19
    ("giacca barcellona nike 2011/2012 XL", set()),                                 # Meldung #21
    ("Espanyol Barcelona 2012-13 Trikot auswärts BNWT - 10/10 - [XL]", set()),      # Meldung #4
    ("Bayer 04 Leverkusen - Kroos #39 - Trikot 2008–2009 - XL", set()),             # Meldung #5
    ("Maillot de football retro Equipe d'Espagne N°7 MARAVILLA 2010-2011 XL", set()),   # Meldung #7
    ("2004/05 - Juventus (XL) *university*", set()),                                # Meldung #6
    ("2013-14 Bayern Munich Home Shirt Kroos #39 (XL)", {"Kroos"}),
])
def test_meldungen_0410(title, expected):
    assert {l for l, _ in M.labels(title)} == expected


def test_log_problems(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "ERROR_LOG", tmp_path / "log.json")
    monkeypatch.setattr(tracker, "ERROR_REPORT", tmp_path / "FEHLER.md")
    t1 = tracker.now().isoformat()
    tracker.log_problems([("Oh Calcio", "keine Produkte erhalten")], "full", t1)
    tracker.log_problems([("Oh Calcio", "keine Produkte erhalten"), ("FYJ", "HTTP 500")], "priority", t1)
    log = tracker.load_json(tmp_path / "log.json", {})
    assert log["Oh Calcio|keine Produkte erhalten"]["anzahl"] == 2
    assert "Oh Calcio" in (tmp_path / "FEHLER.md").read_text() and "FYJ" in (tmp_path / "FEHLER.md").read_text()


WM06 = "WM 2006"


@pytest.mark.parametrize("title,yes", [
    ("Germany 2006 Home Shirt Ballack #13 (XL)", True),
    ("2005-07 Germany Home Shirt Klose #11 (XL)", True),           # WM-Trikot kam 2005
    ("Italy 2006 World Cup Home Shirt Totti 10 XL", True),
    ("2006-08 Argentina Home Shirt Riquelme #10 (XXL)", True),
    ("Maillot Equipe de France 2006 Domicile ZIDANE XL", True),
    ("2006-07 England Home Shirt Gerrard #8 (XL)", True),
    ("Germany 2006 Home Shirt (XL)", False),                        # nur beflockt
    ("Netherlands 2004/2005/2006 Home Shirt Van Nistelrooy XL", False),   # T90-Vorgänger
    ("New England Revolution 2006 Home Shirt Twellman #20 XL", False),
    ("2006-07 Juventus Home Shirt Del Piero #10 XL", False),       # Verein, kein Land
    ("Germany 2006 Training Shirt Ballack XL", False),
    ("2006/07 - Coupe de France #11 (XL) [MATCH ISSUE]", False),
])
def test_wm2006(title, yes):
    assert (WM06 in {l for l, _ in M.labels(title)}) == yes


def test_check_alarms(monkeypatch):
    issues = [{"number": 7, "body": "grund: alarm\nid: shop.de/products/x\n", "user": {"login": "me"}}]
    monkeypatch.setattr(tracker, "owner_issues", lambda label, state="open": (issues, ("api", {})))
    posted = []
    monkeypatch.setattr(tracker.requests, "post", lambda *a, **k: posted.append(a))
    monkeypatch.setattr(tracker.requests, "patch", lambda *a, **k: posted.append(a))
    seen = {"shop.de/products/x": {"title": "Thiago XL", "shop": "S", "url": "u", "price": "100.00 EUR", "size": "XL"}}
    st, pushes = {}, []
    note = lambda *a: pushes.append(a)
    tracker.check_alarms(seen, st, "t", {"EUR": 1.0}, "full", note)       # Startpreis merken
    seen["shop.de/products/x"]["price"] = "80.00 EUR"
    tracker.check_alarms(seen, st, "t", {"EUR": 1.0}, "full", note)       # gesunken -> Push
    assert len(pushes) == 1 and "100.00 € → 80.00 €" in pushes[0][1]
    seen["shop.de/products/x"]["verkauft"] = "t"
    tracker.check_alarms(seen, st, "t", {"EUR": 1.0}, "full", note)       # verkauft -> Push, Issue zu
    assert len(pushes) == 2 and posted and st["alarme"] == {}


def test_add_shops_from_issues(tmp_path, monkeypatch):
    f = tmp_path / "shops.yaml"
    f.write_text("shops:\n  - {name: A, url: \"https://a.com\"}\n\n# Marktplätze (eBay, Depop)\n")
    monkeypatch.setattr(tracker, "SHOPS_FILE", f)
    issues = [{"number": 3, "body": "Shop aufnehmen\n\nurl: https://www.new-shop.co.uk\nplattform: shopify\n"},
              {"number": 4, "body": "url: https://wixy.com\nplattform: wix\n"},
              {"number": 5, "body": "url: https://a.com\nplattform: shopify\n"}]          # schon drin
    monkeypatch.setattr(tracker, "owner_issues", lambda label, state="open": (issues, ("api", {})))
    monkeypatch.setattr(tracker.requests, "post", lambda *a, **k: None)
    monkeypatch.setattr(tracker.requests, "patch", lambda *a, **k: None)
    assert tracker.add_shops_from_issues() == 2
    cfg = yaml.safe_load(f.read_text())
    names = {s["name"]: s for s in cfg["shops"]}
    assert names["New Shop"]["url"] == "https://www.new-shop.co.uk" and names["New Shop"]["schnellcheck"] == "nein"
    assert names["Wixy"]["plattform"] == "wix" and len(cfg["shops"]) == 3


def test_fundgrube(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "FUNDGRUBE_REPORT", tmp_path / "FUNDGRUBE.md")
    monkeypatch.setattr(tracker, "detect_platform", lambda base: "shopify" if "good" in base else "unbekannt")
    tracker.FYJ_DOMAIN_STATS.clear()
    tracker.FYJ_DOMAIN_STATS.update({"good.com": [20, 1], "remake.com": [10, 5]})
    monkeypatch.setattr(tracker, "detect_platform", lambda base: "shopify" if ("good" in base or "remake" in base) else "unbekannt")
    st = {"fyj_shops": {"good.com": {"treffer": 9, "seit": "t"}, "remake.com": {"treffer": 4, "seit": "t"},
                        "known.com": {"treffer": 7, "seit": "t"}, "ebay.de": {"treffer": 3, "seit": "t"},
                        "odd.net": {"treffer": 2, "seit": "t"}}}
    cands = tracker.fundgrube(st, [{"url": "https://www.known.com"}], tracker.now().isoformat())
    by = {c["domain"]: c for c in cands}
    assert set(by) == {"good.com", "remake.com", "odd.net"}            # bekannte und Marktplätze raus
    assert by["good.com"]["empfohlen"] and not by["remake.com"]["empfohlen"] and not by["odd.net"]["empfohlen"]
    assert tracker.fundgrube(st, [], tracker.now().isoformat()) is None   # erst nach einer Woche wieder


def test_short_size():
    assert tracker.short_size("X-LARGE") == "XL"
    assert tracker.short_size("Extra Large") == "XL"
    assert tracker.short_size("XX-LARGE") == "XXL"
    assert tracker.short_size("2XL") == "XXL"
    assert tracker.short_size("XL") == "XL"
    assert tracker.short_size("") == ""


@pytest.mark.parametrize("title,expected", [
    ("2008-09 Barcelona Away Shirt (XL)", {"Barça 2008-2013"}),
    ("2008/09 FC Barcelona Third Shirt XL", {"Barça 2008-2013"}),
    ("2009-10 Barcelona Home Shirt (XXL)", {"Barça 2008-2013"}),
    ("2009-10 Barcelona Away Shirt Henry #14 (XL)", set()),           # fremder Flock
    ("2008-09 Barcelona Home Shirt Eto'o #9 (XL)", set()),
    ("2007-08 Barcelona Home Shirt (XL)", set()),
])
def test_barca_2008_2010(title, expected):
    assert {l for l, _ in M.labels(title)} == expected


@pytest.mark.parametrize("title,expected", [
    ("Trikot - Hamburger SV - Tony Yeboah - 1999/2000 - XL - Heim", True),      # Flock ohne Nummer
    ("1998-99 HAMBURG *SPORL* SHIRT XL", True),
    ("Original Hamburger SV 2013/14 Third - Calhanoglu #9 Size XXL", True),
    ("Hamburger SV 11/12 Guerreiro", True),
    ("2010-11 HAMBURG SHIRT XL", False),                                         # kein Flock
    ("Hamburger SV 07/08 Kein Flock", False),
    ("Erima SC Victoria Hamburg 1990s Long Sleeve Home Shirt #9 XL", False),
    ("Hamburger SV thuisshirt 2017-2018 Kyriakos Papadopoulos", False),          # nach 2016
    ("FC St. Pauli 2010/11 Home Shirt #10 XL", False),
])
def test_hsv(title, expected):
    assert ("HSV 1990-2016" in {l for l, _ in M.labels(title)}) == expected


@pytest.mark.parametrize("title", [
    "Bayern Munich 2021-22 Octoberfest Shirt XL",
    "FC Bayern München Wiesntrikot 2021 XL",
    "FC Bayern Oktoberfest-Trikot 2021/22 grün",
])
def test_wiesn_schreibweisen(title):
    assert "Bayern Wiesn 2021/22 (grün)" in {l for l, _ in M.labels(title)}
