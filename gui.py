"""
PlayerReferences – Interfaz gráfica (customtkinter).

Layout:
  ┌─ top bar: Mi Profile ID + [Cargar] ─────────────────────────┐
  ├─ left panel (oponentes) ──┬─ right panel (notas) ───────────┤
  │  [buscar...]              │  Nombre  [profile_id]           │
  │                           │  ×N partidas · último: fecha    │
  │  pid  Nombre  ×N  📝      │  ─────────────────────────────  │
  │  pid  Nombre  ×N          │  [notas guardadas]              │
  │  …                        │                                 │
  │                           │  Nueva nota:                    │
  │                           │  [textbox]   [Guardar]          │
  └───────────────────────────┴─────────────────────────────────┘
  [status bar]
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable

import customtkinter as ctk

import database as db
import scraper

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_FONT_H1 = ("Segoe UI", 17, "bold")
_FONT_H2 = ("Segoe UI", 14, "bold")
_FONT_NORMAL = ("Segoe UI", 13)
_FONT_SMALL = ("Segoe UI", 11)
_FONT_MONO = ("Consolas", 12)
_COL_ACCENT = "#3a7ebf"
_COL_SELECTED = "#1a3f6f"
_COL_NOTE_BG = "#252535"
_COL_SEP = "#333340"
_COL_WIN = "#2d622d"
_COL_LOSS = "#622d2d"
_COL_LIVE = "#7a2020"


def _short_date(iso: str | None) -> str:
    if not iso:
        return "—"
    return iso[:16].replace("T", " ").replace("Z", "")


def _speak(text: str):
    """Speak text via Windows SAPI (non-blocking, true async)."""
    safe = text.replace('"', '').replace("'", ' ')
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 1; "
        f'$s.Speak("{safe}")'
    )
    def run_async():
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    threading.Thread(target=run_async, daemon=True).start()


# ── Notes Dialog (opens on double-click in match view) ────────────────────────

class NotesDialog(ctk.CTkToplevel):
    """Modal window showing notes for one opponent, opened by double-click."""

    def __init__(self, master, profile_id: int, player_name: str):
        super().__init__(master)
        self.title(f"Notas – {player_name}")
        self.geometry("580x500")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()
        self.focus()

        self._profile_id = profile_id
        self._player_name = player_name

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text=player_name, font=_FONT_H1, text_color=_COL_ACCENT, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            hdr, text=f"Profile ID: {profile_id}", font=_FONT_SMALL, text_color="#777", anchor="w"
        ).grid(row=1, column=0, sticky="w")

        ctk.CTkFrame(self, height=1, fg_color=_COL_SEP).grid(row=0, column=0, sticky="sew", padx=8)

        # Notes list
        self._notes_scroll = ctk.CTkScrollableFrame(self, label_text="Notas guardadas")
        self._notes_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self._notes_scroll.grid_columnconfigure(0, weight=1)

        # New note
        note_area = ctk.CTkFrame(self, fg_color="transparent")
        note_area.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        note_area.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(note_area, text="Nueva nota:", font=_FONT_SMALL, text_color="#888").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self._note_input = ctk.CTkTextbox(note_area, height=70, font=_FONT_NORMAL)
        self._note_input.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            note_area, text="Guardar nota", command=self._save_note, width=140, height=32
        ).grid(row=2, column=0, sticky="w")

        self._load_notes()

    def _load_notes(self):
        for w in self._notes_scroll.winfo_children():
            w.destroy()
        notes = db.get_notes(self._profile_id)
        if not notes:
            ctk.CTkLabel(
                self._notes_scroll, text="Sin notas todavía.", font=_FONT_SMALL, text_color="#555"
            ).pack(anchor="w", padx=8, pady=10)
            return
        for note in notes:
            NoteCard(self._notes_scroll, note=note, on_delete=self._delete_note).pack(
                fill="x", padx=4, pady=3
            )

    def _save_note(self):
        text = self._note_input.get("1.0", "end").strip()
        if not text:
            return
        db.ensure_opponent(self._profile_id, self._player_name)
        db.add_note(self._profile_id, text)
        self._note_input.delete("1.0", "end")
        self._load_notes()

    def _delete_note(self, note_id: int):
        db.delete_note(note_id)
        self._load_notes()


# ── Match card widget ─────────────────────────────────────────────────────────

class MatchCard(ctk.CTkFrame):
    """
    Displays one match: header (date · map · result) + team rows.
    Player names in team rows trigger a NotesDialog on double-click.
    """

    def __init__(self, master, match: dict, my_pid: int, open_notes, **kwargs):
        if match.get("is_live"):
            bg = _COL_LIVE
        elif match.get("my_won") == 1:
            bg = _COL_WIN
        elif match.get("my_won") == 0:
            bg = _COL_LOSS
        else:
            bg = "#2a2a2a"
        super().__init__(master, corner_radius=5, fg_color=bg, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        # Header line
        is_live = match.get("is_live")
        my_won = match.get("my_won")
        if is_live:
            result = "🔴 EN VIVO"
        elif my_won == 1:
            result = "✓ GANÓ"
        elif my_won == 0:
            result = "✗ PERDIÓ"
        else:
            result = "—"

        date_str = _short_date(match.get("started_at"))
        map_name = match.get("map_name") or "?"
        hdr_text = f"{date_str}   {map_name}   {result}"
        ctk.CTkLabel(
            self, text=hdr_text, font=_FONT_SMALL, anchor="w", text_color="#ccc"
        ).grid(row=0, column=0, padx=10, pady=(7, 2), sticky="w")

        # Teams
        teams: dict = match.get("teams", {})
        for row_i, (tid, players) in enumerate(sorted(teams.items()), start=1):
            team_frame = ctk.CTkFrame(self, fg_color="transparent")
            team_frame.grid(row=row_i, column=0, sticky="ew", padx=10, pady=1)

            ctk.CTkLabel(
                team_frame, text=f"Eq {tid}:", font=_FONT_SMALL, text_color="#888", width=40, anchor="w"
            ).pack(side="left")

            for p in players:
                pid = p.get("profile_id")
                name = p.get("name", "?")
                civ = p.get("civ_name") or ""
                is_user = pid == my_pid
                display = f"[{name}]" if is_user else name
                if civ:
                    display += f" ({civ})"

                lbl = ctk.CTkLabel(
                    team_frame,
                    text=display + "  ",
                    font=("Segoe UI", 11, "bold") if is_user else _FONT_SMALL,
                    text_color="#6ab0f5" if is_user else "white",
                    cursor="hand2" if (not is_user and pid) else "arrow",
                    anchor="w",
                )
                lbl.pack(side="left")

                if not is_user and pid:
                    lbl.bind(
                        "<Double-Button-1>",
                        lambda _e, p=p: open_notes(p["profile_id"], p["name"]),
                    )

        # bottom padding
        ctk.CTkFrame(self, height=4, fg_color="transparent").grid(
            row=len(teams) + 1, column=0
        )


# ── Reusable widgets ──────────────────────────────────────────────────────────

class NoteCard(ctk.CTkFrame):
    """One saved note with date header and delete button."""

    def __init__(self, master, note: dict, on_delete: Callable[[int], None], **kwargs):
        super().__init__(master, fg_color=_COL_NOTE_BG, corner_radius=6, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        date_str = note["created_at"][:16].replace("T", " ")
        ctk.CTkLabel(
            self, text=date_str, font=_FONT_SMALL, text_color="#777", anchor="w"
        ).grid(row=0, column=0, padx=10, pady=(7, 1), sticky="w")

        ctk.CTkLabel(
            self, text=note["note_text"], font=_FONT_NORMAL,
            anchor="w", justify="left", wraplength=500,
        ).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")

        ctk.CTkButton(
            self, text="✕", width=26, height=22, font=_FONT_SMALL,
            fg_color="transparent", hover_color="#5a2020",
            command=lambda: on_delete(note["id"]),
        ).grid(row=0, column=1, padx=(4, 8), pady=(5, 0), sticky="ne")


class OpponentRow(ctk.CTkFrame):
    """Clickable row for one opponent in the left panel list."""

    def __init__(
        self, master, opp: dict, on_select: Callable[[dict], None], **kwargs
    ):
        super().__init__(master, cursor="hand2", corner_radius=4, **kwargs)
        self._opp = opp
        self._on_select = on_select
        self.grid_columnconfigure(1, weight=1)
        self._build(opp)

    def _build(self, opp: dict):
        has_notes = opp.get("note_count", 0) > 0
        click = lambda _e, o=opp: self._on_select(o)

        pid_lbl = ctk.CTkLabel(
            self, text=str(opp["profile_id"]),
            width=82, font=_FONT_MONO, text_color="#888", anchor="w",
        )
        pid_lbl.grid(row=0, column=0, padx=(10, 4), pady=7)
        pid_lbl.bind("<Button-1>", click)

        name_font = ("Segoe UI", 13, "bold") if has_notes else _FONT_NORMAL
        name_lbl = ctk.CTkLabel(self, text=opp["name"], font=name_font, anchor="w")
        name_lbl.grid(row=0, column=1, padx=4, pady=7, sticky="ew")
        name_lbl.bind("<Button-1>", click)

        times = opp.get("times_met", 0)
        tm_lbl = ctk.CTkLabel(
            self, text=f"×{times}", width=38, font=_FONT_SMALL, text_color="#666", anchor="e"
        )
        tm_lbl.grid(row=0, column=2, padx=(2, 4))
        tm_lbl.bind("<Button-1>", click)

        col = 3
        if has_notes:
            badge = ctk.CTkLabel(self, text="📝", width=22, font=("Segoe UI", 11))
            badge.grid(row=0, column=col, padx=(0, 8))
            badge.bind("<Button-1>", click)
            col += 1

        self.bind("<Button-1>", click)

    def set_selected(self, selected: bool):
        self.configure(fg_color=_COL_SELECTED if selected else "transparent")


# ── Main application ──────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PlayerReferences – AoE2 Tracker")
        self.geometry("1150x700")
        self.minsize(860, 520)

        db.init_db()

        self._my_pid: int | None = None
        self._selected_opp: dict | None = None
        self._opp_rows: list[OpponentRow] = []
        self._scraping = False
        self._live_match_key: str | None = None

        self._build_ui()

        saved = db.get_my_profile_id()
        if saved:
            self._my_pid = saved
            self._pid_entry.insert(0, str(saved))
            self._refresh_opponent_list()
            self._refresh_matches_tab()

        self.after(5000, self._poll_live)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_topbar()       # row 0
        self._build_live_banner()  # row 1 (hidden until live match)
        self._build_content()      # row 2
        self._build_statusbar()    # row 3

    def _build_topbar(self):
        bar = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color="#14141e")
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, text="Mi Profile ID:", font=_FONT_NORMAL).pack(
            side="left", padx=(18, 6), pady=14
        )
        self._pid_entry = ctk.CTkEntry(
            bar, placeholder_text="ej. 459658", width=150, font=_FONT_MONO
        )
        self._pid_entry.pack(side="left", padx=(0, 6), pady=12)
        self._pid_entry.bind("<Return>", lambda _: self._start_scrape())

        # Name label sits right after the entry field so it's always visible
        self._my_name_lbl = ctk.CTkLabel(
            bar, text="", font=("Segoe UI", 14, "bold"), text_color=_COL_ACCENT,
            width=180, anchor="w",
        )
        self._my_name_lbl.pack(side="left", padx=(0, 10), pady=14)

        ctk.CTkButton(
            bar, text="Cargar mis partidas", command=self._start_scrape,
            width=170, height=32,
        ).pack(side="left", padx=(0, 8), pady=11)

        ctk.CTkButton(
            bar, text="↻ Actualizar", command=self._start_scrape,
            width=110, height=32, fg_color="#285228", hover_color="#357035",
        ).pack(side="left", pady=11)

    def _build_content(self):
        pane = ctk.CTkFrame(self, fg_color="transparent")
        pane.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        pane.grid_columnconfigure(1, weight=1)
        pane.grid_rowconfigure(0, weight=1)
        self._build_left(pane)
        self._build_right(pane)

    # ── Live match banner ─────────────────────────────────────────────────────

    def _build_live_banner(self):
        self._live_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#3a0e0e")
        # Not gridded until a live match is detected
        self._live_frame.grid_columnconfigure(0, weight=1)

        self._live_header_lbl = ctk.CTkLabel(
            self._live_frame, text="", font=_FONT_H2,
            text_color="#ff8888", anchor="w",
        )
        self._live_header_lbl.grid(row=0, column=0, padx=14, pady=(8, 4), sticky="w")

        self._live_opps_frame = ctk.CTkFrame(self._live_frame, fg_color="transparent")
        self._live_opps_frame.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        self._live_opps_frame.grid_columnconfigure(1, weight=1)

    def _update_live_banner(self, live: scraper.MatchInfo | None, announce: bool = False):
        if live is None:
            self._live_frame.grid_remove()
            return

        my_team = next((p.team_id for p in live.all_players if p.is_me), None)
        opponents = [p for p in live.all_players if p.team_id != my_team]
        n_total = len(live.all_players)
        mode = f"{n_total // 2}v{n_total // 2}" if n_total > 2 else "1v1"

        self._live_header_lbl.configure(
            text=f"🔴  EN VIVO — {live.map_name or '?'}   {mode}"
        )

        for w in self._live_opps_frame.winfo_children():
            w.destroy()

        # Build UI without DB reads (keep UI fast)
        for i, opp in enumerate(opponents):
            ctk.CTkLabel(
                self._live_opps_frame,
                text=opp.name,
                font=("Segoe UI", 12, "bold"),
                text_color="#ffaaaa",
                width=160,
                anchor="w",
            ).grid(row=i, column=0, padx=(0, 8), pady=1, sticky="w")

            # Placeholder until notes load
            ctk.CTkLabel(
                self._live_opps_frame,
                text="Cargando notas…",
                font=_FONT_SMALL,
                text_color="#666666",
                anchor="w",
            ).grid(row=i, column=1, pady=1, sticky="w")

        self._live_frame.grid(row=1, column=0, sticky="ew")

        if announce:
            self._announce_live_match(live)

        # Load notes in background thread without blocking UI
        def load_notes_async():
            notes_map = {}
            for opp in opponents:
                notes = db.get_notes(opp.profile_id)
                last3 = notes[-3:] if notes else []
                if last3:
                    notes_text = "  ·  ".join(n["note_text"][:70] for n in last3)
                else:
                    notes_text = "No tengo información acerca de este jugador"
                notes_map[opp.profile_id] = notes_text

            def update_ui():
                if not self._live_frame.winfo_exists():
                    return
                for i, opp in enumerate(opponents):
                    for w in self._live_opps_frame.grid_slaves(row=i, column=1):
                        w.destroy()
                    ctk.CTkLabel(
                        self._live_opps_frame,
                        text=notes_map.get(opp.profile_id, "Error cargando"),
                        font=_FONT_SMALL,
                        text_color="#cccccc",
                        anchor="w",
                    ).grid(row=i, column=1, pady=1, sticky="w")

            self.after(0, update_ui)

        threading.Thread(target=load_notes_async, daemon=True).start()

    def _announce_live_match(self, live: scraper.MatchInfo):
        """Build and speak live match info in background thread (doesn't block UI)."""
        def build_and_speak():
            my_team = next((p.team_id for p in live.all_players if p.is_me), None)
            opponents = [p for p in live.all_players if p.team_id != my_team]
            n_total = len(live.all_players)
            mode = f"{n_total // 2}v{n_total // 2}" if n_total > 2 else "1v1"
            map_name = live.map_name or "mapa desconocido"

            speech_parts = []
            for opp in opponents:
                notes = db.get_notes(opp.profile_id)
                last3 = notes[-3:] if notes else []
                if last3:
                    speech_notes = ". ".join(n["note_text"] for n in last3)
                else:
                    speech_notes = "No tengo información"
                speech_parts.append(f"{opp.name}. {speech_notes}")

            full_text = (
                f"Partida en vivo. {map_name}. {mode}. "
                + ". ".join(speech_parts)
            )
            _speak(full_text)

        threading.Thread(target=build_and_speak, daemon=True).start()

    def _poll_live(self):
        if self._my_pid is None:
            self.after(5000, self._poll_live)
            return
        threading.Thread(
            target=self._poll_worker, args=(self._my_pid,), daemon=True
        ).start()

    def _poll_worker(self, my_pid: int):
        try:
            matches = scraper.get_player_matches(my_pid, count=3)
            live = next((m for m in matches if m.is_live), None)
            new_key = live.match_key if live else None

            if new_key != self._live_match_key:
                self._live_match_key = new_key
                match_dicts = [
                    {
                        "match_key": m.match_key,
                        "map_name": m.map_name,
                        "started_at": m.started_at,
                        "is_live": m.is_live,
                        "my_won": m.my_won,
                        "opponents": m.opponents,
                    }
                    for m in matches
                ]
                db.save_matches(my_pid, match_dicts)
                # Single batched UI update call (avoids multiple event loop entries)
                self.after(0, lambda l=live: self._batch_ui_update(l))
        except Exception:
            pass
        try:
            self.after(5000, self._poll_live)
        except Exception:
            pass  # window was destroyed

    def _batch_ui_update(self, live: scraper.MatchInfo | None):
        """Batch all UI updates together to prevent multiple UI thread entries."""
        self._update_live_banner(live, announce=live is not None)
        self._refresh_matches_tab()
        self._refresh_opponent_list()

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left(self, parent):
        frame = ctk.CTkFrame(parent, width=360)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        frame.grid_propagate(False)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_list())
        ctk.CTkEntry(
            frame, placeholder_text="Buscar oponente…",
            textvariable=self._search_var, font=_FONT_NORMAL,
        ).grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")

        self._opp_scroll = ctk.CTkScrollableFrame(frame, label_text="Oponentes")
        self._opp_scroll.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="nsew")
        self._opp_scroll.grid_columnconfigure(0, weight=1)

        self._count_lbl = ctk.CTkLabel(
            frame, text="", font=_FONT_SMALL, text_color="#555"
        )
        self._count_lbl.grid(row=2, column=0, padx=8, pady=(0, 6))

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self, parent):
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        self._tabs = ctk.CTkTabview(frame)
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._tabs.add("Notas")
        self._tabs.add("Partidas")

        self._build_notes_tab()
        self._build_matches_tab()

    def _build_notes_tab(self):
        tab = self._tabs.tab("Notas")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(tab, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        hdr.grid_columnconfigure(0, weight=1)
        self._opp_name_lbl = ctk.CTkLabel(
            hdr, text="← Selecciona un oponente",
            font=_FONT_H1, anchor="w", text_color="#555",
        )
        self._opp_name_lbl.grid(row=0, column=0, sticky="w")
        self._opp_meta_lbl = ctk.CTkLabel(
            hdr, text="", font=_FONT_SMALL, anchor="w", text_color="#666"
        )
        self._opp_meta_lbl.grid(row=1, column=0, sticky="w")
        ctk.CTkFrame(tab, height=1, fg_color=_COL_SEP).grid(row=0, column=0, sticky="sew", padx=10)

        # Notes list
        self._notes_scroll = ctk.CTkScrollableFrame(tab, label_text="Notas guardadas")
        self._notes_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self._notes_scroll.grid_columnconfigure(0, weight=1)

        # New note area
        note_area = ctk.CTkFrame(tab, fg_color="transparent")
        note_area.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        note_area.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            note_area, text="Nueva nota:", font=_FONT_SMALL, text_color="#888"
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._note_input = ctk.CTkTextbox(note_area, height=80, font=_FONT_NORMAL)
        self._note_input.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self._save_btn = ctk.CTkButton(
            note_area, text="Guardar nota", command=self._save_note,
            width=140, height=32, state="disabled",
        )
        self._save_btn.grid(row=2, column=0, sticky="w")

    def _build_matches_tab(self):
        tab = self._tabs.tab("Partidas")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self._matches_scroll = ctk.CTkScrollableFrame(
            tab, label_text="Historial de partidas  (doble-click en un jugador → notas)"
        )
        self._matches_scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._matches_scroll.grid_columnconfigure(0, weight=1)

    # ── Opponent list management ──────────────────────────────────────────────

    def _refresh_opponent_list(self, search: str = ""):
        if self._my_pid is None:
            return
        for w in self._opp_scroll.winfo_children():
            w.destroy()
        self._opp_rows.clear()

        opponents = db.get_opponents(self._my_pid, search)
        self._count_lbl.configure(text=f"{len(opponents)} oponente(s)")

        for opp in opponents:
            row = OpponentRow(
                self._opp_scroll, opp=opp, on_select=self._select_opponent,
                fg_color="transparent",
            )
            row.grid(sticky="ew", pady=1)
            if (
                self._selected_opp
                and opp["profile_id"] == self._selected_opp["profile_id"]
            ):
                row.set_selected(True)
            self._opp_rows.append(row)

    def _filter_list(self):
        self._refresh_opponent_list(self._search_var.get())

    def _select_opponent(self, opp: dict):
        self._selected_opp = opp
        for row in self._opp_rows:
            row.set_selected(row._opp["profile_id"] == opp["profile_id"])
        self._show_opponent(opp)

    # ── Right panel updates ───────────────────────────────────────────────────

    def _show_opponent(self, opp: dict):
        self._opp_name_lbl.configure(text=opp["name"], text_color=_COL_ACCENT)
        times = opp.get("times_met", 0)
        last = (opp.get("last_seen") or "")[:10]
        self._opp_meta_lbl.configure(
            text=f"Profile ID: {opp['profile_id']}  ·  {times} partida(s)  ·  Último: {last}",
            text_color="#888",
        )
        self._save_btn.configure(state="normal")
        self._note_input.delete("1.0", "end")
        self._load_notes(opp["profile_id"])

    def _load_notes(self, profile_id: int):
        for w in self._notes_scroll.winfo_children():
            w.destroy()
        notes = db.get_notes(profile_id)
        if not notes:
            ctk.CTkLabel(
                self._notes_scroll, text="Sin notas todavía.",
                font=_FONT_SMALL, text_color="#555",
            ).pack(anchor="w", padx=8, pady=10)
            return
        for note in notes:
            NoteCard(
                self._notes_scroll, note=note, on_delete=self._delete_note
            ).pack(fill="x", padx=4, pady=3)

    def _save_note(self):
        if self._selected_opp is None:
            return
        text = self._note_input.get("1.0", "end").strip()
        if not text:
            self._set_status("Escribe algo antes de guardar.", error=True)
            return
        db.add_note(self._selected_opp["profile_id"], text)
        self._note_input.delete("1.0", "end")
        self._load_notes(self._selected_opp["profile_id"])
        self._refresh_opponent_list(self._search_var.get())
        self._set_status("✓ Nota guardada.")

    def _delete_note(self, note_id: int):
        db.delete_note(note_id)
        if self._selected_opp:
            self._load_notes(self._selected_opp["profile_id"])
        self._set_status("Nota eliminada.")

    def _open_notes_dialog(self, profile_id: int, player_name: str):
        NotesDialog(self, profile_id, player_name)
        # Refresh opponents list in case a new note was added for a new opponent
        self.after(200, self._refresh_opponent_list)

    # ── Matches tab ───────────────────────────────────────────────────────────

    def _refresh_matches_tab(self):
        if self._my_pid is None:
            return
        for w in self._matches_scroll.winfo_children():
            w.destroy()
        matches = db.get_match_history(self._my_pid, limit=30)
        if not matches:
            ctk.CTkLabel(
                self._matches_scroll,
                text="Sin partidas guardadas. Usa 'Cargar mis partidas'.",
                font=_FONT_SMALL, text_color="#555",
            ).pack(anchor="w", padx=10, pady=10)
            return
        for m in matches:
            MatchCard(
                self._matches_scroll, match=m, my_pid=self._my_pid,
                open_notes=self._open_notes_dialog,
            ).pack(fill="x", padx=4, pady=3)

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _start_scrape(self):
        pid_text = self._pid_entry.get().strip()
        if not pid_text:
            self._set_status("Introduce tu Profile ID.", error=True)
            return
        try:
            pid = int(pid_text)
        except ValueError:
            self._set_status("El Profile ID debe ser numérico.", error=True)
            return
        if self._scraping:
            self._set_status("Ya hay un scraping en curso, espera.", error=True)
            return

        self._my_pid = pid
        db.set_my_profile_id(pid)
        self._scraping = True
        self._set_status(f"Scrapeando partidas de [{pid}]…")
        threading.Thread(target=self._scrape_worker, args=(pid,), daemon=True).start()

    def _scrape_worker(self, my_pid: int):
        try:
            matches = scraper.get_player_matches(my_pid, count=30)

            # Extract the user's own name from the first match they appear in
            my_name = next(
                (p.name for m in matches for p in m.all_players if p.is_me),
                None,
            )
            if my_name:
                self.after(0, lambda n=my_name: self._my_name_lbl.configure(text=n))

            match_dicts = [
                {
                    "match_key": m.match_key,
                    "map_name": m.map_name,
                    "started_at": m.started_at,
                    "is_live": m.is_live,
                    "my_won": m.my_won,
                    "opponents": m.opponents,
                }
                for m in matches
            ]
            new_m, new_o = db.save_matches(my_pid, match_dicts)

            unique_opps = len({
                p.profile_id for m in matches for p in m.all_players if not p.is_me
            })
            self.after(0, self._refresh_opponent_list)
            self.after(0, self._refresh_matches_tab)
            self.after(0, lambda: self._set_status(
                f"✓ {len(matches)} partidas  ·  {unique_opps} oponentes únicos  "
                f"·  {new_m} nuevas guardadas  ·  {new_o} oponentes nuevos"
            ))
        except Exception as exc:
            self.after(0, lambda: self._set_status(f"✗ Error: {exc}", error=True))
        finally:
            self._scraping = False

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color="#0e0e16")
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        self._status_lbl = ctk.CTkLabel(
            bar, text="Listo.", font=_FONT_SMALL, text_color="#555"
        )
        self._status_lbl.pack(side="left", padx=12, pady=4)

    def _set_status(self, text: str, error: bool = False):
        self._status_lbl.configure(
            text=text, text_color="#d45050" if error else "#888"
        )


