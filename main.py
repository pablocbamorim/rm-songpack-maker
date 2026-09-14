#!/usr/bin/env python3
"""Entry point for the ReactiveMusic Songpack Editor."""
import sys

try:
    import app
    import ui_enhancements
except ImportError as exc:
    if "tkinter" in str(exc).lower():
        print("This program needs Python's 'tkinter' GUI library.",
              file=sys.stderr)
        sys.exit(1)
    raise


def main():
    application = app.App()
    ui_enhancements.install(application)
    application.mainloop()


if __name__ == "__main__":
    main()
