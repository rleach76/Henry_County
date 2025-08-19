import asyncio
import logging
import aiohttp
import os
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import Browser
import feedparser
from asyncpg.pool import Pool

from . import utils
from . import config
from . import database

DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']

async def save_business_listing(pool: Pool, county_name, source, name, address, phone, website, url):
    """Saves a business listing to the database using a connection from the pool."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO business_listings (county_name, source, business_name, address, phone_number, website, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (county_name, source, business_name) DO NOTHING
            """,
            county_name, source, name.strip(), address.strip(), phone.strip(), website.strip(), url
        )

async def scrape_chamber_of_commerce(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """Scrapes the Henry County Chamber of Commerce member directory."""
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
    Crawls a website, routing page links to the browser and document links to a direct downloader.
    """
    logging.info(f"[{county_name}] Starting intelligent crawl for: {start_url}")

    source_domain = urlparse(start_url).netloc
    page_queue = [start_url]
    doc_queue = []
    visited_urls = {start_url}

    page = await browser.new_page()
    try:
        while page_queue:
            url = page_queue.pop(0)
            logging.info(f"[{county_name}] Navigating to page: {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                async with pool.acquire() as conn:
                    content_element = soup.find('main') or soup.find('article') or soup.body
                    main_text = content_element.get_text(separator='\n', strip=True)
                    await conn.execute(
                        "INSERT INTO scraped_pages (county_name, url, source_site, content_type, status, text_content) VALUES ($1, $2, $3, 'text/html', 'processed_text', $4) ON CONFLICT (url) DO UPDATE SET text_content = EXCLUDED.text_content, timestamp = NOW()",
                        county_name, url, source_domain, main_text
                    )

                for a_tag in soup.find_all('a', href=True):
                    link = urljoin(url, a_tag['href']).split('#')[0]
                    if not link or link in visited_urls or urlparse(link).netloc != source_domain or "antiforgery" in link.lower():
                        continue

                    visited_urls.add(link)
                    link_lower = link.lower()
                    link_ext = os.path.splitext(urlparse(link).path)[1].lower()
                    is_doc_link = (link_ext in DOCUMENT_EXTENSIONS or link_ext in IMAGE_EXTENSIONS or "/documentcenter/" in link_lower or "/viewfile/" in link_lower or "/agendacenter/" in link_lower)

                    if is_doc_link:
                        if link not in doc_queue: doc_queue.append(link)
                    else:
                        page_queue.append(link)
            except Exception as e:
                logging.error(f"[{county_name}] Failed to process page {url}: {e}")
    finally:
        await page.close()

    logging.info(f"[{county_name}] Found {len(doc_queue)} documents to download.")
    if doc_queue:
        async with aiohttp.ClientSession() as session:
            tasks = [utils.download_and_process_file(session, pool, doc_url, county_name) for doc_url in doc_queue]
            await asyncio.gather(*tasks)
    logging.info(f"[{county_name}] Finished intelligent crawl for: {start_url}")

async def scrape_ohiobiz(browser: Browser, start_url: str, county_name: str, pool: Pool):
    logging.warning(f"[{county_name}] Skipping `scrape_ohiobiz` as it is currently out of scope.")
    pass

async def scrape_rss_feeds():
    """Scrapes all RSS feeds defined in all county config files."""
    logging.info("--- Starting Defensive RSS Feed Scrape for all counties ---")
    pool = None
    try:
        pool = await database.create_connection_pool()
        async with pool.acquire() as conn:
            county_configs = config.load_county_configs()
            headers = {'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'}
            async with aiohttp.ClientSession(headers=headers) as session:
                for county_config in county_configs:
                    county_name = county_config.get("county_name")
                    feeds = county_config.get("rss_feeds", {})
                    for feed_name, url in feeds.items():
                        try:
                            async with session.get(url, timeout=30) as response:
                                if response.status != 200: continue
                                text = await response.text()
                                feed = feedparser.parse(text)
                                if feed.bozo: logging.warning(f"Feed {feed_name} may be malformed.")
                                for entry in feed.entries:
                                    title, link = entry.get("title", ""), entry.get("link", "")
                                    if not title or not link: continue
                                    await conn.execute(
                                        "INSERT INTO rss_articles (county_name, source_feed, title, link, summary, published_date) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (link) DO NOTHING",
                                        county_name, feed_name, title, link, entry.get("summary", ""), entry.get("published", "")
                                    )
                        except Exception as e:
                            logging.error(f"Could not process RSS feed {feed_name} at {url}: {e}")
    finally:
        if pool: await database.close_connection_pool()
        logging.info("--- Finished RSS Feed Scrape ---")
