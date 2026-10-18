from pathlib import Path
from types import SimpleNamespace
import tkinter as tk

import pytest
from pypdf import PdfReader, PdfWriter

from chartorganizer.app import ChartOrganizerApp
from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
from chartorganizer.repository import Repository


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def button(dialog, text):
    return next(widget for widget in widgets(dialog) if widget.winfo_class() == "TButton" and widget.cget("text") == text)


@pytest.fixture
def parts_app(tmp_path: Path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    real_toplevel = tk.Toplevel

    def hidden_dialog(*args, **kwargs):
        dialog = real_toplevel(*args, **kwargs)
        dialog.withdraw()
        return dialog

    monkeypatch.setattr("chartorganizer.app.tk.Toplevel", hidden_dialog)
    app = ChartOrganizerApp.__new__(ChartOrganizerApp)
    app.root = root
    app.paths = SimpleNamespace(source=tmp_path / "source", overrides=tmp_path / "overrides")
    (app.paths.source / "Alpha").mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=792)
    writer.write(app.paths.source / "Alpha" / "trombone.pdf")
    marked = tmp_path / "marked.pdf"
    writer.write(marked)
    monkeypatch.setattr("chartorganizer.app.filedialog.askopenfilename", lambda **kwargs: str(marked))
    monkeypatch.setattr("chartorganizer.app.filedialog.askopenfilenames", lambda **kwargs: (str(marked),))

    app.repository = Repository(tmp_path / "library.sqlite3")
    song = app.repository.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = app.repository.instrument("Trombone")
    app.playlist = Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id)])
    app.instrument_var = tk.StringVar(root, value=instrument.name)
    app.status_var = tk.StringVar(root)
    app.playlist_list = tk.Listbox(root)
    app.playlist_list.insert(tk.END, song.display_name)
    app.playlist_list.selection_set(0)
    try:
        yield app, song, instrument
    finally:
        root.destroy()


@pytest.mark.parametrize("kind", ["part", "song"])
def test_import_appears_immediately_and_stays_available_after_deselection(parts_app, kind):
    app, song, instrument = parts_app
    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    listbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "Listbox")
    import_text = "Import selected part override…" if kind == "part" else "Import song/instrument override…"
    button(dialog, import_text).invoke()
    assert listbox.size() == 2
    assert listbox.curselection() == (0, 1)
    assert "override:" in listbox.get(1)
    button(dialog, "Save").invoke()
    selections = app.repository.selections(song.id, instrument.id)
    assert selections[0].override_path is None
    assert selections[1].override_path is not None

    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    listbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "Listbox")
    listbox.selection_clear(1)
    button(dialog, "Save").invoke()
    assert len(app.repository.selections(song.id, instrument.id)) == 1

    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    listbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "Listbox")
    assert listbox.size() == 2
    assert listbox.curselection() == (0,)


def test_override_order_and_ranges_survive_saving_and_reopening(parts_app):
    app, song, instrument = parts_app
    original = PartSelection(None, song.id, instrument.id, str(Path("Alpha") / "trombone.pdf"))
    app.repository.save_selections(song.id, instrument.id, [original])
    app.repository.add_override_part(song.id, instrument.id, "marked.pdf", "Part override: marked.pdf")
    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    listbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "Listbox")
    listbox.selection_clear(0, tk.END)
    listbox.selection_set(1)
    # Withdrawn windows do not receive generated selection events.
    selection_callback = listbox.bind("<<ListboxSelect>>").split("[", 1)[1].split()[0]
    listbox.tk.call(selection_callback)
    entry = next(widget for widget in widgets(dialog) if widget.winfo_class() == "TEntry")
    assert str(entry.cget("state")) == "normal"
    entry.insert(0, "1")
    button(dialog, "Move up").invoke()
    button(dialog, "Save").invoke()
    assert app.repository.selections(song.id, instrument.id)[0].page_ranges == "1"

    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    listbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "Listbox")
    assert "override:" in listbox.get(0)
    assert listbox.curselection() == (0,)
    listbox.selection_set(1)
    button(dialog, "Save").invoke()
    assert [s.override_path for s in app.repository.selections(song.id, instrument.id)] == ["marked.pdf", None]


def test_override_manager_replaces_and_deletes_imported_file(parts_app, tmp_path, monkeypatch):
    app, song, instrument = parts_app
    replacement = tmp_path / "replacement.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=500, height=792)
    writer.add_blank_page(width=500, height=792)
    writer.write(replacement)
    imported = app.paths.overrides / "override.pdf"
    imported.parent.mkdir(parents=True, exist_ok=True)
    writer.write(imported)
    app.repository.add_override_part(song.id, instrument.id, imported.name, "Part override: old.pdf")
    monkeypatch.setattr("chartorganizer.app.filedialog.askopenfilename", lambda **kwargs: str(replacement))
    monkeypatch.setattr("chartorganizer.app.messagebox.askyesno", lambda *args, **kwargs: True)

    app.edit_parts()
    parts_dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    button(parts_dialog, "Manage overrides…").invoke()
    manager = next(child for child in parts_dialog.winfo_children() if child.winfo_class() == "Toplevel")
    override_list = next(widget for widget in widgets(manager) if widget.winfo_class() == "Listbox")
    assert override_list.get(0) == "Part override: old.pdf"
    override_list.selection_set(0)

    button(manager, "Replace file…").invoke()
    assert override_list.get(0) == "Part override: replacement.pdf"
    assert len(PdfReader(str(imported)).pages) == 2
    selected = app.repository.selections(song.id, instrument.id)
    assert selected[-1].override_path == imported.name

    button(manager, "Delete override…").invoke()
    assert app.repository.override_parts(song.id, instrument.id) == []
    assert all(selection.override_path is None for selection in app.repository.selections(song.id, instrument.id))
    assert not imported.exists()


def test_kindle_option_defaults_on_and_is_saved_with_playlist(parts_app):
    app, song, instrument = parts_app
    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    checkbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "TCheckbutton")
    assert checkbox.instate(["selected"])
    checkbox.invoke()
    button(dialog, "Save").invoke()
    assert app.playlist.entries[0].optimize_for_kindle is False
    assert app.playlist.dirty
    saved = app.repository.save_playlist(app.playlist)
    app.playlist = app.repository.load_playlist(saved.name)
    app.edit_parts()
    dialog = next(child for child in app.root.winfo_children() if child.winfo_class() == "Toplevel")
    checkbox = next(widget for widget in widgets(dialog) if widget.winfo_class() == "TCheckbutton")
    assert not checkbox.instate(["selected"])
    checkbox.invoke()
    dialog.destroy()  # Closing without Save leaves the playlist choice unchanged.
    assert app.playlist.entries[0].optimize_for_kindle is False
