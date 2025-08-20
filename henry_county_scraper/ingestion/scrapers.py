import asyncio
import logging
import aiohttp
import os
import hashlib
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import Browser
import feedparser
from asyncpg.pool import Pool

from . import utils
from . import database

DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.zip']
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']

# ... (save_business_listing and scrape_chamber_of_commerce are unchanged) ...
async def save_business_listing(pool: Pool, county_name, source, name, address, phone, website, url):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO business_listings (county_name, source, business_name, address, phone_number, website, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (county_name, source, business_name) DO NOTHING
            """,
            county_name, source, name.strip(), address.strip(), phone.strip(), website.strip(), url
        )

async def scrape_chamber_of_commerce(browser: Browser, start_url: str, county_name: str, pool: Pool):
    source = "Henry Chamber of Commerce"
    logging.info(f"[{county_name}] Starting scrape for {source} at {start_url}")
    page = await browser.new_page()
    try:
        for i in range(1, 39):
            page_url = f"{start_url}?frm-page-530={i}"
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                container = await page.query_selector('div#hccoc-members')
                listings = await container.query_selector_all('div.hccoc-member') if container else []
                if not listings: continue
                for listing in listings:
                    name_element = await listing.query_selector('span[style*="font-weight:bold"]')
                    business_name = (await name_element.inner_text() if name_element else "").strip()
                    if not business_name: continue
                    info_div = await listing.query_selector('div.member-info1')
                    if not info_div: continue
                    full_text = await info_div.inner_text()
                    website_element = await info_div.query_selector('a:has-text("Website")')
                    website = await website_element.get_attribute("href") if website_element else ""
                    import re
                    phone_match = re.search(r'(\(\d{3}\) \d{3}-\d{4})', full_text)
                    phone_number = phone_match.group(0) if phone_match else ""
                    address_lines = [line.strip() for line in full_text.split('\n') if line.strip() and business_name not in line and phone_number not in line and "Website" not in line]
                    address = "\n".join(address_lines)
                    await save_business_listing(pool, county_name, source, business_name, address, phone_number, website, page_url)
            except Exception as e:
                logging.error(f"Could not scrape page {page_url}: {e}")
    finally:
        await page.close()

async def crawl_generic_website(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """
    Crawls a website, performs change detection with hashing, saves new versions,
    and discovers new links.
    """
    logging.info(f"[{county_name}] Starting version-aware crawl for: {start_url}")

    source_domain = urlparse(start_url).netloc
    page_queue = [start_url]
    doc_queue = []
    visited_urls = {start_url}

    page = await browser.new_page()
    try:
        while page_queue:
            url = page_queue.pop(0)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                # 1. Extract content and compute hash
                content_element = soup.find('main') or soup.find('article') or soup.body
                main_text = content_element.get_text(separator='\n', strip=True)
                current_hash = hashlib.sha256(main_text.encode()).hexdigest()

                async with pool.acquire() as conn:
                    # 2. Check for existing versions
                    latest_version = await conn.fetchrow("SELECT version, content_hash FROM scraped_pages WHERE url = $1 AND county_name = $2 ORDER BY version DESC LIMIT 1", url, county_name)

                    if latest_version and latest_version['content_hash'] == current_hash:
                        logging.info(f"[{county_name}] Content unchanged for {url}. Updating last_seen_at.")
                        await conn.execute("UPDATE scraped_pages SET last_seen_at = NOW() WHERE url = $1 AND version = $2", url, latest_version['version'])
                    else:
                        new_version = (latest_version['version'] + 1) if latest_version else 1
                        logging.info(f"[{county_name}] New content found for {url}. Saving version {new_version}.")
                        await conn.execute(
                            "INSERT INTO scraped_pages (county_name, url, version, source_site, content_type, status, text_content, content_hash) VALUES ($1, $2, $3, $4, 'text/html', 'processed_text', $5, $6)",
                            county_name, url, new_version, source_domain, main_text, current_hash
                        )

                # 3. Discover and queue new links (always do this)
                new_links_to_add = []
                for a_tag in soup.find_all('a', href=True):
                    link = urljoin(url, a_tag['href']).split('#')[0]
                    if not link or link in visited_urls or urlparse(link).netloc != source_domain or "antiforgery" in link.lower():
                        continue

                    visited_urls.add(link)
                    new_links_to_add.append((county_name, link, 'discovered', 'pending', 'once'))

                    link_lower = link.lower()
                    link_ext = os.path.splitext(urlparse(link).path)[1].lower()
                    is_doc_link = (link_ext in DOCUMENT_EXTENSIONS or link_ext in IMAGE_EXTENSIONS or "/documentcenter/" in link_lower or "/viewfile/" in link_lower or "/agendacenter/" in link_lower or link_lower.endswith(('-pdf', '-doc', '-docx')))
                    if is_doc_link:
                        if link not in doc_queue: doc_queue.append(link)
                    else:
                        page_queue.append(link)

                if new_links_to_add:
                    async with pool.acquire() as conn:
                        await conn.executemany("INSERT INTO scraping_targets (county_name, url, category, status, scrape_frequency) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (county_name, url) DO NOTHING", new_links_to_add)
                    logging.info(f"[{county_name}] Added {len(new_links_to_add)} new URLs to the scraping queue.")

            except Exception as e:
                logging.error(f"[{county_name}] Failed to process page {url}: {e}")
    finally:
        await page.close()

    logging.info(f"[{county_name}] Found {len(doc_queue)} documents to download.")
    if doc_queue:
        # Create a semaphore to limit concurrent downloads
        semaphore = asyncio.Semaphore(5)
        async with aiohttp.ClientSession() as session:
            tasks = [utils.download_and_process_file(session, pool, doc_url, county_name, semaphore) for doc_url in doc_queue]
            await asyncio.gather(*tasks)
    logging.info(f"[{county_name}] Finished intelligent crawl for: {start_url}")

async def scrape_ohiobiz(browser: Browser, start_url: str, county_name: str, pool: Pool):
    logging.warning(f"[{county_name}] Skipping `scrape_ohiobiz` as it is currently out of scope.")
    pass

async def scrape_rss_feeds(pool: Pool, county_name: str, feed_urls: list):
    """
    Scrapes a list of RSS feeds, parses them, and stores new entries in the database.
    """
    if not feed_urls:
        return

    logging.info(f"[{county_name}] Scraping {len(feed_urls)} RSS feed(s).")

    async with aiohttp.ClientSession() as session:
        for feed_url in feed_urls:
            try:
                # Use aiohttp to fetch the feed asynchronously
                async with session.get(feed_url, timeout=30) as response:
                    if response.status != 200:
                        logging.warning(f"[{county_name}] Failed to fetch RSS feed {feed_url} with status {response.status}")
                        continue

                    # feedparser can handle bytes directly
                    feed_content = await response.read()
                    parsed_feed = feedparser.parse(feed_content)

                if parsed_feed.bozo:
                    logging.warning(f"[{county_name}] Feed {feed_url} may be malformed. Bozo reason: {parsed_feed.bozo_exception}")

                records_to_insert = []
                for entry in parsed_feed.entries:
                    # Get a unique ID for the entry, fallback to link
                    entry_id = entry.get('id') or entry.get('link')
                    if not entry_id:
                        continue # Skip entries without a unique identifier

                    # Parse publication date
                    published_date = None
                    if 'published_parsed' in entry and entry.published_parsed:
                        from datetime import datetime
                        published_date = datetime(*entry.published_parsed[:6])

                    records_to_insert.append((
                        county_name,
                        feed_url,
                        entry_id,
                        entry.get('title'),
                        entry.get('link'),
                        published_date,
                        entry.get('summary')
                    ))

                if records_to_insert:
                    async with pool.acquire() as conn:
                        await conn.executemany(
                            """
                            INSERT INTO rss_feed_entries (county_name, feed_url, entry_id, title, link, published_date, summary)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (county_name, feed_url, entry_id) DO NOTHING
                            """,
                            records_to_insert
                        )
                        logging.info(f"[{county_name}] Processed {len(records_to_insert)} entries from {feed_url}.")

            except Exception as e:
                logging.error(f"[{county_name}] Error processing RSS feed {feed_url}: {e}")
