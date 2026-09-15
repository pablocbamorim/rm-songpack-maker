"""Small UI-only version indicator for the Songpack Maker build."""
from __future__ import annotations

import webbrowser

BUILD_VERSION = "v0.1.4.2"
REPOSITORY_URL = "https://github.com/pablocbamorim/rm-songpack-maker"
README_URL = f"{REPOSITORY_URL}#readme"


def install(app):
    """Show the current build version and project documentation on the Help menu."""
    try:
        menu = app.nametowidget(app["menu"])
        help_index = menu.index("Help")
        help_menu_name = menu.entrycget(help_index, "menu")
        help_menu = app.nametowidget(help_menu_name)

        # Keep the existing help action, but make the build version visible
        # directly on the Help menu button.
        menu.entryconfigure(help_index, label=f"Help ({BUILD_VERSION})")

        help_menu.add_separator()
        help_menu.add_command(
            label="README / Documentation",
            command=lambda: webbrowser.open(README_URL),
        )
        help_menu.add_command(
            label="GitHub Repository",
            command=lambda: webbrowser.open(REPOSITORY_URL),
        )
    except Exception:
        # The version indicator and external links are cosmetic; never prevent
        # the application from starting if a platform-specific Tk menu behaves differently.
        pass
