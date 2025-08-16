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
    Crawls a generic website by attaching a response listener and following internal links.
    """
    logging.info(f"Starting generic crawl for: {start_url}")

    source_domain = urlparse(start_url).netloc
    queue = [start_url]
    visited_urls = {start_url}

    page = await browser.new_page()

    background_tasks = set()
    def handle_response(response):
        task = asyncio.create_task(utils.process_response(response))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    page.on("response", handle_response)

    while queue:
        url = queue.pop(0)
        logging.info(f"Crawling: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html_content = await page.content()

            soup = BeautifulSoup(html_content, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                link = urljoin(url, a_tag['href']).split('#')[0]

                # --- FIX for Anti-Forgery Loop ---
                if "antiforgery" in link.lower():
                    logging.warning(f"Skipping likely anti-forgery link: {link}")
                    continue

                if urlparse(link).netloc == source_domain and link not in visited_urls:
                    visited_urls.add(link)
                    queue.append(link)
        except Exception as e:
            logging.error(f"Failed to crawl or parse {url}: {e}")

    logging.info(f"Crawling finished. Waiting for {len(background_tasks)} background tasks to complete.")
    if background_tasks:
        await asyncio.gather(*background_tasks)

    await page.close()
    logging.info(f"Finished generic crawl for: {start_url}")

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
