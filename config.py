import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
DB_PATH = os.environ.get("DB_PATH", "./bot.db")

OPENAI_MODEL = "gpt-5-mini"
CHUNK_SIZE_WORDS = 750
DELIVERY_TIME = "09:30"  # HH:MM, Europe/Moscow
TIMEZONE = "Europe/Moscow"
