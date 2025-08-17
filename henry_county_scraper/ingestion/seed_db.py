import asyncio
import logging
from . import database
from . import config

async def seed():
    """
    Populates the scraping_targets table with the initial list of URLs
    from the config file. This is intended to be run once for setup.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # First, ensure the database and tables are created.
    logging.info("Initializing database schema...")
    await database.init_db()

    db_conn = await database.get_db_connection()
    logging.info("Seeding database with initial URLs...")

    try:
        urls_to_seed = []
        for category, urls in config.URLS_TO_SCRAPE.items():
            if isinstance(urls, list):
                for url in urls:
                    urls_to_seed.append((url, category))
            elif isinstance(urls, dict): # For RSS feeds
                for name, url in urls.items():
                    # Use a more specific category for RSS feeds
                    urls_to_seed.append((url, f"rss_{name}"))

        if not urls_to_seed:
            logging.warning("No URLs found in config file to seed.")
            return

        # Using executemany for efficient batch insertion
        await db_conn.executemany(
            """
            INSERT INTO scraping_targets (url, category, status, scrape_frequency)
            VALUES ($1, $2, 'pending', 'always')
            ON CONFLICT (url) DO UPDATE SET
                category = EXCLUDED.category,
                scrape_frequency = EXCLUDED.scrape_frequency
            """,
            urls_to_seed
        )

        logging.info(f"Successfully seeded {len(urls_to_seed)} URLs into the scraping_targets table.")

    except Exception as e:
        logging.critical(f"An error occurred during database seeding: {e}")
    finally:
        if db_conn:
            await db_conn.close()

if __name__ == "__main__":
    asyncio.run(seed())
