import os
from pathlib import Path

import requests

BASE_PATH = Path(__file__).resolve().parent.parent

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


def read_latest_changes(path=".version"):
    if not Path(BASE_PATH / path).exists():
        return "Изменения недоступны"
    return (
        Path(BASE_PATH / path)
        .read_text(encoding="utf-8")
        .strip()
        .replace("LAST_CHANGES=", "")
    )


def send_message(text):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
    )
    print("Telegram response:", response.text)


if __name__ == "__main__":
    message = "🚀 *Новый релиз каталога*\n"
    message += read_latest_changes()
    send_message(message)
