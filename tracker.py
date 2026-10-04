#!/usr/bin/env python3
"""
Trikot-Tracker: Einstieg. Der Code liegt im Paket trikot/ (Aufbau siehe trikot/__init__.py).

Modi:
  full      kompletter Durchlauf über alle Quellen (1x täglich, nachts)
  priority  nur Einträge mit prioritaet "hoch" über die Shop-Suchen (3x täglich)
  drop      nur Shops, deren Drop gerade fällig ist
  test      schickt nur eine Test-Benachrichtigung

Lokal testen:  python tracker.py --mode full --dry-run --only "Shopname"
"""
# Alle Namen auch unter tracker.* bereitstellen (Tests, Workflow-Schritt "Fehlschlag ins Fehler-Log")
import datetime as dt  # noqa: F401
import requests  # noqa: F401

from trikot.basis import *  # noqa: F401,F403
from trikot.speicher import *  # noqa: F401,F403
from trikot.abgleich import *  # noqa: F401,F403
from trikot.netz import *  # noqa: F401,F403
from trikot.zustand import *  # noqa: F401,F403
from trikot.preise import *  # noqa: F401,F403
from trikot.rhythmus import *  # noqa: F401,F403
from trikot.quellen.gemeinsam import *  # noqa: F401,F403
from trikot.quellen.shopify import *  # noqa: F401,F403
from trikot.quellen.woo import *  # noqa: F401,F403
from trikot.quellen.suchseiten import *  # noqa: F401,F403
from trikot.quellen.fyj import *  # noqa: F401,F403
from trikot.quellen.wix import *  # noqa: F401,F403
from trikot.quellen import *  # noqa: F401,F403
from trikot.pruefung import *  # noqa: F401,F403
from trikot.melden import *  # noqa: F401,F403
from trikot.issues import *  # noqa: F401,F403
from trikot.berichte import *  # noqa: F401,F403
from trikot.lauf import *  # noqa: F401,F403
from trikot.lauf import main

if __name__ == "__main__":
    main()
