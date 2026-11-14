# LellaVERSE AI Shorts Builder – Official Windows Installation & Setup Guide

**Version:** 1.0.0  
**Target OS:** Windows 10 & Windows 11 (64-bit)  
**Author:** Lelum Anuradha Fernando (LellaVERSE)  

---

## 1. System Requirements

### Hardware:
- **Processor:** Intel Core i3 (7th Gen+) or AMD Ryzen 3 (Quad Core minimum). Intel Core i5/i7 recommended for hardware-accelerated QSV encoding.
- **Memory (RAM):** 8 GB minimum; 16 GB recommended for 60fps livestream processing.
- **Storage:** Minimum 3 GB free disk space (SSD recommended).
- **Display:** 1080p (1920x1080) or higher resolution recommended.

### Software:
- **Operating System:** 64-bit Windows 10 (Version 1909+) or Windows 11.
- **FFmpeg:** Automatically bundled with the installation and portable packages. No manual configuration required.
- **Internet Connection:** Required for Google Gemini AI features and YouTube live stream downloads.

---

## 2. Installation Methods

### Method A: Windows Universal Setup (Recommended)
1. Download `LellaVERSE_AI_Shorts_Builder_v1.0.0_Setup.exe`.
2. Double-click the installer. If Windows SmartScreen or UAC prompts appear, click **"More info"** and **"Run anyway"**.
3. Select your installation folder (Default: `C:\Program Files\LellaVERSE AI Shorts Builder`).
4. Select whether to create a **Desktop Shortcut** and **Start Menu Shortcut**.
5. Click **"Install"**. The installer will unpack the complete runtime, FFmpeg binaries, CNN models, and application assets.
6. Check **"Launch LellaVERSE AI Shorts Builder"** and click **"Finish"**.

### Method B: Portable Package
1. Download `LellaVERSE_AI_Shorts_Builder_v1.0.0_Portable.zip`.
2. Extract the contents to any desired folder (e.g., `D:\LellaVERSE_Portable` or USB Drive).
3. Double-click `Run_LellaVerse.bat` or `LellaVERSE.exe` to launch immediately.
4. No installation or administrative privileges required.

---

## 3. First Launch & Gemini API Setup

Upon opening the application, the LellaVERSE studio interface will load in your browser (`http://localhost:8501`).

### Configuring Your Free Gemini API Key:
1. In the left sidebar, locate the **🔑 Gemini API Keys** section.
2. If you don't have an API key, click **"Get Free Key ↗"** or visit [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
3. Sign in with any Google account and click **"Create API Key"**.
4. Paste your key into the text box.
5. Click **"🔍 Check Key Quota & Health"** to verify connection.
6. *Tip:* You can paste up to **4 keys** (one per line). The application will round-robin between them and auto-switch if one reaches its daily quota.

---

## 4. Hardware Acceleration & Intel Quick Sync (QSV)

The application automatically benchmarks your PC's hardware encoders upon startup:
- **Intel Quick Sync (`h264_qsv`):** If your Intel CPU has integrated graphics (HD/UHD/Iris Graphics), QSV is automatically activated. This renders 1080x1920 shorts at 3x–6x realtime speed while using almost 0% CPU.
- **NVIDIA NVENC (`h264_nvenc`):** Automatically detected if a GeForce GTX/RTX card is present.
- **CPU Fallback (`libx264`):** If no supported GPU encoder is active, the engine automatically falls back to optimized multi-threaded CPU rendering.
- **Low-End PC Mode:** Enabled by default in the sidebar to prevent thermal throttling and maintain responsive PC performance during video exports.

---

## 5. User Data & Settings Storage

To ensure seamless upgrades without losing your preferences or API keys:
- **User Settings & API Keys Location:**  
  `%APPDATA%\LellaVERSE\settings.json`  
  *(Usually: `C:\Users\<YourUsername>\AppData\Roaming\LellaVERSE\settings.json`)*
- **Exported Videos:** Stored in the `outputs/` folder inside your application or portable directory.
- **Upgrades:** When updating to a newer version of LellaVERSE, your user settings and API keys are preserved automatically.

---

## 6. Uninstallation

To remove LellaVERSE AI Shorts Builder:
1. Open Windows **Settings** > **Apps** > **Installed apps**.
2. Search for **LellaVERSE AI Shorts Builder** and click **Uninstall**.
3. Or navigate to `C:\Program Files\LellaVERSE AI Shorts Builder\` and run `unins000.exe`.
4. The uninstaller removes all application binaries and temporary files. By default, your personal API keys and settings in `%APPDATA%\LellaVERSE` are preserved unless you choose to delete them.

---

## 7. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **"API Quota Limit Reached"** | Gemini Free Tier daily requests exhausted (20 requests/day). | Add a second free key from Google AI Studio into the sidebar, or switch Caption Engine to **Whisper (Offline fallback)**. |
| **Browser doesn't open automatically** | Security firewall blocked background browser trigger. | Open your browser and navigate manually to `http://localhost:8501`. |
| **Black screen or video not loading** | Corrupted video download or unsupported codec. | Verify the source video plays in VLC or Windows Media Player before uploading. |
| **High CPU or fan noise during export** | CPU encoding active on older hardware. | Check the **"🚀 Low-End PC Mode"** box in the sidebar to throttle CPU usage to a smooth, safe level. |

For community support and updates, join our channel:  
**YouTube:** [https://www.youtube.com/@LellaVerse](https://www.youtube.com/@LellaVerse)  
**Facebook:** [https://web.facebook.com/fb.lellaverse](https://web.facebook.com/fb.lellaverse)
