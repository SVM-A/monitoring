import re


def normalize_message(text: str) -> str:
    # В нижний регистр
    text = text.lower()
    # Заменяем ё на е (если нужен русский текст)
    text = text.replace('ё', 'е')
    # Заменяем разные типы кавычек на обычные
    text = text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    # Убираем не-буквенно-цифровые символы, кроме базовых знаков (если нужно)
    text = re.sub(r'[^\w\s@.,!?-]', '', text)
    # Превращаем все виды пробелов (много пробелов, табы, переводы строк) в один пробел
    text = re.sub(r'\s+', ' ', text)
    # Убираем пробелы по краям
    text = text.strip()
    return text