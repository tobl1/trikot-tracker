"""Trikot-Tracker: sucht Vintage-Trikots aus watchlist.yaml in XL/XXL bei den Shops aus shops.yaml und meldet
neue Treffer per Push. Aufbau:

  basis       Konstanten, Text-Normalisierung, kleine Helfer
  speicher    Pfade der Datendateien, Laden und Speichern
  abgleich    Matcher: Spieler, Sondertrikots, Flock, Größe
  netz        HTTP mit Pausen, Wiederholungen und Shopify-Bremse
  quellen/    Shop-Anbindungen (Shopify, WooCommerce, Wix, Suchseiten, FindYourJersey)
  zustand     Zustand und Verfügbarkeit aus Produktseiten
  pruefung    Treffer auf der Shop-Seite nachprüfen
  preise      Preise lesen, in Euro umrechnen
  rhythmus    Drop-Rhythmus und fällige Drops
  melden      Push-Benachrichtigungen
  issues      GitHub-Issues aus dem Dashboard (Meldungen, Preisalarme, Shop aufnehmen)
  berichte    Dashboard-Daten, TREFFER.md, Fehler-Log, Fundgrube
  lauf        ein Run von Anfang bis Ende
"""
