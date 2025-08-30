import random
import re
import secrets
import string

# Популярные типы сервисов (можно расширять)
SERVICE_TYPES = [
    "postgresql",  # Реляционная БД
    "mongodb",  # Документно-ориентированная БД
    "redis",  # In-memory cache, pub/sub
    "minio",  # S3-совместимое хранилище
    "rabbitmq",  # Брокер сообщений
    "kafka",  # Стриминг/логирование
    "mysql",  # Альтернатива PostgreSQL
    "elasticsearch",  # Поисковый движок
    "clickhouse",  # Аналитика/OLAP
    "sqlite",  # Простая файловая БД
]


def slugify(name: str) -> str:
    """Преобразует строку в безопасный slug"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())


def generate_service_name(service_type: str, base_name: str) -> str:
    """Генерирует уникальное имя сервиса"""
    slug = slugify(base_name)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{service_type}_{slug}_{suffix}"


def generate_db_name(name: str) -> str:
    """Генерирует безопасное имя базы данных"""
    return slugify(name)


def generate_token(length: int = 64) -> str:
    """Генерирует безопасный токен"""
    return secrets.token_urlsafe(length)


def generate_password(length: int = 16, symbols: bool = True) -> str:
    """Генерирует пароль с или без символов"""
    chars = string.ascii_letters + string.digits
    if symbols:
        chars += "!@#$%^&*()-_=+"
    return "".join(secrets.choice(chars) for _ in range(length))


if __name__ == "__main__":
    print("🔧 Генератор имён, паролей и ключей для сервисов")
    print("Выберите тип сервиса (можно ввести номер или название):")

    for idx, name in enumerate(SERVICE_TYPES, 1):
        print(f"{idx}. {name}")

    service_input = input("👉 Введите номер или название сервиса: ").strip().lower()

    # Определим тип сервиса
    if service_input.isdigit():
        index = int(service_input) - 1
        if 0 <= index < len(SERVICE_TYPES):
            service_type = SERVICE_TYPES[index]
        else:
            print("❌ Номер вне диапазона. Завершение.")
            exit(1)
    else:
        service_type = slugify(service_input)  # Позволяем произвольное название

    base_name = input("🔤 Введите имя проекта или модуля (например, catalog): ").strip()
    db_label = input("📂 Введите название базы данных (например, users): ").strip()

    # Генерация значений
    service_name = generate_service_name(service_type, base_name)
    db_name = generate_db_name(db_label)
    token = generate_token()
    short_token = generate_token(32)
    strong_pass = generate_password(20)
    compatible_pass = generate_password(16, symbols=False)

    print("\n✅ Результаты генерации:")
    print(f"🔹 Имя сервиса:           {service_name}")
    print(f"🔹 Имя базы данных:       {db_name}")
    print(f"🔐 Токен (длинный, 64+):  {token}")
    print(f"🔐 Токен (короткий, 32):  {short_token}")
    print(f"🔑 Пароль (надёжный):     {strong_pass}")
    print(f"🔑 Пароль (без символов): {compatible_pass}")
