import multiprocessing
import subprocess
import sys
import logging
from pathlib import Path

# Adjust path to import from sibling modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

import asyncio
from ingestion import config
from ingestion import database

def run_worker(county_name):
    """
    Function to be executed by each process.
    It calls the worker script as a separate command-line process.
    """
    logging.info(f"Orchestrator: Spawning worker for {county_name} county.")
    try:
        command = [sys.executable, "-m", "henry_county_scraper.ingestion.worker", "--county", county_name]
        project_root = Path(__file__).resolve().parent.parent.parent

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=project_root
        )

        if result.returncode == 0:
            logging.info(f"Worker for {county_name} finished successfully.")
        else:
            logging.error(f"Worker for {county_name} failed with exit code {result.returncode}.")
            logging.error(f"[{county_name} STDERR]:\n{result.stderr}")

        if result.stdout:
            logging.debug(f"[{county_name} STDOUT]:\n{result.stdout}")

    except Exception as e:
        logging.critical(f"An unexpected error occurred while running worker for {county_name}: {e}")

async def main_async():
    """
    Main asynchronous orchestrator function.
    Launches parallel scrapers for each configured county.
    """
    config.setup_logging(log_filename="orchestrator.log")
    logging.info("--- Main Orchestrator Started ---")

    county_configs = config.load_county_configs()
    if not county_configs:
        logging.warning("No county configuration files found. Exiting.")
        return

    county_names = [cfg.get('county_name') for cfg in county_configs if cfg.get('county_name')]
    logging.info(f"Found configurations for counties: {', '.join(county_names)}")

    if not county_names:
        logging.warning("No counties with a 'county_name' key found in configs. Exiting.")
        return

    with multiprocessing.Pool(processes=len(county_names)) as pool:
        pool.map(run_worker, county_names)

    logging.info("--- All county workers have finished. Orchestrator shutting down. ---")

def main():
    """Synchronous wrapper for the main async function."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logging.info("Orchestrator shut down by user.")

if __name__ == "__main__":
    main()
