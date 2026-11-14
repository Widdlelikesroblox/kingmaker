"""Compile the C engine into the kingmaker package folder.

    python build_native.py

Needs a C compiler (gcc or clang). On Windows use MinGW-w64 gcc.
"""
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = {"win32": "kingmaker.dll", "darwin": "libkingmaker.dylib"}.get(sys.platform, "libkingmaker.so")


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        print("No C compiler found. Install gcc or clang. The app still works with the slower Python engine.")
        return 1
    out = os.path.join(HERE, "kingmaker", NAME)
    cmd = [cc, "-O3", "-shared", "-o", out, os.path.join(HERE, "native", "kingmaker.c")]
    if sys.platform != "win32":
        cmd.insert(2, "-fPIC")
    if platform.machine().lower() in ("x86_64", "amd64"):
        cmd.insert(2, "-mpopcnt")
    if sys.platform == "darwin":
        cmd += ["-dynamiclib"]
    print(" ".join(cmd))
    r = subprocess.call(cmd)
    print("Built " + out if r == 0 else "Build failed")
    return r


if __name__ == "__main__":
    sys.exit(main())
