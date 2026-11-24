# -*- coding: utf-8 -*-
"""Dati simulati per l'autotest di Prima e dopo (senza rete).
© 2026 Edoardo Battistel"""
import math
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

import motore_pd as M


def _scrivi_fits(percorso, dati, h):
    from astropy.io import fits
    hd = fits.Header()
    for k, v in h.items():
        hd[k] = v
    fits.PrimaryHDU(np.asarray(dati, np.float32), hd).writeto(percorso, overwrite=True)


def _filamenti_base(n, scala, rng, a_arcmin, b_arcmin, pa):
    """Nebulosa 'vera' all'anno di riferimento, su una griglia fine n×n (pixel da 'scala' ″)."""
    img = np.zeros((n, n), np.float32)
    c = (n - 1) / 2
    t = math.radians(pa)
    for _ in range(260):                        # filamenti come passeggiate casuali dentro l'ellisse
        r = math.sqrt(rng.random()) * 0.95
        ang = rng.random() * 2 * math.pi
        u, v = r * math.cos(ang) * a_arcmin, r * math.sin(ang) * b_arcmin
        e, nn = u * math.sin(t) + v * math.cos(t), u * math.cos(t) - v * math.sin(t)
        x, y = c - e * 60 / scala, c + nn * 60 / scala
        d = rng.random() * 2 * math.pi
        for _ in range(int(rng.integers(20, 70))):
            d += rng.normal(0, 0.25)
            x += math.cos(d) * 1.2
            y += math.sin(d) * 1.2
            if 0 <= x < n and 0 <= y < n:
                img[int(y), int(x)] += 1.0
    img = ndi.gaussian_filter(img, 1.4) * 6
    yy, xx = np.mgrid[0:n, 0:n]
    dx, dy = -(xx - c) * scala / 60, (yy - c) * scala / 60
    uu = dx * math.sin(t) + dy * math.cos(t)
    vv = dx * math.cos(t) - dy * math.sin(t)
    q = (uu / a_arcmin) ** 2 + (vv / b_arcmin) ** 2
    img += 0.35 * np.exp(-q * 2.5)               # alone diffuso
    return img


def crea_m1(cartella, rng=None, anno_zero=1130.0, saturazione=(3.0, 4.0)):
    """Tre epoche di una nebulosa che si espande dal 'anno_zero' (velocità costante)."""
    rng = rng or np.random.default_rng(3)
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    ogg = M.oggetto("M1_ottico")
    ra0, dec0 = ogg["ra"], ogg["dec"]
    fine = M.Griglia(ra0, dec0, 0.5, 2000)
    base = _filamenti_base(fine.n, 0.5, rng, 3.6, 2.5, 130.0)
    rif = 2012.0
    stelle_ra = ra0 + (rng.random(500) - 0.5) * 0.30 / math.cos(math.radians(dec0))
    stelle_dec = dec0 + (rng.random(500) - 0.5) * 0.30
    stelle_f = 10 ** rng.uniform(0.3, 2.5, 500)
    epoche = [  # anno, scala ″/px, sigma PSF ″, rotazione °, errore WCS ″, nome, non linearità
        (1954.2, 1.7, 1.6, 0.6, (2.0, -1.5), "DSS1_sim", saturazione[0]),
        (1991.7, 1.0, 1.2, -0.4, (-1.0, 1.2), "DSS2_sim", saturazione[1]),
        (2012.0, 1.0, 0.6, 0.0, (0.2, 0.1), "PS1_sim", None),
    ]
    file = []
    for anno, sc, psf, rot, err, nome, nonlin in epoche:
        n = int(16 * 60 / sc)
        h = {"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
             "CRVAL1": ra0 + err[0] / 3600 / math.cos(math.radians(dec0)), "CRVAL2": dec0 + err[1] / 3600,
             "CRPIX1": (n + 1) / 2, "CRPIX2": (n + 1) / 2}
        cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        s = sc / 3600
        h.update({"CD1_1": -s * cr, "CD1_2": s * sr, "CD2_1": s * sr, "CD2_2": s * cr})
        from astropy.wcs import WCS
        w = WCS(h)
        ys, xs = np.mgrid[0:n, 0:n].astype(float)
        ra, dec = w.all_pix2world(xs.ravel(), ys.ravel(), 0)
        # posizione vera (errore WCS: il cielo vero è spostato rispetto a quello dichiarato)
        ra_v = ra - err[0] / 3600 / math.cos(math.radians(dec0))
        dec_v = dec - err[1] / 3600
        fx, fy = fine.world2pix(ra_v, dec_v)
        k = (anno - anno_zero) / (rif - anno_zero)
        img = ndi.map_coordinates(base, [fine.c + (fy - fine.c) / k, fine.c + (fx - fine.c) / k],
                                  order=1, cval=0).reshape(n, n)
        img = ndi.gaussian_filter(img, psf / sc)
        px, py = w.all_world2pix(stelle_ra + err[0] / 3600 / math.cos(math.radians(dec0)) * 0, stelle_dec, 0)
        # le stelle: posizioni vere -> pixel con il WCS 'vero' (cioè senza errore)
        px, py = w.all_world2pix(stelle_ra + err[0] / 3600 / math.cos(math.radians(dec0)),
                                 stelle_dec + err[1] / 3600, 0)
        sig = psf / sc
        for x, y, f in zip(px, py, stelle_f):
            xi, yi = int(x), int(y)
            if 8 <= xi < n - 8 and 8 <= yi < n - 8:
                yy, xx = np.mgrid[yi - 8:yi + 9, xi - 8:xi + 9]
                img[yi - 8:yi + 9, xi - 8:xi + 9] += f / (2 * math.pi * sig ** 2) * np.exp(
                    -((xx - x) ** 2 + (yy - y) ** 2) / (2 * sig ** 2))
        img = img + 0.05 + rng.normal(0, 0.012, img.shape)
        if nonlin:
            img = (1 - np.exp(-img * nonlin)) * 20000 + 1000        # lastra fotografica: satura
        else:
            img = img * 900
        h["DATE-OBS"] = M.data_da_anno(anno).strftime("%Y-%m-%dT%H:%M:%S")
        h["TELESCOP"] = nome
        p = cartella / f"{nome}.fits"
        _scrivi_fits(p, img, h)
        file.append(p)
    return file


def crea_barnard(cartella, rng=None):
    rng = rng or np.random.default_rng(5)
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    ogg = M.oggetto("Barnard")
    ra0, dec0 = M.centro_campo(ogg)
    st_ra = ra0 + (rng.random(400) - 0.5) * 0.3 / math.cos(math.radians(dec0))
    st_dec = dec0 + (rng.random(400) - 0.5) * 0.3
    st_f = 10 ** rng.uniform(0.5, 2.5, 400)
    file = []
    for anno, sc, psf, err, nome in ((1951.6, 1.7, 1.8, (1.5, -1.0), "B_DSS1"), (1993.4, 1.0, 1.2, (-0.8, 0.6), "B_DSS2"),
                                     (2012.0, 1.0, 0.6, (0.0, 0.0), "B_PS1")):
        n = int(18 * 60 / sc)
        h = {"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRVAL1": ra0, "CRVAL2": dec0,
             "CRPIX1": (n + 1) / 2, "CRPIX2": (n + 1) / 2, "CDELT1": -sc / 3600, "CDELT2": sc / 3600}
        from astropy.wcs import WCS
        w = WCS(h)
        img = np.full((n, n), 0.05) + rng.normal(0, 0.01, (n, n))
        bra, bdec = M.posizione_al_tempo(ogg, anno)
        tutte = list(zip(st_ra, st_dec, st_f)) + [(bra, bdec, 600.0)]
        sig = psf / sc
        for ra, dec, f in tutte:
            x, y = w.all_world2pix([ra + err[0] / 3600], [dec + err[1] / 3600], 0)
            x, y = float(x[0]), float(y[0])
            xi, yi = int(x), int(y)
            if 10 <= xi < n - 10 and 10 <= yi < n - 10:
                yy, xx = np.mgrid[yi - 10:yi + 11, xi - 10:xi + 11]
                img[yi - 10:yi + 11, xi - 10:xi + 11] += f / (2 * math.pi * sig ** 2) * np.exp(
                    -((xx - x) ** 2 + (yy - y) ** 2) / (2 * sig ** 2))
        h["DATE-OBS"] = M.data_da_anno(anno).strftime("%Y-%m-%d")
        h["TELESCOP"] = nome
        p = cartella / f"{nome}.fits"
        _scrivi_fits(p, img * 1000, h)
        file.append(p)
    return file
