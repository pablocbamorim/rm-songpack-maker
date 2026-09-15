"""Compatibility entry point for the ReactiveMusic Songpack Editor."""

from app_core import *  # noqa: F401,F403 - preserve the historical app.py API

import biome_customization


def main():
    # Keep app.py as a fully supported entry point.  The customization layer
    # must be installed before App() constructs its widgets and File menu.
    biome_customization.install()
    application = App()
    application.mainloop()


if __name__ == "__main__":
    main()
