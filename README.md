# Tobias Trikot Tracker (TTT)

Sucht automatisch Vintage-Trikots deiner Lieblingsspieler und Wunsch-Trikots in XL/XXL
und schickt neue Treffer per ntfy-Push aufs Handy.

- **Gesamt-Run** nachts gegen 5:30 Uhr: rund 120 Shops direkt plus Lückenfüller über FindYourJersey
- **Neuheiten-Radar** tagsüber etwa alle 30 Minuten: die neuesten Artikel aller Shopify- und WooCommerce-Shops
- **Schnell-Run** 3x täglich (ca. 9:45, 15:45, 21:45 Uhr): Thiago und die Sondertrikots über die Shop-Suchen
- **Drop-Run**: prüft Shops kurz nach ihrem Drop (feste Zeiten aus `shops.yaml` und automatisch erkannte)
- **Dashboard** mit Bildern, Filtern und Preisen in Euro: https://tobl1.github.io/trikot-tracker/
- **Übersicht** als Liste: [TREFFER.md auf dem Daten-Zweig](https://github.com/tobl1/trikot-tracker/blob/daten/TREFFER.md)

## Aufbau

| Wo | Was |
|---|---|
| `watchlist.yaml` | Spieler, Sondertrikots, Größen, Ausschlüsse |
| `shops.yaml` | direkt abgefragte Shops |
| `tracker.py`, `trikot/` | das Programm (Einstieg und Module) |
| `tests/` | automatische Tests, laufen vor jedem Run |
| `.github/workflows/` | Runs (`tracker.yml`), Dashboard veröffentlichen (`dashboard.yml`), Tests (`tests.yml`) |
| `docs/` | Dashboard-Seite |
| Zweig **`daten`** | alles, was die Runs schreiben: Zustand, `treffer.json`, `TREFFER.md`, `FEHLER.md`, `FUNDGRUBE.md` |

Code und Daten liegen getrennt: Änderungen am Programm (Zweig `main`) und die Ergebnisse der Runs
(Zweig `daten`) kommen sich so nie in die Quere. Der Daten-Zweig wird einmal am Tag zu einem einzigen
Commit zusammengefasst, damit das Repository klein bleibt.

## Ablauf eines Runs

1. Tests laufen, schlagen sie fehl, startet der Run gar nicht erst
2. Shops abfragen, Treffer prüfen, alles im Daten-Zweig speichern
3. **Erst danach** gehen die Pushes raus (Postausgang): scheitert das Speichern, kommt nichts doppelt
4. Dashboard wird neu veröffentlicht

## Anpassen

- **Spieler hinzufügen:** in `watchlist.yaml` einen Block nach Vorbild der anderen ergänzen
- **Shop hinzufügen:** in `shops.yaml` eine Zeile ergänzen, das Shopsystem wird automatisch erkannt.
  Oder im Dashboard unter "Fundgrube" auf "Aufnehmen" tippen
- **Shop pausieren:** `plattform: aus` dazuschreiben

## Gut zu wissen

- Gestartet werden die Runs von cron-job.org (minutengenau). GitHubs eigene Zeitpläne kamen teils Stunden
  zu spät und dienen nur als Rückfall
- Probleme der Runs stehen in `FEHLER.md` auf dem Daten-Zweig. Bleiben Runs aus, zeigt das Dashboard
  oben einen Hinweis
- Wird ein Shop zum ersten Mal erfolgreich abgefragt, kommt dessen Bestand ohne Einzel-Pushes
  in die Übersicht, damit es keine Flut an Nachrichten gibt
- Das Repository ist öffentlich, damit das Dashboard über GitHub Pages läuft. Das ntfy-Thema liegt als
  Secret und bleibt geheim
- Die Abfragen sind bewusst gedrosselt (Shopify sperrt sonst die IP), ein Gesamt-Run dauert daher länger
