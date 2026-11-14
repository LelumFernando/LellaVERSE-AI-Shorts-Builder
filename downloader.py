"""Module A - Stream Downloader (quality limit + optional time-range download).
Author: Lelum Anuradha Fernando (LellaVerse)
"""
import os, re
import yt_dlp
from yt_dlp.utils import download_range_func

def download_video(url, out_dir="workspace", progress_cb=None, height=720, section=None):
    """Downloads YouTube live stream or video with quality limits and optional time sections."""
    os.makedirs(out_dir, exist_ok=True)

    def hook(d):
        if progress_cb and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total > 0:
                progress_cb(min(d["downloaded_bytes"] / total, 1.0))

    suffix = f"_{int(section[0])}-{int(section[1])}m" if section else ""
    opts = {
        "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
        "outtmpl": os.path.join(out_dir, f"%(id)s{suffix}.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "concurrent_fragment_downloads": 4,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"]
            }
        }
    }
    if section:
        opts["download_ranges"] = download_range_func(None, [(section[0] * 60, section[1] * 60)])
        opts["force_keyframes_at_cuts"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        target = base + ".mp4"
        return target if os.path.exists(target) else filename
