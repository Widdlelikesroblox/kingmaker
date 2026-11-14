"""ctypes bridge to the C engine (native/kingmaker.c).

If the shared library is missing, `available()` is False and the pure Python engine is used instead.
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import Callable, Optional, Sequence

_LIB_NAMES = {"win32": "kingmaker.dll", "darwin": "libkingmaker.dylib"}
_lib = None
_tried = False


class OutMove(ctypes.Structure):
    _fields_ = [("path", ctypes.c_int8 * 16), ("plen", ctypes.c_int8),
                ("ncaps", ctypes.c_int8), ("caps", ctypes.c_int8 * 12)]


class Result(ctypes.Structure):
    _fields_ = [("score", ctypes.c_int32), ("depth", ctypes.c_int32), ("nmoves", ctypes.c_int32),
                ("npv", ctypes.c_int32), ("nodes", ctypes.c_uint64),
                ("best", OutMove), ("pv", OutMove * 8)]


PROGRESS = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint64, ctypes.POINTER(OutMove))


def _candidates() -> list:
    name = _LIB_NAMES.get(sys.platform, "libkingmaker.so")
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.join(here, name), os.path.join(os.path.dirname(here), name)]
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        paths = [os.path.join(frozen, "kingmaker", name), os.path.join(frozen, name)] + paths
    return paths


def _load():
    global _lib, _tried
    if _tried:
        return _lib
    _tried = True
    if os.environ.get("KINGMAKER_PURE_PYTHON"):
        return None
    for path in _candidates():
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path)
            lib.km_abi.restype = ctypes.c_int
            if lib.km_abi() != ctypes.sizeof(Result) * 1000 + ctypes.sizeof(OutMove):
                continue
            lib.km_init.restype = None
            lib.km_init()
            lib.km_analyze.restype = ctypes.c_int
            lib.km_analyze.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_int32), PROGRESS, ctypes.POINTER(Result)]
            lib.km_perft.restype = ctypes.c_uint64
            lib.km_perft.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            _lib = lib
            break
        except OSError:
            continue
    return _lib


def available() -> bool:
    return _load() is not None


def _move(o: OutMove, sq64, Move):
    return Move(tuple(sq64(o.path[i]) for i in range(o.plen)), tuple(sq64(o.caps[i]) for i in range(o.ncaps)))


def perft(board: Sequence[int], side: int, depth: int) -> int:
    lib = _load()
    arr = (ctypes.c_int8 * 64)(*board)
    return int(lib.km_perft(arr, side, depth))


def analyze(board: Sequence[int], side: int, ms: int, on_progress: Optional[Callable[[dict], None]],
            stop: Optional[Callable[[], bool]], max_depth: int, sq64, Move, Analysis):
    lib = _load()
    arr = (ctypes.c_int8 * 64)(*board)
    stop_flag = ctypes.c_int32(0)
    res = Result()

    def progress(depth, score, nodes, best):
        if stop is not None and stop():
            stop_flag.value = 1
        if on_progress:
            on_progress({"depth": depth, "score": score, "nodes": nodes, "best": _move(best.contents, sq64, Move)})

    cb = PROGRESS(progress)
    # A watcher thread would be heavier than needed: the C search also checks `stop_flag`, which we set
    # from the progress callback and from the helper below when the caller supplies a stop function.
    import threading
    done = threading.Event()

    def watch():
        while not done.wait(0.05):
            if stop is not None and stop():
                stop_flag.value = 1
                return

    t = None
    if stop is not None:
        t = threading.Thread(target=watch, daemon=True)
        t.start()
    try:
        lib.km_analyze(arr, side, ms, max_depth, ctypes.byref(stop_flag), cb, ctypes.byref(res))
    finally:
        done.set()
    if res.nmoves == 0:
        return Analysis(None, -10000, 0, 0, [], 0)
    pv = [_move(res.pv[i], sq64, Move) for i in range(res.npv)]
    return Analysis(_move(res.best, sq64, Move), res.score, res.depth, int(res.nodes), pv, res.nmoves)
