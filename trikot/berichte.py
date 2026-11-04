"""Ausgaben: Dashboard-Daten, TREFFER.md, Fehler-Log, Fundgrube"""

import datetime as dt

import requests

from . import speicher
from . import quellen
from .basis import (
    ERROR_KEEP_DAYS, FUNDGRUBE_DAYS, FUNDGRUBE_MAX, FUNDGRUBE_MAX_REISSUE, FYJ_MARKETPLACES, REPORT_HOURS, TZ,
    domain, is_high, now, short_size,
)
from .preise import to_eur
from .quellen.fyj import FYJ_DOMAIN_STATS
from .rhythmus import drop_calendar
from .speicher import load_json


def current_entries(seen):
    """{Schlüssel: Eintrag} aller Treffer, die in den letzten REPORT_HOURS gesehen wurden"""
    cutoff = now() - dt.timedelta(hours=REPORT_HOURS)
    return {k: e for k, e in seen.items()
            if dt.datetime.fromisoformat(e["last"]) >= cutoff
            and not (e.get("verkauft") or e.get("weg") or e.get("aussortiert"))}


def doubt(e):
    """Hinweis, wenn Angaben eines Treffers wackelig sind (Dashboard-Markierung "prüfen"), sonst """""
    if e.get("push_offen"):
        return "Shop-Seite wird noch geprüft"
    if e.get("ungeprueft"):
        return "Shop-Seite ließ sich nicht prüfen"
    if e.get("groesse_quelle") == "schlagwort":
        return "Größe nur aus einem Schlagwort des Shops, nicht aus Titel oder Auswahl"
    return ""


def write_dashboard(seen, status_store, mode, ts, watch_cfg, shops):
    """docs/treffer.json für das Dashboard auf GitHub Pages"""
    kurse = status_store.get("kurse") or {}
    rates = kurse.get("rates") or {"EUR": 1.0}
    items = []
    for key, e in current_entries(seen).items():
        if e.get("teuer"):
            continue   # über der Preisgrenze: konsequent raus (Nutzer 09.10.2026)
        items.append({
            "id": key, "titel": e["title"], "url": e["url"], "shop": e["shop"],
            "preis": e.get("price", ""), "eur": to_eur(e.get("price"), rates),
            "groesse": short_size(e.get("size", "")), "labels": e["labels"], "hoch": is_high(e),
            "zustand": e.get("zustand", ""), "notiz": e.get("zustand_notiz", ""), "bild": e.get("image", ""),
            "erst": e["first"], "zuletzt": e["last"], "via": e.get("via", ""),
            "still": bool(e.get("still")), "teuer": bool(e.get("teuer")), "repro": bool(e.get("repro")), "reissue": bool(e.get("reissue")),
            "warum": "; ".join(f"{l}: {r}" for l, r in (e.get("warum") or {}).items() if l in e["labels"]),
            "pruefen": doubt(e), "offen": bool(e.get("push_offen")),   # offen: Push steht noch aus
            "preis_runter": (e.get("preis_runter") or {}).get("prozent", 0),
            "preis_zeit": (e.get("preis_runter") or {}).get("zeit", ""),   # Run, in dem der Preis fiel
            "unter_grenze": e.get("unter_grenze", ""),                      # Run, in dem er unter die Grenze fiel
        })
    quellen = status_store.get("quellen") or {}
    data = {"stand": ts, "modus": mode, "letzter_gesamtlauf": status_store.get("last_full", ""),
            "fyj_shops": status_store.get("fyj_shops") or {},
            "fundgrube": status_store.get("fundgrube") or {},
            "push_links": status_store.get("push_links") or {},   # Sammel-Pushes -> Trikots (App: #push=<Kennung>)
            "laeufe": status_store.get("laeufe") or [],
            "drops": drop_calendar(shops, status_store),
            # Neukunden-Rabatte laut Shop-Seite (shops.yaml, Nutzer 15.10.2026), App ordnet per Name oder Domain zu
            "rabatte": [{"shop": s["name"], "host": speicher._host(s["url"]), "text": s["rabatt"]}
                        for s in shops if s.get("rabatt")],
            "versand": [{"shop": s["name"], "host": speicher._host(s["url"]), "text": s["versand"]}
                        for s in shops if s.get("versand")],
            "preisgrenze": (watch_cfg.get("preisgrenze") or {}),
            "kurse_datum": kurse.get("datum", ""), "treffer": items,
            "push_abos": len(status_store.get("push_abos") or {}),   # 0: Dashboard warnt (keine Pushes)
            "quellen": quellen.get("liste", []), "quellen_stand": quellen.get("zeit", "")}
    speicher.DASHBOARD_FILE.parent.mkdir(exist_ok=True)
    speicher.save_json(speicher.DASHBOARD_FILE, data, compact=True)


def write_report(seen, sources, sources_time, mode):
    current = [e for e in current_entries(seen).values() if not e.get("teuer")]
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
        lines += [f"## {lab} ({len(es)})", "", "| Trikot | Größe | Zustand | Preis | Shop | seit |",
                  "|---|---|---|---|---|---|"]
        for e in es:
            t = e["title"].replace("|", "/")
            size = (e.get("size") or "").replace("|", "/")[:25]
            first = dt.datetime.fromisoformat(e["first"]).astimezone(TZ)
            cond = (e.get("zustand") or "").replace("|", "/")
            lines.append(f"| [{t}]({e['url']}) | {size} | {cond} | {e.get('price', '')} | {e['shop']} | {first:%d.%m.} |")
        lines.append("")
    when = dt.datetime.fromisoformat(sources_time).astimezone(TZ) if sources_time else None
    lines += ["## Quellen-Status", "",
              f"Vom letzten Gesamt-Run ({when:%d.%m.%Y %H:%M} Uhr)" if when else "Vom aktuellen Run", "",
              "| Quelle | System | Produkte | Anfragen | Hinweis |", "|---|---|---|---|---|"]
    for s in sources:
        lines.append(f"| {s['name']} | {s.get('plattform', '')} | {s.get('produkte', 0)} | "
                     f"{s.get('anfragen', '')} | {s.get('fehler') or s.get('info') or 'ok'} |")
    speicher.save_text(speicher.REPORT_FILE, "\n".join(lines) + "\n")


def log_problems(problems, mode, ts):
    """Probleme sammeln: gleiche (Quelle, Meldung) zusammengefasst mit erstem/letztem Auftreten und Anzahl.
    FEHLER.md ist die lesbare Fassung; Claude liest sie bei jeder neuen Anfrage (siehe CLAUDE.md)"""
    log = load_json(speicher.ERROR_LOG, {})
    for quelle, meldung in problems:
        key = f"{quelle}|{meldung}"
        e = log.setdefault(key, {"quelle": quelle, "meldung": meldung, "erst": ts, "anzahl": 0, "modi": []})
        e["letzt"] = ts
        e["anzahl"] += 1
        if mode not in e["modi"]:
            e["modi"].append(mode)
    cutoff = now() - dt.timedelta(days=ERROR_KEEP_DAYS)
    log = {k: v for k, v in log.items() if dt.datetime.fromisoformat(v["letzt"]) >= cutoff}
    speicher.save_json(speicher.ERROR_LOG, log)
    rows = sorted(log.values(), key=lambda v: v["letzt"], reverse=True)
    fmt = lambda t: dt.datetime.fromisoformat(t).astimezone(TZ).strftime("%d.%m. %H:%M")
    lines = ["# Fehler-Log", "",
             f"Probleme der letzten {ERROR_KEEP_DAYS} Tage, zusammengefasst. Stand {fmt(ts)} Uhr. "
             "Wird bei jedem Run aktualisiert und von Claude bei jeder neuen Anfrage gelesen.", "",
             "| zuletzt | seit | Anzahl | Quelle | Meldung | Runs |", "|---|---|---|---|---|---|"]
    for v in rows:
        lines.append(f"| {fmt(v['letzt'])} | {fmt(v['erst'])} | {v['anzahl']} | {v['quelle']} | "
                     f"{str(v['meldung']).replace('|', '/')} | {', '.join(v['modi'])} |")
    if not rows:
        lines.append("| | | | | keine Probleme | |")
    speicher.save_text(speicher.ERROR_REPORT, "\n".join(lines) + "\n")


def fyj_haendler(status_store, shops, ts):
    """FYJ-Händlerliste mit dem Stand der Vorwoche vergleichen. Gibt (alle, neu, weg) zurück, neu und weg mit
    Hinweis, wie der Händler bei uns läuft; neu/weg zählen 30 Tage. Beim ersten Abgleich gilt niemand als neu"""
    liste = quellen.fyj.fyj_retailers()
    st = status_store.setdefault("fyj_haendler", {})
    alt, weg = st.get("liste") or {}, st.setdefault("weg", {})
    if liste:
        st["liste"] = {d: alt[d] if d in alt else (ts if alt else "") for d in liste}
        weg.update({d: ts for d in alt if d not in st["liste"]})
    cutoff = now() - dt.timedelta(days=30)
    for d in list(weg):
        if d in (st.get("liste") or {}) or dt.datetime.fromisoformat(weg[d]) < cutoff:
            del weg[d]
    bare = lambda u: (lambda d: d[4:] if d.startswith("www.") else d)(domain(u) if "/" in u else u.lower())
    ours = {bare(s["url"]): s for s in shops}

    def bei_uns(d):
        s = ours.get(bare(d))
        if not s:
            return "Marktplatz" if any(m in d for m in FYJ_MARKETPLACES) or d.endswith("-ebay") else "nicht angebunden"
        plat = (s.get("plattform") or "auto").lower()
        return "gesperrt" if s.get("sperren") else {"aus": "bewusst aus", "fyj": "nur über FYJ"}.get(plat, "direkt")
    neu = [(d, bei_uns(d)) for d, t in sorted((st.get("liste") or {}).items())
           if t and dt.datetime.fromisoformat(t) >= cutoff]
    return len(st.get("liste") or {}), neu, [(d, bei_uns(d)) for d in sorted(weg)]


def fundgrube(status_store, shops, ts, force=False):
    """Wöchentlich: Shops, die nur über FYJ Treffer liefern, prüfen (System, Nachbau-Anteil) und als
    Kandidaten für die direkte Anbindung merken. Gibt die Kandidaten zurück, wenn neu berechnet"""
    last = (status_store.get("fundgrube") or {}).get("zeit")
    if not force and last and now() - dt.datetime.fromisoformat(last) < dt.timedelta(days=FUNDGRUBE_DAYS):
        return None
    known = {domain(s["url"]) for s in shops}
    known |= {d[4:] if d.startswith("www.") else d for d in known}
    found = sorted((status_store.get("fyj_shops") or {}).items(), key=lambda kv: -kv[1]["treffer"])
    cands = []
    for dom, info in found:
        if dom in known or any(m in dom for m in FYJ_MARKETPLACES) or len(cands) >= FUNDGRUBE_MAX:
            continue
        plat = "unbekannt"
        for base in (f"https://{dom}", f"https://www.{dom}"):
            try:
                plat = quellen.detect_platform(base)
            except requests.RequestException:
                plat = "unbekannt"
            if plat != "unbekannt":
                break
        rows, reissue = FYJ_DOMAIN_STATS.get(dom, [0, 0])
        share = round(100 * reissue / rows) if rows else None
        cands.append({"domain": dom, "url": base if plat != "unbekannt" else f"https://{dom}",
                      "treffer": info["treffer"], "seit": info.get("seit", ts), "plattform": plat,
                      "nachbau_prozent": share,
                      "empfohlen": plat != "unbekannt" and (share or 0) < FUNDGRUBE_MAX_REISSUE})
    status_store["fundgrube"] = {"zeit": ts, "kandidaten": cands}
    fmt = lambda t: dt.datetime.fromisoformat(t).astimezone(TZ).strftime("%d.%m.%Y")
    lines = ["# Fundgrube", "", f"Shops, die nur über FindYourJersey Treffer liefern. Stand {fmt(ts)}, "
             "wird wöchentlich im Gesamt-Run aktualisiert. Aufnehmen über das Dashboard (Knopf \"Aufnehmen\").", "",
             "| Shop | Treffer | System | Nachbauten laut FYJ | Empfehlung |", "|---|---|---|---|---|"]
    for c in cands:
        lines.append(f"| [{c['domain']}]({c['url']}) | {c['treffer']} | {c['plattform']} | "
                     f"{'?' if c['nachbau_prozent'] is None else str(c['nachbau_prozent']) + ' %'} | "
                     f"{'anbindbar' if c['empfohlen'] else 'eher nicht' if c['plattform'] != 'unbekannt' else 'System unklar'} |")
    if not cands:
        lines.append("| | | | | keine Kandidaten |")
    # Händlerliste von FYJ: Neuzugänge sind Kandidaten für die direkte Anbindung (Nutzer 02.11.2026)
    alle, neu, weg = fyj_haendler(status_store, shops, ts)
    lines += ["", "## Händlerliste von FindYourJersey", "",
              f"{alle} Händler bei FYJ, verglichen mit der Vorwoche (neu und weg zählen 30 Tage)." if alle else
              "Händlerliste nicht abrufbar.", ""]
    for head, rows in (("Neu bei FYJ", neu), ("Nicht mehr bei FYJ", weg)):
        lines.append(f"**{head}:** " + (", ".join(f"{d} ({h})" for d, h in rows) if rows else "keine"))
        lines.append("")
    speicher.save_text(speicher.FUNDGRUBE_REPORT, "\n".join(lines) + "\n")
    return cands
