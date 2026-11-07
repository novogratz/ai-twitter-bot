#!/usr/bin/env python3
"""Independent SI news draft worker; running this never starts the X bot."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import settings
settings.load()
from src.news.cli import main

if __name__ == "__main__":
    main()
