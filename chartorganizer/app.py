from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from dataclasses import replace
from tkinter import filedialog, messagebox, simpledialog, ttk

from .compiler import Compiler
from .config import migrate_library, normalize_sources, project_paths, save_user_settings, source_key, user_settings_path
from .models import PartSelection, PdfCandidate, Playlist
from .overrides import OverrideService
from .playlist import PlaylistService
from .repository import Repository
from .scanner import candidates, scan_repertoire
from .selections import SelectionService


class ChartOrganizerApp:
    def __init__(self, root: tk.Tk, project_root: Path | None = None):
        self.root = root
        self.first_run = not user_settings_path().exists()
        self.paths = project_paths(project_root)
        self.paths.ensure()
        self.repository = Repository(self.paths.database)
        self.paths = replace(self.paths, sources=self.repository.source_paths(self.paths.source))
        self.unavailable_sources = []
        self.songs = scan_repertoire(self.paths.sources, self.repository, self.unavailable_sources)
        self.service = PlaylistService(self.songs)
        self.playlist = Playlist(None, "", self.repository.instrument("Trombone").id, [])
        self.active_instrument_id = self.playlist.instrument_id
        self._build_ui()
        self._refresh_song_lists()
        self._show_scan_status()
        if self.first_run:
            self.root.after(100, self.setup_paths)

    def _build_ui(self):
        self.root.title("ChartOrganizer")
        self.root.geometry("980x620")
        self.root.minsize(760, 480)
        self._build_menus()
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Playlist:").pack(side="left")
        self.name_var = tk.StringVar()
        self.playlist_box = ttk.Combobox(toolbar, textvariable=self.name_var, values=self.repository.playlists(), state="readonly", width=26)
        self.playlist_box.pack(side="left", padx=(4, 14))
        self.playlist_box.bind("<<ComboboxSelected>>", self._select_playlist)
        ttk.Label(toolbar, text="Instrument:").pack(side="left")
        self.instrument_var = tk.StringVar(value="Trombone")
        self.instrument_box = ttk.Combobox(toolbar, textvariable=self.instrument_var, values=[i.name for i in self.repository.instruments()], state="readonly", width=20)
        self.instrument_box.pack(side="left", padx=4)
        self.instrument_box.bind("<<ComboboxSelected>>", self._select_instrument)

        input_frame = ttk.Frame(self.root, padding=(8, 0))
        input_frame.pack(fill="x")
        ttk.Label(input_frame, text="Add songs (comma separated):").pack(side="left")
        self.input_var = tk.StringVar()
        entry = ttk.Entry(input_frame, textvariable=self.input_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda event: self.add_text() if not event.state & 0x4 else None)
        ttk.Button(input_frame, text="Add", command=self.add_text).pack(side="left")

        body = ttk.Frame(self.root, padding=8)
        body.pack(fill="both", expand=True)
        left = ttk.LabelFrame(body, text="Playlist order", padding=6)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.LabelFrame(body, text="Available songs", padding=6)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        playlist_content = ttk.Frame(left)
        playlist_content.pack(fill="both", expand=True)
        self.playlist_list = tk.Listbox(playlist_content, selectmode="extended", exportselection=False)
        self.playlist_list.pack(side="left", fill="both", expand=True)
        left_scroll = ttk.Scrollbar(playlist_content, orient="vertical", command=self.playlist_list.yview)
        left_scroll.pack(side="right", fill="y")
        self.playlist_list.configure(yscrollcommand=left_scroll.set)
        left_controls = ttk.Frame(left)
        left_controls.pack(fill="x", pady=(6, 0))
        for text, command in (("Remove", self.remove_selected), ("Up", lambda: self.move_selected(-1)), ("Down", lambda: self.move_selected(1)), ("Parts…", self.edit_parts)):
            ttk.Button(left_controls, text=text, command=command).pack(side="left", padx=2)

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(right, textvariable=self.search_var)
        self.search_entry.pack(fill="x", pady=(0, 6))
        self.search_var.trace_add("write", lambda *_: self._refresh_song_lists())
        self.song_list = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.song_list.pack(fill="both", expand=True)
        ttk.Button(right, text="Add selected", command=self.add_selected).pack(pady=(6, 0))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_menus(self):
        bar = tk.Menu(self.root)
        self.root.configure(menu=bar)
        file_menu = tk.Menu(bar, tearoff=False)
        playlist_menu = tk.Menu(bar, tearoff=False)
        library_menu = tk.Menu(bar, tearoff=False)
        for label, menu in (("File", file_menu), ("Playlist", playlist_menu), ("Library", library_menu)):
            bar.add_cascade(label=label, menu=menu, underline=0)
        commands = (
            ("New Playlist", self.new_playlist, "Ctrl+N", "<Control-n>"),
            ("Open Playlist…", self.open_playlist, "Ctrl+O", "<Control-o>"),
            ("Save", self.save_playlist, "Ctrl+S", "<Control-s>"),
            ("Save As…", self.save_as, "Ctrl+Shift+S", "<Control-Shift-S>"),
        )
        for label, command, accelerator, sequence in commands:
            file_menu.add_command(label=label, command=command, accelerator=accelerator, underline=5 if label == "Save As…" else 0)
            self._bind_shortcut(sequence, command)
        file_menu.add_separator()
        file_menu.add_command(label="Compile PDF", command=self.compile, accelerator="Ctrl+Enter", underline=0)
        self._bind_shortcut("<Control-Return>", self.compile)
        file_menu.add_command(label="Open Output Folder", command=self.open_output_folder, underline=12)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy, underline=1)
        for label, command in (("Add Selected Songs", self.add_selected),
                               ("Remove Selected Songs", self.remove_selected),
                               ("Move Up", lambda: self.move_selected(-1)),
                               ("Move Down", lambda: self.move_selected(1)),
                               ("Parts…", self.edit_parts)):
            playlist_menu.add_command(label=label, command=command, underline=5 if label.startswith("Move ") else 0)
        library_menu.add_command(label="Source Folders…", command=self.choose_source, underline=0)
        library_menu.add_command(label="Library Settings…", command=self.edit_library, underline=0)
        library_menu.add_separator()
        library_menu.add_command(label="Refresh", command=self.refresh, accelerator="F5", underline=0)
        library_menu.add_command(label="Setup…", command=self.setup_paths)
        self._bind_shortcut("<F5>", self.refresh)

    def _bind_shortcut(self, sequence, command):
        def invoke(event):
            if event.widget.winfo_toplevel() == self.root:
                command()
                return "break"
        self.root.bind(sequence, invoke)

    def _update_song_labels(self):
        groups = {}
        for song in self.repository.songs():
            groups.setdefault(song.display_name.casefold(), []).append(song)
        self._song_labels = {}
        for duplicates in groups.values():
            for song in duplicates:
                label = song.display_name
                if len(duplicates) > 1:
                    source = Path(song.source_root).name if song.source_root else "Unassigned"
                    if sum(Path(s.source_root).name.casefold() == source.casefold() for s in duplicates) > 1:
                        source = song.source_root or "Unassigned"
                    if any(s.id != song.id and source_key(s.source_root) == source_key(song.source_root) for s in duplicates):
                        source += f" / {song.relative_folder}"
                    label += f" [{source}]"
                self._song_labels[song.id] = label

    def _song_label(self, song):
        return self._song_labels.get(song.id, song.display_name)

    def _refresh_song_lists(self):
        self._update_song_labels()
        query = self.search_var.get().casefold() if hasattr(self, "search_var") else ""
        if hasattr(self, "song_list"):
            self.song_list.delete(0, tk.END)
            for song in self.songs:
                if not query or query in song.display_name.casefold() or any(query in a.casefold() for a in song.aliases):
                    self.song_list.insert(tk.END, self._song_label(song))
        if hasattr(self, "playlist_list"):
            self.playlist_list.delete(0, tk.END)
            for entry in self.playlist.entries:
                song = self.repository.song(entry.song_id)
                self.playlist_list.insert(tk.END, self._song_label(song) if song else f"Missing song {entry.song_id}")

    def _show_scan_status(self):
        count = len(self.paths.sources)
        status = f"Found {len(self.songs)} songs in {count} source folder{'s' if count != 1 else ''}"
        if self.unavailable_sources:
            status += "; unavailable: " + ", ".join(str(p) for p in self.unavailable_sources)
        self.status_var.set(status)

    def refresh(self):
        self.unavailable_sources = []
        self.songs = scan_repertoire(self.paths.sources, self.repository, self.unavailable_sources)
        self.service = PlaylistService(self.songs)
        self._refresh_song_lists()
        self._show_scan_status()

    def choose_source(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Source Folders")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("680x280")
        dialog.minsize(440, 220)
        folders = list(self.paths.sources)
        ttk.Label(dialog, text="Sources can contain song folders, nested collections, and standalone PDFs. Removing a source keeps saved playlists and settings.",
                  wraplength=400).pack(anchor="w", padx=12, pady=(12, 6))
        listing = tk.Listbox(dialog, selectmode="extended", exportselection=False)
        listing.pack(fill="both", expand=True, padx=12)
        scrollbar = ttk.Scrollbar(dialog, orient="horizontal", command=listing.xview)
        scrollbar.pack(fill="x", padx=12)
        listing.configure(xscrollcommand=scrollbar.set)

        def redraw():
            listing.delete(0, tk.END)
            for folder in folders:
                listing.insert(tk.END, str(folder))

        def add():
            selected = filedialog.askdirectory(parent=dialog, title="Add source folder")
            if selected:
                try:
                    updated = normalize_sources([*folders, selected])
                except ValueError as exc:
                    messagebox.showwarning("Source Folders", str(exc), parent=dialog)
                    return
                folders[:] = updated
                redraw()

        def remove():
            for index in reversed(listing.curselection()):
                folders.pop(index)
            redraw()

        def save():
            try:
                sources = self.repository.save_source_paths(folders)
            except ValueError as exc:
                messagebox.showwarning("Source Folders", str(exc), parent=dialog)
                return
            self.paths = replace(self.paths, sources=sources)
            save_user_settings(self.paths)
            self.refresh()
            dialog.destroy()

        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=12, pady=12)
        ttk.Button(actions, text="Add Folder…", command=add).pack(side="left")
        ttk.Button(actions, text="Remove", command=remove).pack(side="left", padx=6)
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(actions, text="Save", command=save).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        redraw()

    def setup_paths(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("ChartOrganizer setup")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Choose music folders, the library folder, and compiled PDF location.").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=12)
        values = [tk.StringVar(value="; ".join(map(str, self.paths.sources))),
                  tk.StringVar(value=str(self.paths.library)), tk.StringVar(value=str(self.paths.compiled))]
        labels = ["Music source folders (separate with semicolons)", "Library and imported parts", "Compiled PDF folder"]
        for row, (label, variable) in enumerate(zip(labels, values), 1):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=6)
            ttk.Entry(dialog, textvariable=variable, width=48).grid(row=row, column=1, padx=6, pady=6)
            ttk.Button(dialog, text="Browse…", command=lambda v=variable, l=label, multi=(row == 1): self._browse_path(v, l, dialog, multi)).grid(row=row, column=2, padx=12)
        def save():
            try:
                sources = normalize_sources([p.strip() for p in values[0].get().split(";") if p.strip()])
                data_dir, output_dir = Path(values[1].get()).expanduser(), Path(values[2].get()).expanduser()
                old_library = self.paths.library
                if data_dir.resolve() != old_library.resolve():
                    if (data_dir / "library.sqlite3").exists():
                        if (old_library / "library.sqlite3").exists() and not messagebox.askyesno(
                                "Setup", "The selected folder already has a ChartOrganizer library. Use that library?", parent=dialog):
                            return
                    else:
                        migrate_library(old_library, data_dir)
                for folder in (data_dir, output_dir):
                    folder.mkdir(parents=True, exist_ok=True)
                    probe = folder / ".chartorganizer-write-check"
                    probe.touch(); probe.unlink()
                self.paths = replace(self.paths, sources=sources, data_dir=data_dir, output_dir=output_dir)
                self.paths.ensure()
                self.repository = Repository(self.paths.database)
                self.repository.save_source_paths(sources)
                save_user_settings(self.paths)
                self.refresh()
                self.first_run = False
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Setup", str(exc), parent=dialog)
        actions = ttk.Frame(dialog)
        actions.grid(row=4, column=0, columnspan=3, sticky="e", padx=12, pady=12)
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(actions, text="Save", command=save).pack(side="right")

    @staticmethod
    def _browse_path(variable, title, parent, multi=False):
        current = [p.strip() for p in variable.get().split(";") if p.strip()]
        selected = filedialog.askdirectory(parent=parent, title=title, initialdir=current[0] if current else None)
        if selected:
            if multi and selected not in current:
                current.append(selected)
                variable.set("; ".join(current))
            elif not multi:
                variable.set(selected)

    def edit_library(self):
        self._update_song_labels()
        dialog = tk.Toplevel(self.root)
        dialog.title("Library settings")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Song:").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        song_var = tk.StringVar(value=self._song_label(self.songs[0]) if self.songs else "")
        song_box = ttk.Combobox(dialog, textvariable=song_var, values=[self._song_label(s) for s in self.songs], state="readonly", width=36)
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
            song = self.songs[song_box.current()] if song_box.current() >= 0 else None
            aliases_var.set(", ".join(song.aliases) if song else "")
            instrument = self.repository.instrument(instrument_box.get())
            filter_var.set(", ".join(instrument.filters) if instrument else "")
        def save_fields():
            song = self.songs[song_box.current()] if song_box.current() >= 0 else None
            if song:
                song.aliases = [a.strip() for a in aliases_var.get().split(",") if a.strip()]
                self.repository.upsert_song(song)
            instrument = self.repository.instrument(instrument_box.get())
            if instrument:
                instrument.filters = [f.strip() for f in filter_var.get().split(",") if f.strip()]
                self.repository.save_instrument(instrument)
            self.refresh()
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
        available = candidates(getattr(self.paths, "sources", self.paths.source), song)
        if self.playlist.id is None and hasattr(self, "name_var"):
            if not self.name_var.get().strip():
                messagebox.showinfo("Parts", "Save this playlist before saving instrument parts.", parent=self.root)
                return
            if not self.save_playlist():
                return
        playlist_id = getattr(self.playlist, "id", None)
        saved = self.repository.selections(song.id, instrument.id, playlist_id)
        by_path = {s.source_relative_path: s for s in saved}
        initial = [s.source_relative_path for s in saved]
        from .matcher import match_instrument
        automatic_match = match_instrument(available, instrument)
        if not initial:
            initial = [c.relative_path for c in automatic_match.selected]
        override_by_path = {part.selection_path: part for part in self.repository.override_parts(song.id, instrument.id)}
        for part in override_by_path.values():
            available.append(PdfCandidate(self.paths.overrides / part.override_path, part.selection_path, 0, 0, part.label))
        saved_order = {path: order for order, path in enumerate(initial)}
        available.sort(key=lambda candidate: saved_order.get(candidate.relative_path, len(initial)))
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Parts — {song.display_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        kindle_var = tk.BooleanVar(dialog, value=entry.optimize_for_kindle)
        ttk.Checkbutton(dialog, text="Optimize for Kindle Paperwhite (landscape, crop whitespace)",
                        variable=kindle_var).pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Label(dialog, text=f"Select {instrument.name} parts in order:").pack(anchor="w", padx=10, pady=(10, 4))
        listbox = tk.Listbox(dialog, selectmode="extended", width=80, height=16, exportselection=False)
        listbox.pack(fill="both", expand=True, padx=10)
        for candidate in available:
            listbox.insert(tk.END, candidate.label if candidate.relative_path in override_by_path else candidate.relative_path)
        for index, candidate in enumerate(available):
            if candidate.relative_path in initial:
                listbox.selection_set(index)
        ranges_var = tk.StringVar(value="")
        range_frame = ttk.Frame(dialog)
        range_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(range_frame, text="Page ranges for one selected PDF (optional, e.g. 3-4,7):").pack(side="left")
        range_entry = ttk.Entry(range_frame, textvariable=ranges_var, width=18)
        range_entry.pack(side="left", padx=5)
        def load_ranges(_event=None):
            indexes = list(listbox.curselection())
            candidate = available[indexes[0]] if len(indexes) == 1 else None
            old = by_path.get(candidate.relative_path) if candidate else None
            ranges_var.set((old.page_ranges or "") if old else "")
            enabled = candidate is not None and (not automatic_match.selected or candidate.relative_path in override_by_path)
            range_entry.configure(state="normal" if enabled else "disabled")
        listbox.bind("<<ListboxSelect>>", load_ranges)
        load_ranges()
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        def save():
            selected_indexes = list(listbox.curselection())
            if not selected_indexes:
                messagebox.showerror("Parts", "Select at least one PDF", parent=dialog)
                return
            selections = []
            for order, index in enumerate(selected_indexes):
                candidate = available[index]
                old = by_path.get(candidate.relative_path)
                override = override_by_path.get(candidate.relative_path)
                selections.append(PartSelection(old.id if old else None, song.id, instrument.id, candidate.relative_path, order,
                                                old.page_ranges if old else None, override.override_path if override else None))
            if len(selections) == 1 and str(range_entry.cget("state")) == "normal":
                selections[0].page_ranges = ranges_var.get().strip() or None
            self.repository.save_selections(song.id, instrument.id, selections, playlist_id)
            if entry.optimize_for_kindle != kindle_var.get():
                entry.optimize_for_kindle = kindle_var.get()
                self.playlist.dirty = True
            dialog.destroy()
            self.status_var.set(f"Saved selection for {song.display_name}")
        def show_imported(override_path):
            selected_paths = {available[index].relative_path for index in listbox.curselection()}
            selected_paths.add(f"Overrides/{override_path}")
            for selection in self.repository.selections(song.id, instrument.id, playlist_id):
                if selection.override_path:
                    by_path[selection.source_relative_path] = selection
            for part in self.repository.override_parts(song.id, instrument.id):
                if part.selection_path not in override_by_path:
                    override_by_path[part.selection_path] = part
                    available.append(PdfCandidate(self.paths.overrides / part.override_path, part.selection_path, 0, 0, part.label))
                    listbox.insert(tk.END, part.label)
            listbox.selection_clear(0, tk.END)
            for index, candidate in enumerate(available):
                if candidate.relative_path in selected_paths:
                    listbox.selection_set(index)
            listbox.see(next(index for index, candidate in enumerate(available) if candidate.relative_path == f"Overrides/{override_path}"))
            load_ranges()
        def render_part_choices(selected_paths=None):
            if selected_paths is None:
                selected_paths = {available[index].relative_path for index in listbox.curselection()}
            listbox.delete(0, tk.END)
            for index, candidate in enumerate(available):
                listbox.insert(tk.END, candidate.label if candidate.relative_path in override_by_path else candidate.relative_path)
                if candidate.relative_path in selected_paths:
                    listbox.selection_set(index)
            load_ranges()
        def manage_overrides():
            manager = tk.Toplevel(dialog)
            manager.title(f"Manage overrides — {song.display_name}")
            manager.transient(dialog)
            manager.grab_set()
            ttk.Label(manager, text="Select an override to replace or delete:").pack(anchor="w", padx=10, pady=(10, 4))
            override_list = tk.Listbox(manager, selectmode="browse", width=72, height=12, exportselection=False)
            override_list.pack(fill="both", expand=True, padx=10)
            manager_parts = []
            def refresh_manager(select_path=None):
                manager_parts[:] = self.repository.override_parts(song.id, instrument.id)
                override_list.delete(0, tk.END)
                for index, part in enumerate(manager_parts):
                    override_list.insert(tk.END, part.label)
                    if part.override_path == select_path:
                        override_list.selection_set(index)
                if not manager_parts:
                    override_list.insert(tk.END, "No overrides imported")
            def selected_override():
                indexes = list(override_list.curselection())
                return manager_parts[indexes[0]] if indexes and indexes[0] < len(manager_parts) else None
            def replace_override():
                part = selected_override()
                if not part:
                    return
                if part.kind == "song":
                    paths = filedialog.askopenfilenames(parent=manager, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
                else:
                    path = filedialog.askopenfilename(parent=manager, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
                    paths = [path] if path else []
                if not paths:
                    return
                try:
                    updated = OverrideService(self.repository, self.paths.overrides).replace(
                        song.id, instrument.id, part, [Path(path) for path in paths])
                except Exception as exc:
                    messagebox.showerror("Manage overrides", f"Could not replace override: {exc}", parent=manager)
                    return
                override_by_path[updated.selection_path] = updated
                for index, candidate in enumerate(available):
                    if candidate.relative_path == updated.selection_path:
                        available[index] = PdfCandidate(candidate.path, candidate.relative_path, candidate.size,
                                                        candidate.modified_ns, updated.label)
                render_part_choices()
                refresh_manager(updated.override_path)
            def delete_override():
                part = selected_override()
                if not part:
                    return
                if not messagebox.askyesno("Delete override", f"Delete {part.label}?", parent=manager):
                    return
                try:
                    OverrideService(self.repository, self.paths.overrides).delete(song.id, instrument.id, part)
                except Exception as exc:
                    messagebox.showerror("Manage overrides", f"Could not delete override: {exc}", parent=manager)
                    refresh_manager(part.override_path)
                    return
                override_by_path.pop(part.selection_path, None)
                available[:] = [candidate for candidate in available if candidate.relative_path != part.selection_path]
                render_part_choices()
                refresh_manager()
            manager_actions = ttk.Frame(manager)
            manager_actions.pack(fill="x", padx=10, pady=10)
            ttk.Button(manager_actions, text="Replace file…", command=replace_override).pack(side="left")
            ttk.Button(manager_actions, text="Delete override…", command=delete_override).pack(side="left", padx=6)
            ttk.Button(manager_actions, text="Close", command=manager.destroy).pack(side="right")
            refresh_manager()
        def move_part(delta):
            indexes = list(listbox.curselection())
            if not indexes:
                return
            selected_paths = {available[index].relative_path for index in indexes}
            for index in indexes if delta < 0 else reversed(indexes):
                target = index + delta
                if 0 <= target < len(available) and available[target].relative_path not in selected_paths:
                    available[index], available[target] = available[target], available[index]
            listbox.delete(0, tk.END)
            for index, candidate in enumerate(available):
                listbox.insert(tk.END, candidate.label if candidate.relative_path in override_by_path else candidate.relative_path)
                if candidate.relative_path in selected_paths:
                    listbox.selection_set(index)
        def import_override():
            selected_indexes = list(listbox.curselection())
            if len(selected_indexes) != 1:
                messagebox.showinfo("Override", "Select exactly one part first", parent=dialog)
                return
            candidate = available[selected_indexes[0]]
            old = by_path.get(candidate.relative_path) or PartSelection(None, song.id, instrument.id, candidate.relative_path)
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            if path:
                try:
                    imported = OverrideService(self.repository, self.paths.overrides).import_pdf(old, Path(path))
                except Exception as exc:
                    messagebox.showerror("Override", f"Could not import part override: {exc}", parent=dialog)
                    return
                show_imported(imported.override_path)
        def import_song_instrument_override():
            paths = filedialog.askopenfilenames(parent=dialog, filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            if paths:
                try:
                    imported_path = OverrideService(self.repository, self.paths.overrides).import_song_instrument_pdfs(song.id, instrument.id, [Path(path) for path in paths])
                except Exception as exc:
                    messagebox.showerror("Override", f"Could not import song/instrument override: {exc}", parent=dialog)
                    return
                show_imported(imported_path)
        order_frame = ttk.Frame(dialog)
        order_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(order_frame, text="Move up", command=lambda: move_part(-1)).pack(side="left")
        ttk.Button(order_frame, text="Move down", command=lambda: move_part(1)).pack(side="left", padx=6)
        ttk.Button(order_frame, text="Manage overrides…", command=manage_overrides).pack(side="left", padx=(4, 0))
        ttk.Label(order_frame, text="Select originals, overrides, or both, then Save.").pack(side="left", padx=6)
        ttk.Button(button_frame, text="Import song/instrument override…", command=import_song_instrument_override).pack(side="left")
        ttk.Button(button_frame, text="Import selected part override…", command=import_override).pack(side="left", padx=(6, 0))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(button_frame, text="Save", command=save).pack(side="right")

    def new_playlist(self):
        name = simpledialog.askstring("New playlist", "Playlist name:", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        self.playlist = Playlist(None, name, self.repository.instrument(self.instrument_var.get()).id, [])
        self.name_var.set(name)
        self._refresh_song_lists()
        self.status_var.set(f"New playlist '{name}' — add songs, then Save")

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
            self.active_instrument_id = instrument.id
            self.playlist.entries = self.repository.load_entry_settings(loaded.id, instrument.id, loaded.entries)
        self._refresh_song_lists()

    def _select_playlist(self, _event=None):
        self._load_playlist(self.name_var.get())

    def _select_instrument(self, _event=None):
        instrument = self.repository.instrument(self.instrument_var.get())
        if not instrument:
            return
        if self.playlist.id is not None:
            self.repository.save_entry_settings(self.playlist.id, self.active_instrument_id, self.playlist.entries)
            self.playlist.entries = self.repository.load_entry_settings(self.playlist.id, instrument.id, self.playlist.entries)
        self.active_instrument_id = instrument.id
        self.playlist.instrument_id = instrument.id
        self._refresh_song_lists()
        self.status_var.set(f"{self.name_var.get() or 'New playlist'} · {instrument.name}")

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
            self.repository.save_entry_settings(self.playlist.id, self.playlist.instrument_id, self.playlist.entries)
            self.name_var.set(self.playlist.name)
            self._refresh_playlist_names()
            self.status_var.set(f"Saved {name}")
        except ValueError as exc:
            messagebox.showerror("Save playlist", str(exc), parent=self.root)
            return False
        return True

    def save_as(self):
        name = simpledialog.askstring("Save As", "New playlist name:", initialvalue=self.name_var.get(), parent=self.root)
        if name and name.strip():
            try:
                if not self.save_playlist():
                    return
                copied = self.repository.duplicate_playlist(self.playlist.name, name.strip())
                self.playlist = copied
                self.name_var.set(copied.name)
                self._refresh_playlist_names()
                self._refresh_song_lists()
            except (ValueError, KeyError) as exc:
                messagebox.showerror("Save As", str(exc), parent=self.root)

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
            if not self.repository.selections(entry.song_id, instrument_obj.id, self.playlist.id):
                song = self.repository.song(entry.song_id)
                if song:
                    selection_service.auto_select(entry.song_id, instrument_obj.id,
                                                  candidates(getattr(self.paths, "sources", self.paths.source), song),
                                                  instrument_obj, self.playlist.id)
        self.status_var.set("Compiling…")
        def work():
            try:
                result = Compiler(self.repository, self.paths.sources, self.paths.overrides, self.paths.compiled).compile(self.playlist, instrument)
                self.root.after(0, lambda: self._compile_done(result.output_path))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc): messagebox.showerror("Compile", error, parent=self.root))
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
