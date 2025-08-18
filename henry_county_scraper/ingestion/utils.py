import asyncio
import os
import logging
import aiohttp
from urllib.parse import urlparse
from PIL import Image
import pytesseract
from io import BytesIO
from pdfminer.high_level import extract_text as extract_pdf_text
import docx2txt

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

async def download_and_process_file(url: str, county_name: str):
    """
    Directly downloads a file from a URL and processes it based on MIME type.
    This is used for non-HTML files like PDFs, DOCX, and images found in links.
    """
    db_conn = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as response:
                if response.status != 200:
                    logging.warning(f"[{county_name}] Direct download failed for {url} with status {response.status}")
                    return

                content_type = response.headers.get("content-type", "").lower().split(';')[0]
                body = await response.read()

                if len(body) > config.MAX_FILE_SIZE_BYTES:
                    logging.warning(f"[{county_name}] Skipped downloaded file {url} due to size.")
                    return

                is_allowed_mime = content_type in config.MIME_TYPE_ALLOWLIST
                is_ocr_mime = content_type in config.OCR_MIME_TYPES

                if not is_allowed_mime and not is_ocr_mime:
                    logging.info(f"[{county_name}] Skipping downloaded file {url} with MIME type '{content_type}'")
                    return

                db_conn = await database.get_db_connection()
                source_site = urlparse(url).netloc

                if is_allowed_mime:
                    text_content, status = "", "processed_text"
                    if "pdf" in content_type:
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
                        ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, text_content = EXCLUDED.text_content, timestamp = NOW()
                        """,
                        county_name, url, source_site, content_type, status, text_content
                    )
                    logging.info(f"[{county_name}] Saved text content from direct download {url}")

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
                        ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, timestamp = NOW() RETURNING id
                        """,
                        county_name, url, source_site, content_type
                    )
                    await db_conn.execute(
                        "INSERT INTO downloaded_documents (county_name, page_id, filepath, file_type, ocr_text) VALUES ($1, $2, $3, $4, $5)",
                        county_name, page_id, filepath, content_type, ocr_text
                    )
                    logging.info(f"[{county_name}] Saved image {filepath} from direct download")

    except Exception as e:
        logging.error(f"An unexpected error occurred while directly downloading {url}: {e}")
    finally:
        if db_conn: await db_conn.close()
