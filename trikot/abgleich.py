"""Abgleich mit der Suchliste (watchlist.yaml): Spieler, Sondertrikots, Flock, Größe"""

import re

from .basis import (
    FLOCK_NUM_RX, SIZE_RX, STAR_RX, STAR_TAGS, VARIANT_RX, any_rx, canon_url, hit, norm, plain, season_rxs,
    word_rx, year_rx,
)


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
                "vereine_terms": p.get("vereine") or [],
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
        self.flock_extra = any_rx(cfg.get("flock_erkennung"))
        self.brands = {norm(b): word_rx(b) for b in cfg.get("marken") or [] if norm(b)}
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
                "flock_namen": any_rx(k.get("flock_namen")),   # zusätzliche Flock-Namen nur für diesen Eintrag
                "aus": any_rx(k.get("ausschluss")),
                "marke": norm(k.get("marke") or ""),   # z. B. "nike": Titel mit anderem Ausrüster zählt nicht
            })

    def excluded(self, text):
        return hit(self.exclude, text)

    def type_excluded(self, typ):
        """Produktart des Shops ("Tracktop", "Reissue", "Nameset" ...)"""
        t = norm(typ)
        # "Short" als Produktart ist eine Hose (VFA), im Titel wäre "short" zu riskant ("Short Sleeve")
        return t in ("short", "shorts", "pantalon", "pantalones") or hit(self.exclude, t) or hit(self.nachbau, t)

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
                    or hit(self.flock_extra, t)
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

    def labels(self, text, fyj_reissue=False, desc="", ctx=""):
        """Gibt [(label, prio)] zurück, ohne Größenprüfung. Nachbauten nur als Repro-Flock für repro_labels.
        desc (Beschreibung) wird nur für Artikelcodes der Sondertrikots herangezogen"""
        t = norm(text)
        if not t or self.excluded(t):
            return []
        starred = [x.strip() for x in STAR_RX.findall(str(text)) if not STAR_TAGS.match(x.strip())]
        star = any(not hit(self.flock_ok, norm(x)) for x in starred)
        out = self._labels(t, norm(plain(desc)) if desc else "", star, norm(ctx) if ctx else "")
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

    def _labels(self, t, d="", star=False, c=""):
        """c: Kontext des Shops (Schlagwörter, Produktart, Produktadresse). Zählt nur für den Vereinsfilter der
        Spieler ("Thiago #6 Away Shirt" mit Schlagwort "Liverpool"), nie für Spielernamen oder Sondertrikots"""
        out = []
        for p in self.players:
            if not hit(p["suche"], t) or hit(p["aus"], t):
                continue
            if p["vereine"] and not (hit(p["vereine"], t) or (c and hit(p["vereine"], c))):
                continue
            out.append((p["name"], p["prio"]))
        for k in self.kits:
            if k["codes"] and hit(k["codes"], f"{t} {d}"):     # Artikelcode eindeutig, Variante egal
                if k["fremdflock_egal"] or not self.foreign_flock(t, star):
                    out.append((k["name"], k["prio"]))
                continue
            if not hit(k["verein"], t) or hit(k["aus"], t):
                continue
            if k["marke"] and any(rx.search(t) for b, rx in self.brands.items() if b != k["marke"]):
                continue
            if (k["saisons"] or k["jahre"]) and not (hit(k["saisons"], t) or hit(k["jahre"], t)):
                continue
            if not self._variant_ok(k, t):
                continue
            if not k["fremdflock_egal"] and self.foreign_flock(t, star):
                continue
            if k["flock_pflicht"] and not (self.has_flock(t, star) or hit(k["flock_namen"], t)):
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

    def high_team_terms(self):
        """Vereine/Länder der hoch priorisierten Einträge (Thiago und seine Sondertrikots): für gekappte Kataloge
        werden die passenden Kollektionen komplett gelesen"""
        out = []
        for p in self.players:
            if p["prio"] == "hoch":
                out += p["vereine_terms"]
        for k in self.kits:
            if k["prio"] == "hoch":
                out += k["verein_terms"]
        return list(dict.fromkeys(norm(x) for x in out if norm(x)))

    def team_queries(self):
        out = []
        for k in self.kits:
            if k["verein_terms"]:
                q = k["verein_terms"][0]
                if q not in out:
                    out.append(q)
        return out
