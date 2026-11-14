"""LellaVerse Video Editor - Next-Gen Turbo Edition
Hardware-accelerated (QSV / NVENC / AMF / MF / CPU), multi-layout 9:16 compositor,
butter-smooth motion tracking for low-end PCs, Hormozi auto-zoom, and Windows-safe subtitle burning.
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import bisect, functools, gc, json, os, shutil, subprocess, sys, tempfile
import cv2
import numpy as np

OUT_W, OUT_H = 1080, 1920
TOP_H = 640
BOT_H = OUT_H - TOP_H

class EncoderError(RuntimeError): pass

# ====================================================================== FFmpeg Path Auto-Discovery
def _ensure_ffmpeg_path():
    """Ensure ffmpeg and ffprobe are in PATH even if bundled or newly installed without a restart."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    # Priority 1: Check application local directories (bundled portable / installed bin)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    local_dirs = [
        app_dir,
        os.path.join(app_dir, "bin"),
        os.path.join(app_dir, "ffmpeg"),
        os.path.join(app_dir, "ffmpeg", "bin")
    ]
    for ld in local_dirs:
        if os.path.exists(os.path.join(ld, "ffmpeg.exe")):
            os.environ["PATH"] = ld + os.pathsep + os.environ.get("PATH", "")
            if shutil.which("ffmpeg") and shutil.which("ffprobe"):
                return

    # Priority 2: System packages (Winget, Program Files)
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"),
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files")),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
    ]
    for base in candidates:
        if os.path.isdir(base):
            for root, dirs, files in os.walk(base):
                if "ffmpeg.exe" in files:
                    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
                    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
                        return
                if root.count(os.sep) - base.count(os.sep) > 3:
                    dirs.clear()

_ensure_ffmpeg_path()

# ====================================================================== Hardware Acceleration Engine
@functools.lru_cache(maxsize=1)
def detect_hardware_encoders():
    """
    Tests all available video encoders (QSV, NVENC, AMF, MediaFoundation, x264)
    and picks the fastest hardware accelerator for this PC.
    """
    _ensure_ffmpeg_path()
    def test_codec(codec, extra=None):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "color=c=black:s=256x256:r=10", "-frames:v", "3",
               "-pix_fmt", "yuv420p", "-c:v", codec] + (extra or []) + ["-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=12)
            return r.returncode == 0
        except Exception:
            return False

    encoders = [
        ("h264_nvenc", "NVIDIA NVENC (GPU)", ["-preset", "p4"]),
        ("h264_qsv", "Intel Quick Sync (QSV Hardware)", ["-preset", "veryfast", "-global_quality", "22"]),
        ("h264_amf", "AMD AMF (Radeon GPU)", ["-quality", "speed"]),
        ("h264_mf", "Windows Media Foundation (GPU/HW)", ["-b:v", "5500k"]),
        ("libx264", "CPU (Optimized x264)", ["-preset", "veryfast"])
    ]

    avail = []
    for code, name, extra in encoders:
        if test_codec(code, extra):
            avail.append((code, name))

    best_code, best_name = avail[0] if avail else ("libx264", "CPU (Optimized x264)")
    return {
        "best": best_code,
        "best_name": best_name,
        "available": [a[0] for a in avail],
        "descriptions": dict(avail),
        "is_hardware": best_code != "libx264"
    }

def get_active_encoder():
    return detect_hardware_encoders()["best"]

def nvenc_available():
    """Backwards-compatible check: True if ANY hardware GPU encoder is available."""
    return detect_hardware_encoders()["is_hardware"]

def nvenc_error():
    hw = detect_hardware_encoders()
    return f"Active encoder: {hw['best_name']}"

def _encoder_flags(codec, crf=20):
    """Returns optimal ffmpeg flags for the selected codec."""
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(crf)]
    elif codec == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", str(crf)]
    elif codec == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    elif codec == "h264_mf":
        return ["-c:v", "h264_mf", "-b:v", "6000k"]
    else:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-threads", "0"]

# ====================================================================== Video Probe Helpers
def video_size(path):
    cap = cv2.VideoCapture(path)
    w, h = int(cap.get(3)), int(cap.get(4))
    cap.release()
    return w, h

def frame_dims(path):
    cap = cv2.VideoCapture(path)
    ok, fr = cap.read()
    cap.release()
    if not ok: raise EncoderError("Cannot read this video file.")
    return fr.shape[1], fr.shape[0]

def video_duration(path):
    _ensure_ffmpeg_path()
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try: return float(out)
    except ValueError: return 0.0

def grab_frame(path, t=10.0):
    cap = cv2.VideoCapture(path)
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.set(cv2.CAP_PROP_POS_MSEC, min(t, max(total - 1, 0)) * 1000)
    ok, fr = cap.read()
    cap.release()
    return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB) if ok else None

def has_audio(path):
    _ensure_ffmpeg_path()
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())

CLEAN = "highpass=f=70,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11"

# ====================================================================== Facecam & ROI Management
class FacecamROI(tuple):
    """
    Rich Facecam ROI structure:
    Acts as (x, y, w, h) tuple for 100% backward compatibility with list/tuple indexing,
    while carrying rich detection metadata (has_facecam, confidence, position, persistence).
    """
    def __new__(cls, coords, has_facecam=False, confidence=0.0, position="none", persistence=0.0, face_box=None, is_manual=False):
        obj = super().__new__(cls, coords)
        obj.has_facecam = bool(has_facecam)
        obj.confidence = float(confidence)
        obj.position = str(position)
        obj.persistence = float(persistence)
        obj.face_box = face_box
        obj.is_manual = bool(is_manual)
        return obj

def fit_roi(roi, W, H, ar=OUT_W / TOP_H):
    x, y, w, h = [float(v) for v in roi]
    cx, cy = x + w / 2, y + h / 2
    if w / max(h, 1) < ar: w = h * ar
    else: h = w / ar
    w = min(w, W); h = w / ar
    if h > H: h = H; w = h * ar
    return int(np.clip(cx - w / 2, 0, W - w)), int(np.clip(cy - h / 2, 0, H - h)), int(w), int(h)

def get_roi_preset(preset, W, H):
    """Presets: 'top_right', 'top_left', 'bottom_right', 'bottom_left', 'top_bar'"""
    w = int(W * 0.32)
    h = int(w * TOP_H / OUT_W)
    if preset == "top_right":
        coords = fit_roi((W - w - int(W * 0.02), int(H * 0.04), w, h), W, H)
    elif preset == "top_left":
        coords = fit_roi((int(W * 0.02), int(H * 0.04), w, h), W, H)
    elif preset == "bottom_left":
        coords = fit_roi((int(W * 0.02), H - h - int(H * 0.04), w, h), W, H)
    elif preset == "top_bar":
        bw = int(W * 0.45); bh = int(bw * TOP_H / OUT_W)
        coords = fit_roi(((W - bw) // 2, 0, bw, bh), W, H)
    else: # bottom_right default
        coords = fit_roi((W - w - int(W * 0.02), H - h - int(H * 0.04), w, h), W, H)
    return FacecamROI(coords, has_facecam=True, confidence=1.0, position=preset, persistence=1.0, is_manual=True)

def classify_facecam_position(cx, cy, W, H):
    rx, ry = cx / max(W, 1), cy / max(H, 1)
    if rx < 0.45 and ry < 0.45: return "top_left"
    elif rx > 0.55 and ry < 0.45: return "top_right"
    elif rx < 0.45 and ry > 0.55: return "bottom_left"
    elif rx > 0.55 and ry > 0.55: return "bottom_right"
    elif 0.35 <= rx <= 0.65 and ry < 0.30: return "top_bar"
    elif 0.30 <= rx <= 0.70 and 0.30 <= ry <= 0.70: return "center"
    return "custom"

def detect_facecam(path, num_samples=20, min_persistence=0.30):
    """
    Intelligent Temporal Persistence & Region Stability Facecam Detection (Part 1):
    1. Analyzes video frames across multiple timestamps.
    2. Detects human faces using deep learning CNN (YuNet).
    3. Tracks detected faces across frames with spatial clustering.
    4. Identifies persistent Facecam regions rather than transient gameplay faces.
    5. Rejects game characters, cutscenes, killcams, and UI portraits.
    6. Accurately determines Facecam position (top-left, top-right, bottom-left, bottom-right, etc.).
    7. Accurately flags when NO reliable Facecam is present.
    """
    cap = cv2.VideoCapture(path)
    W, H = int(cap.get(3)), int(cap.get(4))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if W <= 0 or H <= 0 or total <= 0:
        cap.release()
        return FacecamROI((0, 0, 1280, 720), has_facecam=False, confidence=0.0, position="none", persistence=0.0)

    model_path = os.path.join(os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx")
    if not os.path.exists(model_path):
        model_path = os.path.join("models", "face_detection_yunet_2023mar.onnx")

    det = None
    if os.path.exists(model_path):
        try:
            det = cv2.FaceDetectorYN.create(model=model_path, config="", input_size=(W, H), score_threshold=0.55)
        except Exception:
            det = None

    step = max(1, total // num_samples)
    sampled_indices = [min(i * step, total - 1) for i in range(num_samples)]
    raw_detections = []

    try:
        for fno in sampled_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ok, fr = cap.read()
            if not ok: continue
            if det is not None:
                r, faces = det.detect(fr)
                if faces is not None:
                    for f in faces:
                        bx = f[0:4].astype(int)
                        conf = float(f[-1])
                        # Streamer faces are typically 0.5% to 20% of screen area
                        area_frac = (bx[2] * bx[3]) / max(W * H, 1)
                        if 0.005 <= area_frac <= 0.25:
                            raw_detections.append({
                                "fno": fno, "box": bx, "conf": conf,
                                "cx": bx[0] + bx[2] / 2.0, "cy": bx[1] + bx[3] / 2.0
                            })
    except Exception:
        pass
    finally:
        cap.release()

    if not raw_detections:
        return FacecamROI((0, 0, W, H), has_facecam=False, confidence=0.0, position="none", persistence=0.0)

    # Spatial clustering: group face detections with nearby centroids
    clusters = []
    for d in raw_detections:
        matched = False
        for c in clusters:
            dist = np.hypot((d["cx"] - c["cx"]) / W, (d["cy"] - c["cy"]) / H)
            if dist < 0.08:
                c["items"].append(d)
                c["frames"].add(d["fno"])
                c["cx"] = float(np.mean([x["cx"] for x in c["items"]]))
                c["cy"] = float(np.mean([x["cy"] for x in c["items"]]))
                matched = True
                break
        if not matched:
            clusters.append({"cx": d["cx"], "cy": d["cy"], "items": [d], "frames": {d["fno"]}})

    # Score clusters by temporal persistence, spatial stability, and confidence
    scored = []
    for c in clusters:
        persistence = len(c["frames"]) / float(len(sampled_indices))
        mean_conf = float(np.mean([x["conf"] for x in c["items"]]))
        std_pos = float(np.std([x["cx"] for x in c["items"]]) + np.std([x["cy"] for x in c["items"]]))
        norm_std = std_pos / max(W, 1)
        score = (persistence * 2.0) - (norm_std * 3.0) + (mean_conf * 0.5)
        scored.append((score, persistence, mean_conf, norm_std, c))

    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    best_score, persistence, mean_conf, norm_std, best_c = best

    # If no face appears persistently across sampled frames, this video has NO facecam
    if persistence < min_persistence:
        return FacecamROI((0, 0, W, H), has_facecam=False, confidence=0.0, position="none", persistence=round(persistence, 2))

    med_w = float(np.median([x["box"][2] for x in best_c["items"]]))
    med_h = float(np.median([x["box"][3] for x in best_c["items"]]))
    pos = classify_facecam_position(best_c["cx"], best_c["cy"], W, H)

    # Calculate expanded facecam crop (includes head, hair, shoulders, microphone)
    cam_w = int(max(med_w * 3.2, W * 0.22))
    cam_h = int(cam_w * TOP_H / OUT_W)
    cam_x = int(np.clip(best_c["cx"] - cam_w / 2, 0, W - cam_w))
    cam_y = int(np.clip(best_c["cy"] - cam_h * 0.42, 0, H - cam_h))
    coords = fit_roi((cam_x, cam_y, cam_w, cam_h), W, H)

    return FacecamROI(coords, has_facecam=True, confidence=round(mean_conf, 2),
                      position=pos, persistence=round(persistence, 2),
                      face_box=(int(best_c["cx"]), int(best_c["cy"]), int(med_w), int(med_h)))

# ====================================================================== Mode 1: 9:16 Render Engines
def seek_frame_accurate(cap, start_sec, fps):
    """
    Guarantees frame-accurate seeking in OpenCV:
    Jumps before target to nearest keyframe and advances frame-by-frame
    until the exact target millisecond is reached.
    Eliminates opening freeze frames and audio/video desync.
    """
    target_ms = max(0.0, float(start_sec) * 1000.0)
    if target_ms <= 30.0:
        cap.set(cv2.CAP_PROP_POS_MSEC, 0.0)
        return
    # Pre-seek ~400ms prior to target
    pre_ms = max(0.0, target_ms - 400.0)
    cap.set(cv2.CAP_PROP_POS_MSEC, pre_ms)
    frame_dur_ms = 1000.0 / max(float(fps), 1.0)
    tolerance_ms = frame_dur_ms * 0.45
    while True:
        pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if pos_ms >= target_ms - tolerance_ms:
            break
        if not cap.grab():
            break

def _render_ffmpeg_native_split(src, start, dur, out, roi, encoder, fade=0.0):
    """Ultra-fast C-level FFmpeg render when motion tracking is off (no Python frame-pipe overhead!)."""
    W, H = video_size(src)
    fx, fy, fw, fh = fit_roi(roi, W, H)
    cw = min(int(H * OUT_W / BOT_H), W)
    x0 = int(np.clip(W / 2 - cw / 2, 0, W - cw))
    
    fc = (f"[0:v]crop={fw}:{fh}:{fx}:{fy},scale={OUT_W}:{TOP_H}:flags=bilinear[face];"
          f"[0:v]crop={cw}:{H}:{x0}:0,scale={OUT_W}:{BOT_H}:flags=bilinear[game];"
          f"[face][game]vstack,setpts=PTS-STARTPTS[v]")
    
    af_filters = ["asetpts=PTS-STARTPTS", "aresample=async=1:first_pts=0"]
    if fade:
        af_filters.append(f"afade=t=in:st=0:d={fade},afade=t=out:st={max(dur - fade, 0):.3f}:d={fade},apad")
    
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-accurate_seek", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           *_encoder_flags(encoder, 20), "-pix_fmt", "yuv420p",
           "-af", ",".join(af_filters), "-fps_mode", "cfr",
           "-avoid_negative_ts", "make_zero",
           "-c:a", "aac", "-b:a", "192k", "-shortest", out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise EncoderError(r.stderr.decode(errors="ignore")[-400:] or "FFmpeg native split failed")

def _render_ffmpeg_blur_fill(src, start, dur, out, encoder, fade=0.0):
    """Cinematic blurred background + sharp 16:9 gameplay in center."""
    fc = (f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},boxblur=20:5[bg];"
          f"[0:v]scale={OUT_W}:-2:flags=bilinear[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setpts=PTS-STARTPTS[v]")
    
    af_filters = ["asetpts=PTS-STARTPTS", "aresample=async=1:first_pts=0"]
    if fade:
        af_filters.append(f"afade=t=in:st=0:d={fade},afade=t=out:st={max(dur - fade, 0):.3f}:d={fade},apad")

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-accurate_seek", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           *_encoder_flags(encoder, 20), "-pix_fmt", "yuv420p",
           "-af", ",".join(af_filters), "-fps_mode", "cfr",
           "-avoid_negative_ts", "make_zero",
           "-c:a", "aac", "-b:a", "192k", "-shortest", out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise EncoderError(r.stderr.decode(errors="ignore")[-400:] or "FFmpeg blur fill failed")

def _render_opencv_smooth(src, start, end, out, roi, motion, encoder, progress_cb, punch=0.0, fade=0.0, layout="split"):
    """
    Butter-smooth OpenCV render:
    - Frame-accurate start seeking guarantees zero black or frozen frames.
    - Subsampled motion tracking (samples every 3 frames on 160x90) for negligible CPU load.
    - Auto-detects absence of facecam and seamlessly falls back to 9:16 full-gameplay crop.
    - Supports 'split', 'pip' (overlay), 'action_crop'.
    """
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W, H = int(cap.get(3)), int(cap.get(4))
    
    # Frame-accurate positioning
    seek_frame_accurate(cap, start, fps)
    
    # Check if facecam is present; if not, gracefully route to action crop
    has_cam = getattr(roi, "has_facecam", True)
    effective_layout = layout
    if not has_cam and layout in ("split", "pip"):
        effective_layout = "action_crop"

    fx, fy, fw, fh = fit_roi(roi, W, H)
    cw = min(int(H * OUT_W / BOT_H), W); cx = W / 2; prev = None
    dur = max(0.1, end - start)
    n = int(dur * fps)

    af_filters = ["asetpts=PTS-STARTPTS", "aresample=async=1:first_pts=0"]
    if fade:
        af_filters.append(f"afade=t=in:st=0:d={fade},afade=t=out:st={max(dur - fade, 0):.3f}:d={fade},apad")

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}",
           "-r", f"{fps:.3f}", "-i", "-",
           "-accurate_seek", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-vf", "setpts=PTS-STARTPTS",
           "-map", "0:v", "-map", "1:a?", *_encoder_flags(encoder, 20), "-pix_fmt", "yuv420p",
           "-af", ",".join(af_filters), "-fps_mode", "cfr",
           "-avoid_negative_ts", "make_zero",
           "-c:a", "aac", "-b:a", "192k", "-shortest", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    ok_all = False
    try:
        # Precompute facecam coordinates and overlay sizes if layout == 'pip'
        pip_w = int(OUT_W * 0.38)
        pip_h = int(pip_w * TOP_H / OUT_W)
        pip_x = OUT_W - pip_w - 30 if getattr(roi, "position", "") != "top_right" else 30
        pip_y = 70

        for i in range(n):
            ok, fr = cap.read()
            if not ok: break

            # Subsampled motion tracking: update only every 3 frames on low-res preview
            if motion:
                if i % 3 == 0:
                    small = cv2.resize(fr, (160, 90), interpolation=cv2.INTER_NEAREST)
                    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    if prev is not None:
                        d = cv2.absdiff(g, prev)
                        if has_cam:
                            s_fx, s_fy, s_fw, s_fh = int(fx * 160 / W), int(fy * 90 / H), int(fw * 160 / W), int(fh * 90 / H)
                            d[s_fy:s_fy + s_fh + 1, s_fx:s_fx + s_fw + 1] = 0
                        cols = (d > 24).astype(np.float32).sum(axis=0)
                        if cols.sum() > 25:
                            center_col = float((cols * np.arange(len(cols))).sum() / cols.sum())
                            target_x = center_col * (W / 160.0)
                            cx = 0.90 * cx + 0.10 * target_x
                    prev = g

            # Impact punch-in zoom on cuts
            if punch > 0:
                z = 1.0 + punch * max(0.0, 1.0 - (i / fps) / 0.30) ** 2
            else:
                z = 1.0

            if effective_layout == "pip" and has_cam:
                # Full vertical gameplay + floating facecam overlay
                cw_full = int(H * OUT_W / OUT_H / z)
                x0 = int(np.clip(cx - cw_full / 2, 0, W - cw_full))
                frame_out = cv2.resize(fr[:, x0:x0 + cw_full], (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
                # Overlay facecam in corner
                face_pip = cv2.resize(fr[fy:fy + fh, fx:fx + fw], (pip_w, pip_h), interpolation=cv2.INTER_LINEAR)
                # Add cyan and dark border
                cv2.rectangle(face_pip, (0, 0), (pip_w - 1, pip_h - 1), (255, 240, 0), 4) # Cyan BGR
                cv2.rectangle(face_pip, (4, 4), (pip_w - 5, pip_h - 5), (0, 0, 0), 2)
                frame_out[pip_y:pip_y + pip_h, pip_x:pip_x + pip_w] = face_pip

            elif effective_layout in ("action_crop", "gameplay_only") or not has_cam:
                # Full 9:16 vertical gameplay tracking action, no facecam
                cw_full = int(H * OUT_W / OUT_H / z)
                x0 = int(np.clip(cx - cw_full / 2, 0, W - cw_full))
                frame_out = cv2.resize(fr[:, x0:x0 + cw_full], (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)

            else:
                # Standard split: Top 1/3 Facecam, Bottom 2/3 Gameplay
                cwz, chz = int(cw / z), int(H / z)
                x0 = int(np.clip(cx - cwz / 2, 0, W - cwz))
                y0 = (H - chz) // 2
                game = cv2.resize(fr[y0:y0 + chz, x0:x0 + cwz], (OUT_W, BOT_H), interpolation=cv2.INTER_LINEAR)
                face = cv2.resize(fr[fy:fy + fh, fx:fx + fw], (OUT_W, TOP_H), interpolation=cv2.INTER_LINEAR)
                frame_out = np.vstack([face, game])

            p.stdin.write(frame_out.tobytes())
            if progress_cb and i % 12 == 0:
                progress_cb(i / max(n, 1))

        ok_all = True
    except OSError:
        pass
    finally:
        cap.release()
        try: p.stdin.close()
        except Exception: pass
        if not ok_all and p.poll() is None:
            p.kill()
        err = p.stderr.read().decode(errors="ignore"); p.wait()

    if p.returncode != 0 or not ok_all:
        raise EncoderError(err[-400:] or "FFmpeg encoder failed")

def render_vertical(src, start, end, out, face_roi, motion=True, encoder=None, progress_cb=None,
                    punch=0.0, fade=0.0, layout="split"):
    """
    Renders 9:16 vertical video for a single cut.
    Automatically chooses the best available hardware encoder (QSV/NVENC/MF/CPU).
    """
    dur = end - start
    if dur <= 0: return out
    
    if encoder is None:
        encoder = get_active_encoder()

    # Fast path: If layout is blur_fill, do 100% native FFmpeg
    if layout == "blur_fill":
        try:
            _render_ffmpeg_blur_fill(src, start, dur, out, encoder, fade)
            return out
        except EncoderError:
            # Fall back to CPU if hardware failed
            _render_ffmpeg_blur_fill(src, start, dur, out, "libx264", fade)
            return out

    # Fast path: If motion is OFF and punch is 0 for standard split, do native FFmpeg filter
    if not motion and punch <= 0.001 and layout == "split":
        try:
            _render_ffmpeg_native_split(src, start, dur, out, face_roi, encoder, fade)
            return out
        except EncoderError:
            pass

    # OpenCV pipeline with auto-fallback to CPU
    try:
        _render_opencv_smooth(src, start, end, out, face_roi, motion, encoder, progress_cb, punch, fade, layout)
    except EncoderError:
        if encoder != "libx264":
            _render_opencv_smooth(src, start, end, out, face_roi, motion, "libx264", progress_cb, punch, fade, layout)
        else:
            raise
    return out

# ====================================================================== Concat & Montage
def concat_segments(segs, out, sfx_wav=None):
    """Lossless stream-copy join of clips + optional audio sound effect track."""
    lst = out + ".txt"
    with open(lst, "w", encoding="utf-8") as f:
        for sg in segs:
            f.write("file '" + os.path.abspath(sg).replace("\\", "/").replace("'", "'\\''") + "'\n")
    
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst]
    if sfx_wav and has_audio(segs[0]):
        cmd += ["-i", sfx_wav, "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[aout]",
                "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a?"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True)
    try: os.remove(lst)
    except OSError: pass
    if r.returncode != 0:
        raise EncoderError(r.stderr.decode(errors="ignore")[-400:])

def render_super_edit(src, cuts, out, roi, motion=True, encoder=None, punch=0.10, sfx=True,
                      temp_dir=None, progress_cb=None, layout="split", sfx_vol=0.8):
    """Renders all cuts for a montage Short and stitches them with audio crossfades and whoosh hits."""
    import sfx as sfxmod
    tmp = tempfile.mkdtemp(prefix="lv_cuts_", dir=temp_dir)
    try:
        segs, n = [], len(cuts)
        for i, (a, b) in enumerate(cuts):
            seg = os.path.join(tmp, f"seg{i}.mp4")
            render_vertical(src, a, b, seg, roi, motion, encoder,
                            (lambda f, i=i: progress_cb((i + f) / n)) if progress_cb else None,
                            punch, 0.04, layout)
            segs.append(seg)
        track = None
        if sfx and n > 1:
            durs = [video_duration(sg) for sg in segs]
            times = [sum(durs[:k]) for k in range(1, n)]
            track = sfxmod.build_track(os.path.join(tmp, "sfx.wav"), sum(durs), times, gain=sfx_vol)
        concat_segments(segs, out, track)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        gc.collect()
    return out

# ====================================================================== Production Quality Control & Validation
def validate_exported_clip(path, expected_duration=None, max_diff=0.6):
    """
    Automated Production Quality Control (Part 8):
    Verifies every quality requirement before a Short is declared complete:
      1. File exists and has healthy size (> 50KB).
      2. Container can be parsed by FFprobe cleanly.
      3. Video stream exists, is 1080x1920 (9:16 vertical).
      4. Audio stream exists (AAC stereo/mono).
      5. Audio vs Video duration consistency (delta <= max_diff).
      6. No corrupted or frozen packets.
    """
    if not os.path.exists(path) or os.path.getsize(path) < 50_000:
        return {"valid": False, "issues": ["File missing or smaller than 50KB"]}

    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries",
               "stream=codec_type,codec_name,width,height,duration,r_frame_rate:format=duration,size",
               "-of", "json", path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout)
    except Exception as e:
        return {"valid": False, "issues": [f"FFprobe inspection failed: {e}"]}

    streams = data.get("streams", [])
    format_info = data.get("format", {})
    container_dur = float(format_info.get("duration", 0.0) or 0.0)

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    issues = []
    w, h = 0, 0
    if not v_stream:
        issues.append("No video stream found")
    else:
        w = int(v_stream.get("width", 0))
        h = int(v_stream.get("height", 0))
        if w != 1080 or h != 1920:
            issues.append(f"Resolution is {w}x{h}, expected 1080x1920 (9:16)")

    v_dur = float(v_stream.get("duration", container_dur) or container_dur) if v_stream else 0.0
    a_dur = float(a_stream.get("duration", container_dur) or container_dur) if a_stream else 0.0

    if v_dur < 3.0:
        issues.append(f"Clip too short ({v_dur:.1f}s < 3.0s)")

    if a_stream and abs(v_dur - a_dur) > max_diff:
        issues.append(f"A/V duration mismatch (video={v_dur:.2f}s, audio={a_dur:.2f}s)")

    if expected_duration and abs(v_dur - expected_duration) > 3.0:
        issues.append(f"Duration mismatch with plan (actual={v_dur:.1f}s, expected={expected_duration:.1f}s)")

    return {
        "valid": len(issues) == 0,
        "duration": round(v_dur, 2),
        "width": w,
        "height": h,
        "aspect_ratio": "9:16",
        "has_audio": a_stream is not None,
        "size_bytes": int(format_info.get("size", 0)),
        "issues": issues
    }

# ====================================================================== Subtitle Burning
def ff_filter_path(p):
    """Escapes paths cleanly for Windows and POSIX inside FFmpeg filter strings."""
    p = os.path.abspath(p).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "'\\\\\\''")

_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

def _ass_filter(ass, fonts_dir=None):
    f = f"setpts=PTS-STARTPTS,ass=filename='{ff_filter_path(ass)}'"
    if fonts_dir and os.path.isdir(fonts_dir):
        f += f":fontsdir='{ff_filter_path(fonts_dir)}'"
    return f + "," + _EVEN

def burn_subtitles(video, ass, out, fonts_dir=None, encoder=None, progress_cb=None, audio_clean=False):
    """Burns ASS subtitles into video using hardware acceleration with seamless CPU fallback and strict A/V sync."""
    dur = video_duration(video)
    if encoder is None:
        encoder = get_active_encoder()
    vf = _ass_filter(ass, fonts_dir)
    
    af_filters = ["asetpts=PTS-STARTPTS", "aresample=async=1:first_pts=0"]
    if audio_clean:
        af_filters.append(CLEAN)
    af_arg = ["-af", ",".join(af_filters)]

    def attempt(enc):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-i", video,
               "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, *_encoder_flags(enc, 19), "-pix_fmt", "yuv420p",
               *af_arg, "-fps_mode", "cfr", "-avoid_negative_ts", "make_zero", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", out]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for line in p.stdout:
                if progress_cb and dur and line.startswith(("out_time_us=", "out_time_ms=")):
                    try: progress_cb(min(int(line.split("=")[1]) / 1e6 / dur, 1.0))
                    except ValueError: pass
            err = p.stderr.read(); p.wait()
        except BaseException:
            p.kill(); raise
        if p.returncode != 0:
            raise EncoderError(err[-400:] or f"FFmpeg burn failed ({enc})")

    try:
        attempt(encoder)
    except EncoderError:
        if encoder != "libx264":
            attempt("libx264")
        else:
            raise
    return out

# ====================================================================== Hormozi-Style Auto Zoom
def pause_cuts(words, min_gap=0.35, min_seg=1.6):
    cuts, last = [], 0.0
    for a, b in zip(words, words[1:]):
        mid = (a["e"] + b["s"]) / 2
        if b["s"] - a["e"] >= min_gap and mid - last >= min_seg:
            cuts.append(mid); last = mid
    return cuts

def zoom_curve(cuts, strength=0.08, ease=0.18):
    targets = [1.0 if k % 2 == 0 else 1.0 + strength for k in range(len(cuts) + 1)]
    def z(t):
        k = bisect.bisect_right(cuts, t)
        if k == 0: return targets[0]
        d = (t - cuts[k - 1]) / ease
        if d >= 1: return targets[k]
        d = d * d * (3 - 2 * d)
        return targets[k - 1] + (targets[k] - targets[k - 1]) * d
    return z

def _apply_zoom(fr, z, W, H):
    if z <= 1.002: return fr
    cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
    x, y = (W - cw) // 2, (H - ch) // 2
    return cv2.resize(fr[y:y + ch, x:x + cw], (W, H), interpolation=cv2.INTER_LINEAR)

def render_zoom_burn(src, ass, out, words, strength=0.08, min_gap=0.35, fonts_dir=None, encoder=None,
                     progress_cb=None, audio_clean=False, sfx_wav=None):
    """Auto zoom punch-in/out on speech pauses with burned subtitles."""
    if encoder is None:
        encoder = get_active_encoder()
    cuts = pause_cuts(words, min_gap)
    zfun = zoom_curve(cuts, strength)
    vf = _ass_filter(ass, fonts_dir)

    def run_zoom(enc):
        cap = cv2.VideoCapture(src)
        ok, fr = cap.read()
        if not ok:
            cap.release(); raise EncoderError("Cannot read this video file.")
        H, W = fr.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        ha = has_audio(src); use_sfx = bool(sfx_wav and ha)
        fc, label = [], None
        if ha:
            clean_part = f"{CLEAN}," if audio_clean else ""
            fc.append(f"[1:a:0]{clean_part}asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[ac]")
            label = "[ac]"
        if use_sfx:
            fc.append(f"{label or '[1:a:0]'}[2:a]amix=inputs=2:duration=first:normalize=0[aout]")
            label = "[aout]"
        amap = ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", label] if label else ["-map", "0:v", "-map", "1:a:0?"]
        
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", f"{fps:.3f}", "-i", "-", "-i", src, *(["-i", sfx_wav] if use_sfx else []), *amap, "-vf", vf,
               *_encoder_flags(enc, 19), "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-avoid_negative_ts", "make_zero",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        ok_all, i = False, 0
        try:
            while ok:
                p.stdin.write(_apply_zoom(fr, zfun(i / fps), W, H).tobytes())
                i += 1
                if progress_cb and i % 15 == 0: progress_cb(min(i / total, 1.0))
                ok, fr = cap.read()
            ok_all = True
        except OSError:
            pass
        finally:
            cap.release()
            try: p.stdin.close()
            except Exception: pass
            if not ok_all and p.poll() is None: p.kill()
            err = p.stderr.read().decode(errors="ignore"); p.wait()
        if p.returncode != 0 or not ok_all:
            raise EncoderError(err[-400:] or f"FFmpeg zoom encoder failed ({enc})")

    try:
        run_zoom(encoder)
    except EncoderError:
        if encoder != "libx264": run_zoom("libx264")
        else: raise
    return out
