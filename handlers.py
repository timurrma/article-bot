"""
Все хэндлеры команд и сообщений бота.
"""
import re
import logging

from aiogram import Router, F
from aiogram.filters import Command, Filter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

import database as db
from readers import read_source, ReaderError
from delivery import deliver_digest
from ai import answer_question
from scheduler import reschedule
from config import ALLOWED_USER_ID

logger = logging.getLogger(__name__)
router = Router()


class IsOwner(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == ALLOWED_USER_ID


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(Command("start"), IsOwner())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я буду присылать тебе ежедневные выжимки из статей и книг.\n\n"
        "Команды:\n"
        "/add <ссылка> — добавить материал\n"
        "/queue — очередь и прогресс\n"
        "/now — получить выжимку прямо сейчас\n"
        "/skip — пропустить текущий чанк\n"
        "/pause / /resume — пауза\n"
        "/settings time HH:MM — изменить время доставки\n"
        "/restart\\_doc — начать текущий материал сначала\n"
        "/remove — удалить материал из очереди\n\n"
        "Или просто напиши мне вопрос — отвечу 🤓"
    )


# ─── /add ─────────────────────────────────────────────────────────────────────

@router.message(Command("add"), IsOwner())
async def cmd_add(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].startswith("http"):
        await message.answer("❌ Нужна ссылка. Например:\n/add https://habr.com/ru/articles/...")
        return

    url = parts[1].strip()

    existing = await db.url_in_queue(url)
    if existing:
        queue = await db.get_queue()
        pos = next((i + 1 for i, item in enumerate(queue) if item["id"] == existing["id"]), "?")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, добавить ещё раз", callback_data=f"add_dup:{url}"),
                InlineKeyboardButton(text="Нет", callback_data="add_dup:cancel"),
            ]
        ])
        await message.answer(
            f"Этот материал уже есть в очереди (позиция {pos}).\nДобавить повторно?",
            reply_markup=keyboard
        )
        return

    await _do_add(message, url)


@router.callback_query(F.data.startswith("add_dup:"))
async def callback_add_dup(callback: CallbackQuery):
    if callback.from_user.id != ALLOWED_USER_ID:
        return
    data = callback.data[len("add_dup:"):]
    if data == "cancel":
        await callback.message.edit_text("Ок, не добавляю.")
        return
    await callback.message.edit_text("⏳ Добавляю...")
    await _do_add(callback.message, data)


async def _do_add(message: Message, url: str):
    await message.answer("⏳ Проверяю ссылку...")
    try:
        title, text = await read_source(url)
        if not text.strip():
            await message.answer("❌ Текст не найден. Попробуй другую ссылку.")
            return
    except ReaderError as e:
        await message.answer(f"❌ Не могу прочитать: {e}")
        return

    await db.add_to_queue(url, title)
    queue = await db.get_queue()
    pos = len(queue)
    await message.answer(
        f"✅ Добавлено на позицию {pos}:\n*{title}*\n\n"
        f"Слов в материале: ~{len(text.split()):,}",
        parse_mode="Markdown"
    )


# ─── /queue ───────────────────────────────────────────────────────────────────

@router.message(Command("queue"), IsOwner())
async def cmd_queue(message: Message):
    queue = await db.get_queue()
    if not queue:
        await message.answer("📭 Очередь пуста. Добавь материал через /add")
        return

    lines = ["📚 *Очередь:*\n"]
    for i, item in enumerate(queue):
        title = item["title"] or item["url"]
        if item["total_chars"] > 0:
            pct = int(item["char_offset"] / item["total_chars"] * 100)
            progress = f"{pct}%"
        else:
            progress = "не начат"
        marker = "▶️" if i == 0 else f"{i + 1}."
        lines.append(f"{marker} *{title}* — {progress}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /now ─────────────────────────────────────────────────────────────────────

@router.message(Command("now"), IsOwner())
async def cmd_now(message: Message):
    await message.answer("⏳ Генерирую выжимку...")
    await deliver_digest(message.bot, message.chat.id)


# ─── /skip ────────────────────────────────────────────────────────────────────

@router.message(Command("skip"), IsOwner())
async def cmd_skip(message: Message):
    item = await db.get_current_item()
    if not item:
        await message.answer("📭 Очередь пуста.")
        return

    try:
        _, text = await read_source(item["url"])
    except ReaderError as e:
        await message.answer(f"❌ Не могу прочитать источник: {e}")
        return

    from chunker import get_chunk
    _, new_offset, total = get_chunk(text, item["char_offset"])
    await db.update_offset(item["id"], new_offset, total)
    await message.answer("⏭ Чанк пропущен. Завтра придёт следующий.")


# ─── /pause / /resume ─────────────────────────────────────────────────────────

@router.message(Command("pause"), IsOwner())
async def cmd_pause(message: Message):
    await db.set_setting("paused", "1")
    await message.answer("⏸ Пауза. Выжимки не будут приходить до /resume")


@router.message(Command("resume"), IsOwner())
async def cmd_resume(message: Message):
    await db.set_setting("paused", "0")
    delivery_time = await db.get_setting("delivery_time")
    await message.answer(f"▶️ Возобновлено. Следующая выжимка в {delivery_time} по Москве.")


# ─── /settings ────────────────────────────────────────────────────────────────

@router.message(Command("settings"), IsOwner())
async def cmd_settings(message: Message):
    parts = message.text.split()
    if len(parts) == 3 and parts[1] == "time":
        new_time = parts[2]
        if not re.match(r"^\d{2}:\d{2}$", new_time):
            await message.answer("❌ Формат: /settings time 09:30")
            return
        await db.set_setting("delivery_time", new_time)
        reschedule(message.bot, new_time)
        await message.answer(f"✅ Время доставки изменено на {new_time} (Москва)")
    else:
        delivery_time = await db.get_setting("delivery_time")
        paused = await db.get_setting("paused")
        status = "⏸ на паузе" if paused == "1" else "▶️ активен"
        await message.answer(
            f"⚙️ *Настройки:*\n"
            f"Время доставки: {delivery_time} (Москва)\n"
            f"Статус: {status}\n\n"
            f"Изменить время: /settings time HH:MM",
            parse_mode="Markdown"
        )


# ─── /restart_doc ─────────────────────────────────────────────────────────────

@router.message(Command("restart_doc"), IsOwner())
async def cmd_restart_doc(message: Message):
    parts = message.text.split()
    if len(parts) > 1 and parts[1] == "all":
        await db.restart_all()
        await message.answer("🔄 Прогресс сброшен для всех материалов.")
        return

    item = await db.get_current_item()
    if not item:
        await message.answer("📭 Очередь пуста.")
        return

    await db.restart_item(item["id"])
    title = item["title"] or item["url"]
    await message.answer(f"🔄 Прогресс по «{title}» сброшен на начало.")


# ─── /finish_doc ──────────────────────────────────────────────────────────────

@router.message(Command("finish_doc"), IsOwner())
async def cmd_finish_doc(message: Message):
    item = await db.get_current_item()
    if not item:
        await message.answer("📭 Очередь пуста.")
        return

    title = item["title"] or item["url"]
    await db.remove_item(item["id"])

    queue = await db.get_queue()
    if queue:
        next_item = queue[0]
        await message.answer(
            f"✅ «{title}» завершён.\n"
            f"Следующий: *{next_item['title'] or next_item['url']}*",
            parse_mode="Markdown"
        )
    else:
        await message.answer(f"✅ «{title}» завершён.\n📭 Очередь пуста.")


# ─── /remove ──────────────────────────────────────────────────────────────────

@router.message(Command("remove"), IsOwner())
async def cmd_remove(message: Message):
    queue = await db.get_queue()
    if not queue:
        await message.answer("📭 Очередь пуста.")
        return

    buttons = []
    for item in queue:
        title = (item["title"] or item["url"])[:40]
        buttons.append([InlineKeyboardButton(
            text=f"❌ {title}",
            callback_data=f"remove:{item['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="remove:cancel")])

    await message.answer(
        "Что удалить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("remove:"))
async def callback_remove(callback: CallbackQuery):
    if callback.from_user.id != ALLOWED_USER_ID:
        return
    data = callback.data[len("remove:"):]
    if data == "cancel":
        await callback.message.edit_text("Отменено.")
        return

    item_id = int(data)
    queue = await db.get_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    title = item["title"] if item else "материал"
    await db.remove_item(item_id)
    await callback.message.edit_text(f"✅ «{title}» удалён из очереди.")


# ─── Получение файла (epub, fb2, pdf) ────────────────────────────────────────

@router.message(F.document, IsOwner())
async def handle_document(message: Message):
    doc = message.document
    name = doc.file_name or ""
    lower = name.lower()

    if not any(lower.endswith(ext) for ext in (".epub", ".fb2", ".zip")):
        await message.answer("❌ Поддерживаются epub, fb2, zip. Для ссылок используй /add <ссылка>")
        return

    await message.answer(f"⏳ Скачиваю «{name}»...")

    import os
    from config import DB_PATH
    books_dir = os.path.join(os.path.dirname(DB_PATH), "books")
    os.makedirs(books_dir, exist_ok=True)
    file_path = os.path.join(books_dir, name)

    file = await message.bot.get_file(doc.file_id)
    await message.bot.download_file(file.file_path, destination=file_path)

    # Если zip — распаковываем и ищем epub/fb2
    if lower.endswith(".zip"):
        import zipfile
        extract_dir = file_path.replace(".zip", "_extracted")
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(extract_dir)
        # Ищем первый epub или fb2
        found = None
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.lower().endswith((".epub", ".fb2")):
                    found = os.path.join(root, f)
                    break
            if found:
                break
        if not found:
            await message.answer("❌ В zip не найден epub или fb2 файл.")
            return
        file_path = found

    from readers import read_local_file, ReaderError
    try:
        title, text = read_local_file(file_path)
        if not text.strip():
            await message.answer("❌ Файл не содержит текста.")
            return
    except ReaderError as e:
        await message.answer(f"❌ Не могу прочитать файл: {e}")
        return

    await db.add_to_queue(file_path, title)
    queue = await db.get_queue()
    pos = len(queue)
    await message.answer(
        f"✅ Добавлено на позицию {pos}:\n*{title}*\n\n"
        f"Слов в материале: ~{len(text.split()):,}",
        parse_mode="Markdown"
    )


# ─── Q&A — любое сообщение ────────────────────────────────────────────────────

@router.message(F.text, IsOwner())
async def handle_question(message: Message):
    item = await db.get_current_item()
    topic = item["title"] if item else ""

    await message.answer("🤔 Думаю...")
    try:
        answer = await answer_question(message.text, topic)
        await message.answer(answer)
    except Exception as e:
        logger.error(f"Ошибка Q&A: {e}")
        await message.answer("⚠️ Не смог ответить. Попробуй ещё раз.")
