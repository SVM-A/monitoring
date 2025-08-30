# scripts/update_version.py

import sys
from pathlib import Path


new_version = sys.argv[1]

version_file = Path(__file__).parent.parent / "version.txt"
with open(version_file, "w") as file:
    file.write(new_version)

print(f"Version updated to: {new_version}")
