"""
Читает текст из разных источников по URL.
Возвращает (title, full_text) или бросает ReaderError.
"""
import io
import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from config import GOOGLE_CREDENTIALS_JSON


class ReaderError(Exception):
    pass


def _is_google_docs(url: str) -> bool:
    return "docs.google.com/document" in url


def _is_google_drive(url: str) -> bool:
    return "drive.google.com" in url


def _is_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


def _get_google_creds():
    if not GOOGLE_CREDENTIALS_JSON:
        raise ReaderError("GOOGLE_CREDENTIALS_JSON не задан в .env")
    try:
        from google.oauth2 import service_account
        info = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/documents.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as e:
        raise ReaderError(f"Ошибка Google credentials: {e}")


def _extract_doc_id(url: str) -> str:
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ReaderError("Не могу извлечь doc_id из ссылки Google Docs")
    return match.group(1)


def _extract_drive_id(url: str) -> str:
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        match = re.search(r"id=([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ReaderError("Не могу извлечь file_id из ссылки Google Drive")
    return match.group(1)


async def read_google_docs(url: str) -> tuple[str, str]:
    from googleapiclient.discovery import build

    creds = _get_google_creds()
    doc_id = _extract_doc_id(url)

    try:
        service = build("docs", "v1", credentials=creds)
        doc = service.documents().get(documentId=doc_id).execute()
    except Exception as e:
        raise ReaderError(f"Ошибка Google Docs API: {e}")

    title = doc.get("title", "Без названия")
    content = doc.get("body", {}).get("content", [])

    paragraphs = []
    for element in content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        text = ""
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if text_run:
                text += text_run.get("content", "")
        text = text.strip()
        if text:
            paragraphs.append(text)

    return title, "\n\n".join(paragraphs)


async def read_google_drive_pdf(url: str) -> tuple[str, str]:
    import fitz  # PyMuPDF
    from googleapiclient.discovery import build

    creds = _get_google_creds()
    file_id = _extract_drive_id(url)

    try:
        service = build("drive", "v3", credentials=creds)
        meta = service.files().get(fileId=file_id, fields="name").execute()
        title = meta.get("name", "Без названия")
        request = service.files().get_media(fileId=file_id)
        content = request.execute()
    except Exception as e:
        raise ReaderError(f"Ошибка Google Drive API: {e}")

    return title, _extract_pdf_text(content)


async def read_pdf_url(url: str) -> tuple[str, str]:
    import fitz  # PyMuPDF

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content
    except Exception as e:
        raise ReaderError(f"Не могу скачать PDF: {e}")

    title = urlparse(url).path.split("/")[-1].replace(".pdf", "") or "PDF документ"
    return title, _extract_pdf_text(content)


def _extract_pdf_text(content: bytes) -> str:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        text = "\n\n".join(pages)
        if not text.strip():
            raise ReaderError("PDF не содержит текста (возможно, это сканы)")
        return text
    except ReaderError:
        raise
    except Exception as e:
        raise ReaderError(f"Ошибка парсинга PDF: {e}")


async def read_web_page(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        raise ReaderError(f"Не могу загрузить страницу: {e}")

    soup = BeautifulSoup(html, "html.parser")

    # Заголовок
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else urlparse(url).netloc

    # Убираем мусор
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
        tag.decompose()

    # Ищем основной контент — article, main, или просто body
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if not main:
        raise ReaderError("Не могу найти основной текст на странице")

    paragraphs = []
    for p in main.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        text = p.get_text(separator=" ", strip=True)
        if len(text) > 40:  # фильтруем короткий мусор
            paragraphs.append(text)

    if not paragraphs:
        raise ReaderError("На странице не найден читаемый текст")

    return title, "\n\n".join(paragraphs)


def read_epub_file(path: str) -> tuple[str, str]:
    """Читает epub файл с диска."""
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup as BS

        book = epub.read_epub(path)
        title = book.get_metadata("DC", "title")
        title = title[0][0] if title else path.split("/")[-1].replace(".epub", "")

        chapters = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BS(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > 100:
                chapters.append(text)

        if not chapters:
            raise ReaderError("Epub не содержит читаемого текста")

        return title, "\n\n".join(chapters)
    except ReaderError:
        raise
    except Exception as e:
        raise ReaderError(f"Ошибка чтения epub: {e}")


def read_fb2_file(path: str) -> tuple[str, str]:
    """Читает fb2 файл с диска."""
    try:
        from bs4 import BeautifulSoup as BS

        with open(path, "rb") as f:
            content = f.read()

        soup = BS(content, "xml")
        title_tag = soup.find("book-title")
        title = title_tag.get_text(strip=True) if title_tag else path.split("/")[-1].replace(".fb2", "")

        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(separator=" ", strip=True)
            if len(text) > 40:
                paragraphs.append(text)

        if not paragraphs:
            raise ReaderError("FB2 не содержит читаемого текста")

        return title, "\n\n".join(paragraphs)
    except ReaderError:
        raise
    except Exception as e:
        raise ReaderError(f"Ошибка чтения fb2: {e}")


def read_local_file(path: str) -> tuple[str, str]:
    """Читает локальный файл по расширению."""
    lower = path.lower()
    if lower.endswith(".epub"):
        return read_epub_file(path)
    elif lower.endswith(".fb2"):
        return read_fb2_file(path)
    elif lower.endswith(".pdf"):
        with open(path, "rb") as f:
            content = f.read()
        title = path.split("/")[-1].replace(".pdf", "")
        return title, _extract_pdf_text(content)
    else:
        raise ReaderError(f"Неподдерживаемый формат файла")


async def read_source(url: str) -> tuple[str, str]:
    """Определяет тип источника и возвращает (title, text)."""
    # Локальный файл (сохранённый от пользователя)
    if url.startswith("/"):
        return read_local_file(url)
    elif _is_google_docs(url):
        return await read_google_docs(url)
    elif _is_google_drive(url):
        return await read_google_drive_pdf(url)
    elif _is_pdf_url(url):
        return await read_pdf_url(url)
    else:
        return await read_web_page(url)
