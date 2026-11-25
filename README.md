# ChartOrganizer

ChartOrganizer is a Windows desktop app for building an ordered PDF from sheet-music parts in one or more repertoire folders. Source folders are read-only. On first launch, use **Library → Setup…** to choose music source folders, the library folder, and the compiled PDF folder. The library folder contains the database and imported parts; keep it together when backing up or moving the app to another computer. Settings are stored in the current Windows user profile.

## Install the ready-to-run Windows release

1. Download and extract `ChartOrganizer-<version>-windows-x64.zip` to a folder you can write to.
2. Launch `ChartOrganizer.exe` from the extracted folder.
3. On first launch, choose your sheet-music folders, library location, and compiled PDF destination in Setup. You can reopen Setup later from the Library menu.
4. Create a playlist, add songs, choose an instrument, set its parts, and save. The playlist keeps one song order; each playlist and instrument pair keeps its own part selections and Kindle layout choices. Choose another instrument to set up and compile its PDF from the same playlist.

Keep the library folder when upgrading. Extract a newer release to its own folder, then open it and select the existing library folder in Setup. The app copies the library before switching to it and retains the original as a recovery copy.

## Run from source

```powershell
python -m pip install -r requirements.txt
python -m chartorganizer.app
```

The app scans configured source folders on launch. Use **Library → Setup…** to change source, library, or output folders, or **Library → Source Folders…** to edit source folders. Sources can contain song folders, nested collections (such as holiday categories), and standalone PDFs. Collections are expanded into individual songs; instrument parts, PDF/audio subfolders, and song versions stay grouped with their song. Existing song groups keep their identities and saved selections. Same-name songs stay separate and display their source or relative path beside the name. A typed name matching several songs is ambiguous; select the intended song from Available songs instead.

Use **File** for New Playlist, Open Playlist, Save, Save As, Compile PDF, Open Output Folder, and Exit. Choose an instrument and add songs with the searchable list or a comma-separated list. **Playlist** contains song selection, removal, ordering, and Parts commands; the list buttons remain available. **Library** contains source folders, aliases/instrument filters, and Refresh.

Keyboard shortcuts: **Ctrl+N** New, **Ctrl+O** Open, **Ctrl+S** Save, **Ctrl+Shift+S** Save As, **Ctrl+Enter** Compile, and **F5** Refresh. Use Refresh after source files change.

Existing single-source settings and library records migrate automatically while preserving playlists, aliases, selected parts, and overrides. Unavailable sources retain their cached catalog and appear in the status area. Removing a source hides its songs from Available songs without deleting saved data or playlist entries; re-adding the same path restores its song identities. Compilation resolves each song from its own source and reports missing files without substituting another source's parts.

Source paths retain their original capitalization, including Google Drive shortcut IDs. Previously lowercased paths are repaired automatically when the original source setting provides an accessible reference path.

The compiler includes all saved parts for each song in playlist order and writes one PDF to `Library/Compiled`. In the Parts dialog, import a song/instrument override (one or more PDFs combined) or a selected part override. Imports are stored under `Library/Overrides` and added as separate choices alongside the originals. Select originals, overrides, or both, use Move up/Move down to set their order, then Save. Use Manage overrides to replace an imported PDF or delete an override. Deselected imports remain available in the part list. The catalog and playlists remain available when the Drive folder is unavailable.

Each song's **Parts…** dialog has an **Optimize for Kindle Paperwhite** checkbox, enabled by default (including existing playlists). When enabled, compilation crops outer whitespace from each selected page, leaves a small protective margin, and proportionally scales and centers the chart on a landscape page sized for 1680 × 1264 pixels at 300 dpi (403.2 × 303.36 PDF points). Vector notation stays sharp; scanned charts retain their original image quality. Portrait charts remain upright and fit within the landscape screen. Turn the option off to keep that song's original PDF page dimensions. Save the playlist to retain the choice for each song entry; Save As and playlist duplication preserve it too.

## Build a clickable Windows app

Run `build_windows.ps1` on the target Windows machine. The output is `dist/ChartOrganizer/ChartOrganizer.exe`.
