"""HTTP mit Pausen, Wiederholungen und gemeinsamer Shopify-Bremse"""

import threading
import time
from collections import Counter

import requests

from .basis import BUY_COUNTRY, DELAY, SHOPIFY_INTERVAL, TIMEOUT, UA


class RateGate:
    """Gemeinsame Bremse über mehrere Shops. Shopify drosselt pro IP über alle Shops hinweg,
    8 Shops parallel mit je 1 Anfrage/Sek. ergeben nach ca. 1 Min. flächendeckend HTTP 429"""
    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            slot = max(time.time(), self.next)
            self.next = slot + self.interval
        time.sleep(max(0.0, slot - time.time()))

    def penalize(self, seconds):
        with self.lock:
            self.next = max(self.next, time.time() + seconds)


SHOPIFY_GATE = RateGate(SHOPIFY_INTERVAL)


class Http:
    def __init__(self, gate=None, delay=None):
        self.delay = delay or DELAY   # Pause zwischen zwei Anfragen; je Shop überschreibbar (shops.yaml "pause")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
        # Shopify Markets: ohne das Cookie bekäme der GitHub-Server (USA) US-Preise in USD
        self.s.cookies.set("localization", BUY_COUNTRY)
        self.gate = gate
        self.last = 0.0
        self.count = 0
        self.limited = 0     # Anfragen, die trotz Wiederholung gedrosselt blieben (429)
        self.codes = Counter()   # andere Antworten als 200 (z. B. 403 = gesperrt, 404), für ehrliche Quellenwerte
        self.last_status = None  # Status der letzten Antwort von get() ("Verbindung" bei Netzfehler)

    def post(self, url, json=None, headers=None):
        """POST mit derselben Pause und Wiederholung bei Drosselung wie get(); liefert JSON oder None"""
        for attempt in range(3):
            wait = self.delay - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.count += 1
            try:
                r = self.s.post(url, json=json, headers=headers, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(3)
                continue
            if r.status_code == 429:
                if attempt == 2:
                    self.limited += 1
                    return None
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code != 200:
                self.codes[r.status_code] += 1
                return None
            try:
                return r.json()
            except ValueError:
                return None
        return None

    def get(self, url, params=None, want="json"):
        attempts = 5 if self.gate else 3
        for attempt in range(attempts):
            wait = self.delay - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            if self.gate:
                self.gate.wait()
            self.last = time.time()
            self.count += 1
            try:
                r = self.s.get(url, params=params, timeout=TIMEOUT)
                self.last_status = r.status_code
            except requests.RequestException:
                self.last_status = "Verbindung"
                if attempt == attempts - 1:
                    raise
                time.sleep(3 + 7 * attempt)   # 3 s, 10 s, …: kurze Aussetzer der Shops überbrücken
                continue
            if r.status_code == 429:
                if attempt == attempts - 1:
                    self.limited += 1
                    return None
                try:
                    pause = min(float(r.headers.get("Retry-After", 0)), 60)
                except ValueError:
                    pause = 0
                pause = max(pause, 15 * (attempt + 1))
                if self.gate:
                    self.gate.penalize(pause)   # alle Shops hinter der Bremse pausieren
                else:
                    time.sleep(pause)
                continue
            if r.status_code >= 500 and attempt < 2:
                time.sleep(5)
                continue
            if r.status_code != 200:
                self.codes[r.status_code] += 1
            if want == "json":
                if r.status_code != 200:
                    return None
                try:
                    return r.json()
                except ValueError:
                    return None
            return r.text if r.status_code == 200 else None
        return None
