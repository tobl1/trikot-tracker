"""Ablage: Pfade der Datendateien, Laden und Speichern"""

import json
import os
from pathlib import Path

from .basis import ROOT

# Datenordner: Zustand, Berichte und Dashboard-Daten. Über TRIKOT_DATEN umstellbar (Tests, lokale Probeläufe)
DATA_DIR = Path(os.environ.get("TRIKOT_DATEN") or ROOT)
STATE_DIR = DATA_DIR / "state"
SEEN_FILE = STATE_DIR / "seen.json"
STATUS_FILE = STATE_DIR / "status.json"
OUTBOX_FILE = STATE_DIR / "postausgang.json"   # Pushes, die erst nach dem Speichern verschickt werden
REPORT_FILE = DATA_DIR / "TREFFER.md"
DASHBOARD_FILE = DATA_DIR / "docs" / "treffer.json"
ERROR_LOG = STATE_DIR / "fehlerlog.json"
ERROR_REPORT = DATA_DIR / "FEHLER.md"
FUNDGRUBE_REPORT = DATA_DIR / "FUNDGRUBE.md"
SHOPS_FILE = ROOT / "shops.yaml"


class DatenFehler(Exception):
    """Eine Datendatei ist beschädigt. Der Run bricht dann ab, statt still mit leerem Zustand neu anzufangen
    (das wäre ein falscher "Erstlauf": alle Treffer neu, Daten weg)"""


def load_json(path, default, strict=False):
    """JSON laden. Fehlt die Datei: default. Ist sie kaputt: mit strict DatenFehler, sonst default"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except ValueError as e:
        if strict:
            raise DatenFehler(f"{path.name} ist beschädigt ({e}), Run abgebrochen, Daten bleiben unverändert") from e
        return default


def save_text(path, text):
    """Erst in eine Zwischendatei schreiben, dann umbenennen: nie halb geschriebene Dateien"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_json(path, data, compact=False):
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    save_text(path, text)
