# Lidl Receipt Manager — Android port

A KivyMD rewrite of the desktop PyQt5 app, packaged as an installable Android
`.apk`. Your receipt-parsing logic and SQLite database are reused unchanged; only
the UI layer was rebuilt for touch.

```
android/
├── main.py                 # KivyMD app (UI)
├── core/
│   ├── parser.py           # parse_receipt() — verbatim from the desktop app
│   ├── db.py               # SQLite layer — same schema, injectable data dir
│   └── ocr.py              # ML Kit on Android, pytesseract on desktop
├── buildozer.spec          # Android build config (APK)
├── requirements-desktop.txt
└── README_ANDROID.md
```

## What changed vs. the desktop app

| Concern        | Desktop (PyQt5)              | Android (KivyMD)                          |
|----------------|------------------------------|-------------------------------------------|
| UI toolkit     | PyQt5 windows/tabs           | KivyMD bottom-nav (Products / Lists)      |
| OCR            | Tesseract via pytesseract    | Google ML Kit on-device (offline)         |
| Image input    | File dialog                  | Camera capture + file picker (plyer)      |
| DB location    | `~/.lidl_receipts`           | App private storage (`user_data_dir`)     |
| Parser & schema| —                            | **identical, reused**                     |

---

## 1. Test on your PC first (fast feedback loop)

You don't need an Android build to iterate on the UI/logic. Two gotchas on
Windows, both already worked out:

1. **Use Python 3.11 or 3.12** — Kivy 2.3.0 has no Windows wheels for Python
   3.13/3.14, so a newer interpreter fails to install it. With `uv`:
   ```bash
   uv python install 3.12
   uv venv --python 3.12 .venv-desktop
   ```
2. **KivyMD 1.1.1 is sdist-only on PyPI** and modern setuptools drops its
   bundled data files (`.kv` layouts, GLSL shaders, fonts), causing
   `FileNotFoundError` for `label.kv` (import) or `header.frag` (first render).
   The included `fix_kivymd_kv.py` restores all of them from the sdist.

Full setup from the `android/` folder:

```bash
# (with the .venv-desktop above activated, or use `uv pip`)
uv pip install --python .venv-desktop "kivy[base]==2.3.0" kivymd==1.1.1 plyer pillow pytesseract
.venv-desktop/Scripts/python fix_kivymd_kv.py      # restore KivyMD .kv files
.venv-desktop/Scripts/python main.py
```

Camera capture is phone-only; on desktop use **Paste** or **Image** (the Image
picker + OCR works on desktop if Tesseract is installed). Everything else —
products DB, search, shopping lists, tick-off — behaves exactly as on the phone.

> Verified: the UI builds and the data layer works on Python 3.12 + KivyMD 1.1.1
> with this setup.

---

## 2. Build the APK

Buildozer (the packager) **only runs on Linux/macOS**. On your Windows 10
machine, use **WSL2 (Ubuntu)** — the recommended, well-trodden path.

### One-time WSL2 + toolchain setup

```powershell
# In PowerShell (admin), install WSL2 with Ubuntu:
wsl --install -d Ubuntu
# reboot if prompted, then open the "Ubuntu" app and create a user
```

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git zip unzip openjdk-17-jdk \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
    libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

python3 -m venv ~/bz && source ~/bz/bin/activate
pip install --upgrade pip buildozer cython==0.29.36
```

### Build

Copy this `android/` folder into the WSL filesystem (building on `/mnt/c/...`
is slow and can hit path issues — prefer `~`):

```bash
cp -r "/mnt/c/Users/liam/Documents/Projects/Lidl Reciept Reader/android" ~/lidl-android
cd ~/lidl-android
cd android
buildozer -v android debug
```

The first build downloads the Android SDK/NDK and compiles everything — expect
**20–40 minutes**. Subsequent builds are minutes. The APK lands in:

```
~/lidl-android/bin/lidlreceipts-1.0-arm64-v8a_armeabi-v7a-debug.apk
```

Copy it back to Windows:

```bash
cp bin/*.apk "/mnt/c/Users/liam/Documents/Projects/Lidl Reciept Reader/"
```

---

## 3. Install on your phone

- **USB:** enable Developer Options → USB debugging, then
  `buildozer android deploy run` (or `adb install bin/*.apk`).
- **Manual:** transfer the `.apk` to the phone and tap it (allow "install from
  unknown sources").

On first launch, grant Camera + Storage permissions when prompted.

---

## Notes & gotchas

- **KivyMD version is pinned to 1.1.1** in both `buildozer.spec` and
  `requirements-desktop.txt`. KivyMD's API changes a lot between releases — keep
  these in sync if you upgrade.
- **ML Kit** is pulled in via `android.gradle_dependencies` in `buildozer.spec`.
  It bundles the Latin text-recognition model into the APK (offline, no Google
  account needed).
- If a build fails midway, `buildozer android clean` then rebuild. The very
  first SDK-license step needs network access (`android.accept_sdk_license` is
  set so it won't prompt).
- Receipt OCR accuracy depends on photo quality — fill the frame, good light,
  flat receipt. If a photo parses poorly, use **Paste**.
