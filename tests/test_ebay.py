"""eBay-Anbindung ohne Netz: nachgebaute Schnittstelle (FakeEbay), Verschlüsselung, Ablauf über mehrere Runs"""

import datetime as _dt
import sys
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tracker  # noqa: E402
import trikot.speicher  # noqa: E402
from trikot import ebay  # noqa: E402

WATCH = yaml.safe_load((Path(__file__).resolve().parent.parent / "watchlist.yaml").read_text(encoding="utf-8"))
M = tracker.Matcher(WATCH)
RATES = {"GBP": 0.85}   # 1 EUR = 0,85 GBP


def summ(iid, title, price="49.99", cur="EUR", country="DE", opts=("FIXED_PRICE",), score=50, pct="99.5"):
    return {"itemId": iid, "legacyItemId": iid.split("|")[1], "title": title, "itemWebUrl": "https://x",
            "price": {"value": price, "currency": cur}, "buyingOptions": list(opts),
            "itemLocation": {"country": country}, "seller": {"feedbackScore": score, "feedbackPercentage": pct},
            "image": {"imageUrl": "https://i.ebayimg.com/x.jpg"}, "condition": "Gebraucht",
            "shippingOptions": [{"shippingCost": {"value": "5.00", "currency": cur}}]}


class FakeEbay:
    def __init__(self, results, details=None):
        self.results = results          # {(where, q): [summaries]}
        self.details = details or {}    # {item_id: (status, detail)}
        self.calls = 0
        self.errors = []
        self.item_calls = []

    def search(self, where, q, newest=False, offset=0):
        self.calls += 1
        items = self.results.get((where, q), [])
        return 200, {"total": len(items), "itemSummaries": items[offset:offset + 200]}

    def item(self, item_id, where):
        self.calls += 1
        self.item_calls.append(item_id)
        return self.details.get(item_id, (200, {"buyingOptions": ["FIXED_PRICE"],
                                                "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}]}))


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "geheim")
    monkeypatch.setattr(trikot.speicher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(trikot.speicher, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()


def run(status, client, mode="full", ts=None):
    pushes = []
    ts = ts or tracker.now().isoformat()
    summary, problems = ebay.run(mode, status, M, WATCH, RATES, ts, lambda *a: pushes.append(a), client=client)
    return pushes, summary, problems


THIAGO = "v1|111|0", "Bayern München Trikot 2013/14 Thiago #6 Gr. XL Adidas"


def test_verschluesselung_hin_und_zurueck():
    blob = ebay.seal_state({"a": 1}, "geheim")
    assert ebay.open_state(blob, "geheim") == {"a": 1} and ebay.open_state(blob, "anders") is None
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = ebay.b64u(priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    sealed = ebay.seal_for_device(pub, {"treffer": [1, 2]})
    assert ebay.open_for_device(priv, sealed) == {"treffer": [1, 2]}
    assert "treffer" not in str(sealed)


def test_sofortkauf_auktion_und_verkaeufer():
    assert ebay.summary_item(summ("v1|1|0", "x", opts=("AUCTION",)), "EU") is None
    it = ebay.summary_item(summ("v1|1|0", "x", opts=("AUCTION", "FIXED_PRICE")), "EU")
    assert it["auktion"] and it["url"] == "https://www.ebay.de/itm/1"
    assert ebay.summary_item(summ("v1|2|0", "x"), "UK")["url"] == "https://www.ebay.co.uk/itm/2"
    cfg = WATCH["ebay"]
    assert ebay.seller_ok(summ("v1|1|0", "x"), cfg)
    assert not ebay.seller_ok(summ("v1|1|0", "x", score=3), cfg) and not ebay.seller_ok(summ("v1|1|0", "x", pct="91.0"), cfg)


def test_endpreis_uk_und_ukraine():
    assert ebay.landed(100, "DE") is None
    assert ebay.landed(100, "GB") == 122.0                      # 19 % MwSt. + 3 € Pauschalzoll
    assert ebay.landed(200, "UA") == round(200 * 1.12 * 1.19 + 12, 2)


def test_ablauf_erstlauf_still_dann_push_groesse_loeschen(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    status = {}
    first = FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO)]})
    pushes, summary, problems = run(status, first)
    assert pushes == [] and not problems                      # Erstlauf: still übernommen
    state = ebay.open_state(trikot.speicher.load_json(ebay.state_path(), None), "geheim")
    assert state["treffer"]["v1|111|0"]["still"] and status["ebay"]["treffer"] == 1
    assert "Thiago" not in (tmp_path / "state" / "ebay.json").read_text()   # nichts im Klartext

    # neues Thiago-Angebot ohne Größe im Titel: Größe aus dem Merkmal, Einzel-Push mit eBay-Link
    neu = summ("v1|222|0", "Spanien Trikot 2010 Home Thiago Alcantara", price="60.00")
    second = FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO), neu]},
                      {"v1|222|0": (200, {"localizedAspects": [{"name": "Größe", "value": "XL"}]})})
    pushes, _, _ = run(status, second)
    assert len(pushes) == 1 and pushes[0][3] == "https://www.ebay.de/itm/222" and pushes[0][2] == 5
    assert "v1|222|0" in second.item_calls

    # Gesamt-Run, Angebot 111 nicht mehr in der Suche und beendet (404): Eintrag gelöscht, nicht nur markiert
    third = FakeEbay({("EU", "(thiago, alcantara)"): [neu]}, {"v1|111|0": (404, {})})
    run(status, third)
    state = ebay.open_state(trikot.speicher.load_json(ebay.state_path(), None), "geheim")
    assert set(state["treffer"]) == {"v1|222|0"} and "v1|222|0" not in third.item_calls   # Größe gemerkt

    # derselbe Artikel neu eingestellt (neue Nummer, gleicher Titel und Preis): keine zweite Push
    relist = summ("v1|333|0", THIAGO[1])
    pushes, _, _ = run(status, FakeEbay({("EU", "(thiago, alcantara)"): [neu, relist]}))
    assert pushes == []


def test_falsche_groesse_teuer_und_uk(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    status = {}
    run(status, FakeEbay({}))                                   # Erstlauf leer
    res = {("EU", "(thiago, alcantara)"): [summ("v1|1|0", "Bayern Trikot 2013/14 Thiago #6 Gr. L")],
           ("UK", "(verratti, perisic, olic, vaart, nistelrooy, nistelrooij, henry, torres, robben, alonso, cavani, "
                  "forlan, ribery, juninho, benzema, kroos, rodri, valverde, vidal, kimmich, barella, grimaldo, jong, "
                  "llorente, roberto)"): [summ("v1|2|0", "Arsenal 2003/04 Home Shirt Henry 14 XL", price="120.00", cur="GBP",
                                               country="GB")]}
    pushes, _, _ = run(status, FakeEbay(res))
    state = ebay.open_state(trikot.speicher.load_json(ebay.state_path(), None), "geheim")
    assert set(state["treffer"]) == {"v1|2|0"}                 # L fliegt raus
    e = state["treffer"]["v1|2|0"]
    assert e["endpreis"] > 150 and e["teuer"] and pushes == []  # 120 £ = 141 €, mit Zoll über der Grenze


def test_app_daten_je_geraet(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = ebay.b64u(priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def issues(label):
        return [{"number": 1, "body": f"ebay-key: {pub}"}], None
    status = {}
    assert ebay.collect_devices(status, "2026-10-08T12:00:00+00:00", issues) == 1
    run(status, FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO)]}))
    app = trikot.speicher.load_json(ebay.app_path(), None)
    data = ebay.open_for_device(priv, app["fuer"][ebay.device_id(pub)])
    assert data["treffer"][0]["groesse"] == "XL" and data["zeigen_h"] == 6 and "Thiago" in data["treffer"][0]["labels"]


def test_faellig():
    status = {"ebay": {"radar": (tracker.now() - _dt.timedelta(minutes=10)).isoformat(), "bestaetigt": {}}}
    import os
    os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"] = "id", "geheim"
    try:
        assert ebay.due(status, "drop", tracker.now()) == {"suche": None, "bestaetigen": False}
        status["ebay"]["bestaetigt"] = {"x": (tracker.now() - _dt.timedelta(hours=5)).isoformat()}
        assert ebay.due(status, "drop", tracker.now())["bestaetigen"]
        assert ebay.due(status, "full", tracker.now())["suche"] == "voll"
        assert ebay.due(status, "priority", tracker.now())["suche"] is None
    finally:
        del os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"]


def test_gemeldet_und_neu_eingestellt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    status = {}
    run(status, FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO)]}))
    status["flags"] = {"ebay:" + ebay.id_key("v1|111|0"): {"grund": "kein original"}}
    run(status, FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO)]}))
    state = ebay.open_state(trikot.speicher.load_json(ebay.state_path(), None), "geheim")
    assert state["treffer"] == {}
    pushes, _, _ = run(status, FakeEbay({("EU", "(thiago, alcantara)"): [summ("v1|999|0", THIAGO[1])]}))   # neu eingestellt
    state = ebay.open_state(trikot.speicher.load_json(ebay.state_path(), None), "geheim")
    assert state["treffer"] == {} and pushes == []


def test_neues_geraet_bekommt_daten_sofort(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    status = {}
    run(status, FakeEbay({("EU", "(thiago, alcantara)"): [summ(*THIAGO)]}))
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = ebay.b64u(priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    ebay.collect_devices(status, "2026-10-08T12:00:00+00:00", lambda label: ([{"number": 1, "body": f"ebay-key: {pub}"}], None))
    assert ebay.rewrite_app(status, "2026-10-08T12:00:00+00:00")
    app = trikot.speicher.load_json(ebay.app_path(), None)
    assert len(ebay.open_for_device(priv, app["fuer"][ebay.device_id(pub)])["treffer"]) == 1
