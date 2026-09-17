"""Compatibility entry point for the ReactiveMusic Songpack Editor."""

import sys

from app_core import *  # noqa: F401,F403 - preserve the historical app.py API

sys.modules.setdefault("app", sys.modules[__name__])


# CTkTabview creates an internal frame for each tab.  app_core.App creates
# the existing tab classes inside those frames, but CTkTabview does not
# geometry-manage arbitrary child widgets automatically.  Keep the original
# App implementation intact and make the compatibility entry point ensure
# each tab fills its CTkTabview container.
_BaseApp = App


class App(_BaseApp):
    def __init__(self):
        super().__init__()
        for tab in (
            self.info_tab,
            self.library_tab,
            self.priority_tab,
            self.settings_tab,
        ):
            tab.pack(fill="both", expand=True)


def main():
    # Biome customization (custom biomes/tags + colors) is built directly
    # into App/LibraryTab in app_core.py -- no separate install step needed.
    application = App()
    application.mainloop()


if __name__ == "__main__":
    main()
