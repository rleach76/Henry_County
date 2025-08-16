import asyncio
import logging
import os
from playwright.async_api import async_playwright

from . import config
from . import database
from . import scrapers

# --- Scraper Category Mapping ---
SCRAPER_MAPPING = {
    "government": scrapers.crawl_generic_website,
    "news_and_obituaries": scrapers.crawl_generic_website,
    "funeral_homes": scrapers.crawl_generic_website,
    "genealogy": scrapers.crawl_generic_website,
    "chamber_of_commerce": scrapers.scrape_chamber_of_commerce,
    "ohiobiz": scrapers.scrape_ohiobiz,
    "business_and_economic": scrapers.crawl_generic_website,
}

def setup_directories_and_logging():
    """Creates necessary directories and sets up logging."""
    # Create data directories if they don't exist
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    # The storage directory is created by init_db if needed, but good to be explicit
    os.makedirs(os.path.dirname(database.DSN), exist_ok=True) if "postgresql" not in database.DSN else None


    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(config.LOGS_DIR, "scraper.log")),
            logging.StreamHandler()
        ]
    )

async def main():
    """
    Main orchestrator for the database-driven scraping process.
    """
    setup_directories_and_logging()
    logging.info("--- Starting Database-Driven Scraper ---")

    db_conn = None
    try:
        # First, run non-browser scrapers like RSS
        logging.info("--- Running RSS Scraper ---")
        await scrapers.scrape_rss_feeds()

        # Fetch scraping targets from the database
        db_conn = await database.get_db_connection()
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
                    await db_conn.execute("UPDATE scraping_targets SET status = 'in_progress', last_scraped_timestamp = NOW() WHERE id = $1", target_id)

                    scraper_func = None
                    if "henrycountychamber" in url:
                        scraper_func = scrapers.scrape_chamber_of_commerce
                    elif "ohiobiz" in url:
                        scraper_func = scrapers.scrape_ohiobiz
                    else:
                        scraper_func = SCRAPER_MAPPING.get(category, scrapers.crawl_generic_website)

                    if scraper_func:
                        await scraper_func(browser, url)
                        await db_conn.execute("UPDATE scraping_targets SET status = 'completed' WHERE id = $1", target_id)
                        logging.info(f"Successfully processed target {target_id}: {url}")
                    else:
                        logging.warning(f"No scraper found for category '{category}'. Marking as failed.")
                        await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

                except Exception as e:
                    logging.error(f"Scraping failed for target {target_id}: {url}. Error: {e}")
                    await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

            await browser.close()

    except Exception as e:
        logging.critical(f"A critical error occurred in the main orchestrator: {e}")
    finally:
        if db_conn and not db_conn.is_closed():
            await db_conn.close()
        logging.info("--- Scraper Run Finished ---")


if __name__ == "__main__":
    asyncio.run(main())
