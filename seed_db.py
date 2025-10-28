import asyncio
import asyncpg
import os
import yaml
import logging

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))
from henry_county_scraper.ingestion import database

# Database connection details from environment variables
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "henry_county_db")
DSN = f"postgres://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

COUNTIES_DIR = "henry_county_scraper/ingestion/counties"

async def seed_database():
    """
    Connects to the database, initializes the schema, and populates
    the scraping_targets table with seed URLs from each county's YAML file.
    """
    conn = None
    try:
        conn = await asyncpg.connect(dsn=DSN)
        logging.info("Successfully connected to the database.")

        # Initialize the database schema
        await database.init_db(conn)

        if not os.path.isdir(COUNTIES_DIR):
            logging.error(f"Counties directory not found at '{COUNTIES_DIR}'")
            return

        yaml_files = [f for f in os.listdir(COUNTIES_DIR) if f.endswith(('.yaml', '.yml'))]
        if not yaml_files:
            logging.warning(f"No YAML configuration files found in '{COUNTIES_DIR}'.")
            return

        for file_name in yaml_files:
            file_path = os.path.join(COUNTIES_DIR, file_name)
            with open(file_path, 'r') as f:
                config_data = yaml.safe_load(f)

                county_name = config_data.get('county_name')
                if not county_name:
                    logging.warning(f"Skipping {file_name}: missing 'county_name'.")
                    continue

                logging.info(f"Seeding data for {county_name}...")

                records_to_insert = []
                seed_targets = config_data.get('seed_targets', {})
                scrape_frequency = seed_targets.get('scrape_frequency', 'once')
                urls_by_category = seed_targets.get('urls', {})

                if not urls_by_category:
                    logging.warning(f"No 'seed_targets' or 'urls' found for {county_name} in {file_name}.")
                    continue

                for category, urls in urls_by_category.items():
                    for url in urls:
                        records_to_insert.append((county_name, url, category, 'pending', scrape_frequency))

                if records_to_insert:
                    await conn.executemany(
                        """
                        INSERT INTO scraping_targets (county_name, url, category, status, scrape_frequency)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (county_name, url) DO NOTHING
                        """,
                        records_to_insert
                    )
                    logging.info(f"-> Inserted {len(records_to_insert)} seed URLs for {county_name}.")

    except asyncpg.exceptions.PostgresError as e:
        logging.error(f"Database error: {e}")
    except FileNotFoundError:
        logging.error(f"Error reading config file at {file_path}")
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file {file_path}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            await conn.close()
            logging.info("Database connection closed.")

if __name__ == "__main__":
    # To run this script, you need to have the database service running.
    # Example: docker-compose up -d db
    logging.info("Starting database seeding process...")
    asyncio.run(seed_database())
    logging.info("Seeding process complete.")
