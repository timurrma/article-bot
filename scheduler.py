"""
Планировщик ежедневной отправки выжимки.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import ALLOWED_USER_ID, TIMEZONE
import database as db

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))


async def send_daily_digest(bot):
    """Основная задача — вызывается по расписанию."""
    from delivery import deliver_digest
    await deliver_digest(bot, ALLOWED_USER_ID)


def start_scheduler(bot, delivery_time: str):
    """Запускает планировщик с заданным временем HH:MM."""
    hour, minute = map(int, delivery_time.split(":"))

    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=pytz.timezone(TIMEZONE)),
        args=[bot],
        id="daily_digest",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()

    logger.info(f"Планировщик запущен: {delivery_time} {TIMEZONE}")


def reschedule(bot, new_time: str):
    """Перепланировать на новое время."""
    start_scheduler(bot, new_time)
