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

async def save_business_listing(db_conn, county_name, source, name, address, phone, website, url):
    """Saves a business listing to the database using asyncpg, partitioned by county."""
    await db_conn.execute(
        """
        INSERT INTO business_listings
        (county_name, source, business_name, address, phone_number, website, scraped_from_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (county_name, source, business_name) DO NOTHING
        """,
        county_name, source, name.strip(), address.strip(), phone.strip(), website.strip(), url
    )

async def scrape_chamber_of_commerce(browser: Browser, start_url: str, county_name: str):
    """
    Scrapes the Henry County Chamber of Commerce member directory.
    """
    source = "Henry Chamber of Commerce"
    logging.info(f"[{county_name}] Starting scrape for {source} at {start_url}")

    page = await browser.new_page()
    db_conn = await database.get_db_connection()

    try:
        for i in range(1, 39): # This range is specific to Henry County's site
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
                    await save_business_listing(db_conn, county_name, source, business_name, address, phone_number, website, page_url)
            except Exception as e:
                logging.error(f"Could not scrape page {page_url}: {e}")
    finally:
        await page.close()
        if db_conn: await db_conn.close()
        logging.info(f"[{county_name}] Finished scrape for {source}.")

async def crawl_generic_website(browser: Browser, start_url: str, county_name: str):
    """
    Crawls a generic website, extracting main content and passing county_name.
    """
    logging.info(f"[{county_name}] Starting intelligent crawl for: {start_url}")

    source_domain = urlparse(start_url).netloc
    queue = [start_url]
    visited_urls = {start_url}

    page = await browser.new_page()
    db_conn = await database.get_db_connection()
    try:
        while queue:
            url = queue.pop(0)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                html_content = await page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                content_element = soup.find('main') or soup.find('article') or soup.body
                main_text = content_element.get_text(separator='\n', strip=True)

                await db_conn.execute(
                    """
                    INSERT INTO scraped_pages (county_name, url, source_site, content_type, status, text_content)
                    VALUES ($1, $2, 'text/html', 'processed_text', $3) ON CONFLICT (url) DO UPDATE SET text_content = EXCLUDED.text_content, timestamp = NOW()
                    """,
                    county_name, url, source_domain, main_text
                )

                for a_tag in soup.find_all('a', href=True):
                    link = urljoin(url, a_tag['href']).split('#')[0]
                    if "antiforgery" in link.lower() or urlparse(link).netloc != source_domain or link in visited_urls:
                        continue
                    visited_urls.add(link)
                    queue.append(link)
            except Exception as e:
                logging.error(f"[{county_name}] Failed to process {url}: {e}")
    finally:
        await page.close()
        if db_conn: await db_conn.close()
        logging.info(f"[{county_name}] Finished intelligent crawl for: {start_url}")

async def scrape_ohiobiz(browser: Browser, start_url: str, county_name: str):
    logging.warning(f"[{county_name}] Skipping `scrape_ohiobiz` as it is currently out of scope.")
    pass

async def scrape_rss_feeds():
    """
    Scrapes all RSS feeds defined in all county config files.
    """
    logging.info("--- Starting Defensive RSS Feed Scrape for all counties ---")
    db_conn = await database.get_db_connection()
    try:
        county_configs = config.load_county_configs()
        headers = {'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'}

        async with aiohttp.ClientSession(headers=headers) as session:
            for county_config in county_configs:
                county_name = county_config.get("county_name")
                feeds = county_config.get("rss_feeds", {})
                for feed_name, url in feeds.items():
                    logging.info(f"[{county_name}] Fetching feed: {feed_name}")
                    try:
                        async with session.get(url, timeout=30) as response:
                            if response.status != 200: continue
                            text = await response.text()
                            feed = feedparser.parse(text)
                            if feed.bozo: logging.warning(f"Feed {feed_name} may be malformed.")

                            for entry in feed.entries:
                                title, link = entry.get("title", ""), entry.get("link", "")
                                if not title or not link: continue
                                await db_conn.execute(
                                    """
                                    INSERT INTO rss_articles (county_name, source_feed, title, link, summary, published_date)
                                    VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (link) DO NOTHING
                                    """,
                                    county_name, feed_name, title, link, entry.get("summary", ""), entry.get("published", "")
                                )
                    except Exception as e:
                        logging.error(f"Could not process RSS feed {feed_name} at {url}: {e}")
    finally:
        if db_conn: await db_conn.close()
        logging.info("--- Finished RSS Feed Scrape ---")
