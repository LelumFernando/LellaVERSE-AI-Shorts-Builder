"""LellaVerse AI Shorts Builder - Next-Gen Turbo Edition
Author: Lelum Anuradha Fernando (LellaVerse)
Run: streamlit run app.py (or double-click Run_LellaVerse.bat)
"""
import gc, json, os, re, shutil
import cv2, streamlit as st
from PIL import Image
from downloader import download_video
from video_editor import (detect_facecam, grab_frame, video_size, detect_hardware_encoders,
                          get_roi_preset, _ensure_ffmpeg_path)
from subtitle_engine import font_family_from_file, resolve_font, ensure_builtin_fonts, PRESETS
from gemini_engine import check_key_status
from pipeline import start_job, start_studio_job, start_regen_job
import maintenance as mt

_ensure_ffmpeg_path()

ROOT = os.path.dirname(os.path.abspath(__file__))

# Config persistence: %APPDATA%\LellaVERSE\settings.json (Windows compliant & upgrade safe)
def _get_config_path():
    appdata = os.environ.get("APPDATA")
    if appdata:
        cfg_dir = os.path.join(appdata, "LellaVERSE")
        os.makedirs(cfg_dir, exist_ok=True)
        user_cfg = os.path.join(cfg_dir, "settings.json")
        if not os.path.exists(user_cfg):
            root_cfg = os.path.join(ROOT, "settings.json")
            if os.path.exists(root_cfg):
                try: shutil.copy2(root_cfg, user_cfg)
                except Exception: pass
        return user_cfg
    return os.path.join(ROOT, "settings.json")

CFG = _get_config_path()
WORK, TEMP, OUT = (os.path.join(ROOT, d) for d in ("workspace", "temp", "outputs"))
FONTS, UPLOADS = os.path.join(WORK, "fonts"), os.path.join(TEMP, "uploads")
for _d in (FONTS, UPLOADS, OUT): os.makedirs(_d, exist_ok=True)
A = lambda n: os.path.join(ROOT, "assets", n)
ensure_builtin_fonts(A("fonts"), FONTS)

# Streamlit Page Setup
st.set_page_config(
    page_title="LellaVerse AI Shorts Builder",
    page_icon=Image.open(A("logo.png")) if os.path.exists(A("logo.png")) else "🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Cyberpunk Streamer UI Theme
st.markdown("""<style>
#MainMenu,footer,[data-testid=stMainMenu],[data-testid=stToolbarActions],[data-testid=stAppDeployButton],[data-testid=stStatusWidget]{visibility:hidden}
[data-testid=stExpandSidebarButton]{visibility:visible!important;border:1px solid #00F0FF!important;border-radius:10px!important;box-shadow:0 0 12px #00F0FF88}
[data-testid=stExpandSidebarButton] *{color:#00F0FF!important}
.stApp{background:radial-gradient(circle at 85% -10%,#D926D922,transparent 40%),#0B0C10;color:#fff}
[data-testid=stSidebar]{background:#13151B;border-right:1px solid #00F0FF33}
h1,h2,h3,label,p{color:#fff}
.stButton>button,.stDownloadButton>button{background:linear-gradient(90deg,#00F0FF,#D926D9);color:#0B0C10;font-weight:800;
 border:0;border-radius:10px;transition:transform .15s,box-shadow .15s}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-2px);box-shadow:0 0 18px #00F0FF99;color:#0B0C10}
.stButton>button:disabled{opacity:.4}
.stTabs [data-baseweb=tab]{background:#1A1D24;border-radius:10px 10px 0 0;color:#fff;padding:8px 18px;margin-right:4px}
.stTabs [aria-selected=true]{border-bottom:3px solid #00F0FF;color:#00F0FF}
.card{background:#161922;border:1px solid #00F0FF33;border-radius:12px;padding:14px;margin-bottom:10px}
.badge-hw{background:#00F0FF22;border:1px solid #00F0FF;border-radius:20px;padding:4px 12px;color:#00F0FF;font-size:13px;display:inline-block;font-weight:600}
.stProgress>div>div>div>div{background:linear-gradient(90deg,#00F0FF,#D926D9)}
video{border-radius:12px;border:1px solid #00F0FF44}
</style>""", unsafe_allow_html=True)

if not shutil.which("ffmpeg"):
    st.error("FFmpeg not found. Run `Run_LellaVerse.bat` to install it automatically, then restart."); st.stop()

# Hardware Detection
HW = detect_hardware_encoders()

# Persisted Settings
def load_cfg():
    try: return json.load(open(CFG, encoding="utf-8"))
    except Exception: return {}

def save_cfg(update):
    d = load_cfg(); d.update(update)
    try: json.dump(d, open(CFG, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError: pass

saved = load_cfg()
S = lambda k, d: saved.get(k, d)
SU = lambda k, d: saved.get("studio", {}).get(k, 78 if k == "y_pct" else d)

@st.cache_data(max_entries=32, show_spinner=False)
def frame_at(path, t): return grab_frame(path, t)

@st.cache_data(max_entries=16, show_spinner=False)
def vsize(path): return video_size(path)

ss = st.session_state
for k, v in {"video": None, "roi": None, "job": None, "sjob": None, "u_video": None}.items():
    ss.setdefault(k, v)
for k in ("video", "u_video"):
    if ss[k] and not os.path.exists(ss[k]): ss[k] = None

def hint(err):
    e = str(err)
    if any(x in e for x in ("503", "UNAVAILABLE", "high demand")):
        st.warning("⏳ **Google Gemini servers are temporarily busy.** Spikes in demand are temporary. Please retry in 1 minute.")
    elif any(x in e for x in ("429", "RESOURCE_EXHAUSTED", "quota")):
        st.error("🚨 **Gemini API Limit Reached!** (Daily Free Tier quota of 20 requests has been used up)")
        st.markdown("""
        <div style="background:#26130b;border:1px solid #FF5500;border-radius:10px;padding:12px;margin:8px 0;">
            <b style="color:#FF7733;font-size:15px">👉 Immediate Fix: Add a New Free Key:</b><br>
            1. Open <a href="https://aistudio.google.com/app/apikey" target="_blank" style="color:#00F0FF;text-decoration:underline;font-weight:bold;">Google AI Studio API Keys ↗</a><br>
            2. Click <b>"Create API Key"</b> (takes 5 seconds, 100% free with any Google account).<br>
            3. Paste the new key into the <b>🔑 Gemini API Keys</b> box in the sidebar.<br>
            <i>💡 Tip: You can also switch Caption Engine to <b>Whisper (Offline fallback)</b> in the sidebar to run offline without any API keys.</i>
        </div>
        """, unsafe_allow_html=True)
        st.toast("⚠️ API Quota Limit Reached! Please add a new key in the sidebar.", icon="⚠️")
    elif "API key" in e or "API_KEY" in e:
        st.error("❌ **Invalid Gemini API Key!** Please check and replace your key in the sidebar.")

def fmt(b): return f"{b/1e9:.2f} GB" if b >= 1e9 else f"{b/1e6:.1f} MB"

# Top Banner & Header
h1, h2 = st.columns([1, 6])
if os.path.exists(A("logo.png")):
    h1.image(A("logo.png"), width=95)
with h2:
    st.markdown("<h1 style='margin:0'>LellaVerse <span style='color:#00F0FF'>AI Shorts Builder</span></h1>"
                "<p style='margin:0;color:#aaa'>Gaming Live Stream Highlights → 9:16 Shorts with Sinhala & English Captions</p>",
                unsafe_allow_html=True)
    st.markdown(f"<span class='badge-hw'>⚡ Engine: {HW['best_name']}</span>", unsafe_allow_html=True)

# Permanent Gemini API Quota Notice (Part 7: Sinhala & English bilingual)
with st.expander("ℹ️ Google Gemini API Quota & Usage Notice (සිංහල / English)", expanded=False):
    col_not_si, col_not_en = st.columns(2)
    with col_not_si:
        st.markdown("""
        <div style="background:#131722;border-left:4px solid #00F0FF;border-radius:8px;padding:12px;font-size:13px;line-height:1.6">
            <b style="color:#00F0FF;font-size:14px">⚠️ වැදගත් දැනුම්දීම – Gemini API සීමාවන්</b><br><br>
            මෙම යෙදුම Google Gemini API භාවිතා කරයි.<br>
            Google Gemini නොමිලේ ලබාදෙන API භාවිතය සඳහා Request, Token සහ කාල සීමා තිබිය හැක.<br>
            එම සීමාවන් ඉක්මවා ගිය විට AI Highlight Analysis, Subtitle Generation සහ අනෙකුත් AI පහසුකම් තාවකාලිකව ක්‍රියා නොකරනු ඇත.<br><br>
            <b style="color:#FFE600">විසඳුම:</b><br>
            1. Google AI Studio වෙතින් අවශ්‍ය නම් නව API Project එකක් සාදන්න.<br>
            2. නව API Key එකක් ලබාගන්න.<br>
            3. පවතින Project වල Quota තත්ත්වය පරීක්ෂා කරන්න.<br>
            4. අවශ්‍ය නම් නව API Key එක Application එකට එක් කරන්න.<br><br>
            <i style="color:#aaa">*නව Project එකක් සෑදීමෙන් Google හි අදාළ Free Tier භාවිත සීමා ඉවත් නොවේ.*</i>
        </div>
        """, unsafe_allow_html=True)
    with col_not_en:
        st.markdown("""
        <div style="background:#131722;border-left:4px solid #D926D9;border-radius:8px;padding:12px;font-size:13px;line-height:1.6">
            <b style="color:#D926D9;font-size:14px">⚠️ IMPORTANT – GEMINI API FREE TIER LIMITATIONS</b><br><br>
            This application uses the Google Gemini API.<br>
            Google Gemini Free Tier usage is subject to request, token, and time-based quotas.<br>
            When these limits are reached, AI Highlight Analysis, Subtitle Generation, and other AI features may temporarily stop working.<br><br>
            <b style="color:#FFE600">To resolve quota-related issues:</b><br>
            1. Create another Gemini API project through Google AI Studio if appropriate.<br>
            2. Generate a new API key.<br>
            3. Check existing project quotas.<br>
            4. Add the new key through the application sidebar.<br><br>
            <i style="color:#aaa">*Creating additional projects does not remove Google's applicable usage restrictions.*</i>
        </div>
        """, unsafe_allow_html=True)

# ====================================================================== SIDEBAR
with st.sidebar:
    if os.path.exists(A("banner.png")):
        st.image(A("banner.png"))
        
    _old = [S("api_key", "")] if S("api_key", "") else []
    keys_txt = st.text_area("🔑 Gemini API Keys (one per line, up to 4)",
                            "\n".join(S("api_keys", _old)) or os.getenv("GEMINI_API_KEY", ""),
                            height=90, help="Work is split across all keys in parallel. If one key hits its quota, the others take over automatically.")
    api_keys = [k.strip() for k in keys_txt.splitlines() if k.strip()][:4]
    
    col_k1, col_k2 = st.columns([1, 1])
    with col_k1:
        st.caption(f"⚡ {len(api_keys)} key(s) loaded" if api_keys else "⚠️ Add at least 1 key")
    with col_k2:
        st.markdown("<div style='text-align:right'><a href='https://aistudio.google.com/app/apikey' target='_blank' style='color:#00F0FF;font-size:12px'>Get Free Key ↗</a></div>", unsafe_allow_html=True)

    if st.button("🔍 Check Key Quota & Health", key="btn_check_keys", use_container_width=True):
        if not api_keys:
            st.warning("Please paste at least one API key above.")
        else:
            with st.spinner("Testing API keys with Google..."):
                for idx, k in enumerate(api_keys, 1):
                    status, msg = check_key_status(k)
                    if status == "active":
                        st.success(f"Key {idx}: {msg}")
                    elif status == "quota":
                        st.error(f"Key {idx}: {msg}")
                    else:
                        st.warning(f"Key {idx}: {msg}")

    st.markdown("---")
    st.markdown("### ⚙️ Engine & Speed")
    
    # Low-End PC Mode Toggle
    low_end_mode = st.checkbox("🚀 Low-End PC Mode (Smooth & Light)", S("low_end_mode", True),
                               help="Keeps CPU & RAM usage low so your PC never freezes or overheats while rendering.")

    models = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]
    _m = S("hl_model", "gemini-3.5-flash")
    if _m == "gemini-2.5-flash": _m = "gemini-3.5-flash"
    model = st.selectbox("Gemini Model", models if _m in models else [_m] + models,
                         0 if _m not in models else models.index(_m),
                         help="gemini-3.5-flash is ultra-fast and recommended for streams & captions.")

    engines = {
        "Gemini Flash — Sinhala + English (Recommended) ✅": "flash",
        "Gemini 3.5 Transcribe — English Native": "transcribe",
        "Whisper (Offline fallback)": "whisper"
    }
    _e = S("engine", "flash")
    engine_name = st.selectbox("Caption Engine", list(engines),
                               list(engines.values()).index(_e) if _e in engines.values() else 0)
    engine = engines[engine_name]

    langs = {
        "Auto (Sinhala + English)": "si",
        "Sinhala Only (සිංහල)": "si",
        "English Only": "en"
    }
    saved_lang = S("lang", "Auto")
    lang_idx = 0
    for idx, (k, _) in enumerate(langs.items()):
        if saved_lang.lower() in k.lower() or k.lower() in saved_lang.lower():
            lang_idx = idx
            break
    lang_name = st.selectbox("Speech Language", list(langs), lang_idx)
    wsize = st.selectbox("Whisper Model Size", ["small", "medium"], ["small", "medium"].index(S("wsize", "small"))) if engine == "whisper" else "small"

    hw_choices = ["Auto (Fastest Hardware Acceleration)"] + [HW["descriptions"].get(a, a) for a in HW["available"]]
    hw_choice = st.selectbox("Video Encoder Acceleration", hw_choices, 0,
                             help="Auto detects Intel QuickSync, NVIDIA NVENC, AMD AMF, or Windows Media Foundation.")
    selected_encoder = HW["best"] if "Auto" in hw_choice else next((k for k, v in HW["descriptions"].items() if v == hw_choice), HW["best"])

    sfx_vol = st.slider("Sound Effects Volume %", 10, 100, int(S("sfx_vol", 80)), 5) / 100.0

    # Maintenance Expander
    with st.expander("🧹 System Maintenance"):
        busy = any(j and j.state == "running" for j in (ss.job, ss.sjob))
        st.caption(f"Temp files: **{fmt(mt.folder_size(TEMP))}** · Raw downloads: "
                   f"**{fmt(sum(os.path.getsize(p) for p in mt.raw_downloads(WORK)))}** · "
                   f"🔒 Outputs: **{fmt(mt.folder_size(OUT))}**")
        if busy: st.warning("A job is currently running.")
        if st.button("🧽 Clear Temp Cache", disabled=busy):
            r = mt.clear_temp(TEMP, OUT); os.makedirs(UPLOADS, exist_ok=True); st.cache_data.clear()
            st.success(f"Cleared {r['files']} file(s), freed {fmt(r['bytes'])}")
        raw_ok = st.checkbox("Delete raw YouTube stream downloads", disabled=busy)
        if st.button("🗑️ Delete Raw Downloads", disabled=busy or not raw_ok):
            r = mt.delete_raw_downloads(WORK, OUT); st.cache_data.clear()
            if ss.video and not os.path.exists(ss.video): ss.video = None
            st.success(f"Deleted {r['files']} stream file(s), freed {fmt(r['bytes'])}")

    # ==================================================================
    # PART 4 – PROFESSIONAL ABOUT APP
    # ==================================================================
    with st.expander("ℹ️ About LellaVERSE AI Shorts Builder"):
        st.markdown("""
        <div style="line-height:1.5;font-size:13px">
            <h4 style="margin:0;color:#00F0FF">LellaVERSE AI Shorts Builder</h4>
            <span style="color:#D926D9;font-weight:700">Version: v1.0.0 (Release)</span><br>
            <i style="color:#eee">"AI-Powered Gaming Highlights & Sinhala-English Subtitle Generator."</i>
            <hr style="border:none;border-top:1px solid #00F0FF33;margin:8px 0">
            <p style="color:#ccc;margin-bottom:8px">
            LellaVERSE AI Shorts Builder is an independently developed creator-focused application designed to transform long gaming livestreams and uploaded videos into engaging vertical short-form videos.
            </p>
            <b style="color:#00F0FF">Core Features:</b>
            <ul style="padding-left:18px;margin-top:4px;color:#ddd">
                <li>AI-assisted highlight detection</li>
                <li>Full-video timeline analysis</li>
                <li>Unique highlight selection</li>
                <li>Automatic Facecam detection</li>
                <li>Automatic Facecam positioning</li>
                <li>Vertical 9:16 generation</li>
                <li>Sinhala and English mixed-language subtitles</li>
                <li>Word-level subtitle timing</li>
                <li>Subtitle styling & glowing animations</li>
                <li>Audio/video synchronization (Zero-drift PTS)</li>
                <li>FFmpeg video processing</li>
                <li>Intel Quick Sync hardware acceleration</li>
                <li>Low-End PC Mode</li>
                <li>Gemini API multi-key management</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    # ==================================================================
    # PART 5 – DEVELOPMENT CREDITS
    # ==================================================================
    with st.expander("👨‍💻 Development Credits"):
        st.markdown("""
        <div style="line-height:1.5;font-size:13px">
            <p style="margin:0"><b style="color:#00F0FF">CREATED BY:</b> <span style="color:#fff">Lelum Anuradha Fernando</span></p>
            <p style="margin:0"><b style="color:#D926D9">BRAND:</b> <span style="color:#fff">LellaVERSE</span></p>
            <hr style="border:none;border-top:1px solid #00F0FF33;margin:8px 0">
            <b style="color:#FFE600">Project Origin:</b>
            <p style="color:#ccc;margin-top:4px">
            This application originated from an independent idea by <b>Lelum Anuradha Fernando</b>.<br><br>
            Google Gemini was initially used for research, technical exploration, and gathering information about possible implementation approaches.<br><br>
            The initial application development was carried out with assistance from Claude.<br><br>
            Google Antigravity was subsequently used extensively for further development, integration, debugging, improvements, and refinement.
            </p>
            <b style="color:#FFE600">Inspiration & Acknowledgement:</b>
            <p style="color:#ccc;margin-top:4px">
            A special acknowledgement to <b>Shehan Dilhara</b> for the inspiration received from a Sinhala subtitle generator demonstration video discovered on TikTok.<br><br>
            The original concept was independently expanded into a broader AI-powered gaming highlight and subtitle generation application.
            </p>
            <b style="color:#FFE600">AI Development Tools:</b>
            <ul style="padding-left:18px;margin-top:4px;color:#ddd">
                <li><b>Google Gemini</b> – Research and AI integration</li>
                <li><b>Claude</b> – Initial development assistance</li>
                <li><b>Google Antigravity</b> – Subsequent development and refinement</li>
            </ul>
            <p style="color:#888;font-size:11px;font-style:italic;margin-top:6px">
            *This application is an independent development. No official partnership, sponsorship, or endorsement is claimed.
            </p>
        </div>
        """, unsafe_allow_html=True)

    # ==================================================================
    # PART 6 – OFFICIAL LINKS
    # ==================================================================
    with st.expander("🌐 Official Links & Social Media"):
        st.markdown("""
        <div style="line-height:1.8;font-size:13px">
            <a href="https://github.com/LelumFernando" target="_blank" style="color:#00F0FF;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">🐙</span> <b>GitHub:</b> LelumFernando ↗
            </a>
            <a href="https://www.youtube.com/@LellaVerse" target="_blank" style="color:#FF0000;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">▶️</span> <b>YouTube:</b> @LellaVerse ↗
            </a>
            <a href="https://web.facebook.com/fb.lellaverse" target="_blank" style="color:#1877F2;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">🌐</span> <b>Facebook Page:</b> fb.lellaverse ↗
            </a>
            <a href="https://www.instagram.com/lelum.fernando/" target="_blank" style="color:#E4405F;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">📸</span> <b>Instagram:</b> lelum.fernando ↗
            </a>
            <a href="https://www.tiktok.com/@lelum.fernando" target="_blank" style="color:#00F0FF;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">🎵</span> <b>TikTok:</b> @lelum.fernando ↗
            </a>
            <a href="https://web.facebook.com/Lelum.Fenando" target="_blank" style="color:#4267B2;text-decoration:none;display:block;margin-bottom:6px">
                <span style="font-size:15px">👤</span> <b>Personal Facebook:</b> Lelum Fernando ↗
            </a>
        </div>
        """, unsafe_allow_html=True)

# ====================================================================== SHARED SUBTITLE STYLE PANEL
def style_panel(p, get):
    st.markdown("##### 🎨 Subtitle Style Presets")
    preset_cols = st.columns(len(PRESETS))
    for idx, (pkey, pdata) in enumerate(PRESETS.items()):
        with preset_cols[idx]:
            if st.button(pdata["name"].split(" ")[0] + " " + pkey.capitalize(), key=f"{p}_preset_{pkey}"):
                for k, v in pdata.items():
                    if k != "name": ss[f"{p}_{k}"] = v
                st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        fonts = ["Noto Sans Sinhala", "Poppins", "Abhaya Libre", "Noto Serif Sinhala", "Arial", "Impact", "Nirmala UI"]
        cur_font = ss.get(f"{p}_font", get("font", "Noto Sans Sinhala"))
        if cur_font not in fonts: fonts = [cur_font] + fonts
        font = st.selectbox("Font Family", fonts, fonts.index(cur_font), key=p + "font_sel")

        up_font = st.file_uploader("Upload custom font (.ttf/.otf)", type=["ttf", "otf"], key=p + "fontup")
        if up_font:
            fp = os.path.join(FONTS, up_font.name)
            open(fp, "wb").write(up_font.getbuffer())
            font = font_family_from_file(fp)
            st.success(f"Font uploaded: {font}")

        size = st.slider("Font Size", 24, 90, ss.get(f"{p}_size", get("size", 64)), key=p + "size")
        
        # Word chunking selector
        wmode_map = {1: "1 Word (High-Energy TikTok Pop)", 3: "2-3 Words (Standard Short)", 7: "Full Sentence (Classic)"}
        cur_wmode = ss.get(f"{p}_words_mode", get("words_mode", 3))
        wmode_sel = st.selectbox("Words Per Caption", list(wmode_map.values()),
                                 list(wmode_map.keys()).index(cur_wmode) if cur_wmode in wmode_map else 1, key=p + "wmode")
        words_mode = next(k for k, v in wmode_map.items() if v == wmode_sel)

        b, i, u = st.columns(3)
        bold = b.checkbox("Bold", ss.get(f"{p}_bold", get("bold", True)), key=p + "bold")
        italic = i.checkbox("Italic", ss.get(f"{p}_italic", get("italic", False)), key=p + "italic")
        upper = u.checkbox("UPPERCASE", ss.get(f"{p}_upper", get("upper", True)), key=p + "upper")

        anims = ["karaoke", "pop", "bounce"]
        cur_anim = ss.get(f"{p}_anim", get("anim", "karaoke"))
        anim = st.selectbox("Animation Style", anims, anims.index(cur_anim) if cur_anim in anims else 0,
                            format_func={"karaoke": "Karaoke Active Word", "pop": "Word Pop-In Scale", "bounce": "Bounce & Settle"}.get,
                            key=p + "anim")
        y_pct = st.slider("Vertical Position (% from top)", 10, 90, ss.get(f"{p}_y_pct", get("y_pct", 70)), key=p + "y")

    with c2:
        auto_c = st.checkbox("🎨 Auto Video Colors (Match video palette)", ss.get(f"{p}_auto_color", get("auto_color", True)), key=p + "auto")
        primary = st.color_picker("Primary Text Color", ss.get(f"{p}_primary", get("primary", "#FFFFFF")), key=p + "c1", disabled=auto_c)
        highlight = st.color_picker("Active Word Highlight", ss.get(f"{p}_highlight", get("highlight", "#00F0FF")), key=p + "c2", disabled=auto_c)
        outline = st.color_picker("Outline Color", ss.get(f"{p}_outline", get("outline", "#000000")), key=p + "c3", disabled=auto_c)
        outline_w = st.slider("Outline Thickness", 0, 8, ss.get(f"{p}_outline_w", get("outline_w", 3)), key=p + "ow")
        shadow = st.slider("Drop Shadow", 0, 5, ss.get(f"{p}_shadow", get("shadow", 1)), key=p + "shad")
        
        bg_on = st.checkbox("Background Pill (Replaces outline)", ss.get(f"{p}_bg_on", get("bg_on", False)), key=p + "bgon")
        bg_color = st.color_picker("Pill Color", ss.get(f"{p}_bg_color", get("bg_color", "#000000")), key=p + "bgc", disabled=not bg_on)
        bg_opacity = st.slider("Pill Opacity %", 10, 100, ss.get(f"{p}_bg_opacity", get("bg_opacity", 75)), key=p + "bgo", disabled=not bg_on)

        # Live HTML Preview Card
        st.markdown(f"""
        <div style="background:#0F1116;border:1px dashed #00F0FF55;border-radius:12px;padding:24px;text-align:center;margin-top:10px;">
          <div style="font-family:'{font}',sans-serif;font-size:{size*0.48}px;font-weight:{700 if bold else 400};
               font-style:{'italic' if italic else 'normal'};color:{primary};
               text-shadow: {f'{shadow*2}px {shadow*2}px 0px #000' if shadow else 'none'};
               -webkit-text-stroke:{outline_w/2}px {outline};
               {f'background:{bg_color};opacity:{bg_opacity/100};padding:6px 16px;border-radius:16px;display:inline-block;' if bg_on else ''}">
            {'NEXT ' if upper else 'Next '}<span style="color:{highlight}">{'LEVEL ' if upper else 'Level '}</span>{'CLUTCH' if upper else 'Clutch'}
          </div>
          <div style="font-family:'Noto Sans Sinhala',sans-serif;font-size:{size*0.38}px;margin-top:8px;color:#aaa">
            සුපිරි ගේම්ප්ලේ එකක් 🔥 (Sinhala Preview)
          </div>
        </div>
        """, unsafe_allow_html=True)

    return dict(font=font, size=size, bold=bold, italic=italic, upper=upper, primary=primary,
                highlight=highlight, outline=outline, outline_w=outline_w, shadow=shadow,
                bg_on=bg_on, bg_color=bg_color, bg_opacity=bg_opacity, y_pct=y_pct,
                align="center", anim=anim, words_mode=words_mode, auto_color=auto_c)

# Main Navigation Tabs
tab_mode1, tab_mode2 = st.tabs(["📺 YouTube Live Generator", "🎞️ Subtitle Studio"])

# ====================================================================== MODE 1: YOUTUBE LIVE GENERATOR
with tab_mode1:
    t1, t2, t3, t4 = st.tabs(["📥 1. Stream Source", "🎥 2. Layout & Facecam", "🅰️ 3. Subtitles & Style", "🚀 4. Generate Shorts"])

    # 1. Source Tab
    with t1:
        st.markdown("#### 📥 Download YouTube Stream")
        url = st.text_input("YouTube Live Stream or Video URL", placeholder="https://www.youtube.com/watch?v=...")
        q1, q2 = st.columns(2)
        quality = q1.selectbox("Stream Resolution", [480, 720, 1080], 1, format_func=lambda v: f"{v}p (Recommended for Shorts)" if v == 720 else f"{v}p")
        part = q2.checkbox("Download a time range (Minutes)", False, help="Recommended for long streams to test quickly")
        section = None
        if part:
            p1, p2 = st.columns(2)
            a_min = p1.number_input("Start Minute", 0, 2000, 0)
            b_min = p2.number_input("End Minute", 1, 2000, 15)
            section = (a_min, b_min) if b_min > a_min else None

        if st.button("⬇️ Download Stream", disabled=not url):
            pbar = st.progress(0.0, text="Starting download…")
            try:
                ss.video = download_video(url, WORK, lambda f: pbar.progress(f, text=f"Downloading… {f:.0%}"), quality, section)
                ss.roi = list(detect_facecam(ss.video))
                pbar.progress(1.0, text="Downloaded successfully ✔")
                st.rerun()
            except Exception as e:
                st.error(f"Download failed: {e}")

        if ss.video and os.path.exists(ss.video):
            st.success(f"Stream Loaded: {os.path.basename(ss.video)}")
            st.video(ss.video)

    # 2. Layout & Facecam Tab
    with t2:
        if not ss.video or not os.path.exists(ss.video):
            st.info("Download a stream first in Tab 1 (Source).")
        else:
            W, H = vsize(ss.video)
            if not ss.roi:
                ss.roi = detect_facecam(ss.video)

            has_cam = getattr(ss.roi, "has_facecam", False)
            pos_label = getattr(ss.roi, "position", "custom").replace("_", " ").title()
            conf_pct = int(getattr(ss.roi, "confidence", 0.0) * 100)
            persist_pct = int(getattr(ss.roi, "persistence", 0.0) * 100)

            st.markdown("#### 🎥 9:16 Layout & Facecam Setup")
            if has_cam:
                st.success(f"🟢 **Facecam Detected:** {pos_label} ({conf_pct}% confidence · {persist_pct}% stable)")
            else:
                st.warning("🎮 **No Persistent Facecam Detected** · Video appears to be gameplay-only without a webcam. Defaulting to 9:16 Action Crop.")

            layouts = {
                "split": "📱 Split Screen (Facecam Top 1/3 + Gameplay Bottom 2/3)",
                "pip": "🔲 Picture-in-Picture (Facecam Floating Corner Overlay)",
                "action_crop": "🎯 Full Action Crop (9:16 Action Tracking, No Cam)",
                "blur_fill": "🌫️ Cinematic Blur Fill (Full Gameplay with Blurred Background, No Cam)"
            }
            default_layout = "split" if has_cam else "action_crop"
            cur_layout = S("layout", default_layout)
            layout_idx = list(layouts.keys()).index(cur_layout) if cur_layout in layouts else 0
            layout_key = st.selectbox("Video Layout", list(layouts.keys()),
                                      index=layout_idx, format_func=layouts.get)

            if layout_key in ("split", "pip"):
                st.markdown("##### 📍 Facecam Position Presets")
                pr1, pr2, pr3, pr4, pr5, pr6 = st.columns(6)
                if pr1.button("🔍 Auto Detect"):
                    ss.roi = detect_facecam(ss.video); st.rerun()
                if pr2.button("↗️ Top-Right"):
                    ss.roi = get_roi_preset("top_right", W, H); st.rerun()
                if pr3.button("↖️ Top-Left"):
                    ss.roi = get_roi_preset("top_left", W, H); st.rerun()
                if pr4.button("↘️ Bottom-Right"):
                    ss.roi = get_roi_preset("bottom_right", W, H); st.rerun()
                if pr5.button("↙️ Bottom-Left"):
                    ss.roi = get_roi_preset("bottom_left", W, H); st.rerun()
                if pr6.button("🔝 Top Bar"):
                    ss.roi = get_roi_preset("top_bar", W, H); st.rerun()

                r = ss.roi
                col_ctrl, col_prev = st.columns([1, 2])
                with col_ctrl:
                    st.caption("Fine-tune Coordinates")
                    x = st.number_input("X Coordinate", 0, W, min(int(r[0]), W))
                    y = st.number_input("Y Coordinate", 0, H, min(int(r[1]), H))
                    w = st.number_input("Width", 10, W, min(int(r[2]), W))
                    h = st.number_input("Height", 10, H, min(int(r[3]), H))
                    from video_editor import FacecamROI
                    ss.roi = FacecamROI((x, y, w, h), has_facecam=True, confidence=1.0, position="custom", persistence=1.0, is_manual=True)
                    pt = st.slider("Preview Frame Time (Seconds)", 0, 600, 10)
                    motion = st.checkbox("Motion-tracked gameplay (auto-pans to action)", S("motion", True))

                with col_prev:
                    fr = frame_at(ss.video, pt)
                    if fr is not None:
                        prev_fr = fr.copy()
                        cv2.rectangle(prev_fr, (x, y), (x + w, y + h), (0, 240, 255), max(3, W // 300))
                        st.image(prev_fr, caption="Cyan box = Facecam region", use_container_width=True)
            else:
                motion = st.checkbox("Motion-tracked gameplay crop", S("motion", True))
                st.info("This layout uses full gameplay without a facecam.")

    # 3. Subtitles & Style Tab
    with t3:
        style = style_panel("", S)

    # 4. Generate & Results Tab
    with t4:
        job = ss.job
        running = bool(job and job.state == "running")
        st.markdown("#### 🚀 Generate AI Shorts")
        st.caption("Gemini watches the stream, extracts 4-9 multi-cut highlights under 60 seconds, and burns dynamic subtitles.")

        e1, e2, e3 = st.columns([1, 1, 1])
        n_clips = e1.slider("Number of Shorts to create", 1, 5, S("n", 3))
        punch = e2.checkbox("💥 Impact Zoom on cuts", S("punch", True))
        sfx_cuts = e3.checkbox("🔊 Whoosh SFX on cuts", S("sfx", True))

        b1, b2, b3 = st.columns([2, 1, 2])
        if b1.button("🚀 Generate Shorts Now", disabled=running):
            if not ss.video:
                st.error("Please download a stream first in Tab 1.")
            elif not api_keys:
                st.error("Please add at least one Gemini API key in the sidebar.")
            else:
                save_cfg({**style, "api_keys": api_keys, "hl_model": model, "engine": engine,
                          "n": n_clips, "wsize": wsize, "lang": lang_name, "motion": motion,
                          "punch": punch, "sfx": sfx_cuts, "layout": layout_key,
                          "sfx_vol": sfx_vol, "low_end_mode": low_end_mode})
                ss.job = start_job(dict(
                    api_keys=api_keys, model=model, engine=engine, n=n_clips, wsize=wsize,
                    lang=langs[lang_name], video=ss.video, roi=ss.roi, motion=motion,
                    encoder=selected_encoder, punch=punch, sfx=sfx_cuts, sfx_vol=sfx_vol,
                    layout=layout_key, low_end_mode=low_end_mode, style=style,
                    temp=TEMP, fonts=FONTS, out_dir=OUT
                ))
                st.rerun()

        if running and b2.button("⛔ Cancel"):
            job.cancel = True

        if b3.button("📂 Open Outputs Folder") and hasattr(os, "startfile"):
            os.startfile(OUT)

        def mode1_results_panel():
            j = ss.job
            if not j: return
            if j.state == "running":
                st.progress(j.p, text=j.msg)
            elif j.state == "error":
                st.error(f"Pipeline error: {j.error}")
                hint(j.error)
                with st.expander("Error Details"): st.code(j.trace)
            elif j.state == "cancelled":
                st.warning("Job was cancelled.")

            if j.state != "running" and not j.notified:
                j.notified = True; st.rerun()

            if j.state == "done":
                st.success(f"🎉 {len(j.results)} Shorts ready and saved to outputs folder!")

            cols = st.columns(3)
            for idx, r in enumerate(j.results):
                if not os.path.exists(r["path"]): continue
                with cols[idx % 3]:
                    qc_badge = '<span style="color:#39FF14">✅ QC Verified: 1080x1920 (9:16) · In-Sync</span>' if r.get("qc_valid") else '<span style="color:#FFA500">⚠️ QC Review</span>'
                    s_st = r.get("source_start", 0.0)
                    s_en = r.get("source_end", r.get("length", 0.0))
                    st.markdown(f"""
                    <div class="card">
                      <b style="color:#00F0FF">{r['title']}</b><br>
                      <small>⏱️ Source: {s_st:.0f}s – {s_en:.0f}s ({r['length']:.0f}s · {r['cuts']} cuts) · Score: {r['score']}/10<br>
                      {qc_badge}<br>
                      {r['description']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    if r.get("caption_error"):
                        st.warning(f"Captions issue: {r['caption_error'][:120]}")
                    st.video(r["path"])
                    btn_c1, btn_c2 = st.columns([1, 1])
                    with btn_c1:
                        with open(r["path"], "rb") as f:
                            st.download_button("⬇️ Download MP4", f.read(), os.path.basename(r["path"]),
                                               "video/mp4", key=f"dl_short_{idx}")
                    with btn_c2:
                        if st.button("🔄 Regenerate", key=f"regen_btn_{idx}"):
                            sh_data = {"title": r["title"], "description": r["description"],
                                       "score": r["score"], "cuts": r.get("cuts_data", [(s_st, s_en)])}
                            cfg = dict(
                                api_keys=api_keys, model=model, engine=engine, wsize=wsize,
                                lang=langs[lang_name], video=ss.video, roi=ss.roi, motion=motion,
                                encoder=selected_encoder, punch=punch, sfx=sfx_cuts, sfx_vol=sfx_vol,
                                layout=layout_key, low_end_mode=low_end_mode, style=style,
                                temp=TEMP, fonts=FONTS, out_dir=OUT
                            )
                            ss.job = start_regen_job(cfg, sh_data, idx)
                            st.rerun()

        st.fragment(mode1_results_panel, run_every=1.0 if running else None)()

# ====================================================================== MODE 2: SUBTITLE STUDIO
with tab_mode2:
    st.markdown("#### 🎞️ Subtitle Studio — Add Sinhala & English captions to any video")
    up_vid = st.file_uploader("Upload video (.mp4 / .mov / .mkv / .webm)", type=["mp4", "mov", "mkv", "webm"], key="studio_uploader")
    if up_vid is not None:
        safe_name = re.sub(r"[^\w.\-]+", "_", up_vid.name)
        up_path = os.path.join(UPLOADS, safe_name)
        if not os.path.exists(up_path) or os.path.getsize(up_path) != up_vid.size:
            os.makedirs(UPLOADS, exist_ok=True)
            with open(up_path, "wb") as f: f.write(up_vid.getbuffer())
        ss.u_video = up_path

    if ss.u_video and os.path.exists(ss.u_video):
        st.caption(f"Loaded: {os.path.basename(ss.u_video)}")
        if ss.u_video.lower().endswith((".mp4", ".mov", ".webm")):
            st.video(ss.u_video)

    with st.expander("🅰️ Subtitle Style & Presets", expanded=True):
        style_u = style_panel("u_", SU)

    st.markdown("##### 🎯 Hormozi-Style Auto Zoom")
    z1, z2, z3 = st.columns([2, 1, 1])
    zoom_on = z1.checkbox("Auto Zoom-In/Out on pauses (Hormozi style)", SU("zoom", False), key="u_zoom")
    zoom_strength = z2.slider("Zoom Strength %", 3, 15, int(SU("zoom_strength", 8)), key="u_zs", disabled=not zoom_on)
    zoom_gap = z3.slider("Pause Gap (Seconds)", 0.2, 1.0, float(SU("zoom_gap", 0.35)), 0.05, key="u_zg", disabled=not zoom_on)

    a1, a2 = st.columns(2)
    sfx_u = a1.checkbox("🔊 Whoosh SFX on zoom punch", SU("sfx", True), key="u_sfx", disabled=not zoom_on)
    clean_u = a2.checkbox("🎚️ Audio Clean-up (Noise reduction + Loudness)", SU("clean", False), key="u_clean")

    sj = ss.sjob; srun = bool(sj and sj.state == "running")

    def launch_studio(mode):
        if engine != "whisper" and not api_keys:
            st.error("Please add at least one Gemini API key in the sidebar."); return
        save_cfg({
            "studio": {**style_u, "zoom": zoom_on, "zoom_strength": zoom_strength,
                       "zoom_gap": zoom_gap, "sfx": sfx_u, "clean": clean_u},
            "api_keys": api_keys, "hl_model": model, "engine": engine, "wsize": wsize,
            "lang": lang_name, "sfx_vol": sfx_vol
        })
        ss.sjob = start_studio_job(dict(
            mode=mode, video=ss.u_video, api_keys=api_keys, model=model, engine=engine,
            wsize=wsize, lang=langs[lang_name], style=style_u, zoom=zoom_on,
            zoom_strength=zoom_strength / 100.0, zoom_gap=zoom_gap, sfx=sfx_u and zoom_on,
            sfx_vol=sfx_vol, clean=clean_u, encoder=selected_encoder, temp=TEMP,
            fonts=FONTS, out_dir=OUT
        ))
        st.rerun()

    s1, s2, s3, s4 = st.columns([2, 2, 1, 2])
    if s1.button("🎬 Render Video with Subtitles", disabled=srun or not ss.u_video): launch_studio("render")
    if s2.button("📝 Export Subtitles (.SRT / .ASS)", disabled=srun or not ss.u_video): launch_studio("subs")
    if srun and s3.button("⛔ Cancel", key="u_cancel"): sj.cancel = True
    if s4.button("📂 Open Outputs Folder", key="u_open") and hasattr(os, "startfile"): os.startfile(OUT)

    def studio_panel():
        j = ss.sjob
        if not j: return
        if j.state == "running":
            st.progress(j.p, text=j.msg)
        elif j.state == "error":
            st.error(f"Error: {j.error}"); hint(j.error)
            with st.expander("Error Details"): st.code(j.trace)
        elif j.state == "cancelled":
            st.warning("Job cancelled.")

        if j.state != "running" and not j.notified:
            j.notified = True; st.rerun()

        if j.state == "done":
            st.success("🎉 Completed! Files are saved in the outputs folder.")
            if j.info: st.caption(j.info)
            for r in j.results:
                if not os.path.exists(r["path"]): continue
                name = os.path.basename(r["path"])
                with open(r["path"], "rb") as f:
                    data = f.read()
                if r["kind"] == "video":
                    st.video(r["path"])
                    st.download_button("⬇️ Download Video", data, name, "video/mp4", key="s_dl_v")
                elif r["kind"] == "srt":
                    st.download_button("⬇️ Download .SRT", data, name, "application/x-subrip", key="s_dl_srt")
                    with st.expander("Preview .SRT Subtitles"):
                        st.code(data.decode("utf-8", "ignore")[:2000], language=None)
                else:
                    st.download_button("⬇️ Download .ASS", data, name, "text/plain", key="s_dl_ass")

    st.fragment(studio_panel, run_every=1.0 if srun else None)()
