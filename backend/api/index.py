import os
import sys

# Make the "app" package importable (backend/ is the project root on Vercel)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app  # noqa: E402,F401
