"""Ablage: Pfade der Datendateien, Laden und Speichern"""

import json

from .basis import ROOT


STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
STATUS_FILE = STATE_DIR / "status.json"
REPORT_FILE = ROOT / "TREFFER.md"
DASHBOARD_FILE = ROOT / "docs" / "treffer.json"
ERROR_LOG = STATE_DIR / "fehlerlog.json"
ERROR_REPORT = ROOT / "FEHLER.md"
FUNDGRUBE_REPORT = ROOT / "FUNDGRUBE.md"
SHOPS_FILE = ROOT / "shops.yaml"


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default
