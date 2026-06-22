"""Pluggable OCR backend.

On Android we use Google ML Kit's on-device text recognizer (added to the build
via ``android.gradle_dependencies`` in buildozer.spec) through pyjnius. It runs
fully offline and needs no extra setup on the phone.

On desktop (for development/testing) we fall back to ``pytesseract`` if it and
Tesseract are installed. This lets you exercise the whole app with
``python main.py`` on your PC before building the APK.

Public API:
    ocr_available() -> bool
    image_to_text(path) -> str
"""
import os
import sys

ON_ANDROID = 'ANDROID_ARGUMENT' in os.environ or hasattr(sys, 'getandroidapilevel')


# --------------------------------------------------------------------------- #
#  Android backend: Google ML Kit text recognition via pyjnius
# --------------------------------------------------------------------------- #
def _android_image_to_text(path):
    from jnius import autoclass

    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    InputImage = autoclass('com.google.mlkit.vision.common.InputImage')
    TextRecognition = autoclass('com.google.mlkit.vision.text.TextRecognition')
    TextRecognizerOptions = autoclass(
        'com.google.mlkit.vision.text.latin.TextRecognizerOptions')
    Tasks = autoclass('com.google.android.gms.tasks.Tasks')
    File = autoclass('java.io.File')
    Uri = autoclass('android.net.Uri')

    context = PythonActivity.mActivity
    # The gallery/file picker returns a content:// URI; the camera returns a
    # plain filesystem path. InputImage.fromFilePath() accepts either as a Uri,
    # but we must build the Uri the right way for each.
    if str(path).startswith('content://'):
        uri = Uri.parse(path)
    else:
        uri = Uri.fromFile(File(path))
    image = InputImage.fromFilePath(context, uri)

    recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    # Tasks.await() blocks the calling (background) thread until OCR completes.
    # 'await' is a reserved word in Python, so reach the Java method via getattr.
    task_await = getattr(Tasks, 'await')
    result = task_await(recognizer.process(image))
    return result.getText() or ''


# --------------------------------------------------------------------------- #
#  Desktop backend: pytesseract (optional, dev only)
# --------------------------------------------------------------------------- #
def _desktop_backend():
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except Exception:
        return None
    # Point pytesseract at the Tesseract executable if it isn't already on PATH
    # (mirrors the original desktop app: common Windows install locations).
    cmd = pytesseract.pytesseract.tesseract_cmd
    if not cmd or os.path.basename(cmd).lower() in ('tesseract', 'tesseract.exe'):
        for cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join(os.environ.get('LOCALAPPDATA', ''),
                         r"Programs\Tesseract-OCR\tesseract.exe"),
        ):
            if os.path.isfile(cand):
                pytesseract.pytesseract.tesseract_cmd = cand
                break
    return pytesseract


def ocr_available():
    """True if some OCR backend is usable on the current platform."""
    if ON_ANDROID:
        return True  # ML Kit is bundled into the APK
    return _desktop_backend() is not None


def image_to_text(path):
    """Run OCR on an image file and return the recognised text.

    Raises RuntimeError if no backend is available.
    """
    if ON_ANDROID:
        return _android_image_to_text(path)

    pt = _desktop_backend()
    if pt is None:
        raise RuntimeError(
            "No OCR backend available. On desktop install: "
            "pip install pytesseract pillow (and the Tesseract binary).")
    from PIL import Image
    return pt.image_to_string(Image.open(path))
