import asyncio
import logging
from playwright.async_api import async_playwright

from . import database
from . import scrapers

# --- Scraper Category Mapping ---
# Maps the 'category' string from the database to the actual scraper function
# Note: This is a simple router. A more advanced system might use a more
#       pluggable architecture.
SCRAPER_MAPPING = {
    # Generic crawler is the default for most categories
    "government": scrapers.crawl_generic_website,
    "news_and_obituaries": scrapers.crawl_generic_website,
    "funeral_homes": scrapers.crawl_generic_website,
    "genealogy": scrapers.crawl_generic_website,
    # Specialized scrapers are routed explicitly
    "chamber_of_commerce": scrapers.scrape_chamber_of_commerce,
    "ohiobiz": scrapers.scrape_ohiobiz,
    "business_and_economic": scrapers.crawl_generic_website, # Default for this category
}

async def main():
    """
    Main orchestrator for the database-driven scraping process.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("--- Starting Database-Driven Scraper ---")

    db_conn = None
    try:
        # First, run non-browser scrapers like RSS
        logging.info("--- Running RSS Scraper ---")
        await scrapers.scrape_rss_feeds()

        # Fetch scraping targets from the database
        db_conn = await database.get_db_connection()
        # Fetch a batch of pending targets
        targets = await db_conn.fetch("SELECT id, url, category FROM scraping_targets WHERE status = 'pending' LIMIT 10")

        if not targets:
            logging.info("No pending targets found in the database. Exiting browser-based scraping.")
            return

        logging.info(f"Found {len(targets)} pending targets to scrape.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            for target in targets:
                target_id, url, category = target['id'], target['url'], target['category']
                logging.info(f"Processing target {target_id}: {url} (Category: {category})")

                try:
                    # Mark target as in_progress
                    await db_conn.execute("UPDATE scraping_targets SET status = 'in_progress', last_scraped_timestamp = NOW() WHERE id = $1", target_id)

                    # --- Simple Scraper Routing Logic ---
                    scraper_func = None
                    if "henrycountychamber" in url:
                        scraper_func = scrapers.scrape_chamber_of_commerce
                    elif "ohiobiz" in url:
                        scraper_func = scrapers.scrape_ohiobiz
                    else:
                        scraper_func = SCRAPER_MAPPING.get(category, scrapers.crawl_generic_website)

                    if scraper_func:
                        # Pass the browser and URL to the selected scraper
                        await scraper_func(browser, url)
                        # Mark as completed
                        await db_conn.execute("UPDATE scraping_targets SET status = 'completed' WHERE id = $1", target_id)
                        logging.info(f"Successfully processed target {target_id}: {url}")
                    else:
                        logging.warning(f"No scraper found for category '{category}'. Marking as failed.")
                        await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

                except Exception as e:
                    logging.error(f"Scraping failed for target {target_id}: {url}. Error: {e}")
                    # Mark as failed
                    await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

            await browser.close()

    except Exception as e:
        logging.critical(f"A critical error occurred in the main orchestrator: {e}")
    finally:
        if db_conn and not db_conn.is_closed():
            await db_conn.close()
        logging.info("--- Scraper Run Finished ---")


if __name__ == "__main__":
    # Note: Before running this, you should run `seed_db.py` once
    # to populate the scraping_targets table in your PostgreSQL database.
    asyncio.run(main())
