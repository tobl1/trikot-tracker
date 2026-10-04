"""Drop-Rhythmus der Shops und fällige Drops"""

import datetime as dt
import re
from zoneinfo import ZoneInfo

from .basis import (
    BATCH_GAP_MIN, BATCH_MIN, DROP_DAY_MIN, DROP_DAY_SHARE, DROP_LEAD_MIN, DROP_MAX_SPREAD_MIN,
    DROP_MIN_GAP_DAYS, DROP_MIN_SHARE, DROP_RECHECK_MIN, DROP_WINDOW_MIN, RHYTHM_DAYS, TZ, now,
)


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def rhythm(stamps):
    """Wann stellt ein Shop neue Artikel ein? Schub = viele Artikel kurz hintereinander"""
    t = now()
    ds = []
    for x in stamps:
        try:
            d = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo and t - dt.timedelta(days=RHYTHM_DAYS) <= d <= t:
            ds.append(d)
    ds.sort()
    out = {"neu_7": sum(d >= t - dt.timedelta(days=7) for d in ds),
           "neu_30": sum(d >= t - dt.timedelta(days=30) for d in ds),
           "tage_30": len({d.astimezone(TZ).date() for d in ds if d >= t - dt.timedelta(days=30)}),
           "letzte": ds[-1].isoformat() if ds else ""}
    batches = []
    for d in ds:
        if batches and d - batches[-1][-1] <= dt.timedelta(minutes=BATCH_GAP_MIN):
            batches[-1].append(d)
        else:
            batches.append([d])
    big = [b for b in batches if len(b) >= BATCH_MIN]
    share = sum(len(b) for b in big) / len(ds) if ds else 0
    if not out["neu_30"]:
        out["typ"], out["text"] = "ruhig", f"seit 30 Tagen nichts Neues ({len(ds)} in {RHYTHM_DAYS} Tagen)"
        return out
    starts = [b[0].astimezone(TZ) for b in big]
    gaps = sorted((b - a).total_seconds() / 86400 for a, b in zip(starts, starts[1:]))
    gap = gaps[len(gaps) // 2] if gaps else 0
    if len(big) >= 2 and share >= 0.6 and gap >= DROP_MIN_GAP_DAYS:
        # pro Wochentag mit genug Schüben einen Termin (manche Shops droppen z. B. Di und Fr)
        termine = []
        for wd in range(7):
            dom = [s for s in starts if s.weekday() == wd]
            if len(dom) < DROP_DAY_MIN or len(dom) / len(big) < DROP_DAY_SHARE:
                continue
            mins = sorted(s.hour * 60 + s.minute for s in dom)
            med = mins[len(mins) // 2]
            recent = sorted(s.hour * 60 + s.minute for s in dom[-4:])
            shifted = len(dom) >= 6 and abs(recent[len(recent) // 2] - med) > 60
            if shifted:   # Uhrzeit hat sich zuletzt verschoben: die letzten Drops zählen
                med, mins = recent[len(recent) // 2], recent
            spread = (mins[(3 * len(mins)) // 4] - mins[len(mins) // 4]) // 2
            termine.append({"tag": WEEKDAYS[wd], "uhrzeit": med // 60, "minute": med % 60, "streuung_min": spread,
                            "anzahl": len(dom), "verschoben": shifted})
        termine.sort(key=lambda x: -x["anzahl"])
        top = termine[0] if termine else {"tag": WEEKDAYS[starts[-1].weekday()], "uhrzeit": starts[-1].hour,
                                           "minute": 0, "streuung_min": 0, "anzahl": 1, "verschoben": False}
        out.update(typ="drops", schuebe=len(big), abstand_tage=round(gap, 1), termine=termine,
                   wochentag=top["tag"], uhrzeit=top["uhrzeit"], minute=top["minute"],
                   anteil=round(sum(x["anzahl"] for x in termine) / len(big), 2),
                   letzter_schub=big[-1][0].isoformat())
        parts = [f"{x['tag']} gegen {x['uhrzeit']:02d}:{x['minute']:02d} (±{x['streuung_min']} Min., {x['anzahl']}x"
                 + (", zuletzt verschoben" if x["verschoben"] else "") + ")" for x in termine]
        out["text"] = (f"Drops etwa alle {gap:.0f} Tage: " + ("; ".join(parts) or "kein fester Wochentag")
                       + f"; {len(big)} Schübe in {RHYTHM_DAYS} Tagen, zuletzt {starts[-1]:%d.%m. %H:%M}")
    elif out["tage_30"] >= 8:
        out["typ"] = "laufend"
        out["text"] = (f"laufend: an {out['tage_30']} von 30 Tagen neue Artikel, "
                       f"{out['neu_7']} in 7 Tagen, {out['neu_30']} in 30 Tagen")
    else:
        out["typ"] = "unregelmäßig"
        out["text"] = (f"unregelmäßig: an {out['tage_30']} von 30 Tagen neue Artikel, "
                       f"{out['neu_30']} in 30 Tagen, zuletzt {ds[-1].astimezone(TZ):%d.%m.}")
    return out


def drop_slots(shop, status_store):
    """[(Wochentag 0-6, Stunde, Minute, Quelle, Fenster in Min.)]: fest aus shops.yaml plus gemessen"""
    slots = []
    for x in drop_specs(shop):
        slot = fixed_slot(x)
        if slot:
            slots.append((*slot, "fest", DROP_WINDOW_MIN))
    for q in (status_store.get("quellen") or {}).get("liste", []):
        r = q.get("rhythmus") or {}
        if q.get("name") != shop["name"] or r.get("typ") != "drops" or r.get("anteil", 0) < DROP_MIN_SHARE:
            continue
        termine = r.get("termine") or [{"tag": r["wochentag"], "uhrzeit": r["uhrzeit"],
                                        "minute": r.get("minute", 0), "streuung_min": r.get("streuung_min", 0)}]
        for x in termine:
            # etwas vor der typischen Zeit beginnen, bei großer Streuung entsprechend früher und länger
            early = DROP_LEAD_MIN + min(int(x.get("streuung_min", 0)), DROP_MAX_SPREAD_MIN)
            start = max(int(x["uhrzeit"]) * 60 + int(x.get("minute", 0)) - early, 0)
            slots.append((WEEKDAYS.index(x["tag"]), start // 60, start % 60, "gemessen", DROP_WINDOW_MIN + early))
    return slots


def drop_specs(shop):
    """Drop-Angaben aus shops.yaml; "täglich 18:00 Europe/London" wird zu sieben Wochentagen"""
    out = []
    for x in shop.get("drop") or []:
        m = re.match(r"(?i)t(ä|ae)glich\s+(.+)$", str(x).strip())
        out += [f"{d} {m.group(2)}" for d in WEEKDAYS] if m else [str(x)]
    return out


def fixed_slot(spec, ref=None):
    """'Fr 19:00' (deutsche Zeit) oder 'Fr 20:00 Pacific/Auckland' -> (Wochentag, Stunde, Minute) in deutscher
    Zeit, für die Woche um ref (Zeitumstellungen in beiden Ländern werden so automatisch berücksichtigt)"""
    m = re.match(r"(Mo|Di|Mi|Do|Fr|Sa|So)\s+(\d{1,2}):(\d{2})(?:\s+([A-Za-z_]+/[A-Za-z_]+))?$", str(spec).strip())
    if not m:
        return None
    wd, h, mi = WEEKDAYS.index(m.group(1)), int(m.group(2)), int(m.group(3))
    if not m.group(4):
        return wd, h, mi
    zone = ZoneInfo(m.group(4))
    local = (ref or now()).astimezone(zone)
    day = local - dt.timedelta(days=(local.weekday() - wd) % 7)
    berlin = day.replace(hour=h, minute=mi, second=0, microsecond=0).astimezone(TZ)
    return berlin.weekday(), berlin.hour, berlin.minute


def drop_calendar(shops, status_store):
    """Alle Drop-Termine fürs Dashboard: feste (shops.yaml) und gemessene (Rhythmus)"""
    rhythms = {q.get("name"): q.get("rhythmus") or {} for q in (status_store.get("quellen") or {}).get("liste", [])}
    out = []
    for shop in shops:
        if (shop.get("plattform") or "auto").lower() in ("aus", "fyj"):
            continue
        for x in drop_specs(shop):
            slot = fixed_slot(x)
            if slot:
                out.append({"shop": shop["name"], "tag": WEEKDAYS[slot[0]], "zeit": f"{slot[1]:02d}:{slot[2]:02d}",
                            "quelle": "fest"})
        r = rhythms.get(shop["name"]) or {}
        if r.get("typ") == "drops" and r.get("anteil", 0) >= DROP_MIN_SHARE:
            for x in r.get("termine") or []:
                out.append({"shop": shop["name"], "tag": x["tag"], "zeit": f"{x['uhrzeit']:02d}:{x['minute']:02d}",
                            "quelle": "gemessen", "streuung": x.get("streuung_min", 0), "anzahl": x.get("anzahl", 0),
                            "abstand": r.get("abstand_tage"), "verschoben": x.get("verschoben", False)})
    out.sort(key=lambda d: (WEEKDAYS.index(d["tag"]), d["zeit"], d["shop"]))
    return out


def drop_due(shop, status_store, t):
    """Fälliger Drop-Slot (Text) oder None. Fenster: ab Drop-Zeit DROP_WINDOW_MIN Minuten"""
    last = (status_store.get("drop_checks") or {}).get(shop["name"])
    if last and t - dt.datetime.fromisoformat(last) < dt.timedelta(minutes=DROP_RECHECK_MIN):
        return None
    local = t.astimezone(TZ)
    for wd, h, mi, src, window in drop_slots(shop, status_store):
        start = (local - dt.timedelta(days=(local.weekday() - wd) % 7)).replace(hour=h, minute=mi, second=0,
                                                                                 microsecond=0)
        if start > local:
            start -= dt.timedelta(days=7)
        if local - start <= dt.timedelta(minutes=window):
            return f"{WEEKDAYS[wd]} {h:02d}:{mi:02d} ({src})"
    return None
