# Daten-Zweig des Trikot-Trackers

Hier liegen nur Daten, geschrieben von den Runs (GitHub Actions). Der Code liegt auf `main`.
Der Gesamt-Run fasst diesen Zweig einmal am Tag zu einem einzigen Commit zusammen, damit das Repo klein bleibt.

| Datei | Inhalt |
|---|---|
| `state/seen.json` | alle bekannten Treffer (Schlüssel = kanonische URL) |
| `state/status.json` | Quellen-Status, Plattformen, Läufe, Meldungen, Preisalarme, Fundgrube |
| `state/fehlerlog.json`, `FEHLER.md` | Fehler-Log der letzten 30 Tage |
| `state/postausgang.json` | Pushes, die erst nach dem Speichern verschickt werden |
| `treffer.json` | Daten fürs Dashboard (GitHub Pages) |
| `TREFFER.md` | Übersicht als Markdown |
| `FUNDGRUBE.md` | wöchentliche Shop-Kandidaten |
| `shops_fundgrube.yaml` | per Dashboard aus der Fundgrube aufgenommene Shops |
