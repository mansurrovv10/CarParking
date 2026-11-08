import re


REGIONS = {
    "01": "Бишкек",
    "02": "г. Ош",
    "03": "Баткенская область",
    "04": "Джалал-Абадская область",
    "05": "Нарынская область",
    "06": "Ошская область",
    "07": "Таласская область",
    "08": "Чуйская область",
    "09": "Иссык-Кульская область",
    "10": "Легализованный автомобиль",
    "11": "Временная регистрация",
}


MODERN_PATTERN = re.compile(
    r"^(0[1-9]|10|11)(\d{3})([A-Z]{3})$"
)


OLD_FIVE_PATTERN = re.compile(r"^(\d{5})([A-Z]{2})$")
OLD_PATTERN = re.compile(r"^([A-Z])(\d{4})([A-Z])$")


def normalize_plate(text: str) -> str:
    """
    Удаляет пробелы и посторонние символы.

    Например:
    '01 506 AVD' -> '01506AVD'
    """
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def parse_plate(texts: str | list[str]) -> dict | None:
    """
    Проверяет номер и определяет регион.

    Принимает:
        str       - результат FastPlateOCR
        list[str] - фрагменты OCR

    Возвращает:
        словарь с данными номера или None.
    """

    # 1. Приводим вход к одному формату
    if isinstance(texts, str):
        texts = [texts]

    parts = []

    # 2. Очищаем OCR-текст
    for text in texts:
        token = normalize_plate(text)

        # Пропускаем обозначение страны
        if token == "KG":
            continue

        # Убираем KG перед номером или регионом
        if token.startswith("KG"):
            remaining = token[2:]

            if remaining in REGIONS or MODERN_PATTERN.fullmatch(remaining):
                token = remaining

        if token:
            parts.append(token)

    if not parts:
        return None

    # 3. Собираем возможные варианты
    joined = "".join(parts)
    candidates = [joined]

    # Убираем KG между кодом региона и номером
    without_kg = re.sub(
        r"^((?:0[1-9]|10|11))KG(?=\d{3}[A-Z]{3}$)",
        r"\1",
        joined
    )
    candidates.append(without_kg)


    for code in parts:
        if code in REGIONS:
            rest = parts.copy()
            rest.remove(code)
            candidates.append(code + "".join(rest))


    for code in REGIONS:
        if joined.endswith(code) and len(joined) > 2:
            candidates.append(code + joined[:-2])

    for candidate in dict.fromkeys(candidates):

        modern = MODERN_PATTERN.fullmatch(candidate)

        if modern:
            code, digits, letters = modern.groups()

            return {
                "plate_number": code + digits + letters,
                "country": "KG",
                "region_code": code,
                "region": REGIONS[code]
            }

        old_five = OLD_FIVE_PATTERN.fullmatch(candidate)

        if old_five:
            return {
                "plate_number": candidate,
                "country": "KG",
                "region_code": None,
                "region": None
            }

        old = OLD_PATTERN.fullmatch(candidate)

        if old:
            return {
                "plate_number": candidate,
                "country": "KG",
                "region_code": None,
                "region": None
            }


    return None
