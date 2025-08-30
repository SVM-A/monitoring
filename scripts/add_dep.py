import sys
from pathlib import Path

import tomlkit

BASE_PATH = Path(__file__).resolve().parent.parent

def add_dep(package: str, version: str):
    file_path = Path(BASE_PATH / "pyproject.toml")
    doc = tomlkit.parse(file_path.read_text(encoding="utf-8"))

    deps = doc["project"]["dependencies"]
    new_entry = f"{package}>={version}"

    if not any(
        dep.startswith(f"{package}>=") or dep.startswith(f"{package}==") for dep in deps
    ):
        deps.append(new_entry)
        file_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        print(f"[✓] Added to dependencies: {new_entry}")
    else:
        print(f"[=] Already in dependencies: {package}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python add_dep.py <package> <version>")
        sys.exit(1)
    add_dep(sys.argv[1], sys.argv[2])
