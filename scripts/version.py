# app/utils/version.py
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent.parent


def get_app_version():
    # Определение пути к файлу version.txt в корне проекта
    version_file = BASE_PATH / "version.txt"

    # Чтение текущей версии из файла
    try:
        with open(version_file, "r") as file:
            version = file.read().strip()
            now_version = ".".join(version.split(".")[:3])
            print(f"Current version: {now_version}")
            return now_version

    except FileNotFoundError:
        print(f"Version file not found. Returning default version '1.0.0'.")
        return "1.0.0"
