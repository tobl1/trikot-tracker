"""Ausgaben: Dashboard-Daten, TREFFER.md, Fehler-Log, Fundgrube"""

import datetime as dt
import json

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


def write_dashboard(seen, status_store, mode, ts, watch_cfg, shops):
    """docs/treffer.json für das Dashboard auf GitHub Pages"""
    kurse = status_store.get("kurse") or {}
    rates = kurse.get("rates") or {"EUR": 1.0}
    items = []
    for key, e in current_entries(seen).items():
        items.append({
            "id": key, "titel": e["title"], "url": e["url"], "shop": e["shop"],
            "preis": e.get("price", ""), "eur": to_eur(e.get("price"), rates),
            "groesse": short_size(e.get("size", "")), "labels": e["labels"], "hoch": is_high(e),
            "zustand": e.get("zustand", ""), "notiz": e.get("zustand_notiz", ""), "bild": e.get("image", ""),
            "erst": e["first"], "zuletzt": e["last"], "via": e.get("via", ""),
            "still": bool(e.get("still")), "teuer": bool(e.get("teuer")), "repro": bool(e.get("repro")), "reissue": bool(e.get("reissue")),
        })
    quellen = status_store.get("quellen") or {}
    data = {"stand": ts, "modus": mode, "letzter_gesamtlauf": status_store.get("last_full", ""),
            "fyj_shops": status_store.get("fyj_shops") or {},
            "fundgrube": status_store.get("fundgrube") or {},
            "laeufe": status_store.get("laeufe") or [],
            "drops": drop_calendar(shops, status_store),
            "preisgrenze": (watch_cfg.get("preisgrenze") or {}),
            "kurse_datum": kurse.get("datum", ""), "treffer": items,
            "quellen": quellen.get("liste", []), "quellen_stand": quellen.get("zeit", "")}
    speicher.DASHBOARD_FILE.parent.mkdir(exist_ok=True)
    speicher.DASHBOARD_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


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
    speicher.REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    speicher.ERROR_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
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
    speicher.ERROR_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    speicher.FUNDGRUBE_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cands
