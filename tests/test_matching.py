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
