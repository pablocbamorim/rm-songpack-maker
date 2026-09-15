"""Compatibility entry point for the ReactiveMusic Songpack Editor."""

import sys

from app_core import *  # noqa: F401,F403 - preserve the historical app.py API

# When app.py is executed directly, Python names it __main__.  The biome
# customization module imports the application as "app", so expose this
# exact module object under that name instead of loading app.py a second time.
sys.modules.setdefault("app", sys.modules[__name__])

import biome_customization


def main():
    # Keep app.py as a fully supported entry point.  The customization layer
    # must be installed before App() constructs its widgets and File menu.
    biome_customization.install()
    application = App()
    application.mainloop()


if __name__ == "__main__":
    main()
