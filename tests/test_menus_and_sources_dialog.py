from dataclasses import replace
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace

import pytest

from chartorganizer.app import ChartOrganizerApp
from chartorganizer.config import project_paths
from chartorganizer.models import Playlist, PlaylistEntry, Song


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def button(dialog, text):
    return next(w for w in widgets(dialog) if w.winfo_class() == "TButton" and w.cget("text") == text)


def dialog_for(app):
    return next(w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel))


@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    source = tmp_path / "one" / "Repertoire"
    (source / "Same Song").mkdir(parents=True)
    paths = project_paths(tmp_path, source)
    settings = tmp_path / "settings.json"
    settings.touch()
    monkeypatch.setattr("chartorganizer.app.project_paths", lambda _root: paths)
    monkeypatch.setattr("chartorganizer.app.user_settings_path", lambda: settings)
    monkeypatch.setattr("chartorganizer.app.save_user_settings", lambda _paths: None)
    instance = ChartOrganizerApp(root, tmp_path)
    instance.first_run = False
    try:
        yield instance
    finally:
        root.destroy()


def test_source_menu_opens_populated_dialog_with_visible_controls(app, monkeypatch):
    errors = []
    monkeypatch.setattr(app.root, "report_callback_exception", lambda *error: errors.append(error))
    app.root.deiconify()
    app.root.update()
    bar = app.root.nametowidget(app.root.cget("menu"))
    library = app.root.nametowidget(bar.entrycget(3, "menu"))
    library.invoke(0)
    app.root.update()

    assert not errors
    dialog = dialog_for(app)
    listing = next(w for w in widgets(dialog) if isinstance(w, tk.Listbox))
    assert listing.get(0, tk.END) == tuple(str(folder) for folder in app.paths.sources)
    assert listing.winfo_ismapped()
    for label in ("Add Folder…", "Remove", "Save", "Cancel"):
        assert button(dialog, label).winfo_ismapped()
    assert dialog.winfo_width() >= 440
    button(dialog, "Cancel").invoke()


def test_setup_saves_browsed_paths_and_migrates_playlist_data(app, tmp_path, monkeypatch):
    source_song = app.repository.upsert_song(Song(None, "Song", "Song", [], "Song", source_root=str(app.paths.source)))
    instrument = app.repository.instrument("Trombone")
    app.repository.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(source_song.id)]))
    saved_settings = []
    monkeypatch.setattr("chartorganizer.app.save_user_settings", lambda paths: saved_settings.append(paths))
    monkeypatch.setattr(app, "refresh", lambda: None)
    app.setup_paths()
    dialog = dialog_for(app)
    entries = [w for w in widgets(dialog) if w.winfo_class() == "TEntry"]
    assert len(entries) == 3
    chosen_source = tmp_path / "music-two"
    chosen_source.mkdir()
    chosen_library = tmp_path / "library-two"
    chosen_output = tmp_path / "pdf-output"
    entries[0].delete(0, tk.END)
    entries[0].insert(0, f"{app.paths.source}; {chosen_source}")
    entries[1].delete(0, tk.END)
    entries[1].insert(0, str(chosen_library))
    entries[2].delete(0, tk.END)
    entries[2].insert(0, str(chosen_output))

    button(dialog, "Save").invoke()

    assert app.paths.sources == (app.paths.source, chosen_source)
    assert app.paths.library == chosen_library
    assert app.paths.compiled == chosen_output
    assert app.repository.load_playlist("Set").entries[0].song_id == source_song.id
    assert saved_settings and saved_settings[0] == app.paths


def test_same_named_nested_songs_show_distinct_relative_paths(app):
    songs = [app.repository.upsert_song(Song(None, "Shared Song", "Shared Song", [],
                                           str(Path(parent) / "Shared Song"), source_root=str(app.paths.source)))
             for parent in ("Halloween", "Winter")]
    app._update_song_labels()
    labels = [app._song_label(song) for song in songs]
    assert labels[0] != labels[1]
    assert "Halloween" in labels[0] and "Winter" in labels[1]


def test_new_playlist_prompts_for_name_and_shows_unsaved_state(app, monkeypatch):
    prompts = []
    monkeypatch.setattr("chartorganizer.app.simpledialog.askstring",
                        lambda *args, **kwargs: prompts.append((args, kwargs)) or "  Rehearsal  ")

    app.new_playlist()

    assert prompts and prompts[0][0][:2] == ("New playlist", "Playlist name:")
    assert app.playlist.name == "Rehearsal"
    assert app.playlist.id is None
    assert app.playlist.entries == []
    assert app.name_var.get() == "Rehearsal"
    assert "add songs, then Save" in app.status_var.get()


def test_canceling_new_playlist_keeps_current_playlist(app, monkeypatch):
    current = app.playlist
    monkeypatch.setattr("chartorganizer.app.simpledialog.askstring", lambda *args, **kwargs: None)

    app.new_playlist()

    assert app.playlist is current


def test_menus_dispatch_and_shortcuts_stay_in_main_window(app, monkeypatch):
    calls = []
    commands = ["new_playlist", "open_playlist", "save_playlist", "save_as", "compile",
                "open_output_folder", "add_selected", "remove_selected", "move_selected",
                "edit_parts", "choose_source", "edit_library", "refresh"]
    for name in commands:
        monkeypatch.setattr(app, name, lambda *args, name=name: calls.append((name, args)))
    app._build_menus()
    bar = app.root.nametowidget(app.root.cget("menu"))
    assert [bar.entrycget(i, "label") for i in range(1, 4)] == ["File", "Playlist", "Library"]
    menus = [app.root.nametowidget(bar.entrycget(i, "menu")) for i in range(1, 4)]
    expected = [
        [(0, "new_playlist"), (1, "open_playlist"), (2, "save_playlist"), (3, "save_as"),
         (5, "compile"), (6, "open_output_folder")],
        [(0, "add_selected"), (1, "remove_selected"), (2, "move_selected"),
         (3, "move_selected"), (4, "edit_parts")],
        [(0, "choose_source"), (1, "edit_library"), (3, "refresh")],
    ]
    for menu, entries in zip(menus, expected):
        for index, name in entries:
            menu.invoke(index)
            assert calls[-1][0] == name

    bindings = {}
    monkeypatch.setattr(app.root, "bind", lambda sequence, callback: bindings.setdefault(sequence, callback))
    app._build_menus()
    expected_shortcuts = {
        "<Control-n>": "new_playlist", "<Control-o>": "open_playlist",
        "<Control-s>": "save_playlist", "<Control-Shift-S>": "save_as",
        "<Control-Return>": "compile", "<F5>": "refresh",
    }
    other = tk.Toplevel(app.root)
    for sequence, name in expected_shortcuts.items():
        assert bindings[sequence](SimpleNamespace(widget=app.playlist_list)) == "break"
        assert calls[-1][0] == name
        count = len(calls)
        assert bindings[sequence](SimpleNamespace(widget=other)) is None
        assert len(calls) == count
    other.destroy()


def test_ctrl_enter_in_song_entry_only_compiles(app, monkeypatch):
    calls = []
    bindings = {}
    monkeypatch.setattr(app, "add_text", lambda: calls.append("add"))
    monkeypatch.setattr(app, "compile", lambda: calls.append("compile"))
    monkeypatch.setattr(app.root, "bind", lambda sequence, callback: bindings.setdefault(sequence, callback))
    app._build_menus()
    entry = next(w for w in widgets(app.root) if w.winfo_class() == "TEntry"
                 and str(w.cget("textvariable")) == str(app.input_var))
    assert bindings["<Control-Return>"](SimpleNamespace(widget=entry)) == "break"
    assert calls == ["compile"]


def test_source_dialog_cancel_save_duplicate_and_empty(app, tmp_path, monkeypatch):
    other = tmp_path / "two" / "Repertoire"
    (other / "Same Song").mkdir(parents=True)
    monkeypatch.setattr("chartorganizer.app.filedialog.askdirectory", lambda **kwargs: str(other))
    warnings = []
    monkeypatch.setattr("chartorganizer.app.messagebox.showwarning", lambda *args, **kwargs: warnings.append(args))
    original = app.paths.sources
    app.choose_source()
    dialog = dialog_for(app)
    button(dialog, "Add Folder…").invoke()
    button(dialog, "Cancel").invoke()
    assert app.paths.sources == original == app.repository.source_paths()

    app.choose_source()
    dialog = dialog_for(app)
    listing = next(w for w in widgets(dialog) if isinstance(w, tk.Listbox))
    button(dialog, "Add Folder…").invoke()
    button(dialog, "Add Folder…").invoke()
    assert listing.size() == 2 and len(warnings) == 1
    button(dialog, "Save").invoke()
    assert len(app.paths.sources) == 2 and len(app.songs) == 2
    assert app.repository.source_paths() == app.paths.sources
    labels = app.song_list.get(0, tk.END)
    assert len(set(labels)) == 2
    assert all(str(root) in label for root, label in zip(app.paths.sources, labels))

    app.choose_source()
    dialog = dialog_for(app)
    listing = next(w for w in widgets(dialog) if isinstance(w, tk.Listbox))
    for _ in range(2):
        listing.selection_set(0)
        button(dialog, "Remove").invoke()
    button(dialog, "Save").invoke()
    assert dialog.winfo_exists() and len(warnings) == 2
    assert len(app.paths.sources) == 2
    button(dialog, "Cancel").invoke()


def test_duplicate_library_settings_edit_correct_song_and_minimum_layout(app, tmp_path):
    other = tmp_path / "two"
    (other / "Same Song").mkdir(parents=True)
    app.repository.save_source_paths([*app.paths.sources, other])
    app.paths = replace(app.paths, sources=app.repository.source_paths())
    app.refresh()
    app.song_list.selection_set(1)
    app.add_selected()
    assert app.playlist.entries[0].song_id == app.songs[1].id
    assert "[" in app.playlist_list.get(0)
    app.edit_library()
    dialog = dialog_for(app)
    combos = [w for w in widgets(dialog) if w.winfo_class() == "TCombobox"]
    combos[0].current(1)
    combos[0].event_generate("<<ComboboxSelected>>")
    aliases = next(w for w in widgets(dialog) if w.winfo_class() == "TEntry")
    aliases.delete(0, tk.END)
    aliases.insert(0, "Second only")
    button(dialog, "Save").invoke()
    assert app.repository.song(app.songs[1].id).aliases == ["Second only"]
    assert app.repository.song(app.songs[0].id).aliases == []

    app.root.geometry("760x480")
    app.root.deiconify()
    app.root.update()
    assert app.root.winfo_width() == 760
    for widget in widgets(app.root):
        if widget.winfo_class() == "TButton":
            assert widget.winfo_ismapped()
            assert widget.winfo_width() >= widget.winfo_reqwidth()
            assert widget.winfo_rootx() + widget.winfo_width() <= app.root.winfo_rootx() + 760
    assert app.playlist_list.winfo_height() > 150
    assert app.song_list.winfo_height() > 150
