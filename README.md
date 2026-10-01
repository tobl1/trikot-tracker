# Trikot-Tracker

Sucht automatisch Vintage-Trikots deiner Lieblingsspieler und Wunsch-Trikots in XL/XXL
und schickt neue Treffer per ntfy-Push aufs Handy.

- **Gesamtlauf** nachts gegen 5:30 Uhr: rund 46 Shops direkt plus ~125 Shops über FindYourJersey
- **Schnellcheck** 3x täglich (ca. 9:45, 15:45, 21:45 Uhr): Thiago und die Sondertrikots in den direkt angebundenen Shops
- **Dashboard** mit Bildern, Filtern und Preisen in Euro: https://tobl1.github.io/trikot-tracker/
- **Übersicht** als Liste: [TREFFER.md](TREFFER.md) (beides wird bei jedem Lauf aktualisiert)

## Dateien

| Datei | Zweck |
|---|---|
| `watchlist.yaml` | Spieler, Sondertrikots, Größen, Ausschlüsse |
| `shops.yaml` | direkt abgefragte Shops |
| `tracker.py` | das Programm |
| `.github/workflows/tracker.yml` | Zeitsteuerung |
| `docs/index.html` | Dashboard-Seite |
| `TREFFER.md`, `state/`, `docs/treffer.json` | entstehen automatisch, nicht bearbeiten |

## Einrichtung

1. Im Repository auf **Add file → Upload files**, diese Dateien hineinziehen:
   `tracker.py`, `watchlist.yaml`, `shops.yaml`, `requirements.txt`, `README.md`,
   dann **Commit changes**
2. **Add file → Create new file**, als Dateinamen exakt `.github/workflows/tracker.yml`
   eintippen (die Schrägstriche legen die Ordner an), den Inhalt der Datei `tracker.yml`
   hineinkopieren, **Commit changes**
3. Reiter **Actions** öffnen. Falls GitHub fragt, Workflows aktivieren
4. Links **Trikot-Tracker** wählen, rechts **Run workflow**, Modus `test`.
   Nach ca. 1 Minute sollte ein Test-Push auf dem Handy ankommen
5. Nochmal **Run workflow**, diesmal Modus `full`. Das ist der Erstlauf: Du bekommst die
   aktuell verfügbaren Thiago- und Sondertrikot-Treffer plus eine Zusammenfassung.
   Alle Treffer stehen danach in `TREFFER.md`

Ab dann läuft alles automatisch.

## Anpassen

Dateien direkt auf GitHub bearbeiten (Datei öffnen, Stift-Symbol, speichern).
Änderungen gelten ab dem nächsten Lauf.

- **Spieler hinzufügen:** in `watchlist.yaml` einen Block nach Vorbild der anderen ergänzen
- **Shop hinzufügen:** in `shops.yaml` eine Zeile ergänzen, das Shopsystem wird automatisch erkannt
- **Shop pausieren:** `plattform: aus` dazuschreiben

## Gut zu wissen

- Die Uhrzeiten von GitHub sind nicht minutengenau, Verzögerungen von 10 bis 30 Minuten sind normal
- Nach jedem Gesamtlauf zeigt `TREFFER.md` unten den **Quellen-Status**. Shops mit Hinweis
  "nicht automatisch erkannt" brauchen eine Sonderanbindung (sofern sie nicht über FYJ laufen)
- Wird ein Shop zum ersten Mal erfolgreich abgefragt, kommt dessen Bestand ohne Einzel-Pushes
  in die Übersicht, damit es keine Flut an Nachrichten gibt
- Treffer, die 36 Stunden nicht mehr gesehen wurden (verkauft), verschwinden aus der Übersicht
- Das Repository ist öffentlich, damit das Dashboard über GitHub Pages läuft. Dadurch sind
  Actions-Minuten unbegrenzt. Das ntfy-Thema liegt als Secret und bleibt geheim
- Die Abfragen sind bewusst gedrosselt (Shopify sperrt sonst die IP), ein Gesamtlauf dauert daher länger
