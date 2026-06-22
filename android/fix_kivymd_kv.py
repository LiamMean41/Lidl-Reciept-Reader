"""Desktop-only helper: restore KivyMD 1.1.1's bundled data files.

KivyMD 1.1.1 is sdist-only on PyPI, and modern setuptools drops ALL of its
non-Python package data when building that sdist: ``.kv`` layouts, GLSL shaders
(``.frag``/``.vert``), fonts and images. The .py modules then fail with errors
like ``FileNotFoundError: ... label.kv`` (import time) or
``... data/glsl/elevation/header.frag`` (at runtime). This script copies every
non-``.py`` asset out of the official sdist into your installed kivymd package
so the desktop preview runs.

Only needed for running ``python main.py`` on a PC. The Android APK build is
unaffected (python-for-android packages KivyMD differently).

Usage (inside your desktop venv):
    python fix_kivymd_kv.py
"""
import io
import json
import os
import tarfile
import urllib.request


def main():
    import kivymd
    if kivymd.__version__ != "1.1.1":
        print(f"Note: installed KivyMD is {kivymd.__version__}, expected 1.1.1.")

    dest_root = os.path.dirname(kivymd.__file__)
    meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/kivymd/1.1.1/json"))
    url = next(f["url"] for f in meta["urls"] if f["packagetype"] == "sdist")
    print("Downloading", url)
    raw = urllib.request.urlopen(url).read()

    copied = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")
            if "kivymd" not in parts:
                continue
            rel = "/".join(parts[parts.index("kivymd") + 1:])
            # .py modules are already installed correctly; restore everything
            # else (the dropped data files: kv, frag, vert, png, ttf, json...).
            if rel.endswith(".py") or not rel:
                continue
            out = os.path.join(dest_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(tf.extractfile(m).read())
            copied += 1
    print(f"Restored {copied} data files into {dest_root}")


if __name__ == "__main__":
    main()
