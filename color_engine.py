"""Auto caption colours: picks readable text / highlight / outline colours from the video itself.
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import cv2, colorsys
import numpy as np

BRAND_CYAN = "#00F0FF"

def _lin(c):
    c = c / 255.0
    return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def _lum(rgb):
    r, g, b = _lin(np.asarray(rgb, dtype=np.float64))
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)

def _contrast(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

def _hex(rgb): return "#%02X%02X%02X" % tuple(int(round(v)) for v in rgb)

def _hsv_rgb(h, s, v): return tuple(c * 255 for c in colorsys.hsv_to_rgb(h % 1.0, s, v))

def analyze(video, y_pct=68, samples=8):
    """Returns (dominant_hue 0..1 or None, mean luminance of the caption band 0..1)."""
    cap = cv2.VideoCapture(video)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        hist = np.zeros(36); lums = []
        for k in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (0.05 + 0.9 * k / max(samples - 1, 1))))
            ok, fr = cap.read()
            if not ok: continue
            h, w = fr.shape[:2]
            sm = cv2.resize(fr, (160, max(int(160 * h / w), 8)))
            hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV).astype(np.float32)
            s, v = hsv[..., 1] / 255, hsv[..., 2] / 255
            wgt = np.where((s > 0.25) & (v > 0.25), s * v, 0)
            hist += np.bincount((hsv[..., 0] // 5).astype(int).ravel() % 36, weights=wgt.ravel(), minlength=36)
            y0, y1 = int(sm.shape[0] * max(y_pct - 9, 0) / 100), int(sm.shape[0] * min(y_pct + 9, 100) / 100) + 1
            band = sm[y0:y1].reshape(-1, 3)[:, ::-1].mean(axis=0)
            lums.append(_lum(band))
    finally:
        cap.release()

    lum = float(np.mean(lums)) if lums else 0.1
    hue = (int(hist.argmax()) * 10 + 5) / 360.0 if hist.sum() > 20 else None
    return hue, lum

def auto_style(video, style):
    """Copy of `style` with primary / highlight / outline colours matched to the video."""
    hue, lum = analyze(video, style.get("y_pct", 68))
    dark = lum < 0.35
    primary, outline = ("#FFFFFF", "#000000") if dark else ("#111111", "#FFFFFF")
    if hue is None:
        hl = BRAND_CYAN if dark else "#0057FF"
    else:
        cands = []
        for h in (hue, hue + 0.5, hue + 1 / 3):
            for v in ((1.0,) if dark else (0.5, 0.7)):
                rgb = _hsv_rgb(h, 0.9, v)
                cands.append((rgb, _contrast(_lum(rgb), lum)))
        best = next((r for r, c in cands if c >= 3.0), max(cands, key=lambda x: x[1])[0])
        hl = _hex(best)
    return {**style, "primary": primary, "highlight": hl, "outline": outline}
