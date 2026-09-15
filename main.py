#!/usr/bin/env python3
"""Entry point for the ReactiveMusic Songpack Editor."""
import os
import sys

try:
    import app
    import ui_enhancements
    import biome_customization
    import version_ui
except ImportError as exc:
    if "tkinter" in str(exc).lower():
        print("This program needs Python's 'tkinter' GUI library.",
              file=sys.stderr)
        sys.exit(1)
    raise


def _set_window_icon(application):
    """Use the project icon for the Tk window in both source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    icon_path = os.path.join(base_dir, "assets", "SoundpackMaker.ico")
    if os.path.exists(icon_path):
        try:
            application.iconbitmap(default=icon_path)
        except Exception:
            pass


def main():
    application = app.App()
    _set_window_icon(application)
    ui_enhancements.install(application)
    biome_customization.install(application)
    version_ui.install(application)
    application.mainloop()


if __name__ == "__main__":
    main()
