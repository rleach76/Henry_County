import asyncio
import os
import logging
from urllib.parse import urlparse
from PIL import Image
import pytesseract
from io import BytesIO
from pdfminer.high_level import extract_text as extract_pdf_text
import docx2txt
from playwright.async_api import Response

from . import config
from . import database

async def perform_ocr(image_bytes: bytes) -> str:
    """Performs OCR on a given image's bytes and returns the text."""
    try:
        image = Image.open(BytesIO(image_bytes))
        text = pytesseract.image_to_string(image)
        logging.info("OCR performed successfully on image.")
        return text
    except Exception as e:
        logging.error(f"OCR failed: {e}")
        return ""

async def process_response(response: Response, county_name: str):
    """
    Checks a Playwright response object, processes it based on content type, and saves to DB.
    Now includes county_name for data partitioning.
    """
    url = response.url
    db_conn = None
    try:
        content_type = (response.headers.get("content-type") or "").lower().split(';')[0]
        if not response.ok: return "skipped_bad_status"

        is_allowed_mime = content_type in config.MIME_TYPE_ALLOWLIST
        is_ocr_mime = content_type in config.OCR_MIME_TYPES
        if not is_allowed_mime and not is_ocr_mime: return "skipped_mime"

        body = await response.body()
        if len(body) > config.MAX_FILE_SIZE_BYTES: return "skipped_size"

        db_conn = await database.get_db_connection()
        source_site = urlparse(url).netloc

        if is_allowed_mime:
            text_content, status = "", "processed_text"
            if "html" in content_type or "text" in content_type:
                text_content = body.decode('utf-8', errors='ignore')
            elif "pdf" in content_type:
                try:
                    text_content = extract_pdf_text(BytesIO(body))
                    status = "processed_pdf"
                except Exception as e: status = "pdf_extraction_failed"
            elif "word" in content_type:
                try:
                    text_content = docx2txt.process(BytesIO(body))
                    status = "processed_docx"
                except Exception as e: status = "docx_extraction_failed"

            await db_conn.execute(
                """
                INSERT INTO scraped_pages (county_name, url, source_site, content_type, status, text_content)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (url) DO UPDATE SET
                    county_name = EXCLUDED.county_name, text_content = EXCLUDED.text_content, timestamp = NOW()
                """,
                county_name, url, source_site, content_type, status, text_content
            )
            logging.info(f"[{county_name}] Saved text content for {url}")

        elif is_ocr_mime:
            ocr_text = await perform_ocr(body)
            filename = os.path.basename(urlparse(url).path) or f"{source_site.replace('.', '_')}_image.png"
            filepath = os.path.join(config.DOWNLOAD_DIR, county_name, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f: f.write(body)

            page_id = await db_conn.fetchval(
                """
                INSERT INTO scraped_pages (county_name, url, source_site, content_type, status)
                VALUES ($1, $2, $3, $4, 'downloaded_ocr')
                ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, timestamp = NOW()
                RETURNING id
                """,
                county_name, url, source_site, content_type
            )
            await db_conn.execute(
                "INSERT INTO downloaded_documents (county_name, page_id, filepath, file_type, ocr_text) VALUES ($1, $2, $3, $4, $5)",
                county_name, page_id, filepath, content_type, ocr_text
            )
            logging.info(f"[{county_name}] Saved image {filepath} and OCR text")

        return "processed"

    except Exception as e:
        logging.error(f"An unexpected error occurred while processing {url}: {e}")
        return "processing_error"
    finally:
        if db_conn: await db_conn.close()
