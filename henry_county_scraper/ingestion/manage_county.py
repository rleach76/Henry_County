import argparse
import asyncio
import yaml
import sys
from pathlib import Path

# This is a standalone script, but we need to adjust the path
# to import from our sibling modules (config, database)
# This assumes the script is run from the project root directory
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ingestion import config
from ingestion import database

def create_yaml_file(county_name, seed_urls):
    """Creates a new YAML config file for a county."""
    county_slug = county_name.lower().replace(' ', '_')
    filepath = config.COUNTIES_DIR / f"{county_slug}.yaml"

    if filepath.exists():
        print(f"Warning: Config file for {county_name} already exists at {filepath}. Appending new URLs.")
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {
            'county_name': county_name,
            'seed_targets': {
                'scrape_frequency': 'always',
                'urls': {'government': []} # Start with a default category
            },
            'rss_feeds': {}
        }

    # Add new seed URLs, avoiding duplicates
    existing_urls = set(data['seed_targets']['urls'].get('government', []))
    for url in seed_urls:
        if url not in existing_urls:
            data['seed_targets']['urls'].setdefault('government', []).append(url)

    with open(filepath, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)

    print(f"Successfully created/updated config file: {filepath}")
    return list(seed_urls)

async def seed_urls_to_db(county_name, urls_to_seed):
    """Seeds a list of URLs for a specific county into the database."""
    if not urls_to_seed:
        print("No new URLs to seed.")
        return

    print(f"Seeding {len(urls_to_seed)} URLs for {county_name} into the database...")
    db_conn = None
    try:
        db_conn = await database.get_db_connection()

        records_to_insert = [
            (county_name, url, 'government', 'pending', 'always') for url in urls_to_seed
        ]

        await db_conn.executemany(
            """
            INSERT INTO scraping_targets (county_name, url, category, status, scrape_frequency)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (county_name, url) DO NOTHING
            """,
            records_to_insert
        )
        print("Database seeding complete.")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        if db_conn:
            await db_conn.close()

def main():
    """Main function to parse arguments and manage counties."""
    parser = argparse.ArgumentParser(description="County Scraper Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 'add' command
    add_parser = subparsers.add_parser("add", help="Add a new county and its seed URLs")
    add_parser.add_argument("--name", required=True, help="The name of the county (e.g., 'Fulton')")
    add_parser.add_argument("--seed-urls", required=True, nargs='+', help="One or more seed URLs for the county")

    args = parser.parse_args()

    if args.command == "add":
        print(f"Adding new county: {args.name}")
        new_urls = create_yaml_file(args.name, args.seed_urls)
        asyncio.run(seed_urls_to_db(args.name, new_urls))

if __name__ == "__main__":
    main()
