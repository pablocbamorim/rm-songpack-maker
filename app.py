"""Compatibility entry point for the ReactiveMusic Songpack Editor."""

import sys

from app_core import *  # noqa: F401,F403 - preserve the historical app.py API

sys.modules.setdefault("app", sys.modules[__name__])


def main():
    # Biome customization (custom biomes/tags + colors) is built directly
    # into App/LibraryTab in app_core.py -- no separate install step needed.
    application = App()
    application.mainloop()


if __name__ == "__main__":
    main()
