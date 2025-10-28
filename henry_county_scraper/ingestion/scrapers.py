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

async def _save_recorder_record(pool: Pool, county_name: str, record: dict, url: str):
    """Saves a single recorder record to the database."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO recorder_records (county_name, document_number, document_type, recording_date, grantor, grantee, description, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (county_name, document_number) DO NOTHING
            """,
            county_name,
            record.get("doc_number"),
            record.get("doc_type"),
            record.get("record_date"),
            record.get("grantor"),
            record.get("grantee"),
            record.get("description"),
            url,
        )

async def scrape_kofile_recorder(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """
    Scrapes the Kofile portal for recorder/deed records.
    This is a complex multi-step process involving:
    1. Navigating to the site.
    2. Clicking 'Guest' login.
    3. Navigating to the search form.
    4. Performing a search (e.g., by date).
    5. Parsing results and saving to the database.
    """
    logging.info(f"[{county_name}] Starting Kofile recorder scrape for: {start_url}")
    page = await browser.new_page()
    try:
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

        # 1. Handle Guest Login
        guest_button = page.locator('a:has-text("Guest")')
        if await guest_button.is_visible():
            await guest_button.click()
            await page.wait_for_load_state("domcontentloaded")
            # After login, there might be a welcome/disclaimer page.
            # Look for a search link or button. Common text includes "Document Search", "Accept", "Continue".
            accept_button = page.locator('a:has-text("Accept")')
            if await accept_button.is_visible():
                 await accept_button.click()
                 await page.wait_for_load_state("domcontentloaded")


        # 2. Perform Search by Date
        # Use a reliable selector for the start date input. Kofile often uses name attributes.
        from datetime import datetime, timedelta
        # Search for documents recorded in the last 7 days.
        start_date = (datetime.now() - timedelta(days=7)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        await page.fill('input[name="searchCriteria.startDate"]', start_date)
        await page.fill('input[name="searchCriteria.endDate"]', end_date)

        # Click the search button
        await page.locator('input[type="submit"][value="Search"]').click()
        await page.wait_for_selector('table.results-table', timeout=60000)

        # 3. Parse Results
        rows = await page.query_selector_all('table.results-table tbody tr')
        logging.info(f"[{county_name}] Found {len(rows)} records in Kofile search results.")

        for row in rows:
            cells = await row.query_selector_all('td')
            if len(cells) < 8: continue # Basic check for valid row

            # Extract data based on typical Kofile table structure. This may need adjustment.
            doc_number_element = await cells[2].query_selector('a')
            doc_number = await doc_number_element.inner_text() if doc_number_element else ""

            record_date_str = await cells[3].inner_text()
            record_date = datetime.strptime(record_date_str.strip(), "%m/%d/%Y").date() if record_date_str else None

            record = {
                "doc_number": doc_number.strip(),
                "doc_type": (await cells[1].inner_text()).strip(),
                "record_date": record_date,
                "grantor": (await cells[5].inner_text()).strip(),
                "grantee": (await cells[6].inner_text()).strip(),
                "description": (await cells[7].inner_text()).strip(),
            }
            await _save_recorder_record(pool, county_name, record, page.url)

    except Exception as e:
        logging.error(f"[{county_name}] An error occurred during Kofile scrape: {e}")
    finally:
        await page.close()

async def _save_sheriff_sale(pool: Pool, county_name: str, sale: dict, url: str):
    """Saves a single sheriff sale record to the database."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sheriff_sales (county_name, case_number, sale_date, property_address, plaintiff, defendant, appraisal_value, status, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (county_name, case_number, sale_date) DO NOTHING
            """,
            county_name,
            sale.get("case_number"),
            sale.get("sale_date"),
            sale.get("address"),
            sale.get("plaintiff"),
            sale.get("defendant"),
            sale.get("appraisal"),
            sale.get("status"),
            url,
        )

async def scrape_realauction_sheriff_sales(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """
    Scrapes the RealAuction portal for sheriff sale listings.
    """
    logging.info(f"[{county_name}] Starting RealAuction sheriff sale scrape for: {start_url}")
    page = await browser.new_page()
    try:
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

        # The properties are listed in blocks. The selector might need to be adjusted if the site changes.
        property_blocks = await page.query_selector_all("div.ASTAT_DIV")
        logging.info(f"[{county_name}] Found {len(property_blocks)} property blocks on RealAuction.")

        from datetime import datetime

        for block in property_blocks:
            # Extract data from the block. This relies on the structure of the HTML.
            case_number_el = await block.query_selector('span[id^="caseH_"]')
            case_number = (await case_number_el.inner_text()).replace("CASE #:", "").strip() if case_number_el else ""

            sale_date_el = await block.query_selector('span[id^="saleDateH_"]')
            sale_date_str = (await sale_date_el.inner_text()).replace("Sale Date:", "").strip() if sale_date_el else ""
            sale_date = datetime.strptime(sale_date_str, "%m/%d/%Y").date() if sale_date_str else None

            address_el = await block.query_selector('span[id^="Address_"]')
            address = await address_el.inner_text() if address_el else ""

            plaintiff_el = await block.query_selector('span[id^="Plaintiff_"]')
            plaintiff = (await plaintiff_el.inner_text()).replace("PLAINTIFF:", "").strip() if plaintiff_el else ""

            defendant_el = await block.query_selector('span[id^="Defendant_"]')
            defendant = (await defendant_el.inner_text()).replace("DEFENDANT:", "").strip() if defendant_el else ""

            appraisal_el = await block.query_selector('span[id^="appraisedH_"]')
            appraisal_str = (await appraisal_el.inner_text()).replace("APPRAISED VALUE:", "").replace("$", "").replace(",", "").strip() if appraisal_el else "0"
            appraisal = float(appraisal_str) if appraisal_str else 0.0

            status_el = await block.query_selector('span[id^="AuctionStatus_"]')
            status = await status_el.inner_text() if status_el else ""

            sale = {
                "case_number": case_number,
                "sale_date": sale_date,
                "address": address,
                "plaintiff": plaintiff,
                "defendant": defendant,
                "appraisal": appraisal,
                "status": status,
            }
            await _save_sheriff_sale(pool, county_name, sale, page.url)

    except Exception as e:
        logging.error(f"[{county_name}] An error occurred during RealAuction scrape: {e}")
    finally:
        await page.close()

async def _save_auditor_property(pool: Pool, county_name: str, prop: dict, url: str):
    """Saves a single auditor property record to the database."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auditor_properties (county_name, parcel_id, property_address, owner_name, assessed_value_total, tax_district, school_district, land_use_code, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (county_name, parcel_id) DO UPDATE SET
                property_address = EXCLUDED.property_address,
                owner_name = EXCLUDED.owner_name,
                assessed_value_total = EXCLUDED.assessed_value_total,
                scraped_timestamp = NOW()
            """,
            county_name,
            prop.get("parcel_id"),
            prop.get("address"),
            prop.get("owner"),
            prop.get("value"),
            prop.get("tax_district"),
            prop.get("school_district"),
            prop.get("land_use"),
            url,
        )

async def scrape_arc_auditor(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """
    Scrapes the Appraisal Research Corp (ARC) portal for auditor property data.
    """
    logging.info(f"[{county_name}] Starting ARC auditor scrape for: {start_url}")
    page = await browser.new_page()
    try:
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

        # 1. Agree to disclaimer
        await page.locator('a:has-text("I Agree")').click()
        await page.wait_for_load_state("domcontentloaded")

        # 2. Perform a search. We will search for a common street name to get a list of results.
        # This is a good way to discover many properties without needing specific parcel IDs.
        await page.fill('input[name="search.query"]', "MAIN ST")
        await page.locator('button:has-text("Search")').click()

        # 3. Wait for and parse results
        await page.wait_for_selector("table#results-table", timeout=60000)
        rows = await page.query_selector_all("table#results-table tbody tr")
        logging.info(f"[{county_name}] Found {len(rows)} properties in ARC search.")

        # Store links to detail pages to avoid navigating while iterating
        detail_links = []
        for row in rows:
            link_el = await row.query_selector('a')
            if link_el:
                detail_links.append(await link_el.get_attribute('href'))

        for link in detail_links:
            detail_url = urljoin(page.url, link)
            try:
                await page.goto(detail_url, wait_until="domcontentloaded")

                # Extract data from the detail page. Selectors are based on ARC's typical layout.
                parcel_id_el = await page.query_selector('td:has-text("Parcel ID") + td')
                parcel_id = await parcel_id_el.inner_text() if parcel_id_el else ""

                owner_el = await page.query_selector('td:has-text("Owner") + td')
                owner = await owner_el.inner_text() if owner_el else ""

                address_el = await page.query_selector('td:has-text("Address") + td')
                address = await address_el.inner_text() if address_el else ""

                value_el = await page.query_selector('td:has-text("Total Assessed") + td')
                value_str = (await value_el.inner_text()).replace("$", "").replace(",", "") if value_el else "0"
                value = float(value_str) if value_str else 0.0

                tax_dist_el = await page.query_selector('td:has-text("Tax District") + td')
                tax_district = await tax_dist_el.inner_text() if tax_dist_el else ""

                school_dist_el = await page.query_selector('td:has-text("School District") + td')
                school_district = await school_dist_el.inner_text() if school_dist_el else ""

                land_use_el = await page.query_selector('td:has-text("Land Use") + td')
                land_use = await land_use_el.inner_text() if land_use_el else ""

                prop = {
                    "parcel_id": parcel_id,
                    "owner": owner,
                    "address": address,
                    "value": value,
                    "tax_district": tax_district,
                    "school_district": school_district,
                    "land_use": land_use,
                }
                await _save_auditor_property(pool, county_name, prop, page.url)

            except Exception as e:
                logging.error(f"[{county_name}] Failed to process ARC detail page {detail_url}: {e}")

    except Exception as e:
        logging.error(f"[{county_name}] An error occurred during ARC scrape: {e}")
    finally:
        await page.close()

async def _save_court_case(pool: Pool, county_name: str, case: dict, url: str):
    """Saves a single court case record to the database."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO court_cases (county_name, case_number, case_type, filing_date, plaintiffs, defendants, status, scraped_from_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (county_name, case_number) DO UPDATE SET
                status = EXCLUDED.status,
                scraped_timestamp = NOW()
            """,
            county_name,
            case.get("case_number"),
            case.get("case_type"),
            case.get("filing_date"),
            case.get("plaintiffs"),
            case.get("defendants"),
            case.get("status"),
            url,
        )

async def scrape_courtview_clerk(browser: Browser, start_url: str, county_name: str, pool: Pool):
    """
    Scrapes the CourtView portal for Clerk of Courts case data.
    """
    logging.info(f"[{county_name}] Starting CourtView clerk scrape for: {start_url}")
    page = await browser.new_page()
    try:
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

        # 1. Navigate to the case search page
        # The site uses frames, so we need to target the correct frame to find the search link.
        # However, a direct link is often easier if available. Let's assume a direct navigation is possible.
        # Based on inspection, the search is often under a 'Case' or 'Search' menu.
        # Let's try to find a link with text 'Case Number' to get to the search page.
        # If this fails, a more complex frame-based navigation would be needed.

        # Click on "Case Information" in the left nav, which loads the search options.
        await page.locator('a:has-text("Case Information")').click()

        # 2. Perform a search by date
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=30)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        await page.fill('input[name="filingDateFrom"]', start_date)
        await page.fill('input[name="filingDateTo"]', end_date)

        # Click the search button
        await page.locator('input[type="submit"][value="Search"]').click()

        # 3. Wait for and parse results
        await page.wait_for_selector("table.result", timeout=60000)
        rows = await page.query_selector_all("table.result tr.result-row")
        logging.info(f"[{county_name}] Found {len(rows)} cases in CourtView search.")

        for row in rows:
            cells = await row.query_selector_all('td')
            if len(cells) < 5: continue

            case_number_el = await cells[0].query_selector('a')
            case_number = await case_number_el.inner_text() if case_number_el else ""

            filing_date_str = await cells[2].inner_text()
            filing_date = datetime.strptime(filing_date_str.strip(), "%m/%d/%Y").date() if filing_date_str else None

            # Extracting party names can be complex due to HTML structure.
            # We'll take the full text and process it simply.
            parties_text = await cells[1].inner_text()
            plaintiffs = defendants = parties_text # Simple assignment for now

            case = {
                "case_number": case_number.strip(),
                "case_type": (await cells[3].inner_text()).strip(),
                "filing_date": filing_date,
                "plaintiffs": plaintiffs,
                "defendants": defendants,
                "status": (await cells[4].inner_text()).strip(),
            }
            await _save_court_case(pool, county_name, case, page.url)

    except Exception as e:
        logging.error(f"[{county_name}] An error occurred during CourtView scrape: {e}")
    finally:
        await page.close()
