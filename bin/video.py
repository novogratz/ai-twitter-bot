#!/usr/bin/env python3
"""Video administration. `worker` never requests a startup publication."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import settings
settings.load()
from src.video.cli import main

if __name__ == "__main__":
    main()
