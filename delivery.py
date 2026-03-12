"""
Логика доставки выжимки — вынесена отдельно, чтобы использовать и из scheduler, и из /now.
"""
import logging

import database as db
from readers import read_source, ReaderError
from chunker import get_chunk, count_chunks, current_chunk_number
from ai import generate_summary
from config import ALLOWED_USER_ID

logger = logging.getLogger(__name__)


async def deliver_digest(bot, chat_id: int):
    paused = await db.get_setting("paused")
    if paused == "1":
        return

    item = await db.get_current_item()
    if not item:
        return  # очередь пуста, молчим

    # Читаем источник
    try:
        title, full_text = await read_source(item["url"])
    except ReaderError as e:
        await bot.send_message(
            chat_id,
            f"⚠️ Не могу прочитать «{item['title'] or item['url']}».\n"
            f"Причина: {e}\n\n"
            f"Проверь доступ и попробуй /now"
        )
        return

    total_chars = len(full_text)

    # Проверка: offset больше длины текста (документ стал короче)
    if item["char_offset"] > total_chars:
        await bot.send_message(
            chat_id,
            f"⚠️ «{title}» стал короче чем был (возможно, документ изменился).\n"
            f"Начать сначала? /restart_doc\n"
            f"Или завершить и перейти к следующему? /finish_doc"
        )
        return

    # Берём чанк
    chunk_text, new_offset, _ = get_chunk(full_text, item["char_offset"])

    if not chunk_text:
        # Документ закончился
        await _finish_document(bot, chat_id, item, title)
        return

    # Считаем номера
    total_chunks = count_chunks(full_text)
    chunk_num = current_chunk_number(full_text, item["char_offset"])

    # Генерируем выжимку
    try:
        summary = await generate_summary(chunk_text, title, chunk_num, total_chunks)
    except Exception as e:
        logger.error(f"Ошибка OpenAI: {e}")
        await bot.send_message(
            chat_id,
            "⚠️ Не смог сгенерировать выжимку (ошибка AI). "
            "Попробуй /now или подожди завтра."
        )
        return

    # Сохраняем прогресс
    await db.update_offset(item["id"], new_offset, total_chars)

    # Формируем и отправляем сообщение
    header = f"📖 *{_escape(title)}* — часть {chunk_num}/{total_chunks}\n\n"
    separator = "─────────────────────\n"
    full_message = header + separator + summary

    # Telegram лимит 4096 символов — разбиваем если нужно
    await _send_long_message(bot, chat_id, full_message)

    # Проверяем: если после этого чанка текст закончился
    if new_offset >= total_chars:
        await _finish_document(bot, chat_id, item, title)


async def _finish_document(bot, chat_id: int, item: dict, title: str):
    await db.remove_item(item["id"])

    queue = await db.get_queue()
    if queue:
        next_item = queue[0]
        await bot.send_message(
            chat_id,
            f"✅ «{title}» прочитан полностью!\n"
            f"Следующий в очереди: *{_escape(next_item['title'] or next_item['url'])}*",
            parse_mode="Markdown"
        )
    else:
        await bot.send_message(
            chat_id,
            f"✅ «{title}» прочитан полностью!\n\n"
            f"📭 Очередь пуста. Добавь новый материал через /add"
        )


async def _send_long_message(bot, chat_id: int, text: str):
    max_len = 4000
    if len(text) <= max_len:
        await bot.send_message(chat_id, text, parse_mode="Markdown")
        return

    # Разбиваем по абзацам
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)

    for part in parts:
        await bot.send_message(chat_id, part, parse_mode="Markdown")


def _escape(text: str) -> str:
    """Экранирует спецсимволы Markdown."""
    for ch in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        text = text.replace(ch, f"\\{ch}")
    return text
