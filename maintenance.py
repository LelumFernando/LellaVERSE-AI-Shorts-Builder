"""System maintenance - safe cleanup helpers. NEVER touches the outputs folder."""
import os, shutil

RAW_EXT = (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".part", ".ytdl", ".temp")

def _real(p): return os.path.realpath(os.path.abspath(p))

def _within(child, parent):
    c, p = _real(child), _real(parent)
    try: return os.path.commonpath([c, p]) == p
    except ValueError: return False                       # different drives (Windows)

def folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                try: total += os.path.getsize(fp)
                except OSError: pass
    return total

def raw_downloads(work_dir):
    """Top-level raw video/audio files in the downloads folder (sub-folders such as fonts/ are never listed)."""
    if not os.path.isdir(work_dir): return []
    return [os.path.join(work_dir, n) for n in os.listdir(work_dir)
            if os.path.isfile(os.path.join(work_dir, n)) and n.lower().endswith(RAW_EXT)]

def _refuse(a, b):
    ra, rb = _real(a), _real(b)
    return ra == rb or _within(ra, rb) or _within(rb, ra)

def clear_temp(temp_dir, out_dir):
    """Empty temp_dir (keeps the folder itself). Refuses if temp and outputs overlap in any way."""
    if _refuse(temp_dir, out_dir):
        return {"files": 0, "bytes": 0, "refused": "temp and outputs folders overlap - nothing deleted"}
    n = freed = 0
    if os.path.isdir(temp_dir):
        for name in os.listdir(temp_dir):
            p = os.path.join(temp_dir, name)
            if _within(p, out_dir): continue
            try:
                if os.path.islink(p): os.unlink(p)
                elif os.path.isfile(p): freed += os.path.getsize(p); os.remove(p); n += 1
                else: freed += folder_size(p); shutil.rmtree(p, ignore_errors=True); n += 1
            except OSError: pass
    return {"files": n, "bytes": freed, "refused": None}

def delete_raw_downloads(work_dir, out_dir):
    """Delete raw downloaded videos in work_dir only. Skips anything inside outputs."""
    if _refuse(work_dir, out_dir) and _real(work_dir) != _real(out_dir) and _within(out_dir, work_dir):
        pass                                              # outputs nested in work_dir: files are filtered below
    elif _real(work_dir) == _real(out_dir):
        return {"files": 0, "bytes": 0, "refused": "downloads folder is the outputs folder - nothing deleted"}
    n = freed = 0
    for p in raw_downloads(work_dir):
        if _within(p, out_dir): continue
        try: freed += os.path.getsize(p); os.remove(p); n += 1
        except OSError: pass
    return {"files": n, "bytes": freed, "refused": None}
