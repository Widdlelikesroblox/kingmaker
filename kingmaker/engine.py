"""Kingmaker engine: American checkers (8x8, mandatory captures, flying-free kings).

Pure Python, no dependencies. Positions are bitboards over the 32 dark squares.
Public API works on 64-square boards (list of 64 ints):

    1 = black man, 2 = black king, -1 = red man, -2 = red king, 0 = empty

Square s is row = s // 8, col = s % 8, row 0 at the top. Black starts at the top
and moves down, red starts at the bottom and moves up. Black moves first.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, NamedTuple, Optional, Sequence, Tuple

BLACK, RED = 1, -1
WIN = 10000
INF = 32000
MAX_PLY = 100
M32 = 0xFFFFFFFF


# --------------------------------------------------------------------------- geometry

def _idx32(r: int, c: int) -> int:
    if r < 0 or r > 7 or c < 0 or c > 7 or ((r + c) & 1) == 0:
        return -1
    return r * 4 + (c >> 1)


COL32 = [(2 * (i & 3)) if ((i >> 2) & 1) else (2 * (i & 3) + 1) for i in range(32)]
SD: List[List[int]] = []  # steps toward higher rows
SU: List[List[int]] = []  # steps toward lower rows
JD: List[List[int]] = []  # jumps toward higher rows: [over, land, over, land]
JU: List[List[int]] = []
for _i in range(32):
    _r, _c = _i >> 2, COL32[_i]
    sd, su, jd, ju = [], [], [], []
    for _dc in (-1, 1):
        t = _idx32(_r + 1, _c + _dc)
        if t >= 0:
            sd.append(t)
        t = _idx32(_r - 1, _c + _dc)
        if t >= 0:
            su.append(t)
        m, l = _idx32(_r + 1, _c + _dc), _idx32(_r + 2, _c + 2 * _dc)
        if m >= 0 and l >= 0:
            jd += [m, l]
        m, l = _idx32(_r - 1, _c + _dc), _idx32(_r - 2, _c + 2 * _dc)
        if m >= 0 and l >= 0:
            ju += [m, l]
    SD.append(sd); SU.append(su); JD.append(jd); JU.append(ju)


def sq64(i: int) -> int:
    """32-square index -> 64-square index."""
    return (i >> 2) * 8 + COL32[i]


def sq32(s: int) -> int:
    """64-square index -> 32-square index (-1 for a light square)."""
    return _idx32(s >> 3, s & 7)


def bits(x: int) -> Iterator[int]:
    while x:
        low = x & -x
        yield low.bit_length() - 1
        x ^= low


# --------------------------------------------------------------------------- public types

class Move(NamedTuple):
    path: Tuple[int, ...]   # 64-square indices, start to finish
    caps: Tuple[int, ...]   # 64-square indices of captured pieces


@dataclass
class Analysis:
    best: Optional[Move]
    score: int                      # centipawns from the side to move; |score| > 9700 means forced result
    depth: int
    nodes: int
    pv: List[Move] = field(default_factory=list)
    n_moves: int = 0

    @property
    def over(self) -> bool:
        return self.best is None


def start_board() -> List[int]:
    b = [0] * 64
    for s in range(64):
        r, c = s >> 3, s & 7
        if (r + c) % 2 == 1:
            if r < 3:
                b[s] = 1
            elif r > 4:
                b[s] = -1
    return b


def notation(move: Move) -> str:
    sep = "x" if move.caps else "-"
    return sep.join(str(sq32(s) + 1) for s in move.path)


# --------------------------------------------------------------------------- bitboard helpers

Pos = Tuple[int, int, int, int]  # black men, black kings, red men, red kings
RawMove = Tuple[int, int, int, Tuple[int, ...]]  # from, to, captured mask, path (32-indices)


def to_bitboards(board: Sequence[int]) -> Pos:
    bm = bk = rm = rk = 0
    for s in range(64):
        v = board[s]
        if not v:
            continue
        i = sq32(s)
        if i < 0:
            continue
        bit = 1 << i
        if v == 1:
            bm |= bit
        elif v == 2:
            bk |= bit
        elif v == -1:
            rm |= bit
        else:
            rk |= bit
    return bm, bk, rm, rk


def to_board(pos: Pos) -> List[int]:
    bm, bk, rm, rk = pos
    b = [0] * 64
    for i in range(32):
        bit = 1 << i
        b[sq64(i)] = 1 if bm & bit else 2 if bk & bit else -1 if rm & bit else -2 if rk & bit else 0
    return b


def _jumps(origin: int, sq: int, king: bool, side: int, caps: int, path: Tuple[int, ...],
           occ: int, opp: int, out: List[RawMove]) -> None:
    found = False
    for forward, table in ((side > 0, JD), (side < 0, JU)):
        if not (king or forward):
            continue
        t = table[sq]
        crown = 28 if side > 0 else 3
        for k in range(0, len(t), 2):
            mid, land = t[k], t[k + 1]
            if not (opp >> mid) & 1 or (caps >> mid) & 1:
                continue
            if (occ >> land) & 1 and land != origin:
                continue
            found = True
            nc, np_ = caps | (1 << mid), path + (land,)
            reached = (land >= crown) if side > 0 else (land <= crown)
            if not king and reached:
                out.append((origin, land, nc, np_))  # a man stops when it is crowned
            else:
                _jumps(origin, land, king, side, nc, np_, occ, opp, out)
    if not found and caps:
        out.append((origin, sq, caps, path))


def gen(pos: Pos, side: int) -> List[RawMove]:
    bm, bk, rm, rk = pos
    occ = bm | bk | rm | rk
    if side > 0:
        men, kings, opp = bm, bk, rm | rk
    else:
        men, kings, opp = rm, rk, bm | bk
    out: List[RawMove] = []
    for sq in bits(men):
        _jumps(sq, sq, False, side, 0, (sq,), occ, opp, out)
    for sq in bits(kings):
        _jumps(sq, sq, True, side, 0, (sq,), occ, opp, out)
    if out:
        return out
    steps = SD if side > 0 else SU
    for sq in bits(men):
        for t in steps[sq]:
            if not (occ >> t) & 1:
                out.append((sq, t, 0, (sq, t)))
    for sq in bits(kings):
        for t in SD[sq] + SU[sq]:
            if not (occ >> t) & 1:
                out.append((sq, t, 0, (sq, t)))
    return out


def make(pos: Pos, side: int, frm: int, to: int, caps: int) -> Pos:
    bm, bk, rm, rk = pos
    fb, tb = 1 << frm, 1 << to
    if side > 0:
        king = bk & fb
        bm &= ~fb; bk &= ~fb
        rm &= ~caps; rk &= ~caps
        if king or to >= 28:
            bk |= tb
        else:
            bm |= tb
    else:
        king = rk & fb
        rm &= ~fb; rk &= ~fb
        bm &= ~caps; bk &= ~caps
        if king or to <= 3:
            rk |= tb
        else:
            rm |= tb
    return bm, bk, rm, rk


def _public(raw: RawMove) -> Move:
    frm, to, caps, path = raw
    return Move(tuple(sq64(p) for p in path), tuple(sq64(c) for c in bits(caps)))


def legal_moves(board: Sequence[int], side: int) -> List[Move]:
    return [_public(m) for m in gen(to_bitboards(board), side)]


def apply_move(board: Sequence[int], move: Move) -> List[int]:
    side = 1 if board[move.path[0]] > 0 else -1
    caps = 0
    for c in move.caps:
        caps |= 1 << sq32(c)
    pos = make(to_bitboards(board), side, sq32(move.path[0]), sq32(move.path[-1]), caps)
    return to_board(pos)


# --------------------------------------------------------------------------- evaluation

def _pop(x: int) -> int:
    return x.bit_count()


def _mask(squares: Sequence[int]) -> int:
    m = 0
    for n in squares:
        m |= 1 << (n - 1)
    return m


ROWM = [0xF << (4 * r) for r in range(8)]
ADV = [0, 3, 7, 12, 18, 26, 38, 0]
CENTER = _mask([10, 11, 14, 15, 18, 19, 22, 23])
EDGE = sum(1 << i for i in range(32) if COL32[i] in (0, 7))
MAIN_DIAG = _mask([4, 8, 11, 15, 18, 22, 25, 29])


def evaluate(pos: Pos, side: int) -> int:
    """Static score in centipawns from the point of view of `side`."""
    bm, bk, rm, rk = pos
    nbm, nbk, nrm, nrk = _pop(bm), _pop(bk), _pop(rm), _pop(rk)
    sc = 100 * (nbm - nrm) + 155 * (nbk - nrk)
    for r in range(1, 7):
        sc += ADV[r] * _pop(bm & ROWM[r]) - ADV[7 - r] * _pop(rm & ROWM[r])
    sc += 6 * (_pop(bm & CENTER) - _pop(rm & CENTER)) + 10 * (_pop(bk & CENTER) - _pop(rk & CENTER))
    sc -= 4 * (_pop(bm & EDGE) - _pop(rm & EDGE)) + 8 * (_pop(bk & EDGE) - _pop(rk & EDGE))
    if nrm > 0:
        sc += 9 * _pop(bm & 0x5) + 3 * _pop(bm & 0xA)    # keep back-rank guards while the enemy can still crown
    if nbm > 0:
        sc -= 9 * _pop(rm & 0xA0000000) + 3 * _pop(rm & 0x50000000)
    empty = ~(bm | bk | rm | rk) & M32
    bd, rd = bm | bk, rm | rk
    mb = (_pop((((bd << 4) | ((bd & 0xE0E0E0E0) << 3) | ((bd & 0x07070707) << 5)) & M32) & empty)
          + _pop(((bk >> 4) | ((bk & 0x07070707) >> 3) | ((bk & 0xE0E0E0E0) >> 5)) & empty))
    mr = (_pop(((rd >> 4) | ((rd & 0x07070707) >> 3) | ((rd & 0xE0E0E0E0) >> 5)) & empty)
          + _pop((((rk << 4) | ((rk & 0xE0E0E0E0) << 3) | ((rk & 0x07070707) << 5)) & M32) & empty))
    sc += 2 * (mb - mr)
    tot = nbm + nbk + nrm + nrk
    diff = (nbm - nrm) * 100 + (nbk - nrk) * 155
    if diff:
        lead = 1 if diff > 0 else -1
        ad = abs(diff)
        sc += lead * min(ad, 300) * (24 - tot) / 60       # trade down when ahead
        if tot <= 8 and ad >= 100 and (nbk + nrk) > 0:    # drive the opponent into the open
            lm, om = ((bm | bk), (rm | rk)) if lead > 0 else ((rm | rk), (bm | bk))
            A, B = list(bits(lm)), list(bits(om))
            if A and B:
                ds = 0
                for a in A:
                    for b in B:
                        ds += max(abs((a >> 2) - (b >> 2)), abs(COL32[a] - COL32[b]))
                sc += lead * (8 - ds / (len(A) * len(B))) * 6
        if tot <= 7 and ad >= 100:                        # losing side should not own the main diagonal
            sc += -10 * _pop(rk & MAIN_DIAG) if lead > 0 else 10 * _pop(bk & MAIN_DIAG)
    sc = int(sc)
    return sc if side > 0 else -sc


# --------------------------------------------------------------------------- search

class _Abort(Exception):
    pass


class _Searcher:
    def __init__(self, deadline: float, stop: Optional[Callable[[], bool]]) -> None:
        self.deadline = deadline
        self.stop = stop
        self.nodes = 0
        self.tt: dict = {}
        self.hist: dict = {}

    def search(self, ply: int, pos: Pos, side: int, depth: int, alpha: int, beta: int) -> int:
        self.nodes += 1
        if (self.nodes & 2047) == 0 and (time.monotonic() > self.deadline or (self.stop and self.stop())):
            raise _Abort
        moves = gen(pos, side)
        if not moves:
            return -(WIN - ply)
        capture = moves[0][2] != 0
        if (depth <= 0 and not capture) or ply >= MAX_PLY:
            return evaluate(pos, side)

        key = (pos, side)
        tt_move = -1
        if depth > 0:
            e = self.tt.get(key)
            if e is not None:
                e_depth, e_score, e_flag, tt_move = e
                if e_depth >= depth:
                    s = e_score - ply if e_score > WIN - 200 else e_score + ply if e_score < -WIN + 200 else e_score
                    if e_flag == 0 or (e_flag == 1 and s >= beta) or (e_flag == 2 and s <= alpha):
                        return s

        hist = self.hist
        moves.sort(key=lambda m: -(10 ** 9 if m[0] * 32 + m[1] == tt_move else
                                   10 ** 6 if m[2] else hist.get(m[0] * 32 + m[1], 0)))
        alpha0 = alpha
        best, best_code = -INF, -1
        single = len(moves) == 1
        for i, (frm, to, caps, _p) in enumerate(moves):
            child = make(pos, side, frm, to, caps)
            nd = depth if (single and caps) else depth - 1
            if i == 0:
                sc = -self.search(ply + 1, child, -side, nd, -beta, -alpha)
            else:
                sc = -self.search(ply + 1, child, -side, nd, -alpha - 1, -alpha)
                if alpha < sc < beta:
                    sc = -self.search(ply + 1, child, -side, nd, -beta, -alpha)
            if sc > best:
                best, best_code = sc, frm * 32 + to
                if sc > alpha:
                    alpha = sc
            if alpha >= beta:
                if not caps:
                    hist[frm * 32 + to] = hist.get(frm * 32 + to, 0) + depth * depth
                break
        if depth > 0:
            flag = 2 if best <= alpha0 else 1 if best >= beta else 0
            s = best + ply if best > WIN - 200 else best - ply if best < -WIN + 200 else best
            old = self.tt.get(key)
            if old is None or old[0] <= depth:
                self.tt[key] = (depth, s, flag, -1 if flag == 2 else best_code)
        return best


def analyze_py(board: Sequence[int], side: int, ms: int = 3000,
            on_progress: Optional[Callable[[dict], None]] = None,
            stop: Optional[Callable[[], bool]] = None,
            max_depth: int = 64) -> Analysis:
    """Search for the best move for `side`.

    ms          time budget in milliseconds
    on_progress called after every completed depth with {depth, score, best, nodes}
    stop        optional callable; return True to abort the search early
    """
    pos = to_bitboards(board)
    root = gen(pos, side)
    if not root:
        return Analysis(None, -WIN, 0, 0, [], 0)
    budget = min(ms, 400) if len(root) == 1 else ms
    s = _Searcher(time.monotonic() + budget / 1000.0, stop)
    best_score, done_depth = 0, 0
    for depth in range(1, max_depth + 1):
        alpha, it_best, it_score = -INF, -1, -INF
        try:
            for i, (frm, to, caps, _p) in enumerate(root):
                child = make(pos, side, frm, to, caps)
                nd = depth if (len(root) == 1 and caps) else depth - 1
                if i == 0:
                    sc = -s.search(1, child, -side, nd, -INF, -alpha)
                else:
                    sc = -s.search(1, child, -side, nd, -alpha - 1, -alpha)
                    if sc > alpha:
                        sc = -s.search(1, child, -side, nd, -INF, -alpha)
                if sc > it_score:
                    it_score, it_best = sc, i
                if sc > alpha:
                    alpha = sc
        except _Abort:
            break
        if it_best > 0:
            root.insert(0, root.pop(it_best))
        best_score, done_depth = it_score, depth
        if on_progress:
            on_progress({"depth": depth, "score": best_score, "best": _public(root[0]), "nodes": s.nodes})
        if abs(best_score) > WIN - 150 and depth >= 2:
            break
        if time.monotonic() > s.deadline:
            break

    pv = [_public(root[0])]
    cur, cside = make(pos, side, root[0][0], root[0][1], root[0][2]), -side
    for _ in range(6):
        e = s.tt.get((cur, cside))
        if not e or e[3] < 0:
            break
        match = [m for m in gen(cur, cside) if m[0] * 32 + m[1] == e[3]]
        if not match:
            break
        m = match[0]
        pv.append(_public(m))
        cur, cside = make(cur, cside, m[0], m[1], m[2]), -cside
    return Analysis(_public(root[0]), best_score, done_depth, s.nodes, pv, len(root))


def analyze(board: Sequence[int], side: int, ms: int = 3000,
            on_progress: Optional[Callable[[dict], None]] = None,
            stop: Optional[Callable[[], bool]] = None,
            max_depth: int = 64) -> Analysis:
    """Search with the native C engine when it is built, otherwise with the pure Python engine."""
    from . import native
    if native.available():
        return native.analyze(board, side, ms, on_progress, stop, max_depth, sq64, Move, Analysis)
    return analyze_py(board, side, ms, on_progress, stop, max_depth)


def engine_name() -> str:
    from . import native
    return "native C engine" if native.available() else "pure Python engine"
