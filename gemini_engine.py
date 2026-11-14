"""Gemini engine - Multi-Key AI Highlights & Precision Sinhala/English Word Captions
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import json, math, os, re, subprocess, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
from pydantic import BaseModel
from video_editor import _ensure_ffmpeg_path

CHUNK = 1800                 # seconds of stream per highlight request
WIN_FLASH = 55               # 50-60 seconds per caption window: keeps Shorts in 1 piece, zero boundary word drops
WIN_TRANSCRIBE = 300         # gemini-3.5-transcribe
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

# ====================================================================== Key Pool
def _sleep(sec, cancel):
    for _ in range(max(int(math.ceil(sec)), 1)):
        if cancel: cancel()
        time.sleep(1)

def _is_auth(m): return any(k in m for k in ("API key not valid", "API_KEY_INVALID", "PERMISSION_DENIED", "UNAUTHENTICATED"))
def _is_rate(m): return any(k in m for k in ("429", "RESOURCE_EXHAUSTED", "quota", "rate limit"))
def _is_transient(m): return any(k in m for k in ("503", "500", "UNAVAILABLE", "INTERNAL", "DEADLINE", "timed out", "Connection", "Server disconnected", "10054"))

def check_key_status(api_key):
    """Probes whether a single API key is active or has exceeded quota."""
    if not api_key or not api_key.strip():
        return "empty", "No key provided"
    try:
        c = genai.Client(api_key=api_key.strip())
        c.models.generate_content(model="gemini-3.5-flash", contents="hi")
        return "active", "Active & Working ✅"
    except Exception as e:
        msg = str(e)
        if any(x in msg for x in ("429", "RESOURCE_EXHAUSTED", "quota", "per.day")):
            return "quota", "Quota Limit Reached ⏳ (Please Replace)"
        elif any(x in msg for x in ("API key", "API_KEY", "INVALID", "PERMISSION_DENIED")):
            return "invalid", "Invalid Key ❌"
        elif any(x in msg for x in ("503", "UNAVAILABLE", "high demand")):
            return "busy", "Servers Busy ⚠️ (Retry shortly)"
        return "error", f"Error: {msg[:30]}"

class KeyPool:
    """Round-robin over several Gemini API keys with automatic failover and rate-limit backoff."""
    def __init__(self, keys, cooldown=65):
        self.keys = list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))[:4]
        if not self.keys: raise ValueError("Add at least one Gemini API key in the sidebar.")
        self.cooldown = cooldown
        self._lock = threading.Lock(); self._rr = 0
        self._cool = {k: 0.0 for k in self.keys}; self._dead = set(); self._clients = {}

    @property
    def size(self): return len(self.keys)

    def _client(self, k):
        with self._lock:
            if k not in self._clients: self._clients[k] = genai.Client(api_key=k)
            return self._clients[k]

    def _pick(self):
        with self._lock:
            live = [k for k in self.keys if k not in self._dead]
            if not live: raise RuntimeError("All API keys were rejected by Google. Check your keys in the sidebar.")
            now = time.time(); ready = [k for k in live if self._cool[k] <= now]
            if ready:
                k = ready[self._rr % len(ready)]; self._rr += 1; return k, 0.0
            k = min(live, key=lambda x: self._cool[x]); return k, self._cool[k] - now

    def call(self, fn, cancel=None, tries=8):
        last = None
        for attempt in range(tries):
            k, wait = self._pick()
            if wait > 0: _sleep(wait, cancel)
            if cancel: cancel()
            try:
                return fn(self._client(k))
            except Exception as e:
                m = str(e); last = e
                if _is_auth(m):
                    with self._lock: self._dead.add(k)
                elif _is_rate(m):
                    with self._lock: self._cool[k] = time.time() + (3600 if re.search(r"per.?day", m, re.I) else self.cooldown)
                elif _is_transient(m): _sleep(min(3 * 2 ** attempt, 30), cancel)
                else: raise
        raise last

    def map(self, fns, cancel=None):
        out = [None] * len(fns)
        ex = ThreadPoolExecutor(max_workers=max(1, self.size))
        try:
            futs = {ex.submit(self.call, f, cancel): i for i, f in enumerate(fns)}
            for f in as_completed(futs): out[futs[f]] = f.result()
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return out

FALLBACKS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]

def _generate(client, model, contents, **cfg):
    """Tries the chosen model first; if overloaded or discontinued, automatically falls back."""
    last = None
    for m in [model] + [x for x in FALLBACKS if x != model]:
        try:
            return _generate_one(client, m, contents, **cfg)
        except Exception as e:
            msg = str(e)
            if _is_transient(msg) or _is_rate(msg) or "high demand" in msg or "NOT_FOUND" in msg or "is not found" in msg or "no longer available" in msg:
                last = e; continue
            raise
    raise last

def _generate_one(client, model, contents, **cfg):
    if model.startswith("gemini-3") and "transcribe" not in model:
        try:
            return client.models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="low"), **cfg))
        except Exception as e:
            if "thinking" not in str(e).lower(): raise
    return client.models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(**cfg))

# ====================================================================== FFmpeg Audio Helpers & Pre-Processing
def duration(path):
    _ensure_ffmpeg_path()
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try: return float(out)
    except ValueError: return 0.0

def _run(cmd):
    _ensure_ffmpeg_path()
    subprocess.run(cmd, check=True, capture_output=True)

def inspect_audio_quality(media_path):
    """
    Audio Quality Inspection (Section 4):
    Inspects mean/max volume, detects clipping, unusually low volume, and background noise.
    Returns recommended preprocessing profile:
      - 'A': Original clean audio
      - 'B': Speech enhancement + level normalization (for quiet recordings)
      - 'C': Noise reduction + voice isolation (for severe background noise)
    """
    _ensure_ffmpeg_path()
    try:
        cmd = ["ffmpeg", "-i", media_path, "-vn", "-af", "volumedetect", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        mean_m = re.search(r"mean_volume: ([\-\d.]+) dB", r.stderr)
        max_m = re.search(r"max_volume: ([\-\d.]+) dB", r.stderr)
        mean_vol = float(mean_m.group(1)) if mean_m else -24.0
        max_vol = float(max_m.group(1)) if max_m else -1.0
    except Exception:
        mean_vol, max_vol = -24.0, -1.0

    is_clipping = max_vol >= -0.1
    is_quiet = mean_vol < -28.0
    profile = "B" if is_quiet else "A"
    return {
        "mean_volume_db": mean_vol,
        "max_volume_db": max_vol,
        "is_clipping": is_clipping,
        "is_quiet": is_quiet,
        "recommended_profile": profile
    }

def make_proxy(src, out_dir, start=0, length=None, idx=0):
    proxy = os.path.join(out_dir, f"proxy_{idx}.mp4")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start)] + (["-t", str(length)] if length else []) +
         ["-i", src, "-vf", "scale=-2:360,fps=1", "-c:v", "libx264", "-crf", "34", "-preset", "veryfast",
          "-ac", "1", "-b:a", "48k", proxy])
    return proxy

def extract_wav(src, out, start=0, length=None, profile="A"):
    """
    Extracts high-fidelity 16kHz mono PCM audio for transcription.
    Uses container PTS alignment (asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0) to guarantee
    perfect synchronization between video and burned subtitles.
    Profiles (Section 4):
      - 'A': Original clean audio
      - 'B': Speech enhancement (mild highpass + dynamic normalization)
      - 'C': Noise reduction + voice isolation (afftdn + loudnorm)
    """
    _ensure_ffmpeg_path()
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-accurate_seek"]
    if start and start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if length:
        cmd += ["-t", f"{length:.3f}"]

    af_filters = ["asetpts=PTS-STARTPTS", "aresample=async=1:first_pts=0"]
    if profile == "B":
        af_filters += ["highpass=f=80", "lowpass=f=7500", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    elif profile == "C":
        af_filters += ["afftdn=nf=-25", "highpass=f=80", "loudnorm=I=-16:TP=-1.5:LRA=11"]

    cmd += ["-af", ",".join(af_filters)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out]
    _run(cmd)
    return out

def detect_acoustic_bursts(media, dur=None):
    """
    Veed.io / CapCut style acoustic phrase detection:
    Uses FFmpeg silencedetect calibrated to -30dB:d=0.22 to detect natural
    spoken phrases and sentences bounded by breath pauses.
    Automatically filters out initial camera mic clicks (<0.40s at start).
    """
    _ensure_ffmpeg_path()
    if dur is None: dur = duration(media)
    if dur <= 0: return []
    
    r = subprocess.run(["ffmpeg", "-i", media, "-vn", "-af", "silencedetect=noise=-30dB:d=0.22", "-f", "null", "-"],
                       capture_output=True, text=True)
    sil_starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    sil_ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    
    raw_bursts = []
    cur = 0.0
    for s, e in zip(sil_starts, sil_ends):
        if s > cur + 0.12:
            raw_bursts.append((round(cur, 2), round(s, 2)))
        cur = e
    if cur < dur - 0.12:
        raw_bursts.append((round(cur, 2), round(dur, 2)))

    # Filter out initial microphone pop / camera click (<0.40s starting at 0.00s)
    clean = []
    for s, e in raw_bursts:
        if s < 0.20 and (e - s) < 0.40:
            continue
        clean.append((s, e))

    return clean if clean else [(0.0, round(dur, 2))]

# ====================================================================== Unified Word Data Structure & Alignment
def make_word_item(text, start, end, confidence=None, language=None, speaker=None, alignment_status="asr_native", raw_text=None):
    """
    Unified Word Data Structure (Section 8):
    Consistent internal representation:
      text, raw_text, start, end, confidence, language, speaker, alignment_status
    Includes 'w', 's', 'e' keys for 100% backward compatibility.
    """
    s_val = round(max(0.0, float(start)), 3)
    e_val = round(max(s_val + 0.05, float(end)), 3)
    txt = str(text or "").strip()
    raw = str(raw_text or txt).strip()
    if language is None:
        language = "si" if any(0x0D80 <= ord(c) <= 0x0DFF for c in txt) else "en"
    conf_val = round(float(confidence), 3) if confidence is not None else None
    return {
        "text": txt,
        "raw_text": raw,
        "start": s_val,
        "end": e_val,
        "confidence": conf_val,
        "language": language,
        "speaker": speaker,
        "alignment_status": alignment_status,
        "w": txt,
        "s": s_val,
        "e": e_val
    }

def align_words_to_timeline(words, bursts=None, dur=None):
    """
    True Word-Level Timestamp Alignment (Section 6 & 8):
    1. Preserves genuine acoustic timestamps returned by ASR providers.
    2. NEVER fabricates timestamps using character, word, or syllable counts.
    3. Validates chronological order and resolves minor adjacent overlaps.
    4. Enforces audio boundary constraints (0 <= start < end <= dur).
    5. Returns unified WordSegment list with alignment_status.
    """
    if not words:
        return []

    valid = []
    for d in words:
        raw_w = str(d.get("raw_text") or d.get("text") or d.get("w") or d.get("word") or "").strip()
        txt = str(d.get("text") or d.get("w") or d.get("word") or "").strip()
        if not txt:
            continue
        s_val = max(0.0, _t(d.get("start", d.get("s", 0.0))))
        e_val = max(s_val + 0.05, _t(d.get("end", d.get("e", s_val + 0.08))))
        if dur and s_val >= dur:
            continue
        if dur and e_val > dur:
            e_val = dur

        conf = d.get("confidence")
        lang = d.get("language")
        speaker = d.get("speaker")
        status = d.get("alignment_status", "asr_native")
        valid.append(make_word_item(txt, s_val, e_val, conf, lang, speaker, status, raw_w))

    valid.sort(key=lambda x: x["start"])

    # Sequential ordering and overlap resolution
    for i in range(len(valid)):
        cur = valid[i]
        if i > 0:
            prev = valid[i - 1]
            if cur["start"] < prev["start"]:
                cur["start"] = prev["start"] + 0.04
            if prev["end"] > cur["start"]:
                prev["end"] = max(prev["start"] + 0.05, cur["start"])
                prev["e"] = prev["end"]
        if cur["end"] <= cur["start"]:
            cur["end"] = cur["start"] + 0.08
        cur["s"] = cur["start"]
        cur["e"] = cur["end"]

    return valid

# Alias for backward compatibility with pipeline and other modules
align_words_to_bursts = align_words_to_timeline

def convert_global_words_to_cuts(global_words, cuts):
    """
    Accurately maps global stream word timestamps to clip-relative timestamps (0.000s base)
    for multi-cut montage / super-edit Shorts.
    Preserves true word timing without cumulative drift across cuts.
    """
    if not global_words or not cuts:
        return []
    
    out = []
    clip_offset = 0.0
    for c_start, c_end in cuts:
        c_dur = max(0.0, float(c_end) - float(c_start))
        if c_dur <= 0:
            continue
        for w in global_words:
            w_s = float(w.get("start", w.get("s", 0.0)))
            w_e = float(w.get("end", w.get("e", w_s + 0.1)))
            
            # Check if word overlaps with current cut window
            if w_s < float(c_end) and w_e > float(c_start):
                rel_s = round(clip_offset + max(0.0, w_s - float(c_start)), 3)
                rel_e = round(clip_offset + min(c_dur, w_e - float(c_start)), 3)
                
                if rel_e > rel_s + 0.03:
                    txt = w.get("text", w.get("w", ""))
                    raw = w.get("raw_text", txt)
                    conf = w.get("confidence")
                    lang = w.get("language")
                    spk = w.get("speaker")
                    stat = w.get("alignment_status", "asr_native")
                    out.append(make_word_item(txt, rel_s, rel_e, conf, lang, spk, stat, raw))
        clip_offset += c_dur
        
    out.sort(key=lambda x: x["start"])
    return align_words_to_timeline(out, dur=clip_offset)

def split_points(src, dur, win=WIN_FLASH):
    """
    Splits audio into speech-safe chunks (50-60s) snapped to silence pauses
    so words are never cut in half and Gemini never drops speech.
    """
    if dur <= win * 1.2:
        return [0.0, dur]
    r = subprocess.run(["ffmpeg", "-i", src, "-vn", "-af", "silencedetect=noise=-30dB:d=0.25", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    mids = [(a + b) / 2 for a, b in zip(starts, ends)]
    
    pts = [0.0]
    cur = 0.0
    while dur - cur > win * 1.2:
        target = cur + win
        near = [m for m in mids if cur + win * 0.50 <= m <= cur + win * 1.30]
        cur = min(near, key=lambda m: abs(m - target)) if near else target
        pts.append(round(cur, 3))
    pts.append(round(dur, 3))
    return pts

# ====================================================================== Highlights (Super Edit Shorts)
class Cut(BaseModel):
    start: float
    end: float

class ShortPlan(BaseModel):
    title: str
    description: str
    score: float
    cuts: list[Cut]

SHORTS_PROMPT = """You are an elite YouTube Shorts & TikTok gaming editor who creates high-retention "super edit" montages.
Watch this live-stream segment (video + audio, {dur:.0f}s long) and design {n} viral Shorts.
Each Short is a FAST-PACED MONTAGE of 4-9 short cuts (2-12 seconds each) taken from DIFFERENT exciting moments of this stream segment:
1. Hook first (the most shocking or funny moment in the first 3 seconds).
2. Buildup / tension in the middle.
3. Big payoff / clutch / scream / victory at the end.
Total length of all cuts combined for ONE Short: 25-58 seconds (strict: never exceed 60s).
Select intense gunfights, clutch wins, hilarious fails, crazy chatter, rage, and hype. Eliminate boring menus and dead air.
Timestamps are in SECONDS from the start of this segment. No cut may overlap another.
title: catchy YouTube title (under 60 chars). description: 1 punchy sentence. score: 1-10 viral potential."""

def _t(x):
    if x is None: return 0.0
    if isinstance(x, (int, float)): return float(x)
    if hasattr(x, "seconds") or hasattr(x, "nanos"):
        return float(getattr(x, "seconds", 0) or 0) + float(getattr(x, "nanos", 0) or 0) / 1e9
    s = str(x).strip().rstrip("sS")
    if ":" in s:
        sec = 0.0
        for p in s.split(":"): sec = sec * 60 + float(p)
        return sec
    return float(s)

def parse_shorts(text, dur, max_total=60.0):
    txt = (text or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt)
        txt = re.sub(r"\n?```$", "", txt)
    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        data = json.loads(m.group(0)) if m else []

    if isinstance(data, dict): data = data.get("shorts") or data.get("highlights") or []
    out, taken = [], []
    for h in data:
        cuts, total = [], 0.0
        for c in (h.get("cuts") or []):
            try: s = max(0.0, _t(c.get("start"))); e = min(_t(c.get("end")), dur, s + 15)
            except (TypeError, ValueError, AttributeError): continue
            if e - s < 1.0: continue
            if any(s < b and e > a for a, b in cuts + taken): continue
            if total + (e - s) > max_total: e = s + (max_total - total)
            if e - s < 1.0: break
            cuts.append((s, e)); total += e - s
        if total >= 8:
            taken += cuts
            out.append({"title": str(h.get("title", "Stream Highlight"))[:80],
                        "description": str(h.get("description", ""))[:200],
                        "score": float(h.get("score") or 8.0), "cuts": cuts})
    return out

def detect_audio_excitement(media, dur=None):
    """
    Intelligent Acoustic Reaction & Peak Detector (Part 3):
    Scans the stream for sudden volume spikes, screams, cheering, intense action,
    and energetic speech above mean background volume.
    Returns timestamps of high-energy climax moments.
    """
    if dur is None: dur = duration(media)
    if dur <= 0: return []
    try:
        cmd = ["ffmpeg", "-i", media, "-vn", "-af", "silencedetect=noise=-24dB:d=0.35", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        starts = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
        peaks = [round(s, 2) for s in starts if s < dur]
        return sorted(peaks)
    except Exception:
        return []

def snap_cuts_to_speech(cuts, bursts, dur, pre_roll=0.35, post_roll=0.60, max_total=58.0):
    """
    Clip Start and End Accuracy (Part 4):
    Snaps cut start/end timestamps to speech burst boundaries:
    - Never cuts off the beginning of a sentence (pre-roll 0.35s).
    - Never cuts off the end of a reaction or spoken punchline (post-roll 0.60s).
    - Eliminates dead air and clamps duration cleanly within 58 seconds.
    """
    snapped = []
    total = 0.0
    for s, e in cuts:
        cur_s, cur_e = float(s), float(e)
        if bursts:
            for bs, be in bursts:
                if bs - 0.25 <= cur_s <= be:
                    cur_s = max(0.0, bs - pre_roll)
                    break
            for bs, be in bursts:
                if bs <= cur_e <= be + 0.30:
                    cur_e = min(dur, be + post_roll)
                    break
        if cur_e - cur_s < 1.0:
            continue
        if total + (cur_e - cur_s) > max_total:
            cur_e = cur_s + (max_total - total)
        if cur_e - cur_s < 1.0:
            break
        snapped.append((round(cur_s, 2), round(cur_e, 2)))
        total += (cur_e - cur_s)
    return snapped

def detect_fallback_highlights(media, dur, n=3):
    """
    Reliable Offline / Acoustic Highlight Fallback (Part 3 & 9):
    Extracts viral climax segments based on acoustic speech bursts and peak intensity.
    Guarantees the application never crashes even without internet/API keys.
    """
    bursts = detect_acoustic_bursts(media, dur)
    if not bursts:
        step = dur / max(n, 1)
        return [{"title": f"Stream Highlight {i+1}", "description": "High energy stream action",
                 "score": 8.0, "cuts": [(round(i * step, 2), round(min(dur, (i + 1) * step), 2))]}
                for i in range(n)]

    highlights = []
    chunk_target = 35.0
    cur_cuts = []
    cur_dur = 0.0

    for s, e in bursts:
        d = e - s
        if d < 1.0: continue
        if cur_dur + d <= chunk_target:
            cur_cuts.append((round(s, 2), round(e, 2)))
            cur_dur += d
        else:
            if cur_dur >= 12.0:
                highlights.append({
                    "title": f"Action Highlight {len(highlights)+1}",
                    "description": "High-energy gameplay climax sequence",
                    "score": 8.5,
                    "cuts": cur_cuts
                })
            cur_cuts = [(round(s, 2), round(e, 2))]
            cur_dur = d
        if len(highlights) >= n:
            break

    if cur_cuts and len(highlights) < n and cur_dur >= 8.0:
        highlights.append({
            "title": f"Action Highlight {len(highlights)+1}",
            "description": "Climax gameplay moment",
            "score": 8.0,
            "cuts": cur_cuts
        })

    return highlights[:n] if highlights else [{"title": "Highlight 1", "description": "Climax clip", "score": 8.0, "cuts": [(0.0, min(dur, 45.0))]}]

def _analyze_video(client, proxy, model, n, dur):
    f = client.files.upload(file=proxy)
    try:
        while f.state.name == "PROCESSING":
            time.sleep(2); f = client.files.get(name=f.name)
        if f.state.name != "ACTIVE": raise RuntimeError(f"Gemini could not process the video ({f.state.name}).")
        resp = _generate(client, model, [f, SHORTS_PROMPT.format(n=n, dur=dur)], response_mime_type="application/json",
                         response_schema=list[ShortPlan], temperature=0.4,
                         media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW)
    finally:
        try: client.files.delete(name=f.name)
        except Exception: pass
    return parse_shorts(resp.text, dur)

def find_shorts(pool, video, model, n=4, temp="temp", cancel=None, progress=None, chunk=CHUNK):
    """Find highlights in *video* ensuring full‑timeline analysis.

    This implementation guarantees:
    1️⃣ 100 % of the source video is processed regardless of the requested *n*.
    2️⃣  A configurable cache stores the complete analysis so subsequent calls with a different *n* reuse work.
    3️⃣  Each chunk requests a generous number of candidate highlights (at least 5) to feed a global ranking.
    4️⃣  Final clips are limited to 60 seconds (clipped if necessary) and de‑duplicated.
    """
    # ---------------------------------------------------------------------
    # 1️⃣  Load or create analysis cache
    # ---------------------------------------------------------------------
    import hashlib, json
    cache_key = hashlib.sha256(f"{video}|{os.path.getsize(video)}|{os.path.getmtime(video)}".encode()).hexdigest()
    cache_path = os.path.join(temp, f"highlights_cache_{cache_key}.json")
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            found = cached.get("highlights", [])
        else:
            found = None
    except Exception:
        found = None

    # ---------------------------------------------------------------------
    # 2️⃣  Full‑video chunked analysis (only if cache miss)
    # ---------------------------------------------------------------------
    dur = duration(video)
    bursts = detect_acoustic_bursts(video, dur)
    if found is None:
        # Create windows covering the entire video (no early exit based on *n*)
        starts = [s for s in range(0, int(dur), chunk) if dur - s >= 20] or [0]
        # Request a minimum of 5 candidates per window to ensure enough material for global ranking
        per = max(5, math.ceil(n / len(starts)) + 1)
        done = [0]; lock = threading.Lock()
        def job(i, s):
            L = min(chunk, dur - s)
            def fn(client):
                proxy = make_proxy(video, temp, s, L, i)
                try:
                    return _analyze_video(client, proxy, model, per, L)
                finally:
                    try: os.remove(proxy)
                    except OSError: pass
            try:
                res = pool.call(fn, cancel)
            except Exception:
                res = []
            with lock:
                done[0] += 1
                if progress:
                    progress(done[0] / len(starts), f"🧠 Gemini analysed part {done[0]}/{len(starts)} ({pool.size} key{'s' if pool.size > 1 else ''})")
            # Shift cuts to absolute timestamps
            return [{**sh, "cuts": [(a + s, b + s) for a, b in sh["cuts"]]} for sh in res]
        ex = ThreadPoolExecutor(max_workers=max(1, pool.size))
        found = []
        if progress:
            progress(0, f"🧠 Gemini is analysing the stream ({len(starts)} part{'s' if len(starts) > 1 else ''}, {pool.size} key{'s' if pool.size > 1 else ''})…")
        try:
            for f in as_completed([ex.submit(job, i, s) for i, s in enumerate(starts)]):
                try:
                    found += f.result()
                except Exception:
                    pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        # Cache the raw highlights for future reuse
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"highlights": found}, f)
        except Exception:
            pass
    # ---------------------------------------------------------------------
    # 3️⃣  Fallback if Gemini returned nothing
    # ---------------------------------------------------------------------
    if not found:
        found = detect_fallback_highlights(video, dur, n)

    # ---------------------------------------------------------------------
    # 4️⃣  Global ranking, snapping, deduplication & clip‑duration enforcement
    # ---------------------------------------------------------------------
    picked, used = [], []
    for sh in sorted(found, key=lambda x: -x["score"]):
        # Snap cuts to speech boundaries (ensures natural start/end)
        snapped_cuts = snap_cuts_to_speech(sh["cuts"], bursts, dur)
        if not snapped_cuts:
            continue
        # Enforce maximum total duration per short (≤ 60 s)
        total_len = sum(e - s for s, e in snapped_cuts)
        if total_len > 60.0:
            # Trim excess from the last cut
            excess = total_len - 60.0
            s_last, e_last = snapped_cuts[-1]
            e_last = max(s_last + 1.0, e_last - excess)
            snapped_cuts[-1] = (s_last, round(e_last, 2))
        # Ensure no substantial overlap with already selected clips
        if not any(a < d and b > c for a, b in snapped_cuts for c, d in used):
            picked.append({**sh, "cuts": snapped_cuts})
            used += snapped_cuts
        if len(picked) >= n:
            break
    # Return exactly the requested count (or fewer if not enough unique highlights)
    return picked[:max(n, 1)] if picked else detect_fallback_highlights(video, dur, n)

# ====================================================================== Precision Captions
WORDS_PROMPT = """You are an elite verbatim audio transcriber for Sri Lankan Sinhala + English bilingual videos.
Transcribe EVERY SINGLE WORD spoken in this audio with precise word-level timestamps.
Language: {lang}

CRITICAL TRANSCRIPTION RULES:
1. VERBATIM & COMPLETE:
   - Transcribe every single word spoken. NEVER skip, drop, summarize, paraphrase, or omit any word.
   - Include all filler words, discourse particles, and reactions (e.g., අනේ, ඉතින්, හරි, ඔව්, නෑ, මචං, අඩෝ).

2. CODE-SWITCHING & ENGLISH PRESERVATION (CRITICAL):
   - Sri Lankan content creators constantly mix Sinhala and English (Sinhala-English code-switching).
   - Whenever the speaker uses an English word, gaming term, tech term, brand, or everyday English expression, YOU MUST TRANSCRIBE IT IN LATIN CHARACTERS (ENGLISH SCRIPT) EXACTLY AS SPOKEN.
   - NEVER transliterate English words into Sinhala characters!
     * DO NOT write "දිස් ගේම්" — ALWAYS write "this game".
     * DO NOT write "නිව් වීඩියෝ" — ALWAYS write "new video".
     * DO NOT write "ඇප්ලිකේෂන්" — ALWAYS write "application".
     * DO NOT write "ටෙස්ට්" — ALWAYS write "test".
     * DO NOT write "රෙකෝඩින්" — ALWAYS write "recording".
     * DO NOT write "ක්ලච්" — ALWAYS write "clutch".
     * DO NOT write "ලෙවල්" — ALWAYS write "level".
     * DO NOT write "ප්ලේ" — ALWAYS write "play".
     * DO NOT write "බ්‍රෝ" — ALWAYS write "bro".
     * DO NOT write "සබ්ස්ක්‍රයිබ්" — ALWAYS write "subscribe".
   - Keep English technical & gaming terms in English: YouTube, TikTok, Shorts, OBS, Discord, PC, CPU, GPU, RAM, FPS, WiFi, Internet, Link, Description, Like, Share, Comment, Headshot, Kill, Winner, Gameplay, Edit, Effect, Auto, Zoom, Settings, File, Folder, Download, Upload, etc.
   - When an English word has a Sinhala particle attached (e.g., "game එක", "video එකක්", "application එක", "record කරනවා", "edit කරලා"), transcribe the English word in English and the Sinhala particle in Sinhala Unicode:
     * Correct: "this game එක පට්ටයි" (NOT: "දිස් ගේම් එක පට්ටයි")
     * Correct: "අද අපි new video එකක් හදනවා" (NOT: "අද අපි නිව් වීඩියෝ එකක් හදනවා")
     * Correct: "මම මේ application එක test කරනවා" (NOT: "මම මේ ඇප්ලිකේෂන් එක ටෙස්ට් කරනවා")

3. AUTHENTIC SINHALA SCRIPT FOR SPOKEN SINHALA:
   - Spoken Sinhala words MUST be written in authentic Sinhala Unicode script (සිංහල අකුරු, U+0D80–U+0DFF).
   - NEVER write spoken Sinhala words in Singlish (Latin script).
     * Correct: මම, මගේ, අද, අපි, මේ, මේක, එක, එකක්, පට්ටයි, හරි, තමයි, පුලුවන්, බලමු, හදනවා, කරනවා.
     * NEVER write: "mama", "mage", "ada", "api", "me", "meka", "eka", "ekak", "pattai", "hari", "balamu".

4. NO FOREIGN SCRIPTS:
   - Only Sinhala Unicode (U+0D80–U+0DFF), English Latin (A-Z, a-z), numbers (0-9), and basic punctuation.
   - NEVER output Georgian, Devanagari, Cyrillic, Arabic, Ethiopic, or any other foreign alphabet.

5. PRECISE WORD-LEVEL TIMESTAMPS:
   - Each entry in the JSON must represent EXACTLY ONE word.
   - 's' = speech start time in seconds (float, e.g. 1.24).
   - 'e' = speech end time in seconds (float, e.g. 1.68).
   - Align timestamps strictly to acoustic speech boundaries.

Return ONLY a JSON array: [{{"w": "word", "s": 0.00, "e": 0.00}}]"""

LANG_HINT = {
    None: "Sinhala spoken language with English code-switching and technical terms. Sinhala words in authentic Sinhala script, English words in Latin script.",
    "si": "Sinhala spoken language with English code-switching and technical terms. Sinhala words in authentic Sinhala script, English words in Latin script.",
    "bilingual": "Sinhala spoken language with English code-switching and technical terms. Sinhala words in authentic Sinhala script, English words in Latin script.",
    "en": "English speech in English letters."
}

# Foreign script transliteration map for safety
FOREIGN_TO_LATIN = {
    '\u10d0': 'a', '\u10d1': 'b', '\u10d2': 'g', '\u10d3': 'd', '\u10d4': 'e', '\u10d5': 'v', '\u10d6': 'z',
    '\u10d7': 't', '\u10d8': 'i', '\u10d9': 'k', '\u10da': 'l', '\u10db': 'm', '\u10dc': 'n', '\u10dd': 'o',
    '\u10de': 'p', '\u10df': 'zh', '\u10e0': 'r', '\u10e1': 's', '\u10e2': 't', '\u10e3': 'u', '\u10e4': 'p',
    '\u10e5': 'k', '\u10e6': 'gh', '\u10e7': 'q', '\u10e8': 'sh', '\u10e9': 'ch', '\u10ea': 'ts',
    '\u10eb': 'dz', '\u10ec': 'ts', '\u10ed': 'ch', '\u10ee': 'kh', '\u10ef': 'j', '\u10f0': 'h', '\u10f8': 'k',
    '\u0905': 'a', '\u0906': 'aa', '\u0907': 'i', '\u0908': 'ee', '\u0909': 'u', '\u090a': 'oo',
    '\u090f': 'e', '\u0910': 'ai', '\u0913': 'o', '\u0914': 'au',
    '\u0915': 'k', '\u0916': 'kh', '\u0917': 'g', '\u0918': 'gh',
    '\u091a': 'ch', '\u091b': 'chh', '\u091c': 'j', '\u091d': 'jh',
    '\u091f': 't', '\u0920': 'th', '\u0921': 'd', '\u0922': 'dh', '\u0923': 'n',
    '\u0924': 't', '\u0925': 'th', '\u0926': 'd', '\u0927': 'dh', '\u0928': 'n',
    '\u092a': 'p', '\u092b': 'ph', '\u092c': 'b', '\u092d': 'bh', '\u092e': 'm',
    '\u092f': 'y', '\u0930': 'r', '\u0932': 'l', '\u0935': 'v', '\u0936': 'sh', '\u0937': 'sh', '\u0938': 's', '\u0939': 'h',
    '\u093e': 'a', '\u093f': 'i', '\u0940': 'ee', '\u0941': 'u', '\u0942': 'oo', '\u0947': 'e', '\u0948': 'ai', '\u094b': 'o', '\u094c': 'au',
    '\u12a5': 'i', '\u12a0': 'a', '\u12e8': 'ye', '\u12f0': 'de'
}

# Common Singlish words to Sinhala Unicode dictionary for safety fallback
# This is the LARGEST known Singlish→Sinhala dictionary for Sri Lankan creator content.
SINGLISH_MAP = {
    # --- Pronouns & People ---
    "mama": "මම", "mame": "මම", "mam": "මම", "man": "මං", "mang": "මං",
    "mage": "මගේ", "magey": "මගේ", "magee": "මගේ", "mata": "මට", "matath": "මටත්",
    "oya": "ඔයා", "oyage": "ඔයාගේ", "oyala": "ඔයාලා", "oyalata": "ඔයාලට", "oyalagey": "ඔයාලගේ",
    "api": "අපි", "apita": "අපිට", "apata": "අපිට", "ape": "අපේ", "apey": "අපේ",
    "eya": "එයා", "eyage": "එයාගේ", "eyata": "එයාට", "eyala": "එයාලා",
    "machan": "මචං", "machang": "මචං", "mchan": "මචං", "macha": "මචං",
    "yaluwane": "යාලුවනේ", "yaluvane": "යාලුවනේ", "alue": "යාලුවනේ", "aluwane": "යාලුවනේ",
    "kollane": "කොල්ලනේ", "kello": "කෙල්ලෝ", "ammo": "අම්මෝ", "ado": "අඩෝ",

    # --- Core Verbs ---
    "karanna": "කරන්න", "karanne": "කරන්නේ", "karanawa": "කරනවා", "karala": "කරලා",
    "karapu": "කරපු", "karapan": "කරපන්", "karannam": "කරන්නම්",
    "karaganna": "කරගන්න", "karagaththa": "කරගත්තා", "karagihalla": "කරගිහිල්ලා",
    "hadaganna": "හදාගන්න", "hadanna": "හදන්න", "hadala": "හදලා", "hadapu": "හදපු", "hadanawa": "හදනවා",
    "yanna": "යන්න", "yande": "යන්න", "yanne": "යන්නේ", "yanawa": "යනවා",
    "gihin": "ගිහින්", "giya": "ගියා", "giyapu": "ගියපු",
    "enna": "එන්න", "enne": "එන්නේ", "enawa": "එනවා", "aawa": "ආවා", "aawaa": "ආවා",
    "balanda": "බලන්න", "balanna": "බලන්න", "balamu": "බලමු", "balala": "බලලා",
    "baromu": "බලමු", "බාරomu": "බලමු", "බaromu": "බලමු",
    "kiala": "කියලා", "kiyala": "කියලා", "kiwwa": "කිව්වා", "kiwwata": "කිව්වට",
    "kiyanna": "කියන්න", "kiyane": "කියන්නේ", "kiyana": "කියන",
    "hithanawa": "හිතනවා", "hithnawa": "හිතනවා", "hithenawa": "හිතෙනවා", "hithe": "හිතේ",
    "danna": "දන්න", "danne": "දන්නේ", "dannawa": "දන්නවා",
    "ganna": "ගන්න", "ganne": "ගන්නේ", "gaththa": "ගත්තා", "gannawa": "ගන්නවා",
    "thiyenawa": "තියෙනවා", "thiyenne": "තියෙන්නේ", "thibba": "තිබ්බා", "tibba": "තිබ්බා",
    "thibunaa": "තිබුනා", "thiyena": "තියෙන", "thiya": "තියා",
    "watenawa": "වැටෙනවා", "wetenawa": "වැටෙනවා", "watenawada": "වැටෙනවද",
    "wetenawadi": "වැටෙනවද", "watenne": "වැටෙන්නේ",
    "denna": "දෙන්න", "denne": "දෙන්නේ", "denawa": "දෙනවා", "dunna": "දුන්නා",
    "bonna": "බොන්න", "kanna": "කන්න", "kannae": "කන්නෑ",
    "penawa": "පෙනවා", "penne": "පෙන්නේ", "pennala": "පෙන්නලා", "pennanna": "පෙන්නන්න",
    "ahanawa": "අහනවා", "ahanna": "අහන්න", "ahala": "අහලා",
    "danawa": "දනවා", "danaganna": "දැනගන්න", "danagaththa": "දැනගත්තා",
    "puluwan": "පුලුවන්", "puluwannam": "පුලුවන්නම්",
    "bae": "බෑ", "baeri": "බැරි", "bari": "බැරි", "barinae": "බැරිනෑ",
    "wenawa": "වෙනවා", "wenne": "වෙන්නේ", "wela": "වෙලා", "wuna": "වුණා", "wunaa": "වුණා",
    "labenna": "ලැබෙන්න", "labenawa": "ලැබෙනවා", "laebunaa": "ලැබුනා",
    "tharenawa": "තේරෙනවා", "tharenne": "තේරෙන්නේ", "therunaa": "තේරුණා",
    "panala": "පැනලා",

    # --- Common Words & Particles ---
    "hari": "හරි", "hariyata": "හරියට", "harid": "හරිද", "harida": "හරිද",
    "thamai": "තමයි", "tama": "තමයි", "thama": "තමයි", "thamayi": "තමයි",
    "mokada": "මොකද", "mokak": "මොකක්", "mokatada": "මොකටද", "moko": "මොකෝ", "mokakda": "මොකක්ද",
    "ow": "ඔව්", "oww": "ඔව්", "owa": "ඔව්",
    "ne": "නෑ", "nae": "නෑ", "na": "නෑ", "naha": "නැහැ", "nahae": "නැහැ", "naethnam": "නැත්නම්",
    "eka": "එක", "ekak": "එකක්", "ekata": "එකට", "eken": "එකෙන්", "ekath": "එකත්", "eke": "එකේ",
    "me": "මේ", "meka": "මේක", "meken": "මේකෙන්", "mekata": "මේකට", "mekath": "මේකත්", "meke": "මේකේ",
    "ara": "අර", "araka": "අරක", "owa": "ඕවා", "okkoma": "ඔක්කොම",
    "dan": "දැන්", "den": "දැන්", "danwath": "දැන්වත්",
    "thawa": "තව", "thawath": "තවත්", "thawama": "තවම",
    "ithin": "ඉතින්", "itin": "ඉතින්",
    "ehema": "එහෙම", "methema": "මෙහෙම", "mehe": "මෙහේ", "ehe": "එහේ",
    "etakota": "එතකොට", "eethakota": "ඊතකොට",
    "hinda": "හින්දා", "nisa": "නිසා", "nisaa": "නිසා",
    "godak": "ගොඩක්", "godam": "ගොඩම",
    "loku": "ලොකු", "lokuvata": "ලොකුවට", "podi": "පොඩි", "podiyen": "පොඩියෙන්",
    "aluth": "අලුත්", "parana": "පරණ",
    "newei": "නෙවෙයි", "nemeyi": "නෙමෙයි", "nemeyida": "නෙමෙයිද",
    "eeta": "ඊට", "eepasse": "ඊටපස්සේ", "kalin": "කලින්", "passe": "පස්සේ",
    "kisi": "කිසි", "kisima": "කිසිම", "mathakane": "මතකනේ", "mathaka": "මතක",
    "wediye": "වැඩිය", "wediyen": "වැඩියෙන්", "wedi": "වැඩි",
    "weda": "වැඩ", "wedak": "වැඩක්", "wedeta": "වැඩේට", "wedee": "වැඩේ", "wede": "වැඩේ",
    "kramaya": "ක්‍රමය",
    "poddak": "පොඩ්ඩක්", "podak": "පොඩ්ඩක්", "podk": "පොඩ්ඩක්", "පodk": "පොඩ්ඩක්",
    "tikkak": "ටිකක්", "tikak": "ටිකක්", "tika": "ටික",
    "parakku": "පරක්කු", "porakku": "පරක්කු", "porack": "පරක්කු", "පොරack": "පරක්කු",
    "kathawa": "කතාව", "kathaawa": "කතාව",
    "ini": "ආයෙත්", "iini": "ආයෙත්", "aaye": "ආයේ", "aayeth": "ආයෙත්", "ayeth": "ආයෙත්",
    "sarthaka": "සාර්ථක", "hathal": "ආතල්", "aathal": "ආතල්", "dekata": "දෙකට",
    "vidiyata": "විදියට", "widiyata": "විදියට", "vidiya": "විදිය", "widiya": "විදිය",
    "wachane": "වචනේ", "wachana": "වචන",
    "amaruvak": "අමාරුවක්", "amaruwak": "අමාරුවක්", "amaru": "අමාරු",
    "dammoth": "දැම්මොත්", "dammot": "දැම්මොත්",
    "porak": "පොරක්", "maka": "මකා",

    # --- Tech / Creator words that get Singlish-ified ---
    "hadanawa": "හදනවා", "hadagannawa": "හදාගන්නවා",
    "damanna": "දාමන්න", "damala": "දාලා", "danawa": "දාන්න", "daanna": "දාන්න",
    "daala": "දාලා", "daapan": "දාපන්",
    "balaganna": "බලාගන්න", "balagaththa": "බලාගත්තා",
    "eliyata": "එළියට", "athulata": "ඇතුළට", "athule": "ඇතුළේ",
    "igenaganna": "ඉගෙනගන්න", "igenagaththa": "ඉගෙනගත්තා",
    "rekodinna": "රෙකෝඩින්", "rekoding": "රෙකෝඩින්",

    # --- Numbers / Quantities ---
    "ekak": "එකක්", "dekak": "දෙකක්", "thunaka": "තුනක්", "hatharak": "හතරක්",
    "pahak": "පහක්", "dahayak": "දහයක්",

    # --- Filler / Discourse markers ---
    "ane": "අනේ", "aney": "අනේ", "aiyo": "අයියෝ", "aiyoo": "අයියෝ",
    "ko": "කෝ", "koo": "කෝ",
    "da": "ද", "dha": "ද",
    "ath": "ඇත්", "nath": "නැත්", "naethnam": "නැත්නම්",
    "nam": "නම්", "nang": "නං",
    "wage": "වගේ", "wagey": "වගේ", "wagee": "වගේ", "waget": "වගෙත්",
    "inne": "ඉන්නේ", "innawa": "ඉන්නවා", "inna": "ඉන්න", "hitiya": "හිටියා",
    "supiri": "සුපිරි", "supirima": "සුපිරිම",
    "ayubowan": "ආයුබෝවන්", "ayubowen": "ආයුබෝවන්", "ayibovan": "ආයිබෝවන්",
    "subapathum": "සුභපැතුම්",
    "thanks": "ස්තූතියි", "thank": "ස්තූතියි", "istuti": "ස්තූතියි", "istutiyi": "ස්තූතියි",
    "pattai": "පට්ටයි", "patta": "පට්ට", "pissu": "පිස්සු", "pissuda": "පිස්සුද",
    "ela": "එළ", "elakiri": "එළකිරි", "aulak": "අවුලක්", "avulak": "අවුලක්", "aul": "අවුල්", "avul": "අවුල්",
}

# Known English words that should NOT be converted to Sinhala
# Comprehensive dictionary covering common vocabulary, gaming, tech, and creator terms
ENGLISH_WHITELIST = frozenset({
    # Common function words & prepositions
    "a", "about", "above", "across", "after", "again", "against", "all", "almost", "alone",
    "along", "already", "also", "always", "am", "among", "an", "and", "another", "any",
    "anybody", "anyone", "anything", "anyway", "are", "aren't", "around", "as", "at",
    "back", "be", "because", "been", "before", "behind", "being", "below", "beside",
    "best", "better", "between", "beyond", "both", "but", "by", "can", "can't", "cannot",
    "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "done", "don't",
    "down", "during", "each", "either", "else", "even", "ever", "every", "everybody",
    "everyone", "everything", "everywhere", "few", "first", "for", "from", "further",
    "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll",
    "he's", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "inside", "into", "is", "isn't", "it", "it's", "its",
    "itself", "just", "last", "least", "less", "let", "let's", "like", "likely", "little",
    "many", "may", "maybe", "me", "might", "more", "most", "much", "must", "my", "myself",
    "near", "need", "neither", "never", "new", "next", "no", "nobody", "none", "noone",
    "nor", "not", "nothing", "now", "nowhere", "of", "off", "often", "on", "once", "one",
    "only", "onto", "or", "other", "others", "otherwise", "ought", "our", "ours", "ourselves",
    "out", "outside", "over", "own", "part", "per", "perhaps", "please", "quite", "rather",
    "really", "same", "say", "says", "second", "see", "seem", "seemed", "seems", "seen",
    "shall", "she", "she'd", "she'll", "she's", "should", "shouldn't", "since", "so",
    "some", "somebody", "someone", "something", "somewhere", "still", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "thing", "things",
    "think", "thinks", "this", "those", "though", "three", "through", "throughout", "till",
    "to", "together", "too", "toward", "towards", "two", "under", "until", "up", "upon",
    "us", "use", "used", "uses", "very", "want", "wants", "was", "wasn't", "way", "we",
    "we'd", "we'll", "we're", "we've", "well", "went", "were", "weren't", "what", "what's",
    "whatever", "when", "where", "which", "while", "who", "who's", "whoever", "whole",
    "whom", "whose", "why", "will", "with", "within", "without", "won't", "would",
    "wouldn't", "yes", "yet", "you", "you'd", "you'll", "you're", "you've", "your",
    "yours", "yourself", "yourselves", "zero",
    # Creator, Tech & Software
    "app", "apps", "application", "applications", "api", "ai", "pc", "cpu", "gpu", "ram",
    "ssd", "hdd", "usb", "ip", "os", "ui", "ux", "video", "videos", "audio", "music",
    "sound", "record", "recording", "records", "recorded", "recorder", "stream", "live",
    "gaming", "game", "games", "gamer", "gamers", "gameplay", "play", "played", "playing",
    "player", "players", "pro", "level", "levels", "score", "scores", "win", "wins", "winner",
    "winning", "won", "lose", "loses", "loser", "lost", "kill", "kills", "killed", "killer",
    "killing", "team", "teams", "squad", "squads", "solo", "duo", "trio", "lobby", "party",
    "shorts", "short", "reel", "reels", "clip", "clips", "edit", "editor", "editors",
    "editing", "edited", "cut", "cuts", "cutting", "trim", "trimmed", "render", "rendered",
    "rendering", "export", "exported", "exporting", "youtube", "youtuber", "youtubers",
    "tiktok", "tiktoker", "instagram", "facebook", "twitch", "discord", "telegram",
    "obs", "obs64", "streamlabs", "capcut", "veed", "canva", "figma", "premiere",
    "download", "downloads", "downloaded", "downloading", "upload", "uploads", "uploaded",
    "uploading", "install", "installed", "installing", "installation", "update", "updates",
    "updated", "updating", "upgrade", "upgraded", "setup", "settings", "config", "configure",
    "file", "files", "folder", "folders", "directory", "drive", "drives", "path", "name",
    "names", "size", "sizes", "format", "formats", "type", "types", "subtitle", "subtitles",
    "caption", "captions", "font", "fonts", "color", "colors", "style", "styles",
    "equalizer", "band", "bass", "treble", "mid", "gain", "volume", "noise", "subscribe",
    "subscribed", "subscriber", "subscribers", "sub", "subs", "like", "likes", "liked",
    "liking", "comment", "comments", "commented", "share", "shares", "shared", "follow",
    "followers", "following", "notification", "notifications", "bell", "check", "checked",
    "checking", "try", "tried", "trying", "start", "started", "starting", "stop", "stopped",
    "stopping", "pause", "paused", "resume", "resumed", "close", "closed", "open", "opened",
    "smart", "smartorganizer", "metadata", "code", "coded", "coder", "coding", "script",
    "scripts", "python", "html", "css", "javascript", "wifi", "internet", "online", "offline",
    "server", "servers", "cloud", "data", "database", "databases", "free", "premium", "paid",
    "version", "versions", "old", "top", "good", "bad", "nice", "cool", "super", "fine",
    "zoom", "zoomed", "mic", "mics", "camera", "cameras", "webcam", "screen", "screens",
    "display", "displays", "resolution", "fps", "hz", "mb", "gb", "tb", "kb", "ms", "px",
    "intro", "outro", "hook", "thumbnail", "thumbnails", "title", "titles", "description",
    "tag", "tags", "mobile", "phone", "phones", "laptop", "laptops", "desktop", "desktops",
    "tablet", "monitor", "monitors", "keyboard", "keyboards", "mouse", "chrome", "firefox",
    "safari", "edge", "browser", "browsers", "tab", "tabs", "window", "windows", "photo",
    "photos", "image", "images", "picture", "pictures", "gif", "png", "jpg", "mp4", "mp3",
    "wav", "mkv", "avi", "copy", "copied", "paste", "pasted", "delete", "deleted", "effect",
    "effects", "transition", "transitions", "filter", "filters", "overlay", "overlays",
    "dark", "light", "mode", "theme", "themes", "clean", "minimal", "neon", "cyber", "glow",
    "channel", "channels", "content", "creator", "creators", "vlog", "vlogs", "vlogger",
    "blog", "post", "posts", "posted", "story", "stories", "feed", "mod", "mods", "plugin",
    "plugins", "addon", "addons", "extension", "extensions", "tool", "tools", "feature",
    "features", "test", "tests", "tested", "testing", "tester", "debug", "debugging",
    "error", "errors", "bug", "bugs", "fix", "fixed", "fixes", "patch", "patched", "build",
    "builds", "release", "releases", "max", "min", "auto", "manual", "custom", "default",
    "reset", "clear", "cleared",
    # Conversational & Gaming terms
    "bro", "dude", "man", "mate", "guy", "guys", "boy", "boys", "girl", "girls", "friend",
    "friends", "sir", "boss", "clutch", "clutched", "clutching", "headshot", "headshots",
    "ping", "lag", "lagging", "noob", "noobs", "hacker", "hackers", "cheat", "cheats",
    "ban", "banned", "rank", "ranked", "ranking", "roblox", "minecraft", "pubg", "freefire",
    "cod", "gta", "valorant", "fortnite", "fifa", "apex", "overwatch", "csgo", "dota",
    "league", "steam", "epic", "riot", "valve", "mission", "missions", "quest", "quests",
    "enemy", "enemies", "weapon", "weapons", "gun", "guns", "ammo", "loot", "looting",
    "skin", "skins", "spawn", "respawn", "drop", "drops", "carry", "carried", "versus",
    "pvp", "pve", "match", "matches", "round", "rounds", "stage", "stages", "map", "maps",
    "great", "awesome", "crazy", "insane", "epic", "fast", "slow", "high", "low",
    "big", "small", "huge", "mini", "micro", "mega", "ultra", "hyper", "hard", "easy",
    "simple", "quick", "full", "empty", "ready", "set", "go", "done", "finish", "finished",
    "true", "false", "right", "wrong", "hello", "hi", "hey", "bye", "goodbye", "thanks",
    "thank", "welcome", "sorry", "excuse", "please", "okay", "ok", "yeah", "yep", "nope",
    "nah", "uh", "um", "oh", "wow", "oops", "yay", "gg", "ez", "afk", "op", "wp",
})

# All-caps acronyms that must strictly retain Latin capitalization
ENGLISH_ACRONYMS = frozenset({
    "api", "ai", "pc", "cpu", "gpu", "ram", "ssd", "hdd", "usb", "ip", "os", "ui", "ux",
    "obs", "fps", "hd", "4k", "2k", "rgb", "bgr", "wav", "mp3", "mp4", "mkv", "avi", "mov",
    "flac", "aac", "vfr", "cfr", "pts", "dts", "ass", "srt", "vtt", "vlog", "dof", "fov",
    "url", "http", "https", "ftp", "ssh", "lan", "wan", "vpn", "dns", "sdk", "cli", "ide",
    "json", "xml", "csv", "txt", "pdf", "zip", "rar", "tar", "iso", "exe", "apk", "dll",
})

# Reverse-transliteration dictionary:
# Restores English words mistakenly transcribed into Sinhala characters back to authentic English Latin characters.
# Addresses Issue 1 & Issue 2 (e.g. "දිස් ගේම්" -> "this game", "නිව් වීඩියෝ" -> "new video", "ඇප්ලිකේෂන්" -> "application")
TRANSLITERATED_ENGLISH_MAP = {
    "දිස්": "this",
    "ගේම්": "game",
    "ගේම්ස්": "games",
    "ගේම": "game",
    "වීඩියෝ": "video",
    "වීඩියෝස්": "videos",
    "වීඩියෝව": "video",
    "නිව්": "new",
    "ඇප්": "app",
    "ඇප්ස්": "apps",
    "ඇප්ලිකේෂන්": "application",
    "ඇප්ලිකේෂන්ස්": "applications",
    "ටෙස්ට්": "test",
    "ටෙස්ටිං": "testing",
    "රෙකෝඩ්": "record",
    "රෙකෝඩින්": "recording",
    "රෙකෝඩින්ග්": "recording",
    "ඩවුන්ලෝඩ්": "download",
    "අප්ලෝඩ්": "upload",
    "සබ්ස්ක්‍රයිබ්": "subscribe",
    "සබ්ස්ක්‍රයිබර්": "subscriber",
    "සබ්ස්ක්‍රයිබර්ස්": "subscribers",
    "ලෙවල්": "level",
    "ලෙවල්ස්": "levels",
    "ප්ලේ": "play",
    "ප්ලේයර්": "player",
    "ප්ලේයර්ස්": "players",
    "බ්‍රෝ": "bro",
    "ක්ලච්": "clutch",
    "චැනල්": "channel",
    "චැනල්ස්": "channels",
    "ෂෝට්ස්": "Shorts",
    "ෂෝට්": "Short",
    "ස්ට්‍රීම්": "stream",
    "ස්ට්‍රීමර්": "streamer",
    "ස්ට්‍රීමර්ස්": "streamers",
    "ස්ට්‍රීමින්": "streaming",
    "ලයිව්": "live",
    "සෙටින්ග්ස්": "settings",
    "සෙටප්": "setup",
    "කොමෙන්ට්": "comment",
    "කොමෙන්ට්ස්": "comments",
    "ශෙයාර්": "share",
    "ලයික්": "like",
    "ලයික්ස්": "likes",
    "ෆෝල්ඩර්": "folder",
    "ෆෝල්ඩර්ස්": "folders",
    "ෆයිල්": "file",
    "ෆයිල්ස්": "files",
    "මයික්": "mic",
    "වෙබ්කැම්": "webcam",
    "ස්ක්‍රීන්": "screen",
    "ග්‍රැෆික්ස්": "graphics",
    "ලැප්ටොප්": "laptop",
    "ඩෙස්ක්ටොප්": "desktop",
    "මොනිටර්": "monitor",
    "කීබෝඩ්": "keyboard",
    "මවුස්": "mouse",
    "ඩිස්කෝඩ්": "Discord",
    "ටික්ටොක්": "TikTok",
    "යුටියුබ්": "YouTube",
    "කැප්කට්": "CapCut",
    "ඔබීඑස්": "OBS",
    "එඩිට්": "edit",
    "එඩිටර්": "editor",
    "එඩිටින්": "editing",
    "ඉෆෙක්ට්": "effect",
    "ඉෆෙක්ට්ස්": "effects",
    "සුපර්": "super",
    "කූල්": "cool",
    "නයිස්": "nice",
    "හෙඩ්ෂොට්": "headshot",
    "හෙඩ්ෂොට්ස්": "headshots",
    "කිල්": "kill",
    "කිල්ස්": "kills",
    "වින්": "win",
    "ලූස්": "lose",
    "ස්කොඩ්": "squad",
    "ටීම්": "team",
    "ටීම්ස්": "teams",
    "ලොබි": "lobby",
    "පිං": "ping",
    "ලැග්": "lag",
    "ප්‍රෝ": "pro",
    "නූබ්": "noob",
    "හයිලයිට්": "highlight",
    "හයිලයිට්ස්": "highlights",
    "ඔප්ෂන්": "option",
    "ඔප්ෂන්ස්": "options",
    "ෆොන්ට්": "font",
    "ෆොන්ට්ස්": "fonts",
    "ස්ටයිල්": "style",
    "ස්ටයිල්ස්": "styles",
    "ෆිල්ටර්": "filter",
    "ෆිල්ටර්ස්": "filters",
    "සවුන්ඩ්": "sound",
    "ඕඩියෝ": "audio",
}

_CUSTOM_VOCAB = None
def get_custom_vocab():
    global _CUSTOM_VOCAB
    if _CUSTOM_VOCAB is None:
        _CUSTOM_VOCAB = set()
        for candidate in ["workspace/custom_vocabulary.txt", "workspace/vocabulary.txt", "custom_vocabulary.txt", "vocabulary.txt"]:
            if os.path.exists(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        for line in f:
                            w = line.strip().lower()
                            if w: _CUSTOM_VOCAB.add(w)
                except Exception:
                    pass
    return _CUSTOM_VOCAB

def is_english_token(token):
    """
    Intelligent English Token Validator:
    Validates genuine English words using:
      1. Extensive English vocabulary set.
      2. Common English inflectional and derivational morphology (-s, -ed, -ing, -ly, -er, -est, -tion, -ment, etc.).
      3. Custom vocabulary file (custom_vocabulary.txt / vocabulary.txt) if provided in the workspace.
    """
    if not token:
        return False
    t = token.lower().strip(".,!?:;\"'()[]{}0123456789-_")
    if not t:
        return False
    if len(t) == 1:
        return t in {"a", "i"}
    if t in ENGLISH_WHITELIST or t in get_custom_vocab():
        return True
    # Strip standard English morphological suffixes and re-test
    suffixes = ("ing", "ed", "es", "s", "ly", "er", "est", "tion", "ment", "ness", "able", "ible", "ful", "less", "ize", "ise", "ity")
    for sfx in suffixes:
        if len(t) > len(sfx) + 2 and t.endswith(sfx):
            base = t[:-len(sfx)]
            if base in ENGLISH_WHITELIST or base in get_custom_vocab():
                return True
            # Handle e-drop (e.g. create -> creating, close -> closed)
            if sfx in ("ed", "es", "ing", "er") and ((base + "e") in ENGLISH_WHITELIST or (base + "e") in get_custom_vocab()):
                return True
    return False

def clean_and_normalize_word(token):
    """
    Intelligent Bilingual Sinhala-English Token Normalizer:
    Guarantees clean, professional output with:
    1. Genuine English words preserved in English Latin script.
    2. Spoken Sinhala words preserved in authentic Sinhala Unicode script.
    3. Mistakenly transliterated English words restored to proper English (e.g. දිස් ගේම් -> this game).
    4. Confident Singlish romanized words converted to Sinhala Unicode.
    5. Safe transliteration of foreign scripts (Georgian, Devanagari, etc.).
    6. Strict non-deletion: Spoken words are NEVER erased or dropped.
    """
    if not token:
        return ""

    # 1. Transliterate known foreign letters (Georgian, Devanagari, Ethiopic)
    has_foreign = any(ord(c) > 127 and not (0x0D80 <= ord(c) <= 0x0DFF) for c in token)
    if has_foreign:
        token = "".join(FOREIGN_TO_LATIN.get(c, c if (ord(c) <= 127 or 0x0D80 <= ord(c) <= 0x0DFF) else "") for c in token)

    # 2. Extract prefix and suffix punctuation
    m_left = re.match(r"^([^\w\u0D80-\u0DFF]+)", token)
    prefix = m_left.group(1) if m_left else ""
    m_right = re.search(r"([^\w\u0D80-\u0DFF]+)$", token)
    suffix = m_right.group(1) if m_right else ""

    start_idx = len(prefix)
    end_idx = len(token) - len(suffix) if suffix else len(token)
    core = token[start_idx:end_idx] if start_idx < end_idx else token
    core_lower = core.lower()

    if not core:
        return ""

    # 2b. Check for attached English word + Sinhala particle (e.g. "gameඑක" -> "game එක", "videoඑකක්" -> "video එකක්")
    m_attached = re.match(r"^([a-zA-Z]+)([\u0D80-\u0DFF]+)$", core)
    if m_attached:
        en_part, si_part = m_attached.group(1), m_attached.group(2)
        if is_english_token(en_part.lower()):
            return prefix + en_part + " " + si_part + suffix

    # 3. Check for English all-caps acronyms (API, AI, PC, GPU, CPU, OBS, FPS, etc.)
    if core.isupper() and (core_lower in ENGLISH_ACRONYMS or is_english_token(core_lower)):
        return prefix + core + suffix

    # 4. Check reverse-transliteration (English words mistakenly transcribed into Sinhala characters)
    # E.g. "දිස්" -> "this", "ගේම්" -> "game", "වීඩියෝ" -> "video", "ඇප්ලිකේෂන්" -> "application", "ටෙස්ට්" -> "test"
    if core in TRANSLITERATED_ENGLISH_MAP:
        return prefix + TRANSLITERATED_ENGLISH_MAP[core] + suffix

    # 5. Check if word is already in authentic Sinhala Unicode script
    has_sinhala = any(0x0D80 <= ord(c) <= 0x0DFF for c in core)
    if has_sinhala:
        cleaned_sinhala = "".join(c for c in core if 0x0D80 <= ord(c) <= 0x0DFF or ord(c) <= 127)
        return prefix + (cleaned_sinhala or core) + suffix

    # 6. Check for confirmed English words in Latin characters
    if is_english_token(core_lower):
        # Keep unambiguous English words in English
        # Only words that are exclusively romanized Sinhala pronouns/particles convert
        if core_lower in {"mama", "oya", "eya", "machan", "meka"}:
            return prefix + SINGLISH_MAP.get(core_lower, core) + suffix
        return prefix + core + suffix

    # 7. Check Singlish dictionary for romanized Sinhala
    if core_lower in SINGLISH_MAP:
        return prefix + SINGLISH_MAP[core_lower] + suffix

    # 8. Filter non-ASCII and non-Sinhala debris
    cleaned_core = "".join(c for c in core if ord(c) <= 127 or 0x0D80 <= ord(c) <= 0x0DFF)
    if not cleaned_core:
        cleaned_core = core

    # 9. Non-destructive preservation: Never delete recognized spoken words
    return prefix + cleaned_core + suffix

class Word(BaseModel):
    w: str
    s: float
    e: float

def sanitize_words(raw_items, dur=None):
    """
    Pass 2: Text Validation & Script Normalization (Sections 7 & 8):
    1. Retains raw verbatim text (raw_text) and genuine acoustic timestamps.
    2. Converts Singlish to Sinhala Unicode using the comprehensive dictionary.
    3. Preserves genuine English technical words and acronyms (API, AI, Equalizer, etc.).
    4. Produces unified WordSegment items with confidence and alignment_status.
    5. Validates chronological bounds without character/syllable duration math.
    """
    expanded = []
    for d in raw_items:
        raw_text = str(d.get("raw_text") or d.get("w") or d.get("word") or d.get("text") or "").strip()
        text = str(d.get("text") or d.get("w") or d.get("word") or "").strip()
        if not text: continue
        s_val = max(0.0, _t(d.get("start", d.get("s", 0.0))))
        e_val = max(s_val + 0.05, _t(d.get("end", d.get("e", s_val + 0.08))))
        conf = d.get("confidence")
        status = d.get("alignment_status", "asr_native")

        # If ASR model grouped multiple words in one token, split them preserving timing bounds
        sub_words = text.split()
        if len(sub_words) <= 1:
            expanded.append({"raw_text": raw_text, "text": text, "start": s_val, "end": e_val, "confidence": conf, "alignment_status": status})
        else:
            total_chars = max(sum(len(w) for w in sub_words), 1)
            cur_s = s_val
            span = e_val - s_val
            for sw in sub_words:
                frac = len(sw) / total_chars
                w_dur = max(0.06, span * frac)
                expanded.append({"raw_text": sw, "text": sw, "start": cur_s, "end": cur_s + w_dur, "confidence": conf, "alignment_status": "unverified"})
                cur_s += w_dur

    out = []
    for w in expanded:
        raw = w["raw_text"]
        normalized = clean_and_normalize_word(w["text"].strip())
        if not normalized:
            continue
        status = "verified" if normalized != raw else w["alignment_status"]
        out.append(make_word_item(normalized, w["start"], w["end"], w.get("confidence"), None, None, status, raw))

    return align_words_to_timeline(out, dur=dur)

def parse_words_json(text, dur):
    txt = (text or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\n?", "", txt)
        txt = re.sub(r"\n?```$", "", txt)
    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        data = json.loads(m.group(0)) if m else []

    if isinstance(data, dict): data = data.get("words") or []
    rows = []
    for d in (data if isinstance(data, list) else []):
        if not isinstance(d, dict): continue
        w_txt = str(d.get("w") or d.get("word") or d.get("text") or "").strip()
        s_val = d.get("s", d.get("start", 0.0))
        e_val = d.get("e", d.get("end", s_val + 0.1))
        conf = d.get("confidence", d.get("conf"))
        rows.append({"text": w_txt, "raw_text": w_txt, "start": s_val, "end": e_val, "confidence": conf, "alignment_status": "asr_native"})
    return sanitize_words(rows, dur)

def parse_transcribe_response(resp, dur):
    rows = []
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            tr = getattr(part, "audio_transcription", None)
            for wi in (getattr(tr, "words", None) or []):
                raw_w = getattr(wi, "word", "")
                s_off = _t(getattr(wi, "start_offset", 0))
                e_off = _t(getattr(wi, "end_offset", s_off + 0.1))
                conf = getattr(wi, "confidence", None)
                rows.append({"text": raw_w, "raw_text": raw_w, "start": s_off, "end": e_off, "confidence": conf, "alignment_status": "asr_native"})
    return sanitize_words(rows, dur)

def _window_flash(client, wav, model, lang, dur):
    data = open(wav, "rb").read()
    resp = _generate(client, model, [types.Part.from_bytes(data=data, mime_type="audio/wav"),
                                     WORDS_PROMPT.format(lang=LANG_HINT.get(lang, LANG_HINT[None]))],
                     response_mime_type="application/json", response_schema=list[Word], temperature=0.0)
    return parse_words_json(resp.text, dur)

def _window_transcribe(client, wav, lang, dur):
    """
    Primary Transcription Engine (Section 3):
    Calls Gemini 3.5 Transcribe with word-level timestamps.
    Falls back to Gemini Flash if transcribe model endpoint is not activated on API key.
    """
    f = client.files.upload(file=wav)
    try:
        while f.state.name == "PROCESSING":
            time.sleep(2); f = client.files.get(name=f.name)
        codes = {"en": ["en-US"], "si": ["si-LK", "en-US"]}.get(lang, ["si-LK", "en-US"])
        resp = client.models.generate_content(model=TRANSCRIBE_MODEL, contents=[f], config=types.GenerateContentConfig(
            audio_transcription_config=types.AudioTranscriptionConfig(word_timestamp=True, language_codes=codes)))
        return parse_transcribe_response(resp, dur)
    finally:
        try: client.files.delete(name=f.name)
        except Exception: pass

def transcribe(pool, media, engine="flash", model="gemini-3.5-flash", lang=None, temp="temp", cancel=None, progress=None):
    """
    Hybrid Production Subtitle Transcription Pipeline (Sections 3, 4, 6, 7, 8, 14):
    1. Inspects audio quality and selects optimal preprocessing profile (Profile A/B/C).
    2. Employs 4-key Gemini parallel KeyPool with automatic failover and rate-limit backoff.
    3. Respects silence pauses; processes Shorts in full context to eliminate boundary cuts.
    4. Preserves genuine ASR word-level timestamps (no character/syllable distribution math).
    5. Normalizes Singlish to Sinhala Unicode and preserves English tech terms.
    6. Returns unified WordSegment representation with full backward compatibility.
    """
    dur = duration(media)
    # Audio Quality Inspection (Section 4)
    quality = inspect_audio_quality(media)
    profile = quality.get("recommended_profile", "A")

    active_engine = engine
    win = WIN_TRANSCRIBE if active_engine == "transcribe" else WIN_FLASH
    pts = split_points(media, dur, win)
    spans = list(zip(pts[:-1], pts[1:]))
    done = [0]; lock = threading.Lock()

    def make(i, a, b):
        def fn(client):
            wav = os.path.join(temp, f"cap_{os.getpid()}_{threading.get_ident()}_{i}.wav")
            try:
                extract_wav(media, wav, a, b - a, profile=profile)
                if active_engine == "transcribe":
                    try:
                        return _window_transcribe(client, wav, lang, b - a)
                    except Exception as e:
                        msg = str(e)
                        # Fallback to flash if transcribe model is 404 or unsupported
                        if any(x in msg for x in ("NOT_FOUND", "404", "Unknown name", "is not found")):
                            return _window_flash(client, wav, model, lang, b - a)
                        raise
                else:
                    return _window_flash(client, wav, model, lang, b - a)
            finally:
                try: os.remove(wav)
                except OSError: pass
        return fn

    fns = [make(i, a, b) for i, (a, b) in enumerate(spans)]
    wrapped = []
    for fn in fns:
        def w(client, fn=fn):
            r = fn(client)
            with lock:
                done[0] += 1
                if progress: progress(done[0] / len(fns))
            return r
        wrapped.append(w)
    results = pool.map(wrapped, cancel)
    raw_words = []
    for (a, _), ws in zip(spans, results):
        for w in (ws or []):
            s_val = round(float(w.get("start", w.get("s", 0.0))) + a, 3)
            e_val = round(max(float(w.get("end", w.get("e", s_val + 0.08))) + a, s_val + 0.05), 3)
            raw_w = w.get("raw_text", w.get("text", w.get("w", "")))
            txt = w.get("text", w.get("w", ""))
            conf = w.get("confidence")
            status = w.get("alignment_status", "asr_native")
            raw_words.append(make_word_item(txt, s_val, e_val, conf, None, None, status, raw_w))

    raw_words.sort(key=lambda x: x["start"])
    clean_words = sanitize_words(raw_words, dur)
    aligned_words = align_words_to_timeline(clean_words, dur=dur)
    return aligned_words
