# ChartOrganizer

ChartOrganizer is a Windows desktop app for building a single ordered PDF from sheet-music parts in the shared `Active Repertoire` folder. The Drive folder is read-only. Local settings and outputs are under the project-root `Library/` folder (for this checkout: `C:\Users\Joe\Projects\ChartOrganizer\Library`). The packaged app keeps this folder outside `dist`, so rebuilding the app preserves playlists and other library data.

## Run from source

```powershell
python -m pip install -r requirements.txt
python -m chartorganizer.app
```

The app scans the default source path on launch. Use the Refresh button after the Drive folder changes. Enter a playlist name, choose an instrument, add songs with the searchable list or a comma-separated list, save, and compile.

The compiler includes all saved parts for each song in playlist order and writes one PDF to `Library/Compiled`. A marked-up local replacement can be stored under `Library/Overrides` and associated with a saved part through the library service/API. The catalog and playlists remain available when the Drive folder is unavailable.

## Build a clickable Windows app

Run `build_windows.ps1` on the target Windows machine. The output is `dist/ChartOrganizer/ChartOrganizer.exe`.
