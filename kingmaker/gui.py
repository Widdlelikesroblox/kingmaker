"""Kingmaker desktop app (Tkinter). Run with `python -m kingmaker`."""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from . import engine as E

SQ = 80                      # square size in pixels
LIGHT, DARK = "#E3E7EC", "#34506B"
BLACK_DISC, BLACK_RIM, BLACK_RING = "#1C1F25", "#8895A7", "#3A424E"
RED_DISC, RED_RIM, RED_RING = "#D8483F", "#F6A9A2", "#A52E27"
GOLD, GOLD_INK = "#F2B632", "#1B1405"
BG, PANEL, INK, MUTED, LINE = "#EDF0F4", "#FFFFFF", "#131A22", "#566273", "#D5DBE4"
THINK_CHOICES = {"Quick (1.5 s)": 1500, "Strong (5 s)": 5000, "Deep (12 s)": 12000, "Maximum (30 s)": 30000}
CROWN = [(-16, 11), (-18, -9), (-8, 0), (0, -13), (8, 0), (18, -9), (16, 11)]


def name(side: int) -> str:
    return "Black" if side > 0 else "Red"


def square_number(sq: int) -> int:
    return E.sq32(sq) + 1


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Kingmaker")
        self.configure(bg=BG)
        self.minsize(980, 700)
        self.me = 1
        self.board: List[int] = E.start_board()
        self.turn = 1
        self.mode = "play"
        self.brush = "meMan"
        self.sel: List[int] = []
        self.hist: list = []
        self.last: Optional[tuple] = None
        self.legal: List[E.Move] = []
        self.flip: Optional[bool] = None
        self.show_nums = tk.BooleanVar(value=True)
        self.think_ms = 12000
        self.msg = ""
        self.an: dict = {}
        self.req = 0
        self.stop_ev: Optional[threading.Event] = None
        self.q: "queue.Queue" = queue.Queue()
        self._build_chooser()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ screens
    def _build_chooser(self) -> None:
        self.chooser = tk.Frame(self, bg=BG)
        self.chooser.pack(fill="both", expand=True)
        box = tk.Frame(self.chooser, bg=BG)
        box.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(box, text="Kingmaker", font=("Helvetica", 34, "bold"), bg=BG, fg=INK).pack(anchor="w")
        tk.Label(box, text="Which side are you playing?", font=("Helvetica", 18), bg=BG, fg=INK).pack(anchor="w", pady=(8, 4))
        tk.Label(box, text="Set the pieces up the way they sit on your real board.\n"
                           "Tell Kingmaker what your opponent played and it finds your strongest reply.",
                 justify="left", font=("Helvetica", 12), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 18))
        row = tk.Frame(box, bg=BG)
        row.pack(anchor="w")
        for side, sub in ((1, "Moves first"), (-1, "Moves second")):
            f = tk.Frame(row, bg=PANEL, highlightbackground=LINE, highlightthickness=1, cursor="hand2")
            f.pack(side="left", padx=(0, 14))
            c = tk.Canvas(f, width=64, height=64, bg=PANEL, highlightthickness=0)
            c.pack(side="left", padx=12, pady=12)
            self._piece(c, 32, 32, side, False, 26)
            t = tk.Frame(f, bg=PANEL)
            t.pack(side="left", padx=(0, 22))
            tk.Label(t, text=name(side), font=("Helvetica", 20, "bold"), bg=PANEL, fg=INK).pack(anchor="w")
            tk.Label(t, text=sub, font=("Helvetica", 11), bg=PANEL, fg=MUTED).pack(anchor="w")
            for w in (f, c, t, *t.winfo_children()):
                w.bind("<Button-1>", lambda _e, s=side: self._choose(s))
        tk.Label(box, text="American checkers · 8x8 board · captures are mandatory · kings move both ways",
                 font=("Helvetica", 10), bg=BG, fg=MUTED).pack(anchor="w", pady=(20, 0))

    def _choose(self, side: int) -> None:
        self.me = side
        self.chooser.destroy()
        self._build_main()
        self.refresh_legal()
        self.request()
        self.render()

    def _build_main(self) -> None:
        self.main = tk.Frame(self, bg=BG)
        self.main.pack(fill="both", expand=True, padx=16, pady=14)
        left = tk.Frame(self.main, bg=BG)
        left.pack(side="left", anchor="n")
        self.canvas = tk.Canvas(left, width=SQ * 8, height=SQ * 8, bg=DARK, highlightthickness=4, highlightbackground="#22364A")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click)
        tools = tk.Frame(left, bg=BG)
        tools.pack(fill="x", pady=(10, 0))
        ttk.Button(tools, text="Flip board", command=self._flip).pack(side="left")
        ttk.Checkbutton(tools, text="Square numbers", variable=self.show_nums, command=self.render).pack(side="left", padx=12)
        tk.Label(tools, text="Think time", bg=BG, fg=MUTED).pack(side="left")
        self.think_box = ttk.Combobox(tools, values=list(THINK_CHOICES), state="readonly", width=14)
        self.think_box.set("Deep (12 s)")
        self.think_box.pack(side="left", padx=6)
        self.think_box.bind("<<ComboboxSelected>>", self._on_think)
        tk.Label(left, text="Engine: " + E.engine_name(), bg=BG, fg=MUTED, font=("Helvetica", 9)).pack(anchor="w", pady=(6, 0))

        right = tk.Frame(self.main, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(18, 0), anchor="n")
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x")
        self.mode_play = ttk.Button(top, text="Play", command=lambda: self.set_mode("play"))
        self.mode_play.pack(side="left")
        self.mode_setup = ttk.Button(top, text="Set up", command=lambda: self.set_mode("setup"))
        self.mode_setup.pack(side="left", padx=6)
        self.swap_btn = ttk.Button(top, command=self._swap)
        self.swap_btn.pack(side="right")
        self.panel = tk.Frame(right, bg=BG)
        self.panel.pack(fill="both", expand=True, pady=(12, 0))

    # ------------------------------------------------------------------ drawing
    def _piece(self, c: tk.Canvas, x: float, y: float, side: int, king: bool, r: float) -> None:
        f, rim, ring = (BLACK_DISC, BLACK_RIM, BLACK_RING) if side > 0 else (RED_DISC, RED_RIM, RED_RING)
        c.create_oval(x - r, y - r + 4, x + r, y + r + 4, fill="#1A2733", outline="")
        c.create_oval(x - r, y - r, x + r, y + r, fill=f, outline=rim, width=2)
        k = r * 0.69
        c.create_oval(x - k, y - k, x + k, y + k, outline=ring, width=2)
        if king:
            s = r / 42 * 0.95
            c.create_polygon([(x + px * s, y + py * s) for px, py in CROWN], fill="#FFD166", outline="")
            c.create_rectangle(x - 16 * s, y + 12 * s, x + 16 * s, y + 16 * s, fill="#FFD166", outline="")

    def _xy(self, sq: int) -> tuple:
        r, c = sq >> 3, sq & 7
        if self._flipped():
            r, c = 7 - r, 7 - c
        return c * SQ + SQ / 2, r * SQ + SQ / 2

    def _flipped(self) -> bool:
        return self.flip if self.flip is not None else self.me == 1

    def _from_xy(self, x: float, y: float) -> int:
        c, r = int(x // SQ), int(y // SQ)
        if not (0 <= c < 8 and 0 <= r < 8):
            return -1
        if self._flipped():
            r, c = 7 - r, 7 - c
        return r * 8 + c

    def render_board(self) -> None:
        c = self.canvas
        c.delete("all")
        for sq in range(64):
            x, y = self._xy(sq)
            dark = (((sq >> 3) + (sq & 7)) & 1) == 1
            c.create_rectangle(x - SQ / 2, y - SQ / 2, x + SQ / 2, y + SQ / 2, fill=DARK if dark else LIGHT, outline="")
            if dark and self.show_nums.get():
                c.create_text(x - SQ / 2 + 4, y - SQ / 2 + 3, text=str(square_number(sq)), anchor="nw", fill="#9FB1C3", font=("Courier", 9))
        for sq in (self.last or ()):
            x, y = self._xy(sq)
            c.create_rectangle(x - SQ / 2, y - SQ / 2, x + SQ / 2, y + SQ / 2, fill="#6B6F45", outline="", stipple="gray50")
        targets, movable = [], []
        best = self.an.get("best") if self.mode == "play" else None
        if self.mode == "play" and not self.over():
            cands = [m for m in self.legal if m.path[: len(self.sel)] == tuple(self.sel)]
            if self.sel:
                targets = {m.path[len(self.sel)] for m in cands if len(m.path) > len(self.sel)}
            elif self.has_capture():
                movable = {m.path[0] for m in self.legal}
        for sq in movable:
            x, y = self._xy(sq)
            c.create_oval(x - 38, y - 38, x + 38, y + 38, outline=GOLD, width=3, dash=(5, 5))
        for sq in self.sel:
            x, y = self._xy(sq)
            c.create_oval(x - 37, y - 37, x + 37, y + 37, outline=GOLD, width=4)
        for sq in range(64):
            v = self.board[sq]
            if v:
                x, y = self._xy(sq)
                self._piece(c, x, y, 1 if v > 0 else -1, abs(v) == 2, 33)
        for sq in targets:
            x, y = self._xy(sq)
            c.create_oval(x - 11, y - 11, x + 11, y + 11, fill=GOLD, outline=GOLD_INK, width=2)
        if best and not self.over():
            for sq in best.caps:
                x, y = self._xy(sq)
                c.create_oval(x - 36, y - 36, x + 36, y + 36, outline="#FF5A4D", width=3, dash=(4, 5))
                c.create_line(x - 11, y - 11, x + 11, y + 11, fill="#FF5A4D", width=4, capstyle="round")
                c.create_line(x + 11, y - 11, x - 11, y + 11, fill="#FF5A4D", width=4, capstyle="round")
            self._arrow(best)

    def _arrow(self, move: E.Move) -> None:
        pts = [self._xy(s) for s in move.path]
        mine = self.turn == self.me
        colour = "#FFC93C" if mine else "#BFE0FF"
        (x0, y0), (x1, y1) = pts[0], pts[1]
        d = math.hypot(x1 - x0, y1 - y0) or 1
        pts[0] = (x0 + (x1 - x0) / d * 34, y0 + (y1 - y0) / d * 34)
        flat = [v for p in pts for v in p]
        kwargs = dict(width=9, arrow="last", arrowshape=(18, 20, 9), capstyle="round", joinstyle="round")
        if not mine:
            kwargs["dash"] = (14, 8)
        self.canvas.create_line(*flat, fill="#0A1118", **{**kwargs, "width": 15, "dash": ()})
        self.canvas.create_line(*flat, fill=colour, **kwargs)

    # ------------------------------------------------------------------ side panel
    def clear_panel(self) -> None:
        for w in self.panel.winfo_children():
            w.destroy()

    def card(self, pady=(0, 10)) -> tk.Frame:
        f = tk.Frame(self.panel, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        f.pack(fill="x", pady=pady)
        inner = tk.Frame(f, bg=PANEL)
        inner.pack(fill="x", padx=14, pady=12)
        return inner

    def eval_info(self) -> Optional[tuple]:
        score = self.an.get("score")
        if score is None:
            return None
        mine = score if self.turn == self.me else -score
        if abs(score) > 9700:
            mv = max(1, math.ceil((10000 - abs(score)) / 2))
            unit = "move" if mv == 1 else "moves"
            return (0.985 if mine > 0 else 0.015,
                    f"Forced {'win' if mine > 0 else 'loss'} in about {mv} {unit}")
        v = mine / 100
        p = 1 / (1 + math.exp(-mine / 170))
        if abs(v) < 0.25:
            return p, "Even position"
        return p, f"You {'lead' if v > 0 else 'trail'} by {abs(v):.1f} men"

    def describe(self, m: E.Move) -> str:
        v = self.board[m.path[0]]
        king = abs(v) == 2
        row = m.path[-1] >> 3
        promo = (not king) and ((v > 0 and row == 7) or (v < 0 and row == 0))
        if m.caps:
            t = "Jumps one piece." if len(m.caps) == 1 else f"Jumps {len(m.caps)} pieces in a row."
        else:
            t = "King slides one square." if king else "Steps forward one square."
        return t + (" Crowns a king." if promo else "")

    def render_panel(self) -> None:
        self.swap_btn.config(text=f"You play {name(self.me)} · swap")
        self.clear_panel()
        if self.mode == "setup":
            self._render_setup()
            return
        mine = self.turn == self.me
        a = self.an
        if self.over():
            win = self.turn != self.me
            c = self.card()
            tk.Label(c, text="You win" if win else "You lose", font=("Helvetica", 18, "bold"), bg=PANEL, fg=INK).pack(anchor="w")
            tk.Label(c, text=f"{name(self.turn)} has no legal move.", bg=PANEL, fg=MUTED).pack(anchor="w")
        else:
            c = self.card()
            head = tk.Frame(c, bg=PANEL)
            head.pack(fill="x")
            tk.Label(head, text="Your best move" if mine else "Their strongest reply",
                     font=("Helvetica", 14, "bold"), bg=PANEL, fg=INK).pack(side="left")
            status = ""
            if a.get("status") == "thinking":
                status = f"Searching · depth {a.get('depth', 0)}"
            elif a.get("status") == "done":
                status = f"Searched to depth {a.get('depth')}"
            tk.Label(head, text=status, bg=PANEL, fg=MUTED, font=("Helvetica", 10)).pack(side="right")
            best = a.get("best")
            if best:
                tk.Label(c, text=E.notation(best), font=("Courier", 30, "bold"), bg=PANEL, fg=INK if mine else MUTED).pack(anchor="w", pady=(6, 0))
                tk.Label(c, text=("Only legal move. " if a.get("forced") else "") + self.describe(best), bg=PANEL, fg=MUTED).pack(anchor="w")
            else:
                tk.Label(c, text="...", font=("Courier", 30, "bold"), bg=PANEL, fg=MUTED).pack(anchor="w", pady=(6, 0))
                tk.Label(c, text="Looking at the position.", bg=PANEL, fg=MUTED).pack(anchor="w")
            if self.has_capture():
                tk.Label(c, text=f"A capture is available, so it is mandatory for {'you' if mine else 'them'}.",
                         bg=PANEL, fg=INK, font=("Helvetica", 10)).pack(anchor="w", pady=(8, 0))
            if self.msg:
                tk.Label(c, text=self.msg, bg=PANEL, fg=INK, font=("Helvetica", 10), wraplength=340, justify="left").pack(anchor="w", pady=(6, 0))
            ev = self.eval_info()
            if ev:
                p, text = ev
                bar = tk.Canvas(c, height=10, bg=RED_DISC if self.me > 0 else BLACK_DISC, highlightthickness=1, highlightbackground=LINE)
                bar.pack(fill="x", pady=(12, 4))
                bar.update_idletasks()
                w = max(bar.winfo_width(), 340)
                bar.create_rectangle(0, 0, w * p, 12, fill=BLACK_DISC if self.me > 0 else RED_DISC, outline="")
                row = tk.Frame(c, bg=PANEL)
                row.pack(fill="x")
                tk.Label(row, text=text, bg=PANEL, fg=INK, font=("Helvetica", 11, "bold")).pack(side="left")
                tk.Label(row, text=f"{a.get('nodes', 0):,} positions", bg=PANEL, fg=MUTED, font=("Courier", 10)).pack(side="right")
            pv = a.get("pv") or []
            if len(pv) > 1:
                side = self.turn
                parts = []
                for m in pv:
                    parts.append(f"{'●' if side > 0 else '○'} {E.notation(m)}")
                    side = -side
                tk.Label(c, text="Likely line:  " + "   ".join(parts), bg=PANEL, fg=MUTED, wraplength=340, justify="left",
                         font=("Courier", 10)).pack(anchor="w", pady=(10, 0))
            row = tk.Frame(c, bg=PANEL)
            row.pack(fill="x", pady=(12, 0))
            ttk.Button(row, text="Play this move", command=self.apply_best, state="normal" if best else "disabled").pack(side="left")
            ttk.Button(row, text="Recalculate", command=self._recalc).pack(side="left", padx=6)
        c = self.card()
        head = tk.Frame(c, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Moves", font=("Helvetica", 12, "bold"), bg=PANEL, fg=INK).pack(side="left")
        ttk.Button(head, text="Undo", command=self.undo, state="normal" if self.hist else "disabled").pack(side="right")
        if self.hist:
            text = "   ".join(f"{'●' if e['side'] > 0 else '○'} {e['note']}" for e in self.hist)
        else:
            text = f"Click a piece, then its destination, to record what was played on the real board. {name(self.turn)} is to move."
        tk.Label(c, text=text, bg=PANEL, fg=MUTED, wraplength=340, justify="left", font=("Courier", 10) if self.hist else None).pack(anchor="w", pady=(6, 0))

    def _render_setup(self) -> None:
        c = self.card()
        tk.Label(c, text="Place pieces", font=("Helvetica", 14, "bold"), bg=PANEL, fg=INK).pack(anchor="w")
        self.brush_var = tk.StringVar(value=self.brush)
        for key, label in (("meMan", "My man"), ("meKing", "My king"), ("oppMan", "Their man"), ("oppKing", "Their king"), ("erase", "Erase")):
            tk.Radiobutton(c, text=label, value=key, variable=self.brush_var, bg=PANEL, fg=INK, activebackground=PANEL,
                           selectcolor=PANEL, command=lambda: setattr(self, "brush", self.brush_var.get())).pack(anchor="w")
        tk.Label(c, text="Who moves next", font=("Helvetica", 12, "bold"), bg=PANEL, fg=INK).pack(anchor="w", pady=(12, 0))
        self.turn_var = tk.IntVar(value=self.turn)
        for side, label in ((self.me, f"You · {name(self.me)}"), (-self.me, f"Opponent · {name(-self.me)}")):
            tk.Radiobutton(c, text=label, value=side, variable=self.turn_var, bg=PANEL, fg=INK, activebackground=PANEL,
                           selectcolor=PANEL, command=lambda: setattr(self, "turn", self.turn_var.get())).pack(anchor="w")
        nb = sum(1 for v in self.board if v > 0)
        nr = sum(1 for v in self.board if v < 0)
        tk.Label(c, text=f"Black {nb} · Red {nr}", bg=PANEL, fg=MUTED).pack(anchor="w", pady=(10, 0))
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Starting position", command=lambda: self._set_board(E.start_board(), 1)).pack(side="left")
        ttk.Button(row, text="Clear board", command=lambda: self._set_board([0] * 64, self.turn)).pack(side="left", padx=6)
        ttk.Button(c, text="Analyze this position", command=lambda: self.set_mode("play")).pack(fill="x")
        tk.Label(c, text="Click a dark square to place the selected piece. Click it again to remove it.",
                 bg=PANEL, fg=MUTED, wraplength=340, justify="left", font=("Helvetica", 10)).pack(anchor="w", pady=(8, 0))

    def _set_board(self, board: List[int], turn: int) -> None:
        self.board, self.turn = board, turn
        self.render()

    def render(self) -> None:
        self.render_board()
        self.render_panel()

    # ------------------------------------------------------------------ game logic
    def refresh_legal(self) -> None:
        self.legal = E.legal_moves(self.board, self.turn) if self.mode == "play" else []

    def over(self) -> bool:
        return self.mode == "play" and not self.legal

    def has_capture(self) -> bool:
        return bool(self.legal) and bool(self.legal[0].caps)

    def do_move(self, m: E.Move) -> None:
        self.hist.append({"board": self.board, "turn": self.turn, "side": self.turn, "note": E.notation(m), "last": self.last})
        self.board = E.apply_move(self.board, m)
        self.turn = -self.turn
        self.last = m.path
        self.sel, self.msg = [], ""
        self.refresh_legal()
        self.request()
        self.render()

    def undo(self) -> None:
        if not self.hist:
            return
        e = self.hist.pop()
        self.board, self.turn, self.last = e["board"], e["turn"], e["last"]
        self.sel, self.msg = [], ""
        self.refresh_legal()
        self.request()
        self.render()

    def apply_best(self) -> None:
        best = self.an.get("best")
        if not best:
            return
        for m in self.legal:
            if m.path == best.path:
                self.do_move(m)
                return

    def _on_click(self, ev: tk.Event) -> None:
        sq = self._from_xy(ev.x, ev.y)
        if sq < 0 or (((sq >> 3) + (sq & 7)) & 1) == 0:
            return
        if self.mode == "play":
            self._play_click(sq)
        else:
            self._setup_click(sq)

    def _play_click(self, sq: int) -> None:
        if self.over():
            return
        self.msg = ""
        sel = tuple(self.sel)
        cands = [m for m in self.legal if m.path[: len(sel)] == sel]
        if not sel:
            if any(m.path[0] == sq for m in self.legal):
                self.sel = [sq]
            elif self.board[sq] and (self.board[sq] > 0) == (self.turn > 0):
                self.msg = "You must capture. Pick a piece with a dashed ring." if self.has_capture() else "That piece has no legal move."
            elif self.board[sq]:
                self.msg = f"{name(self.turn)} is to move."
        else:
            nxt = [m for m in cands if len(m.path) > len(sel) and m.path[len(sel)] == sq]
            if nxt:
                self.sel.append(sq)
                done = [m for m in self.legal if m.path == tuple(self.sel)]
                if done:
                    self.do_move(done[0])
                    return
            elif len(sel) == 1 and any(m.path[0] == sq for m in self.legal):
                self.sel = [sq]
            else:
                self.sel = []
        self.render()

    def _setup_click(self, sq: int) -> None:
        me = self.me
        v = {"meMan": me, "meKing": 2 * me, "oppMan": -me, "oppKing": -2 * me, "erase": 0}[self.brush]
        row = sq >> 3
        if abs(v) == 1 and ((v > 0 and row == 7) or (v < 0 and row == 0)):
            v *= 2                       # a man on the far row is a king
        self.board = list(self.board)
        self.board[sq] = 0 if self.board[sq] == v else v
        self.render()

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode, self.sel, self.msg = mode, [], ""
        if mode == "setup":
            self.req += 1
            self._stop()
            self.an, self.legal = {}, []
        else:
            self.hist, self.last = [], None
            self.refresh_legal()
            self.request()
        self.render()

    def _swap(self) -> None:
        self.me = -self.me
        self.flip, self.sel = None, []
        if self.mode == "play":
            self.request()
        self.render()

    def _flip(self) -> None:
        self.flip = not self._flipped()
        self.render_board()

    def _recalc(self) -> None:
        self.request()
        self.render()

    def _on_think(self, _e=None) -> None:
        self.think_ms = THINK_CHOICES[self.think_box.get()]
        if self.mode == "play":
            self.request()
            self.render_panel()

    # ------------------------------------------------------------------ background search
    def _stop(self) -> None:
        if self.stop_ev:
            self.stop_ev.set()

    def request(self) -> None:
        self._stop()
        self.req += 1
        rid = self.req
        if self.mode != "play":
            self.an = {}
            return
        self.refresh_legal()
        if not self.legal:
            self.an = {"status": "over"}
            return
        self.an = {"status": "thinking", "depth": 0, "nodes": 0, "score": None, "best": None, "pv": []}
        ms = self.think_ms if self.turn == self.me else min(self.think_ms, 3000)
        ev = threading.Event()
        self.stop_ev = ev
        board, side = list(self.board), self.turn

        def work() -> None:
            res = E.analyze(board, side, ms,
                            on_progress=lambda p: self.q.put((rid, "progress", p)),
                            stop=ev.is_set)
            self.q.put((rid, "done", res))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        changed = False
        try:
            while True:
                rid, kind, data = self.q.get_nowait()
                if rid != self.req:
                    continue
                if kind == "progress":
                    self.an.update(depth=data["depth"], score=data["score"], best=data["best"], nodes=data["nodes"], pv=[])
                else:
                    self.an = {"status": "done", "depth": data.depth, "nodes": data.nodes, "score": data.score,
                               "best": data.best, "pv": data.pv, "forced": data.n_moves == 1}
                changed = True
        except queue.Empty:
            pass
        if changed and self.mode == "play":
            self.render()
        self.after(100, self._poll)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
