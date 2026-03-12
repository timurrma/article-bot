"""
Генерация выжимки и Q&A через OpenAI API.
"""
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

DEFAULT_SUMMARY_SYSTEM = """Ты — интеллектуальный ассистент для глубокого анализа текстов.
Твоя задача — создавать образовательные, содержательные выжимки, а не поверхностный пересказ.

Требования:
- Ключевые тезисы должны быть самодостаточными — понятными без прочтения оригинала
- Цитаты выбирай самые ёмкие и показательные
- Вывод должен давать инсайт, а не просто резюмировать
- Пиши на русском языке, даже если текст на английском
"""

DEFAULT_SUMMARY_USER = """Вот фрагмент из материала «{title}» (часть {chunk_num} из {total_chunks}):

---
{chunk_text}
---

Создай выжимку строго в этом формате (используй именно эти заголовки):

📝 Краткое содержание
[тут основное краткое содержание. Не сильно укороченное чтобы передать весь смысл + если это уместно то цитату]


🧠 ЧТО СТОИТ ЗАПОМНИТЬ
[1-2 предложения: главный инсайт или практический вывод]
"""

QA_SYSTEM_PROMPT = """Ты — умный ассистент. Отвечай развёрнуто и по существу.
Сейчас пользователь читает материал на тему: «{topic}».
Отвечай на основе своих знаний. Если вопрос не связан с темой — всё равно отвечай полезно.
Пиши на русском языке."""


async def _get_prompts() -> tuple[str, str]:
    """Возвращает (system_prompt, user_prompt) из базы или дефолтные."""
    import database as db
    system = await db.get_setting("prompt_system")
    user = await db.get_setting("prompt_user")
    return (system or DEFAULT_SUMMARY_SYSTEM), (user or DEFAULT_SUMMARY_USER)


async def generate_summary(
    chunk_text: str,
    title: str,
    chunk_num: int,
    total_chunks: int,
) -> str:
    system_prompt, user_prompt_template = await _get_prompts()
    user_prompt = user_prompt_template.format(
        title=title,
        chunk_num=chunk_num,
        total_chunks=total_chunks,
        chunk_text=chunk_text,
    )

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=90.0,
    )

    return response.choices[0].message.content.strip()


async def answer_question(question: str, current_topic: str = "") -> str:
    system = QA_SYSTEM_PROMPT.format(topic=current_topic or "общая тема")

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        timeout=60.0,
    )

    return response.choices[0].message.content.strip()
