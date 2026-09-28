from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from dataclasses import replace
from tkinter import filedialog, messagebox, simpledialog, ttk

from .compiler import Compiler
from .config import project_paths
from .models import PartSelection, Playlist
from .overrides import OverrideService
from .playlist import PlaylistService
from .repository import Repository
from .scanner import candidates, scan_repertoire
from .selections import SelectionService


class ChartOrganizerApp:
    def __init__(self, root: tk.Tk, project_root: Path | None = None):
        self.root = root
        self.paths = project_paths(project_root)
        self.paths.ensure()
        self.repository = Repository(self.paths.database)
        saved_source = self.repository.setting("source_path")
        if saved_source:
            self.paths = replace(self.paths, source=Path(saved_source))
        self.songs = scan_repertoire(self.paths.source, self.repository)
        self.service = PlaylistService(self.songs)
        self.playlist = Playlist(None, "", self.repository.instrument("Trombone").id, [])
        self._build_ui()
        self._refresh_song_lists()

    def _build_ui(self):
        self.root.title("ChartOrganizer")
        self.root.geometry("980x620")
        self.root.minsize(760, 480)
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Playlist:").pack(side="left")
        self.name_var = tk.StringVar()
        self.playlist_box = ttk.Combobox(toolbar, textvariable=self.name_var, values=self.repository.playlists(), state="readonly", width=26)
        self.playlist_box.pack(side="left", padx=(4, 14))
        self.playlist_box.bind("<<ComboboxSelected>>", self._select_playlist)
        ttk.Label(toolbar, text="Instrument:").pack(side="left")
        self.instrument_var = tk.StringVar(value="Trombone")
        ttk.Combobox(toolbar, textvariable=self.instrument_var, values=[i.name for i in self.repository.instruments()], state="readonly", width=20).pack(side="left", padx=4)
        for text, command in (("New", self.new_playlist), ("Open", self.open_playlist), ("Save", self.save_playlist), ("Save As", self.save_as), ("Compile", self.compile)):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Source…", command=self.choose_source).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Library…", command=self.edit_library).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Output folder", command=self.open_output_folder).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")

        input_frame = ttk.Frame(self.root, padding=(8, 0))
        input_frame.pack(fill="x")
        ttk.Label(input_frame, text="Add songs (comma separated):").pack(side="left")
        self.input_var = tk.StringVar()
        entry = ttk.Entry(input_frame, textvariable=self.input_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _event: self.add_text())
        ttk.Button(input_frame, text="Add", command=self.add_text).pack(side="left")

        body = ttk.Frame(self.root, padding=8)
        body.pack(fill="both", expand=True)
        left = ttk.LabelFrame(body, text="Playlist order", padding=6)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.LabelFrame(body, text="Available songs", padding=6)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        self.playlist_list = tk.Listbox(left, selectmode="extended", exportselection=False)
        self.playlist_list.pack(side="left", fill="both", expand=True)
        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.playlist_list.yview)
        left_scroll.pack(side="right", fill="y")
        self.playlist_list.configure(yscrollcommand=left_scroll.set)
        left_controls = ttk.Frame(left)
        left_controls.pack(fill="x", pady=(6, 0))
        for text, command in (("Remove", self.remove_selected), ("Up", lambda: self.move_selected(-1)), ("Down", lambda: self.move_selected(1)), ("Parts…", self.edit_parts)):
            ttk.Button(left_controls, text=text, command=command).pack(side="left", padx=2)

        self.search_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.search_var).pack(fill="x", pady=(0, 6))
        self.search_var.trace_add("write", lambda *_: self._refresh_song_lists())
        self.song_list = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.song_list.pack(fill="both", expand=True)
        ttk.Button(right, text="Add selected", command=self.add_selected).pack(pady=(6, 0))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _refresh_song_lists(self):
        query = self.search_var.get().casefold() if hasattr(self, "search_var") else ""
        if hasattr(self, "song_list"):
            self.song_list.delete(0, tk.END)
            for song in self.songs:
                if not query or query in song.display_name.casefold() or any(query in a.casefold() for a in song.aliases):
                    self.song_list.insert(tk.END, song.display_name)
        if hasattr(self, "playlist_list"):
            self.playlist_list.delete(0, tk.END)
            for entry in self.playlist.entries:
                song = self.repository.song(entry.song_id)
                self.playlist_list.insert(tk.END, song.display_name if song else f"Missing song {entry.song_id}")

    def refresh(self):
        self.songs = scan_repertoire(self.paths.source, self.repository)
        self.service = PlaylistService(self.songs)
        self._refresh_song_lists()
        self.status_var.set(f"Found {len(self.songs)} songs")

    def choose_source(self):
        selected = filedialog.askdirectory(parent=self.root, title="Repertoire source", initialdir=str(self.paths.source) if self.paths.source.exists() else None)
        if selected:
            self.paths = replace(self.paths, source=Path(selected))
            self.repository.set_setting("source_path", str(self.paths.source))
            self.refresh()

    def edit_library(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Library settings")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Song:").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        song_var = tk.StringVar(value=self.songs[0].display_name if self.songs else "")
        song_box = ttk.Combobox(dialog, textvariable=song_var, values=[s.display_name for s in self.songs], state="readonly", width=36)
        song_box.grid(row=0, column=1, padx=10, pady=8)
        ttk.Label(dialog, text="Aliases (comma separated):").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        aliases_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=aliases_var, width=42).grid(row=1, column=1, padx=10, pady=8)
        ttk.Label(dialog, text="Instrument filters:").grid(row=2, column=0, sticky="w", padx=10, pady=8)
        filter_var = tk.StringVar()
        instrument_box = ttk.Combobox(dialog, values=[i.name for i in self.repository.instruments()], state="readonly", width=36)
        instrument_box.set(self.instrument_var.get())
        instrument_box.grid(row=2, column=1, padx=10, pady=8)
        ttk.Entry(dialog, textvariable=filter_var, width=42).grid(row=3, column=1, padx=10, pady=8)
        def load_fields(*_):
            song = next((s for s in self.songs if s.display_name == song_var.get()), None)
            aliases_var.set(", ".join(song.aliases) if song else "")
            instrument = self.repository.instrument(instrument_box.get())
            filter_var.set(", ".join(instrument.filters) if instrument else "")
        def save_fields():
            song = next((s for s in self.songs if s.display_name == song_var.get()), None)
            if song:
                song.aliases = [a.strip() for a in aliases_var.get().split(",") if a.strip()]
                self.repository.upsert_song(song)
            instrument = self.repository.instrument(instrument_box.get())
            if instrument:
                instrument.filters = [f.strip() for f in filter_var.get().split(",") if f.strip()]
                self.repository.save_instrument(instrument)
            self.songs = self.repository.songs()
            self.service = PlaylistService(self.songs)
            self._refresh_song_lists()
            dialog.destroy()
        song_box.bind("<<ComboboxSelected>>", load_fields)
        instrument_box.bind("<<ComboboxSelected>>", load_fields)
        load_fields()
        actions = ttk.Frame(dialog)
        actions.grid(row=4, column=0, columnspan=2, sticky="e", padx=10, pady=10)
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(actions, text="Save", command=save_fields).pack(side="right")

    def open_output_folder(self):
        self.paths.compiled.mkdir(parents=True, exist_ok=True)
        os.startfile(self.paths.compiled)  # type: ignore[attr-defined]

    def add_text(self):
        resolved, unknown, ambiguous = self.service.resolve(self.input_var.get())
        for song in resolved:
            self.service.add(self.playlist, song)
        problems = []
        if unknown:
            problems.append("Unknown: " + ", ".join(unknown))
        if ambiguous:
            problems.append("Ambiguous: " + ", ".join(ambiguous))
        if problems:
            messagebox.showwarning("Songs needing attention", "\n".join(problems), parent=self.root)
        self.input_var.set("")
        self._refresh_song_lists()

    def add_selected(self):
        visible = [s for s in self.songs if not self.search_var.get().casefold() or self.search_var.get().casefold() in s.display_name.casefold() or any(self.search_var.get().casefold() in a.casefold() for a in s.aliases)]
        for index in self.song_list.curselection():
            self.service.add(self.playlist, visible[index])
        self._refresh_song_lists()

    def remove_selected(self):
        for index in sorted(self.playlist_list.curselection(), reverse=True):
            self.service.remove(self.playlist, index)
        self._refresh_song_lists()

    def move_selected(self, delta: int):
        indexes = list(self.playlist_list.curselection())
        if indexes:
            self.service.move(self.playlist, indexes[0], delta)
            self._refresh_song_lists()

    def edit_parts(self):
        indexes = self.playlist_list.curselection()
        if not indexes:
            messagebox.showinfo("Parts", "Select a song in the playlist first", parent=self.root)
            return
        entry = self.playlist.entries[indexes[0]]
        song = self.repository.song(entry.song_id)
        instrument = self.repository.instrument(self.instrument_var.get())
        if not song or not instrument:
            return
        available = candidates(self.paths.source, song)
        saved = self.repository.selections(song.id, instrument.id)
        by_path = {s.source_relative_path: s for s in saved}
        initial = [s.source_relative_path for s in saved]
        from .matcher import match_instrument
        automatic_match = match_instrument(available, instrument)
        if not initial:
            initial = [c.relative_path for c in automatic_match.selected]
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Parts — {song.display_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text=f"Select {instrument.name} parts in order:").pack(anchor="w", padx=10, pady=(10, 4))
        listbox = tk.Listbox(dialog, selectmode="extended", width=80, height=16, exportselection=False)
        listbox.pack(fill="both", expand=True, padx=10)
        for candidate in available:
            listbox.insert(tk.END, candidate.relative_path)
        for index, candidate in enumerate(available):
            if candidate.relative_path in initial:
                listbox.selection_set(index)
        ranges_var = tk.StringVar(value="")
        range_frame = ttk.Frame(dialog)
        range_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(range_frame, text="Page ranges for selected PDFs (optional, e.g. 3-4,7):").pack(side="left")
        range_entry = ttk.Entry(range_frame, textvariable=ranges_var, width=18)
        range_entry.pack(side="left", padx=5)
        if automatic_match.selected:
            range_entry.configure(state="disabled")
            ttk.Label(range_frame, text="(individual part PDFs found; page ranges disabled)").pack(side="left")
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        def save():
            selected_indexes = list(listbox.curselection())
            has_song_instrument_override = self.repository.song_instrument_override(song.id, instrument.id)
            if not selected_indexes and not has_song_instrument_override:
                messagebox.showerror("Parts", "Select at least one PDF", parent=dialog)
                return
            selections = []
            for order, index in enumerate(selected_indexes):
                candidate = available[index]
                old = by_path.get(candidate.relative_path)
                selections.append(PartSelection(old.id if old else None, song.id, instrument.id, candidate.relative_path, order, old.page_ranges if old else None, old.override_path if old else None, old.override_enabled if old else True))
            if ranges_var.get().strip():
                if len(selections) != 1:
                    messagebox.showerror("Page ranges", "Page ranges are for a single bundled PDF selection", parent=dialog)
                    return
                selections[0].page_ranges = ranges_var.get().strip()
            self.repository.save_selections(song.id, instrument.id, selections)
            dialog.destroy()
            self.status_var.set(f"Saved selection for {song.display_name}")
        def import_override():
            selected_indexes = list(listbox.curselection())
            if len(selected_indexes) != 1:
                messagebox.showinfo("Override", "Select exactly one part first", parent=dialog)
                return
            candidate = available[selected_indexes[0]]
            old = by_path.get(candidate.relative_path)
            if not old:
                messagebox.showinfo("Override", "Save the selection first, then import its override", parent=dialog)
                return
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            if path:
                OverrideService(self.repository, self.paths.overrides).import_pdf(old, Path(path))
                messagebox.showinfo("Override", "Override imported", parent=dialog)
        def import_song_instrument_override():
            paths = filedialog.askopenfilenames(parent=dialog, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            if paths:
                try:
                    OverrideService(self.repository, self.paths.overrides).import_song_instrument_pdfs(song.id, instrument.id, [Path(path) for path in paths])
                except Exception as exc:
                    messagebox.showerror("Override", f"Could not import song/instrument override: {exc}", parent=dialog)
                    return
                messagebox.showinfo("Override", f"Song/instrument override imported ({len(paths)} PDFs combined)", parent=dialog)
        ttk.Button(button_frame, text="Import song/instrument override…", command=import_song_instrument_override).pack(side="left")
        ttk.Button(button_frame, text="Import selected part override…", command=import_override).pack(side="left", padx=(6, 0))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(button_frame, text="Save", command=save).pack(side="right")

    def new_playlist(self):
        self.playlist = Playlist(None, "", self.repository.instrument(self.instrument_var.get()).id, [])
        self.name_var.set("")
        self._refresh_song_lists()

    def _refresh_playlist_names(self):
        names = self.repository.playlists()
        self.playlist_box.configure(values=names)

    def _load_playlist(self, name: str):
        loaded = self.repository.load_playlist(name)
        if not loaded:
            return
        self.playlist = loaded
        self.name_var.set(loaded.name)
        instrument = next((i for i in self.repository.instruments() if i.id == loaded.instrument_id), None)
        if instrument:
            self.instrument_var.set(instrument.name)
        self._refresh_song_lists()

    def _select_playlist(self, _event=None):
        self._load_playlist(self.name_var.get())

    def save_playlist(self):
        name = self.name_var.get().strip()
        if not name:
            name = simpledialog.askstring("Save playlist", "Playlist name:", parent=self.root)
            if not name or not name.strip():
                return False
            name = name.strip()
        self.playlist.name = name
        self.playlist.instrument_id = self.repository.instrument(self.instrument_var.get()).id
        try:
            self.playlist = self.repository.save_playlist(self.playlist)
            self.name_var.set(self.playlist.name)
            self._refresh_playlist_names()
            self.status_var.set(f"Saved {name}")
        except ValueError as exc:
            messagebox.showerror("Save playlist", str(exc), parent=self.root)
            return False
        return True

    def save_as(self):
        name = simpledialog.askstring("Save As", "New playlist name:", initialvalue=self.name_var.get(), parent=self.root)
        if name:
            self.playlist.id, self.playlist.name = None, name.strip()
            self.name_var.set(self.playlist.name)
            self.save_playlist()

    def open_playlist(self):
        names = self.repository.playlists()
        if not names:
            messagebox.showinfo("Open playlist", "No saved playlists", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Open playlist")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Choose a saved playlist:").pack(anchor="w", padx=12, pady=(12, 4))
        selected_name = tk.StringVar(value=self.name_var.get() if self.name_var.get() in names else names[0])
        playlist_box = ttk.Combobox(dialog, textvariable=selected_name, values=names, state="readonly", width=32)
        playlist_box.pack(fill="x", padx=12, pady=4)
        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=12, pady=12)
        def open_selected():
            self._load_playlist(selected_name.get())
            dialog.destroy()
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(actions, text="Open", command=open_selected).pack(side="right")

    def compile(self):
        if not self.playlist.entries:
            messagebox.showerror("Compile", "Add at least one song", parent=self.root)
            return
        if not self.save_playlist():
            return
        instrument = self.instrument_var.get()
        instrument_obj = self.repository.instrument(instrument)
        selection_service = SelectionService(self.repository, self.paths.source)
        for entry in self.playlist.entries:
            if not self.repository.selections(entry.song_id, instrument_obj.id):
                song = self.repository.song(entry.song_id)
                if song:
                    selection_service.auto_select(entry.song_id, instrument_obj.id, candidates(self.paths.source, song), instrument_obj)
        self.status_var.set("Compiling…")
        def work():
            try:
                result = Compiler(self.repository, self.paths.source, self.paths.overrides, self.paths.compiled).compile(self.playlist, instrument)
                self.root.after(0, lambda: self._compile_done(result.output_path))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("Compile", str(exc), parent=self.root))
                self.root.after(0, lambda: self.status_var.set("Compilation failed"))
        threading.Thread(target=work, daemon=True).start()

    def _compile_done(self, path: Path):
        self.status_var.set(f"Created {path.name}")
        if messagebox.askyesno("Compilation complete", f"Created:\n{path}\n\nOpen it now?", parent=self.root):
            os.startfile(path)  # type: ignore[attr-defined]


def main() -> None:
    root = tk.Tk()
    ChartOrganizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
