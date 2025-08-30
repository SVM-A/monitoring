import re
from pathlib import Path


base_path = Path(__file__).resolve().parent.parent.parent

# Какие расширения считать как исходный код
all_code_extensions = [
    ".py", ".js", ".ts", ".html", ".css", ".scss", ".sh",
    ".yml", ".yaml", ".json", ".md", ".txt"
]

# Директории, которые игнорируем
excluded_dirs = {
    ".venv", ".git", ".idea", "__pycache__", ".github", "photos",
    "logs", ".mypy_cache", "imgs", ".vscode", "env", "ENV",
    "node_modules", "frontend/node_modules", "frontend/dist"
}

# Расширения и паттерны файлов, которые игнорируем
excluded_file_suffixes = {
    ".egg-info", ".bak", ".swp", ".DS_Store", ".pyc", ".pyo", ".pyd",
    ".sqlite3", ".log", ".tar"
}


def is_valid_file(f: Path, extensions: list[str]) -> bool:
    if not f.is_file() or not f.exists():
        return False
    if any(part in excluded_dirs for part in f.parts):
        return False
    if f.suffix in excluded_file_suffixes:
        return False
    return f.suffix in extensions


def count_lines(extensions: list[str], label: str) -> int:
    total = 0
    for f in base_path.rglob("*"):
        if not is_valid_file(f, extensions):
            continue

        count = 0
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "//", '"', "'")):
                    continue
                count += 1

            print(f"{f} - {count} строк ({label})")
            total += count
        except UnicodeDecodeError:
            print(f"Ошибка декодирования файла: {f}")

    print(f"ИТОГО {label}: {total}")
    return total


def update_readme(py_lines: int, all_lines: int):
    readme_path = base_path / "README.md"
    if not readme_path.exists():
        print("Файл README.md не найден.")
        return

    try:
        content = readme_path.read_text(encoding="utf-8")

        content, py_count = re.subn(
            r"Общее количество строк python кода в проекте: \d+",
            f"Общее количество строк python кода в проекте: {py_lines}",
            content
        )
        content, all_count = re.subn(
            r"Общее количество строк кода в проекте: \d+",
            f"Общее количество строк кода в проекте: {all_lines}",
            content
        )

        if py_count + all_count == 0:
            print("Строки со счётчиками не найдены.")
        else:
            readme_path.write_text(content, encoding="utf-8")
            print("README.md успешно обновлён.")

    except Exception as e:
        print(f"Ошибка при обновлении README.md: {e}")


if __name__ == "__main__":
    python_lines = count_lines([".py"], label="Python")
    total_lines = count_lines(all_code_extensions, label="All")
    update_readme(python_lines, total_lines)
