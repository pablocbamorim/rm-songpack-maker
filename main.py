#!/usr/bin/env python3
"""
Entry point for the ReactiveMusic Songpack Editor.

Run with:  python3 main.py
"""
import sys


def main():
    try:
        import app
    except ImportError as exc:
        if "tkinter" in str(exc).lower():
            print(
                "This program needs Python's 'tkinter' GUI library, which isn't installed.\n"
                "  Windows / macOS (python.org installer): tkinter is included already --\n"
                "    reinstall Python and make sure 'tcl/tk' is checked.\n"
                "  Debian/Ubuntu: sudo apt install python3-tk\n"
                "  Fedora:        sudo dnf install python3-tkinter\n"
                "  Arch:          sudo pacman -S tk\n",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
    app.main()


if __name__ == "__main__":
    main()
