# MMacro HUD

A Windows macro for Sol's RNG with auto fishing, Eden, merchant detection and collection, clipping rare auras, auto reconnect, and Discord webhook alerts.

## Quick Start (Windows 10 / 11)

1. Make sure **Python 3.11 or newer** is installed (check **"Add python.exe to PATH"** during install).
2. Double-click **`Start MMacro HUD.bat`**.
   - On the first run, it automatically installs required packages from `requirements.txt` into a local `deps` folder.
   - New users start with clean settings and an interactive tutorial inside the app.

## Manual Run

```
pip install -r requirements.txt
python app.py
```

Settings and `logs.txt` are stored in `%LOCALAPPDATA%\MMacroHUD`.

## Files

- `app.py`, `ui/` - WebView HUD window, backend API, and run loop
- `game.py`, `points.py`, `gui_points.json` - Roblox window handling, clicks, keys, and UI coordinates
- `fishing.py`, `eden.py`, `merchant.py`, `merchant_cache.py`, `equip.py`, `clipper.py`, `potions.py` - automation modules

## License

GPL-3.0
