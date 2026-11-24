# -*- coding: utf-8 -*-
"""
PRIMA E DOPO - MOTORE DI CALCOLO (versione 1.10)
===============================================
© 2026 Edoardo Battistel

Lo stesso oggetto del cielo fotografato a anni di distanza:
  1. cerca le epoche negli archivi (DSS 1950 e 1990 da SkyView/STScI, Pan-STARRS
     2010-2014, Chandra da HEASARC) e tra i file già scaricati;
  2. scarica, riproietta tutto su una griglia comune (Nord in alto, Est a sinistra),
     allinea finemente con le stelle del campo (o con il punto più brillante nei raggi X);
  3. uguaglia nitidezza e luminosità tra strumenti diversi;
  4. misura il movimento: espansione dei filamenti (M 1, frecce, velocità in km/s,
     anno dell'esplosione) o moto proprio di una stella (stella di Barnard);
  5. crea GIF, MP4 e una pagina con cursore che funziona anche senza Internet.

Senza interfaccia grafica: la usa prima_e_dopo.py (finestra e righe di comando).
"""

import base64
import gzip
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

NOME_PROGRAMMA = "Prima e dopo"
VERSIONE = "1.10"
AUTORE = "Edoardo Battistel"
COPYRIGHT = f"© 2026 {AUTORE}"
FIRMA = f"© 2026 {AUTORE}"
COPYRIGHT_ASCII = f"(C) 2026 {AUTORE}"
UA = {"User-Agent": f"PrimaEDopo/{VERSIONE} (programma di astronomia amatoriale)"}

URL_SKYVIEW = "https://skyview.gsfc.nasa.gov/cgi-bin/images"
URL_SKYVIEW_TEMP = "https://skyview.gsfc.nasa.gov/tempspace/fits/"
URL_DSS_STSCI = "https://archive.stsci.edu/cgi-bin/dss_search"
URL_PS1_NOMI = "https://ps1images.stsci.edu/cgi-bin/ps1filenames.py"
URL_PS1_TAGLIO = "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi"
URL_HEASARC_TAP = "https://heasarc.gsfc.nasa.gov/xamin/vo/tap/sync"
URL_CHANDRA_FTP = "https://heasarc.gsfc.nasa.gov/FTP/chandra/data/byobsid/{d}/{obsid}/primary/"

TIMEOUT_DOMANDA = 60          # interrogazioni brevi (elenchi, intestazioni)
TIMEOUT_FILE = 300            # scaricamento di un file intero (tempo massimo totale)
CARTELLA_EPOCHE = "epoche"
CARTELLA_LAVORO = "lavoro"
FILE_EPOCHE = "epoche.json"
FILE_RISULTATI = "risultati.json"
KMS = 4.74047                 # km/s per (1"/anno a 1 pc)
DTYPE = np.float32


# =============================================================================
# OGGETTI DELLA LISTA
# =============================================================================
# tipo: "espansione" (misura dell'ingrandimento attorno a un centro),
#       "moto_proprio" (una stella che si sposta), "animazione" (solo confronto)
OGGETTI = [
    dict(chiave="M1_ottico", nome="M 1 – Nebulosa del Granchio (luce visibile)",
         breve="M 1 Granchio – filamenti", ra=83.633083, dec=22.014500,
         campo_arcmin=14.0, scala_arcsec=1.0, tipo="espansione", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico",
         alias=r"(^|[^a-z0-9])(m_?1|crab|granchio)($|[^a-z0-9])",
         centro=(83.633083, 22.014500), centro_nome="pulsar del Granchio",
         ellisse=(4.3, 3.1, 130.0), raggio_interno_arcsec=25.0, raggio_guscio_arcsec=90.0,
         distanza_pc=2000.0, anno_evento=1054,
         descrizione=("Il resto della supernova vista dagli astronomi cinesi e arabi nel 1054. "
                      "I filamenti si allontanano dal centro a circa 1500 km/s: in 60 anni (lastre "
                      "di Palomar degli anni '50 contro Pan-STARRS) si spostano di una decina di "
                      "secondi d'arco. Il programma misura l'ingrandimento, disegna le frecce e "
                      "calcola in che anno sarebbe esplosa la stella se si espandesse sempre "
                      "alla stessa velocità.")),
    dict(chiave="M1_raggiX", nome="M 1 – il cuore in raggi X (Chandra)",
         breve="M 1 Granchio – raggi X", ra=83.633083, dec=22.014500,
         campo_arcmin=4.0, scala_arcsec=0.5, tipo="animazione", allinea="picco",
         fonti=["chandra"], banda_locale="raggi_x", max_epoche_archivio=8,
         alias=r"(^|[^a-z0-9])(m_?1|crab|granchio)($|[^a-z0-9])",
         descrizione=("La nebulosa a vento della pulsar vista da Chandra: anelli, «wisps» e il getto "
                     "cambiano in pochi mesi. Il programma prende le osservazioni ACIS senza reticolo "
                     "dall'archivio HEASARC (al massimo 8, distribuite negli anni) più i tuoi file "
                     "Chandra di M 1, e le allinea sulla pulsar (il punto più brillante).")),
    dict(chiave="Barnard", nome="Stella di Barnard (moto proprio)",
         breve="Stella di Barnard", ra=269.452075, dec=4.693391,
         campo_arcmin=16.0, scala_arcsec=1.0, tipo="moto_proprio", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico",
         alias=r"barnard", epoca_centro=1981.0,
         pm_mas=(-801.551, 10362.394), plx_mas=546.976,     # Gaia DR3, epoca 2016,0
         pos_catalogo=(269.448502, 4.739420, 2016.0), cerca_gaia=True,
         descrizione=("La stella con il moto proprio più grande del cielo: 10,4″ all'anno verso nord. "
                      "Tra la lastra di Palomar degli anni '50 e Pan-STARRS (2012 circa) si è spostata "
                      "di più di 10 primi d'arco, un terzo del diametro della Luna. Il programma la "
                      "ritrova in ogni epoca, misura il moto proprio e la velocità e li confronta con Gaia.")),
    dict(chiave="EtaCar_Hubble", nome="Eta Carinae – la nebulosa Homunculus (Hubble)",
         breve="Eta Carinae – Homunculus", ra=161.264963, dec=-59.684528,
         campo_arcmin=0.5, scala_arcsec=0.05, tipo="espansione", allinea="picco",
         picco_raggio_arcsec=2.0, picco_max_arcsec=5.0, picco_sigma_arcsec=0.3,
         fonti=["hubble"], banda_locale="ottico", max_epoche_archivio=6,
         filtri_hubble=["F631N", "F658N", "F656N", "F550M", "F555W", "F606W", "F625W", "F675W", "F814W"],
         alias=r"(^|[^a-z0-9])(eta_?car|homunculus|ngc_?3372)($|[^a-z0-9])",
         centro=(161.264963, -59.684528), centro_nome="stella Eta Carinae",
         ellisse=(10.0, 6.0, 132.0), raggio_interno_arcsec=1.5, scala_max=1.45,
         dettagli_arcsec=(0.1, 0.5), centro_fisso=True,
         distanza_pc=2350.0, anno_evento=1843,
         descrizione=("Nel 1843 Eta Carinae divenne per qualche anno la seconda stella più brillante del cielo: "
                      "la «Grande Eruzione» espulse circa dieci masse solari di gas, che oggi formano i due lobi "
                      "dell'Homunculus (18″ di lunghezza). Le immagini Hubble dal 1993 a oggi lo mostrano "
                      "crescere di circa 0,06″ all'anno, a 650 km/s. Il programma prende da MAST al massimo 6 "
                      "epoche nello stesso tipo di filtro, le allinea sulla stella e misura l'espansione come per M 1: "
                      "qui l'anno trovato dovrebbe essere vicino al 1843.")),
    dict(chiave="CasA_raggiX", nome="Cassiopea A – resto di supernova in raggi X (Chandra)",
         breve="Cassiopea A – raggi X", ra=350.8500, dec=58.8150,
         campo_arcmin=7.0, scala_arcsec=0.5, tipo="espansione", allinea="nessuno",
         fonti=["chandra"], banda_locale="raggi_x", max_epoche_archivio=8,
         alias=r"(^|[^a-z0-9])(cas_?a|cassiopea_?a|cassiopeia_?a)($|[^a-z0-9])",
         centro=(350.86642, 58.81178), centro_nome="stella di neutroni centrale",
         ellisse=(2.9, 2.9, 0.0), raggio_interno_arcsec=40.0,
         distanza_pc=3400.0, anno_evento=1680, anno_evento_incerto=True,
         descrizione=("Il resto di supernova più giovane della nostra Galassia: la luce dell'esplosione "
                      "arrivò sulla Terra intorno al 1680 (forse la «stella» annotata da Flamsteed), ma "
                      "nessuno la notò davvero. Chandra la osserva quasi ogni anno dal 1999: il guscio di "
                      "gas a 30 milioni di gradi si allarga a 5000 km/s. Il programma misura "
                      "l'espansione tra la prima e l'ultima osservazione, come per M 1.")),
    dict(chiave="Groombridge1830", nome="Groombridge 1830 (moto proprio)",
         breve="Groombridge 1830", ra=178.24488, dec=37.71867,
         campo_arcmin=16.0, scala_arcsec=1.0, tipo="moto_proprio", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico", alias=r"groombridge",
         epoca_centro=1982.0, pos_catalogo=(178.24488, 37.71867, 2000.0),
         pm_mas=(4003.98, -5813.0), plx_mas=109.0, cerca_gaia=True,
         descrizione=("Una stella vecchia dell'alone della Galassia che attraversa il disco a più di "
                      "250 km/s: 7″ all'anno verso sud-est. Moto proprio e distanza vengono chiesti "
                      "all'archivio Gaia, poi il programma la ritrova nelle lastre di Palomar e in Pan-STARRS.")),
    dict(chiave="61Cygni", nome="61 Cygni (moto proprio, la prima distanza misurata)",
         breve="61 Cygni", ra=316.72480, dec=38.74942,
         campo_arcmin=14.0, scala_arcsec=1.0, tipo="moto_proprio", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico", alias=r"61_?cyg",
         epoca_centro=1982.0, pos_catalogo=(316.72480, 38.74942, 2000.0),
         pm_mas=(4164.2, 3250.0), plx_mas=286.0, cerca_gaia=True,
         descrizione=("La «stella volante» di Piazzi: per il suo moto proprio di 5″ all'anno Bessel la "
                      "scelse e nel 1838 ne misurò la parallasse, la prima distanza di una stella. È una "
                      "coppia (A e B a circa 30″): il programma segue la A con i dati di Gaia.")),
    dict(chiave="Lalande21185", nome="Lalande 21185 (moto proprio)",
         breve="Lalande 21185", ra=165.83413, dec=35.96989,
         campo_arcmin=14.0, scala_arcsec=1.0, tipo="moto_proprio", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico", alias=r"lalande",
         epoca_centro=1982.0, pos_catalogo=(165.83413, 35.96989, 2000.0),
         pm_mas=(-580.3, -4767.1), plx_mas=392.6, cerca_gaia=True,
         descrizione=("Una nana rossa a 8 anni luce, una delle stelle più vicine al Sole: 4,8″ all'anno "
                      "verso sud. Moto proprio e distanza da Gaia.")),
    dict(chiave="NGC2261", nome="NGC 2261 – Nebulosa Variabile di Hubble",
         breve="NGC 2261 – Hubble", ra=99.79167, dec=8.74444,
         campo_arcmin=6.0, scala_arcsec=1.0, tipo="animazione", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico", alias=r"ngc_?2261",
         descrizione=("Un ventaglio di gas illuminato dalla giovane stella R Monocerotis. Nubi di polvere "
                      "vicine alla stella ci passano davanti e proiettano ombre: la forma della nebulosa "
                      "cambia in settimane. Fu l'ultimo oggetto fotografato da Edwin Hubble (1949) e la "
                      "prima foto ufficiale del telescopio Hale. Solo animazione (cambia la luce, non c'è "
                      "un movimento da misurare).")),
    dict(chiave="NGC1555", nome="NGC 1555 – Nebulosa Variabile di Hind",
         breve="NGC 1555 – Hind", ra=65.48750, dec=19.53500,
         campo_arcmin=6.0, scala_arcsec=1.0, tipo="animazione", allinea="stelle",
         fonti=["dss1_red", "dss2_red", "ps1_r"], banda_locale="ottico", alias=r"ngc_?1555|hind",
         descrizione=("La nebulosa accanto a T Tauri, la stella che dà il nome alle giovani stelle «T Tauri». "
                      "Scoperta da Hind nel 1852, poi quasi sparita, poi ricomparsa: la sua luminosità "
                      "cambia perché cambia la luce che la illumina. Solo animazione.")),
    dict(chiave="file_tuoi", nome="File tuoi (qualsiasi oggetto)",
         breve="File tuoi", ra=None, dec=None, campo_arcmin=None, scala_arcsec=None,
         tipo="animazione", allinea="stelle", fonti=[], banda_locale=None, alias=None,
         descrizione=("Scegli tu i FITS (almeno due epoche dello stesso oggetto, con coordinate WCS) "
                      "con «Aggiungi file tuoi…». Il programma li mette sulla stessa griglia, li "
                      "allinea con le stelle e crea GIF, MP4 e pagina con cursore.")),
]
IN_ARRIVO = [
    ("V838 Monocerotis – eco di luce (Hubble 2002-2006)", "versione futura"),
    ("SN 1987A – l'anello che si accende", "versione futura"),
]

FONTI = {
    "dss1_red": dict(etichetta="DSS1 rosso", strumento="Palomar Schmidt 1,2 m, lastra POSS-I E (103aE)",
                     banda="rosso (con H-alfa)", survey_skyview="DSS1 Red", stsci="poss1_red",
                     anno_ripiego=1953.0, nota_ripiego="POSS-I: 1949-1958"),
    "dss2_red": dict(etichetta="DSS2 rosso", strumento="Palomar Schmidt 1,2 m, lastra POSS-II F (IIIaF)",
                     banda="rosso (con H-alfa)", survey_skyview="DSS2 Red", stsci="poss2ukstu_red",
                     anno_ripiego=1991.0, nota_ripiego="POSS-II: 1985-2000"),
    "ps1_r": dict(etichetta="Pan-STARRS r", strumento="Pan-STARRS1 1,8 m (Haleakala), immagine sommata",
                  banda="r (con H-alfa)", anno_ripiego=2012.0, nota_ripiego="survey 3π: 2010-2014"),
    "chandra": dict(etichetta="Chandra ACIS", strumento="Chandra ACIS", banda="raggi X 0,5-7 keV"),
    "hubble": dict(etichetta="Hubble", strumento="Hubble Space Telescope", banda="visibile"),
}


def oggetto(chiave):
    for o in OGGETTI:
        if o["chiave"] == chiave:
            return dict(o)
    raise KeyError(chiave)


# =============================================================================
# CARTELLE
# =============================================================================
def cartella_astronomia():
    for n in ("Scrivania", "Desktop"):
        p = Path.home() / n / "Astronomia"
        if p.is_dir():
            return p
    return Path.home() / "Scrivania" / "Astronomia"


def cartella_risultati(base=None):
    return Path(base) if base else cartella_astronomia() / "Prima_e_dopo"


def cartella_oggetto(ogg, base=None):
    return cartella_risultati(base) / ogg["chiave"]


def risorsa(nome):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / nome


def ambiente_esterno():
    """Ambiente per i programmi esterni (zenity, xdg-open, ffmpeg) senza le librerie di PyInstaller."""
    env = dict(os.environ)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    return env


# =============================================================================
# RETE (sempre con un tempo massimo)
# =============================================================================
class Fermato(Exception):
    """L'utente ha premuto «Ferma»."""


def scarica(url, timeout=TIMEOUT_DOMANDA, progresso=None, ferma=None, max_byte=None, dati=None):
    """Scarica un indirizzo con un tempo massimo TOTALE (non solo per pacchetto); con 'dati' fa un POST."""
    req = urllib.request.Request(url, data=dati, headers=dict(UA, **({"Content-Type": "application/x-www-form-urlencoded"}
                                                                     if dati is not None else {})))
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=min(timeout, 60)) as f:
        totale = int(f.headers.get("Content-Length") or 0)
        parti, n = [], 0
        while True:
            if ferma is not None and ferma.is_set():
                raise Fermato()
            if time.time() - t0 > timeout:
                raise TimeoutError(f"più di {timeout} s per {url.split('?')[0]}")
            b = f.read(256 * 1024)
            if not b:
                break
            parti.append(b)
            n += len(b)
            if max_byte and n > max_byte:
                raise ValueError(f"risposta troppo grande (> {max_byte // 1024**2} MB)")
            if progresso:
                progresso(n, totale)
    return b"".join(parti)


def e_fits_bytes(b):
    if b[:2] == b"\x1f\x8b":
        try:
            b = gzip.decompress(b[:200000]) if len(b) < 200000 else gzip.GzipFile(fileobj=io.BytesIO(b)).read(100)
        except Exception:
            return False
    return b[:9] == b"SIMPLE  ="


def intestazione_grezza(b):
    """Intestazione primaria di un FITS letta dai byte (senza astropy): {chiave: valore}."""
    if b[:2] == b"\x1f\x8b":
        b = gzip.GzipFile(fileobj=io.BytesIO(b)).read(2880 * 40)
    h = {}
    for i in range(0, min(len(b), 2880 * 60), 80):
        c = b[i:i + 80].decode("ascii", "replace")
        k = c[:8].strip()
        if k == "END":
            break
        if c[8:10] != "= ":
            continue
        v = c[10:].strip()
        if v.startswith("'"):
            e = v.find("'", 1)
            v = v[1:e].strip() if e > 0 else v[1:]
        else:
            v = v.split("/")[0].strip()
            try:
                v = float(v) if any(x in v for x in ".E") else int(v)
            except ValueError:
                pass
        h.setdefault(k, v)
    return h


# =============================================================================
# DATE
# =============================================================================
MJD_0 = datetime(1858, 11, 17, tzinfo=timezone.utc)


def anno_decimale(dt):
    a = dt.year
    inizio = datetime(a, 1, 1, tzinfo=timezone.utc)
    fine = datetime(a + 1, 1, 1, tzinfo=timezone.utc)
    return a + (dt - inizio).total_seconds() / (fine - inizio).total_seconds()


def anno_da_mjd(mjd):
    return anno_decimale(MJD_0 + timedelta(days=float(mjd)))


def data_da_anno(anno):
    a = int(math.floor(anno))
    inizio = datetime(a, 1, 1, tzinfo=timezone.utc)
    fine = datetime(a + 1, 1, 1, tzinfo=timezone.utc)
    return inizio + (fine - inizio) * (anno - a)


def leggi_data_testo(t):
    """'2024-12-23T23:18:57', '1955-11-08', '08/11/55', '1955.85' -> anno decimale (o None)."""
    t = str(t or "").strip()
    if not t:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d*)?))?)?", t)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        hh, mi, ss = int(m[4] or 0), int(m[5] or 0), float(m[6] or 0)
        try:      # ore, minuti e secondi sommati: lo STScI scrive anche «09:60:00»
            return anno_decimale(datetime(y, mo, d, tzinfo=timezone.utc) + timedelta(hours=hh, minutes=mi, seconds=ss))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", t)                # ESO: aaaa/mm/gg
    if m:
        try:
            return anno_decimale(datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", t)            # vecchio formato FITS gg/mm/aa
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        y = y + 1900 if y < 100 else y
        try:
            return anno_decimale(datetime(y, mo, d, tzinfo=timezone.utc))
        except ValueError:
            return None
    m = re.match(r"^(1[89]\d\d|20\d\d)(\.\d+)?$", t)
    if m:
        return float(t)
    return None


def anno_da_intestazione(h):
    """Anno decimale dell'osservazione da un'intestazione (dizionario)."""
    for k in ("MJD-OBS", "MJD_OBS", "MJD-BEG", "MJDSTART", "OBSMJD"):
        try:
            v = float(h.get(k))
            if 30000 < v < 80000:
                return anno_da_mjd(v)
        except (TypeError, ValueError):
            pass
    for k in ("DATE-OBS", "DATE_OBS", "DATEOBS", "DATE-BEG", "OBS-DATE"):
        v = h.get(k)
        if v:
            a = leggi_data_testo(v)
            if a is not None:
                tempo = h.get("TIME-OBS") or h.get("UT") or h.get("UTSTART")
                if tempo and "T" not in str(v) and re.match(r"^\d{1,2}:\d{2}", str(tempo)):
                    a2 = leggi_data_testo(f"{str(v)[:10]}T{tempo}")
                    a = a2 if a2 is not None else a
                return a
    return None


MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def testo_mese(a):
    """1954.2 -> 'mar 1954' (per le epoche vicine, come nei raggi X)."""
    if a is None:
        return "?"
    d = data_da_anno(a)
    return f"{MESI[d.month - 1]} {d.year}"


def testo_anno(a, dec=1):
    if a is None:
        return "?"
    return f"{a:.{dec}f}".replace(".", ",")


# =============================================================================
# GRIGLIA COMUNE (proiezione gnomonica TAN, Nord in alto, Est a sinistra)
# =============================================================================
class Griglia:
    """Pixel 0-based, origine in basso a sinistra come nei FITS (dati[y, x])."""

    def __init__(self, ra0, dec0, scala_arcsec, n):
        self.ra0, self.dec0 = float(ra0), float(dec0)
        self.scala = float(scala_arcsec)
        self.n = int(n)
        self.c = (self.n - 1) / 2.0
        self._s = math.radians(self.scala / 3600.0)

    @classmethod
    def per_oggetto(cls, ogg, ra=None, dec=None):
        ra = ogg["ra"] if ra is None else ra
        dec = ogg["dec"] if dec is None else dec
        n = int(round(ogg["campo_arcmin"] * 60 / ogg["scala_arcsec"]))
        return cls(ra, dec, ogg["scala_arcsec"], n + (n % 2))

    def pix2world(self, x, y):
        xi = -(np.asarray(x, float) - self.c) * self._s
        eta = (np.asarray(y, float) - self.c) * self._s
        a0, d0 = math.radians(self.ra0), math.radians(self.dec0)
        rho = np.hypot(xi, eta)
        cc = np.arctan(rho)
        with np.errstate(invalid="ignore", divide="ignore"):
            q = np.where(rho > 0, eta * np.sin(cc) * math.cos(d0) / np.where(rho > 0, rho, 1), 0.0)
            dec = np.arcsin(np.clip(np.cos(cc) * math.sin(d0) + q, -1, 1))
        ra = a0 + np.arctan2(xi * np.sin(cc), rho * math.cos(d0) * np.cos(cc) - eta * math.sin(d0) * np.sin(cc))
        return np.degrees(ra) % 360.0, np.degrees(dec)

    def world2pix(self, ra, dec):
        a, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
        a0, d0 = math.radians(self.ra0), math.radians(self.dec0)
        cosc = math.sin(d0) * np.sin(d) + math.cos(d0) * np.cos(d) * np.cos(a - a0)
        xi = np.cos(d) * np.sin(a - a0) / cosc
        eta = (math.cos(d0) * np.sin(d) - math.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
        return self.c - xi / self._s, self.c + eta / self._s

    def intestazione(self):
        return {"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRVAL1": self.ra0, "CRVAL2": self.dec0,
                "CRPIX1": self.c + 1, "CRPIX2": self.c + 1, "CDELT1": -self.scala / 3600.0,
                "CDELT2": self.scala / 3600.0, "CUNIT1": "deg", "CUNIT2": "deg", "RADESYS": "ICRS",
                "EQUINOX": 2000.0}

    def descrizione(self):
        return f"{self.n}×{self.n} pixel da {self.scala:g}″ ({self.n * self.scala / 60:.1f}′)"


def separazione_arcsec(ra1, dec1, ra2, dec2):
    a1, d1, a2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((a2 - a1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * 3600


# =============================================================================
# LETTURA DEI FITS (astropy sul PC)
# =============================================================================
ESTENSIONI_FITS = (".fits", ".fit", ".fts", ".fits.gz", ".fit.gz", ".fts.gz")
TELESCOPI_X = ("CHANDRA", "XMM", "NEWTON", "ROSAT", "EROSITA", "SRG", "NUSTAR", "SUZAKU", "SWIFT-XRT")


def e_file_fits(p):
    n = str(p).lower()
    return n.endswith(ESTENSIONI_FITS)


def _intestazione_dict(*hh):
    d = {}
    for h in reversed([h for h in hh if h is not None]):
        for k in list(h.keys()):
            if k and k not in ("COMMENT", "HISTORY", ""):
                try:
                    d[str(k).upper()] = h[k]
                except Exception:
                    pass
    return d


def e_raggi_x(h):
    tel = str(h.get("TELESCOP", "")).upper()
    return any(t in tel for t in TELESCOPI_X) or str(h.get("INSTRUME", "")).upper() in ("ACIS", "HRC", "EPN", "EMOS1", "EMOS2")


def immagine_da_eventi(x, y, energia, col, ra, dec, lato=1024, emin=500.0, emax=7000.0):
    """Lista di eventi (raggi X) -> immagine dei conteggi lato×lato centrata su (ra, dec).
    col: dict con ctype, crval, crpix, cdelt delle colonne x e y (coordinate «sky»)."""
    from astropy.wcs import WCS
    hw = {"CTYPE1": col["ctype"][0], "CTYPE2": col["ctype"][1], "CRVAL1": col["crval"][0],
          "CRVAL2": col["crval"][1], "CRPIX1": col["crpix"][0], "CRPIX2": col["crpix"][1],
          "CDELT1": col["cdelt"][0], "CDELT2": col["cdelt"][1]}
    w = WCS(hw)
    xc, yc = w.all_world2pix([ra], [dec], 1)
    x0 = math.floor(float(xc[0])) - lato // 2
    y0 = math.floor(float(yc[0])) - lato // 2
    sel = np.isfinite(x) & np.isfinite(y)
    if energia is not None:
        sel &= (energia >= emin) & (energia <= emax)
    img, _, _ = np.histogram2d(np.asarray(y)[sel], np.asarray(x)[sel],
                               bins=[np.arange(lato + 1) + y0 + 0.5, np.arange(lato + 1) + x0 + 0.5])
    hw["CRPIX1"] = col["crpix"][0] - x0
    hw["CRPIX2"] = col["crpix"][1] - y0
    return img.astype(DTYPE), hw


def leggi_immagine(percorso, ra=None, dec=None):
    """Legge un FITS: dict(dati, wcs, intestazione, raggi_x, esposizione).
    Accetta immagini 2D (anche in estensioni) e liste di eventi Chandra/XMM."""
    import warnings as _w
    from astropy.io import fits
    from astropy.wcs import WCS
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        with fits.open(percorso, memmap=False) as hdul:
            hp = hdul[0].header
            scelta = None
            for hdu in hdul:
                h = hdu.header
                n = h.get("NAXIS", 0)
                if hdu.data is None:
                    continue
                if (n == 2 or (n == 3 and h.get("NAXIS3", 1) == 1)) and str(h.get("XTENSION", "IMAGE")).strip() in ("IMAGE", ""):
                    if h.get("NAXIS1", 0) > 8 and h.get("NAXIS2", 0) > 8:
                        scelta = ("img", hdu)
                        break
            if scelta is None:
                for hdu in hdul:
                    h = hdu.header
                    if str(h.get("XTENSION", "")).strip() == "BINTABLE" and "EVENT" in str(h.get("EXTNAME", "")).upper():
                        scelta = ("eventi", hdu)
                        break
            if scelta is None:
                raise ValueError("nessuna immagine 2D né lista di eventi nel file")
            tipo, hdu = scelta
            hd = _intestazione_dict(hdu.header, hp)
            if tipo == "img":
                d = np.asarray(hdu.data, dtype=DTYPE)
                if d.ndim == 3:
                    d = d[0]
                w = WCS(hdu.header, naxis=2)
                w = w.celestial if w.has_celestial else None
            else:
                nomi = [c.lower() for c in hdu.columns.names]
                ix, iy = nomi.index("x") + 1, nomi.index("y") + 1
                h = hdu.header
                col = {"ctype": (h[f"TCTYP{ix}"], h[f"TCTYP{iy}"]), "crval": (h[f"TCRVL{ix}"], h[f"TCRVL{iy}"]),
                       "crpix": (h[f"TCRPX{ix}"], h[f"TCRPX{iy}"]), "cdelt": (h[f"TCDLT{ix}"], h[f"TCDLT{iy}"])}
                en = np.asarray(hdu.data["energy"], float) if "energy" in nomi else None
                if ra is None:
                    ra, dec = float(hd.get("RA_TARG", hd.get("RA_NOM"))), float(hd.get("DEC_TARG", hd.get("DEC_NOM")))
                d, hw = immagine_da_eventi(np.asarray(hdu.data["x"], float), np.asarray(hdu.data["y"], float),
                                           en, col, ra, dec)
                w = WCS(hw)
    if w is None:
        raise ValueError("il file non ha coordinate celesti (WCS)")
    x_ray = e_raggi_x(hd)
    try:
        esp = float(hd.get("EXPOSURE") or hd.get("LIVETIME") or hd.get("EXPTIME") or 0)
    except (TypeError, ValueError):
        esp = 0.0
    if not x_ray:
        d[d == 0] = np.nan                         # nei FITS ottici lo 0 vuol dire «senza dati»
    return dict(dati=d, wcs=w, intestazione=hd, raggi_x=x_ray, esposizione=esp)


def scala_sorgente_arcsec(w, shape):
    ny, nx = shape
    x0, y0 = (nx - 1) / 2, (ny - 1) / 2
    ra, dec = w.all_pix2world(np.array([x0, x0 + 1, x0]), np.array([y0, y0, y0 + 1]), 0)
    s1 = separazione_arcsec(ra[0], dec[0], ra[1], dec[1])
    s2 = separazione_arcsec(ra[0], dec[0], ra[2], dec[2])
    return (s1 + s2) / 2


def riduci_blocchi(a, f, somma=False):
    ny, nx = a.shape
    ny2, nx2 = ny // f * f, nx // f * f
    b = a[:ny2, :nx2].reshape(ny2 // f, f, nx2 // f, f)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        r = np.nansum(b, axis=(1, 3)) if somma else np.nanmean(b, axis=(1, 3))
    if somma:
        r[np.all(~np.isfinite(b), axis=(1, 3))] = np.nan
    return r.astype(DTYPE)


def campiona(a, xs, ys, ordine=1):
    """Valori dell'array nei punti (xs, ys) (pixel 0-based), i NaN restano fuori."""
    ok = np.isfinite(a)
    pieno = np.where(ok, a, 0).astype(DTYPE)
    v = ndi.map_coordinates(pieno, [ys, xs], order=ordine, mode="constant", cval=0.0, prefilter=False)
    pesi = ndi.map_coordinates(ok.astype(DTYPE), [ys, xs], order=1, mode="constant", cval=0.0, prefilter=False)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(pesi > 0.6, v / np.where(pesi > 0, pesi, 1), np.nan)
    return out.astype(DTYPE)


def riproietta(img, griglia):
    """Porta un'immagine (dict di leggi_immagine) sulla griglia comune."""
    d, w = img["dati"], img["wcs"]
    s_src = scala_sorgente_arcsec(w, d.shape)
    f = int(griglia.scala / s_src) if griglia.scala / s_src >= 2 else 1
    sorgente = riduci_blocchi(d, f, somma=img["raggi_x"]) if f > 1 else d
    n = griglia.n
    out = np.empty((n, n), DTYPE)
    xx = np.arange(n, dtype=float)
    for y0 in range(0, n, 256):
        ys, xs = np.mgrid[y0:min(y0 + 256, n), 0:n].astype(float)
        ra, dec = griglia.pix2world(xs.ravel(), ys.ravel())
        px, py = w.all_world2pix(ra, dec, 0)
        px, py = np.asarray(px, float), np.asarray(py, float)
        if f > 1:
            px, py = (px - (f - 1) / 2) / f, (py - (f - 1) / 2) / f
        out[y0:y0 + ys.shape[0]] = campiona(sorgente, px, py).reshape(ys.shape)
    del xx
    if img["raggi_x"]:
        out *= (griglia.scala / (s_src * f)) ** 2       # conteggi per pixel della griglia
    return out, s_src


# =============================================================================
# STELLE E ALLINEAMENTO FINE
# =============================================================================
def rumore_robusto(v):
    v = v[np.isfinite(v)]
    if v.size < 10:
        return 1.0
    m = np.median(v)
    s = 1.4826 * np.median(np.abs(v - m))
    return float(s) if s > 0 else float(np.std(v) or 1.0)


def maschera_ellisse(griglia, ogg, fattore=1.0):
    """Ellisse della nebulosa (semiassi in primi, angolo di posizione da Nord verso Est)."""
    n = griglia.n
    if not ogg.get("ellisse"):
        return np.zeros((n, n), bool)
    a, b, pa = ogg["ellisse"]
    cx, cy = griglia.world2pix(*ogg.get("centro", (ogg["ra"], ogg["dec"])))
    y, x = np.mgrid[0:n, 0:n].astype(float)
    dx, dy = -(x - cx) * griglia.scala / 60, (y - cy) * griglia.scala / 60     # primi: Est, Nord
    t = math.radians(pa)
    u = dx * math.sin(t) + dy * math.cos(t)                   # lungo l'asse maggiore
    v = dx * math.cos(t) - dy * math.sin(t)
    return (u / (a * fattore)) ** 2 + (v / (b * fattore)) ** 2 <= 1.0


def trova_stelle(a, escludi=None, max_n=400, soglia=6.0):
    """Sorgenti puntiformi: (x, y, flusso) ordinate dalla più brillante."""
    ok = np.isfinite(a)
    if ok.sum() < 100:
        return np.zeros((0, 3))
    b = np.where(ok, a - np.nanmedian(a), 0.0).astype(DTYPE)
    d = ndi.gaussian_filter(b, 1.0) - ndi.gaussian_filter(b, 4.0)
    sig = rumore_robusto(d[ok][::max(1, ok.sum() // 400000)])
    picchi = (d == ndi.maximum_filter(d, 7)) & (d > soglia * sig) & ok
    picchi &= ndi.binary_erosion(ok, iterations=6)
    if escludi is not None:
        picchi &= ~escludi
    ys, xs = np.nonzero(picchi)
    if not len(xs):
        return np.zeros((0, 3))
    fl = d[ys, xs]
    o = np.argsort(fl)[::-1][:max_n]
    ys, xs, fl = ys[o], xs[o], fl[o]
    out = []
    for y, x, f in zip(ys, xs, fl):
        sub = d[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3]
        sub = np.clip(sub, 0, None)
        if sub.sum() <= 0:
            continue
        yy, xx = np.mgrid[max(y - 2, 0):max(y - 2, 0) + sub.shape[0], max(x - 2, 0):max(x - 2, 0) + sub.shape[1]]
        out.append((float((xx * sub).sum() / sub.sum()), float((yy * sub).sum() / sub.sum()), float(f)))
    return np.array(out)


def _accoppia(pa, pb, raggio):
    """Per ogni stella di pa la più vicina di pb entro raggio (indici unici)."""
    from scipy.spatial import cKDTree
    if len(pa) == 0 or len(pb) == 0:
        return np.zeros(0, int), np.zeros(0, int)
    d, j = cKDTree(pb).query(pa, distance_upper_bound=raggio)
    i = np.nonzero(np.isfinite(d))[0]
    j = j[i]
    d = d[i]
    o = np.argsort(d)
    _, primo = np.unique(j[o], return_index=True)
    sel = o[primo]
    return i[sel], j[sel]


def stima_trasformazione(st_img, st_rif, max_spost=15.0):
    """Trasformazione affine q = B p + u dai pixel del riferimento (p) a quelli
    dell'immagine (q). Restituisce (B, u, n_stelle, rms) oppure None."""
    if len(st_img) < 3 or len(st_rif) < 3:
        return None
    a, r = st_img[:150, :2], st_rif[:150, :2]
    diff = (a[None, :, :] - r[:, None, :]).reshape(-1, 2)
    diff = diff[np.all(np.abs(diff) < max_spost, axis=1)]
    if len(diff) < 3:
        return None
    nb = int(2 * max_spost)
    h, ex, ey = np.histogram2d(diff[:, 0], diff[:, 1], bins=nb, range=[[-max_spost, max_spost]] * 2)
    h = ndi.gaussian_filter(h, 0.8)
    ix, iy = np.unravel_index(int(np.argmax(h)), h.shape)
    spost = np.array([(ex[ix] + ex[ix + 1]) / 2, (ey[iy] + ey[iy + 1]) / 2])
    B, u = np.eye(2), spost.copy()
    pa, pr = st_img[:, :2], st_rif[:, :2]
    risultato = None
    for raggio in (3.0, 2.0, 1.5, 1.5):
        prev = pr @ B.T + u
        ir, ii = _accoppia(prev, pa, raggio)
        if len(ir) < 3:
            break
        P, Q = pr[ir], pa[ii]
        for _ in range(3):
            if len(P) >= 6:
                X = np.column_stack([P, np.ones(len(P))])
                sol, *_ = np.linalg.lstsq(X, Q, rcond=None)
                B, u = sol[:2].T, sol[2]
            else:
                B, u = np.eye(2), np.median(Q - P, axis=0)
            res = np.hypot(*(Q - (P @ B.T + u)).T)
            rms = float(np.sqrt(np.mean(res ** 2)))
            tieni = res < max(3 * 1.4826 * np.median(res), 0.5)
            if tieni.all() or tieni.sum() < 3:
                break
            P, Q = P[tieni], Q[tieni]
        risultato = (B.copy(), u.copy(), len(P), rms)
    return risultato


def applica_trasformazione(a, B, u):
    n_y, n_x = a.shape
    ys, xs = np.mgrid[0:n_y, 0:n_x].astype(float)
    qx = B[0, 0] * xs + B[0, 1] * ys + u[0]
    qy = B[1, 0] * xs + B[1, 1] * ys + u[1]
    return campiona(a, qx.ravel(), qy.ravel()).reshape(a.shape)


def picco(a, centro=None, raggio=None, sigma=2.0):
    """Posizione (x, y) del punto più brillante (levigato), vicino al centro se indicato.
    Con 'sigma' grande anche una stella satura (buco al centro) dà il centro giusto."""
    b = ndi.gaussian_filter(np.nan_to_num(a), sigma)
    if centro is not None and raggio:
        y, x = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        b = np.where(np.hypot(x - centro[0], y - centro[1]) <= raggio, b, -np.inf)
    yp, xp = np.unravel_index(int(np.argmax(b)), b.shape)
    w = max(3, int(round(1.5 * sigma)))
    base = b if sigma > 2.5 else np.nan_to_num(a)          # stella satura: baricentro sull'immagine levigata
    sub = base[max(yp - w, 0):yp + w + 1, max(xp - w, 0):xp + w + 1]
    sub = np.clip(sub - (np.median(sub) if sigma > 2.5 else 0), 0, None)
    if sub.sum() <= 0:
        return float(xp), float(yp)
    yy, xx = np.mgrid[max(yp - w, 0):max(yp - w, 0) + sub.shape[0], max(xp - w, 0):max(xp - w, 0) + sub.shape[1]]
    return float((xx * sub).sum() / sub.sum()), float((yy * sub).sum() / sub.sum())


def sigma_psf(a, stelle, max_n=60):
    """Sigma (pixel) tipico delle stelle, dai momenti del secondo ordine."""
    if len(stelle) < 3:
        return None
    sel = stelle[len(stelle) // 10: len(stelle) // 10 + max_n]      # non le più brillanti (sature)
    vals = []
    for x, y, _ in sel:
        xi, yi = int(round(x)), int(round(y))
        sub = a[yi - 6:yi + 7, xi - 6:xi + 7]
        if sub.shape != (13, 13) or not np.isfinite(sub).all():
            continue
        bordo = np.concatenate([sub[0], sub[-1], sub[:, 0], sub[:, -1]])
        s = np.clip(sub - np.median(bordo), 0, None)
        s[s < 0.1 * s.max()] = 0
        if s.sum() <= 0:
            continue
        yy, xx = np.mgrid[-6:7, -6:7]
        mx, my = (xx * s).sum() / s.sum(), (yy * s).sum() / s.sum()
        v = (((xx - mx) ** 2 + (yy - my) ** 2) * s).sum() / s.sum() / 2
        if 0.1 < v < 25:
            vals.append(math.sqrt(v))
    return float(np.median(vals)) if len(vals) >= 3 else None


def uguaglia_istogramma(src, rif, maschera):
    """Trasforma i valori di src perché abbiano la stessa distribuzione di rif nella
    maschera (corregge anche la risposta non lineare delle lastre fotografiche)."""
    m = maschera & np.isfinite(src) & np.isfinite(rif)
    if m.sum() < 200:
        return src
    q = np.linspace(0.5, 99.95, 500)
    qs = np.maximum.accumulate(np.percentile(src[m], q))
    qr = np.maximum.accumulate(np.percentile(rif[m], q))
    qs = qs + np.arange(len(qs)) * 1e-9 * (abs(qs[-1]) + 1)       # strettamente crescente
    out = np.interp(src, qs, qr)
    out[~np.isfinite(src)] = np.nan
    return out.astype(DTYPE)


# =============================================================================
# EPOCHE: ARCHIVI E FILE LOCALI
# =============================================================================
def nuova_epoca(**k):
    e = dict(id="", fonte="", etichetta="", strumento="", banda="", anno=None, data="", origine="archivio",
             file="", usa=True, nota="", anno_approssimato=False, scarica={})
    e.update(k)
    return e


SURVEY_STSCI_RISERVA = {"poss2ukstu_red": ["poss2ukstu_red", "phase2_gsc2"], "poss1_red": ["poss1_red", "phase1_gsc1"]}


def data_lastra_stsci(ra, dec, survey, ferma=None):
    """Data della lastra DSS (STScI): (anno, testo, id lastra). Prova più riquadri e,
    per la DSS2, anche il nome «phase2_gsc2»; se fallisce dice che cosa ha risposto."""
    ultimo = ""
    for v in SURVEY_STSCI_RISERVA.get(survey, [survey]):
        for lato in ("2", "5"):
            q = {"v": v, "r": f"{ra:.5f}", "d": f"{dec:.5f}", "e": "J2000", "h": lato, "w": lato,
                 "f": "fits", "c": "none", "fov": "NONE", "v3": ""}
            b = scarica(URL_DSS_STSCI + "?" + urllib.parse.urlencode(q), TIMEOUT_DOMANDA, ferma=ferma)
            if not e_fits_bytes(b):
                testo = re.sub(r"<[^>]+>", " ", b[:3000].decode("latin-1", "replace"))
                ultimo = f"{v}, {lato}′: " + " ".join(testo.split())[:160]
                continue
            h = intestazione_grezza(b)
            a = anno_da_intestazione(h)
            return a, str(h.get("DATE-OBS", "")), str(h.get("PLATEID", h.get("PLATE", "")))
    raise ValueError("risposta dello STScI non in formato FITS (" + ultimo + ")")


URL_DSS_ESO = "https://archive.eso.org/dss/dss/image"
SURVEY_ESO = {"poss1_red": "DSS1", "poss2ukstu_red": "DSS2-red"}


def data_lastra_eso(ra, dec, survey, ferma=None):
    """Riserva: data della lastra DSS dal server DSS dell'ESO."""
    q = {"ra": f"{ra:.5f}", "dec": f"{dec:.5f}", "equinox": "J2000", "name": "", "x": "2", "y": "2",
         "Sky-Survey": SURVEY_ESO.get(survey, "DSS2-red"), "mime-type": "download-fits", "statsmode": "WEBFORM"}
    b = scarica(URL_DSS_ESO + "?" + urllib.parse.urlencode(q), TIMEOUT_DOMANDA, ferma=ferma)
    if not e_fits_bytes(b):
        testo = re.sub(r"<[^>]+>", " ", b[:2000].decode("latin-1", "replace"))
        raise ValueError("risposta dell'ESO non in formato FITS (" + " ".join(testo.split())[:120] + ")")
    h = intestazione_grezza(b)
    return anno_da_intestazione(h), str(h.get("DATE-OBS", "")), str(h.get("PLATEID", h.get("PLATE", "")))


def nomi_ps1(ra, dec, filtri="r", ferma=None):
    t = scarica(URL_PS1_NOMI + "?" + urllib.parse.urlencode({"ra": ra, "dec": dec, "filters": filtri}),
                TIMEOUT_DOMANDA, ferma=ferma).decode("utf-8", "replace")
    righe = [r.split() for r in t.strip().splitlines()]
    if len(righe) < 2:
        raise ValueError("nessuna immagine Pan-STARRS in questa zona (sotto −30° non c'è)")
    testa = righe[0]
    out = {}
    for r in righe[1:]:
        if len(r) >= len(testa):
            d = dict(zip(testa, r))
            out[d.get("filter")] = d
    return out


FORMATI_HEASARC = ["votable", "", "csv", "votable/td"]     # il 10/11 HEASARC rifiutava «csv»; "" = senza formato
_formato_heasarc = [None]


def interroga_heasarc(query, ferma=None):
    """ADQL al TAP di HEASARC: prova più formati (ricorda quello che funziona)."""
    ultimo = None
    ok = _formato_heasarc[0]
    prove = ([ok] if ok is not None else []) + [f for f in FORMATI_HEASARC if f != ok]
    for fmt in prove:
        par = {"REQUEST": "doQuery", "LANG": "ADQL", "QUERY": query, "MAXREC": "5000"}
        if fmt:
            par.update(FORMAT=fmt, RESPONSEFORMAT=fmt)
        try:
            b = scarica(URL_HEASARC_TAP + "?" + urllib.parse.urlencode(par), 90, ferma=ferma)
            testa = b[:3000].lstrip()
            if b"<VOTABLE" in testa or testa.startswith(b"<?xml"):
                righe = _leggi_votable(b)
            elif testa.startswith(b"<"):
                raise ValueError("risposta di HEASARC non valida (HTML)")
            else:
                import csv
                testo = b.decode("utf-8", "replace")
                if "unsupported" in testo[:300].lower() or "error" in testo[:120].lower():
                    raise ValueError(testo[:200])
                r = csv.reader(io.StringIO(testo))
                campi = [c.strip().lower() for c in next(r, [])]
                righe = [dict(zip(campi, [v.strip() for v in x])) for x in r if x]
        except Fermato:
            raise
        except (ValueError, urllib.error.HTTPError) as e:
            ultimo = e
            if "column" in str(e).lower() or "colonna" in str(e).lower():
                raise                                  # errore della domanda, non del formato
            continue
        _formato_heasarc[0] = fmt
        return righe
    raise ultimo or ValueError("HEASARC non risponde")


def _leggi_votable(b):
    import xml.etree.ElementTree as ET
    campi, righe, binaria = [], [], False
    for _, el in ET.iterparse(io.BytesIO(b), events=("end",)):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "FIELD":
            campi.append((el.get("name") or "").lower())
        elif tag == "TR":
            righe.append(dict(zip(campi, [(td.text or "").strip() for td in el])))
            el.clear()
        elif tag in ("BINARY", "BINARY2"):
            binaria = True
        elif tag == "INFO" and el.get("value", "").upper() == "ERROR":
            raise ValueError("errore di HEASARC: " + (el.text or "")[:200])
    if binaria and not righe:
        from astropy.io.votable import parse_single_table
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t = parse_single_table(io.BytesIO(b)).to_table()
        for r in t:
            d = {}
            for c in t.colnames:
                v = r[c]
                if hasattr(v, "mask") and v.mask:
                    v = ""
                elif isinstance(v, bytes):
                    v = v.decode("utf-8", "replace")
                d[c.lower()] = str(v).strip()
            righe.append(d)
    return righe


def _campo(r, *nomi):
    for n in nomi:
        if r.get(n) not in (None, ""):
            return str(r[n]).strip()
    return ""


def osservazioni_chandra(ogg, ferma=None, log=None, statistiche=None):
    """Osservazioni Chandra ACIS senza reticolo, pubbliche, entro 3′ dall'oggetto.
    'statistiche' (dict) riceve righe grezze e motivi di scarto, per la diagnostica."""
    dove = f"CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ogg['ra']:.5f}, {ogg['dec']:.5f}, 0.05)) = 1"
    righe = interroga_heasarc("SELECT * FROM chanmaster WHERE " + dove, ferma)
    st = statistiche if statistiche is not None else {}
    st.update(righe=len(righe), formato=_formato_heasarc[0], colonne=list(righe[0].keys()) if righe else [],
              esempi=righe[:2], scarti={})

    def scarta(motivo):
        st["scarti"][motivo] = st["scarti"].get(motivo, 0) + 1
    oss = []
    for r in righe:
        det = _campo(r, "detector", "instrument", "instrume").upper()
        gr = _campo(r, "grating").upper() or "NONE"
        stato = _campo(r, "status").lower() or "archived"
        if "ACIS" not in det:
            scarta(f"non ACIS ({det or 'vuoto'})")
            continue
        if gr not in ("NONE", "NULL", "N/A", "NO"):
            scarta(f"reticolo {gr}")
            continue
        if stato in ("scheduled", "unobserved", "canceled", "cancelled", "untriggered", "observed"):
            scarta(f"stato {stato}")
            continue
        try:
            obsid = int(float(_campo(r, "obsid", "obs_id", "datalinkid")))   # HEASARC 10/11: solo «datalinkid»
        except ValueError:
            scarta("obsid illeggibile")
            continue
        t = _campo(r, "time", "start_date", "start_time", "obs_date")
        anno = None
        try:
            v = float(t)
            anno = anno_da_mjd(v) if 40000 < v < 80000 else None
        except ValueError:
            anno = leggi_data_testo(t)
        if anno is None:
            scarta(f"data illeggibile ({t[:20]})")
            continue
        try:
            esp = float(_campo(r, "exposure", "exposure_time") or 0)
        except ValueError:
            esp = 0.0
        oss.append(dict(obsid=obsid, anno=anno, esposizione=esp, rivelatore=det, nome=_campo(r, "name")))
    if log and st["scarti"]:
        log("   Chandra: scartate " + ", ".join(f"{n} {m}" for m, n in st["scarti"].items()))
    return oss


URL_MAST = "https://mast.stsci.edu/api/v0/invoke"
URL_MAST_FILE = "https://mast.stsci.edu/api/v0.1/Download/file?uri="


def mast(servizio, parametri, ferma=None, pagine=2000):
    """Richiesta all'API di MAST (POST, JSON); aspetta se la risposta è «EXECUTING»."""
    req = {"service": servizio, "params": parametri, "format": "json", "pagesize": pagine, "page": 1,
           "removenullcolumns": True}
    dati = urllib.parse.urlencode({"request": json.dumps(req)}).encode()
    for _ in range(12):
        b = scarica(URL_MAST, 120, ferma=ferma, dati=dati)
        r = json.loads(b.decode("utf-8", "replace"))
        if r.get("status") in ("COMPLETE", None) and "data" in r:
            return r["data"]
        if r.get("status") == "ERROR":
            raise ValueError("MAST: " + str(r.get("msg", ""))[:200])
        time.sleep(5)
    raise TimeoutError("MAST non ha finito la ricerca in un minuto")


def osservazioni_hubble(ogg, ferma=None, log=None, statistiche=None):
    """Immagini Hubble (CAOM) attorno all'oggetto, nei filtri scelti, con un prodotto combinato."""
    righe = mast("Mast.Caom.Cone", {"ra": ogg["ra"], "dec": ogg["dec"], "radius": 0.004}, ferma)
    st = statistiche if statistiche is not None else {}
    st.update(righe=len(righe), colonne=list(righe[0].keys()) if righe else [], esempi=righe[:2], scarti={})

    def scarta(m):
        st["scarti"][m] = st["scarti"].get(m, 0) + 1
    filtri = [f.upper() for f in ogg.get("filtri_hubble", [])]
    oss = []
    for r in righe:
        if str(r.get("obs_collection", "")).upper() != "HST":
            scarta("non HST")
            continue
        if str(r.get("dataproduct_type", "")).lower() != "image":
            scarta("non immagine")
            continue
        strum = str(r.get("instrument_name", "")).upper()
        if "STIS" in strum or "NICMOS" in strum or "FOC" in strum or "FGS" in strum or "COS" in strum:
            scarta(f"strumento {strum.split('/')[0]}")
            continue
        f = re.sub(r"[^A-Z0-9;]", "", str(r.get("filters", "")).upper())
        f = next((x for x in f.split(";") if x.startswith("F") and x != "CLEAR"), f)
        if f not in filtri:
            scarta(f"filtro {f or '?'}")
            continue
        try:
            anno = anno_da_mjd(float(r.get("t_min")))
            esp = float(r.get("t_exptime") or 0)
        except (TypeError, ValueError):
            scarta("data illeggibile")
            continue
        if esp <= 0.05:
            scarta("esposizione nulla")
            continue
        try:
            rilascio = float(r.get("t_obs_release") or 0)
        except (TypeError, ValueError):
            rilascio = 0
        oggi_mjd = (datetime.now(timezone.utc) - MJD_0).total_seconds() / 86400
        if rilascio > oggi_mjd:
            scarta("ancora riservata")
            continue
        oss.append(dict(obsid=str(r.get("obsid")), obs_id=str(r.get("obs_id", "")), anno=anno, esposizione=esp,
                        strumento=strum, filtro=f, livello=int(float(r.get("calib_level") or 0))))
    if log and st["scarti"]:
        log("   Hubble: scartate " + ", ".join(f"{n} {m}" for m, n in sorted(st["scarti"].items(), key=lambda x: -x[1])[:8]))
    return oss


def scegli_hubble(oss, filtri, n_max):
    """Un solo tipo di filtro (quello con più anni diversi, a parità quello prima nella lista),
    poi un'osservazione per anno (la più lunga), distribuite nel tempo."""
    if not oss:
        return []
    anni = {}
    for o in oss:
        anni.setdefault(o["filtro"], set()).add(int(o["anno"]))
    migliore = max(anni, key=lambda f: (len(anni[f]), -filtri.index(f) if f in filtri else -99))
    return scegli_distribuite([o for o in oss if o["filtro"] == migliore], n_max)


def scegli_distribuite(oss, n_max):
    """Al massimo n_max osservazioni, una per anno (la più lunga), distribuite nel tempo."""
    per_anno = {}
    for o in oss:
        k = int(o["anno"])
        if k not in per_anno or o["esposizione"] > per_anno[k]["esposizione"]:
            per_anno[k] = o
    scelte = sorted(per_anno.values(), key=lambda o: o["anno"])
    if len(scelte) <= n_max:
        return scelte
    idx = np.unique(np.round(np.linspace(0, len(scelte) - 1, n_max)).astype(int))
    return [scelte[i] for i in idx]


def epoche_archivio(ogg, log=print, ferma=None):
    """Epoche disponibili negli archivi per l'oggetto (senza scaricare le immagini)."""
    out = []
    ra, dec = centro_campo(ogg)
    for f in ogg.get("fonti", []):
        if ferma is not None and ferma.is_set():
            raise Fermato()
        info = FONTI[f]
        if f.startswith("dss"):
            anno, testo, lastra, nota, appross = None, "", "", "", False
            try:
                anno, testo, lastra = data_lastra_stsci(ra, dec, info["stsci"], ferma)
                nota = f"lastra {lastra}" if lastra else ""
                log(f"   {info['etichetta']}: lastra {lastra or '?'} del {testo or '?'} (STScI)")
            except Fermato:
                raise
            except Exception as e:
                log(f"   {info['etichetta']}: STScI senza data ({type(e).__name__}: {str(e)[:70]}); provo l'ESO")
                try:
                    anno, testo, lastra = data_lastra_eso(ra, dec, info["stsci"], ferma)
                    if anno is not None:
                        nota = f"lastra {lastra} (data dall'ESO)" if lastra else "data dall'ESO"
                        log(f"   {info['etichetta']}: lastra {lastra or '?'} del {testo or '?'} (ESO)")
                except Fermato:
                    raise
                except Exception as e2:
                    log(f"   {info['etichetta']}: data della lastra non trovata neanche all'ESO "
                        f"({type(e2).__name__}: {str(e2)[:80]})")
            if anno is None:
                anno, appross = info["anno_ripiego"], True
                nota = f"data approssimata ({info['nota_ripiego']}): correggila se la conosci"
            out.append(nuova_epoca(id=f, fonte=f, etichetta=info["etichetta"], strumento=info["strumento"],
                                   banda=info["banda"], anno=anno, data=testo, nota=nota, anno_approssimato=appross,
                                   scarica={"tipo": "skyview", "survey": info["survey_skyview"]}))
        elif f == "ps1_r":
            try:
                nomi = nomi_ps1(ra, dec, "r", ferma)
                d = nomi.get("r", {})
                mjd = float(d.get("mjd", 0) or 0)
                anno = anno_da_mjd(mjd) if mjd > 50000 else None
                appross = anno is None
                if appross:
                    anno = info["anno_ripiego"]
                log(f"   Pan-STARRS r: {d.get('shortname', d.get('filename', '?'))}")
                out.append(nuova_epoca(id=f, fonte=f, etichetta=info["etichetta"], strumento=info["strumento"],
                                       banda=info["banda"], anno=anno, anno_approssimato=appross,
                                       nota=("anno medio della survey (2010-2014)" if appross else "data media della somma"),
                                       scarica={"tipo": "ps1", "filename": d.get("filename", "")}))
            except Fermato:
                raise
            except Exception as e:
                log(f"   Pan-STARRS: non disponibile ({type(e).__name__}: {str(e)[:100]})")
        elif f == "hubble":
            try:
                oss = osservazioni_hubble(ogg, ferma, log)
                scelte = scegli_hubble(oss, [x.upper() for x in ogg.get("filtri_hubble", [])],
                                       ogg.get("max_epoche_archivio", 6))
                log(f"   Hubble (MAST): {len(oss)} immagini nei filtri scelti; filtro "
                    f"{scelte[0]['filtro'] if scelte else '–'}, ne uso {len(scelte)}")
                for o in scelte:
                    out.append(nuova_epoca(id=f"hst_{re.sub(r'[^A-Za-z0-9]+', '_', o['obs_id'] or o['obsid'])}",
                                           fonte="hubble", etichetta=f"Hubble {o['strumento'].split('/')[0]} {o['filtro']}",
                                           strumento=f"Hubble {o['strumento']}", banda=o["filtro"], anno=o["anno"],
                                           data=data_da_anno(o["anno"]).strftime("%Y-%m-%d"),
                                           nota=f"{o['obs_id']}, esposizione {o['esposizione']:.0f} s",
                                           scarica={"tipo": "hubble", "obsid": o["obsid"]}))
            except Fermato:
                raise
            except Exception as e:
                log(f"   Hubble (MAST): non disponibile ({type(e).__name__}: {str(e)[:120]})")
        elif f == "chandra":
            try:
                oss = osservazioni_chandra(ogg, ferma, log)
                scelte = scegli_distribuite(oss, ogg.get("max_epoche_archivio", 8))
                log(f"   Chandra (HEASARC): {len(oss)} osservazioni ACIS senza reticolo, ne uso {len(scelte)}")
                for o in scelte:
                    out.append(nuova_epoca(id=f"chandra_{o['obsid']}", fonte="chandra", etichetta=f"Chandra {o['obsid']}",
                                           strumento=f"Chandra {o['rivelatore']}", banda=info["banda"], anno=o["anno"],
                                           data=data_da_anno(o["anno"]).strftime("%Y-%m-%d"),
                                           nota=f"esposizione {o['esposizione'] / 1000:.1f} ks",
                                           scarica={"tipo": "chandra", "obsid": o["obsid"]}))
            except Fermato:
                raise
            except Exception as e:
                log(f"   Chandra (HEASARC): non disponibile ({type(e).__name__}: {str(e)[:100]})")
    return out


def centro_campo(ogg):
    """Centro della griglia: per la stella di Barnard la posizione a metà delle epoche."""
    if ogg.get("pm_mas") and ogg.get("epoca_centro"):
        return posizione_al_tempo(ogg, ogg["epoca_centro"])
    return ogg["ra"], ogg["dec"]


def posizione_al_tempo(ogg, anno):
    pmra, pmdec = ogg["pm_mas"]
    ra0, dec0, ep0 = ogg["pos_catalogo"]
    dt = anno - ep0
    dec = dec0 + pmdec * dt / 3.6e6
    ra = ra0 + pmra * dt / 3.6e6 / math.cos(math.radians(dec))
    return ra, dec


URL_GAIA_ESA = "https://gea.esac.esa.int/tap-server/tap/sync"
URL_GAIA_IRSA = "https://irsa.ipac.caltech.edu/TAP/sync"


def aggiorna_da_gaia(ogg, base=None, log=print, ferma=None):
    """Moto proprio, parallasse e posizione (epoca 2016) da Gaia DR3: la stella con il moto
    proprio più grande entro 1′ dalla posizione prevista. Risultato salvato in gaia.json."""
    if not ogg.get("cerca_gaia"):
        return ogg
    c = cartella_oggetto(ogg, base)
    p = c / "gaia.json"
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        g = None
    if g is None:
        ra, dec = posizione_al_tempo(ogg, 2016.0)
        dove = f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, 0.0167))"
        for url, tab in ((URL_GAIA_ESA, "gaiadr3.gaia_source"), (URL_GAIA_IRSA, "gaia_dr3_source")):
            q = (f"SELECT TOP 3 source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM {tab} "
                 f"WHERE {dove} AND pmra IS NOT NULL ORDER BY (pmra*pmra + pmdec*pmdec) DESC")
            par = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}
            try:
                import csv
                t = scarica(url + "?" + urllib.parse.urlencode(par), 90, ferma=ferma).decode("utf-8", "replace")
                righe = list(csv.DictReader(io.StringIO(t)))
                r = righe[0]
                g = dict(source_id=r["source_id"], ra=float(r["ra"]), dec=float(r["dec"]), pmra=float(r["pmra"]),
                         pmdec=float(r["pmdec"]), parallax=float(r["parallax"]), g=float(r["phot_g_mean_mag"] or 0),
                         fonte=url.split("/")[2])
                break
            except Fermato:
                raise
            except Exception as e:
                log(f"   Gaia ({url.split('/')[2]}): non disponibile ({type(e).__name__} {str(e)[:80]})")
        if g is not None:
            c.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(g, indent=1), encoding="utf-8")
    atteso = np.array(ogg["pm_mas"], float)
    if g is not None and np.hypot(*(np.array([g["pmra"], g["pmdec"]]) - atteso)) > 0.15 * np.hypot(*atteso):
        log(f"   Gaia: la stella trovata ({g['source_id']}) non ha il moto proprio atteso: uso i valori del programma")
        g = None
        p.unlink(missing_ok=True)
    if g is not None:
        ogg.update(pm_mas=(g["pmra"], g["pmdec"]), plx_mas=g["parallax"], pos_catalogo=(g["ra"], g["dec"], 2016.0),
                   fonte_pm=f"Gaia DR3 {g['source_id']}")
        log(f"   Gaia DR3 {g['source_id']}: moto proprio {math.hypot(g['pmra'], g['pmdec']) / 1000:.3f}″/anno, "
            f"parallasse {g['parallax']:.2f} mas")
    else:
        ogg["fonte_pm"] = "valori di catalogo del programma (Gaia non raggiunto)"
    return ogg


def info_file(percorso):
    """Informazioni veloci su un FITS (solo intestazione): per scegliere i file tuoi."""
    from astropy.io import fits
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(percorso, memmap=True, lazy_load_hdus=True) as hdul:
            hh = [hdul[0].header]
            for hdu in list(hdul)[1:4]:
                hh.append(hdu.header)
            h = _intestazione_dict(*hh)
    ra = dec = None
    for kr, kd in (("RA_TARG", "DEC_TARG"), ("RA_NOM", "DEC_NOM"), ("CRVAL1", "CRVAL2"), ("RA", "DEC"), ("OBJCTRA", "OBJCTDEC")):
        try:
            ra, dec = float(h[kr]), float(h[kd])
            if str(h.get("CTYPE1", "RA")).upper().startswith("RA") or kr != "CRVAL1":
                break
        except (KeyError, TypeError, ValueError):
            ra = dec = None
    tel = str(h.get("TELESCOP", "")).strip()
    strum = str(h.get("INSTRUME", "")).strip()
    filtro = str(h.get("FILTER", h.get("FILTER1", h.get("FILTNAM1", ""))) or "").strip()
    return dict(anno=anno_da_intestazione(h), ra=ra, dec=dec, telescopio=tel, strumento=strum, filtro=filtro,
                raggi_x=e_raggi_x(h), oggetto=str(h.get("OBJECT", "")).strip(),
                obs_id=str(h.get("OBS_ID", h.get("OBSID", h.get("ROOTNAME", "")))).strip(),
                contenuto=str(h.get("CONTENT", "")).upper())


def e_infrarosso(i):
    t = f"{i.get('telescopio', '')} {i.get('strumento', '')}".upper()
    f = str(i.get("filtro", "")).upper()
    if any(x in t for x in ("JWST", "SPITZER", "WISE", "HERSCHEL", "2MASS", "AKARI", "NIRCAM", "MIRI", "NIRISS",
                            "IRAC", "MIPS", "NICMOS", "NEOWISE")):
        return True
    m = re.match(r"^F(\d{3,4})", f)
    return bool(m and "WFC3" in t and int(m.group(1)) >= 1000)


def epoca_da_file(percorso):
    i = info_file(percorso)
    p = Path(percorso)
    banda = "raggi X" if i["raggi_x"] else (i["filtro"] or "")
    nome = " ".join(x for x in (i["telescopio"], i["strumento"]) if x) or p.name
    return nuova_epoca(id="file_" + re.sub(r"[^A-Za-z0-9]+", "_", p.name)[:60], fonte="file", etichetta=nome,
                       strumento=nome, banda=banda, anno=i["anno"], origine="file tuo", file=str(p),
                       data=data_da_anno(i["anno"]).strftime("%Y-%m-%d") if i["anno"] else "",
                       nota=("data non trovata nel file: scrivila tu" if i["anno"] is None else p.name),
                       usa=i["anno"] is not None, _info=i)


def cerca_file_locali(ogg, base=None, log=print, profondita=3, max_file=400):
    """FITS già scaricati (cartella Astronomia) dell'oggetto: cartelle con il nome
    dell'oggetto, coordinate dentro il campo, banda giusta (ottico / raggi X)."""
    if not ogg.get("alias"):
        return []
    base = Path(base) if base else cartella_astronomia()
    if not base.is_dir():
        return []
    rx = re.compile(ogg["alias"], re.I)
    candidati = []
    for radice, cartelle, files in os.walk(base):
        rel = Path(radice).relative_to(base)
        if len(rel.parts) >= profondita:
            cartelle[:] = []
        cartelle[:] = [c for c in cartelle if not c.startswith(("_", ".")) and c != "Prima_e_dopo"]
        if not any(rx.search(p.lower()) for p in rel.parts):
            continue
        for f in files:
            if e_file_fits(f) and not f.lower().startswith(("stack_", "analisi_", "allineata_")):
                candidati.append(Path(radice) / f)
        if len(candidati) > max_file:
            break
    ra0, dec0 = centro_campo(ogg)
    raggio = ogg["campo_arcmin"] * 60 * 0.75 + 300
    trovati = {}
    for p in candidati:
        try:
            i = info_file(p)
        except Exception:
            continue
        if i["ra"] is None or separazione_arcsec(i["ra"], i["dec"], ra0, dec0) > raggio:
            continue
        if ogg.get("banda_locale") == "raggi_x" and not i["raggi_x"]:
            continue
        if ogg.get("banda_locale") == "ottico" and i["raggi_x"]:
            continue
        if "LORES" in i["contenuto"]:          # Chandra «full_img»: doppione a bassa risoluzione
            continue
        chiave = (i["telescopio"], i["obs_id"] or p.name, round(i["anno"] or 0, 3))
        if chiave not in trovati or p.stat().st_size > Path(trovati[chiave]).stat().st_size:
            trovati[chiave] = str(p)
    out = []
    for p in sorted(trovati.values()):
        try:
            e = epoca_da_file(p)
        except Exception as ex:
            log(f"   {Path(p).name}: non letto ({ex})")
            continue
        if ogg.get("banda_locale") == "ottico":
            i = e.get("_info", {})
            ir = e_infrarosso(i)
            e["usa"] = False                       # per la misura servono epoche nella stessa banda
            e["nota"] = ("INFRAROSSO: non adatto al confronto con le lastre rosse" if ir else
                         "file tuo: spunta «Usa» solo se è nel rosso/visibile e copre tutta la nebulosa")
            if ir:
                e["banda"] = (e.get("banda") + " · infrarosso").strip(" ·")
        out.append(e)
    if out:
        log(f"   file tuoi trovati in {base}: {len(out)}")
    return out


def leggi_epoche(ogg, base=None):
    p = cartella_oggetto(ogg, base) / FILE_EPOCHE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def salva_epoche(ogg, epoche, base=None):
    c = cartella_oggetto(ogg, base)
    c.mkdir(parents=True, exist_ok=True)
    pulite = [{k: v for k, v in e.items() if not k.startswith("_")} for e in epoche]
    tmp = c / (FILE_EPOCHE + ".tmp")
    tmp.write_text(json.dumps(pulite, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, c / FILE_EPOCHE)


def unisci_epoche(vecchie, nuove):
    """Le nuove sostituiscono le vecchie con lo stesso id, ma restano le scelte
    dell'utente (usa, anno corretto a mano) e i file già scaricati."""
    per_id = {e["id"]: e for e in vecchie}
    out = []
    for e in nuove:
        v = per_id.pop(e["id"], None)
        if v:
            if v.get("usa_manuale"):
                e["usa"], e["usa_manuale"] = v.get("usa", e["usa"]), True
            if v.get("anno_manuale"):
                e["anno"], e["anno_manuale"], e["anno_approssimato"] = v["anno"], True, False
            if v.get("file") and Path(v["file"]).exists() and not e.get("file"):
                e["file"] = v["file"]
        out.append(e)
    out += [v for v in per_id.values() if v.get("origine") == "file tuo"]
    return ordina_epoche(out)


def ordina_epoche(ep):
    return sorted(ep, key=lambda e: (e["anno"] is None, e["anno"] or 0))


def cerca_epoche(ogg, base=None, log=print, ferma=None, cartella_dati=None):
    log(f"Cerco le epoche di {ogg['nome']}…")
    aggiorna_da_gaia(ogg, base, log, ferma)
    nuove = []
    if ogg.get("fonti"):
        nuove += epoche_archivio(ogg, log, ferma)
    if ogg.get("alias"):
        nuove += cerca_file_locali(ogg, cartella_dati, log)
    ep = unisci_epoche(leggi_epoche(ogg, base), nuove)
    salva_epoche(ogg, ep, base)
    log(f"Epoche trovate: {len(ep)}")
    return ep


# ----------------------------------------------------------------- scaricamento
def ritaglio_ps1(filename, ra, dec, lato, scala, progresso=None, ferma=None):
    size = int(round(lato / 0.25))
    q = {"red": filename, "ra": f"{ra:.6f}", "dec": f"{dec:.6f}", "size": size, "format": "fits",
         "output_size": int(round(lato / scala))}
    b = scarica(URL_PS1_TAGLIO + "?" + urllib.parse.urlencode(q), TIMEOUT_FILE, progresso, ferma,
                max_byte=400 * 1024 ** 2)
    if not e_fits_bytes(b):
        raise ValueError("Pan-STARRS non ha restituito un FITS")
    return sistema_ps1(b, size)


def scarica_celle_vicine_ps1(ep, ogg, cartella, log=print, ferma=None):
    """Se il campo esce dalla cella Pan-STARRS, scarica lo stesso ritaglio dalle celle vicine
    (stesso centro): nella riproiezione riempiono la parte che manca."""
    if "file_extra" in ep and all(Path(f).exists() for f in ep["file_extra"]):
        return
    ra, dec = centro_campo(ogg)
    lato = ogg["campo_arcmin"] * 60
    principale = (ep.get("scarica") or {}).get("filename", "")
    nomi = []
    for dx in (-0.45, 0.0, 0.45):
        for dy in (-0.45, 0.0, 0.45):
            if dx == 0 and dy == 0:
                continue
            r2 = ra + dx * lato / 3600 / math.cos(math.radians(dec))
            d2 = dec + dy * lato / 3600
            try:
                f = nomi_ps1(r2, d2, "r", ferma).get("r", {}).get("filename", "")
            except Fermato:
                raise
            except Exception:
                continue
            if f and f != principale and f not in nomi:
                nomi.append(f)
    extra = []
    for k, f in enumerate(nomi, 2):
        dest = Path(cartella) / f"{ep['id']}_{k}.fits"
        if not (dest.exists() and dest.stat().st_size > 2880):
            try:
                b = ritaglio_ps1(f, ra, dec, lato, ogg["scala_arcsec"], ferma=ferma)
            except Fermato:
                raise
            except Exception as e:
                log(f"   Pan-STARRS, cella vicina {f.split('/')[-1]}: non scaricata ({e})")
                continue
            dest.write_bytes(b)
        extra.append(str(dest))
    ep["file_extra"] = extra
    if extra:
        log(f"   Pan-STARRS: {len(extra)} celle vicine per coprire tutto il campo")


def scarica_epoca(ep, ogg, base=None, log=print, ferma=None, progresso=None):
    """Scarica il FITS di un'epoca d'archivio (se non c'è già). Restituisce il percorso."""
    c = cartella_oggetto(ogg, base) / CARTELLA_EPOCHE
    if (ep.get("scarica") or {}).get("tipo") == "ps1" and ogg.get("campo_arcmin"):
        c.mkdir(parents=True, exist_ok=True)
        scarica_celle_vicine_ps1(ep, ogg, c, log, ferma)
    if ep.get("file") and Path(ep["file"]).exists():
        return Path(ep["file"])
    c.mkdir(parents=True, exist_ok=True)
    dest = c / f"{ep['id']}.fits"
    if dest.exists() and dest.stat().st_size > 2880:
        ep["file"] = str(dest)
        return dest
    s = ep.get("scarica") or {}
    ra, dec = centro_campo(ogg)
    lato = ogg["campo_arcmin"] * 60
    if s.get("tipo") == "skyview":
        n = int(round(lato / ogg["scala_arcsec"]))
        base_q = {"Position": f"{ra:.6f},{dec:.6f}", "Survey": s["survey"], "Pixels": str(n),
                  "Size": f"{lato / 3600:.5f}", "Projection": "Tan", "Coordinates": "J2000"}
        b = scarica(URL_SKYVIEW + "?" + urllib.parse.urlencode(dict(base_q, Return="FITS")), TIMEOUT_FILE,
                    progresso, ferma)
        if not e_fits_bytes(b):
            stem = scarica(URL_SKYVIEW + "?" + urllib.parse.urlencode(dict(base_q, Return="filename")),
                           TIMEOUT_DOMANDA, ferma=ferma).decode("utf-8", "replace").strip()
            if re.fullmatch(r"[\w\-]+", stem or ""):
                b = scarica(URL_SKYVIEW_TEMP + stem + ".fits", TIMEOUT_FILE, progresso, ferma)
        if not e_fits_bytes(b):
            raise ValueError("SkyView non ha restituito un FITS")
    elif s.get("tipo") == "ps1":
        if not s.get("filename"):
            raise ValueError("nome dell'immagine Pan-STARRS mancante: rifai «Cerca le epoche»")
        b = ritaglio_ps1(s["filename"], ra, dec, lato, ogg["scala_arcsec"], progresso, ferma)
    elif s.get("tipo") == "hubble":
        prodotti = mast("Mast.Caom.Products", {"obsid": s["obsid"]}, ferma)
        uri = scegli_prodotto_hubble(prodotti)
        if not uri:
            raise ValueError("nessun prodotto combinato (_drz/_drc) per questa osservazione Hubble")
        b = scarica(URL_MAST_FILE + urllib.parse.quote(uri, safe=":/"), TIMEOUT_FILE, progresso, ferma,
                    max_byte=800 * 1024 ** 2)
        if b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
        if not e_fits_bytes(b):
            raise ValueError("MAST non ha restituito un FITS")
    elif s.get("tipo") == "chandra":
        obsid = int(s["obsid"])
        url = URL_CHANDRA_FTP.format(d=obsid % 10, obsid=obsid)
        indice = scarica(url, TIMEOUT_DOMANDA, ferma=ferma).decode("utf-8", "replace")
        nomi = re.findall(r'href="([^"?/]*cntr_img2\.fits(?:\.gz)?)"', indice)
        if not nomi:
            raise ValueError(f"nessuna immagine «cntr_img2» per ObsID {obsid}")
        b = scarica(url + nomi[0], TIMEOUT_FILE, progresso, ferma)
        if b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    else:
        raise ValueError("epoca senza indicazioni per scaricarla")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(b)
    os.replace(tmp, dest)
    ep["file"] = str(dest)
    log(f"   scaricato {dest.name} ({len(b) / 1024 ** 2:.1f} MB)")
    return dest


def scegli_prodotto_hubble(prodotti):
    """Il prodotto combinato migliore: drc (corretto per l'effetto di carica) poi drz; mai le singole esposizioni."""
    cand = []
    for p in prodotti:
        nome = str(p.get("productFilename", "")).lower()
        uri = p.get("dataURI", "")
        if not uri or not nome.endswith(".fits"):
            continue
        for k, suff in enumerate(("_drc.fits", "_drz.fits", "_c0m.fits")):
            if nome.endswith(suff):
                cand.append((k, 0 if "hst_" not in nome else 1, nome, uri))
    cand.sort()
    return cand[0][3] if cand else None


def sistema_ps1(b, size_richiesto):
    """Pan-STARRS: dati in scala asinh -> lineari; WCS corretto se l'immagine è stata ridotta."""
    from astropy.io import fits
    with fits.open(io.BytesIO(b)) as hdul:
        h = hdul[0].header.copy()
        d = np.asarray(hdul[0].data, dtype=np.float64)
    if "BSOFTEN" in h and "BOFFSET" in h:
        a = 2.5 / math.log(10)
        d = float(h["BOFFSET"]) + float(h["BSOFTEN"]) * 2 * np.sinh(d / a)
        for k in ("BSOFTEN", "BOFFSET"):
            h[k] = (h[k], "gia applicato da Prima e dopo: dati lineari")
    nx = int(h.get("NAXIS1", d.shape[1]))
    f = size_richiesto / nx
    if f > 1.5:
        cd = abs(float(h.get("CDELT1", h.get("CD1_1", 0)) or 0)) * 3600
        if cd and abs(cd - 0.25) < 0.05:                   # WCS ancora dei pixel da 0,25″
            for k in ("CDELT1", "CDELT2", "CD1_1", "CD1_2", "CD2_1", "CD2_2"):
                if k in h:
                    h[k] = float(h[k]) * f
            for k in ("CRPIX1", "CRPIX2"):
                h[k] = (float(h[k]) - 0.5) / f + 0.5
    buf = io.BytesIO()
    fits.PrimaryHDU(d.astype(np.float32), h).writeto(buf)
    return buf.getvalue()


# =============================================================================
# PREPARAZIONE: riproiezione, allineamento, nitidezza e luminosità
# =============================================================================
def griglia_per(ogg, immagini=None):
    if ogg.get("campo_arcmin"):
        ra, dec = centro_campo(ogg)
        return Griglia.per_oggetto(ogg, ra, dec)
    # «File tuoi»: centro e campo dal primo file, scala la più grossolana (max 1500 pixel)
    img = immagini[0]
    ny, nx = img["dati"].shape
    ra, dec = img["wcs"].all_pix2world([(nx - 1) / 2], [(ny - 1) / 2], 0)
    scale = [scala_sorgente_arcsec(i["wcs"], i["dati"].shape) for i in immagini]
    lati = [min(i["dati"].shape) * s for i, s in zip(immagini, scale)]
    lato = min(lati) * 0.9
    scala = max(max(scale), lato / 1500)
    n = int(lato / scala)
    return Griglia(float(ra[0]), float(dec[0]), scala, n + n % 2)


def prepara(ogg, epoche, base=None, log=print, ferma=None, progresso=None, nitidezza_uguale=True):
    """Scarica, riproietta, allinea, uguaglia. Restituisce un dict 'lavoro' con le
    immagini sulla griglia comune (grezze e per la vista) e le informazioni."""
    usate = [e for e in epoche if e.get("usa") and e.get("anno") is not None]
    usate = ordina_epoche(usate)
    if len(usate) < 2:
        raise ValueError("servono almeno due epoche con l'anno (spunta «Usa» e controlla le date)")
    tot = len(usate)
    immagini = []
    for k, e in enumerate(usate):
        if ferma is not None and ferma.is_set():
            raise Fermato()
        if progresso:
            progresso(0.05 + 0.35 * k / tot, f"scarico {e['etichetta']} ({testo_anno(e['anno'])})")
        try:
            p = scarica_epoca(e, ogg, base, log, ferma,
                              (lambda n, t, k=k: progresso(0.05 + 0.35 * (k + (n / t if t else 0.5)) / tot,
                                                           f"scarico {e['etichetta']}: {n / 1024 ** 2:.1f} MB"))
                              if progresso else None)
            img = leggi_immagine(p, *centro_campo(ogg)) if ogg.get("ra") is not None else leggi_immagine(p)
            img["extra"] = []
            for f in e.get("file_extra") or []:
                try:
                    img["extra"].append(leggi_immagine(f))
                except Exception as ex2:
                    log(f"   {Path(f).name}: non letto ({ex2})")
        except Fermato:
            raise
        except Exception as ex:
            log(f"   {e['etichetta']} {testo_anno(e['anno'])}: SALTATA ({type(ex).__name__}: {str(ex)[:150]})")
            e["errore"] = str(ex)[:200]
            continue
        e.pop("errore", None)
        if e.get("anno_approssimato") and not e.get("anno_manuale"):
            a = anno_da_intestazione(img["intestazione"])
            if a is not None and 1940 < a < 2100:
                e.update(anno=a, anno_approssimato=False, nota="data letta dal file scaricato",
                         data=data_da_anno(a).strftime("%Y-%m-%d"))
                log(f"   {e['etichetta']}: data letta dal file, {testo_anno(a, 2)}")
        img["epoca"] = e
        immagini.append(img)
    salva_epoche(ogg, epoche, base)
    if len(immagini) < 2:
        raise ValueError("meno di due epoche leggibili: controlla il registro")
    g = griglia_per(ogg, immagini)
    log(f"Griglia comune: {g.descrizione()}, centro {g.ra0:.5f} {g.dec0:+.5f}")
    grezze, info = [], []
    for k, img in enumerate(immagini):
        if progresso:
            progresso(0.42 + 0.18 * k / len(immagini), f"riproietto {img['epoca']['etichetta']}")
        a, s_src = riproietta(img, g)
        for ex in img.get("extra", []):                 # celle vicine (Pan-STARRS): riempiono i vuoti
            b, _ = riproietta(ex, g)
            a = np.where(np.isfinite(a), a, b)
        valido = float(np.isfinite(a).mean())
        log(f"   {img['epoca']['etichetta']} {testo_anno(img['epoca']['anno'])}: pixel originali {s_src:.2f}″, "
            f"campo coperto {valido * 100:.0f} %")
        soglia = 0.5 if ogg.get("tipo") in ("espansione", "moto_proprio") else 0.2
        if valido < soglia:
            log(f"      copre meno del {soglia * 100:.0f} % del campo: saltata")
            continue
        grezze.append(a)
        info.append(dict(epoca=img["epoca"], raggi_x=img["raggi_x"], esposizione=img["esposizione"],
                         scala_originale=s_src, copertura=valido))
    if len(grezze) < 2:
        raise ValueError("meno di due epoche coprono il campo")
    neb = maschera_ellisse(g, ogg, 1.15)
    # riferimento per l'allineamento: l'epoca che copre più campo (a parità, la più recente)
    rif = max(range(len(grezze)), key=lambda k: (round(info[k]["copertura"], 1), k))
    modo = ogg.get("allinea", "stelle")
    if any(i["raggi_x"] for i in info) and modo == "stelle":
        modo = "picco"
    if modo == "nessuno":
        log("   allineamento: solo le coordinate dei file (Chandra è preciso a circa 0,6″)")
    if progresso:
        progresso(0.62, "allineamento fine")
    stelle = [trova_stelle(a, neb) for a in grezze]
    if modo == "stelle":
        for k in range(len(grezze)):
            if k == rif:
                info[k]["allineamento"] = "riferimento"
                continue
            t = stima_trasformazione(stelle[k], stelle[rif], max_spost=max(8.0, 6.0 / g.scala))
            if t is None or t[2] < 3:
                info[k]["allineamento"] = "solo coordinate WCS (troppe poche stelle in comune)"
                log(f"   {info[k]['epoca']['etichetta']}: allineamento solo con le coordinate (stelle insufficienti)")
                continue
            B, u, n_st, rms = t
            grezze[k] = applica_trasformazione(grezze[k], B, u)
            stelle[k] = trova_stelle(grezze[k], neb)
            sp = math.hypot(*u) if np.allclose(B, np.eye(2), atol=1e-3) else math.hypot(*(B @ [g.c, g.c] + u - g.c))
            info[k]["allineamento"] = f"{n_st} stelle, scarto {rms * g.scala:.2f}″, correzione {sp * g.scala:.1f}″"
            log(f"   {info[k]['epoca']['etichetta']}: allineata con {n_st} stelle (scarto medio {rms * g.scala:.2f}″, "
                f"correzione al centro {sp * g.scala:.1f}″)")
    elif modo == "picco":
        c = g.world2pix(ogg["ra"], ogg["dec"]) if ogg.get("ra") is not None else (g.c, g.c)
        rp = ogg.get("picco_raggio_arcsec", 30.0) / g.scala
        sp_ = ogg.get("picco_sigma_arcsec", 2.0 * g.scala) / g.scala
        pr = picco(grezze[rif], c, rp, sp_)
        for k in range(len(grezze)):
            if k == rif:
                info[k]["allineamento"] = "riferimento (punto più brillante)"
                continue
            pk = picco(grezze[k], c, rp, sp_)
            u = np.array([pk[0] - pr[0], pk[1] - pr[1]])
            if math.hypot(*u) * g.scala > ogg.get("picco_max_arcsec", 3.0):   # Chandra ~0,6″: scarto grande = picco sbagliato
                info[k]["allineamento"] = "solo coordinate WCS (punto più brillante non affidabile)"
                log(f"   {info[k]['epoca']['etichetta']}: punto più brillante a {math.hypot(*u) * g.scala:.1f}″, "
                    "tengo le coordinate del file")
                continue
            grezze[k] = applica_trasformazione(grezze[k], np.eye(2), u)
            info[k]["allineamento"] = f"sul punto più brillante, correzione {math.hypot(*u) * g.scala:.2f}″"
            log(f"   {info[k]['epoca']['etichetta']}: allineata sul punto più brillante ({math.hypot(*u) * g.scala:.2f}″)")
    else:
        for i in info:
            i["allineamento"] = "solo coordinate WCS"
    # nitidezza (PSF) delle immagini
    sig = [sigma_psf(a, s) for a, s in zip(grezze, stelle)]
    for i, s in zip(info, sig):
        i["fwhm_arcsec"] = round(2.3548 * s * g.scala, 2) if s and not i["raggi_x"] else None
    if progresso:
        progresso(0.7, "uguaglio nitidezza e luminosità")
    validi = [s for s in sig if s]
    obiettivo = max(validi) if validi else None
    if any(i["raggi_x"] for i in info):
        obiettivo = None                          # raggi X: stesso strumento, niente «stelle» per la PSF
    uguali = []
    for a, s in zip(grezze, sig):
        b = a
        if obiettivo and s and obiettivo ** 2 - s ** 2 > 0.09:
            b = levigata(a, math.sqrt(obiettivo ** 2 - s ** 2))
        uguali.append(b)
    if obiettivo:
        log(f"   nitidezza portata a quella dell'immagine meno nitida: FWHM {2.3548 * obiettivo * g.scala:.1f}″")
    comune = np.all([np.isfinite(a) for a in grezze], axis=0)
    vista = immagini_vista(grezze if not nitidezza_uguale else uguali, info, comune, neb, rif)
    return dict(griglia=g, info=info, grezze=grezze, uguali=uguali, vista=vista, comune=comune, rif=rif,
                nebulosa=neb, ogg=ogg)


def levigata(a, s):
    ok = np.isfinite(a)
    num = ndi.gaussian_filter(np.where(ok, a, 0).astype(DTYPE), s)
    den = ndi.gaussian_filter(ok.astype(DTYPE), s)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 0.5, num / np.where(den > 0, den, 1), np.nan)
    return out.astype(DTYPE)


def immagini_vista(imgs, info, comune, neb, rif):
    """Immagini in [0, 1] con la stessa resa: ottico = istogramma uguagliato al
    riferimento + asinh; raggi X = conteggi al secondo, scala logaritmica comune."""
    x_ray = all(i["raggi_x"] for i in info)
    out = []
    if x_ray:
        tassi = []
        for a, i in zip(imgs, info):
            t = a / (i["esposizione"] if i["esposizione"] > 0 else 1.0)
            tassi.append(levigata(t, 0.8))
        r = tassi[rif]
        v = r[comune & np.isfinite(r) & (r > 0)]
        lo = float(np.percentile(v, 30)) if v.size else 1e-6
        hi = float(np.percentile(v, 99.95)) if v.size else 1.0
        for t in tassi:
            y = (np.log10(np.clip(t, lo, None)) - math.log10(lo)) / max(math.log10(hi) - math.log10(lo), 1e-6)
            y = np.clip(y, 0, 1)
            y[~np.isfinite(t)] = 0
            out.append(y.astype(DTYPE))
        return out
    r = imgs[rif]
    zona = comune & np.isfinite(r)
    fondo_r = float(np.nanmedian(r[zona & ~neb])) if (zona & ~neb).sum() > 100 else float(np.nanmedian(r[zona]))
    alto = float(np.nanpercentile(r[zona], 99.85))
    k = 12.0
    for a in imgs:
        b = uguaglia_istogramma(a, r, zona) if a is not r else a
        x = np.clip((b - fondo_r) / max(alto - fondo_r, 1e-9), 0, 1.2)
        y = np.arcsinh(k * x) / math.asinh(k)
        y = np.clip(np.nan_to_num(y, nan=0.0), 0, 1)
        out.append(y.astype(DTYPE))
    return out


# =============================================================================
# MISURA DELL'ESPANSIONE (M 1)
# =============================================================================
def filamenti(a, s_piccola=1.0, s_grande=6.0):
    """Immagine dei dettagli (differenza di gaussiane), NaN fuori dai dati."""
    ok = np.isfinite(a)
    b = np.where(ok, a, np.nanmedian(a)).astype(DTYPE)
    d = ndi.gaussian_filter(b, s_piccola) - ndi.gaussian_filter(b, s_grande)
    d[~ndi.binary_erosion(ok, iterations=int(3 * s_grande))] = np.nan
    return d


def maschera_stelle(a, raggio):
    """Dischi sulle stelle; il raggio cresce con la luminosità (aloni delle stelle brillanti)."""
    st = trova_stelle(a, None, max_n=3000, soglia=8.0)
    m = np.zeros(a.shape, bool)
    if len(st):
        st = st[e_puntiforme(a, st, max(raggio / 3.0, 1.0))]
    if len(st):
        fmin = max(float(st[:, 2].min()), 1e-12)
        for sx, sy, f in st:
            rr = raggio * (1 + 0.6 * math.log10(max(f / fmin, 1.0)))
            x0, x1 = int(max(sx - rr - 1, 0)), int(min(sx + rr + 2, a.shape[1]))
            y0, y1 = int(max(sy - rr - 1, 0)), int(min(sy + rr + 2, a.shape[0]))
            yy, xx = np.mgrid[y0:y1, x0:x1]
            m[y0:y1, x0:x1] |= (xx - sx) ** 2 + (yy - sy) ** 2 <= rr ** 2
    return m


def maschera_stelle_ferme(a, b, raggio, tolleranza=1.0):
    """Solo le sorgenti puntiformi che stanno nello stesso punto (entro 'tolleranza' pixel)
    in tutte e due le immagini: le stelle. I nodi dei filamenti si spostano e restano."""
    sa = trova_stelle(a, None, max_n=3000, soglia=8.0)
    sb = trova_stelle(b, None, max_n=3000, soglia=8.0)
    if len(sa):
        sa = sa[e_puntiforme(a, sa, max(raggio / 3.0, 1.0))]
    if len(sb):
        sb = sb[e_puntiforme(b, sb, max(raggio / 3.0, 1.0))]
    ia, ib = _accoppia(sa[:, :2] if len(sa) else sa, sb[:, :2] if len(sb) else sb, tolleranza)
    m = np.zeros(a.shape, bool)
    if not len(ia):
        return m
    st = sb[ib]
    fmin = max(float(st[:, 2].min()), 1e-12)
    for sx, sy, f in st:
        rr = min(raggio * (1 + 0.6 * math.log10(max(f / fmin, 1.0))), 3 * raggio)
        x0, x1 = int(max(sx - rr - 1, 0)), int(min(sx + rr + 2, a.shape[1]))
        y0, y1 = int(max(sy - rr - 1, 0)), int(min(sy + rr + 2, a.shape[0]))
        yy, xx = np.mgrid[y0:y1, x0:x1]
        m[y0:y1, x0:x1] |= (xx - sx) ** 2 + (yy - sy) ** 2 <= rr ** 2
    return m


def e_puntiforme(a, st, sigma):
    """Vero per le sorgenti rotonde (stelle) e falso per i nodi dei filamenti: le due
    curvature principali (Hessiano dell'immagine levigata) devono essere simili."""
    b = np.nan_to_num(a - np.nanmedian(a)).astype(DTYPE)
    lxx = ndi.gaussian_filter(b, sigma, order=(0, 2))
    lyy = ndi.gaussian_filter(b, sigma, order=(2, 0))
    lxy = ndi.gaussian_filter(b, sigma, order=(1, 1))
    xi = np.clip(np.round(st[:, 0]).astype(int), 0, a.shape[1] - 1)
    yi = np.clip(np.round(st[:, 1]).astype(int), 0, a.shape[0] - 1)
    A, C, B = lxx[yi, xi], lyy[yi, xi], lxy[yi, xi]
    tr, det = A + C, A * C - B * B
    disc = np.sqrt(np.clip(tr * tr / 4 - det, 0, None))
    l1, l2 = tr / 2 - disc, tr / 2 + disc            # l1 <= l2; per una stella entrambi < 0
    with np.errstate(invalid="ignore", divide="ignore"):
        rapporto = np.where(l1 < 0, l2 / l1, 0)
    return (l2 < 0) & (rapporto > 0.45)


def togli_stelle(a, maschera):
    """Riempie i pixel della maschera con i dintorni (levigatura che ignora i buchi)."""
    b = np.array(a, dtype=DTYPE)
    b[maschera] = np.nan
    for s in (3.0, 6.0, 12.0, 24.0):
        buchi = maschera & ~np.isfinite(b)
        if not buchi.any():
            break
        f = levigata(b, s)
        b[buchi] = f[buchi]
    b[maschera & ~np.isfinite(b)] = np.nanmedian(a)
    b[~np.isfinite(a)] = np.nan
    return b


def _corr(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 100:
        return -1.0
    a, b = a[ok] - a[ok].mean(), b[ok] - b[ok].mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 0 else -1.0


def scala_campioni(H, s, cx, cy, xs, ys):
    """Valori di H 'ingrandita' di s attorno a (cx, cy) nei punti (xs, ys)."""
    return campiona(H, cx + (xs - cx) / s, cy + (ys - cy) / s)


def adatta_scala(H_prima, H_dopo, regione, c0, s_min=0.97, s_max=1.20, centro_fisso=False):
    ys, xs = np.nonzero(regione)
    xs, ys = xs.astype(float), ys.astype(float)
    b = H_dopo[regione]
    griglia_s = np.arange(s_min, s_max + 1e-9, 0.002)
    cc = [_corr(scala_campioni(H_prima, s, c0[0], c0[1], xs, ys), b) for s in griglia_s]
    i = int(np.argmax(cc))
    s0 = float(griglia_s[i])
    if centro_fisso:
        if 0 < i < len(cc) - 1:
            y0, y1, y2 = cc[i - 1], cc[i], cc[i + 1]
            den = y0 - 2 * y1 + y2
            s0 += (0.5 * (y0 - y2) / den if den < 0 else 0.0) * 0.002
        return float(s0), float(c0[0]), float(c0[1]), float(cc[i]), (griglia_s, np.array(cc))
    from scipy.optimize import minimize
    f = lambda p: -_corr(scala_campioni(H_prima, p[0], p[1], p[2], xs, ys), b)
    r = minimize(f, [s0, c0[0], c0[1]], method="Nelder-Mead",
                 options=dict(xatol=1e-4, fatol=1e-5, maxiter=400, initial_simplex=np.array(
                     [[s0, c0[0], c0[1]], [s0 + 0.004, c0[0], c0[1]], [s0, c0[0] + 3, c0[1]], [s0, c0[0], c0[1] + 3]])))
    s, cx, cy = r.x
    if math.hypot(cx - c0[0], cy - c0[1]) > 40 or not (s_min < s < s_max):
        s, cx, cy = s0, c0[0], c0[1]
    return float(s), float(cx), float(cy), float(-r.fun), (griglia_s, np.array(cc))


def adatta_scala_settore(H_prima, H_dopo, regione, c, s_centro):
    ys, xs = np.nonzero(regione)
    if len(xs) < 300:
        return None
    xs, ys = xs.astype(float), ys.astype(float)
    b = H_dopo[regione]
    sg = np.arange(s_centro - 0.04, s_centro + 0.04 + 1e-9, 0.001)
    cc = np.array([_corr(scala_campioni(H_prima, s, c[0], c[1], xs, ys), b) for s in sg])
    i = int(np.argmax(cc))
    if i in (0, len(sg) - 1) or cc[i] < 0.2:
        return None
    y0, y1, y2 = cc[i - 1], cc[i], cc[i + 1]
    den = y0 - 2 * y1 + y2
    d = 0.5 * (y0 - y2) / den if den < 0 else 0.0
    return float(sg[i] + d * 0.001), float(cc[i])


def ncc(E, T):
    """Correlazione normalizzata di un modello T dentro una finestra E (modo 'valid')."""
    from scipy.signal import fftconvolve
    T0 = T - T.mean()
    nT = math.sqrt(float((T0 * T0).sum()))
    if nT <= 0:
        return None
    uno = np.ones_like(T)
    num = fftconvolve(E, T0[::-1, ::-1], mode="valid")
    sE = fftconvolve(E, uno, mode="valid")
    sE2 = fftconvolve(E * E, uno, mode="valid")
    var = np.clip(sE2 - sE * sE / T.size, 1e-12, None)
    return num / (np.sqrt(var) * nT)


def frecce_movimento(H_prima, H_dopo, regione, valido, c, s, lato=24, passo=14):
    """Spostamenti locali dei filamenti (dalla prima all'ultima epoca)."""
    n = H_dopo.shape[0]
    h = lato // 2
    risultati = []
    righe = []
    for y in range(h, n - h, passo):
        for x in range(h, n - h, passo):
            if not regione[y, x]:
                continue
            T = H_dopo[y - h:y + h, x - h:x + h]
            vm = valido[y - h:y + h, x - h:x + h]
            if vm.mean() < 0.7:
                continue
            righe.append((x, y, float(np.nanstd(T))))
    if not righe:
        return []
    soglia = np.percentile([r[2] for r in righe], 25)
    for x, y, sd in righe:
        if sd < soglia:
            continue
        T = np.nan_to_num(H_dopo[y - h:y + h, x - h:x + h].astype(np.float64))
        ex = c[0] + (x - c[0]) / s                    # dove ci si aspetta il filamento nella prima epoca
        ey = c[1] + (y - c[1]) / s
        m = int(6 + 0.6 * math.hypot(x - ex, y - ey))
        xi, yi = int(round(ex)), int(round(ey))
        if yi - h - m < 0 or xi - h - m < 0 or yi + h + m > n or xi + h + m > n:
            continue
        E = H_prima[yi - h - m:yi + h + m, xi - h - m:xi + h + m].astype(np.float64)
        if np.isfinite(E).mean() < 0.7:
            continue
        E = np.nan_to_num(E)
        mappa = ncc(E, T)
        if mappa is None:
            continue
        iy, ix = np.unravel_index(int(np.argmax(mappa)), mappa.shape)
        best = float(mappa[iy, ix])
        if best < 0.45 or iy in (0, mappa.shape[0] - 1) or ix in (0, mappa.shape[1] - 1):
            continue

        def parab(a, b, cc_):
            den = a - 2 * b + cc_
            return 0.5 * (a - cc_) / den if den < 0 else 0.0
        dy = parab(mappa[iy - 1, ix], mappa[iy, ix], mappa[iy + 1, ix])
        dx = parab(mappa[iy, ix - 1], mappa[iy, ix], mappa[iy, ix + 1])
        qx = xi - m + ix + dx                     # posizione nella prima epoca
        qy = yi - m + iy + dy
        # scarta gli abbinamenti sbagliati: troppo lontani da quanto dice l'espansione misurata
        attesa = math.hypot(x - ex, y - ey)
        if math.hypot(qx - ex, qy - ey) > max(4.0, 0.75 * attesa):
            continue
        risultati.append(dict(x=float(x), y=float(y), x0=float(qx), y0=float(qy), ncc=best))
    return risultati


def dettagli(ogg, g, sig):
    """Scale (pixel) del filtro dei dettagli: piccola e grande."""
    if ogg.get("dettagli_arcsec"):
        a, b = ogg["dettagli_arcsec"]
        return max(a / g.scala, 0.7), max(b / g.scala, 3.0)
    return max(sig * 0.5, 0.7), 6.0


def epoche_correlate(lavoro, buone, log=print):
    """Confronta ogni epoca con l'ultima (centro fisso, griglia grossolana) e scarta quelle che non
    si correlano (rumore, saturazione): restituisce le epoche buone."""
    ogg, g, info, imgs = lavoro["ogg"], lavoro["griglia"], lavoro["info"], lavoro["uguali"]
    if len(buone) < 3:
        return buone
    sig = max([i.get("fwhm_arcsec") or 2.0 for i in info]) / 2.3548 / g.scala
    sp, sgr = dettagli(ogg, g, sig)
    ultima = buone[-1]
    cx, cy = g.world2pix(*ogg["centro"])
    y, x = np.mgrid[0:g.n, 0:g.n]
    r = np.hypot(x - cx, y - cy) * g.scala
    Hu = filamenti(imgs[ultima], sp, sgr)
    valori = {}
    for k in buone[:-1]:
        Hk = filamenti(imgs[k], sp, sgr)
        reg = maschera_ellisse(g, ogg, 1.0) & (r > ogg.get("raggio_interno_arcsec", 20)) & np.isfinite(Hk) & np.isfinite(Hu)
        if reg.sum() < 500:
            valori[k] = 0.0
            continue
        ys, xs = np.nonzero(reg)
        ys, xs = ys[::4].astype(float), xs[::4].astype(float)
        b = Hu[ys.astype(int), xs.astype(int)]
        valori[k] = max(_corr(scala_campioni(Hk, s_, cx, cy, xs, ys), b)
                        for s_ in np.arange(0.99, ogg.get("scala_max", 1.2) + 1e-9, 0.01))
    migliore = max(valori.values()) if valori else 0
    tenute = [k for k in buone[:-1] if valori[k] >= 0.4 * migliore] + [ultima]
    for k in buone[:-1]:
        if k not in tenute:
            log(f"   {info[k]['epoca']['etichetta']} {testo_anno(info[k]['epoca']['anno'])}: si correla poco con "
                f"l'ultima epoca ({valori[k]:.2f} contro {migliore:.2f}): esclusa dalla misura (resta nell'animazione)")
    return tenute


def misura_espansione(lavoro, log=print, progresso=None):
    ogg, g, info = lavoro["ogg"], lavoro["griglia"], lavoro["info"]
    imgs = lavoro["uguali"]
    buone = [k for k, i in enumerate(info) if i["copertura"] >= 0.8] or list(range(len(info)))
    buone = epoche_correlate(lavoro, buone, log)
    lavoro["epoche_misura"] = buone
    i0, i1 = buone[0], buone[-1]
    t0_, t1_ = info[i0]["epoca"]["anno"], info[i1]["epoca"]["anno"]
    dt = t1_ - t0_
    if dt < 5:
        raise ValueError("le epoche sono troppo vicine nel tempo per misurare l'espansione")
    log(f"Misura dell'espansione: {info[i0]['epoca']['etichetta']} {testo_anno(t0_)} → "
        f"{info[i1]['epoca']['etichetta']} {testo_anno(t1_)} ({dt:.1f} anni)")
    sig = max([i.get("fwhm_arcsec") or 2.0 for i in info]) / 2.3548 / g.scala
    # le stelle non si espandono: tolte da entrambe le immagini PRIMA del filtro dei dettagli
    if any(i["raggi_x"] for i in info):
        stelle = np.zeros(imgs[i0].shape, bool)     # nei raggi X i punti brillanti sono nodi di gas, non stelle
    else:
        stelle = maschera_stelle_ferme(imgs[i0], imgs[i1], 2 * sig + 2)
    log(f"   stelle ferme tolte: {stelle[maschera_ellisse(g, ogg, 1.0)].mean() * 100:.0f} % della nebulosa")
    pulite = [togli_stelle(imgs[i0], stelle), togli_stelle(imgs[i1], stelle)]
    sp, sgr = dettagli(ogg, g, sig)
    H0, H1 = (filamenti(a, sp, sgr) for a in pulite)
    for H in (H0, H1):                            # limita i punti saturi
        v = H[np.isfinite(H)]
        if v.size:
            lo, hi = np.percentile(v, [0.5, 99.5])
            np.clip(H, lo, hi, out=H)
    nucleo = ndi.binary_dilation(stelle, iterations=1)
    H0[nucleo] = np.nan
    H1[nucleo] = np.nan
    cx0, cy0 = g.world2pix(*ogg["centro"])
    neb = maschera_ellisse(g, ogg, 1.0)
    y, x = np.mgrid[0:g.n, 0:g.n]
    r = np.hypot(x - cx0, y - cy0) * g.scala
    regione = neb & (r > ogg.get("raggio_interno_arcsec", 20)) & ~stelle & np.isfinite(H0) & np.isfinite(H1)
    if regione.sum() < 2000:
        raise ValueError("zona della nebulosa troppo piccola o senza dati")
    if progresso:
        progresso(0.78, "misuro l'ingrandimento della nebulosa")
    s, cx, cy, cmax, (sg, cc) = adatta_scala(H0, H1, regione, (cx0, cy0), 0.97, ogg.get("scala_max", 1.20),
                                             centro_fisso=ogg.get("centro_fisso", False))
    k = s - 1
    anno_zero = (s * t0_ - t1_) / (s - 1) if k > 1e-4 else None
    ra_c, dec_c = g.pix2world(np.array([cx]), np.array([cy]))
    sep_c = separazione_arcsec(float(ra_c[0]), float(dec_c[0]), *ogg["centro"])
    log(f"   ingrandimento {k * 100:.2f} % in {dt:.1f} anni (correlazione {cmax:.3f}), "
        f"centro a {sep_c:.1f}″ dalla {ogg.get('centro_nome', 'posizione di riferimento')}")
    # settori: stima dell'incertezza
    ang = (np.degrees(np.arctan2(-(x - cx), y - cy)) + 360) % 360      # da Nord verso Est
    settori = []
    for j in range(8):
        sel = regione & (ang >= j * 45) & (ang < (j + 1) * 45)
        rs = adatta_scala_settore(H0, H1, sel, (cx, cy), s)
        if rs:
            ss, cs = rs
            settori.append(dict(angolo=j * 45 + 22.5, scala=ss, correlazione=cs,
                                anno_zero=(ss * t0_ - t1_) / (ss - 1) if ss - 1 > 1e-4 else None))
    az = [q["anno_zero"] for q in settori if q["anno_zero"] is not None]
    err_anno = float(np.std(az, ddof=1) / math.sqrt(len(az))) if len(az) >= 3 else None
    if anno_zero is not None:
        # parte sistematica: 1,5 % sull'ingrandimento (prove con nebulose simulate e lastre sature)
        # e, se una data è approssimata, ±3 anni su quella data
        eta = t1_ - anno_zero
        sist = eta * 0.015
        dt_appross = sum(3.0 for i in (info[i0], info[i1]) if i["epoca"].get("anno_approssimato"))
        sist = math.hypot(sist, dt_appross * s / (s - 1)) if dt_appross else sist
        err_anno = math.hypot(err_anno or 0.0, sist)
    ks = [q["scala"] - 1 for q in settori]
    err_k = float(np.std(ks, ddof=1) / math.sqrt(len(ks))) if len(ks) >= 3 else None
    err_k = math.hypot(err_k or 0.0, 0.015 * k)
    if progresso:
        progresso(0.84, "frecce sui filamenti")
    valido = np.isfinite(H0) & np.isfinite(H1) & ~stelle
    fr = frecce_movimento(H0, H1, regione, valido, (cx, cy), s)
    d_pc = ogg.get("distanza_pc", 2000.0)
    for f in fr:
        dx, dy = f["x"] - f["x0"], f["y"] - f["y0"]
        f["spost_arcsec"] = math.hypot(dx, dy) * g.scala
        rx, ry = f["x"] - cx, f["y"] - cy
        rr = math.hypot(rx, ry)
        f["raggio_arcsec"] = rr * g.scala
        f["radiale_arcsec"] = (dx * rx + dy * ry) / rr * g.scala if rr > 0 else 0.0
        f["mu_arcsec_anno"] = f["spost_arcsec"] / dt
        f["v_kms"] = KMS * f["mu_arcsec_anno"] * d_pc
        f["anno_zero"] = (t1_ - f["raggio_arcsec"] / (f["radiale_arcsec"] / dt)) if f["radiale_arcsec"] > 0.3 else None
        ra_f, dec_f = g.pix2world(np.array([f["x"]]), np.array([f["y"]]))
        f["ra"], f["dec"] = float(ra_f[0]), float(dec_f[0])
    # tieni le frecce coerenti con un'espansione (radiali verso l'esterno, entro 50° dalla direzione radiale)
    buone = []
    for f in fr:
        if f["spost_arcsec"] < 0.3 or f["radiale_arcsec"] <= 0:
            continue
        cosang = f["radiale_arcsec"] / f["spost_arcsec"]
        if cosang > math.cos(math.radians(50)):
            buone.append(f)
    log(f"   frecce: {len(buone)} filamenti misurati (su {len(fr)} provati)")
    v = [f["v_kms"] for f in buone]
    az_f = [f["anno_zero"] for f in buone if f["anno_zero"] is not None]
    coppie, stime = [], {}
    ep_ok = list(lavoro["epoche_misura"])
    if anno_zero is not None and len(ep_ok) >= 3:
        if progresso:
            progresso(0.86, "controllo con le coppie di epoche")
        for a, b in zip(ep_ok[:-1], ep_ok[1:]):
            c_ = scala_coppia(lavoro, a, b, (cx, cy), anno_zero)
            if c_ is None:
                log(f"   coppia {info[a]['epoca']['etichetta']} → {info[b]['epoca']['etichetta']}: misura non riuscita")
                continue
            sc, cc_, es = c_
            es = math.hypot(es or 0.0, 0.015 * (sc - 1))      # come la coppia principale: + 1,5 % sistematico
            ta, tb = info[a]["epoca"]["anno"], info[b]["epoca"]["anno"]
            ea, eb = info[a]["epoca"], info[b]["epoca"]
            q = dict(prima=ea["etichetta"], dopo=eb["etichetta"], anno_prima=ta, anno_dopo=tb, scala=sc,
                     ingrandimento_pc=(sc - 1) * 100, correlazione=cc_,
                     anno_prima_approssimato=bool(ea.get("anno_approssimato")),
                     anno_dopo_approssimato=bool(eb.get("anno_approssimato")),
                     err_ingrandimento_pc=es * 100,
                     anno_zero=(sc * ta - tb) / (sc - 1) if sc - 1 > 1e-4 else None,
                     err_anno_zero=(tb - ta) / (sc - 1) ** 2 * es if sc - 1 > 1e-4 else None)
            # data dell'epoca approssimata ricavata dal modello (anno_zero della coppia principale)
            if ea.get("anno_approssimato") and not eb.get("anno_approssimato"):
                q["data_stimata"] = anno_zero + (tb - anno_zero) / sc
                q["err_data_stimata"] = (tb - anno_zero) / sc ** 2 * es
                stime.setdefault(a, []).append(q["data_stimata"])
            elif eb.get("anno_approssimato") and not ea.get("anno_approssimato"):
                q["data_stimata"] = anno_zero + sc * (ta - anno_zero)
                q["err_data_stimata"] = abs(ta - anno_zero) * es
                stime.setdefault(b, []).append(q["data_stimata"])
            coppie.append(q)
            log(f"   coppia {ea['etichetta']} {testo_anno(ta)} → {eb['etichetta']} {testo_anno(tb)}: "
                f"+{(sc - 1) * 100:.2f} ± {es * 100:.2f} % (correlazione {cc_:.3f})"
                + (f", anno {q['anno_zero']:.0f} ± {q['err_anno_zero']:.0f}" if q.get("anno_zero") else "")
                + (f", data stimata dell'epoca approssimata {q['data_stimata']:.1f} ± {q['err_data_stimata']:.1f}"
                   if "data_stimata" in q else ""))
    guscio = []
    rg = ogg.get("raggio_guscio_arcsec")
    if rg and anno_zero is not None and len(ep_ok) >= 2:
        if progresso:
            progresso(0.87, f"misura sul solo guscio esterno (oltre {rg:.0f}″)")
        lista = [(ep_ok[0], ep_ok[-1])] + ([(a, b) for a, b in zip(ep_ok[:-1], ep_ok[1:])] if len(ep_ok) >= 3 else [])
        for a, b in lista:
            c_ = scala_coppia(lavoro, a, b, (cx, cy), anno_zero, raggio_min=rg)
            if c_ is None:
                log(f"   guscio esterno {info[a]['epoca']['etichetta']} → {info[b]['epoca']['etichetta']}: non riuscita")
                continue
            sc, cc_, es = c_
            es = math.hypot(es or 0.0, 0.015 * (sc - 1))
            ta, tb = info[a]["epoca"]["anno"], info[b]["epoca"]["anno"]
            q = dict(prima=info[a]["epoca"]["etichetta"], dopo=info[b]["epoca"]["etichetta"], anno_prima=ta,
                     anno_dopo=tb, ingrandimento_pc=(sc - 1) * 100, err_ingrandimento_pc=es * 100,
                     correlazione=cc_, anno_zero=(sc * ta - tb) / (sc - 1) if sc - 1 > 1e-4 else None,
                     err_anno_zero=(tb - ta) / (sc - 1) ** 2 * es if sc - 1 > 1e-4 else None)
            guscio.append(q)
            log(f"   guscio esterno (> {rg:.0f}″) {q['prima']} {testo_anno(ta)} → {q['dopo']} {testo_anno(tb)}: "
                f"+{q['ingrandimento_pc']:.2f} ± {q['err_ingrandimento_pc']:.2f} %"
                + (f", anno {q['anno_zero']:.0f} ± {q['err_anno_zero']:.0f}" if q["anno_zero"] else ""))
    date_stimate = {info[k]["epoca"]["etichetta"]: float(np.mean(v)) for k, v in stime.items()}
    ris = dict(tipo="espansione", epoca_prima=info[i0]["epoca"]["etichetta"], epoca_dopo=info[i1]["epoca"]["etichetta"],
               coppie=coppie, date_stimate=date_stimate, guscio=guscio, raggio_guscio_arcsec=rg,
               anno_prima=t0_, anno_dopo=t1_, anni=dt, scala=s, ingrandimento_pc=k * 100,
               err_ingrandimento_pc=err_k * 100 if err_k else None, ritmo_pc_anno=k / dt * 100,
               centro_x=cx, centro_y=cy, centro_ra=float(ra_c[0]), centro_dec=float(dec_c[0]),
               centro_dal_riferimento_arcsec=sep_c, correlazione=cmax, anno_zero=anno_zero,
               err_anno_zero=err_anno, settori=settori, frecce=buone,
               v_media_kms=float(np.median(v)) if v else None, v_max_kms=float(np.percentile(v, 95)) if v else None,
               spost_medio_arcsec=float(np.median([f["spost_arcsec"] for f in buone])) if buone else None,
               spost_max_arcsec=float(np.percentile([f["spost_arcsec"] for f in buone], 95)) if buone else None,
               anno_zero_frecce=float(np.median(az_f)) if len(az_f) >= 5 else None,
               distanza_pc=d_pc, anno_evento=ogg.get("anno_evento"),
               curva=dict(scale=sg.tolist(), correlazioni=cc.tolist()),
               date_approssimate=[i["epoca"]["etichetta"] for i in (info[i0], info[i1]) if i["epoca"].get("anno_approssimato")])
    if anno_zero is not None:
        log(f"   anno dell'esplosione (espansione sempre uguale): {anno_zero:.0f}"
            + (f" ± {err_anno:.0f}" if err_anno else ""))
    return ris


def scala_coppia(lavoro, a, b, centro, anno_zero, raggio_min=None):
    """Ingrandimento tra due epoche qualsiasi, con il centro già trovato: (scala, correlazione)."""
    ogg, g, info, imgs = lavoro["ogg"], lavoro["griglia"], lavoro["info"], lavoro["uguali"]
    sig = max([info[k].get("fwhm_arcsec") or 2.0 for k in (a, b)]) / 2.3548 / g.scala
    if any(info[k]["raggi_x"] for k in (a, b)):
        stelle = np.zeros(imgs[a].shape, bool)
    else:
        stelle = maschera_stelle_ferme(imgs[a], imgs[b], 2 * sig + 2)
    sp, sgr = dettagli(ogg, g, sig)
    Ha, Hb = (filamenti(togli_stelle(imgs[k], stelle), sp, sgr) for k in (a, b))
    for H in (Ha, Hb):
        v = H[np.isfinite(H)]
        if v.size:
            lo, hi = np.percentile(v, [0.5, 99.5])
            np.clip(H, lo, hi, out=H)
    nucleo = ndi.binary_dilation(stelle, iterations=1)
    Ha[nucleo] = np.nan
    Hb[nucleo] = np.nan
    y, x = np.mgrid[0:g.n, 0:g.n]
    r = np.hypot(x - centro[0], y - centro[1]) * g.scala
    regione = (maschera_ellisse(g, ogg, 1.0) & (r > (raggio_min or ogg.get("raggio_interno_arcsec", 20)))
               & np.isfinite(Ha) & np.isfinite(Hb))
    ta, tb = info[a]["epoca"]["anno"], info[b]["epoca"]["anno"]
    attesa = (tb - anno_zero) / (ta - anno_zero)
    r_tot = adatta_scala_settore(Ha, Hb, regione, centro, attesa)
    if r_tot is None:
        return None
    ang = (np.degrees(np.arctan2(-(x - centro[0]), y - centro[1])) + 360) % 360
    ss = []
    for j in range(8):
        q = adatta_scala_settore(Ha, Hb, regione & (ang >= j * 45) & (ang < (j + 1) * 45), centro, r_tot[0])
        if q:
            ss.append(q[0])
    err = float(np.std(ss, ddof=1) / math.sqrt(len(ss))) if len(ss) >= 3 else None
    return r_tot[0], r_tot[1], err


# =============================================================================
# MOTO PROPRIO (stella di Barnard)
# =============================================================================
def misura_moto_proprio(lavoro, log=print):
    ogg, g, info = lavoro["ogg"], lavoro["griglia"], lavoro["info"]
    punti = []
    for a, i in zip(lavoro["grezze"], info):
        anno = i["epoca"]["anno"]
        ra_p, dec_p = posizione_al_tempo(ogg, anno)
        px, py = g.world2pix(ra_p, dec_p)
        r = 15.0 / g.scala
        if not (r < px < g.n - r and r < py < g.n - r):
            log(f"   {i['epoca']['etichetta']}: la stella cade fuori dal campo")
            continue
        b = np.nan_to_num(a - np.nanmedian(a))
        x0, y0 = picco(b, (px, py), r)
        sub = b[int(y0) - 6:int(y0) + 7, int(x0) - 6:int(x0) + 7]
        if sub.size:
            s = np.clip(sub - np.median(sub), 0, None)
            yy, xx = np.mgrid[int(y0) - 6:int(y0) - 6 + s.shape[0], int(x0) - 6:int(x0) - 6 + s.shape[1]]
            if s.sum() > 0:
                x0, y0 = float((xx * s).sum() / s.sum()), float((yy * s).sum() / s.sum())
        ra_m, dec_m = g.pix2world(np.array([x0]), np.array([y0]))
        dist = math.hypot(x0 - px, y0 - py) * g.scala
        punti.append(dict(anno=anno, x=x0, y=y0, ra=float(ra_m[0]), dec=float(dec_m[0]), scarto_previsto_arcsec=dist,
                          etichetta=i["epoca"]["etichetta"]))
        log(f"   {i['epoca']['etichetta']} {testo_anno(anno)}: stella trovata a {dist:.1f}″ dalla posizione prevista da Gaia")
    if len(punti) < 2:
        raise ValueError("stella trovata in meno di due epoche")
    t = np.array([p["anno"] for p in punti])
    X = np.array([p["x"] for p in punti])
    Y = np.array([p["y"] for p in punti])
    A = np.column_stack([t - t.mean(), np.ones_like(t)])
    (vx, _), *_ = np.linalg.lstsq(A, X, rcond=None)
    (vy, _), *_ = np.linalg.lstsq(A, Y, rcond=None)
    pmra = -vx * g.scala * 1000          # mas/anno (verso Est = x che diminuisce)
    pmdec = vy * g.scala * 1000
    mu = math.hypot(pmra, pmdec)
    d_pc = 1000.0 / ogg["plx_mas"]
    v = KMS * mu / 1000 * d_pc
    mu_gaia = math.hypot(*ogg["pm_mas"])
    res = None
    if len(punti) >= 3:
        res = float(np.sqrt(np.mean((X - (vx * (t - t.mean()) + X.mean())) ** 2 + (Y - (vy * (t - t.mean()) + Y.mean())) ** 2)) * g.scala)
    log(f"   moto proprio misurato {mu / 1000:.2f}″/anno (Gaia {mu_gaia / 1000:.2f}″/anno), velocità {v:.0f} km/s")
    return dict(tipo="moto_proprio", punti=punti, fonte_pm=ogg.get("fonte_pm", "Gaia DR3"), pmra_mas=pmra, pmdec_mas=pmdec, mu_mas=mu, mu_gaia_mas=mu_gaia,
                pm_gaia_mas=list(ogg["pm_mas"]), distanza_pc=d_pc, v_kms=v,
                v_gaia_kms=KMS * mu_gaia / 1000 * d_pc, scarto_arcsec=res,
                angolo_gradi=(math.degrees(math.atan2(pmra, pmdec)) + 360) % 360,
                spostamento_arcsec=mu / 1000 * (t.max() - t.min()), anni=float(t.max() - t.min()))


# =============================================================================
# TESTI DEI RISULTATI
# =============================================================================
def num(v, d=1):
    if v is None:
        return "–"
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def righe_risultati(ogg, lavoro, ris):
    info = lavoro["info"] if lavoro else []
    r = [ogg["nome"], "=" * len(ogg["nome"]), ""]
    r.append("Epoche usate:")
    for i in info:
        e = i["epoca"]
        r.append(f"  {testo_anno(e['anno'], 2)}  {e['etichetta']}" + (f" – {e['banda']}" if e.get("banda") else "")
                 + ("  (data approssimata)" if e.get("anno_approssimato") else "")
                 + (f"  · nitidezza {num(i.get('fwhm_arcsec'))}″" if i.get("fwhm_arcsec") else "")
                 + f"  · {i.get('allineamento', '')}")
    r.append("")
    if not ris:
        r.append("Solo animazione e confronto (nessuna misura per questo oggetto).")
    elif ris["tipo"] == "espansione":
        r += [f"Espansione dei filamenti ({ris['epoca_prima']} {testo_anno(ris['anno_prima'])} → "
              f"{ris['epoca_dopo']} {testo_anno(ris['anno_dopo'])}, {num(ris['anni'])} anni)",
              f"  la nebulosa si è ingrandita del {num(ris['ingrandimento_pc'], 2)} %"
              + (f" ± {num(ris['err_ingrandimento_pc'], 2)} %" if ris.get("err_ingrandimento_pc") else ""),
              f"  ritmo: {num(ris['ritmo_pc_anno'], 3)} % all'anno",
              f"  centro dell'espansione a {num(ris['centro_dal_riferimento_arcsec'])}″ dalla {ogg.get('centro_nome', 'posizione nota')}"]
        if ris.get("anno_zero") is not None:
            r.append(f"  se si fosse sempre espansa così, la stella sarebbe esplosa nell'anno {ris['anno_zero']:.0f}"
                     + (f" ± {ris['err_anno_zero']:.0f}" if ris.get("err_anno_zero") else ""))
        if ris.get("anno_zero_frecce"):
            r.append(f"  stesso calcolo con le frecce (mediana): anno {ris['anno_zero_frecce']:.0f}")
        if ris.get("frecce"):
            r += [f"  frecce: {len(ris['frecce'])} filamenti; spostamento tipico {num(ris['spost_medio_arcsec'])}″, "
                  f"i più veloci {num(ris['spost_max_arcsec'])}″",
                  f"  velocità a {num(ris['distanza_pc'], 0)} parsec: tipica {num(ris['v_media_kms'], 0)} km/s, "
                  f"i più veloci {num(ris['v_max_kms'], 0)} km/s"]
        if ris.get("coppie"):
            r += ["", "Controllo con le coppie di epoche (stesso centro):"]
            for q in ris["coppie"]:
                pa = ("≈ " if q["anno_prima_approssimato"] else "") + testo_anno(q["anno_prima"])
                pb = ("≈ " if q["anno_dopo_approssimato"] else "") + testo_anno(q["anno_dopo"])
                r.append(f"  {q['prima']} {pa} → {q['dopo']} {pb}: +{num(q['ingrandimento_pc'], 2)} ± "
                         f"{num(q.get('err_ingrandimento_pc'), 2)} % (correlazione {num(q['correlazione'], 2)})"
                         + (f" → anno {q['anno_zero']:.0f} ± {q['err_anno_zero']:.0f}" if q.get("anno_zero") and not
                            (q["anno_prima_approssimato"] or q["anno_dopo_approssimato"]) else ""))
            for nome, d in (ris.get("date_stimate") or {}).items():
                ep = next((i["epoca"] for i in lavoro["info"] if i["epoca"]["etichetta"] == nome), {})
                fonte = FONTI.get(ep.get("fonte"), {})
                intervallo = re.findall(r"(\d{4})-(\d{4})", fonte.get("nota_ripiego", ""))
                giudizio = ""
                if intervallo:
                    a0, a1 = map(int, intervallo[0])
                    giudizio = (f" → dentro gli anni della survey ({a0}-{a1}): le tre epoche sono coerenti"
                                if a0 - 2 <= d <= a1 + 2 else
                                f" → FUORI dagli anni della survey ({a0}-{a1}): qualcosa non torna (lastra o misura)")
                r.append(f"  la data di {nome} (non nota) ricavata dall'espansione: {testo_anno(d, 1)}{giudizio}")
            r.append("  (se l'espansione fosse rallentata o accelerata, le coppie darebbero ritmi diversi)")
        if ris.get("guscio"):
            r += ["", f"Solo il guscio esterno (oltre {ris['raggio_guscio_arcsec']:.0f}″ dal centro, lontano dal cuore "
                  "che brilla di luce continua):"]
            for q in ris["guscio"]:
                r.append(f"  {q['prima']} {testo_anno(q['anno_prima'])} → {q['dopo']} {testo_anno(q['anno_dopo'])}: "
                         f"+{num(q['ingrandimento_pc'], 2)} ± {num(q['err_ingrandimento_pc'], 2)} %"
                         + (f" → anno {q['anno_zero']:.0f} ± {q['err_anno_zero']:.0f}" if q.get("anno_zero") else ""))
            tutti = [(q["prima"], q["dopo"]) for q in ris["guscio"]]
            conf = []
            for q in ris["guscio"]:
                inter = next((c for c in ris.get("coppie", []) if (c["prima"], c["dopo"]) == (q["prima"], q["dopo"])), None)
                if inter is None and (q["prima"], q["dopo"]) == (ris["epoca_prima"], ris["epoca_dopo"]):
                    inter = dict(anno_zero=ris["anno_zero"], err_anno_zero=ris.get("err_anno_zero"))
                if inter and inter.get("anno_zero") and q.get("anno_zero"):
                    conf.append((q["prima"], q["dopo"], inter["anno_zero"], q["anno_zero"]))
            if conf:
                r.append("  confronto con tutta la nebulosa: " + "; ".join(
                    f"{a}→{b} {x:.0f} → {y:.0f}" for a, b, x, y in conf))
            del tutti
        if ris.get("anno_evento") and ogg.get("anno_evento_incerto"):
            r += ["", f"Confronto: la luce dell'esplosione arrivò intorno al {ris['anno_evento']} (data incerta: "
                  "nessuno la registrò con sicurezza). Nei raggi X si misura il guscio di gas caldo: il suo "
                  "ritmo di espansione oggi è più lento che all'inizio (il gas frena contro il materiale "
                  "intorno), quindi l'«anno a velocità costante» esce di solito PIÙ ANTICO della data vera."]
        elif ris.get("anno_evento"):
            r += ["", f"Confronto: l'esplosione fu vista nel {ris['anno_evento']}. Se l'anno calcolato è più recente "
                  "(di solito esce tra il 1100 e il 1150) non è un errore: il vento di particelle della pulsar "
                  "ha accelerato i filamenti, quindi in passato andavano più piano e l'espansione «a velocità "
                  "costante» porta a una data troppo recente. Le misure professionali danno circa 1140 (Trimble 1968) "
                  "e 1130 (Nugent 1998)."]
        if ris.get("date_approssimate"):
            r += ["", "Attenzione: la data di " + ", ".join(ris["date_approssimate"]) + " è approssimata; "
                  "ogni anno di errore sulle date sposta l'anno dell'esplosione di circa "
                  f"{abs(1 / (ris['scala'] - 1)) if ris['scala'] > 1 else 0:.0f} anni. Correggila nella scheda «Epoche» "
                  "(doppio clic sull'anno) se la conosci."]
    elif ris["tipo"] == "moto_proprio":
        r += [f"Moto proprio misurato: {num(ris['mu_mas'] / 1000, 2)}″ all'anno verso {num(ris['angolo_gradi'], 0)}° "
              "(da Nord verso Est)",
              f"  {ris.get('fonte_pm', 'Gaia DR3')}: {num(ris['mu_gaia_mas'] / 1000, 2)}″ all'anno "
              f"(differenza {num((ris['mu_mas'] - ris['mu_gaia_mas']) / ris['mu_gaia_mas'] * 100, 1)} %)",
              f"  in {num(ris['anni'])} anni la stella si è spostata di {num(ris['spostamento_arcsec'] / 60, 1)}′",
              f"  distanza {num(ris['distanza_pc'], 2)} parsec (parallasse Gaia): velocità nel cielo "
              f"{num(ris['v_kms'], 0)} km/s (Gaia: {num(ris['v_gaia_kms'], 0)} km/s)"]
        if ris.get("scarto_arcsec") is not None:
            r.append(f"  scarto dei punti dalla retta: {num(ris['scarto_arcsec'], 2)}″")
        for p in ris["punti"]:
            r.append(f"    {testo_anno(p['anno'])}  {p['etichetta']}: RA {p['ra']:.5f}  Dec {p['dec']:+.5f}")
    r += ["", f"{NOME_PROGRAMMA} {VERSIONE} · {FIRMA} · {datetime.now():%Y-%m-%d %H:%M}"]
    return r


# =============================================================================
# FOTOGRAMMI, GIF, MP4, PAGINA
# =============================================================================
def font(px, grassetto=False):
    from PIL import ImageFont
    nomi = ["DejaVuSans-Bold.ttf" if grassetto else "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if grassetto else "DejaVuSans.ttf")]
    try:
        import matplotlib
        nomi.append(os.path.join(matplotlib.get_data_path(), "fonts", "ttf",
                                 "DejaVuSans-Bold.ttf" if grassetto else "DejaVuSans.ttf"))
    except Exception:
        pass
    nomi += ["arial.ttf", "LiberationSans-Regular.ttf"]
    for n in nomi:
        try:
            return ImageFont.truetype(n, int(px))
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=int(px))
    except TypeError:
        return ImageFont.load_default()


def colora(v, raggi_x):
    """[0,1] -> RGB uint8 (ottico: grigio leggermente caldo; raggi X: «magma»)."""
    v = np.flipud(np.clip(v, 0, 1))
    if raggi_x:
        try:
            from matplotlib import colormaps
            rgb = colormaps["magma"](v)[..., :3]
        except Exception:
            rgb = np.stack([v, v ** 1.6, v ** 2.4], -1)
    else:
        rgb = np.stack([v, v * 0.985, v * 0.95], -1)
    return (rgb * 255 + 0.5).astype(np.uint8)


def _ombra(d, xy, testo, f, colore=(255, 255, 255), ancora="la"):
    x, y = xy
    for dx, dy in ((1, 1), (2, 2), (-1, 1), (1, -1)):
        d.text((x + dx, y + dy), testo, font=f, fill=(0, 0, 0), anchor=ancora)
    d.text((x, y), testo, font=f, fill=colore, anchor=ancora)


def disegna_cornice(img, ogg, g, titolo_anno, sotto, lato):
    """Scritte sul fotogramma: anno, strumento, nome, barra di scala, Nord/Est, firma."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    u = lato / 800.0
    if titolo_anno:
        _ombra(d, (18 * u, 14 * u), titolo_anno, font(46 * u, True), (255, 214, 120))
    if sotto:
        _ombra(d, (20 * u, 70 * u), sotto, font(20 * u))
    nome = ogg.get("breve", ogg["nome"])
    if nome:
        _ombra(d, (lato - 18 * u, 18 * u), nome, font(22 * u, True), ancora="ra")
    # barra di scala
    primi = 1.0 if g.n * g.scala >= 300 else 0.5
    if g.n * g.scala < 120:
        primi = 10 / 60
    lpx = primi * 60 / g.scala * lato / g.n
    x0, y0 = 22 * u, lato - 30 * u
    d.line([(x0, y0), (x0 + lpx, y0)], fill=(0, 0, 0), width=int(7 * u))
    d.line([(x0, y0), (x0 + lpx, y0)], fill=(255, 255, 255), width=int(3 * u))
    etichetta = f"{primi:g}′" if primi >= 0.5 else f"{primi * 60:.0f}″"
    _ombra(d, (x0 + lpx / 2, y0 - 8 * u), etichetta, font(18 * u), ancora="ms")
    # Nord in alto, Est a sinistra
    cx, cy, L = x0 + lpx + 70 * u, lato - 30 * u, 34 * u
    for (ex, ey, t) in ((cx, cy - L, "N"), (cx - L, cy, "E")):
        d.line([(cx, cy), (ex, ey)], fill=(0, 0, 0), width=int(5 * u))
        d.line([(cx, cy), (ex, ey)], fill=(255, 255, 255), width=int(2 * u))
        _ombra(d, (ex + (0 if t == "N" else -10 * u), ey - (10 * u if t == "N" else 0)), t, font(17 * u, True), ancora="mm")
    _ombra(d, (lato - 14 * u, lato - 12 * u), FIRMA, font(17 * u), (235, 235, 235), ancora="rs")
    return img


def _pixel_fotogramma(g, x, y, lato):
    return (x + 0.5) * lato / g.n, (g.n - (y + 0.5)) * lato / g.n


def colore_velocita(t):
    """0 = lento (ciano) … 0,5 giallo … 1 = veloce (rosso)."""
    tappe = [(0.0, (60, 220, 255)), (0.5, (255, 235, 80)), (1.0, (255, 70, 60))]
    for (a, ca), (b, cb) in zip(tappe, tappe[1:]):
        if t <= b:
            w = (t - a) / (b - a)
            return tuple(int(ca[k] + w * (cb[k] - ca[k])) for k in range(3)) + (255,)
    return tappe[-1][1] + (255,)


def frecce_da_disegnare(fr, n_max=250):
    """Al massimo n_max frecce, distribuite su tutta la nebulosa (nel CSV ci sono tutte)."""
    if len(fr) <= n_max:
        return fr
    passo = len(fr) / n_max
    return [fr[int(k * passo)] for k in range(n_max)]


def disegna_frecce(img, g, ris, lato, esagera=3.0, trasparente=False):
    """Frecce dei filamenti (lunghezza ×esagera) colorate per velocità; centro dell'espansione."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img, "RGBA")
    u = lato / 800.0
    fr = frecce_da_disegnare(ris.get("frecce") or [])
    vmax = max([f["v_kms"] for f in fr] + [1.0])
    for f in fr:
        x0, y0 = _pixel_fotogramma(g, f["x0"], f["y0"], lato)
        x1, y1 = _pixel_fotogramma(g, f["x"], f["y"], lato)
        xe, ye = x0 + (x1 - x0) * esagera, y0 + (y1 - y0) * esagera
        t = min(f["v_kms"] / vmax, 1.0)
        col = colore_velocita(t)
        d.line([(x0, y0), (xe, ye)], fill=(0, 0, 0, 220), width=max(2, int(6 * u)))
        d.line([(x0, y0), (xe, ye)], fill=col, width=max(1, int(3 * u)))
        ang = math.atan2(ye - y0, xe - x0)
        p = 11 * u
        punta = [(xe, ye), (xe - p * math.cos(ang - 0.45), ye - p * math.sin(ang - 0.45)),
                 (xe - p * math.cos(ang + 0.45), ye - p * math.sin(ang + 0.45))]
        d.polygon(punta, fill=col)
    if "centro_x" in ris:
        cx, cy = _pixel_fotogramma(g, ris["centro_x"], ris["centro_y"], lato)
        r = 9 * u
        d.line([(cx - r, cy), (cx + r, cy)], fill=(255, 80, 80, 255), width=max(1, int(3 * u)))
        d.line([(cx, cy - r), (cx, cy + r)], fill=(255, 80, 80, 255), width=max(1, int(3 * u)))
    if not trasparente:
        _ombra(d, (lato / 2, lato - 80 * u), f"frecce ×{esagera:g}: movimento in {num(ris['anni'], 0)} anni",
               font(19 * u, True), (255, 230, 160), ancora="ms")
        _ombra(d, (lato / 2, lato - 56 * u), "colore: ciano = più lento, rosso = più veloce",
               font(16 * u), (230, 230, 230), ancora="ms")
    return img


def disegna_traccia(img, g, ris, lato, trasparente=False):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img, "RGBA")
    u = lato / 800.0
    pts = [_pixel_fotogramma(g, p["x"], p["y"], lato) for p in ris["punti"]]
    if len(pts) >= 2:
        d.line(pts, fill=(255, 220, 120, 220), width=max(1, int(2.5 * u)))
    for p, (x, y) in zip(ris["punti"], pts):
        r = 13 * u
        d.ellipse([x - r, y - r, x + r, y + r], outline=(120, 220, 255, 255), width=max(1, int(2.5 * u)))
        _ombra(d, (x + 18 * u, y), testo_anno(p["anno"], 0), font(18 * u, True), (120, 220, 255), ancora="lm")
    return img


def scala_immagine(v, s, cx, cy):
    """Immagine [0,1] ingrandita di s attorno a (cx, cy) (per l'animazione dell'espansione)."""
    n = v.shape[0]
    ys, xs = np.mgrid[0:n, 0:n].astype(float)
    out = ndi.map_coordinates(v, [cy + (ys - cy) / s, cx + (xs - cx) / s], order=1, mode="nearest", prefilter=False)
    return out.astype(DTYPE)


def crea_fotogrammi(lavoro, ris, lato=800, tenuta_ms=1400, n_transizione=14, ms_transizione=70):
    """Lista di (immagine PIL RGB, durata in ms). Tra un'epoca e la successiva: per
    l'espansione la nebulosa si ingrandisce col modello misurato, altrimenti dissolvenza."""
    from PIL import Image
    g, info, vista, ogg = lavoro["griglia"], lavoro["info"], lavoro["vista"], lavoro["ogg"]
    x_ray = all(i["raggi_x"] for i in info)
    anni = [i["epoca"]["anno"] for i in info]
    modello = None
    if ris and ris.get("tipo") == "espansione" and ris.get("anno_zero") is not None:
        modello = (ris["anno_zero"], ris["centro_x"], ris["centro_y"])

    def foto(v, titolo, sotto):
        im = Image.fromarray(colora(v, x_ray)).resize((lato, lato), Image.LANCZOS)
        return disegna_cornice(im, ogg, g, titolo, sotto, lato)

    def sotto(i):
        e = info[i]["epoca"]
        return " · ".join(x for x in (e["etichetta"], e.get("banda")) if x)

    appross = {i["epoca"]["anno"]: i["epoca"].get("anno_approssimato") for i in info}
    titolo_epoca = (lambda a: testo_mese(a)) if x_ray else (lambda a: ("≈ " if appross.get(a) else "") + testo_anno(a, 0))
    nebulose = stelle_v = None
    if modello:                                   # le stelle restano ferme, si ingrandisce solo la nebulosa
        mst = np.zeros(vista[0].shape, bool)
        for v in vista:
            mst |= maschera_stelle(v, 2.5)
        nebulose = [togli_stelle(v, mst) for v in vista]
        stelle_v = [np.clip(v - nb, 0, None) for v, nb in zip(vista, nebulose)]
    out = []
    for i in range(len(vista)):
        out.append((foto(vista[i], titolo_epoca(anni[i]), sotto(i)), tenuta_ms))
        if i == len(vista) - 1:
            break
        for k in range(1, n_transizione + 1):
            u = k / (n_transizione + 1)
            t = anni[i] + u * (anni[i + 1] - anni[i])
            if modello:
                t0, cx, cy = modello
                a = scala_immagine(nebulose[i], (t - t0) / (anni[i] - t0), cx, cy)
                b = scala_immagine(nebulose[i + 1], (t - t0) / (anni[i + 1] - t0), cx, cy)
                v = np.clip((1 - u) * a + u * b + (1 - u) * stelle_v[i] + u * stelle_v[i + 1], 0, 1)
                titolo = f"≈ {testo_anno(t, 0)}"
            else:
                v = (1 - u) * vista[i] + u * vista[i + 1]
                titolo = f"→ {titolo_epoca(anni[i + 1])}"
            out.append((foto(v, titolo, "passaggio interpolato" if modello else "dissolvenza"), ms_transizione))
    if ris and ris.get("tipo") == "espansione" and ris.get("frecce"):
        im = foto(vista[-1], titolo_epoca(anni[-1]), sotto(len(vista) - 1))
        out.append((disegna_frecce(im, g, ris, lato), 3000))
    if ris and ris.get("tipo") == "moto_proprio":
        im = foto(vista[-1], titolo_epoca(anni[-1]), sotto(len(vista) - 1))
        out.append((disegna_traccia(im, g, ris, lato), 3000))
    return out


def salva_gif(fotogrammi, percorso, lato=600):
    from PIL import Image
    imm, durate = [], []
    for im, ms in fotogrammi:
        imm.append(im.resize((lato, lato), Image.LANCZOS).quantize(colors=256, method=Image.Quantize.MEDIANCUT))
        durate.append(int(ms))
    tmp = Path(percorso).with_suffix(".tmp.gif")
    imm[0].save(tmp, save_all=True, append_images=imm[1:], duration=durate, loop=0, disposal=1)
    os.replace(tmp, percorso)
    return Path(percorso)


def trova_ffmpeg():
    for c in (shutil.which("ffmpeg"), "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return c
    return None


def salva_mp4(fotogrammi, percorso, fps=25):
    """MP4 (H.264) con ffmpeg; restituisce il percorso o None se ffmpeg manca."""
    ff = trova_ffmpeg()
    if not ff:
        return None
    with tempfile.TemporaryDirectory(prefix="prima_e_dopo_") as tmp:
        k = 0
        for im, ms in fotogrammi:
            for _ in range(max(1, round(ms / 1000 * fps))):
                im.save(os.path.join(tmp, f"f{k:05d}.png"), compress_level=1)
                k += 1
        uscita = Path(percorso).with_suffix(".tmp.mp4")
        cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.png"),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               "-metadata", f"comment={COPYRIGHT_ASCII} - {NOME_PROGRAMMA} {VERSIONE}", str(uscita)]
        r = subprocess.run(cmd, capture_output=True, text=True, env=ambiente_esterno(), timeout=900)
        if r.returncode != 0 or not uscita.exists():
            raise RuntimeError("ffmpeg: " + (r.stderr or "")[-300:])
        os.replace(uscita, percorso)
    return Path(percorso)


def _jpeg_b64(im, q=90):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _png_b64(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def immagini_epoche(lavoro, lato=800, con_anno=True):
    from PIL import Image
    g, info, vista, ogg = lavoro["griglia"], lavoro["info"], lavoro["vista"], lavoro["ogg"]
    x_ray = all(i["raggi_x"] for i in info)
    out = []
    for v, i in zip(vista, info):
        e = i["epoca"]
        im = Image.fromarray(colora(v, x_ray)).resize((lato, lato), Image.LANCZOS)
        if not con_anno:
            out.append(disegna_cornice(im, dict(ogg, breve=""), g, "", "", lato))
            continue
        out.append(disegna_cornice(im, ogg, g, testo_mese(e["anno"]) if x_ray else
                                   ("≈ " if e.get("anno_approssimato") else "") + testo_anno(e["anno"], 0),
                                   " · ".join(x for x in (e["etichetta"], e.get("banda")) if x), lato))
    return out


def sovrapposizione(lavoro, ris, lato=800):
    """Livello trasparente con frecce o traccia (per la pagina e l'anteprima)."""
    from PIL import Image
    if not ris:
        return None
    im = Image.new("RGBA", (lato, lato), (0, 0, 0, 0))
    if ris["tipo"] == "espansione" and ris.get("frecce"):
        return disegna_frecce(im, lavoro["griglia"], ris, lato, trasparente=True)
    if ris["tipo"] == "moto_proprio":
        return disegna_traccia(im, lavoro["griglia"], ris, lato, trasparente=True)
    return None


PAGINA = r"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITOLO__ – Prima e dopo</title>
<style>
:root{--fs:19px}
body{margin:0;background:#0d0f14;color:#e8e6e1;font-family:"DejaVu Sans",Arial,sans-serif;font-size:var(--fs)}
header{padding:14px 22px;display:flex;flex-wrap:wrap;gap:14px;align-items:center;border-bottom:1px solid #2a2f3a}
h1{font-size:1.45em;margin:0;color:#ffd678;font-weight:700}
.sp{flex:1}
button,select{font-size:1em;padding:7px 14px;border-radius:8px;border:1px solid #3d4556;background:#1c212c;color:#e8e6e1;cursor:pointer}
button.on{background:#ffd678;color:#111;border-color:#ffd678}
main{display:flex;flex-wrap:wrap;gap:22px;padding:18px 22px}
#vista{position:relative;width:min(88vh,92vw,900px);aspect-ratio:1;background:#000;border-radius:6px;overflow:hidden;user-select:none}
#vista img{position:absolute;inset:0;width:100%;height:100%}
#linea{position:absolute;top:0;bottom:0;width:3px;background:#ffd678;cursor:ew-resize;box-shadow:0 0 6px #000}
.eti{position:absolute;top:1.6%;color:#ffd678;font-weight:700;font-size:min(5.5vh,46px);text-shadow:0 0 4px #000,2px 2px 3px #000;pointer-events:none}
.eti small{display:block;color:#fff;font-weight:400;font-size:.42em;margin-top:.15em}
#e1{left:2.2%}#e2{right:2.2%;text-align:right;display:none}
#comandi{flex:1;min-width:300px;max-width:640px}
.riga{margin:12px 0}
input[type=range]{width:100%;height:30px}
label{cursor:pointer}
pre{white-space:pre-wrap;font-family:inherit;line-height:1.45;background:#151922;padding:14px;border-radius:8px;font-size:.9em}
.anni{display:flex;justify-content:space-between;font-size:.85em;color:#b8b4aa}
footer{padding:10px 22px 18px;color:#8b8f99;font-size:.8em}
</style></head><body>
<header><h1>__TITOLO__</h1><span class="sp"></span>
<button data-m="dissolvenza" class="on">Cursore nel tempo</button>
<button data-m="tendina">Tendina prima/dopo</button>
<button data-m="lampeggio">Lampeggio</button>
<button id="piu">A+</button><button id="meno">A−</button></header>
<main>
<div id="vista"><img id="a"><img id="b"><img id="sopra" style="display:none"><div id="linea" style="display:none"></div>
<div class="eti" id="e1"></div><div class="eti" id="e2"></div></div>
<div id="comandi">
<div id="c_diss"><div class="riga"><input type="range" id="t" min="0" max="1" step="0.005" value="0"></div>
<div class="anni" id="anni"></div>
<div class="riga"><button id="play">▶ Riproduci</button></div></div>
<div id="c_due" style="display:none"><div class="riga">Prima: <select id="s1"></select> &nbsp; Dopo: <select id="s2"></select></div>
<div class="riga" id="c_vel" style="display:none">Velocità del lampeggio <input type="range" id="vel" min="150" max="1500" value="600"></div>
<div class="riga" id="c_tend">Trascina la linea gialla sull'immagine, oppure: <input type="range" id="tend" min="0" max="100" value="50"></div></div>
<div class="riga" id="c_sopra" style="display:none"><label><input type="checkbox" id="frecce" checked> __SOPRA__</label></div>
<pre id="testo"></pre>
</div></main>
<footer>__FIRMA__ · __PROGRAMMA__ · immagini: __CREDITI__</footer>
<script>
const D=__DATI__;
const A=document.getElementById('a'),B=document.getElementById('b'),S=document.getElementById('sopra'),L=document.getElementById('linea');
const T=document.getElementById('t'),V=document.getElementById('vista');
let modo='dissolvenza',timer=null,gioca=null,fs=19;
T.max=D.img.length-1;
document.getElementById('anni').innerHTML=D.anni.map(a=>'<span>'+a+'</span>').join('');
document.getElementById('testo').textContent=D.testo;
['s1','s2'].forEach((id,k)=>{const s=document.getElementById(id);D.anni.forEach((a,i)=>{const o=document.createElement('option');o.value=i;o.textContent=a+' – '+D.nomi[i];s.appendChild(o)});s.value=k?D.img.length-1:0;s.onchange=aggiorna});
if(D.sopra){S.src='data:image/png;base64,'+D.sopra;document.getElementById('c_sopra').style.display='block'}
const src=i=>'data:image/jpeg;base64,'+D.img[i];
const E1=document.getElementById('e1'),E2=document.getElementById('e2');
const eti=(i,testo)=>testo+'<small>'+D.nomi[i]+'</small>';
function aggiorna(){
 clearInterval(timer);timer=null;A.style.clipPath='';B.style.clipPath='';L.style.display='none';E2.style.display='none';
 if(modo==='dissolvenza'){const t=+T.value,i=Math.floor(t),j=Math.min(i+1,D.img.length-1),u=t-i;
  A.src=src(i);B.src=src(j);B.style.opacity=u;
  if(u<0.04||u>0.96){E1.innerHTML=eti(u>0.5?j:i,D.anni[u>0.5?j:i])}
  else{const a=D.valori[i]+u*(D.valori[j]-D.valori[i]);E1.innerHTML=(D.mesi?D.anni[i]+' → '+D.anni[j]:'≈ '+Math.round(a))+'<small>dissolvenza</small>'}}
 else{const i=+document.getElementById('s1').value,j=+document.getElementById('s2').value;A.src=src(i);B.src=src(j);
  if(modo==='tendina'){B.style.opacity=1;const p=+document.getElementById('tend').value;B.style.clipPath='inset(0 0 0 '+p+'%)';L.style.display='block';L.style.left='calc('+p+'% - 1px)';
   E1.innerHTML=eti(i,D.anni[i]);E2.innerHTML=eti(j,D.anni[j]);E2.style.display='block';}
  else{let vis=false;B.style.opacity=0;E1.innerHTML=eti(i,D.anni[i]);
   timer=setInterval(()=>{vis=!vis;B.style.opacity=vis?1:0;E1.innerHTML=vis?eti(j,D.anni[j]):eti(i,D.anni[i])},+document.getElementById('vel').value);}}
 S.style.display=(D.sopra&&document.getElementById('frecce').checked)?'block':'none';
}
document.querySelectorAll('header button[data-m]').forEach(b=>b.onclick=()=>{modo=b.dataset.m;
 document.querySelectorAll('header button[data-m]').forEach(x=>x.classList.toggle('on',x===b));
 document.getElementById('c_diss').style.display=modo==='dissolvenza'?'block':'none';
 document.getElementById('c_due').style.display=modo==='dissolvenza'?'none':'block';
 document.getElementById('c_vel').style.display=modo==='lampeggio'?'block':'none';
 document.getElementById('c_tend').style.display=modo==='tendina'?'block':'none';aggiorna();});
T.oninput=aggiorna;document.getElementById('tend').oninput=aggiorna;document.getElementById('vel').oninput=aggiorna;
document.getElementById('frecce').onchange=aggiorna;
document.getElementById('play').onclick=function(){if(gioca){clearInterval(gioca);gioca=null;this.textContent='▶ Riproduci';return}
 this.textContent='■ Ferma';gioca=setInterval(()=>{let t=+T.value+0.01;if(t>+T.max+0.6)t=0;T.value=Math.min(t,+T.max);aggiorna()},40)};
let trascina=false;
function posa(e){const r=V.getBoundingClientRect();const x=(e.touches?e.touches[0].clientX:e.clientX)-r.left;
 document.getElementById('tend').value=Math.max(0,Math.min(100,x/r.width*100));aggiorna()}
V.addEventListener('mousedown',e=>{if(modo==='tendina'){trascina=true;posa(e)}});
window.addEventListener('mousemove',e=>{if(trascina)posa(e)});window.addEventListener('mouseup',()=>trascina=false);
V.addEventListener('touchstart',e=>{if(modo==='tendina'){posa(e)}},{passive:true});
V.addEventListener('touchmove',e=>{if(modo==='tendina'){posa(e)}},{passive:true});
document.getElementById('piu').onclick=()=>{fs=Math.min(34,fs+2);document.documentElement.style.setProperty('--fs',fs+'px')};
document.getElementById('meno').onclick=()=>{fs=Math.max(13,fs-2);document.documentElement.style.setProperty('--fs',fs+'px')};
aggiorna();
</script></body></html>
"""


def crediti(info):
    c = set()
    for i in info:
        f = i["epoca"].get("fonte")
        if f in ("dss1_red", "dss2_red"):
            c.add("Digitized Sky Survey (STScI/AURA, Palomar/Caltech) tramite NASA SkyView")
        elif f == "ps1_r":
            c.add("Pan-STARRS1 (STScI)")
        elif f == "chandra":
            c.add("NASA Chandra X-ray Observatory (archivio HEASARC)")
        elif f == "hubble":
            c.add("NASA/ESA Hubble Space Telescope (archivio MAST, STScI)")
        else:
            c.add("file dell'utente")
    return "; ".join(sorted(c))


def salva_pagina(lavoro, ris, testo, percorso, lato=800):
    imm = immagini_epoche(lavoro, lato)
    pulite = immagini_epoche(lavoro, lato, con_anno=False)
    sopra = sovrapposizione(lavoro, ris, lato)
    info = lavoro["info"]
    x_ray = all(i["raggi_x"] for i in info)
    dati = dict(img=[_jpeg_b64(i) for i in pulite], sopra=_png_b64(sopra) if sopra else None,
                anni=[testo_mese(i["epoca"]["anno"]) if x_ray else ("≈ " if i["epoca"].get("anno_approssimato") else "")
                      + testo_anno(i["epoca"]["anno"], 0) for i in info],
                valori=[i["epoca"]["anno"] for i in info], mesi=x_ray,
                nomi=[" · ".join(x for x in (i["epoca"]["etichetta"], i["epoca"].get("banda")) if x) for i in info],
                testo="\n".join(r for r in testo if not set(r.strip()) <= {"="} or not r.strip()))
    sopra_txt = ("Mostra le frecce del movimento (×3)" if ris and ris.get("tipo") == "espansione"
                 else "Mostra la traccia della stella")
    h = (PAGINA.replace("__TITOLO__", lavoro["ogg"]["nome"]).replace("__SOPRA__", sopra_txt)
         .replace("__FIRMA__", FIRMA).replace("__PROGRAMMA__", f"{NOME_PROGRAMMA} {VERSIONE}")
         .replace("__CREDITI__", crediti(info)).replace("__DATI__", json.dumps(dati)))
    tmp = Path(percorso).with_suffix(".tmp")
    tmp.write_text(h, encoding="utf-8")
    os.replace(tmp, percorso)
    return Path(percorso), imm, sopra


def figura_misura(lavoro, ris, percorso):
    """Figura riassuntiva della misura (PNG firmato)."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    g, info, vista = lavoro["griglia"], lavoro["info"], lavoro["vista"]
    fig = Figure(figsize=(15, 7.5), dpi=110)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(1, 2, 1)
    est = [g.n * g.scala / 120, -g.n * g.scala / 120, -g.n * g.scala / 120, g.n * g.scala / 120]   # primi
    ax.imshow(vista[-1], origin="lower", cmap="gray", extent=est, vmin=0, vmax=1)
    pr = lambda x, y: ((g.c - x) * g.scala / 60, (y - g.c) * g.scala / 60)
    ax.set_xlabel("← Est      primi d'arco      Ovest →")
    ax.set_ylabel("primi d'arco (Nord in alto)")
    ax2 = fig.add_subplot(1, 2, 2)
    if ris["tipo"] == "espansione":
        fr = frecce_da_disegnare(ris.get("frecce") or [], 400)
        if fr:
            import matplotlib.cm as cm
            v = np.array([f["v_kms"] for f in fr])
            X0 = np.array([pr(f["x0"], f["y0"]) for f in fr])
            X1 = np.array([pr(f["x"], f["y"]) for f in fr])
            q = ax.quiver(X0[:, 0], X0[:, 1], (X1 - X0)[:, 0] * 3, (X1 - X0)[:, 1] * 3, v, cmap="plasma",
                          angles="xy", scale_units="xy", scale=1, width=0.004)
            fig.colorbar(q, ax=ax, fraction=0.046, pad=0.03).set_label("velocità (km/s) a %d pc" % ris["distanza_pc"])
            rr = np.array([f["raggio_arcsec"] for f in fr])
            rad = np.array([f["radiale_arcsec"] for f in fr])
            ax2.scatter(rr, rad, c=v, cmap="plasma", s=22)
            xx = np.linspace(0, rr.max() * 1.05, 50)
            ax2.plot(xx, xx * (1 - 1 / ris["scala"]), color="#1d4ed8", lw=2,
                     label=f"espansione uniforme: +{num(ris['ingrandimento_pc'], 2)} % in {num(ris['anni'], 0)} anni")
            ax2.legend(loc="upper left")
        cx, cy = pr(ris["centro_x"], ris["centro_y"])
        ax.plot([cx], [cy], "+", color="#ff5050", ms=16, mew=2.5)
        ax.set_title(f"Frecce ×3: spostamento dei filamenti {testo_anno(ris['anno_prima'], 0)} → {testo_anno(ris['anno_dopo'], 0)}")
        ax2.set_xlabel("distanza dal centro dell'espansione (″)")
        ax2.set_ylabel(f"spostamento verso l'esterno in {num(ris['anni'], 0)} anni (″)")
        az = ris.get("anno_zero")
        ax2.set_title("Più lontano dal centro = più veloce: è un'esplosione"
                      + (f"\nanno dell'esplosione (velocità costante): {az:.0f}" if az else ""))
        ax2.grid(alpha=0.3)
    else:
        P = np.array([pr(p["x"], p["y"]) for p in ris["punti"]])
        ax.plot(P[:, 0], P[:, 1], "-o", color="#38bdf8", ms=8, mfc="none", mew=2)
        for p, (a, b) in zip(ris["punti"], P):
            ax.annotate(testo_anno(p["anno"], 0), (a, b), xytext=(8, 0), textcoords="offset points", color="#38bdf8")
        ax.set_title(f"{lavoro['ogg'].get('breve', '')}: posizione nelle varie epoche")
        t = np.array([p["anno"] for p in ris["punti"]])
        dec = np.array([p["dec"] for p in ris["punti"]])
        ax2.plot(t, (dec - dec[0]) * 3600, "o", ms=9, label="misurato")
        tt = np.linspace(t.min(), t.max(), 10)
        ax2.plot(tt, (tt - t[0]) * ris["pm_gaia_mas"][1] / 1000, "-", label="previsto da Gaia")
        ax2.set_xlabel("anno")
        ax2.set_ylabel("spostamento verso Nord (″)")
        ax2.set_title(f"moto proprio {num(ris['mu_mas'] / 1000, 2)}″/anno (Gaia {num(ris['mu_gaia_mas'] / 1000, 2)}″/anno)")
        ax2.legend()
        ax2.grid(alpha=0.3)
    fig.suptitle(lavoro["ogg"]["nome"], fontsize=15, fontweight="bold")
    fig.text(0.995, 0.005, FIRMA, ha="right", va="bottom", fontsize=9, color="0.4")
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(percorso)
    return Path(percorso)


def salva_allineate(lavoro, cartella):
    """FITS allineati sulla griglia comune (si possono aprire con AutoAstroPipe)."""
    from astropy.io import fits
    c = Path(cartella)
    c.mkdir(parents=True, exist_ok=True)
    out = []
    for a, i in zip(lavoro["grezze"], lavoro["info"]):
        e = i["epoca"]
        h = fits.Header()
        for k, v in lavoro["griglia"].intestazione().items():
            h[k] = v
        h["DATE-OBS"] = data_da_anno(e["anno"]).strftime("%Y-%m-%dT%H:%M:%S")
        h["EPOCA"] = (round(e["anno"], 4), "anno decimale")
        h["ORIGINE"] = re.sub(r"[^ -~]", "", e["etichetta"])[:60]
        h["CREATOR"] = f"{NOME_PROGRAMMA} {VERSIONE}".replace("Prima e dopo", "Prima e dopo")
        h["AUTHOR"] = AUTORE
        nome = f"allineata_{testo_anno(e['anno'], 2).replace(',', '_')}_{re.sub(r'[^A-Za-z0-9]+', '_', e['id'])}.fits"
        p = c / nome
        fits.PrimaryHDU(np.asarray(a, np.float32), h).writeto(p, overwrite=True)
        out.append(p)
    return out


def esegui(ogg, epoche, base=None, log=print, ferma=None, progresso=None, nitidezza_uguale=True,
           fa_mp4=True, lato=800):
    """Tutto il lavoro per un oggetto. Restituisce un dict con i percorsi dei risultati."""
    t0 = time.time()
    aggiorna_da_gaia(ogg, base, log, ferma)
    lavoro = prepara(ogg, epoche, base, log, ferma, progresso, nitidezza_uguale)
    ris = None
    try:
        if ogg["tipo"] == "espansione":
            ris = misura_espansione(lavoro, log, progresso)
        elif ogg["tipo"] == "moto_proprio":
            ris = misura_moto_proprio(lavoro, log)
    except Fermato:
        raise
    except Exception as e:
        log(f"Misura non riuscita: {type(e).__name__}: {e}")
        ris = None
    c = cartella_oggetto(ogg, base)
    c.mkdir(parents=True, exist_ok=True)
    lav = c / CARTELLA_LAVORO
    lav.mkdir(exist_ok=True)
    testo = righe_risultati(ogg, lavoro, ris)
    if progresso:
        progresso(0.88, "creo i fotogrammi")
    fot = crea_fotogrammi(lavoro, ris, lato)
    chiave = ogg["chiave"]
    fatti = {}
    if progresso:
        progresso(0.91, "salvo la GIF")
    fatti["gif"] = salva_gif(fot, c / f"{chiave}.gif")
    if progresso:
        progresso(0.93, "salvo la pagina con il cursore")
    pag, imm, sopra = salva_pagina(lavoro, ris, testo, c / f"{chiave}_confronto.html", lato)
    fatti["pagina"] = pag
    for k, im in enumerate(imm):
        im.save(lav / f"epoca_{k:02d}.png")
    for vecchio in lav.glob("epoca_*.png"):
        if int(re.sub(r"\D", "", vecchio.stem) or 0) >= len(imm):
            vecchio.unlink()
    if sopra is not None:
        sopra.save(lav / "sopra.png")
    elif (lav / "sopra.png").exists():
        (lav / "sopra.png").unlink()
    if ris:
        fatti["figura"] = figura_misura(lavoro, ris, c / f"{chiave}_misura.png")
        if ris["tipo"] == "espansione" and ris.get("frecce"):
            import csv
            with open(c / f"{chiave}_frecce.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["ra_deg", "dec_deg", "distanza_dal_centro_arcsec", "spostamento_arcsec",
                            "spostamento_radiale_arcsec", "moto_arcsec_anno", "velocita_kms", "anno_zero", "correlazione"])
                for q in ris["frecce"]:
                    w.writerow([f"{q['ra']:.6f}", f"{q['dec']:.6f}", f"{q['raggio_arcsec']:.2f}", f"{q['spost_arcsec']:.3f}",
                                f"{q['radiale_arcsec']:.3f}", f"{q['mu_arcsec_anno']:.5f}", f"{q['v_kms']:.0f}",
                                f"{q['anno_zero']:.0f}" if q["anno_zero"] else "", f"{q['ncc']:.3f}"])
            fatti["csv"] = c / f"{chiave}_frecce.csv"
    if fa_mp4:
        if progresso:
            progresso(0.95, "salvo l'MP4")
        try:
            m = salva_mp4(fot, c / f"{chiave}.mp4")
            if m:
                fatti["mp4"] = m
            else:
                log("MP4 non creato: manca ffmpeg (sudo apt install ffmpeg). GIF e pagina ci sono.")
        except Exception as e:
            log(f"MP4 non creato: {e}")
    try:
        fatti["allineate"] = salva_allineate(lavoro, c / "allineate")
    except Exception as e:
        log(f"FITS allineati non salvati: {e}")
    (c / f"{chiave}_risultati.txt").write_text("\n".join(testo) + "\n", encoding="utf-8")
    js = dict(oggetto=ogg["chiave"], nome=ogg["nome"], versione=VERSIONE, data=datetime.now().strftime("%Y-%m-%d %H:%M"),
              griglia=dict(ra=lavoro["griglia"].ra0, dec=lavoro["griglia"].dec0, scala_arcsec=lavoro["griglia"].scala,
                           lato=lavoro["griglia"].n),
              epoche=[dict(etichetta=i["epoca"]["etichetta"], anno=i["epoca"]["anno"], file=i["epoca"].get("file"),
                           allineamento=i.get("allineamento"), fwhm_arcsec=i.get("fwhm_arcsec"),
                           anno_approssimato=i["epoca"].get("anno_approssimato", False)) for i in lavoro["info"]],
              misura=ris)
    (c / FILE_RISULTATI).write_text(json.dumps(js, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    fatti["testo"] = c / f"{chiave}_risultati.txt"
    log(f"Fatto in {time.time() - t0:.0f} s. Risultati in {c}")
    if progresso:
        progresso(1.0, "fatto")
    return dict(cartella=c, file=fatti, testo=testo, misura=ris, n_epoche=len(lavoro["info"]),
                fotogrammi=len(fot))


def leggi_risultati(ogg, base=None):
    c = cartella_oggetto(ogg, base)
    try:
        js = json.loads((c / FILE_RISULTATI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lav = c / CARTELLA_LAVORO
    js["immagini"] = sorted(str(p) for p in lav.glob("epoca_*.png"))
    js["sopra"] = str(lav / "sopra.png") if (lav / "sopra.png").exists() else None
    js["cartella"] = str(c)
    for k, est in (("gif", ".gif"), ("mp4", ".mp4"), ("pagina", "_confronto.html"), ("figura", "_misura.png"),
                   ("testo", "_risultati.txt")):
        p = c / f"{ogg['chiave']}{est}"
        js[k] = str(p) if p.exists() else None
    return js


# =============================================================================
# DIAGNOSTICA DELLA RETE
# =============================================================================
def diagnostica(log=print):
    m1 = oggetto("M1_ottico")
    prove = []

    def prova(nome, f):
        t0 = time.time()
        try:
            r = f()
            log(f"[ok] {nome}: {r} ({time.time() - t0:.0f} s)")
            prove.append(True)
        except Exception as e:
            log(f"[ERRORE] {nome}: {type(e).__name__} {str(e)[:160]} ({time.time() - t0:.0f} s)")
            prove.append(False)

    def skyview():
        q = {"Position": f"{m1['ra']},{m1['dec']}", "Survey": "DSS1 Red", "Pixels": "100", "Size": "0.05",
             "Return": "FITS"}
        b = scarica(URL_SKYVIEW + "?" + urllib.parse.urlencode(q), 120)
        h = intestazione_grezza(b) if e_fits_bytes(b) else {}
        if not h:
            raise ValueError("non è un FITS: " + b[:80].decode("latin-1"))
        return f"FITS {h.get('NAXIS1')}×{h.get('NAXIS2')}, CTYPE1 {h.get('CTYPE1')}, DATE-OBS {h.get('DATE-OBS', '–')}"
    prova("SkyView DSS1 rosso", skyview)
    prova("lettura della data «1951-11-07T09:60:00»",
          lambda: f"{leggi_data_testo('1951-11-07T09:60:00'):.4f}")
    for s in ("poss1_red", "poss2ukstu_red"):
        prova(f"STScI DSS data della lastra ({s})",
              lambda s=s: "anno {0}, DATE-OBS {1}, lastra {2}".format(*data_lastra_stsci(m1["ra"], m1["dec"], s)))

    for s_ in ("poss2ukstu_red",):
        prova(f"ESO DSS data della lastra ({SURVEY_ESO[s_]})",
              lambda s_=s_: "anno {0}, DATE-OBS {1}, lastra {2}".format(*data_lastra_eso(m1["ra"], m1["dec"], s_)))

    def ps1():
        n = nomi_ps1(m1["ra"], m1["dec"], "r")
        d = n.get("r", {})
        q = {"red": d.get("filename"), "ra": m1["ra"], "dec": m1["dec"], "size": 240, "format": "fits",
             "output_size": 60}
        b = scarica(URL_PS1_TAGLIO + "?" + urllib.parse.urlencode(q), 120)
        h = intestazione_grezza(b) if e_fits_bytes(b) else {}
        date = {k: v for k, v in h.items() if "MJD" in k or "DATE" in k or k.startswith("EXP")}
        return (f"{d.get('shortname', '?')}, mjd {d.get('mjd', '–')}; ritaglio 240 px → {h.get('NAXIS1')} px, "
                f"CDELT1 {h.get('CDELT1', h.get('CD1_1'))}, BSOFTEN {'sì' if 'BSOFTEN' in h else 'no'}; "
                f"anno dall'intestazione {testo_anno(anno_da_intestazione(h), 2)}; date {date}")
    prova("Pan-STARRS r (nomi + ritaglio)", ps1)

    def hubble():
        st = {}
        eta = oggetto("EtaCar_Hubble")
        try:
            oss = osservazioni_hubble(eta, statistiche=st)
        finally:
            if st:
                log(f"     MAST: {st.get('righe')} righe; colonne {st.get('colonne', [])[:40]}")
                for e in st.get("esempi", []):
                    log("     riga: " + str({k: v for k, v in e.items() if v not in ('', None)})[:700])
                log(f"     scartate: {st.get('scarti')}")
        sc = scegli_hubble(oss, [x.upper() for x in eta["filtri_hubble"]], 6)
        if not sc:
            raise ValueError("nessuna immagine utilizzabile (vedi sopra)")
        pr = mast("Mast.Caom.Products", {"obsid": sc[0]["obsid"]})
        uri = scegli_prodotto_hubble(pr)
        return (f"{len(oss)} immagini nei filtri; scelte {len(sc)} in {sc[0]['filtro']} "
                f"({', '.join(testo_anno(o['anno'], 1) for o in sc)}); prodotto: {uri or 'NESSUNO'} "
                f"(prodotti: {len(pr)})")
    prova("MAST Hubble (Eta Carinae)", hubble)

    def chandra():
        st = {}
        try:
            oss = osservazioni_chandra(oggetto("M1_raggiX"), statistiche=st)
        finally:
            if st:
                log(f"     HEASARC: formato {st.get('formato')!r}, {st.get('righe')} righe grezze; "
                    f"colonne {st.get('colonne')}")
                for e in st.get("esempi", []):
                    log("     riga: " + str({k: v for k, v in e.items() if v not in ('', None)})[:900])
                if st.get("scarti"):
                    log(f"     scartate: {st['scarti']}")
        sc = scegli_distribuite(oss, 8)
        if not sc:
            raise ValueError("nessuna osservazione utilizzabile (vedi le righe sopra)")
        o = sc[0]
        url = URL_CHANDRA_FTP.format(d=o["obsid"] % 10, obsid=o["obsid"])
        indice = scarica(url, 60).decode("utf-8", "replace")
        nomi = re.findall(r'href="([^"?/]*cntr_img2\.fits(?:\.gz)?)"', indice)
        return (f"{len(oss)} osservazioni ACIS, scelte {len(sc)} ({testo_anno(sc[0]['anno'], 1)}–"
                f"{testo_anno(sc[-1]['anno'], 1)}); ObsID {o['obsid']}: {nomi[0] if nomi else 'cntr_img2 NON trovato'}")
    prova("HEASARC Chandra (chanmaster + archivio)", chandra)
    ff = trova_ffmpeg()
    log(f"[{'ok' if ff else '--'}] ffmpeg per l'MP4: {ff or 'non installato (sudo apt install ffmpeg)'}")
    return all(prove)
