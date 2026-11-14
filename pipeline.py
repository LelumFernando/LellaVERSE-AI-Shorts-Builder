"""Background job runner - Adaptive low-end PC concurrency + Hardware encoding.
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import gc, hashlib, json, os, re, shutil, threading, traceback
from concurrent.futures import ThreadPoolExecutor
import sfx as sfxmod
from color_engine import auto_style
from gemini_engine import (KeyPool, find_shorts, transcribe as gem_transcribe,
                           detect_acoustic_bursts, align_words_to_bursts,
                           convert_global_words_to_cuts)
from subtitle_engine import transcribe_words, build_ass, build_srt
from video_editor import (render_super_edit, burn_subtitles, render_zoom_burn, frame_dims, pause_cuts,
                          video_duration, detect_hardware_encoders, validate_exported_clip)

class Cancelled(BaseException):
    """BaseException so generic `except Exception` blocks never swallow a user cancel."""

class Job:
    def __init__(self):
        self.p, self.msg, self.state, self.info = 0.0, "Starting…", "running", ""
        self.results, self.error, self.trace, self.cancel, self.notified = [], None, "", False, False

    def set(self, p, msg=None):
        if self.cancel: raise Cancelled()
        self.p = max(0.0, min(p, 1.0))
        if msg: self.msg = msg

def _safe(name):
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "video"

def _captions(c, pool, media, job, progress=None):
    """Word-level captions with chosen engine (Gemini Flash default)."""
    if c["engine"] == "whisper":
        return transcribe_words(media, c.get("wsize", "small"), c.get("lang"), progress)
    return gem_transcribe(pool, media, c.get("engine", "flash"), c.get("model", "gemini-3.5-flash"),
                          c.get("lang"), c.get("temp", "temp"), lambda: job.set(job.p), progress)

# ====================================================================== MODE 1 - Stream -> Montage Shorts
def _finish(job, c, pool, k, sh, rawp, n):
    """Captions + styling + burn + quality validation for one Short."""
    temp, out_dir, fonts = c["temp"], c["out_dir"], c["fonts"]
    vid = os.path.splitext(os.path.basename(c["video"]))[0]
    assp, finp = os.path.join(temp, f"{vid}_sub{k}.ass"), os.path.join(temp, f"{vid}_short{k+1}.mp4")
    words, err, style = [], None, c["style"]
    if c.get("global_words") and sh.get("cuts"):
        words = convert_global_words_to_cuts(c["global_words"], sh["cuts"])
    if not words:
        try:
            words = _captions(c, pool, rawp, job)
        except Exception as e:
            err = str(e)
        
    if style.get("auto_color"):
        try: style = auto_style(rawp, style)
        except Exception: pass

    if words:
        build_ass(words, style, 1080, 1920, out_path=assp, fonts_dir=fonts)
        burn_subtitles(rawp, assp, finp, fonts, c.get("encoder"))
    else:
        shutil.copy(rawp, finp)

    if job.cancel: raise Cancelled()
    final = os.path.join(out_dir, os.path.basename(finp))
    shutil.copy(finp, final)
    
    # Automated Quality Control Validation (Part 8)
    qc = validate_exported_clip(final)

    for t in (rawp, assp, finp):
        try: os.remove(t)
        except OSError: pass

    length = sum(b - a for a, b in sh["cuts"])
    res = {
        "clip_num": k + 1,
        "title": sh["title"],
        "description": sh["description"],
        "score": sh["score"],
        "cuts": len(sh["cuts"]),
        "cuts_data": sh["cuts"],
        "source_start": sh["cuts"][0][0] if sh["cuts"] else 0.0,
        "source_end": sh["cuts"][-1][1] if sh["cuts"] else 0.0,
        "length": length,
        "path": final,
        "captions": bool(words),
        "caption_error": err,
        "colors": (style.get("primary"), style.get("highlight")) if style.get("auto_color") else None,
        "qc": qc,
        "qc_valid": qc.get("valid", False),
        "layout": c.get("layout", "split")
    }
    job.results.append(res)
    job.msg = f"✅ Short {k+1}/{n} ready (QC: {'PASSED' if qc.get('valid') else 'REVIEW'})"
    gc.collect()
    return res

def _run(job, c):
    temp, out_dir = c["temp"], c["out_dir"]
    ex = None
    try:
        os.makedirs(temp, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
        hw = detect_hardware_encoders()
        encoder = c.get("encoder") or hw["best"]
        job.info = f"🚀 Acceleration: {hw['descriptions'].get(encoder, encoder)}"

        pool = KeyPool(c["api_keys"])
        job.set(0.02, f"🧠 Gemini is analysing stream highlights ({pool.size} key{'s' if pool.size > 1 else ''})…")
        shorts = find_shorts(pool, c["video"], c["model"], c["n"], temp,
                             lambda: job.set(job.p),
                             lambda f, m: job.set(0.02 + 0.18 * f, m))
        if not shorts:
            raise RuntimeError("Gemini found no usable highlights. Try selecting another segment or model.")

        vid = os.path.splitext(os.path.basename(c["video"]))[0]
        cores = os.cpu_count() or 4
        # Adaptive concurrency for low-end PCs: 1 worker avoids thermal throttling and lag
        max_w = 1 if (cores <= 4 or c.get("low_end_mode", True)) else 2
        ex = ThreadPoolExecutor(max_workers=max_w)
        futs = []; N = len(shorts)

        for k, sh in enumerate(shorts):
            base, span = 0.2 + 0.7 * k / N, 0.7 / N
            rawp = os.path.join(temp, f"{vid}_raw{k}.mp4")
            job.set(base, f"✂️ Editing Short {k+1}/{N} · {sh['title']} ({len(sh['cuts'])} cuts)")
            render_super_edit(
                src=c["video"], cuts=sh["cuts"], out=rawp, roi=c["roi"],
                motion=c.get("motion", True), encoder=encoder,
                punch=0.10 if c.get("punch", True) else 0.0,
                sfx=c.get("sfx", True), temp_dir=temp,
                progress_cb=lambda f: job.set(base + span * f),
                layout=c.get("layout", "split"),
                sfx_vol=c.get("sfx_vol", 0.8)
            )
            futs.append(ex.submit(_finish, job, c, pool, k, sh, rawp, N))

        job.set(0.9, "💬 Generating captions & burning subtitles…")
        for i, f in enumerate(futs):
            f.result()
            job.set(0.9 + 0.1 * (i + 1) / N)

        job.set(1.0, "✅ Done! All Shorts ready.")
        job.state = "done"
    except Cancelled:
        job.state, job.msg = "cancelled", "Cancelled"
    except Exception as e:
        job.state, job.error, job.trace = "error", str(e), traceback.format_exc()
    finally:
        if ex: ex.shutdown(wait=False, cancel_futures=True)
        try:
            vid = os.path.splitext(os.path.basename(c["video"]))[0]
            for f in os.listdir(temp):
                if f.startswith("proxy_") or (f.startswith(vid + "_") and f.endswith((".ass", ".mp4", ".wav"))):
                    try: os.remove(os.path.join(temp, f))
                    except OSError: pass
        except Exception: pass
        gc.collect()

def start_job(cfg):
    job = Job()
    threading.Thread(target=_run, args=(job, cfg), daemon=True).start()
    return job

def regenerate_single_short(job, c, sh, k=0):
    """
    Regenerates a single Short without re-analyzing the livestream (Part 8).
    Allows quick style/layout tweaking and re-export.
    """
    temp = c["temp"]
    vid = os.path.splitext(os.path.basename(c["video"]))[0]
    rawp = os.path.join(temp, f"{vid}_regen_raw{k}.mp4")
    hw = detect_hardware_encoders()
    encoder = c.get("encoder") or hw["best"]
    pool = KeyPool(c["api_keys"]) if c.get("api_keys") else None
    
    render_super_edit(
        src=c["video"], cuts=sh["cuts"], out=rawp, roi=c["roi"],
        motion=c.get("motion", True), encoder=encoder,
        punch=0.10 if c.get("punch", True) else 0.0,
        sfx=c.get("sfx", True), temp_dir=temp,
        progress_cb=lambda f: job.set(0.1 + 0.5 * f, f"✂️ Re-rendering Short {k+1}… {f:.0%}"),
        layout=c.get("layout", "split"),
        sfx_vol=c.get("sfx_vol", 0.8)
    )
    job.set(0.65, "💬 Re-generating subtitles…")
    return _finish(job, c, pool, k, sh, rawp, 1)

def start_regen_job(cfg, short_data, k):
    job = Job()
    def fn():
        try:
            job.state = "running"
            res = regenerate_single_short(job, cfg, short_data, k)
            job.results = [res]
            job.set(1.0, "✅ Short regenerated successfully!")
            job.state = "done"
        except Exception as e:
            job.state, job.error, job.trace = "error", str(e), traceback.format_exc()
    threading.Thread(target=fn, daemon=True).start()
    return job

# ====================================================================== MODE 2 - Subtitle Studio
def _words_for(job, c, pool):
    """Transcribe once; cached so re-styling / re-burning takes seconds without API costs."""
    v = c["video"]
    key = hashlib.md5(f"{v}|{os.path.getsize(v)}|{os.path.getmtime(v)}|{c['engine']}|{c['model']}|{c.get('wsize')}|{c.get('lang')}".encode()).hexdigest()[:12]
    cp = os.path.join(c["temp"], f"words_{key}.json")
    words = None
    if os.path.exists(cp):
        try: words = json.load(open(cp, encoding="utf-8"))
        except Exception: words = None
    if not words:
        job.set(0.04, "💬 Transcribing speech with " + ("Whisper…" if c["engine"] == "whisper" else f"Gemini ({pool.size} key{'s' if pool.size > 1 else ''})…"))
        words = _captions(c, pool, job=job, media=v, progress=lambda f: job.set(0.05 + 0.5 * f, f"💬 Transcribing… {f:.0%}"))

    # Ground every word acoustically to real speech bursts for super-sync
    try:
        dur = video_duration(v)
        bursts = detect_acoustic_bursts(v, dur)
        words = align_words_to_bursts(words, bursts)
    except Exception:
        pass

    try: json.dump(words, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError: pass
    return words

def _studio(job, c):
    try:
        temp, out_dir, fonts, v = c["temp"], c["out_dir"], c["fonts"], c["video"]
        os.makedirs(temp, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
        stem = _safe(os.path.splitext(os.path.basename(v))[0])
        
        hw = detect_hardware_encoders()
        encoder = c.get("encoder") or hw["best"]
        job.info = f"🚀 Acceleration: {hw['descriptions'].get(encoder, encoder)}"

        pool = KeyPool(c["api_keys"]) if c["engine"] != "whisper" else None
        words = _words_for(job, c, pool)
        if not words:
            raise RuntimeError("No speech detected in this video to caption.")

        style = c["style"]
        if style.get("auto_color"):
            job.set(0.55, "🎨 Matching caption colours to video…")
            try: style = auto_style(v, style)
            except Exception: pass
            job.info = (job.info + " · " if job.info else "") + f"🎨 Text {style.get('primary')} · Highlight {style.get('highlight')}"

        job.set(0.58, "📝 Generating subtitle files…")
        srt = build_srt(words, out_path=os.path.join(out_dir, stem + ".srt"))
        W, H = frame_dims(v)
        ass = build_ass(words, style, W, H, out_path=os.path.join(out_dir, stem + ".ass"), fonts_dir=fonts)
        results = [{"kind": "srt", "path": srt}, {"kind": "ass", "path": ass}]

        if c["mode"] == "render":
            final = os.path.join(out_dir, stem + "_subtitled.mp4")
            part = os.path.join(temp, stem + "_render.mp4")
            try:
                if c.get("zoom"):
                    track = None
                    if c.get("sfx"):
                        cuts = pause_cuts(words, c.get("zoom_gap", 0.35))
                        if cuts:
                            track = sfxmod.build_track(os.path.join(temp, stem + "_sfx.wav"),
                                                       video_duration(v), cuts[0::2], gain=c.get("sfx_vol", 0.8))
                    job.set(0.62, "🎯 Rendering with auto zoom punch…")
                    render_zoom_burn(v, ass, part, words, c.get("zoom_strength", 0.08), c.get("zoom_gap", 0.35),
                                     fonts, encoder,
                                     lambda f: job.set(0.62 + 0.38 * f, f"🎯 Rendering with auto zoom… {f:.0%}"),
                                     c.get("clean", False), track)
                else:
                    job.set(0.62, "🎞️ Burning subtitles…")
                    burn_subtitles(v, ass, part, fonts, encoder,
                                   lambda f: job.set(0.62 + 0.38 * f, f"🎞️ Burning subtitles… {f:.0%}"),
                                   c.get("clean", False))
                if os.path.exists(final): os.remove(final)
                shutil.move(part, final)
            finally:
                if os.path.exists(part): os.remove(part)
            results.insert(0, {"kind": "video", "path": final})

        job.results = results
        job.set(1.0, "✅ Done! Files ready in outputs folder.")
        job.state = "done"
    except Cancelled:
        job.state, job.msg = "cancelled", "Cancelled"
    except Exception as e:
        job.state, job.error, job.trace = "error", str(e), traceback.format_exc()
    finally:
        gc.collect()

def start_studio_job(cfg):
    job = Job()
    threading.Thread(target=_studio, args=(job, cfg), daemon=True).start()
    return job
