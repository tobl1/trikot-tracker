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

## Bei jeder neuen Anfrage zuerst (Wunsch des Nutzers, 05.10.2026)

1. `git pull` und `git -C daten pull` (Daten-Zweig, lokal als Unterordner `daten/` eingehängt; fehlt er:
   `git fetch origin daten && git worktree add --track -b daten daten origin/daten`), dann **`daten/FEHLER.md`**
   lesen (Fehler-Log der Runs, zusammengefasst je Quelle und Meldung, 30 Tage) und neue oder gehäufte Probleme
   kurz analysieren und ansprechen. Der Nutzer will keine Alarm-Pushes, sondern dass Claude das Log selbst prüft
   (das Dashboard zeigt nur einen Hinweis, wenn Runs ausbleiben)
2. `gh issue list --label flag --state all` auf neue Meldungen prüfen, Muster in Regeln übersetzen
3. `daten/FUNDGRUBE.md` überfliegen: Die Fundgrube läuft seit 05.10.2026 **automatisch** wöchentlich im
   Gesamt-Run (`fundgrube()`): FYJ-only-Shops mit Treffern, System erkannt (`detect_platform`), Anteil
   FYJ-Nachbauten (`FYJ_DOMAIN_STATS`), Empfehlung bei bekanntem System und < 15 % Nachbauten, eine Push
   pro Woche. Nutzer tippt im Dashboard (Bereich Fundgrube) auf "Aufnehmen" → Issue Label `shop` →
   `add_shops_from_issues()` trägt den Shop im nächsten Gesamt-Run in `daten/shops_fundgrube.yaml` ein (schnellcheck:
   nein; `speicher.load_shops()` führt sie mit shops.yaml zusammen)
   und schließt das Issue. Bewusst nur über FYJ: Einträge mit `plattform: aus` (z. B. footballshirtvintage.fr).
   Ganz gesperrt (auch nicht über FYJ): `sperren: ja` (The Football Market)

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
| `tracker.py` + `trikot/` | Einstieg `tracker.py`, Code seit 05.10.2026 im Paket `trikot/` (vorher eine Datei mit 2.200 Zeilen): `basis` (Konstanten, Text), `speicher` (Pfade, Laden/Speichern), `abgleich` (Matcher), `netz` (HTTP), `quellen/` (shopify, woo, wix, suchseiten = CFS/IdoSell/html/PrestaShop/SmartWeb, fyj, `run_shop`), `zustand`, `pruefung`, `preise`, `rhythmus`, `melden`, `issues`, `berichte`, `lauf` (main). `tracker.py` stellt alle Namen weiter unter `tracker.*` bereit (Tests); Tests, die etwas umbiegen, müssen das echte Modul treffen (z. B. `trikot.speicher.ERROR_LOG`) |
| `watchlist.yaml` | Spieler mit Suchbegriffen, Ausschlüssen, Vereinsfilter; Sondertrikots; Größen; Produktausschlüsse |
| `shops.yaml` | direkt abgefragte Shops mit `plattform` (auto, cfs, idosell, smartweb, prestashop, fyj, aus), optional `schnellcheck: nein` |
| `.github/workflows/tracker.yml` | **Hauptauslöser cron-job.org** (seit 04.10.2026, `workflow_dispatch`): Gesamt-Run 5:30, Schnell-Run 9:45/15:45/21:45, Drop-Run `5-59/15 9-23` (deutsche Zeit, bewusst versetzt zu :45). GitHub-Zeitpläne nur Rückfall mit `--rueckfall` (überspringt, wenn Gesamt-Run < 20 h bzw. Schnell-Run < 5,5 h her): `30 5`, `15 9,15,21` UTC. Am 04.10.2026 startete ein Rückfall-Schnell-Run 4 h verspätet, lief trotz 4-h-Sperre, 63 Min. mit vielen 429 und verdrängte drei Drop-Runs (deshalb 5,5 h und spätere Zeiten, auch im Winter nach den cron-job.org-Runs). **GitHub-Concurrency hält nur einen wartenden Run**, ein weiterer Start verdrängt ihn (`cancelled`). Deshalb Startzeiten entzerrt und kein Drop-Rückfall |
| Zweig **`daten`** (seit 05.10.2026) | alles, was Runs schreiben, getrennt vom Code: `state/seen.json` (bekannte Treffer, Schlüssel = kanonische URL), `state/status.json` (Plattformen, Quellen, Läufe, Flags, Alarme, Radar), `state/fehlerlog.json` + `FEHLER.md`, `state/postausgang.json`, `treffer.json` (Dashboard), `TREFFER.md`, `FUNDGRUBE.md`, `shops_fundgrube.yaml`. Im Workflow und lokal als Unterordner `daten/` ausgecheckt (`TRIKOT_DATEN` überschreibt den Pfad). Der Gesamt-Run fasst den Zweig täglich zu **einem** Commit zusammen (orphan + force push), die anderen Runs committen normal. Grund: Rebase-Konflikt am 04.10.2026 (Run-Ergebnis verloren) und wachsende Repo-Größe |
| Ablauf `tracker.yml` | Code-Zweig (`ref: github.ref_name`) + Daten-Zweig holen, Tests, Run, **Ergebnisse speichern**, dann **Pushes senden** (`--mode senden`, Postausgang) und **Versand speichern**, danach Job `dashboard` (ruft `dashboard.yml`). Eingaben zum Testen: `zweig` (z. B. `daten-test`) und `stumm` (Probelauf: `--dry-run`, keine Pushes, keine Issues schließen, kein Dashboard). Test eines Umbaus: `gh workflow run tracker.yml --ref <zweig> -f mode=full -f zweig=daten-test -f stumm=true` |
| `.github/workflows/dashboard.yml` | GitHub Pages über Actions (seit 05.10.2026, vorher main/docs): `docs/` von main + `treffer.json` vom Daten-Zweig. Läuft nach Runs mit neuen Daten und bei Push auf `docs/**` |
| `.github/workflows/tests.yml` | Tests bei jedem Push auf Programm, Suchliste, Shops; der Tracker-Workflow testet zusätzlich vor jedem Run und bricht bei Fehlern ab |
| `daten/TREFFER.md` | automatisch erzeugte Übersicht als Markdown, Quellen-Status immer vom letzten Gesamtlauf |
| `docs/index.html` | Dashboard (GitHub Pages, Branch `main`, Ordner `/docs`), statisch, lädt `treffer.json`. Ansichten "Alle Treffer" und "Eingänge nach Lauf" (`#eingaenge`, gruppiert nach `first` = Zeitstempel des Laufs, Läufe aus `status.json` → `laeufe`; still übernommene Treffer, also Erstlauf oder neue Quelle, eingeklappt). Pushes verlinken auf `#eingaenge` |
| Dashboard-Design (05.10.2026) | angelehnt an Dribbble "Crypto Trading Mobile App": Schwarz, Anthrazit-Karten (Radius 22), Rot `#e0352f` als einziger Akzent, Thiago-Kacheln komplett rot. Titel als Grafik `docs/titel.png` in der Schrift **Evantic** (Datei vom Nutzer, Demo nur privat frei, deshalb nur
als Bild veröffentlicht, nicht als Schriftdatei; neu erzeugen mit PIL aus der TTF des Nutzers). Name seit 05.10.2026 **"Tobis Trikot Tracker"**, kurz **TTT** (Homebildschirm, Manifest), Icon vom Nutzer (Spieler im Bayern-Trikot, Ecken mit Hintergrund/Rasen gefüllt). Titel in **UnifrakturCook** (Wunsch war "Citadel of Blackrose", die ist nur privat frei und müsste öffentlich mitveröffentlicht werden; Alternativen: Grenze Gotisch, UnifrakturMaguntia, Pirata One, New Rocker, Texturina), Titel 20 px tiefer wegen iPhone-Statusleiste. Nutzerwünsche davor: Titel neben dem Logo, Kategorie und Preis in der Kachel in **Inter** in der Kopfzeile, rechts "Stand" + Run-Art; Grundschrift **Syne**; keine große rote Statistik und keine Icon-Knöpfe oben; Filter-Knopf neben der Suche (Handy); Kategorien ohne roten Punkt (wirkte wie "Neues"); Tipp auf Alle/Neu pro Run/Favoriten scrollt nach oben. Untere Leiste bewusst schlicht, aktiver Eintrag weiß mit rotem Punkt |
| Dashboard als Web-App | `manifest.webmanifest`, `icon.svg` + `icon-180/192/512.png` (Trikot mit 6), Start vom Homebildschirm im Vollbild. Kein Zoom (viewport, `touch-action`, iOS `gesturestart`), kein seitliches Scrollen, Eingaben 16 px (sonst zoomt iOS beim Tippen). Am Handy: Navigationsleiste unten, seltene Filter hinter "Filter"-Knopf |
| Dashboard-Extras | "Juckt nicht" (05.10.2026): im Melde-Sheet zuerst "Einfach ausblenden", nur lokal (localStorage `tt:hidden`), ohne Issue, mit Rückgängig-Toast; zurückholen über "N ausgeblendet" in den Filtern. Alter in der Kachel kurz: 5h, 3d, 1m (31 bis 60 Tage). Größe immer XL/XXL. Favoriten (Stern, nur lokal im Browser, mit Datenkopie, "nicht mehr gelistet" und "Preis ↓"), gleiche Angebote eines Shops (gleicher Titel und Größe) zusammengefasst auf das günstigste ("+N gleiche im Shop"); Classic-Shirts hat oft mehrere Exemplare desselben Trikots |
| `daten/treffer.json` | aktuelle Treffer inkl. EUR-Preis plus Quellen-Status (Dashboard-Daten). Lokale Vorschau: nach `docs/` kopieren (dort ignoriert) |

Laufzeitumgebung: GitHub Actions, öffentliches Repo, Python 3.12,
`ubuntu-24.04`, `actions/checkout@v6`, `actions/setup-python@v6`. Gesamt-Run mit 77 Shops ca. 50 bis 60 Min.
(bewusst gedrosselt), Timeout 180 Min.
Öffentliches Repo (seit 01.10.2026), dadurch unbegrenzte Actions-Minuten.

Benachrichtigung: seit 05.10.2026 **nur noch Push direkt an die Dashboard-App** (Web Push, siehe Stufe 3).
ntfy ist auf Wunsch des Nutzers abgeschaltet (Code, Workflow und Secret `NTFY_TOPIC` entfernt). Telegram wurde
früher verworfen (kostenpflichtige Verifizierung). Niemals Secrets (`VAPID_PRIVATE_KEY`) in Code, Logs oder Commits.
Ohne aktives App-Abo kommt keine Push: Fehler-Log "App-Push", Dashboard-Hinweis "Kein Push-Abo aktiv".

## Modi

- `full`: alle Shops komplett plus FindYourJersey; erkennt Plattformen neu
- `priority`: nur Einträge mit `prioritaet: hoch` (Thiago + Sondertrikots) über Shop-Suchen,
  nutzt die in `status.json` gemerkten Plattformen. **Seit 05.10.2026 ohne Shopify** (die Shopify-Suche dauerte 70 Min. mit 429 und blockierte das Radar; Neues findet das Radar, Älteres der Gesamt-Run): nur noch Such-Shops (CFS, Classic-Shirts, html, PrestaShop, SmartWeb), Woo und Wix
- `drop`: nur Shops, deren Drop gerade fällig ist (`drop_due`): feste Zeiten aus shops.yaml
  (`drop: ["Fr 19:00"]`, deutsche Zeit) plus gemessene aus dem Rhythmus (typ "drops", mind. 50 % der
  Schübe am selben Wochentag). Fenster 180 Min. ab Drop-Beginn, je Shop höchstens alle 25 Min.
  Shopify: nur die ersten products.json-Seiten (neueste zuerst), Woo: neueste 100. Ist nichts
  fällig, endet der Run sofort ohne Schreiben. Quellen ohne bisherigen Gesamt-Run werden still übernommen
- `droptest` (nur Workflow-Auswahl, intern `--mode drop --alle`, seit 04.10.2026): Drop-Run für alle
  Shopify-, Woo- und Wix-Shops auf einmal, endet mit Push "🧪 Testdrop fertig" (Shops ok, neue Treffer,
  Probleme). Such-Shops (CFS, IdoSell, html …) bewusst nicht, die wären zu teuer. Erster Test: 102/103
  ok in ca. 8 Min., nur Football Legends Kits nicht erkannt (sperrt GitHub-IPs, FYJ deckt ab)
- **Neuheiten-Radar** (seit 05.10.2026, Teil des Drop-Runs): alle `RADAR_MIN` (25) Minuten die neuesten
  `RADAR_LIMIT` (40) Artikel aller automatisch erkannten Shopify- und WooCommerce-Shops (`radar_shops`, nicht Wix,
  Such-Shops, gesperrte), Shopify per `shopify_newest` (weiterblättern nur, wenn die ganze Seite neuer ist als die
  letzte Prüfung, `radar_checks`), gemerkte Währung statt `/cart.js`. Lauf heißt im Verlauf "radar". Last: ca. 90
  kleine Abrufe pro Radar, knapp 30 pro Shop und Tag. Ersetzt nicht die Drops (fällige Drops weiter gründlich)
- `senden`: nur im Workflow nach dem Speichern, verschickt den Postausgang (`state/postausgang.json`); nicht
  zugestellte bleiben für den nächsten Run, ältere als 12 Std. werden verworfen (beides im Fehler-Log)
- `test`: nur Test-Push an alle App-Abos (über den Postausgang, verschickt im Schritt danach)
- Sprachgebrauch gegenüber dem Nutzer: "Run" statt "Lauf" (Gesamt-Run, Schnell-Run, Drop-Run)

Lokal testen: `TRIKOT_DATEN=/tmp/kopie python tracker.py --mode full --dry-run --only "Name"` mit einer Kopie von
`daten/` (Probeläufe schreiben Zustand!). `--dry-run` sendet nichts, schließt keine Issues, prüft keine Preisalarme.
Lokal sperrt Shopify die eigene IP schnell (429), CFS und eBay blocken lokal (403): solche Prüfungen über einen
temporären Workflow aus GitHub heraus (Beispiel 05.10.2026: CFS-Suche "thiago" komplett durchgesehen).

## Matching-Regeln (wichtig, vom Nutzer so festgelegt)

- Text wird normalisiert (Kleinschreibung, Akzente weg, ß→ss, Gedankenstriche→`-`),
  Begriffe werden als **ganze Wörter** gesucht (`rodri` trifft nicht `rodrigo`); eine **Ziffer direkt
  danach ist erlaubt** ("#Thiago10", vintageauthenticretro.com, bis 04.10.2026 deshalb verpasst)
- Sondertrikots können `codes` haben (Hersteller-Artikelcode, z. B. Liverpool Third 22/23 = Nike
  DM1835-377): Code in Titel oder Beschreibung zählt ohne Varianten-/Saisonangabe. Classic-Shirts
  nennt den Code nur auf der Produktseite, `needs_detail()` lädt sie in genau diesen Grenzfällen nach.
  DB2560-688 = Liverpool **Home** 21/22; Away-21/22-Code noch unbekannt
- Classic-Shirts markiert Flock mit Sternchen ("*WINFIELD*"): Sternchen-Wort ohne bekannten Zusatz
  (BNWT, SIGNED, PLAYER ISSUE …, `STAR_TAGS`) gilt als fremder Flock, außer Thiago
- `vereine` bei Spielern ist ein **strikter Filter**. Bewusst gesetzt:
  Henry nur Arsenal; Torres nur Atlético und Liverpool; Robben nur Bayern;
  Olić nur Bayern, HSV, Kroatien (nicht Wolfsburg, nicht ZSKA); Juninho = Pernambucano
- Sondertrikots Thiago: Barça 2008/09 bis 2012/13 (alle Varianten, 08/09 und 09/10 seit 05.10.2026, Label
  "Barça 2008-2013"); Bayern Wiesn-Trikot 2021/22
  grün (nur 21/22 bzw. 2021, **2023 war auch grün**; "third/fourth/special" zählen nur mit
  Farbangabe, sonst käme das reguläre Third 21/22; Vereinsfilter nur "bayern", sonst träfe es
  1860-Wiesn-Trikots); Stichwörter seit 05.10.2026 auch "octoberfest", "wiesntrikot". **Check 05.10.2026:**
  FYJ hat das 21/22-Trikot in keiner einzigen Größe, nur 2013/14 (Thiagos erste Bayern-Saison!), 2024/25 und
  2025/26 als Oktoberfest-Trikot. Es ist also selten, kein Suchbegriff-Problem. Thiago war 21/22 schon in Liverpool; seit 05.10.2026 deshalb zusätzlich das Oktoberfest-Trikot 2013/14 (Thiagos erste
  Bayern-Saison), beide unter dem Label "Bayern Wiesn-Trikot" (zwei Einträge, gleicher Name); Liverpool Away 21/22; Liverpool Third 22/23; Spanien 2010/2011 und 2014
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
- **Nachbauten** (`nachbau` in watchlist: reissue, remake, repro, score draw, nameset …) sind raus,
  **außer Repro-Flock bei Thiago** (Nutzer 04.10.2026): Original-Trikot mit nachgedrucktem Flock
  (`repro_flock.muster`, z. B. "repro flock", "flocage reproduction", "nameset: remake") bzw. FYJ
  `isReissue` bei Thiago-Label → Treffer mit `repro: true`, Dashboard-Kennzeichen "REPRO-FLOCK".
- Beschreibung spricht nur von T-Shirt/Jacke (`desc_not_jersey`, z. B. VFA "Le t-shirt en détail") → raus,
  außer der Titel nennt ausdrücklich ein Trikot (Shirt, Jersey, Maillot …)
- Früher: Reissues (FYJ `isReissue`) wurden gar nicht erst erfasst. **Achtung, FYJ-Flag ist ein Sammelbecken**
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
  nur per `ausschluss_urls` (Bilderkennung verworfen, soll kostenlos bleiben)
- `CHECK_VERSION`: erhöhen, wenn die Seitenprüfung mehr auswertet, dann wird alles neu geprüft
- **Preisgrenze** (`preisgrenze` in watchlist.yaml): über 150 € kein Push, im Dashboard standardmäßig
  ausgeblendet (Schalter "auch über 150 €"); Ausnahme nur Label "Thiago" (Sondertrikots ausdrücklich
  nicht, Nutzer 02.10.2026). Dashboard rechnet selbst nach
- Shopify: gibt es Größen-Varianten, zählen nur **verfügbare** XL/XXL-Varianten; sonst Größe aus
  Titel oder Größen-Tag
- Vertragstests der Anbindungen: `tests/test_quellen.py` (FakeHttp mit Beispieldaten je Plattform, ohne Netz)
- Paketversionen fest in `requirements.txt` (pytest im Workflow ebenfalls fest)
- Testfälle: `tests/test_matching.py` (pytest, `python -m pytest tests/`), vor jeder Änderung an
  Matching, Zustand oder Rhythmus erweitern und laufen lassen. Wichtige Fälle: Thiago Silva ≠ Thiago,
  Ferran ≠ Fernando Torres, Marcos ≠ Xabi Alonso, Wiesn 2023 grün = nein, 1860 Wiesn = nein,
  Liverpool 21/22 ohne "away" = nein, "Hamburger SV" = HSV, 3XL/XXXL = nein, "Short Sleeve" darf
  nicht als Shorts ausgeschlossen werden

## Kategorie Nike Total 90 (2004-06)

- Wunsch des Nutzers (04.10.2026): Nike-T90-Template (runde Brustnummer), Priorität normal (gebündelte
  Pushes). **Seit 05.10.2026 für alle T90-Teams nur beflockt** (`fremdflock: pflicht`). Flock ohne
  Rückennummer ("BRASILE 2004 - RONALDO - HOME") wird über `flock_erkennung` (T90-Spieler 2004-06)
  erkannt; die Liste gilt bewusst nur für "pflicht", nicht für den Fremdflock-Ausschluss der
  Thiago-Sondertrikots ("park", "lee", "blanco" wären dort gefährlich). Fünf Sondertrikot-Einträge mit gleichem
  Namen (je Team einer, damit FYJ jedes Team abfragt): Brasilien, Holland, Portugal mit Saisons
  2004/05, 2005/06, 2004/06 bzw. Jahren 2004/2005 (Nationalteams EM 2004 bis vor WM 2006),
  Inter und Juventus nur 2004/05. Ausschlüsse: Zeiträume 2002-2004/2003-2004, Griechenland
  (EM 2004 fand in Portugal statt). Nike-Neuauflagen von 2025 laufen über `nachbau` raus
- Live-Test 04.10.2026 über FYJ: 78 Treffer in XL/XXL, viele über 150 €. **Preisgrenze 150 € gilt
  auch hier** (Nutzer). **Neuauflagen erwünscht** (`nachbau_erlaubt_fuer`), Dashboard-Kennzeichen
  "NEUAUFLAGE" (`reissue` am Treffer)
- Seit 04.10.2026 zusätzlich: Südkorea, Mexiko, Kroatien (2004-06), Barcelona 2004/05, Arsenal
  2004/05 und 2004-06, Porto 2004/05 (ohne "Porto Alegre"). Weitere mögliche T90-Teams: USA,
  Türkei, Russland (EM 2004), Australien; Man United, Valencia, PSG, PSV, BVB, Corinthians.
  Nicht Chelsea (damals Umbro, eine Quelle irrt)
- `has_flock()`: Rückennummer, Sternchen-Name, Name aus fremdflock/flock_erkennung/Spielerliste oder
  alleinstehende Nummer (nicht Saison, Note, Alter). Seit 05.10.2026 auch Valencia, Australien, PSV
- `season_rxs` versteht echte Bereiche: "2004/06" = 2004-06 (vorher fälschlich wie 2004/05)
- Neue Kategorien werden beim ersten Gesamt-Run still übernommen (`known_labels` in status.json)
- Still übernommene Treffer (neue Shops/Kategorien) lösen **eine** Sammelnachricht aus ("🆕 N Treffer
  aus neuen Shops/Kategorien", Link auf `#eingaenge`)

## Kategorie HSV 1990-2016

- Seit 05.10.2026: HSV-Trikots der Saisons 1990/91 bis 2016/17, **nur beflockt**, Priorität normal,
  Preisgrenze gilt. Vorab-Check über FYJ: ca. 10 beflockte Trikots in XL/XXL, etwa die Hälfte unter 150 €.
  Verein "hamburger sv", "hsv", "hamburg", "hambourg"; Ausschluss Victoria, St. Pauli, Altona, Freezers …
  Flock ohne Nummer über `flock_namen` **am Sondertrikot-Eintrag** (gilt nur für diesen Eintrag, nicht global
  wie `flock_erkennung`; kurze Namen wie "son", "berg", "rost" wären global zu riskant)

## Kategorie WM 2006

- Seit 05.10.2026: alle 32 Teilnehmer (Ländernamen mehrsprachig), **nur beflockt**, Priorität normal,
  Preisgrenze gilt. Saisons 2006/07, 2006/08, 2005/07 (Deutschland, England, Argentinien brachten das
  WM-Trikot schon 2005) und Jahr 2006; nicht "2004-2006"/"2005/2006" (Vorgänger), nicht "Coupe de
  France", Jugendturniere (U17 …) und "New England". Flock ohne Nummer über `flock_erkennung`
  (WM-2006-Stars ergänzt). Live-Test über FYJ: 161 Treffer, fast alle plausibel

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
  Seit 02.10.2026 minutengenau: pro Wochentag mit mind. 3 Drops und 25 % der Schübe ein Termin
  (`termine`, mehrere möglich, z. B. Football Finery Di und Fr 10:59), Median-Uhrzeit, Streuung,
  Verschiebung erkannt, wenn die letzten 4 Drops über 60 Min. abweichen. Wird bei jedem
  Gesamt-Run neu berechnet, Drop-Kalender im Dashboard.
  Messung 02.10.2026: first11shirts Do 18:29 (±8, nicht Fr wie vom Nutzer vermutet), First Street
  Do 10:56, Football Finery Di+Fr 10:59, Fodbold Fr 15:36 alle 14 Tage, Jersely So 20:00, Offside
  Boys Di 18:00 alle 14 Tage, The Football Temple Sa 13:00, The Kitman 97 Sa ca. 16:52 (±72),
  Kickoff Vintage Do ca. 17 Uhr (wandert seit August von 13:24 auf ca. 18 Uhr).
  Erste Messung 01.10.2026, klare Drop-Shops: Kickoff Vintage Do 16 bis 18 Uhr wöchentlich (12/12),
  Trikotparadies Fr 19 Uhr wöchentlich (14/15), Fodbold Shoppen alle 14 Tage Fr 15 Uhr (6/6),
  Kick It Vintage ca. alle 3 Wochen Sa 18 Uhr, Nostalgic Football Shirts ca. alle 3 Wochen Sa 11 bis 12 Uhr
- Plattform-Erkennung: ist ein Shop schon bekannt und die Erkennung schlägt einmal fehl, bleibt die
  bekannte Plattform (RB-Jerseys fiel am 01.10.2026 sonst wegen eines Aussetzers raus)

## Bildprüfung

Mit Claude (Vision) gebaut und am 03.10.2026 auf Wunsch des Nutzers wieder entfernt: **alles soll
komplett kostenlos bleiben**, also keine kostenpflichtigen APIs einbauen. Fehltreffer, die nur
auf dem Foto erkennbar sind (z. B. Trainingsshirt ohne Hinweis im Titel), über `ausschluss_urls`.

## Meldungen aus dem Dashboard

- Fähnchen an jeder Kachel → Grund (unpassend, ausverkauft, falsche groesse, kein original, sonstiges)
  + Kommentar → vorausgefülltes GitHub-Issue mit Label `flag` (Body-Zeilen `grund:`, `id:` = Schlüssel
  aus seen.json, `kommentar:`). Dashboard blendet lokal sofort aus (localStorage)
- `apply_flags()` in jedem Run (auch Drop-Run, der dafür nicht früh abbricht): nur Issues des
  Repo-Inhabers (öffentliches Repo!), speichert in `status.json` → `flags`, kommentiert und schließt
  das Issue. ausverkauft → `verkauft`, sonst → `aussortiert`; gemeldete URLs werden nie wieder aufgenommen
- `apply_flags()` liest **alle** Flag-Issues (auch geschlossene) und baut `flags` daraus auf. Grund: am
  04.10.2026 schloss ein Run 12 Issues, konnte dann aber wegen Git-Konflikt nicht speichern
- Workflow checkt `ref: main` aus: ein wartender Run nutzt sonst den Stand vom Auslösezeitpunkt
  (Konflikt beim Speichern, mögliche Doppel-Pushes)
- Meldungen vom 05.10.2026: VFA-Hose (Produktart "Short" → `type_excluded`), VFA-Trainingsshirt ("Maillot d'entrainement" in der Beschreibung → `zustand.desc_excluded`), VFA "(L)" mit falschem Schlagwort "Taille XL" (ausdrückliche Größe im Titel schlägt Schlagwort, `TITLE_SIZE_RX`), "Chamarra" = Jacke, Originaltrikot ganz raus (`sperren: ja`, Treffer gesperrter Shops werden sofort ausgeblendet), Classic-Shirts "Producer: Official" (Seite war nie geprüft, siehe Prüfen vor dem Push). Neu: trikotcult.de (Shopify), "drittes Trikot" = third
- Meldungen vom 04.10.2026 und Folgen: Trainingsjacken als Wortzusammensetzung ("Trainingsjacke") und
  italienisch/spanisch/französisch ("giacca", "chaqueta", "veste" …), "Espanyol" ist nicht Barça,
  Kroos niemals Leverkusen, "N°7" ist eine Rückennummer, "*university*"/"*academy*" kein Spielername,
  The Football Market deaktiviert (Zustand). Nicht per Text lösbar: VFA-Barça-Trainingsshirts, die der
  Shop "Maillot" nennt (nur über Meldungen)
- Casual Football Shirts, Football Finery und Football Shirt Kingdom teilen ihren Bestand (gleiche
  Bilddateien mit Kennung "ff30…"). Dashboard fasst gleiche Titel (ab 25 Zeichen) und Größe auch
  shopübergreifend zusammen ("auch bei …")
- **Für Claude:** gemeldete Fehltreffer regelmäßig mit `gh issue list --label flag --state all` lesen
  und daraus Matching-Regeln ableiten (mit Testfall), statt nur einzeln auszublenden

## Stufe 3 (05.10.2026): Push aus der App, Melden mit einem Tipp

- **Push direkt aus der Dashboard-App** (Web Push, iPhone ab iOS 16.4, nur App vom Homebildschirm): `docs/sw.js`
  zeigt Pushes an. Einstellungen → "Push aktivieren": App abonniert mit dem öffentlichen VAPID-Schlüssel
  (`VAPID_PUBLIC` in docs/index.html), verschlüsselt das Abo (ECDH + HKDF + AES-GCM, Salt "trikot-tracker-1") und
  schickt es als Issue Label `push`. `issues.collect_push_abos()` legt das verschlüsselte Abo in `status.json` →
  `push_abos` (öffentlich, aber nur mit dem Secret lesbar) und schickt eine Bestätigung nur an dieses Abo
  (`nur_abo`). Versand in `--mode senden` (`melden.send_outbox`): nur noch an die App (bis 05.10.2026 zusätzlich ntfy); 404/410 = Abo erloschen, wird
  ausgetragen. Eigene Umsetzung `trikot/webpush.py` (RFC 8291/8292, nur `cryptography` + `http_ece`, kein pywebpush
  wegen aiohttp & Co.). Geheimer Schlüssel nur im Secret `VAPID_PRIVATE_KEY` (nie ausgeben, nur im Schritt
  "Pushes senden"). ntfy wurde am 05.10.2026 abgeschaltet, nachdem die App-Push ankam
- **Melden mit einem Tipp**: fein-granularer GitHub-Schlüssel nur für Issues dieses Repos, legt der Nutzer selbst an
  und trägt ihn in der App ein (localStorage `tt:token`, bleibt auf dem Gerät). Dann legen Melden, Preisalarm,
  "Aufnehmen" und Push-Abo die Issues direkt über die GitHub-Schnittstelle an (`createIssue`), sonst wie bisher
  über die vorausgefüllte GitHub-Seite. **"Juckt nicht"** wird mit Schlüssel nach der Rückgängig-Frist als Flag
  `grund: juckt nicht` verschickt → auf allen Geräten ausgeblendet, nie wieder Push. **Beim Ableiten von Regeln
  aus Flags `juckt nicht` ignorieren** (keine Fehlermeldung, nur Geschmack)

## Shop wieder offen, Preissenkungen (05.10.2026)

- **Shop wieder offen**: Shops mit Shopify-Passwortseite (HTTP 401, oft vor einem Drop) merkt sich `status.json` → `geschlossen` (`lauf.reopened`); ins Fehler-Log nur beim ersten Mal. Liefert der Shop wieder Artikel (Radar prüft Shopify-Shops alle 30 Min.), kommt eine Push "🔓 … ist wieder offen". Anlass: Kick It Vintage, Oh Calcio
- **Preissenkungen bei allen Treffern** (`lauf.price_drop`, nur direkte Quellen, gleiche Währung, mind. 5 % und 1 Einheit): `preis_runter` am Treffer, Dashboard-Badge "PREIS ↓ x %", Push nur bei Thiago/Sondertrikots (hoch). Favoriten-Preisalarm (unten) bleibt zusätzlich

## Preisalarm für Favoriten

- Glocke in der Favoriten-Ansicht → GitHub-Issue mit Label `alarm` (`grund: alarm`, `id:`). `check_alarms()`
  in jedem Run (nicht bei `--only`): Startpreis merken (`status.json` → `alarme`), Push bei Preissenkung,
  bei verkauft/weg Push und Issue schließen. Nutzer beendet Alarm, indem er das Issue schließt

## Benachrichtigungslogik

- **Postausgang** (seit 05.10.2026): `push()` sammelt nur, `save_outbox()` schreibt am Ende des Runs, verschickt wird
  erst nach dem Speichern im Workflow (`--mode senden`). Das ntfy-Thema steht nie in Dateien. Beschädigte
  `seen.json`/`status.json` brechen den Run ab (`DatenFehler`), statt still einen Erstlauf zu machen
- **Ehrliche Quellenwerte**: `Http.codes` zählt Antworten außer 200; 403/401 ohne Produkte = "gesperrt", sonst
  "keine Produkte erhalten (HTTP …)" bzw. Hinweis in `info`. **Bestandseinbruch** (Gesamt-Run, unter 50 % des
  letzten Bestands ab 100 Produkten) zählt als Fehler (Treffer bleiben, FYJ springt ein), nach 3 Gesamt-Runs in
  Folge gilt der kleinere Bestand als echt (`stock_collapse`, `status.json` → `einbruch`)
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

**05.10.2026: 34 weitere Shops** aus der Recherche direkt angebunden (Abschnitt "Neu seit 05.10.2026"
in shops.yaml, alle `schnellcheck: nein`), damit 115 Shops. Bewusst nicht: originaltrikot.de (Gambio),
wavememorabilia, classicfootballcollectibles, fancyfootballshirts, kitmenapparel, theshirttemple
(Mehraufwand/unklar), 44trikots (passwortgeschützt), Marktplätze und Nachbau-Shops

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

**Wix (`wix`, seit 04.10.2026):** anonymer Besucher-Schlüssel aus `/_api/v1/access-tokens` →
`apps["1380b703-ce81-ff05-f115-39571d94dfcd"].instance` (Wix Stores), dann POST
`/_api/wix-ecommerce-storefront-web/api` (GraphQL `catalog.category("00000000-000000-000000-000000000001")
.productsWithMetaData(limit:100, offset)`), Header `Authorization: <instance>`. Das ist die Schnittstelle,
die der Shop selbst für "Mehr laden" nutzt, keine Bot-Sperre. Felder: name, urlPart (`/product-page/<urlPart>`),
price, currency, isInStock, media[0].url (`static.wixstatic.com/media/<id>`), options (Größe: "Size",
"Taille", "Mens size"; "Youth size" = Kinder; "Condition"). Shops: Lineup Vintage, Original 11vs11,
Rare and Retro, The Football Boutique, Throwback Jerseys NZ. Bulishirts liefert 0 (bleibt FYJ).
kitts.de ist **kein** Wix, sondern ein Sharetribe-Marktplatz (bleibt FYJ). Lineup nennt neuere Trikots
"Rétro", ältere "Vintage" (vermutlich beides Originale, nicht geprüft)

**Wix, neuer Katalog V3** (089kits, vintage-football.com, Bulishirts): Standard-Kategorie liefert 0,
dann `{ catalog { categories(limit: 100) { list { id name } } } }` und Kategorie "All Products" bzw.
alle Kategorien zusammen (Bulishirts: 67 Anfragen). Beschreibung (`description`) kommt als Rich-Text-JSON,
`wix_text()` holt den Text raus

**Repro-Flock in der Beschreibung** (z. B. 089kits "Repro Flock", sundayfootballshirts "Nameset: Remake"):
bei direkt abgefragten Shops wie FYJ-Reissue behandelt, zählt also nur für Thiago (Kennzeichen REPRO-FLOCK)
und Kategorien aus `nachbau_erlaubt_fuer`

**Eigene Shopsysteme (`html`, seit 05.10.2026):** allgemeine Anbindung über die Such-Ergebnisseite,
pro Shop in shops.yaml konfiguriert (`suche` mit {q}, `link` CSS-Selektor, optional `groessen`). Produktseite
nur für passende Titel (JSON-LD für Preis/Bild/Verfügbarkeit, Größe aus Auswahl oder "Size:/Taglia:").
originaltrikot.de (Gambio, Suchseiten ca. 2 MB; Größen-Auswahl zeigt nur verfügbare; Shop bietet
Beflockung auf Wunsch nachträglich an), wavememorabilia.com (IT, Matchworn/Player Issue).
classicfootballcollectibles.com bewusst nicht: griechische Titel, bleibt über FYJ

**ReShirt (`smartweb`):** `/json/products?currencyIso=DKK&field=search&filter={}&id=<begriff>&limit=48&orderBy=-Id&page=N`;
Größe steht im Titel ("… - XL"); Felder `Stock`/`Online` wirken unzuverlässig, nur `Soldout` wird genutzt.
**Gegen den echten Shop noch nicht getestet.**

**Swiat Koszulek (`prestashop`):** `/szukaj?controller=search&s=<begriff>` mit
`Accept: application/json` + `X-Requested-With: XMLHttpRequest` liefert JSON; Größe nur auf der
Produktseite (`.product-variants .radio-label`); Cloudflare-Challenge-Skript auf der Seite,
eventuell werden GitHub-IPs geblockt. **Noch nicht live getestet.**

## Architektur-Review 05.10.2026

**Stufe 2 umgesetzt am 05.10.2026 (Nutzer: "weiter mit Stufe 2"):** Prüfen vor dem Push (`pruefung.needs_check`, `hold_unchecked`: FYJ- und Such-Shop-Treffer warten auf eine erfolgreiche Seitenprüfung, `push_offen`, max. 24 Std., 401/403 sofort mit Hinweis, 404 = verkauft, gescheiterte Prüfungen je Host ins Fehler-Log; Anlass: 46 von 62 Prüfungen im Gesamt-Run still gescheitert, darunter Classic-Shirts "Producer: Official"), Vereinsfilter der Spieler mit Shop-Kontext (`ctx`: Schlagwörter, Produktart, Handle, Woo-Kategorien), gekappte Kataloge zusätzlich über die Kollektionen der Thiago-Vereine (`shopify_collections`, `high_team_terms`; ganz auf Kollektionen umstellen lohnt nicht: VFA hätte 80.000 Artikel in passenden Kollektionen), "warum Treffer" (`Matcher.labels(..., why=)`, `warum` je Label in seen.json, im Dashboard im Fähnchen-Fenster) und Markierung PRÜFEN (`berichte.doubt`: Größe nur aus Schlagwort, Seite ungeprüft). Artikelcodes: nur belegte eingetragen (Barça Heim 11/12 419877-486, 12/13 478323-410, Spanien Heim 2010/11 P47902); für Liverpool Away 21/22 und die Wiesn-Trikots nichts Belastbares gefunden. Nutzen begrenzt, weil VFA und Classic-Shirts keine Codes in den Beschreibungen nennen. Flock aus der Beschreibung (`zustand.desc_flock`: "Flock:", "Beflockung:", "Flocage:", nicht Spielerlisten wie VFA "Joueurs:") seit 05.10.2026, Anlass trikotcult.de (Flock nur in der Beschreibung).

**Umgesetzt am 05.10.2026 (Nutzer: "fang gern an"):** Stufe 1 komplett (Module, feste Paketversionen, Vertragstests,
sicheres Speichern, Postausgang, ehrliche Quellenwerte, Bestandseinbruch, Daten-Zweig, Pages über Actions,
Lebenszeichen im Dashboard, Token-Erinnerung) und das Neuheiten-Radar aus Stufe 2. **Noch offen:** Kollektionen statt
Suche bei gekappten Katalogen, Prüfen vor dem Push für alle Quellen + "warum Treffer"/Sicherheit, Vereinsfilter mit
Tags/Kategorie, Artikelcodes der Thiago-Sondertrikots; Stufe 3 (eBay will der Nutzer erst besprechen, Vinted und
Kleinanzeigen deckt er selbst über App-Suchaufträge ab, Web Push statt ntfy, Ein-Tipp-Aktionen)

Befunde (geprüft, nicht geschätzt):
- 04.10.2026: 69 Runs, 63 sauber, 2 Abbrüche beim Speichern (git-add-Fehler, behoben; Rebase-Konflikt
  "could not apply ... Tracker-Lauf", Run 37187015515), 4 verdrängt (verspäteter Rückfall-Run, behoben)
- Pushes gehen vor dem Speichern raus (main: push() vor SEEN_FILE.write_text, Commit erst im Workflow) →
  scheitert das Speichern, ist der Run verloren und Pushes können doppelt kommen. `load_json` wertet kaputtes
  JSON still als leer (→ Erstlauf). `Http.get` liefert bei 403/404 nur None (Sperre sieht aus wie "leer")
- Thiago-Abgleich: FYJ kennt in 128 Shops 41 Thiago-Artikel (alle Größen), davon 3 in Herren-XL/XXL, alle 3
  bei uns (2 Kindergrößen korrekt raus). CFS-Suche "thiago" (per Diagnose-Run aus GitHub, lokal 403): nur 5
  Artikel, keiner in XL/XXL. Matchworn (bcbootsuk.com, Shopify) = Spielergrößen (Thiago LFC: M), für XL egal
- Von 128 FYJ-Händlern fehlen direkt 23 (Druckereien, Dubletten, Kleinstshops), laufen über FYJ/Fundgrube
- eBay-Suchseiten liefern 403 (nicht umgehen). Offizielle Browse API: kostenlos, 5.000 Abrufe/Tag
- VFA-Kollektionen (`/collections.json`): Barça 6.847, Bayern 3.572, Liverpool 1.580, Spanien 1.577 Artikel,
  also vollständig abrufbar statt Suche bei gekapptem Katalog (VFA braucht im Gesamt-Run über 1 Std.)
- `GITHUB_TOKEN` darf `workflow_dispatch` auslösen (Doku), trotzdem bleibt eine externe Uhr sinnvoll
  (GitHub-Zeitpläne bis über 6 Std. verspätet). GitHub-Nutzungsbedingungen: Actions für Softwareprojekte,
  geringe Last wird toleriert → keine Dauer-Runner, Last niedrig halten
- Drelife: offizielle Barça-Second-Hand-Plattform (angekündigt 04/2026), noch kein Shop gefunden, beobachten

Vorgeschlagener Plan: Stufe 1 Fundament (Daten-Branch, erst speichern dann pushen, ehrliche Quellenwerte inkl.
403/Bestandseinbruch, Vertragstests für Anbindungen, feste Paketversionen, Lebenszeichen im Dashboard,
Token-Ablauf-Erinnerung cron-job.org ca. 04.10.2027, Module). Stufe 2 Neuheiten-Radar (alle 30 Min. neueste
Artikel aller Shopify-/Woo-Shops über die bestehenden cron-job.org-Starts), Kollektionen statt Suche,
Prüfen vor dem Push + "warum Treffer"/Sicherheit, Vereinsfilter mit Tags/Kategorie. Stufe 3 eBay Browse API
(Nutzer legt Entwicklerkonto an), Web Push aus der Dashboard-App statt ntfy (erst parallel), Ein-Tipp-Aktionen
per GitHub-Schlüssel nur auf dem Handy; cron-job.org bleibt. Vinted/Kleinanzeigen/Depop: nur App-Suchaufträge

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
9. **Backlog (Nutzer 05.10.2026): eBay** über die offizielle Browse API (kostenlos, 5.000 Abrufe/Tag, Nutzer bräuchte
   ein eBay-Entwicklerkonto). Eine eigene "bequeme" Lösung später finden. eBay-Suchseiten blocken (403), nicht umgehen

## Bekannte Rahmenbedingungen

- **GitHub-Cron ist sehr unzuverlässig**: am 02.10.2026 startete der Gesamt-Run für 03:30 UTC erst
  um 09:58 UTC, der Schnell-Run 07:45 UTC fiel ganz aus. Für Drops externer Trigger nötig
  (cron-job.org → `workflow_dispatch` mit Fine-grained Token: Repository access "Only select
  repositories" → trikot-tracker, Permission "Actions: Read and write", Ablauf 1 Jahr mit
  Erinnerung). Einrichtung macht der Nutzer selbst (Token nie in Chat, Code oder Logs)
- The Third Kit liefert seit 02.10.2026 aus GitHub heraus nichts mehr (lokal ok), vermutlich Sperre
  für Rechenzentrums-IPs. Allgemein: Shops mit Fehler im letzten Gesamt-Run deckt FYJ wieder ab
- footballcat.eu (Drop Sa 16 Uhr laut Nutzer): JS-Bot-Schutz ("challenge_passed"-Cookie), wird
  **bewusst nicht umgangen**, nicht bei FYJ. Nur per Instagram/Newsletter verfolgbar
- **Topbinz seit 05.10.2026 direkt** (vorher 403): ShopWired, `plattform: html` mit Suche, Neuheiten-Seite `/new-in` (Radar und Drop-Run lesen nur diese), `pause: 10` (robots.txt Crawl-delay 10), `schnellcheck: nein` (Schnell-Run dauerte 14 Min.). Drop Fr 19 Uhr laut Nutzer. first11shirts.com laut Nutzer ebenfalls Fr 19 Uhr (feste Drop-Zeit),
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
