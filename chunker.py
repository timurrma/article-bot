"""
Нарезает текст на чанки ~750 слов.
Никогда не обрывается на середине абзаца.
"""
from config import CHUNK_SIZE_WORDS


def _split_paragraphs(text: str) -> list[str]:
    """Разбивает текст на абзацы по двойным переносам строк."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paragraphs


def get_chunk(text: str, char_offset: int) -> tuple[str, int, int]:
    """
    Возвращает (chunk_text, new_offset, total_chars).

    - Начинает с char_offset
    - Набирает ~CHUNK_SIZE_WORDS слов
    - Добивает до конца абзаца
    - Возвращает новый offset (конец чанка)
    """
    total_chars = len(text)

    if char_offset >= total_chars:
        return "", total_chars, total_chars

    remaining = text[char_offset:]
    paragraphs = _split_paragraphs(remaining)

    if not paragraphs:
        return "", total_chars, total_chars

    chunk_paragraphs = []
    word_count = 0

    for para in paragraphs:
        chunk_paragraphs.append(para)
        word_count += len(para.split())

        if word_count >= CHUNK_SIZE_WORDS:
            break

    chunk_text = "\n\n".join(chunk_paragraphs)

    # Вычисляем новый offset — ищем конец чанка в исходном тексте
    chunk_end_in_remaining = remaining.find(chunk_paragraphs[-1]) + len(chunk_paragraphs[-1])
    new_offset = char_offset + chunk_end_in_remaining

    # Пропускаем пробелы и переносы между абзацами
    while new_offset < total_chars and text[new_offset] in ("\n", " "):
        new_offset += 1

    return chunk_text, new_offset, total_chars


def count_chunks(text: str) -> int:
    """Подсчёт общего количества чанков в тексте."""
    offset = 0
    count = 0
    total = len(text)
    while offset < total:
        _, offset, _ = get_chunk(text, offset)
        count += 1
        if count > 10000:  # защита от бесконечного цикла
            break
    return count


def current_chunk_number(text: str, char_offset: int) -> int:
    """Номер текущего чанка (1-based)."""
    offset = 0
    count = 1
    total = len(text)
    while offset < total and offset < char_offset:
        _, offset, _ = get_chunk(text, offset)
        if offset <= char_offset:
            count += 1
    return count
