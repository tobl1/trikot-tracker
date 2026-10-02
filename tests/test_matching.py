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
    ("2008-09 Hamburger SV Home Shirt Olic #11 (XL)", {"Olić"}),
    ("2009-10 HSV Home Shirt Olić #11 XL", {"Olić"}),
    ("2010-11 Wolfsburg Home Shirt Olic XL", set()),
    ("2003-04 Arsenal Home Shirt Henry #14 (XL)", {"Henry"}),
    ("2008-09 Barcelona Home Shirt Henry #14 (XL)", set()),
    ("2010-11 Bayern Munich Home Shirt Robben #10 (XL)", {"Robben"}),
    ("2006-07 Chelsea Home Shirt Robben #16 (XL)", set()),
    ("2004-05 Lyon Home Shirt Juninho #8 (XL)", {"Juninho (Pernambucano)"}),
    ("2023-24 Man City Home Shirt Rodri #16 (XL)", {"Rodri"}),
    ("2023-24 Man City Home Shirt Rodrigo #16 (XL)", set()),
    ("2019-20 Ajax Home Shirt De Jong #21 (XL)", {"Frenkie de Jong"}),
    ("2014-15 Feyenoord Home Shirt Luuk de Jong (XL)", set()),
    ("2010-11 PSV Home Shirt Van der Vaart XL", {"Van der Vaart"}),
    # Sondertrikots
    ("2011-12 Barcelona Home Shirt (XL)", {"Barça 2010-2013"}),
    ("Barcelona 2010/2011 Away Shirt XL", {"Barça 2010-2013"}),
    ("2009-10 Barcelona Home Shirt (XL)", set()),
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
    ("2012-13 Barcelona Home Short Sleeve Shirt (XL)", {"Barça 2010-2013"}),
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
    ("2012-13 Barcelona Home Shirt Thiago #11 (XL)", {"Thiago", "Barça 2010-2013"}),
    ("2010-11 Spain Home Shirt Alonso #14 (XL)", {"Alonso (Xabi)"}),
    ("2021-22 Liverpool Away Shirt Thiago #6 (XL)", {"Thiago", "Liverpool Away 2021/22"}),
    # Neu (01.10.2026): niederländische Titel (The Football Temple) und andere Sprachen
    ("Spanje 2010 Thuis Shirt (XL)", {"Spanien 2010/2011"}),
    ("Spanje 2014 Uit Shirt (XXL)", {"Spanien 2014"}),
    ("Spanje 2010 Thuis Shirt Iniesta #6 (XL)", set()),
    ("Spanje 2014 Thuis Shirt Thiago #6 (XL)", {"Thiago", "Spanien 2014"}),
    ("Barcelona 2012/2013 Uit Shirt (XL)", {"Barça 2010-2013"}),
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
    ("2012-13 Barcelona Home Shirt Thiago #11 with official name set (XL)", {"Thiago", "Barça 2010-2013"}),
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
    assert M.excluded(tracker.norm(typ)) == excluded


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


class _FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeClient:
    """Nachbau von anthropic.Anthropic für Tests: merkt sich den Aufruf, antwortet mit festem JSON"""
    def __init__(self, answer):
        self.answer, self.calls = answer, []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return type("R", (), {"stop_reason": "end_turn", "content": [_FakeBlock(tracker.json.dumps(self.answer))]})()


class _FakeHttp:
    def __init__(self):
        resp = type("Resp", (), {"status_code": 200, "headers": {"Content-Type": "image/jpeg"}, "content": b"\xff\xd8x"})()
        self.s = type("S", (), {"get": lambda self_, url, timeout=None: resp})()


def test_vision_check_request_and_verdict():
    e = {"title": "2010-11 BARCELONA SHIRT XL", "image": "https://x/img.jpg", "labels": ["Barça 2010-2013"]}
    client = _FakeClient({"art": "trainingsshirt", "passt_zur_beschreibung": False, "flock": "ohne",
                          "begruendung": "Dri-Fit ohne Sponsor"})
    res = tracker.vision_check(e, _FakeHttp(), client)
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"
    assert tracker.vision_verdict(res, e) == "Bild: trainingsshirt"


@pytest.mark.parametrize("art,flock,passt,labels,out", [
    ("spieltrikot", "ohne", True, ["Barça 2010-2013"], None),
    ("spieltrikot", "anderer_spieler", True, ["Barça 2010-2013"], "Bild: Flock eines anderen Spielers"),
    ("spieltrikot", "anderer_spieler", True, ["Thiago", "Barça 2010-2013"], None),
    ("spieltrikot", "ohne", False, ["Spanien 2014"], "Bild: anderes Trikot als gesucht"),
    ("jacke_oder_oberteil", "ohne", True, ["Spanien 2010/2011"], "Bild: jacke oder oberteil"),
    ("unklar", "nicht_sichtbar", False, ["Thiago"], None),
    ("spieltrikot", "thiago", False, ["Thiago"], None),          # Thiago nie wegen Saison-Zweifel raus
])
def test_vision_verdict(art, flock, passt, labels, out):
    res = {"art": art, "flock": flock, "passt_zur_beschreibung": passt, "begruendung": ""}
    assert tracker.vision_verdict(res, {"labels": labels}) == out


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
