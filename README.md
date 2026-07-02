# RuneKit

Alt1-compatible toolbox for RuneScape 3, for macOS and Linux.

This is an actively-maintained fork of [whs/runekit](https://github.com/whs/runekit),
modernized to run on current macOS with the current Jagex-launcher `rs2client`.

* [Compatibility](https://github.com/whs/runekit/wiki/App-Compatibility)
* [Troubleshooting](https://github.com/whs/runekit/wiki/Troubleshooting)

## What's new in this fork

- **Runs on current macOS** (tested on macOS 26) with the current `rs2client`.
- Migrated **PySide2 → PySide6** and **Python 3.9 → 3.12**.
- Screen capture via **ScreenCaptureKit** — the old `CGWindowListCreateImage*`
  APIs return nothing on macOS 15+.
- Native **`alt1.bindFindSubImg`** with Retina-tolerant matching, so
  image-detection apps (clue solver, quest dialog solvers, …) work on HiDPI
  displays where Alt1's exact pixel matcher can't.
- Bundles **[RS3 Quest Buddy](https://techpure.dev/RS3QuestBuddy)** as a
  built-in app.

## Installing

### Linux

1. [Download RuneKit.AppImage](https://github.com/whs/runekit/releases/tag/continuous)
2. Mark file as executable (`chmod +x`)
3. Start the game
4. Run `RuneKit.AppImage`.
   - On first start it will download app list
5. Right click the tray icon and start any application

### macOS

1. [Download RuneKit.app](https://github.com/whs/runekit/releases/tag/continuous) and unzip (if you use Safari it should automatically unzip)
2. Open Terminal (search in spotlight/launchpad if you can't find it)
3. Type `xattr -dr com.apple.quarantine ` (including trailing space) and drop the app onto Terminal so it would be like `yourname@yourmacname ~ % xattr -dr com.apple.quarantine /Users/yourname/Downloads/RuneKit.app`. Press enter.
4. Launch the app. The first launch might spring in the dock for a good minute.
5. If a permission prompt appears, grant it in System Settings > Privacy & Security. **Then quit RuneKit (right click dock icon > quit or force quit) and start it again.** Don't quit RuneKit while it is downloading the app list! The permissions are:
   - Accessibility - for access to the game window
   - Input Monitoring - for hooking alt+1 and idle detection
   - Screen Recording - for capturing the game
6. Once all permissions have been granted the application appears as a system tray icon (top right)

> **Note:** the released builds above are from upstream and predate this fork's
> macOS modernization. Until a new build is published, run from source on macOS
> (see Developer below).

## Troubleshooting

[See wiki](https://github.com/whs/runekit/wiki/Troubleshooting)

## Developer

Requires **Python 3.12** and [Poetry](https://python-poetry.org).

```sh
poetry install
poetry run make dev            # builds Qt resources with pyside6-rcc

# Load a specific app by its appconfig URL, e.g. AFKWarden:
poetry run python main.py https://runeapps.org/apps/alt1/afkscape/appconfig.json

# Or start in tray mode and pick an app from the tray:
poetry run python main.py
```

Or, without Poetry, use a plain virtualenv:

```sh
python3.12 -m venv .venv
.venv/bin/pip install PySide6 requests Pillow click psutil opencv-python-headless \
    pyobjc-framework-Quartz pyobjc-framework-ApplicationServices \
    pyobjc-framework-CoreText pyobjc-framework-ScreenCaptureKit
.venv/bin/pyside6-rcc resources.qrc -o runekit/_resources.py
.venv/bin/python main.py
```

Set the env var `QTWEBENGINE_REMOTE_DEBUGGING=9222` to enable the remote
debugger protocol, then open `chrome://inspect` in Chrome/Chromium.

### Building .app on Mac

1. Run the normal build steps
2. XCode > Settings > Account and download your dev key
3. Set `codesign_identity` in `RuneKit.spec` or leave it `None` for ad-hoc sign
4. `poetry run make dist/RuneKit.app.zip`

## License

This project is [licensed](LICENSE) under GPLv3, and contains code from
[third parties](THIRD_PARTY_LICENSE.md). Contains code from the Alt1 application.

Please do not contact Alt1 or RuneApps.org for support.
