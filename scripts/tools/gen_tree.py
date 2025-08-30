# app/README/gen_tree.py

import os
from pathlib import Path


def get_readable_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024


def generate_folder_structure(path, skipping, out_file):
    structure = [
        "Mode            Length Hierarchy\n",
        "----            ------ ---------\n",
    ]

    for root, dirs, files in os.walk(path):
        # Удаляем исключенные папки из обхода
        dirs[:] = [d for d in dirs if d not in skipping]

        level = root.replace(str(path), "").count(os.sep)
        indent = " " * 4 * level

        # Вычисляем размер файлов в текущей директории
        dir_size = sum(os.path.getsize(os.path.join(root, file)) for file in files)
        structure.append(
            f"d----       {get_readable_size(dir_size):>10} {indent}{os.path.basename(root)}\n"
        )

        sub_indent = " " * 4 * (level + 1)
        for file in files:
            file_path = os.path.join(root, file)
            file_size = get_readable_size(os.path.getsize(file_path))
            structure.append(f"-a---       {file_size:>10} {sub_indent}├── {file}\n")

    # Записываем структуру в файл
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("".join(structure))
    print(f"Дерево проекта обновлено в {out_file}")


if __name__ == "__main__":
    base_path = Path(__file__).resolve().parent.parent.parent
    exclusions = [
        ".venv",
        ".git",
        ".idea",
        "__pycache__",
        ".github",
        "photos",
        "logs",
        ".mypy_cache",
        "imgs",
    ]
    output_file = "tree_for_readme.txt"
    generate_folder_structure(base_path, exclusions, output_file)
