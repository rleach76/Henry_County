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
from asyncpg.pool import Pool

from . import config

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

async def download_and_process_file(session: aiohttp.ClientSession, pool: Pool, url: str, county_name: str, semaphore: asyncio.Semaphore):
    """
    Directly downloads a file and processes it, using a shared session, connection pool,
    and a semaphore to limit concurrency.
    """
    async with semaphore:
        try:
            # Setting a browser-like User-Agent and disabling SSL verification for problematic sites
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            logging.info(f"[{county_name}] Attempting to download: {url}")
            async with session.get(url, timeout=60, headers=headers, ssl=False) as response:
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
                return

            source_site = urlparse(url).netloc
            async with pool.acquire() as conn:
                if is_allowed_mime:
                    text_content, status = "", "processed_text"
                    if "pdf" in content_type:
                        try: text_content, status = extract_pdf_text(BytesIO(body)), "processed_pdf"
                        except Exception: status = "pdf_extraction_failed"
                    elif "word" in content_type:
                        try: text_content, status = docx2txt.process(BytesIO(body)), "processed_docx"
                        except Exception: status = "docx_extraction_failed"
                    elif "zip" in content_type:
                        import zipfile
                        logging.info(f"[{county_name}] Processing zip file from {url}")
                        # First, record the parent zip file in the documents table
                        page_id = await conn.fetchval(
                            """
                            INSERT INTO scraped_pages (county_name, url, source_site, content_type, status)
                            VALUES ($1, $2, $3, $4, 'downloaded_zip')
                            ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, timestamp = NOW() RETURNING id
                            """,
                            county_name, url, source_site, content_type
                        )
                        await conn.execute(
                            "INSERT INTO downloaded_documents (county_name, page_id, filepath, file_type) VALUES ($1, $2, $3, $4)",
                            county_name, page_id, "in-memory-archive", content_type
                        )
                        # Now, process the contents in memory
                        with zipfile.ZipFile(BytesIO(body)) as zf:
                            for file_info in zf.infolist():
                                if file_info.is_dir(): continue
                                inner_filename = file_info.filename
                                inner_content_text, inner_content_type = "", "unknown"
                                try:
                                    with zf.open(file_info) as inner_file:
                                        inner_body = inner_file.read()
                                        if inner_filename.lower().endswith('.pdf'):
                                            inner_content_text = extract_pdf_text(BytesIO(inner_body))
                                            inner_content_type = "application/pdf"
                                        elif inner_filename.lower().endswith(('.txt', '.csv', '.json', '.xml')):
                                            inner_content_text = inner_body.decode('utf-8', errors='ignore')
                                            inner_content_type = "text/plain"

                                    if inner_content_text:
                                        await conn.execute(
                                            "INSERT INTO archived_files (county_name, parent_zip_id, filename_in_zip, file_type, text_content) VALUES ($1, $2, $3, $4, $5)",
                                            county_name, page_id, inner_filename, inner_content_type, inner_content_text
                                        )
                                except Exception as inner_e:
                                    logging.error(f"Failed to process {inner_filename} from zip {url}: {inner_e}")
                        return # Return early as we handled the inserts manually

                    await conn.execute(
                        """
                        INSERT INTO scraped_pages (county_name, url, source_site, content_type, status, text_content)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, text_content = EXCLUDED.text_content, timestamp = NOW()
                        """,
                        county_name, url, source_site, content_type, status, text_content
                    )
                elif is_ocr_mime:
                    ocr_text = await perform_ocr(body)
                    filename = os.path.basename(urlparse(url).path) or f"{source_site.replace('.', '_')}_image.png"
                    filepath = os.path.join(config.DOWNLOAD_DIR, county_name, filename)
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    with open(filepath, "wb") as f: f.write(body)

                    page_id = await conn.fetchval(
                        """
                        INSERT INTO scraped_pages (county_name, url, source_site, content_type, status)
                        VALUES ($1, $2, $3, $4, 'downloaded_ocr')
                        ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, timestamp = NOW() RETURNING id
                        """,
                        county_name, url, source_site, content_type
                    )
                    await conn.execute(
                        "INSERT INTO downloaded_documents (county_name, page_id, filepath, file_type, ocr_text) VALUES ($1, $2, $3, $4, $5)",
                        county_name, page_id, filepath, content_type, ocr_text
                    )
        except Exception as e:
            logging.error(f"An unexpected error occurred while directly downloading {url}: {e}")
