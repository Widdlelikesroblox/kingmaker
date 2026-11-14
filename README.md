# Kingmaker

A checkers coach for American checkers (8x8, captures are mandatory, kings move both ways).

Pick Black or Red, set the pieces up the way they sit on your real board, and record every move
that is played, yours and your opponent's. Kingmaker searches the position and shows the strongest
move for whoever is to play, with an arrow on the board, a win/loss bar and the likely line.

## Quick install

Linux or macOS: `./install.sh`, then `./kingmaker-run`.
Windows: double-click `install.bat`, then `Kingmaker.bat`.

The installer checks Python and Tkinter, builds the C engine and creates the launcher.

## Run it by hand

Needs Python 3.10 or newer with Tkinter (included with the python.org installers; on Debian or
Ubuntu run `sudo apt install python3-tk`). There are no Python packages to install.

```bash
python build_native.py   # compiles the fast C engine (needs gcc or clang)
python run.py            # or: python -m kingmaker
```

The window shows which engine is running. Without the compiled library the app falls back to the
pure Python engine, which works but searches about 12 times shallower.

## Using it

- **Play tab:** click a piece, then its destination, to record a move. Multi-jumps are clicked one landing square at a time.
- **Play this move** applies the suggested move for you. **Undo** steps back.
- **Set up tab:** place or erase men and kings for both sides, choose who moves next, then press *Analyze this position*. Use this to match a game that is already in progress.
- **Think time:** longer means stronger. Deep (12 s) is the default.

## Use the engine in your own code

```python
from kingmaker import engine as E

board = E.start_board()                 # 64 ints: 1 black man, 2 black king, -1 red man, -2 red king
result = E.analyze(board, E.BLACK, ms=3000)
print(E.notation(result.best), result.score, result.depth)
board = E.apply_move(board, result.best)
```

## Tests

```bash
python -m unittest discover -s tests -v
KINGMAKER_PURE_PYTHON=1 python -m unittest discover -s tests   # force the Python engine
```

The tests check move generation against the known node counts for the starting position and
cover mandatory captures, multi-jumps, crowning, and basic search behaviour.

## Build a standalone app

The **Build apps** workflow in `.github/workflows/build.yml` builds Windows, macOS and Linux apps
with PyInstaller. It compiles the C engine on each system and packs it inside the app. Run it from the Actions tab, or push a version tag to attach the files to a release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

## Strength

The engine is an iterative-deepening principal-variation search with alpha-beta pruning, a
transposition table, history ordering, capture extensions and a hand-tuned evaluation.

| Engine | Speed | Depth in 5 s |
| --- | --- | --- |
| C (`native/kingmaker.c`) | about 4 million positions per second | 13 plies |
| Pure Python (`engine.py`) | about 60 thousand positions per second | 9 plies |

Checkers is a draw with perfect play, so no program can promise a win against every opponent.

## Ideas to build on

- Add an opening book or an endgame database to play the early and late game perfectly.
- Make the C search multi-threaded (Lazy SMP) to use every core.
- Tune the weights in `evaluate()` by playing versions against each other.
- Add draw detection (for example the 40-move rule) and a position import and export format.
