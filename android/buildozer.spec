[app]

# (str) Title of your application
title = Lidl Receipt Manager

# (str) Package name
package.name = lidlreceipts

# (str) Package domain (needed for android/ios packaging)
package.domain = org.lidlreceipts

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,ttf

# (str) Application versioning (method 1)
version = 1.0

# (list) Application requirements
# python3/kivy/kivymd = the app; pyjnius = call ML Kit; plyer = camera + file
# picker; android = permissions API. (Pillow intentionally omitted: it's only
# used by the desktop OCR fallback; on Android OCR is ML Kit, so PIL isn't
# needed and would add a fragile native build.)
requirements = python3,kivy==2.3.0,kivymd==1.1.1,pyjnius,plyer,android

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (list) Supported orientations
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = CAMERA, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 34

# (int) Minimum API your APK / AAB will support.
android.minapi = 24

# (str) Android NDK version to use. 25b matches the pinned p4a below.
android.ndk = 25b

# (list) The Android archs to build for.
android.archs = arm64-v8a, armeabi-v7a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (list) Gradle dependencies to add
# Google ML Kit on-device Latin text recognition (used by core/ocr.py).
android.gradle_dependencies = com.google.mlkit:text-recognition:16.0.0

# (bool) If True, then automatically accept SDK license
android.accept_sdk_license = True

# (str) The format used to package the app for release mode (aab or apk).
android.release_artifact = apk

# (str) The format used to package the app for debug mode (apk or aar).
android.debug_artifact = apk

# (str) python-for-android branch/tag to use.
# Pinned to the 2024.01.21 release, which builds Python 3.11. The p4a master
# default (Python 3.14) does NOT compile Kivy 2.3.0 (private CPython C-API
# functions like _PyLong_AsByteArray changed/were removed in 3.14).
p4a.branch = v2024.01.21


[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
