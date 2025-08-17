import asyncio
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page
import feedparser

from . import utils
from . import config
from . import database

async def save_business_listing(db_conn, source, name, address, phone, website, url):
    """Saves a business listing to the database using asyncpg."""
    # Using ON CONFLICT...DO NOTHING to handle duplicates gracefully
    await db_conn.execute(
        """
        INSERT INTO business_listings
        (source, business_name, address, phone_number, website, scraped_from_url)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (source, business_name) DO NOTHING
        """,
        source, name.strip(), address.strip(), phone.strip(), website.strip(), url
    )

async def scrape_chamber_of_commerce(browser: Browser, start_url: str):
    """
    Scrapes the Henry County Chamber of Commerce member directory.
    """
    source = "Henry Chamber of Commerce"
    logging.info(f"Starting scrape for {source} at {start_url}")

    page = await browser.new_page()
    db_conn = await database.get_db_connection()

    try:
        for i in range(1, 39): # Loop through all 38 pages
            page_url = f"{start_url}?frm-page-530={i}"
            logging.info(f"Scraping page: {page_url}")
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)

                container = await page.query_selector('div#hccoc-members')
                listings = await container.query_selector_all('div.hccoc-member') if container else []

                if not listings:
                    logging.warning(f"No listings found on page {i}. The structure might have changed.")
                    continue

                logging.info(f"Found {len(listings)} listings on page {i}.")

                for listing in listings:
                    try:
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

                        address_lines = [
                            line.strip() for line in full_text.split('\n')
                            if line.strip() and business_name not in line and phone_number not in line and "Website" not in line
                        ]
                        address = "\n".join(address_lines)

                        await save_business_listing(db_conn, source, business_name, address, phone_number, website, page_url)

                    except Exception as e:
                        logging.error(f"    - Error processing a listing on {page_url}: {e}")

            except Exception as e:
                logging.error(f"Could not scrape page {page_url}: {e}")
    finally:
        await page.close()
        if db_conn:
            await db_conn.close()
        logging.info(f"Finished scrape for {source}.")

async def crawl_generic_website(browser: Browser, start_url: str):
    """
    Crawls a generic website, extracting main content and avoiding boilerplate/UI elements.
    """
    logging.info(f"Starting intelligent crawl for: {start_url}")

    source_domain = urlparse(start_url).netloc
    queue = [start_url]
    visited_urls = {start_url}

    page = await browser.new_page()
    db_conn = await database.get_db_connection()

    try:
        while queue:
            url = queue.pop(0)
            logging.info(f"Intelligently processing: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')

                # --- 1. Text Extraction (Boilerplate Removal) ---
                content_element = soup.find('main') or soup.find('article') or soup.body
                main_text = content_element.get_text(separator='\n', strip=True)

                await db_conn.execute(
                    """
                    INSERT INTO scraped_pages (url, source_site, content_type, status, text_content)
                    VALUES ($1, $2, 'text/html', 'processed_text', $3)
                    ON CONFLICT (url) DO UPDATE SET text_content = EXCLUDED.text_content, timestamp = NOW()
                    """,
                    url, source_domain, main_text
                )

                # --- 2. Image Extraction (Heuristics to avoid UI elements) ---
                for img in content_element.find_all('img'):
                    # Heuristic 1: Skip tiny images (likely icons/spacers)
                    width = int(img.get('width', 100))
                    height = int(img.get('height', 100))
                    if width < 50 or height < 50:
                        continue

                    # Heuristic 2: Skip images that are links (likely buttons/ads)
                    if img.find_parent('a'):
                        continue

                    img_url = img.get('src')
                    if img_url:
                        full_img_url = urljoin(url, img_url)
                        # We would need another fetch here, perhaps with aiohttp, to get the image
                        # For now, we will just log it as a potential content image
                        logging.info(f"Found potential content image: {full_img_url}")

                # --- 3. Link Discovery (from the whole page) ---
                for a_tag in soup.find_all('a', href=True):
                    link = urljoin(url, a_tag['href']).split('#')[0]
                    if "antiforgery" in link.lower():
                        logging.warning(f"Skipping likely anti-forgery link: {link}")
                        continue
                    if urlparse(link).netloc == source_domain and link not in visited_urls:
                        visited_urls.add(link)
                        queue.append(link)

            except Exception as e:
                logging.error(f"Failed to process {url}: {e}")
    finally:
        await page.close()
        if db_conn:
            await db_conn.close()
        logging.info(f"Finished intelligent crawl for: {start_url}")

async def scrape_ohiobiz(browser: Browser):
    # This scraper remains non-functional and is not a priority per user feedback.
    logging.warning("Skipping `scrape_ohiobiz` as it requires complex interaction and is currently out of scope.")
    pass

async def scrape_rss_feeds():
    """
    Scrapes all RSS feeds defined in the config file using asyncpg.
    """
    logging.info("--- Starting RSS Feed Scrape ---")
    db_conn = await database.get_db_connection()
    try:
        feeds = config.URLS_TO_SCRAPE.get("rss_feeds", {})
        for feed_name, url in feeds.items():
            logging.info(f"Parsing feed: {feed_name} from {url}")
            try:
                feed = feedparser.parse(url)
                if feed.bozo:
                    logging.warning(f"Feed {feed_name} may be malformed. Reason: {feed.bozo_exception}")

                for entry in feed.entries:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    if not title or not link:
                        logging.warning(f"Skipping entry in {feed_name} due to missing title or link.")
                        continue

                    summary = entry.get("summary", "")
                    published = entry.get("published", "")

                    await db_conn.execute(
                        """
                        INSERT INTO rss_articles (source_feed, title, link, summary, published_date)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (link) DO NOTHING
                        """,
                        feed_name, title, link, summary, published
                    )
                logging.info(f"Finished parsing feed: {feed_name}. Found {len(feed.entries)} entries.")
            except Exception as e:
                logging.error(f"Could not parse RSS feed {feed_name} at {url}: {e}")
    finally:
        if db_conn:
            await db_conn.close()
        logging.info("--- Finished RSS Feed Scrape ---")
