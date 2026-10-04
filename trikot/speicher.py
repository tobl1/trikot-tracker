"""Ablage: Pfade der Datendateien, Laden und Speichern"""

import json
import os
from pathlib import Path

import yaml

from .basis import ROOT

# Datenordner: Zustand, Berichte und Dashboard-Daten liegen seit 05.10.2026 auf dem eigenen Zweig "daten"
# (im Workflow und lokal als Unterordner daten/ ausgecheckt), der Code auf main. Über TRIKOT_DATEN umstellbar
DATA_DIR = Path(os.environ.get("TRIKOT_DATEN") or ROOT / "daten")
STATE_DIR = DATA_DIR / "state"
SEEN_FILE = STATE_DIR / "seen.json"
STATUS_FILE = STATE_DIR / "status.json"
OUTBOX_FILE = STATE_DIR / "postausgang.json"   # Pushes, die erst nach dem Speichern verschickt werden
REPORT_FILE = DATA_DIR / "TREFFER.md"
DASHBOARD_FILE = DATA_DIR / "treffer.json"
ERROR_LOG = STATE_DIR / "fehlerlog.json"
ERROR_REPORT = DATA_DIR / "FEHLER.md"
FUNDGRUBE_REPORT = DATA_DIR / "FUNDGRUBE.md"
SHOPS_FILE = ROOT / "shops.yaml"                     # gepflegte Shopliste (Code-Zweig)
SHOPS_EXTRA_FILE = DATA_DIR / "shops_fundgrube.yaml"   # per Dashboard aus der Fundgrube aufgenommene Shops


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


def load_shops():
    """Shopliste: shops.yaml plus die per Fundgrube aufgenommenen Shops (ohne Dubletten). Gibt die ganze
    Konfiguration zurück (auch "fyj" usw.), "shops" ist zusammengeführt"""
    cfg = yaml.safe_load(SHOPS_FILE.read_text(encoding="utf-8")) or {}
    shops = list(cfg.get("shops") or [])
    hosts = {_host(s["url"]) for s in shops}
    for s in load_extra_shops():
        if _host(s.get("url", "")) not in hosts:
            shops.append(s)
            hosts.add(_host(s["url"]))
    cfg["shops"] = shops
    return cfg


def load_extra_shops():
    try:
        return yaml.safe_load(SHOPS_EXTRA_FILE.read_text(encoding="utf-8")) or []
    except FileNotFoundError:
        return []


def _host(url):
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def save_json(path, data, compact=False):
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    save_text(path, text)
