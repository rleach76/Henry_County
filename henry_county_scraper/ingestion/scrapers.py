import asyncio
import logging
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page
import feedparser

from . import utils
from . import config
from . import database

async def save_business_listing(db_conn, source, name, address, phone, website, url):
    """Saves a business listing to the database using asyncpg."""
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
        for i in range(1, 39):
            page_url = f"{start_url}?frm-page-530={i}"
            logging.info(f"Scraping page: {page_url}")
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                container = await page.query_selector('div#hccoc-members')
                listings = await container.query_selector_all('div.hccoc-member') if container else []

                if not listings:
                    logging.warning(f"No listings found on page {i}.")
                    continue

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
                        address_lines = [line.strip() for line in full_text.split('\n') if line.strip() and business_name not in line and phone_number not in line and "Website" not in line]
                        address = "\n".join(address_lines)
                        await save_business_listing(db_conn, source, business_name, address, phone_number, website, page_url)
                    except Exception as e:
                        logging.error(f"Error processing a listing on {page_url}: {e}")
            except Exception as e:
                logging.error(f"Could not scrape page {page_url}: {e}")
    finally:
        await page.close()
        if db_conn: await db_conn.close()
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

                for img in content_element.find_all('img'):
                    if int(img.get('width', 100)) < 50 or int(img.get('height', 100)) < 50: continue
                    if img.find_parent('a'): continue
                    img_url = img.get('src')
                    if img_url:
                        full_img_url = urljoin(url, img_url)
                        logging.info(f"Found potential content image: {full_img_url}")

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
        if db_conn: await db_conn.close()
        logging.info(f"Finished intelligent crawl for: {start_url}")

async def scrape_ohiobiz(browser: Browser, start_url: str):
    logging.warning("Skipping `scrape_ohiobiz` as it requires complex interaction and is currently out of scope.")
    pass

async def scrape_rss_feeds():
    """
    Scrapes all RSS feeds defined in the config file with defensive checks.
    """
    logging.info("--- Starting Defensive RSS Feed Scrape ---")
    db_conn = await database.get_db_connection()
    feeds = config.URLS_TO_SCRAPE.get("rss_feeds", {})

    headers = {'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'}

    async with aiohttp.ClientSession(headers=headers) as session:
        for feed_name, url in feeds.items():
            logging.info(f"Fetching feed: {feed_name} from {url}")
            try:
                async with session.get(url, timeout=30) as response:
                    if response.status != 200:
                        logging.warning(f"Failed to fetch {url}. Status: {response.status}")
                        continue

                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'html' in content_type:
                        logging.warning(f"Skipping {url} because it returned HTML content instead of XML/RSS.")
                        continue

                    text = await response.text()
                    feed = feedparser.parse(text)

                    if feed.bozo:
                        logging.warning(f"Feed {feed_name} may be malformed. Reason: {feed.bozo_exception}. Content preview: {text[:400]}")

                    for entry in feed.entries:
                        title = entry.get("title", "")
                        link = entry.get("link", "")
                        if not title or not link: continue

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
                logging.error(f"Could not process RSS feed {feed_name} at {url}: {e}")
    if db_conn:
        await db_conn.close()
    logging.info("--- Finished RSS Feed Scrape ---")
