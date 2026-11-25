"""Entry point for the Windows build (PyInstaller)."""
import sys

from tarjem.app import main

if __name__ == "__main__":
    sys.exit(main())
