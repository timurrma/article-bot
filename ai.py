"""
Генерация выжимки и Q&A через OpenAI API.
"""
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SUMMARY_SYSTEM_PROMPT = """Ты — интеллектуальный ассистент для глубокого анализа текстов.
Твоя задача — создавать образовательные, содержательные выжимки, а не поверхностный пересказ.

Требования:
- Выдели НЕТРИВИАЛЬНЫЕ идеи, а не очевидные факты
- Ключевые тезисы должны быть самодостаточными — понятными без прочтения оригинала
- Цитаты выбирай самые ёмкие и показательные
- Вывод должен давать инсайт, а не просто резюмировать
- Пиши на русском языке, даже если текст на английском
- Не используй шаблонные фразы типа "автор говорит", "в этом разделе рассматривается"
"""

SUMMARY_USER_PROMPT = """Вот фрагмент из материала «{title}» (часть {chunk_num} из {total_chunks}):

---
{chunk_text}
---

Создай выжимку строго в этом формате (используй именно эти заголовки):

📝 О ЧЁМ ЭТОТ КУСОК
[2-3 предложения: о чём этот раздел и почему это важно]

💡 КЛЮЧЕВЫЕ ИДЕИ
• [тезис — конкретный, без воды]
• [тезис]
• [тезис]
[добавь ещё если есть важные идеи]

🗣 ЦИТАТЫ
«[точная цитата из текста]»
«[точная цитата]»

🧠 ЧТО СТОИТ ЗАПОМНИТЬ
[1-2 предложения: главный инсайт или практический вывод]
"""


async def generate_summary(
    chunk_text: str,
    title: str,
    chunk_num: int,
    total_chunks: int,
) -> str:
    user_prompt = SUMMARY_USER_PROMPT.format(
        title=title,
        chunk_num=chunk_num,
        total_chunks=total_chunks,
        chunk_text=chunk_text,
    )

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


QA_SYSTEM_PROMPT = """Ты — умный ассистент. Отвечай развёрнуто и по существу.
Сейчас пользователь читает материал на тему: «{topic}».
Отвечай на основе своих знаний. Если вопрос не связан с темой — всё равно отвечай полезно.
Пиши на русском языке."""


async def answer_question(question: str, current_topic: str = "") -> str:
    system = QA_SYSTEM_PROMPT.format(topic=current_topic or "общая тема")

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()
