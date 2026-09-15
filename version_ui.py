"""Small UI-only version indicator for the Songpack Maker build."""
from __future__ import annotations

BUILD_VERSION = "v0.1.4.1"


def install(app):
    """Show the current build version on the Help menu."""
    try:
        menu = app.nametowidget(app["menu"])
        help_index = menu.index("Help")
        help_menu_name = menu.entrycget(help_index, "menu")
        help_menu = app.nametowidget(help_menu_name)

        # Keep the existing help action, but make the build version visible
        # directly on the Help menu button.
        menu.entryconfigure(help_index, label=f"Help ({BUILD_VERSION})")
    except Exception:
        # The version indicator is cosmetic; never prevent the application
        # from starting if a platform-specific Tk menu behaves differently.
        pass
