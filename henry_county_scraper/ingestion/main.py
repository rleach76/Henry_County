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

def setup_logging():
    """Sets up logging to file and console."""
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
    setup_logging()
    logging.info("--- Starting Database-Driven Scraper ---")

    db_conn = None
    try:
        # On startup, reset any jobs that were interrupted mid-run
        await database.reset_stale_targets()

        # Run non-browser scrapers first
        await scrapers.scrape_rss_feeds()

        # Fetch all pending targets from the database
        db_conn = await database.get_db_connection()
        # The query is now simpler. We also fetch 'always' jobs that are pending.
        targets = await db_conn.fetch("""
            SELECT id, url, category, scrape_frequency
            FROM scraping_targets
            WHERE status = 'pending'
            LIMIT 20
        """)

        if not targets:
            logging.info("No pending browser-based targets found. Exiting.")
            return

        logging.info(f"Found {len(targets)} pending targets to scrape.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            for target in targets:
                target_id, url, category, freq = target['id'], target['url'], target['category'], target['scrape_frequency']
                logging.info(f"Processing target {target_id}: {url} (Frequency: {freq})")

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

                        # Set status to 'completed' for 'once' jobs, or back to 'pending' for 'always' jobs.
                        new_status = 'pending' if freq == 'always' else 'completed'
                        await db_conn.execute("UPDATE scraping_targets SET status = $1 WHERE id = $2", new_status, target_id)
                        logging.info(f"Successfully processed target {target_id}. New status: {new_status}")
                    else:
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
    # Note: Before running this, you should run `seed_db.py` once
    # to populate the scraping_targets table in your PostgreSQL database.
    asyncio.run(main())
