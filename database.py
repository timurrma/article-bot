import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                char_offset INTEGER NOT NULL DEFAULT 0,
                total_chars INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS offset_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                char_offset INTEGER NOT NULL,
                total_chars INTEGER NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Дефолтные настройки
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('delivery_time', '09:30')
        """)
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('paused', '0')
        """)
        await db.commit()


async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


async def add_to_queue(url: str, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(position) FROM queue WHERE is_active = 1") as cursor:
            row = await cursor.fetchone()
            next_pos = (row[0] or 0) + 1
        async with db.execute(
            "INSERT INTO queue (url, title, position) VALUES (?, ?, ?)",
            (url, title, next_pos)
        ) as cursor:
            return cursor.lastrowid


async def get_queue() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM queue WHERE is_active = 1 ORDER BY position ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_current_item() -> dict | None:
    items = await get_queue()
    return items[0] if items else None


async def url_in_queue(url: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM queue WHERE url = ? AND is_active = 1", (url,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_offset(item_id: int, new_offset: int, total_chars: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # Сохраняем текущий offset в историю перед обновлением
        await db.execute(
            "INSERT INTO offset_history (item_id, char_offset, total_chars) "
            "SELECT id, char_offset, total_chars FROM queue WHERE id = ?",
            (item_id,)
        )
        await db.execute(
            "UPDATE queue SET char_offset = ?, total_chars = ? WHERE id = ?",
            (new_offset, total_chars, item_id)
        )
        # Оставляем только последние 20 записей на материал
        await db.execute(
            "DELETE FROM offset_history WHERE item_id = ? AND id NOT IN "
            "(SELECT id FROM offset_history WHERE item_id = ? ORDER BY id DESC LIMIT 20)",
            (item_id, item_id)
        )
        await db.commit()


async def get_offset_history(item_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM offset_history WHERE item_id = ? ORDER BY id DESC LIMIT 20",
            (item_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def rollback_offset(item_id: int, history_id: int) -> bool:
    """Откатывает offset к указанной записи в истории. Возвращает True если успешно."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT char_offset, total_chars FROM offset_history WHERE id = ? AND item_id = ?",
            (history_id, item_id)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return False
        await db.execute(
            "UPDATE queue SET char_offset = ?, total_chars = ? WHERE id = ?",
            (row["char_offset"], row["total_chars"], item_id)
        )
        # Удаляем записи истории новее этой
        await db.execute(
            "DELETE FROM offset_history WHERE item_id = ? AND id >= ?",
            (item_id, history_id)
        )
        await db.commit()
        return True


async def remove_item(item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE queue SET is_active = 0 WHERE id = ?", (item_id,))
        await db.commit()


async def restart_item(item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE queue SET char_offset = 0 WHERE id = ?", (item_id,)
        )
        await db.commit()


async def restart_all():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE queue SET char_offset = 0 WHERE is_active = 1")
        await db.commit()


async def move_to_front(item_id: int):
    """Переставляет материал на первое место в очереди."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MIN(position) FROM queue WHERE is_active = 1") as cursor:
            row = await cursor.fetchone()
            min_pos = (row[0] or 1) - 1
        await db.execute(
            "UPDATE queue SET position = ? WHERE id = ?",
            (min_pos, item_id)
        )
        await db.commit()
