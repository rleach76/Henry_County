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

# Scraper mapping remains the same
SCRAPER_MAPPING = {
    "government": scrapers.crawl_generic_website,
    "news_and_obituaries": scrapers.crawl_generic_website,
    "funeral_homes": scrapers.crawl_generic_website,
    "genealogy": scrapers.crawl_generic_website,
    "business_and_economic": scrapers.crawl_generic_website,
}

async def scrape_county(county_name: str):
    """
    The main scraping logic for a single county, now managing a connection pool.
    """
    logging.info(f"--- Worker starting for county: {county_name} ---")

    # Load all county configurations and find the one for this worker
    all_configs = config.load_county_configs()
    county_config = next((c for c in all_configs if c.get('county_name') == county_name), None)

    if not county_config:
        logging.error(f"Configuration for '{county_name}' not found. Worker exiting.")
        return

    # Create the connection pool for this worker
    await database.create_connection_pool()

    try:
        # --- Scrape RSS Feeds ---
        rss_feeds_dict = county_config.get('rss_feeds', {})
        if rss_feeds_dict:
            # Flatten the list of URLs, handling both strings and lists of strings
            rss_feed_urls = []
            for item in rss_feeds_dict.values():
                if isinstance(item, str):
                    rss_feed_urls.append(item)
                elif isinstance(item, list):
                    rss_feed_urls.extend(item)

            if rss_feed_urls:
                await scrapers.scrape_rss_feeds(database.pool, county_name, rss_feed_urls)
        else:
            logging.info(f"No RSS feeds to scrape for {county_name}.")

        # On startup, reset any jobs for this county that were interrupted mid-run
        await database.reset_stale_targets(county_name)

        # Use the pool to get a connection for this initial query
        async with database.pool.acquire() as conn:
            targets = await conn.fetch("""
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

                try:
                    # All database operations within the loop will now use the shared pool
                    async with database.pool.acquire() as conn:
                        await conn.execute("UPDATE scraping_targets SET status = 'in_progress', last_scraped_timestamp = NOW() WHERE id = $1", target_id)

                    scraper_func = None
                    if "henrycountychamber" in url: scraper_func = scrapers.scrape_chamber_of_commerce
                    elif "ohiobiz" in url: scraper_func = scrapers.scrape_ohiobiz
                    else: scraper_func = SCRAPER_MAPPING.get(category, scrapers.crawl_generic_website)

                    if scraper_func:
                        # Pass the pool to the scraper function
                        await scraper_func(browser, url, county_name, database.pool)

                        async with database.pool.acquire() as conn:
                            new_status = 'pending' if freq == 'always' else 'completed'
                            await conn.execute("UPDATE scraping_targets SET status = $1 WHERE id = $2", new_status, target_id)
                        logging.info(f"[{county_name}] Successfully processed target {target_id}. New status: {new_status}")
                    else:
                        async with database.pool.acquire() as conn:
                            await conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

                except Exception as e:
                    logging.error(f"[{county_name}] Scraping failed for target {target_id}: {url}. Error: {e}")
                    async with database.pool.acquire() as conn:
                        await conn.execute("UPDATE scraping_targets SET status = 'failed' WHERE id = $1", target_id)

            await browser.close()

    except Exception as e:
        logging.critical(f"A critical error occurred in the worker for {county_name}: {e}")
    finally:
        # Ensure the pool is closed when the worker exits
        await database.close_connection_pool()
        logging.info(f"--- Worker finished for county: {county_name} ---")

def main():
    parser = argparse.ArgumentParser(description="Scraper worker for a single county.")
    parser.add_argument("--county", required=True, help="The name of the county to scrape.")
    args = parser.parse_args()

    # Create a unique log file for this worker process
    log_filename = f"{args.county.lower().replace(' ', '_')}_worker.log"
    config.setup_logging(log_filename=log_filename)

    asyncio.run(scrape_county(args.county))

if __name__ == "__main__":
    main()
