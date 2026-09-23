import pathlib
import sys

# the modules under test live in the repo root, not in a package
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
