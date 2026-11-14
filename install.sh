#!/usr/bin/env bash
# Kingmaker installer for Linux and macOS.
# Checks Python and Tkinter, compiles the fast C engine, and creates a ./kingmaker-run launcher.
set -e
cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$1"; }

say "Checking Python"
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/"; exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "Python 3.10+ is required."; exit 1; }
echo "Using $($PY --version)"

say "Checking Tkinter"
if ! "$PY" -c 'import tkinter' 2>/dev/null; then
  echo "Tkinter is missing."
  case "$(uname -s)" in
    Linux)  echo "Install it with:  sudo apt install python3-tk   (Debian/Ubuntu)"
            echo "             or:  sudo dnf install python3-tkinter   (Fedora)";;
    Darwin) echo "Install Python from python.org, or run:  brew install python-tk";;
  esac
  exit 1
fi

say "Building the C engine"
if "$PY" build_native.py; then
  echo "Native engine built."
else
  echo "No C compiler found, so the app will use the slower Python engine."
  echo "For full strength install gcc or clang (Linux: sudo apt install build-essential, macOS: xcode-select --install) and rerun this script."
fi

say "Running tests"
"$PY" -m unittest discover -s tests >/dev/null 2>&1 && echo "All tests passed." || echo "Some tests failed. Run: $PY -m unittest discover -s tests -v"

say "Creating launcher"
printf '#!/usr/bin/env bash\ncd "$(dirname "$0")"\nexec %s run.py\n' "$PY" > kingmaker-run
chmod +x kingmaker-run
echo "Done. Start Kingmaker with:  ./kingmaker-run"
