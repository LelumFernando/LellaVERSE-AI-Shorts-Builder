# Third-Party Software Notices & Acknowledgements

**LellaVERSE AI Shorts Builder v1.0.0** incorporates, links to, or interfaces with the following open-source software packages and external APIs. LellaVERSE and its author gratefully acknowledge the contributions of the respective open-source communities.

---

### 1. FFmpeg
- **Website:** https://ffmpeg.org
- **License:** GNU Lesser General Public License (LGPL) version 2.1+ / GNU General Public License (GPL) version 2+
- **Usage:** Video decoding, audio filtering (`silencedetect`, `ebur128`, `volumedetect`), hardware encoding via Intel Quick Sync (`h264_qsv`), NVENC, and container PTS synchronization.
- **Notice:** FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project. Binaries are compiled and distributed under Gyan.D FFmpeg build terms. Source code for FFmpeg is available at https://ffmpeg.org/download.html.

---

### 2. OpenCV (Open Source Computer Vision Library)
- **Website:** https://opencv.org
- **License:** Apache License 2.0
- **Usage:** Frame extraction, YuNet CNN deep learning face detection (`face_detection_yunet_2023mar.onnx`), face tracking, and motion stabilization.

---

### 3. Streamlit
- **Website:** https://streamlit.io
- **License:** Apache License 2.0
- **Usage:** Native desktop interactive user interface, real-time job progress tracking, and sidebar configuration.

---

### 4. Google GenAI SDK (Google Gemini API)
- **Website:** https://github.com/google-gemini/generative-ai-python
- **License:** Apache License 2.0
- **Usage:** High-level AI stream highlight detection, excitement scene analysis, and verbatim bilingual speech transcription.
- **Notice:** Google, Gemini, and YouTube are trademarks of Google LLC. Use of Google Gemini API is subject to Google Cloud Terms of Service and Google AI Studio Terms.

---

### 5. Faster-Whisper & CTranslate2
- **Website:** https://github.com/SYSTRAN/faster-whisper
- **License:** MIT License
- **Usage:** Offline fallback speech recognition engine.

---

### 6. NumPy & Pillow
- **Website:** https://numpy.org | https://python-pillow.org
- **License:** BSD 3-Clause License | HPND License
- **Usage:** Frame array operations, visual image processing, and color palette extraction.

---

### 7. Google Fonts (SIL Open Font License 1.1)
The following fonts included in `assets/fonts/` are licensed under the SIL Open Font License, Version 1.1:
- **Noto Sans Sinhala & Noto Serif Sinhala:** Copyright Google LLC (OFL 1.1)
- **Poppins:** Copyright Indian Type Foundry (OFL 1.1)
- **Abhaya Libre:** Copyright Sol Matas and Pushpananda Ekanayake (OFL 1.1)
The complete OFL text is preserved in `assets/fonts/OFL.txt`.

---

### 8. Python
- **Website:** https://www.python.org
- **License:** Python Software Foundation (PSF) License
- **Usage:** Core application runtime.
