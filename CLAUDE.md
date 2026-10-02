# CLAUDE.md: Trikot-Tracker

Übergabe aus einem Chat mit Claude (claude.ai), Stand 01.10.2026. Diese Datei beschreibt Ziel,
Aufbau, getroffene Entscheidungen und offene Punkte. Bitte bei größeren Änderungen aktuell halten.

## Kommunikation mit dem Nutzer

- Deutsch, locker, direkt
- **Niemals Gedankenstriche (—) in Sätzen**, auch nicht in Push-Texten, README oder TREFFER.md.
  Bindestriche in Wörtern ("Rekord-Sieger") sind okay
- Wenn "Stichpunkte" gewünscht: prägnant, ohne Punkt am Ende, viel Inhalt in kurzer Form
- Bei Unklarheiten oder fehlenden wichtigen Infos nachfragen
- Eigene Aussagen kritisch prüfen, Unsicherheiten offen benennen

## Ziel

Automatische Suche nach Vintage-Fußballtrikots der Lieblingsspieler des Nutzers in **XL oder XXL**
(L ausdrücklich nicht) bei vielen Online-Shops, mit Push-Benachrichtigung bei neuen Treffern.
**Thiago (Alcântara) ist absolute Priorität #1.** Gesucht werden primär Trikots mit
Spielerbeflockung, für Thiago zusätzlich bestimmte Trikots (siehe `sondertrikots` in
`watchlist.yaml`), und zwar **nur mit Thiago-Flock oder ganz ohne Flock**, weil der Nutzer
Thiago nachbeflocken lassen will (Messi-Barça 12/13 ist also kein Treffer).
Grundhaltung des Nutzers: alles in sinnvollem Rahmen, Kompromiss aus "Neues sofort sehen" und
wenig Last auf den Shops; lieber langsam und nachts als Sperren riskieren. Später sollen eventuell seltene unbeflockte
Einzeltrikots zum Nachbeflocken dazukommen, das sagt der Nutzer gesondert an.

## Aufbau

| Datei | Zweck |
|---|---|
| `tracker.py` | gesamtes Programm (Abfrage, Matching, Push, Bericht), bewusst eine Datei |
| `watchlist.yaml` | Spieler mit Suchbegriffen, Ausschlüssen, Vereinsfilter; Sondertrikots; Größen; Produktausschlüsse |
| `shops.yaml` | direkt abgefragte Shops mit `plattform` (auto, cfs, idosell, smartweb, prestashop, fyj, aus), optional `schnellcheck: nein` |
| `.github/workflows/tracker.yml` | GitHub Actions: Gesamt-Run `30 3 * * *` UTC, Schnell-Run `45 7,13,19 * * *` UTC, Drop-Run als Rückfall `10,40 11-21 * * 4,5,6` UTC, manuell mit Modus (full, priority, drop, test) |
| `state/seen.json` | bekannte Treffer (Schlüssel = kanonische URL), wird vom Workflow committet |
| `state/status.json` | erkannte Plattformen, erfolgreich abgefragte Quellen, Produktanzahlen, letzter Lauf |
| `TREFFER.md` | automatisch erzeugte Übersicht als Markdown, Quellen-Status immer vom letzten Gesamtlauf |
| `docs/index.html` | Dashboard (GitHub Pages, Branch `main`, Ordner `/docs`), statisch, lädt `treffer.json`. Ansichten "Alle Treffer" und "Eingänge nach Lauf" (`#eingaenge`, gruppiert nach `first` = Zeitstempel des Laufs, Läufe aus `status.json` → `laeufe`; still übernommene Treffer, also Erstlauf oder neue Quelle, eingeklappt). Pushes verlinken auf `#eingaenge` |
| `docs/treffer.json` | aktuelle Treffer inkl. EUR-Preis plus Quellen-Status, wird vom Workflow committet |

Laufzeitumgebung: GitHub Actions, öffentliches Repo, Python 3.12,
`ubuntu-24.04`, `actions/checkout@v6`, `actions/setup-python@v6`. Gesamt-Run mit 77 Shops ca. 50 bis 60 Min.
(bewusst gedrosselt), Timeout 180 Min.
Öffentliches Repo (seit 01.10.2026), dadurch unbegrenzte Actions-Minuten.

Benachrichtigung: **ntfy** (ntfy.sh, iPhone-App), Thema im Secret `NTFY_TOPIC`. Veröffentlicht per
JSON-POST an den Server-Root. Telegram wurde verworfen (kostenpflichtige Verifizierung).
Niemals das Thema oder andere Secrets in Code, Logs oder Commits schreiben.

## Modi

- `full`: alle Shops komplett plus FindYourJersey; erkennt Plattformen neu
- `priority`: nur Einträge mit `prioritaet: hoch` (Thiago + Sondertrikots) über Shop-Suchen,
  nutzt die in `status.json` gemerkten Plattformen
- `drop`: nur Shops, deren Drop gerade fällig ist (`drop_due`): feste Zeiten aus shops.yaml
  (`drop: ["Fr 19:00"]`, deutsche Zeit) plus gemessene aus dem Rhythmus (typ "drops", mind. 50 % der
  Schübe am selben Wochentag). Fenster 180 Min. ab Drop-Beginn, je Shop höchstens alle 25 Min.
  Shopify: nur die ersten products.json-Seiten (neueste zuerst), Woo: neueste 100. Ist nichts
  fällig, endet der Run sofort ohne Schreiben. Quellen ohne bisherigen Gesamt-Run werden still übernommen
- `test`: nur Test-Push
- Sprachgebrauch gegenüber dem Nutzer: "Run" statt "Lauf" (Gesamt-Run, Schnell-Run, Drop-Run)

Lokal testen: `python tracker.py --mode full --dry-run` (sendet nichts, schreibt aber state und
TREFFER.md, also vorher sichern oder nicht committen). `--only "Name"` testet einzelne Shops.

## Matching-Regeln (wichtig, vom Nutzer so festgelegt)

- Text wird normalisiert (Kleinschreibung, Akzente weg, ß→ss, Gedankenstriche→`-`),
  Begriffe werden als **ganze Wörter** gesucht (`rodri` trifft nicht `rodrigo`)
- `vereine` bei Spielern ist ein **strikter Filter**. Bewusst gesetzt:
  Henry nur Arsenal; Torres nur Atlético und Liverpool; Robben nur Bayern;
  Olić nur Bayern, HSV, Kroatien (nicht Wolfsburg, nicht ZSKA); Juninho = Pernambucano
- Sondertrikots Thiago: Barça 2010/11 bis 2012/13 (alle Varianten); Bayern Wiesn-Trikot 2021/22
  grün (nur 21/22 bzw. 2021, **2023 war auch grün**; "third/fourth/special" zählen nur mit
  Farbangabe, sonst käme das reguläre Third 21/22; Vereinsfilter nur "bayern", sonst träfe es
  1860-Wiesn-Trikots); Liverpool Away 21/22; Liverpool Third 22/23; Spanien 2010/2011 und 2014
  jeweils Home und Away
- Varianten-Logik: erlaubtes Wort im Titel → ok; anderes Variantenwort → nein; gar keins → nur ok,
  wenn "home" erlaubt ist
- Größe: XL, XXL, 2XL, X-Large, XX-Large, Extra Large; Kinder- und Damengrößen raus (YXL, XLB, boys,
  "young xl", damska, feminina, infantil …)
- Trainingsshirts raus, auch "treino", "entrenamiento", "allenamento", "trening" usw.
- Sondertrikots: fremd beflockt = Rückennummer (#10, No. 10) oder Name aus `fremdflock.namen`,
  außer Thiago/Alcantara steht drin. Pro Sondertrikot abschaltbar mit `fremdflock: egal`
- Labels werden bei jeder ersten Sichtung im Lauf **neu berechnet** (früher nur ergänzt, dadurch
  blieben alte Labels nach Regeländerungen hängen); Treffer ohne Label fallen nach 36 h raus
- Reissues (FYJ `isReissue`) werden gar nicht erst erfasst. **Achtung, FYJ-Flag ist ein Sammelbecken**
  (Recherche 01.10.2026): (a) Original-Trikot mit nachgedrucktem Flock ("Repro Flock", "flocage
  reproduction récente", "Nameset: Remake", z. B. 089kits.de, footballshirtvintage.fr,
  sundayfootballshirts.com), (b) reine Repro-Flocksätze (first11shirts.com "Name Set (Repro)"),
  (c) offizielle Neuauflagen (adidas Originals, Score Draw, "Reedition"), (d) inoffizielle Kopien
  ("Retro Remake"). Nutzer entscheidet noch, ob (a) mit Kennzeichnung angezeigt werden soll.
  "Replica" bedeutet in UK das normale Fan-Trikot (Gegenteil von Player Issue), kein Fake
- Shopify `product_type` wird gegen `produkt_ausschluss` geprüft (nicht fürs Matching): fängt z. B.
  "Tracktop" bei "2010/11 - Espagne (XL)" (VFA), "Reissue" (Cult Kits), "Goal Keeper", "Shirt - Training"
- `hersteller_ausschluss` (watchlist): Marke aus JSON-LD der Shop-Seite, z. B. classic-shirts.com
  "Producer: Official" = inoffizielles Fan-Produkt → `aussortiert`. `ausschluss_urls`: einzelne vom
  Nutzer gemeldete Fehltreffer. `min_zustand` (shops.yaml, aktuell CFS 7): schlechtere Noten raus.
  "Barcelona SC" (Ecuador) und Nachbau-Begriffe (repro, score draw, nameset) in `produkt_ausschluss`.
  Nicht per Text erkennbar: z. B. Nike-Trainingsshirt "2010-11 BARCELONA SHIRT XL" (classic-shirts),
  dafür wäre Bilderkennung nötig (mit Nutzer besprochen, noch offen)
- `CHECK_VERSION`: erhöhen, wenn die Seitenprüfung mehr auswertet, dann wird alles neu geprüft
- **Preisgrenze** (`preisgrenze` in watchlist.yaml): über 150 € kein Push, im Dashboard standardmäßig
  ausgeblendet (Schalter "auch über 150 €"); Ausnahme nur Label "Thiago" (Sondertrikots ausdrücklich
  nicht, Nutzer 02.10.2026). Dashboard rechnet selbst nach
- Shopify: gibt es Größen-Varianten, zählen nur **verfügbare** XL/XXL-Varianten; sonst Größe aus
  Titel oder Größen-Tag
- Testfälle: `tests/test_matching.py` (pytest, `python -m pytest tests/`), vor jeder Änderung an
  Matching, Zustand oder Rhythmus erweitern und laufen lassen. Wichtige Fälle: Thiago Silva ≠ Thiago,
  Ferran ≠ Fernando Torres, Marcos ≠ Xabi Alonso, Wiesn 2023 grün = nein, 1860 Wiesn = nein,
  Liverpool 21/22 ohne "away" = nein, "Hamburger SV" = HSV, 3XL/XXXL = nein, "Short Sleeve" darf
  nicht als Shorts ausgeschlossen werden

## Zustand, Verfügbarkeit, Drop-Rhythmus

- **Zustand** (`zustand`, `zustand_notiz` in seen.json): Note wie "8/10" aus Titel (CFS: "- 8/10 -")
  oder Beschreibung (Shopify `body_html`, Woo `description`), sonst BNWT, sonst Wort nach
  "Condition:", sonst FYJ-Feld `condition` ("Very Good"). Notiz = Text ab "Condition:", 160 Zeichen
- **FYJ-Treffer werden auf der Shop-Seite geprüft** (`enrich`): JSON-LD Product liefert
  `offers.availability` (OutOfStock → `verkauft`, fliegt raus) und `description` (Zustand).
  Neue Treffer zuerst und vor den Pushes, dann alle 3 Tage erneut; max. 150 Seiten pro Gesamtlauf,
  25 pro Schnellcheck. Beispiel: von zwei Thiago-Trikots bei classic-shirts war eins laut FYJ
  verfügbar, laut Shop ausverkauft
- eBay über FYJ: Angebote mit `lastSyncedAt` älter als 10 Tage gelten als weg (FYJ aktualisiert
  eBay teils seit Monaten nicht). Nutzer will langfristig prüfen, ob eBay überhaupt sinnvoll ist
- **Drop-Rhythmus** (`rhythm()`, nur Shopify): aus `published_at` des ganzen Katalogs, 90 Tage
  rückwirkend. Schub = mind. 8 Artikel mit max. 90 Min. Abstand; "drops" wenn mind. 2 Schübe und
  60 % der Artikel in Schüben und Abstand im Median mind. 3 Tage, sonst "laufend" (an mind. 8 von
  30 Tagen neu), "unregelmäßig" oder "ruhig". Steht im Quellen-Status des Dashboards.
  Erste Messung 01.10.2026, klare Drop-Shops: Kickoff Vintage Do 16 bis 18 Uhr wöchentlich (12/12),
  Trikotparadies Fr 19 Uhr wöchentlich (14/15), Fodbold Shoppen alle 14 Tage Fr 15 Uhr (6/6),
  Kick It Vintage ca. alle 3 Wochen Sa 18 Uhr, Nostalgic Football Shirts ca. alle 3 Wochen Sa 11 bis 12 Uhr
- Plattform-Erkennung: ist ein Shop schon bekannt und die Erkennung schlägt einmal fehl, bleibt die
  bekannte Plattform (RB-Jerseys fiel am 01.10.2026 sonst wegen eines Aussetzers raus)

## Benachrichtigungslogik

- Erstlauf (leeres seen.json): genau **eine** Zusammenfassung
- Neue Quelle oder Bestandssprung (>30 % und >200 Produkte mehr als beim letzten Gesamtlauf):
  Treffer still übernehmen, keine Pushes
- Thiago/Sondertrikots: einzeln mit Priorität 5, max. 5 pro Lauf; alles andere gebündelt in einer
  Nachricht. Hintergrund: Der erste echte Lauf schickte 17 Pushes, das fand der Nutzer zu viel
- `via` eines Treffers springt auf "direkt", sobald ein direkt abgefragter Shop ihn liefert
  (wichtig für die FYJ-Fundgrube und das Ausblenden nicht mehr gelieferter Treffer)
- Gesamtlauf mit 76 Shops dauerte am 01.10.2026 ca. 57 Min. (Timeout jetzt 180 Min.)
- Gleicher Artikel über FYJ und direkt: Deduplizierung über kanonische URL
  (ohne www, Query, Slash; Shopify-Pfade auf `/products/<handle>` gekürzt)

## Quellen und technische Details

**Strategie (entschieden 01.10.2026): direkt zuerst, FYJ nur als Lückenfüller und Fundgrube.**
FYJ-Daten sind oft tagelang alt, teils fehlerhaft, Zustand nur grob. Deshalb: 31 Shopify-Shops,
die vorher nur über FYJ kamen, direkt (`schnellcheck: nein`, nur nachts), classic-shirts.com per
`idosell`. FYJ ignoriert Domains, die direkt abgefragt werden, und Marktplätze (eBay, Depop, Vinted,
Etsy) komplett. `status.json` → `fyj_shops` listet Shops, die nur noch über FYJ Treffer liefern
(im Dashboard unter Quellen-Status), daraus Kandidaten für direkte Anbindung vorschlagen.
Bewusst über FYJ gelassen: first11shirts.com und footballshirtvintage.fr (ca. 20 % Nachbauten laut
FYJ, die FYJ per `isReissue` aussortiert), Wix-Shops (Lineup Vintage, Original 11vs11, Bulishirts,
Rare and Retro), unklare Systeme (kitts.de, Topbinz, The Shirt Collectors, Full90 Prints, Wave).
Ziel: FYJ irgendwann ganz abschalten

**FindYourJersey** (inoffizielle API, Nutzer sollte die Betreiber noch um Erlaubnis fragen):
- `isReissue` kommt als **Text** `"false"`/`"true"`, nicht als Boolean (bis 01.10.2026 deshalb alles als Reissue markiert)
- `GET https://www.findyourjersey.org/api/jerseys?search=<wort>&sizes=XL&limit=200&page=N`
- `limit` > 200 ergibt HTTP 400; Paginierung über `page`; `sizes` filtert zuverlässig, "2XL" läuft unter XXL
- Mehrwort-Suche wirkt nicht wie UND, daher nur einzelne markante Wörter, Feinfilter lokal
- Felder: description, size, year (Saisonbeginn), team, player (oft leer), sourceType, sourceUrl,
  currentValue, currency, imageUrl, createdAt, isReissue
- `/api/retailers` liefert ~125 Händler; Neuzugänge hatten Zeitstempel um 02:40 UTC, vermutlich
  nächtlicher Abgleich, daher für Drops zu langsam
- Classic Football Shirts fehlt bei FYJ komplett

**Shopify** (Großteil der Shops): `products.json?limit=250&page=N` (max. 100 Seiten, `SHOPIFY_PAGE_CAP`),
Fallback `/collections/all/products.json`, dann Suche. Suche (Schnellcheck, gekappte Kataloge)
über die Suchseite `/search?q=…&type=product&page=N`, Vorfilter über den Handle, dann
`/products/<handle>.js` für Varianten. **Nicht** `suggest.json`: max. 10 unscharfe Treffer, bei VFA
lieferte "thiago" nur T. Silva. Shops mit Ziffern-Handles (The Football Temple) findet die Suche
nicht, die laufen nur über den Gesamtlauf
**products.json enthält keine Währung.**

**WooCommerce:** Store API `/wp-json/wc/store/v1/products` (Fallback ohne `v1`), Preise in
Minor Units mit `currency_code`.

**Classic Football Shirts (`cfs`):** Magento, Suche serverseitig gerendert unter
`/catalogsearch/result/?q=<begriff>&p=N`; `.product-item`, Titel im `img alt` inkl. Zustand und
Größe, z. B. "2013-14 Bayern Munich Away Shirt Thiago #6 - 5/10 - (L)"; Cloudflare davor.

**Classic-Shirts (`idosell`):** `/search.php?text=<begriff>&counter=N` (0-basiert, 50 je Seite),
zeigt **nur Verfügbares**; Kacheln `div.product[data-product_id]`, Titel `a.product__name`, Preis
`strong.price`; Sammelangebote ("Multiple Sizes") → Produktseite, `.projector_sizes__name` listet nur
verfügbare Größen. Zustand per Seitenprüfung (JSON-LD description "CONDITION: 8/10 …")

**ReShirt (`smartweb`):** `/json/products?currencyIso=DKK&field=search&filter={}&id=<begriff>&limit=48&orderBy=-Id&page=N`;
Größe steht im Titel ("… - XL"); Felder `Stock`/`Online` wirken unzuverlässig, nur `Soldout` wird genutzt.
**Gegen den echten Shop noch nicht getestet.**

**Swiat Koszulek (`prestashop`):** `/szukaj?controller=search&s=<begriff>` mit
`Accept: application/json` + `X-Requested-With: XMLHttpRequest` liefert JSON; Größe nur auf der
Produktseite (`.product-variants .radio-label`); Cloudflare-Challenge-Skript auf der Seite,
eventuell werden GitHub-IPs geblockt. **Noch nicht live getestet.**

## Offene Punkte (Priorität von oben nach unten)

1. ~~Quellen-Status prüfen~~ erledigt mit dem Gesamtlauf am 01.10.2026 10:27 Uhr (ca. 22 Min. mit
   Drosselung, kein einziges 429): 41/44 Shops ok, CFS 1.532, ReShirt 5, Swiat 111, FYJ 3.777.
   House of Football Shirts deaktiviert: laut Startseite "In-store only in The Hague", alle
   Shopify-Endpunkte leer. Saturdays Football, Vintage Football Area und
   Vintage Football Shirts enden bei 25.000 Produkten (Shopify liefert max. 100 Seiten, neueste zuerst).
   **Nicht unkritisch:** ältere, noch verfügbare Artikel fehlen (z. B. Thiago Bayern 19/20 bei VFA,
   eingestellt 02/2024). Früher fing FYJ das auf. Seit 01.10.2026: bei gekapptem Katalog zusätzlich
   `shopify_search` für alle Suchbegriffe
2. **Feedback des Nutzers** zu den Erstlauf-Treffern einholen (Fehltreffer? Verpasstes?) und
   Matching nachschärfen. Bekannte Schwächen: "de Jong" ohne Vornamen kann Luuk/Nigel sein;
   "Llorente" + Spanien kann Fernando sein; Reissues werden mitgenommen und nur markiert
3. **Währungen**: größtenteils umgesetzt (01.10.2026). Shopify-Währung per `/cart.js` je Shop im
   Gesamtlauf, gemerkt in `status.json` unter `currencies` (überschreibbar mit `waehrung:` in
   shops.yaml); EZB-Kurse über `api.frankfurter.dev`, zuletzt bekannte Kurse als Fallback;
   `parse_price()` erkennt Codes und £/€/zł/$. Offen: "$" wird pauschal als USD gelesen;
   CFS zeigt Preise je nach Abruf-Standort in anderer Währung, im Blick behalten.
   **Shopify Markets:** der GitHub-Server (USA) bekam US-Preise in USD (VFA: 93 $ statt 79,99 €).
   Deshalb Cookie `localization=DE` in jeder Session (`BUY_COUNTRY`), `/cart.js`-Währung wird
   in jedem Lauf neu gelesen
4. ~~Dashboard per GitHub Pages~~ umgesetzt (01.10.2026): Nutzer hat entschieden, das Repo
   öffentlich zu machen (Pages wäre auch mit Pro öffentlich erreichbar, öffentliches Repo spart
   außerdem Actions-Minuten). Push-Links zeigen per `DASHBOARD_URL` aufs Dashboard
5. **Wix-Shops anbinden:** The Football Boutique und Throwback Jerseys NZ (beide `plattform: aus`).
   Throwback NZ droppt **jeden Freitag 20:00 NZ-Zeit** (aktuell Fr 07:00 UTC wegen NZDT, ab April
   08:00 UTC). Danach Extra-Lauf kurz nach dem Drop einplanen, Zeitzonenwechsel beachten
6. Optional direkte Anbindung der FYJ-gedeckten Shops (We Love Football Shirts läuft z. B. auf
   Lightspeed, das hat oft `?format=json`; Classic-Shirts ist vermutlich IdoSell), weil FYJ nur
   nächtlich aktualisiert
7. **Adaptiver Zeitplan** aus dem Drop-Rhythmus: Drop-Shops nur kurz nach ihrem typischen Drop
   gezielt prüfen, "laufend"-Shops im Schnellcheck, "ruhig" nur nachts. Erst ein paar Gesamtläufe
   Rhythmus-Daten ansehen und mit dem Nutzer abstimmen. Für Woo/CFS/FYJ gibt es keine
   Zeitstempel, dort müsste man neue Produkt-IDs selbst mitzählen
8. Backlog: Social-Media-Accounts der Shops auf Drop-Ankündigungen beobachten (Nutzer: eher später)
9. Backlog: eBay als Kanal bewerten (viele Treffer veraltet, Kindergrößen als "Young XL")

## Bekannte Rahmenbedingungen

- **GitHub-Cron ist sehr unzuverlässig**: am 02.10.2026 startete der Gesamt-Run für 03:30 UTC erst
  um 09:58 UTC, der Schnell-Run 07:45 UTC fiel ganz aus. Für Drops externer Trigger nötig
  (cron-job.org → `workflow_dispatch` mit fein granuliertem Token, nur Actions read/write auf
  diesem Repo). Einrichtung macht der Nutzer selbst (Token nie in Chat, Code oder Logs)
- Topbinz blockt alle automatischen Abrufe (HTTP 403 schon auf der Startseite), bleibt über FYJ;
  laut Nutzer Drop Fr 19 Uhr. first11shirts.com laut Nutzer ebenfalls Fr 19 Uhr (feste Drop-Zeit),
  letzte Neuzugänge aber Do 01.10. gegen 21 Uhr, Rhythmus beobachten
- Geplante Workflows werden nach 60 Tagen ohne Repo-Aktivität deaktiviert; die Commits des
  Trackers zählen als Aktivität
- Höflich bleiben: 2 Sekunden Pause pro Shop, max. 8 Shops parallel. Nutzer will lieber langsame
  Läufe (auch über Stunden, nachts) als Sperren riskieren. Schnellcheck deshalb nur 3x täglich,
  er ist mit ca. 400 Shopify-Anfragen pro Lauf (13 Begriffe x 27 Shops) der größere Lastfaktor
- **Shopify drosselt pro IP über alle Shops hinweg** (Cloudflare davor, festgestellt 01.10.2026):
  8 Shops parallel ergaben nach ca. 1 Min. flächendeckend HTTP 429, danach blieb der
  Python-Client an der IP minutenlang gesperrt (curl nicht). Deshalb `SHOPIFY_GATE`: gemeinsamer
  Mindestabstand `SHOPIFY_INTERVAL` für alle Shopify-Abrufe, bei 429 pausieren alle. Bleibt es bei
  429, gilt der Shop als "unvollständig" (früher wurde das still als Katalogende gewertet)
  und eine bekannte Plattform wird nicht mit "unbekannt" überschrieben
- Marktplätze (eBay-Händler, Depop) werden bewusst nicht abgefragt; dem Nutzer wurde empfohlen,
  dort in den Apps Verkäufern zu folgen bzw. gespeicherte Suchen anzulegen
