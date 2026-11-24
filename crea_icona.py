#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Icona di Prima e dopo: la stessa nebulosa divisa in due da una linea dorata,
a sinistra com'era (lastra fotografica seppia, più piccola), a destra com'è
(colori moderni, più grande, con le frecce dell'espansione). Fondo blu petrolio.
© 2026 Edoardo Battistel"""
import math
import random
from PIL import Image, ImageDraw, ImageFilter

LATO = 512
S = 4


def nebulosa(L, scala, colori, seme, grana=False):
    """Nebulosa a filamenti (ellisse inclinata) su fondo trasparente."""
    random.seed(seme)
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = L / 2
    a, b, ang = 0.26 * L * scala, 0.18 * L * scala, math.radians(-35)
    # alone
    alone = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    da = ImageDraw.Draw(alone)
    for k in range(14, 0, -1):
        f = k / 14
        col = colori[0] + (int(34 + 22 * (1 - f)),)
        da.ellipse([c - a * f * 1.15, c - b * f * 1.15, c + a * f * 1.15, c + b * f * 1.15], fill=col)
    alone = alone.rotate(35, resample=Image.BICUBIC, center=(c, c)).filter(ImageFilter.GaussianBlur(0.02 * L))
    img = Image.alpha_composite(img, alone)
    d = ImageDraw.Draw(img)
    for _ in range(45):
        r = math.sqrt(random.random()) * 0.95
        t = random.random() * 2 * math.pi
        u, v = r * math.cos(t) * a, r * math.sin(t) * b
        x = c + u * math.cos(ang) - v * math.sin(ang)
        y = c + u * math.sin(ang) + v * math.cos(ang)
        dirz = random.random() * 2 * math.pi
        punti = [(x, y)]
        for _ in range(random.randint(6, 14)):
            dirz += random.gauss(0, 0.45)
            x += math.cos(dirz) * 0.012 * L * scala
            y += math.sin(dirz) * 0.012 * L * scala
            punti.append((x, y))
        col = random.choice(colori[1:])
        d.line(punti, fill=col + (245,), width=max(1, int(0.015 * L)), joint="curve")
    img = img.filter(ImageFilter.GaussianBlur(0.0025 * L))
    if grana:
        g = Image.effect_noise((L, L), 40).convert("L")
        g = g.point(lambda v: 255 if v > 200 else 0)
        alpha = img.getchannel("A")
        img = Image.composite(img, Image.new("RGBA", (L, L), (0, 0, 0, 0)), alpha.point(lambda v: min(255, v + 20)))
    return img


def crea(percorso_png="prima_e_dopo.png", percorso_ico="prima_e_dopo.ico"):
    L = LATO * S
    fondo = Image.new("RGBA", (L, L))
    d = ImageDraw.Draw(fondo)
    for y in range(L):
        u = y / L
        d.line([(0, y), (L, y)], fill=(int(10 + 8 * u), int(42 - 12 * u), int(56 - 10 * u), 255))
    maschera = Image.new("L", (L, L), 0)
    ImageDraw.Draw(maschera).rounded_rectangle([0, 0, L - 1, L - 1], radius=int(0.18 * L), fill=255)
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), maschera)
    # stelle
    random.seed(4)
    d = ImageDraw.Draw(img)
    for _ in range(45):
        x, y, r = random.random() * L, random.random() * L, random.choice([0.003, 0.004, 0.006]) * L
        d.ellipse([x - r, y - r, x + r, y + r], fill=(235, 240, 255, 220))
    # a sinistra: «prima» (seppia, più piccola); a destra: «dopo» (colori, più grande)
    prima = nebulosa(L, 0.78, [(190, 150, 100), (235, 205, 160), (210, 175, 125)], 11, grana=True)
    dopo = nebulosa(L, 1.0, [(200, 60, 90), (255, 120, 90), (120, 200, 255), (255, 200, 120)], 11)
    sx = Image.new("L", (L, L), 0)
    ImageDraw.Draw(sx).polygon([(0, 0), (0.56 * L, 0), (0.44 * L, L), (0, L)], fill=255)
    dx = Image.eval(sx, lambda v: 255 - v)
    img = Image.alpha_composite(img, Image.composite(prima, Image.new("RGBA", (L, L), (0, 0, 0, 0)), sx))
    img = Image.alpha_composite(img, Image.composite(dopo, Image.new("RGBA", (L, L), (0, 0, 0, 0)), dx))
    d = ImageDraw.Draw(img)
    # frecce dell'espansione (a destra)
    c = L / 2
    for ang in (-60, -20, 25, 70, 115):
        t = math.radians(ang)
        r0, r1 = 0.20 * L, 0.33 * L
        x0, y0 = c + r0 * math.cos(t), c + r0 * math.sin(t)
        x1, y1 = c + r1 * math.cos(t), c + r1 * math.sin(t)
        if x0 < 0.5 * L:
            continue
        d.line([(x0, y0), (x1, y1)], fill=(255, 225, 120, 255), width=int(0.014 * L))
        p = 0.035 * L
        d.polygon([(x1 + 0.4 * p * math.cos(t), y1 + 0.4 * p * math.sin(t)),
                   (x1 - p * math.cos(t - 0.5), y1 - p * math.sin(t - 0.5)),
                   (x1 - p * math.cos(t + 0.5), y1 - p * math.sin(t + 0.5))], fill=(255, 225, 120, 255))
    # linea dorata che divide
    d.line([(0.56 * L, 0), (0.44 * L, L)], fill=(255, 205, 90, 255), width=int(0.02 * L))
    # scritte: anni
    try:
        from PIL import ImageFont
        font = None
        for nome in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(nome, int(0.085 * L))
                break
            except OSError:
                continue
        if font:
            d.text((0.07 * L, 0.88 * L), "1950", font=font, fill=(235, 205, 160, 255), anchor="ls")
            d.text((0.93 * L, 0.88 * L), "OGGI", font=font, fill=(255, 225, 120, 255), anchor="rs")
    except Exception:
        pass
    img = Image.composite(img, Image.new("RGBA", (L, L), (0, 0, 0, 0)), maschera)
    img = img.resize((LATO, LATO), Image.LANCZOS)
    img.save(percorso_png)
    img.save(percorso_ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return percorso_png


if __name__ == "__main__":
    print(crea())
