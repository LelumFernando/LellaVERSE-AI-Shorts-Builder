"""Module D - Word-level transcription, Sinhala & English typography, ASS + SRT builders.
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import functools, os, shutil, sys

_models = {}

def get_model(size="small"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Offline Whisper is not installed. Run:  pip install faster-whisper")
    if size not in _models:
        try:
            _models[size] = WhisperModel(size, device="cuda", compute_type="float16")
        except Exception:
            _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[size]

def transcribe_words(path, size="small", language=None, progress_cb=None):
    """Returns unified word items [{'text', 'start', 'end', 'confidence', 'alignment_status', 'w', 's', 'e'}]."""
    from gemini_engine import clean_and_normalize_word
    def run(m):
        segs, info = m.transcribe(path, language=language, word_timestamps=True, vad_filter=True)
        dur = getattr(info, "duration", 0) or 0
        detected_lang = getattr(info, "language", language or "si")
        out = []
        for s in segs:
            for w in (s.words or []):
                txt = w.word.strip()
                if not txt: continue
                norm_txt = clean_and_normalize_word(txt)
                if not norm_txt: continue
                conf = round(float(getattr(w, "probability", 0.9)), 3)
                s_val = round(float(w.start), 3)
                e_val = round(max(s_val + 0.05, float(w.end)), 3)
                out.append({
                    "text": norm_txt,
                    "raw_text": txt,
                    "start": s_val,
                    "end": e_val,
                    "confidence": conf,
                    "language": detected_lang,
                    "speaker": None,
                    "alignment_status": "asr_native",
                    "w": norm_txt,
                    "s": s_val,
                    "e": e_val
                })
            if progress_cb and dur: progress_cb(min(s.end / dur, 1.0))
        return out
    try:
        return run(get_model(size))
    except Exception:
        from faster_whisper import WhisperModel
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
        return run(_models[size])

# ---------------------------------------------------------------- Fonts Management
def ensure_builtin_fonts(src_dir, dst_dir):
    """Copy the bundled fonts (Sinhala + Latin) into the fonts folder FFmpeg reads."""
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.isdir(src_dir):
        for f in os.listdir(src_dir):
            if f.lower().endswith((".ttf", ".otf")) and not os.path.exists(os.path.join(dst_dir, f)):
                try: shutil.copy(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                except OSError: pass

FONT_EXT = (".ttf", ".otf", ".ttc", ".otc")

def _font_dirs():
    if sys.platform.startswith("win"):
        d = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        d = ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        d = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return [x for x in d if x and os.path.isdir(x)]

def _names(path):
    from fontTools.ttLib import TTFont, TTCollection
    out = set()
    try:
        fonts = TTCollection(path, lazy=True).fonts if path.lower().endswith((".ttc", ".otc")) else [TTFont(path, lazy=True)]
        for f in fonts:
            for r in f["name"].names:
                if r.nameID in (1, 16):
                    try: out.add(r.toUnicode().strip().lower())
                    except Exception: pass
    except Exception:
        pass
    return out

@functools.lru_cache(maxsize=1)
def _system_families():
    fams = set()
    for d in _font_dirs():
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(FONT_EXT): fams |= _names(os.path.join(root, f))
    return frozenset(fams)

def _user_families(fonts_dir):
    fams = set()
    if fonts_dir and os.path.isdir(fonts_dir):
        for f in os.listdir(fonts_dir):
            if f.lower().endswith(FONT_EXT): fams |= _names(os.path.join(fonts_dir, f))
    return fams

def resolve_font(family, fonts_dir=None, fallback="Arial"):
    want = (family or "").strip().lower()
    sysf = _system_families()
    if not sysf:
        return (family or fallback), False
    if want and (want in sysf or want in _user_families(fonts_dir)):
        return family, False
    return fallback, True

def font_family_from_file(path):
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=0)
    for rec in f["name"].names:
        if rec.nameID == 1:
            try: return rec.toUnicode()
            except Exception: continue
    return "Arial"

# ---------------------------------------------------------------- Presets
PRESETS = {
    "capcut": {
        "name": "🔥 CapCut Viral (Yellow Glow)",
        "font": "Poppins",
        "size": 66,
        "bold": True,
        "italic": False,
        "upper": False,
        "primary": "#FFFFFF",
        "highlight": "#FFE600",
        "outline": "#000000",
        "outline_w": 4,
        "shadow": 2,
        "bg_on": False,
        "bg_color": "#000000",
        "bg_opacity": 75,
        "anim": "karaoke",
        "words_mode": 3
    },
    "mrbeast": {
        "name": "🌟 MrBeast (Bold & Punchy)",
        "font": "Poppins",
        "size": 70,
        "bold": True,
        "italic": False,
        "upper": True,
        "primary": "#FFFFFF",
        "highlight": "#FFD700",
        "outline": "#000000",
        "outline_w": 4,
        "shadow": 2,
        "bg_on": False,
        "bg_color": "#000000",
        "bg_opacity": 75,
        "anim": "pop",
        "words_mode": 1
    },
    "hormozi": {
        "name": "🚀 Alex Hormozi (Pill Pop)",
        "font": "Poppins",
        "size": 64,
        "bold": True,
        "italic": False,
        "upper": True,
        "primary": "#FFFFFF",
        "highlight": "#39FF14",
        "outline": "#000000",
        "outline_w": 3,
        "shadow": 0,
        "bg_on": True,
        "bg_color": "#000000",
        "bg_opacity": 80,
        "anim": "pop",
        "words_mode": 1
    },
    "sinhala": {
        "name": "🇱🇰 Sinhala Creator Pro (සිංහල)",
        "font": "Noto Sans Sinhala",
        "size": 64,
        "bold": True,
        "italic": False,
        "upper": False,
        "primary": "#FFFFFF",
        "highlight": "#FFCC00",
        "outline": "#000000",
        "outline_w": 4,
        "shadow": 2,
        "bg_on": False,
        "bg_color": "#000000",
        "bg_opacity": 60,
        "anim": "karaoke",
        "words_mode": 3
    },
    "cyber": {
        "name": "⚡ Cyber Neon (LellaVerse Signature)",
        "font": "Noto Sans Sinhala",
        "size": 64,
        "bold": True,
        "italic": False,
        "upper": False,
        "primary": "#FFFFFF",
        "highlight": "#00F0FF",
        "outline": "#7B1FA2",
        "outline_w": 4,
        "shadow": 2,
        "bg_on": False,
        "bg_color": "#000000",
        "bg_opacity": 60,
        "anim": "karaoke",
        "words_mode": 3
    },
    "minimal": {
        "name": "🤍 Clean Minimal",
        "font": "Arial",
        "size": 58,
        "bold": True,
        "italic": False,
        "upper": False,
        "primary": "#FFFFFF",
        "highlight": "#00E5FF",
        "outline": "#000000",
        "outline_w": 3,
        "shadow": 1,
        "bg_on": False,
        "bg_color": "#000000",
        "bg_opacity": 50,
        "anim": "karaoke",
        "words_mode": 3
    }
}

# ---------------------------------------------------------------- ASS Builder
def _clean(w):
    return str(w).replace("{", "(").replace("}", ")").replace("\\", "")

def _bgr(h):
    h = h.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()

def _bgra(h, opacity):
    h = h.lstrip("#")
    a = int(round(255 * (1 - opacity / 100)))
    return f"&H{a:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()

def _t(sec):
    cs = int(round(sec * 100)); h, r = divmod(cs, 360000); m, r = divmod(r, 6000); s, c = divmod(r, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"

def build_ass(words, st, play_w=1080, play_h=1920, max_words=None, out_path="sub.ass", fonts_dir=None):
    """
    Builds dynamic word-level ASS subtitle files:
    - Supports 1-word pop (TikTok style), 2-3 word dynamic phrases, or full lines.
    - True Sinhala font encoding (UTF-8 with BOM for libass).
    - Drop shadow and neon border styles.
    """
    if max_words is None:
        max_words = int(st.get("words_mode", 3))

    sc = min(play_w, play_h) / 1080.0
    fam = resolve_font(st["font"], fonts_dir)[0].replace(",", " ")
    an, xf = {"left": (4, 1 / 12), "center": (5, 0.5), "right": (6, 11 / 12)}[st.get("align", "center")]
    x, y = int(play_w * xf), int(play_h * st.get("y_pct", 70) / 100)
    
    shadow = int(st.get("shadow", 1) * sc)
    if st.get("bg_on"):
        border, outc, ow = 3, _bgra(st.get("bg_color", "#000000"), st.get("bg_opacity", 75)), round(14 * sc, 1)
    else:
        border, outc, ow = 1, _bgra(st.get("outline", "#000000"), 100), round(st.get("outline_w", 3) * sc, 1)
        
    mg = int(40 * sc)
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,{fam},{max(8, int(st.get('size', 64) * sc))},{_bgra(st.get('primary', '#FFFFFF'),100)},&H000000FF,{outc},&H00000000,{-1 if st.get('bold', True) else 0},{-1 if st.get('italic', False) else 0},0,0,100,100,0,0,{border},{ow},{shadow},{an},{mg},{mg},{mg},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    prim, hl = _bgr(st.get("primary", "#FFFFFF")), _bgr(st.get("highlight", "#00F0FF"))
    conv = (lambda s: s.upper()) if st.get("upper", True) else (lambda s: s)
    lines = []
    
    anim = st.get("anim", "karaoke")

    # Fast 1-word punch mode (Hormozi / MrBeast TikTok style)
    if max_words == 1:
        for w in words:
            w_text = w.get("text", w.get("w", ""))
            txt = conv(_clean(w_text))
            start = w.get("start", w.get("s", 0.0))
            end = w.get("end", w.get("e", start + 0.1))
            dur_ms = int(max(0.08, end - start) * 1000)
            if anim == "pop":
                effect = f"{{\\c{hl}\\fscx112\\fscy112\\t(0,{min(dur_ms, 75)},\\fscx100\\fscy100)}}"
            elif anim == "bounce":
                effect = f"{{\\c{hl}\\fscy75\\t(0,60,\\fscy115)\\t(60,120,\\fscy100)}}"
            else:
                effect = f"{{\\c{hl}}}"
            lines.append(f"Dialogue: 0,{_t(start)},{_t(max(end, start + 0.05))},Main,,0,0,0,,"
                         f"{{\\an{an}\\pos({x},{y})\\fad(30,40)}}{effect}{txt}")

    else:
        # Multi-word phrase mode (e.g. 2-3 words for Shorts, 5-7 words for classic)
        # CRITICAL: Phrases NEVER cross silence pauses (>0.25s) or sentence punctuation!
        phrases = []
        cur_phrase = []
        for w in words:
            w_s = w.get("start", w.get("s", 0.0))
            w_text = w.get("text", w.get("w", ""))
            if not cur_phrase:
                cur_phrase.append(w)
            else:
                prev_e = cur_phrase[-1].get("end", cur_phrase[-1].get("e", 0.0))
                prev_text = cur_phrase[-1].get("text", cur_phrase[-1].get("w", ""))
                gap = w_s - prev_e
                if len(cur_phrase) >= max_words or gap > 0.25 or prev_text[-1:] in ".?!,":
                    phrases.append(cur_phrase)
                    cur_phrase = [w]
                else:
                    cur_phrase.append(w)
        if cur_phrase:
            phrases.append(cur_phrase)

        for chunk in phrases:
            phrase_start = chunk[0].get("start", chunk[0].get("s", 0.0))
            phrase_end = chunk[-1].get("end", chunk[-1].get("e", phrase_start + 0.1))
            n_words = len(chunk)
            for j, w in enumerate(chunk):
                start = w.get("start", w.get("s", 0.0))
                end = chunk[j + 1].get("start", chunk[j + 1].get("s", 0.0)) if j + 1 < n_words else phrase_end
                parts = []
                for k, c in enumerate(chunk):
                    c_text = c.get("text", c.get("w", ""))
                    txt = conv(_clean(c_text))
                    if k == j:
                        # ACTIVE HIGHLIGHTED WORD
                        if anim == "pop":
                            # Vertical-only scale prevents horizontal word reflow & jitter
                            parts.append(f"{{\\c{hl}\\fscy110\\t(0,60,\\fscy100)}}{txt}{{\\fscy100}}")
                        elif anim == "bounce":
                            parts.append(f"{{\\c{hl}\\fscy80\\t(0,50,\\fscy112)\\t(50,110,\\fscy100)}}{txt}")
                        else:
                            parts.append(f"{{\\c{hl}}}{txt}")
                    else:
                        parts.append(f"{{\\c{prim}}}{txt}")

                # Format text with maximum 2 lines if longer than 3 words or exceeds 24 chars
                raw_len = sum(len(c.get("text", c.get("w", ""))) for c in chunk) + n_words - 1
                if n_words >= 4 or (raw_len > 24 and n_words >= 3):
                    split_idx = (n_words + 1) // 2
                    line_text = " ".join(parts[:split_idx]) + "\\N" + " ".join(parts[split_idx:])
                else:
                    line_text = " ".join(parts)

                # FADE EFFECT: Clean phrase fade-in and fade-out on speech pauses
                fade = ""
                if n_words == 1:
                    fade = "\\fad(50,70)"
                elif j == 0:
                    fade = "\\fad(50,0)"
                elif j == n_words - 1:
                    fade = "\\fad(0,70)"

                lines.append(f"Dialogue: 0,{_t(start)},{_t(max(end, start + 0.05))},Main,,0,0,0,,"
                             f"{{\\an{an}\\pos({x},{y}){fade}}}{line_text}")

    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(hdr + "\n".join(lines) + "\n")
    return out_path

# ---------------------------------------------------------------- SRT Builder
def _srt_t(sec):
    ms = int(round(max(sec, 0) * 1000)); h, r = divmod(ms, 3600000); m, r = divmod(r, 60000); s, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def build_srt(words, max_words=7, max_chars=42, max_gap=0.8, out_path="sub.srt"):
    """Sentence-style standard subtitle lines for Premiere, DaVinci, Final Cut, etc."""
    groups, cur = [], []
    for w in words:
        w_text = w.get("text", w.get("w", ""))
        w_s = w.get("start", w.get("s", 0.0))
        if cur:
            prev_e = cur[-1].get("end", cur[-1].get("e", 0.0))
            prev_text = cur[-1].get("text", cur[-1].get("w", ""))
            cur_line = " ".join(x.get("text", x.get("w", "")) for x in cur + [w])
            if (len(cur) >= max_words or len(cur_line) > max_chars
                    or w_s - prev_e > max_gap or prev_text[-1:] in ".?!"):
                groups.append(cur); cur = []
        cur.append(w)
    if cur: groups.append(cur)
    with open(out_path, "w", encoding="utf-8") as f:
        for i, g in enumerate(groups, 1):
            g_start = g[0].get("start", g[0].get("s", 0.0))
            g_end = g[-1].get("end", g[-1].get("e", g_start + 0.1))
            if i < len(groups):
                next_start = groups[i][0].get("start", groups[i][0].get("s", 0.0))
                g_end = min(g_end, next_start)
            g_words = [x.get("text", x.get("w", "")) for x in g]
            full_line = " ".join(g_words)
            if len(full_line) > 35 and len(g_words) >= 4:
                sp = (len(g_words) + 1) // 2
                txt_line = " ".join(g_words[:sp]) + "\n" + " ".join(g_words[sp:])
            else:
                txt_line = full_line
            f.write(f"{i}\n{_srt_t(g_start)} --> {_srt_t(max(g_end, g_start + 0.1))}\n{txt_line}\n\n")
    return out_path
