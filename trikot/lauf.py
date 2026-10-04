"""Ein Run von Anfang bis Ende (Modi full, priority, drop, test)"""

import argparse
import concurrent.futures as cf
import datetime as dt
import os
import sys
import threading
import time

import yaml

from . import speicher
from .abgleich import Matcher
from .basis import (
    EINBRUCH_ANTEIL, EINBRUCH_MIN, EINBRUCH_RUNS, ENRICH_BUDGET, FALLBACK_SKIP_HOURS, MAX_PUSH_HIGH,
    MAX_WORKERS, ROOT, RUN_HISTORY, SIZE_RX, canon_url, domain, is_high, norm, now, short_size,
)
from .berichte import fundgrube, log_problems, write_dashboard, write_report
from .issues import add_shops_from_issues, apply_flags, check_alarms
from .melden import OUTBOX_MAX_HOURS, detail_line, push, push_label, save_outbox, send_now, send_outbox, short
from .netz import Http
from .preise import fetch_rates, to_eur
from .pruefung import enrich
from .quellen import run_shop
from .quellen.fyj import fyj_run
from .rhythmus import drop_due
from .speicher import load_json
from .zustand import below_min, condition_info, desc_not_jersey


def recently_done(status_store, mode):
    """Hat ein Run dieses Modus kürzlich stattgefunden? (Sperre für die GitHub-Rückfall-Zeitpläne)"""
    limit = FALLBACK_SKIP_HOURS.get(mode)
    if not limit:
        return False
    times = [l["zeit"] for l in status_store.get("laeufe") or [] if l.get("modus") == mode]
    if mode == "full" and status_store.get("last_full"):
        times.append(status_store["last_full"])
    return any(now() - dt.datetime.fromisoformat(t) < dt.timedelta(hours=limit) for t in times)


def stock_collapse(collapse, name, n_now, n_prev):
    """Bestandseinbruch im Gesamt-Run: Fehlertext oder "". collapse zählt die Gesamt-Runs in Folge je Quelle"""
    if n_prev >= EINBRUCH_MIN and 0 < n_now < n_prev * EINBRUCH_ANTEIL:
        collapse[name] = collapse.get(name, 0) + 1
        if collapse[name] < EINBRUCH_RUNS:
            return (f"Bestandseinbruch: {n_now} statt {n_prev} Produkte "
                    f"({collapse[name]}. Gesamt-Run in Folge), Abruffehler?")
        return ""   # hält an: echter, kleinerer Bestand
    collapse.pop(name, None)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "priority", "drop", "test", "senden"], default="full",
                    help="senden = Postausgang verschicken (Workflow-Schritt nach dem Speichern)")
    ap.add_argument("--dry-run", action="store_true", help="nichts senden, nur ausgeben")
    ap.add_argument("--only", help="nur Shops, deren Name diesen Text enthält (zum Testen)")
    ap.add_argument("--alle", action="store_true",
                    help="nur mit --mode drop: Testdrop, alle Shops gelten als fällig (nur Shopify, Woo, Wix)")
    ap.add_argument("--rueckfall", action="store_true",
                    help="Start über den GitHub-Zeitplan: nur laufen, wenn cron-job.org den Run nicht schon erledigt hat")
    args = ap.parse_args()

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic and not args.dry_run:
        sys.exit("NTFY_TOPIC fehlt (GitHub Secret anlegen) oder --dry-run verwenden.")

    if args.mode == "test":
        entry = {"title": "✅ Trikot-Tracker verbunden", "message": "Wenn du das liest, funktionieren die Benachrichtigungen.",
                 "prio": 4, "tags": ["white_check_mark"]}
        if args.dry_run:
            print(f"[PUSH p4] {entry['title']}\n    {entry['message']}")
        elif not send_now(topic, entry):
            sys.exit("Test-Push wurde von ntfy nicht angenommen")
        return
    if args.mode == "senden":
        sent, left, dropped = send_outbox(topic)
        print(f"Postausgang: {sent} verschickt, {left} offen, {dropped} verworfen (älter als {OUTBOX_MAX_HOURS} Std.)")
        problems = ([("ntfy", f"{left} Push(es) nicht zugestellt, der nächste Run versucht es erneut")] if left else []) + \
                   ([("ntfy", f"{dropped} Push(es) verworfen, älter als {OUTBOX_MAX_HOURS} Std.")] if dropped else [])
        if problems:
            log_problems(problems, "senden", now().isoformat())
        return

    watch = yaml.safe_load((ROOT / "watchlist.yaml").read_text(encoding="utf-8"))
    if args.mode == "full" and not args.only and not args.dry_run:
        n_added = add_shops_from_issues()
        if n_added:
            print(f"{n_added} Shop(s) aus der Fundgrube aufgenommen")
    shops_cfg = yaml.safe_load(speicher.SHOPS_FILE.read_text(encoding="utf-8"))
    matcher = Matcher(watch)
    speicher.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:   # beschädigte Daten: abbrechen statt still neu anfangen (Fehler-Log + Workflow-Fehlschlag)
        seen = load_json(speicher.SEEN_FILE, {}, strict=True)
        status_store = load_json(speicher.STATUS_FILE, {"platforms": {}, "sources_ok": []}, strict=True)
    except speicher.DatenFehler as e:
        log_problems([("Daten", str(e))], args.mode, now().isoformat())
        sys.exit(str(e))
    if args.rueckfall and recently_done(status_store, args.mode):
        print(f"Rückfall-Start übersprungen: {args.mode} lief schon vor kurzem (cron-job.org)")
        return
    platforms = status_store.setdefault("platforms", {})
    currencies = status_store.setdefault("currencies", {})
    sources_ok = set(status_store.setdefault("sources_ok", []))
    # Reissues (Nachbauten) werden seit 01.10.2026 nicht mehr erfasst; gezielt ausgeschlossene
    # Links und zu schlechter Zustand (min_zustand je Shop) fliegen sofort raus
    min_grade = {s["name"]: s["min_zustand"] for s in shops_cfg.get("shops") or [] if s.get("min_zustand")}
    seen = {k: v for k, v in seen.items()
            if "(Reissue)" not in v["title"] and k not in matcher.url_ex
            and not below_min(v.get("zustand", ""), min_grade.get(v["shop"]))}
    first_run = not seen

    shops = shops_cfg.get("shops") or []
    if args.only:
        shops = [s for s in shops if args.only.lower() in s["name"].lower()]
    # Meldungen aus dem Dashboard (GitHub-Issues) in jedem Run übernehmen
    new_flags = apply_flags(seen, status_store, now().isoformat()) if not args.dry_run else 0
    if new_flags:
        print(f"{new_flags} Meldung(en) aus dem Dashboard übernommen")
    if args.mode == "drop":
        # nur Shops, deren Drop gerade läuft; sonst sofort ohne jede Änderung beenden (außer es gab Meldungen)
        if args.alle:
            # Testdrop: alle Shops mit leichtem Drop-Abruf (neueste Artikel), keine Such-Shops (CFS, IdoSell, html …)
            due = {s["name"]: "Testdrop" for s in shops if (s.get("plattform") or "auto").lower() in ("auto", "wix")}
        else:
            due = {s["name"]: drop_due(s, status_store, now()) for s in shops
                   if (s.get("plattform") or "auto").lower() not in ("aus", "fyj")}
        shops = [s for s in shops if due.get(s["name"])]
        if not shops and not new_flags:
            print("Drop-Run: kein Drop fällig")
            return
        if shops:
            print("Drop-Run:", ", ".join(f"{s['name']} {due[s['name']]}" for s in shops))
    # Shops, die direkt abgefragt werden: deren FYJ-Daten ignorieren (direkt ist aktueller und genauer)
    # Ausnahme: Shops, die im letzten Gesamt-Run nicht funktioniert haben, deckt FYJ wieder ab
    failed = {q["name"] for q in (status_store.get("quellen") or {}).get("liste", []) if q.get("fehler")}
    direct_domains = {domain(s["url"]) for s in shops_cfg.get("shops") or []
                      if (s.get("plattform") or "auto").lower() not in ("fyj", "aus") and s["name"] not in failed}
    # Gesperrte Shops (sperren: ja) auch bei FYJ ignorieren, z. B. wegen durchweg schlechtem Zustand
    direct_domains |= {domain(s["url"]) for s in shops_cfg.get("shops") or []
                       if str(s.get("sperren", "")).lower() in ("ja", "true", "yes")}
    use_fyj = (str(shops_cfg.get("fyj", "an")).lower() in ("an", "true", "ja", "on") and not args.only
               and args.mode != "drop")

    flagged = set(status_store.get("flags") or {})
    # Neu angelegte Kategorien (Labels) beim ersten Gesamt-Run still übernehmen, sonst Push-Flut
    all_labels = {p["name"] for p in matcher.players} | {k["name"] for k in matcher.kits}
    known_labels = set(status_store.get("known_labels") or all_labels)   # erster Start: alles bekannt
    new_labels = all_labels - known_labels
    lock = threading.Lock()
    results, statuses, fyj_status = [], [], None
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_shop, s, args.mode, matcher, platforms, currencies): s for s in shops}
        fyj_fut = None
        if use_fyj:
            def fyj_job():
                http = Http()
                t0 = time.time()
                st = {"name": "FindYourJersey", "plattform": "fyj", "produkte": 0, "fehler": ""}
                try:
                    its, n = fyj_run(http, matcher, args.mode == "priority", direct_domains)
                    st["produkte"] = n
                    if n == 0 and args.mode == "full":
                        st["fehler"] = "keine Daten erhalten (Schnittstelle geändert oder gesperrt?)"
                    return its, st
                except Exception as e:
                    st["fehler"] = f"{type(e).__name__}: {str(e)[:120]}"
                    return [], st
                finally:
                    if http.limited and not st["fehler"]:
                        st["fehler"] = f"unvollständig, {http.limited}x gedrosselt (HTTP 429)"
                    st["anfragen"] = http.count
                    st["sekunden"] = round(time.time() - t0, 1)
            fyj_fut = ex.submit(fyj_job)
        for f in cf.as_completed(list(futs) + ([fyj_fut] if fyj_fut else [])):
            its, st = f.result()
            with lock:
                results.append((st["name"], its, st))
                if f is fyj_fut:
                    fyj_status = st
                else:
                    statuses.append(st)

    # Treffer auswerten
    ts = now().isoformat()
    rates = fetch_rates(status_store)["rates"]
    pg = watch.get("preisgrenze") or {}
    max_eur = float(pg.get("max_eur") or 0)
    no_limit = set(pg.get("ausnahmen") or [])

    def too_expensive(e):
        eur = to_eur(e.get("price"), rates)
        return bool(max_eur and eur and eur > max_eur and not no_limit & set(e["labels"]))
    new_entries = []
    counts = status_store.setdefault("counts", {})
    collapse = status_store.setdefault("einbruch", {})
    for src_name, its, st in results:
        n_now, n_prev = st.get("produkte", 0), counts.get(src_name, 0)
        # Bestand plötzlich unter der Hälfte: eher ein Abruffehler (Seite geändert, halb gesperrt) als ein echter
        # Ausverkauf. Dann als Fehler werten: Treffer werden nicht als "weg" ausgeblendet, FYJ springt ein.
        # Hält es EINBRUCH_RUNS Gesamt-Runs an, ist es echt und der neue Bestand gilt
        if args.mode == "full" and not st.get("fehler"):
            st["fehler"] = stock_collapse(collapse, src_name, n_now, n_prev)
        works = args.mode == "full" and st.get("produkte", 0) > 0 and not st.get("fehler")
        # Neue Quelle ODER Bestand plötzlich viel größer (z. B. vorher abgeschnitten):
        # dann still übernehmen statt eine Flut an "neuen" Treffern zu melden
        jump = works and n_prev and n_now > n_prev * 1.3 and n_now - n_prev > 200
        fresh_source = works and (src_name not in sources_ok or jump)
        if args.mode != "full" and src_name not in sources_ok:
            fresh_source = True   # noch nie im Gesamt-Run gewesen: Bestand still übernehmen
        if works:
            sources_ok.add(src_name)
            counts[src_name] = n_now
        for it in its:
            if it.get("typ") and matcher.type_excluded(it["typ"]):
                continue
            if it["url"] and (canon_url(it["url"]) in matcher.url_ex or canon_url(it["url"]) in flagged):
                continue
            if it.get("desc") and it.get("source") == "direkt" and desc_not_jersey(it["desc"], it["title"]) \
                    and it.get("desc") != it.get("title"):
                continue
            if it.get("desc") and it.get("source") == "direkt" and matcher.repro_flock(it["desc"]):
                it["fyj_reissue"] = it["desc_repro"] = True   # wie FYJ-Reissue: nur Thiago/erlaubte Kategorien
            labs = matcher.labels(it["match_text"], it.get("fyj_reissue", False), it.get("desc", ""))
            if not labs or not matcher.size_ok(it["size_text"], norm(it["match_text"])):
                continue
            if not it["url"]:
                continue
            key = canon_url(it["url"])
            size = SIZE_RX.search(norm(it["size_text"]))
            grade, note = condition_info(it["title"], it.get("desc"), it.get("fyj_condition", ""))
            if below_min(grade, min_grade.get(it["shop"])):
                continue
            entry = seen.get(key)
            if entry:
                # Labels pro Lauf neu berechnen (sonst bleiben alte Regeln ewig hängen),
                # innerhalb eines Laufs aus mehreren Quellen zusammenführen
                if entry["last"] != ts:
                    entry["labels"], entry["prios"] = [], []
                entry["last"] = ts
                entry.pop("weg", None)
                entry["labels"] = sorted(set(entry["labels"]) | {l for l, _ in labs})
                entry["prios"] = sorted(set(entry["prios"]) | {p for _, p in labs})
                if it["source"] == "direkt":      # direkte Daten sind aktueller als FYJ
                    entry.update(price=it["price"] or entry.get("price", ""), shop=it["shop"], via="direkt")
                    if it.get("pruefen"):
                        entry["pruefen"] = True
                    entry.pop("verkauft", None)
                    if grade:
                        entry["zustand"] = grade
                    if note:
                        entry["zustand_notiz"] = note
                elif grade and not entry.get("zustand"):
                    entry["zustand"] = grade
                if it["source"] == entry.get("via"):
                    entry["title"] = it["title"]
                continue
            entry = {"title": it["title"], "url": it["url"], "shop": it["shop"],
                     "price": it["price"], "image": it["image"],
                     "size": short_size(size.group(0)) if size else "",
                     "labels": sorted({l for l, _ in labs}), "prios": sorted({p for _, p in labs}),
                     "first": ts, "last": ts, "via": it["source"]}
            if grade:
                entry["zustand"] = grade
            if note:
                entry["zustand_notiz"] = note
            if it.get("pruefen"):
                entry["pruefen"] = True
            if matcher.repro_flock(it["match_text"]) or it.get("desc_repro") \
                    or (it.get("fyj_reissue") and "Thiago" in entry["labels"]):
                entry["repro"] = True
            elif it.get("fyj_reissue") or matcher.reissue(it["match_text"]):
                entry["reissue"] = True
            seen[key] = entry
            if first_run or fresh_source or (new_labels and set(entry["labels"]) <= new_labels):
                entry["still"] = True   # ohne Push übernommen (Erstlauf, neue Quelle oder neue Kategorie)
            else:
                new_entries.append(entry)

    # Fundgrube: Shops, die nur über FYJ Treffer liefern (Kandidaten für direkte Anbindung)
    if args.mode == "full" and fyj_status and not fyj_status.get("fehler"):
        found = {}
        for e in seen.values():
            if e["last"] == ts and e.get("via") == "fyj" and not e.get("verkauft"):
                found[domain(e["url"])] = found.get(domain(e["url"]), 0) + 1
        old = status_store.get("fyj_shops") or {}
        status_store["fyj_shops"] = {d: {"treffer": c, "seit": (old.get(d) or {}).get("seit", ts)}
                                     for d, c in sorted(found.items(), key=lambda x: -x[1])}

    # Gesamtlauf: Treffer, die eine erfolgreich abgefragte Quelle nicht mehr liefert (verkauft oder
    # passt nach Regeländerung nicht mehr), sofort ausblenden statt erst nach REPORT_HOURS
    if args.mode == "full" and not args.only:
        ok_src = {st["name"] for _, _, st in results if not st.get("fehler")}
        for e in seen.values():
            src = "FindYourJersey" if e.get("via") == "fyj" else e["shop"]
            if e["last"] != ts and src in ok_src:
                e.setdefault("weg", ts)
            elif e["last"] == ts:
                e.pop("weg", None)

    # FYJ-Treffer auf der Shop-Seite prüfen (verkauft? Zustand?), neue zuerst, vor den Pushes
    checked = enrich(seen, ts, ENRICH_BUDGET.get(args.mode, 0), matcher)
    for e in seen.values():
        if e["last"] == ts:
            e["teuer"] = too_expensive(e)
    new_entries = [e for e in new_entries if not e.get("verkauft") and not e.get("teuer") and not e.get("aussortiert")]
    laeufe = status_store.setdefault("laeufe", [])
    laeufe.append({"zeit": ts, "modus": args.mode, "neu": len(new_entries),
                   "still": sum(1 for e in seen.values() if e["first"] == ts and e.get("still"))})
    del laeufe[:-RUN_HISTORY]

    # Benachrichtigen
    repo = os.environ.get("GITHUB_REPOSITORY")
    if os.environ.get("DASHBOARD_URL"):
        report_url = os.environ["DASHBOARD_URL"].rstrip("/") + "/#eingaenge"
    else:
        report_url = f"https://github.com/{repo}/blob/main/TREFFER.md" if repo else None
    if first_run:
        # Erstlauf: genau EINE Nachricht, alles andere steht in TREFFER.md
        cur = [e for e in seen.values() if e["last"] == ts]
        high = [e for e in cur if is_high(e)]
        lines = [f"• {push_label(e)}: {short(e)}" for e in high[:12]]
        more = f"\n… und {len(high) - 12} weitere" if len(high) > 12 else ""
        push(topic, f"🚀 Tracker gestartet: {len(cur)} Treffer",
             f"Davon {len(high)} Thiago/Sondertrikots:\n" + "\n".join(lines) + more +
             "\nAb jetzt kommen nur noch neue Trikots.",
             3, report_url, None, ["rocket"], args.dry_run)
    else:
        high = sorted([e for e in new_entries if is_high(e)], key=lambda e: e["title"])
        normal = sorted([e for e in new_entries if not is_high(e)], key=lambda e: e["title"])
        # Thiago & Sondertrikots einzeln (max. MAX_PUSH_HIGH), Rest gebündelt
        for e in high[:MAX_PUSH_HIGH]:
            push(topic, f"🔥 {push_label(e)} · {e['shop']}",
                 detail_line(e),
                 5, e["url"], e["image"], ["fire"], args.dry_run)
        bundle = high[MAX_PUSH_HIGH:] + normal
        if len(bundle) == 1:
            e = bundle[0]
            push(topic, f"⚽ {push_label(e)} · {e['shop']}",
                 detail_line(e),
                 3, e["url"], e["image"], ["soccer"], args.dry_run)
        elif bundle:
            push(topic, f"⚽ {len(bundle)} neue Treffer",
                 "\n".join(f"• {push_label(e)}: {short(e, shop=True)}"
                           for e in bundle[:20]) +
                 (f"\n… und {len(bundle) - 20} weitere" if len(bundle) > 20 else ""),
                 3, report_url, None, ["soccer"], args.dry_run)

    # Fundgrube wöchentlich (nach der Auswertung der FYJ-Treffer in diesem Gesamt-Run)
    if args.mode == "full" and not args.only and fyj_status and not fyj_status.get("fehler"):
        cands = fundgrube(status_store, shops_cfg.get("shops") or [], ts)
        good = [c for c in cands or [] if c["empfohlen"]]
        if good:
            fg_url = (os.environ.get("DASHBOARD_URL") or "").rstrip("/") + "/#fundgrube" if os.environ.get("DASHBOARD_URL") else report_url
            push(topic, f"🔎 Fundgrube: {len(good)} Shop-Kandidat{'en' if len(good) != 1 else ''} zum Aufnehmen",
                 "\n".join(f"• {c['domain']}: {c['treffer']} Treffer · {c['plattform']}" for c in good[:10]) +
                 "\nIm Dashboard unter Fundgrube auf \"Aufnehmen\" tippen.", 2, fg_url, None, ["mag"], args.dry_run)

    # Preisalarme für Favoriten
    if not args.only:
        check_alarms(seen, status_store, ts, rates, args.mode,
                     lambda title, msg, prio, url: push(topic, title, msg, prio, url, None, ["bell"], args.dry_run))

    # Still übernommene Treffer (neue Shops, neue Kategorien): EINE Sammelnachricht statt Push-Flut
    silent = [e for e in seen.values() if e["first"] == ts and e.get("still")
              and not (e.get("verkauft") or e.get("teuer") or e.get("aussortiert"))]
    if silent and not first_run:
        silent.sort(key=lambda e: (not is_high(e), e["labels"], e["title"]))
        srcs = sorted({e["shop"] for e in silent})
        push(topic, f"🆕 {len(silent)} Treffer aus neuen Shops/Kategorien",
             f"Aus {len(srcs)} Quellen: {', '.join(srcs[:8])}{' …' if len(srcs) > 8 else ''}\n" +
             "\n".join(f"• {push_label(e)}: {short(e, shop=True)}" for e in silent[:15]) +
             (f"\n… und {len(silent) - 15} weitere" if len(silent) > 15 else ""),
             3, report_url, None, ["new"], args.dry_run)

    # Aufräumen: Einträge, die 60 Tage nicht mehr gesehen wurden, vergessen
    old = now() - dt.timedelta(days=60)
    seen = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v["last"]) >= old}

    speicher.save_json(speicher.SEEN_FILE, seen)
    if args.mode == "full" and not args.only:
        status_store["known_labels"] = sorted(all_labels)
    elif "known_labels" not in status_store:
        status_store["known_labels"] = sorted(known_labels)
    if args.mode == "drop":
        status_store.setdefault("drop_checks", {}).update({s["name"]: ts for s in shops})
    status_store["sources_ok"] = sorted(sources_ok)
    status_store["last_run"] = {"mode": args.mode, "time": ts}
    run_sources = ([fyj_status] if fyj_status else []) + sorted(statuses, key=lambda s: (not s["fehler"], s["name"]))
    if args.mode == "full" and not args.only:
        status_store["last_full"] = ts
        # Quellen-Status des Gesamtlaufs merken, damit ihn der Schnellcheck nicht überschreibt
        status_store["quellen"] = {"zeit": ts, "liste": run_sources}
    speicher.save_json(speicher.STATUS_FILE, status_store)
    full_src = status_store.get("quellen") or {}
    if full_src:
        write_report(seen, full_src["liste"], full_src["zeit"], args.mode)
    else:
        write_report(seen, run_sources, "", args.mode)
    write_dashboard(seen, status_store, args.mode, ts, watch, shops_cfg.get("shops") or [])
    problems = [(s["name"], s["fehler"]) for s in run_sources
                if s.get("fehler") and not str(s["fehler"]).startswith("deaktiviert")]
    log_problems(problems, args.mode, ts)

    ok = sum(1 for s in statuses if not s["fehler"])
    print(f"Fertig ({args.mode}): {ok}/{len(statuses)} Shops ok, FYJ: "
          f"{(fyj_status or {}).get('fehler') or 'ok' if fyj_status else 'aus'}, "
          f"{len(new_entries)} neue Treffer, {checked} Seiten geprüft, Erstlauf: {first_run}")
    for s in statuses:
        if s["fehler"]:
            print(f"  - {s['name']}: {s['fehler']}")
    if args.mode == "drop" and args.alle:
        bad = [s["name"] for s in statuses if s["fehler"]]
        push(topic, "🧪 Testdrop fertig",
             f"{ok}/{len(statuses)} Shops ok, {len(new_entries)} neue Treffer"
             + (f". Probleme: {', '.join(bad[:8])}" + (" …" if len(bad) > 8 else "") if bad else ""),
             2, click=report_url, tags=["test_tube"], dry=args.dry_run)
    # Pushes erst jetzt in den Postausgang schreiben; verschickt werden sie nach dem Speichern
    n_out = save_outbox()
    if n_out:
        print(f"{n_out} Push(es) im Postausgang, Versand nach dem Speichern")
