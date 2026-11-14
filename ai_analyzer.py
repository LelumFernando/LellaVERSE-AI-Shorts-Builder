"""Module B - Gemini multimodal highlight detector (with retry + validation)."""
import json, os, subprocess, time
from google import genai
from google.genai import types

PROMPT = """You are an expert gaming-content editor for YouTube Shorts.
Watch this gaming live-stream (video + audio) and find {n} eye-catching, intense,
funny or high-energy highlight moments. Rules:
- Each highlight is 15-60 seconds long (never longer than 60).
- Start slightly before the action begins and end after the reaction finishes.
- Timestamps are in SECONDS from the start of the video (the video is {dur:.0f}s long).
- Highlights must not overlap. Rank by viral potential (score 1-10).
Return ONLY a JSON array: [{{"start": number, "end": number, "title": string,
"description": string, "score": number}}]"""

def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)

def make_proxy(src, out_dir):
    """Tiny proxy (360p, 1fps) - Gemini samples 1fps anyway; keeps upload fast, local VRAM untouched."""
    proxy = os.path.join(out_dir, "proxy.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", src, "-vf", "scale=-2:360,fps=1", "-c:v", "libx264", "-crf", "34",
                    "-preset", "veryfast", "-ac", "1", "-b:a", "48k", proxy], check=True, capture_output=True)
    return proxy

def _retry(fn, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if any(k in msg for k in ("API key", "API_KEY", "PERMISSION", "401", "403")) or i == tries - 1:
                raise
            time.sleep(4 * (i + 1))        # 429 / 503 / network blips

def find_highlights(api_key, video_path, model="gemini-3.6-flash", n=4, out_dir="workspace", cancel=None, progress_cb=None):
    dur = _duration(video_path)
    client = genai.Client(api_key=api_key)
    f = _retry(lambda: client.files.upload(file=make_proxy(video_path, out_dir)))
    try:
        while f.state.name == "PROCESSING":
            if cancel: cancel()
            time.sleep(3); f = client.files.get(name=f.name)
        if f.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini could not process the video ({f.state.name}).")
        resp = _retry(lambda: client.models.generate_content(
            model=model, contents=[f, PROMPT.format(n=n, dur=dur)],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4)))
    finally:
        try: client.files.delete(name=f.name)
        except Exception: pass
    txt = (resp.text or "").strip().removeprefix("```json").removesuffix("```").strip()
    data = json.loads(txt)
    if isinstance(data, dict):
        data = data.get("highlights", [])
    clips = []
    for h in data:
        try:
            s = max(0.0, float(h["start"])); e = min(float(h["end"]), s + 60, dur or 1e9)
        except (KeyError, TypeError, ValueError):
            continue
        if e - s >= 5 and not any(s < c["end"] and e > c["start"] for c in clips):
            clips.append({"start": s, "end": e, "title": str(h.get("title", "Highlight"))[:80],
                          "description": str(h.get("description", ""))[:200], "score": h.get("score", 0)})
    return sorted(clips, key=lambda c: -float(c["score"] or 0))[:5]