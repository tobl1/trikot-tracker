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
| `shops.yaml` | direkt abgefragte Shops mit `plattform` (auto, cfs, smartweb, prestashop, fyj, aus) |
| `.github/workflows/tracker.yml` | GitHub Actions: Gesamtlauf `30 3 * * *` UTC, Schnellcheck `45 7,13,19 * * *` UTC, manuell mit Modus |
| `state/seen.json` | bekannte Treffer (Schlüssel = kanonische URL), wird vom Workflow committet |
| `state/status.json` | erkannte Plattformen, erfolgreich abgefragte Quellen, Produktanzahlen, letzter Lauf |
| `TREFFER.md` | automatisch erzeugte Übersicht als Markdown, Quellen-Status immer vom letzten Gesamtlauf |
| `docs/index.html` | Dashboard (GitHub Pages, Branch `main`, Ordner `/docs`), statisch, lädt `treffer.json` |
| `docs/treffer.json` | aktuelle Treffer inkl. EUR-Preis plus Quellen-Status, wird vom Workflow committet |

Laufzeitumgebung: GitHub Actions, öffentliches Repo, Python 3.12,
`ubuntu-24.04`, `actions/checkout@v6`, `actions/setup-python@v6`. Erster echter Gesamtlauf: ca. 3 Min. (vor der Drosselung, jetzt deutlich länger; Timeout 90 Min.)
Öffentliches Repo (seit 01.10.2026), dadurch unbegrenzte Actions-Minuten.

Benachrichtigung: **ntfy** (ntfy.sh, iPhone-App), Thema im Secret `NTFY_TOPIC`. Veröffentlicht per
JSON-POST an den Server-Root. Telegram wurde verworfen (kostenpflichtige Verifizierung).
Niemals das Thema oder andere Secrets in Code, Logs oder Commits schreiben.

## Modi

- `full`: alle Shops komplett plus FindYourJersey; erkennt Plattformen neu
- `priority`: nur Einträge mit `prioritaet: hoch` (Thiago + Sondertrikots) über Shop-Suchen,
  nutzt die in `status.json` gemerkten Plattformen
- `test`: nur Test-Push

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
- Reissues (FYJ `isReissue`, also Nachbauten) werden gar nicht erst erfasst
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
  60 % der Artikel in Schüben, sonst "laufend" bzw. "ruhig". Steht im Quellen-Status des Dashboards

## Benachrichtigungslogik

- Erstlauf (leeres seen.json): genau **eine** Zusammenfassung
- Neue Quelle oder Bestandssprung (>30 % und >200 Produkte mehr als beim letzten Gesamtlauf):
  Treffer still übernehmen, keine Pushes
- Thiago/Sondertrikots: einzeln mit Priorität 5, max. 5 pro Lauf; alles andere gebündelt in einer
  Nachricht. Hintergrund: Der erste echte Lauf schickte 17 Pushes, das fand der Nutzer zu viel
- Gleicher Artikel über FYJ und direkt: Deduplizierung über kanonische URL
  (ohne www, Query, Slash; Shopify-Pfade auf `/products/<handle>` gekürzt)

## Quellen und technische Details

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

**Shopify** (Großteil der Shops): `products.json?limit=250&page=N` (Limit im Code 120 Seiten),
Fallback `/collections/all/products.json`, dann Suche. Schnellcheck über
`/search/suggest.json` (max. 10 Treffer je Begriff) plus `/products/<handle>.js` für Varianten.
**products.json enthält keine Währung.**

**WooCommerce:** Store API `/wp-json/wc/store/v1/products` (Fallback ohne `v1`), Preise in
Minor Units mit `currency_code`.

**Classic Football Shirts (`cfs`):** Magento, Suche serverseitig gerendert unter
`/catalogsearch/result/?q=<begriff>&p=N`; `.product-item`, Titel im `img alt` inkl. Zustand und
Größe, z. B. "2013-14 Bayern Munich Away Shirt Thiago #6 - 5/10 - (L)"; Cloudflare davor.

**ReShirt (`smartweb`):** `/json/products?currencyIso=DKK&field=search&filter={}&id=<begriff>&limit=48&orderBy=-Id&page=N`;
Größe steht im Titel ("… - XL"); Felder `Stock`/`Online` wirken unzuverlässig, nur `Soldout` wird genutzt.
**Gegen den echten Shop noch nicht getestet.**

**Swiat Koszulek (`prestashop`):** `/szukaj?controller=search&s=<begriff>` mit
`Accept: application/json` + `X-Requested-With: XMLHttpRequest` liefert JSON; Größe nur auf der
Produktseite (`.product-variants .radio-label`); Cloudflare-Challenge-Skript auf der Seite,
eventuell werden GitHub-IPs geblockt. **Noch nicht live getestet.**

## Stand nach dem ersten echten Gesamtlauf

33 von 46 Shops direkt ok (Shopify/Woo/CFS), FYJ ok (3.777 Kandidaten). Danach geändert:
Kit Fever entfernt (Domain gehört jetzt einem Modeshop), Retro Football Kits entfernt
(Shopify "Unavailable Shop"), Seitenlimit angehoben (4 Shops waren bei 10.000 abgeschnitten),
House of Football Shirts per Such-Fallback, ReShirt und Swiat neu, 6 Shops auf `plattform: fyj`
(Classic-Shirts, ClassicShirts-FC, Retro Football Shirt Store, The Hoff Classics, Topbinz,
We Love Football Shirts). **Diese Änderungen sind noch nicht durch einen echten Lauf bestätigt.**

## Offene Punkte (Priorität von oben nach unten)

1. ~~Quellen-Status prüfen~~ erledigt mit dem Gesamtlauf am 01.10.2026 10:27 Uhr (ca. 22 Min. mit
   Drosselung, kein einziges 429): 41/44 Shops ok, CFS 1.532, ReShirt 5, Swiat 111, FYJ 3.777.
   Offen: **House of Football Shirts liefert 0 Produkte** (products.json, Collection und Suche leer,
   53 Anfragen), Ursache noch nicht untersucht. Saturdays Football, Vintage Football Area und
   Vintage Football Shirts enden bei 25.000 Produkten (Shopify liefert max. 100 Seiten). Unkritisch,
   da products.json die neuesten zuerst liefert (geprüft), es fehlen nur die ältesten Einträge
2. **Feedback des Nutzers** zu den Erstlauf-Treffern einholen (Fehltreffer? Verpasstes?) und
   Matching nachschärfen. Bekannte Schwächen: "de Jong" ohne Vornamen kann Luuk/Nigel sein;
   "Llorente" + Spanien kann Fernando sein; Reissues werden mitgenommen und nur markiert
3. **Währungen**: größtenteils umgesetzt (01.10.2026). Shopify-Währung per `/cart.js` je Shop im
   Gesamtlauf, gemerkt in `status.json` unter `currencies` (überschreibbar mit `waehrung:` in
   shops.yaml); EZB-Kurse über `api.frankfurter.dev`, zuletzt bekannte Kurse als Fallback;
   `parse_price()` erkennt Codes und £/€/zł/$. Offen: "$" wird pauschal als USD gelesen;
   CFS zeigt Preise je nach Abruf-Standort in anderer Währung, im Blick behalten
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

- GitHub-Cron ist unpünktlich (10 bis 30 Min.); für minutengenaue Drops ggf. externer Trigger
  (cron-job.org → `workflow_dispatch`)
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
