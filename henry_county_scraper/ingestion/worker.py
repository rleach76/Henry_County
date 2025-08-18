import asyncio
import logging
import argparse
from playwright.async_api import async_playwright

# Adjust path to import from sibling modules
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ingestion import database
from ingestion import scrapers
from ingestion import config

# --- Scraper Category Mapping ---
SCRAPER_MAPPING = {
    "government": scrapers.crawl_generic_website,
    "news_and_obituaries": scrapers.crawl_generic_website,
    "funeral_homes": scrapers.crawl_generic_website,
    "genealogy": scrapers.crawl_generic_website,
    "business_and_economic": scrapers.crawl_generic_website,
}

async def scrape_county(county_name: str):
    """
    The main scraping logic for a single county.
    """
    logging.info(f"--- Worker starting for county: {county_name} ---")
    db_conn = None
    try:
        # On startup, reset any jobs for this county that were interrupted mid-run
        await database.reset_stale_targets(county_name)

        db_conn = await database.get_db_connection()

        targets = await db_conn.fetch("""
            SELECT id, url, category, scrape_frequency
            FROM scraping_targets
            WHERE county_name = $1 AND (status = 'pending' OR scrape_frequency = 'always')
        """, county_name)

        if not targets:
            logging.info(f"No pending targets found for {county_name}. Worker exiting.")
            return

        logging.info(f"Found {len(targets)} targets to scrape for {county_name}.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for target in targets:
                target_id, url, category, freq = target['id'], target['url'], target['category'], target['scrape_frequency']
                logging.info(f"[{county_name}] Processing target {target_id}: {url}")

                try:
                    await db_conn.execute("UPDATE scraping_targets SET status = 'in_progress', last_scraped_timestamp = NOW() WHERE id = $1", target_id)

                    scraper_func = None
                    if "henrycountychamber" in url: scraper_func = scrapers.scrape_chamber_of_commerce
                    elif "ohiobiz" in url: scraper_func = scrapers.scrape_ohiobiz
                    else: scraper_func = SCRAPER_MAPPING.get(category, scrapers.crawl_generic_website)

                    if scraper_func:
                        await scraper_func(browser, url, county_name) # Pass county_name to scrapers
                        new_status = 'pending' if freq == 'always' else 'completed'
                        await db_conn.execute("UPDATE scraping_targets SET status = $1 WHERE id = $2", new_status, target_id)
                        logging.info(f"[{county_name}] Successfully processed target {target_id}. New status: {new_status}")
                    else:
                        await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

                except Exception as e:
                    logging.error(f"[{county_name}] Scraping failed for target {target_id}: {url}. Error: {e}")
                    await db_conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

            await browser.close()

    except Exception as e:
        logging.critical(f"A critical error occurred in the worker for {county_name}: {e}")
    finally:
        if db_conn and not db_conn.is_closed():
            await db_conn.close()
        logging.info(f"--- Worker finished for county: {county_name} ---")

def main():
    parser = argparse.ArgumentParser(description="Scraper worker for a single county.")
    parser.add_argument("--county", required=True, help="The name of the county to scrape.")
    args = parser.parse_args()

    config.setup_logging()

    asyncio.run(scrape_county(args.county))

if __name__ == "__main__":
    main()
