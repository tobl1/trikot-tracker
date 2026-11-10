"""Ganze Runs von Anfang bis Ende (main), ohne Netz: Shops, Seitenprüfung, Kurse und Datenordner sind ersetzt.
Angelegt am 10.11.2026 nach der Gesamtprüfung: bis dahin war der Ablauf selbst nicht getestet, nur seine Bausteine"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import trikot.lauf  # noqa: E402
import trikot.melden  # noqa: E402
import trikot.pruefung  # noqa: E402
import trikot.speicher  # noqa: E402
from trikot import webpush  # noqa: E402
from trikot.preise import parse_price  # noqa: E402
from trikot.quellen.gemeinsam import item  # noqa: E402

SHOP = {"name": "Testshop", "url": "https://testshop.example", "plattform": "idosell"}


@pytest.fixture
def lauf(tmp_path, monkeypatch):
    """run(artikel, seiten) spielt einen Gesamt-Run mit diesen Artikeln; gibt (seen, Pushes im Postausgang) zurück"""
    sp = trikot.speicher
    state = tmp_path / "state"
    for name, path in (("DATA_DIR", tmp_path), ("STATE_DIR", state), ("SEEN_FILE", state / "seen.json"),
                       ("STATUS_FILE", state / "status.json"), ("OUTBOX_FILE", state / "postausgang.json"),
                       ("REPORT_FILE", tmp_path / "TREFFER.md"), ("DASHBOARD_FILE", tmp_path / "treffer.json"),
                       ("ERROR_LOG", state / "fehlerlog.json"), ("ERROR_REPORT", tmp_path / "FEHLER.md"),
                       ("FUNDGRUBE_REPORT", tmp_path / "FUNDGRUBE.md")):
        monkeypatch.setattr(sp, name, path)
    for var in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "DASHBOARD_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sp, "load_shops", lambda: {"shops": [SHOP], "fyj": "aus"})
    monkeypatch.setattr(trikot.lauf, "fetch_rates", lambda st: {"rates": {"EUR": 1.0, "GBP": 0.85}})
    monkeypatch.setattr(trikot.lauf, "add_shops_from_issues", lambda: 0)

    def run(artikel, seiten=None):
        monkeypatch.setattr(trikot.lauf, "run_shop", lambda shop, mode, m, p, c: (
            list(artikel), {"name": shop["name"], "plattform": "idosell", "produkte": 50, "fehler": "", "info": ""}))
        monkeypatch.setattr(trikot.pruefung, "check_page", lambda http, url: (seiten or {}).get(url))
        monkeypatch.setattr(sys, "argv", ["tracker.py", "--mode", "full"])
        trikot.melden.POSTAUSGANG.clear()
        (state / "postausgang.json").unlink(missing_ok=True)
        trikot.lauf.main()
        seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
        out = json.loads((state / "postausgang.json").read_text(encoding="utf-8")) if (state / "postausgang.json").exists() else []
        return seen, out
    return run


def kroos(n, **more):
    return item("direkt", "Testshop", f"https://testshop.example/kroos-{n}.html",
                f"2013-14 BAYERN MUNCHEN *KROOS* SHIRT XL {n}", "XL", "£39.99", "https://testshop.example/b.jpg", **more)


def seite(text):
    return {"verfuegbar": True, "desc": text, "marke": ""}


def test_run_erstlauf_dann_neuer_treffer_mit_push(lauf):
    seen, out = lauf([kroos(1)])
    assert len(seen) == 1 and out[0]["title"].startswith("🚀") and len(out) == 1            # Erstlauf: eine Sammelnachricht
    seen, out = lauf([kroos(1), kroos(2)])
    assert len(seen) == 2 and len(out) == 1 and "Kroos" in out[0]["title"]        # nur der neue wird gemeldet
    seen, out = lauf([kroos(1), kroos(2)])
    assert out == []                                                              # nichts Neues, keine Push


def test_run_mindestnote_von_der_shop_seite(lauf):
    """Note steht nur auf der Shop-Seite (Classic-Shirts): kein Push, und auch in den folgenden Runs keiner.
    Bis 10.11.2026 kam die Push trotzdem, der Eintrag wurde danach vergessen und beim nächsten Fund erneut gemeldet"""
    lauf([kroos(1)])
    schlecht = kroos(2, pruefen=True)
    seiten = {schlecht["url"]: seite("CONDITION: 5/10 DESCRIPTION: holes")}
    for _ in range(3):
        seen, out = lauf([kroos(1), schlecht], seiten)
        e = seen["testshop.example/kroos-2.html"]
        assert out == [] and e["zustand"] == "5/10" and e["aussortiert"] == trikot.lauf.WORN
    treffer = json.loads((trikot.speicher.DASHBOARD_FILE).read_text(encoding="utf-8"))["treffer"]
    assert [t["id"] for t in treffer] == ["testshop.example/kroos-1.html"]        # in der App nicht zu sehen
    # gute Note auf der Seite: ganz normal mit Push
    gut = kroos(3, pruefen=True)
    seen, out = lauf([kroos(1), schlecht, gut], {**seiten, gut["url"]: seite("CONDITION: 8/10 DESCRIPTION: fine")})
    assert len(out) == 1 and "aussortiert" not in seen["testshop.example/kroos-3.html"]


def test_run_nur_web_adressen(lauf):
    """Fremde Daten dürfen nie etwas anderes als Web-Adressen in die App bringen"""
    lauf([kroos(1)])
    boese = dict(kroos(2), url="javascript:alert(1)//kroos-2.html")
    bild = dict(kroos(3), image="javascript:alert(1)")
    seen, _ = lauf([kroos(1), boese, bild])
    assert not any(e["url"].startswith("javascript") for e in seen.values())
    assert seen["testshop.example/kroos-3.html"]["image"] == ""


def test_app_verlinkt_nur_web_adressen():
    html = (Path(__file__).resolve().parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'href="\$\{esc\((?!web\()', html) and "const web = u =>" in html


def test_oeffentlicher_schluessel_wie_in_der_app():
    html = (Path(__file__).resolve().parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'VAPID_PUBLIC = "([^"]+)"', html).group(1) == webpush.VAPID_PUBLIC


def test_ebay_push_liegt_verschluesselt_im_postausgang(tmp_path, monkeypatch):
    """Der Postausgang steht im öffentlichen Daten-Zweig: eBay-Inhalte dürfen dort nicht lesbar sein"""
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(webpush, "VAPID_PUBLIC", webpush.public_key_b64(key))
    monkeypatch.setattr(trikot.speicher, "OUTBOX_FILE", tmp_path / "postausgang.json")
    trikot.melden.POSTAUSGANG.clear()
    trikot.melden.push("🛒 eBay: Thiago", "Geheimer Angebotstitel 49,00 €", 5, "https://x/#ebay=abc", geheim=True)
    trikot.melden.save_outbox()
    roh = (tmp_path / "postausgang.json").read_text(encoding="utf-8")
    assert "Geheim" not in roh and "eBay" not in roh and "#ebay" not in roh
    st = {"push_abos": {"a": {"blob": webpush.seal_abo({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "x", "auth": "y"}},
                                                       webpush.public_key_b64(key)), "seit": "1"}}}
    got = []
    monkeypatch.setattr(trikot.melden.webpush, "send", lambda s, msg, k: got.append(msg) or 201)
    assert trikot.melden.send_outbox(st, key)[:3] == (1, 0, 0)
    assert got == [{"title": "🛒 eBay: Thiago", "body": "Geheimer Angebotstitel 49,00 €", "url": "https://x/#ebay=abc"}]
    # falscher Schlüssel: verwerfen und melden statt abstürzen
    trikot.melden.push("🛒 eBay", "x", 5, geheim=True)
    trikot.melden.save_outbox()
    other = ec.generate_private_key(ec.SECP256R1())
    sent, left, dropped, problems = trikot.melden.send_outbox({"push_abos": {}}, other)
    assert (sent, left, dropped) == (0, 0, 1) and any("nicht lesbar" in m for _, m in problems)


def test_ebay_push_im_probelauf_nicht_im_log(capsys):
    trikot.melden.push("🛒 eBay: Thiago", "Geheimer Angebotstitel", 5, dry=True, geheim=True)
    assert "Geheim" not in capsys.readouterr().out


def test_kaputtes_abo_stoppt_den_versand_nicht():
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    pub = webpush.public_key_b64(key)
    assert webpush.open_abo(webpush.seal_abo({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "abc"}}, pub), key) is None
    assert webpush.open_abo(webpush.seal_abo({"endpoint": "https://web.push.apple.com/x", "keys": "x"}, pub), key) is None
    assert webpush.send({"endpoint": "https://web.push.apple.com/x", "keys": {"p256dh": "abc", "auth": "abc"}}, {"title": "t"}, key) == 0


@pytest.mark.parametrize("text,erwartet", [
    ("Von 45,00 €", (45.0, "EUR")), ("Now £45.00", (45.0, "GBP")), ("ab 49,99 €", (49.99, "EUR")),
    ("45.00 GBP", (45.0, "GBP")), ("1.299,00 kr DKK", (1299.0, "DKK")), ("Sale 30 EUR", (30.0, "EUR")),
    ("NUR 20 CHF", (20.0, "CHF")), ("$45", (45.0, "USD")),
])
def test_waehrung_nur_echte_codes(text, erwartet):
    assert parse_price(text) == erwartet
