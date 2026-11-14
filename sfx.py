"""Built-in sound effects (synthesised - 100% royalty-free, no external downloads):
Whoosh swell + low thump hit for montage cuts and zoom punch-ins.
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import wave
import numpy as np

SR = 44100

def whoosh(sr=SR, dur=0.45, seed=7, gain=0.8):
    """Rising noise swell that ends with a soft low 'hit' at ~0.30s."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.linspace(0, 1, n)
    noise = rng.standard_normal(n)
    out = np.empty(n)
    y = 0.0
    for i in range(n):
        a = 0.03 + 0.55 * t[i] ** 2
        y += a * (noise[i] - y)
        out[i] = noise[i] - y if t[i] > 0.45 else y
    env = np.sin(np.pi * np.clip(t / 0.72, 0, 1)) ** 2 * (t < 0.72)
    sw = out * env
    sw /= max(np.abs(sw).max(), 1e-6)
    
    tt = np.arange(n) / sr
    h0 = int(0.30 * sr)
    hit = np.zeros(n)
    k = tt[: max(n - h0, 0)]
    if len(k) > 0:
        hit[h0:h0 + len(k)] = np.sin(2 * np.pi * (75 - 30 * k / dur) * k) * np.exp(-k * 15)
    
    mix = 0.50 * sw + 0.85 * hit
    return (mix / max(np.abs(mix).max(), 1e-6) * (0.75 * gain)).astype(np.float32)

def build_track(path, total, times, sr=SR, gain=0.8):
    """
    Synthesizes a mono wav track of length `total` seconds, placing a whoosh
    whose punch lands exactly on each timestamp in `times`.
    """
    w = whoosh(sr, gain=gain)
    buf = np.zeros(int(total * sr) + len(w) + 1, dtype=np.float32)
    for t in times:
        i = max(int((t - 0.30) * sr), 0)
        end_idx = min(i + len(w), len(buf))
        buf[i:end_idx] += w[: end_idx - i]
    buf = np.clip(buf[: int(total * sr)], -1.0, 1.0)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((buf * 32767).astype(np.int16).tobytes())
    return path
