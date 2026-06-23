# Lidl Receipt Manager

Read your Lidl (Ireland) receipts, build a searchable product/price history, and
turn it into tick-off shopping lists. Ships as a **desktop app** (PyQt5) and an
**Android port** (KivyMD) that reuse the same receipt parser and SQLite schema.

## Features

- **Import receipts three ways** — from a photo/screenshot (OCR), from a `.txt`
  file, or by pasting the receipt text directly.
- **Product price database** — every imported line item is stored, then rolled
  up per product with average / min / max unit price, how many times you've
  bought it, and when you last did.
- **Search** products as you type.
- **Shopping lists** — add products (pre-filled with their latest price), add
  manual items, tick things off as you shop, and watch a live "remaining" total.
- **Duplicate-safe** — receipts are de-duplicated by their transaction ID, so
  re-importing the same receipt won't double-count.
- **Local & offline** — all data lives in a local SQLite database. Nothing is
  sent anywhere.

## Repository layout

```
.
├── lidlReceiptManager.py     # Desktop app (PyQt5) — single file
└── android/                  # Android port (KivyMD), see android/README_ANDROID.md
    ├── main.py               # Touch UI (KivyMD bottom-nav)
    ├── core/
    │   ├── parser.py         # parse_receipt() — shared with desktop
    │   ├── db.py             # SQLite layer (same schema)
    │   └── ocr.py            # ML Kit on Android, pytesseract on desktop
    └── buildozer.spec        # APK build config
```

## Desktop app

### Requirements

- Python 3
- [PyQt5](https://pypi.org/project/PyQt5/)
- *Optional, for image import:* [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
  plus `pytesseract` and `pillow`

### Install & run

```bash
pip install PyQt5
pip install pytesseract pillow      # optional — only needed for image import
python lidlReceiptManager.py
```

On Linux, image import also needs the Tesseract engine itself:

```bash
sudo apt install tesseract-ocr
```

On Windows the app auto-detects Tesseract in the usual install locations. If you
don't install OCR, the **Text file** and **Paste** import options still work.

### How it works

1. **Import** a receipt from the *Products* tab (image / text file / paste).
2. The parser extracts the store, date, transaction ID, total, and each line
   item (name, quantity, unit price, line total, VAT class), discarding deposit
   lines and noise.
3. Items are written to a local SQLite database and aggregated into the products
   table.
4. Select products and **Add → a shopping list**, or build a list by hand in the
   *Shopping Lists* tab, then tick items off while you shop.

### Data location

A local SQLite database at `~/.lidl_receipts/receipts.db` (Android uses the
app's private storage instead). Delete that file to start fresh.

## Android app

A KivyMD rewrite packaged as an installable `.apk`. The receipt parser and
database schema are reused unchanged; only the UI was rebuilt for touch, and OCR
runs on-device via Google ML Kit (offline). On Android, photos can be captured
straight from the camera.

See **[android/README_ANDROID.md](android/README_ANDROID.md)** for desktop
testing, building the APK (via WSL2/Linux), and installing on a phone.

## Notes

- Built for **Lidl Ireland** receipt formats; other regions/layouts may need
  parser tweaks (see the regexes at the top of `lidlReceiptManager.py` /
  `android/core/parser.py`).
- OCR accuracy depends on photo quality — fill the frame, use good light, and
  keep the receipt flat. If a photo parses poorly, use **Paste**.
