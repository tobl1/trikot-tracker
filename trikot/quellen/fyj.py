"""FindYourJersey als Lückenfüller (Shops ohne direkte Anbindung)"""

from ..basis import FYJ_API, FYJ_MARKETPLACES, FYJ_SIZES, domain, norm
from .gemeinsam import item


FYJ_DOMAIN_STATS = {}


def fyj_run(http, matcher, priority, skip_domains=()):
    """FYJ nur als Lückenfüller: keine Marktplätze, keine Shops, die direkt abgefragt werden"""
    # FYJ-Suche mit einzelnen, markanten Wörtern (z. B. "vaart" statt "van der vaart"),
    # Feinfilterung passiert lokal. Für Sondertrikots werden die Teams komplett geholt.
    queries = []
    for p in matcher.players:
        if priority and p["prio"] != "hoch":
            continue
        for t in p["terms"]:
            w = norm(t).split()[-1] if norm(t) else ""
            if len(w) >= 4 and w not in queries:
                queries.append(w)
    if not priority:
        queries += [norm(q) for q in matcher.team_queries() if norm(q) not in queries]
    items, n = [], 0
    for q in queries:
        for size in FYJ_SIZES:
            for page in range(1, 11):
                data = http.get(FYJ_API, {"search": q, "sizes": size, "limit": 200, "page": page})
                rows = data if isinstance(data, list) else (data or {}).get("jerseys") or []
                if not rows:
                    break
                n += len(rows)
                for r in rows:
                    title = r.get("description") or ""
                    reissue = str(r.get("isReissue")).lower() == "true"   # kommt als Text "false"/"true"
                    dom = domain(r.get("sourceUrl") or "")
                    if not dom or dom in skip_domains or any(m in dom for m in FYJ_MARKETPLACES):
                        continue
                    st = FYJ_DOMAIN_STATS.setdefault(dom, [0, 0])   # Zeilen, davon Nachbauten (Fundgrube)
                    st[0] += 1
                    st[1] += int(reissue)
                    extra = " ".join(str(x) for x in (r.get("player"), r.get("team")) if x)
                    price = f"{r.get('currentValue') or ''} {r.get('currency') or ''}".strip()
                    items.append(item("fyj", r.get("sourceType") or "FYJ", r.get("sourceUrl") or "",
                                      title, r.get("size") or "", price, r.get("imageUrl"), extra,
                                      fyj_condition=r.get("condition") or "", fyj_reissue=reissue))
                if len(rows) < 200:
                    break
    return items, n
