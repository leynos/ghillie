"""Module entry point for `python -m ghillie.cli`."""

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
