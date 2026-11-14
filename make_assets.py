"""Generates LellaVerse brand assets (logo.png, icon.ico, banner.png). Author: Lelum Anuradha Fernando"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
CY, MG, BG, SL = (0, 240, 255), (217, 38, 217), (11, 12, 16), (26, 29, 36)

def font(sz):
    for p in ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def grad(size, c1, c2):
    g = Image.new("RGB", (size, size)); px = g.load()
    for x in range(size):
        for y in range(size):
            t = (x + y) / (2 * size); px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return g

def logo(S=512):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(glow)
    d.rounded_rectangle([40, 40, S - 40, S - 40], 90, outline=CY + (255,), width=26)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(img).rounded_rectangle([40, 40, S - 40, S - 40], 90, fill=BG + (255,))
    ring = Image.new("L", (S, S), 0); ImageDraw.Draw(ring).rounded_rectangle([40, 40, S - 40, S - 40], 90, outline=255, width=14)
    img.paste(grad(S, CY, MG), (0, 0), ring)
    txt = Image.new("L", (S, S), 0); dt = ImageDraw.Draw(txt); f = font(int(S * .42))
    dt.text((S / 2, S / 2 - 8), "LV", font=f, fill=255, anchor="mm")
    img.paste(grad(S, CY, MG), (0, 0), txt)
    # play-triangle accent
    ImageDraw.Draw(img).polygon([(S * .70, S * .72), (S * .70, S * .86), (S * .82, S * .79)], fill=MG + (255,))
    return img

l = logo(); l.save("assets/logo.png")
l.resize((256, 256)).save("assets/icon.ico", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
b = Image.new("RGB", (1200, 260), BG); b.paste(l.resize((200, 200)), (30, 30), l.resize((200, 200)))
d = ImageDraw.Draw(b); d.text((260, 85), "LELLAVERSE", font=font(92), fill=(255, 255, 255), anchor="lm")
d.text((260, 175), "AI SHORTS BUILDER", font=font(48), fill=CY, anchor="lm")
d.rectangle([260, 215, 760, 221], fill=MG); b.save("assets/banner.png")
