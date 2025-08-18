import multiprocessing
import subprocess
import sys
import logging
from pathlib import Path

# Adjust path to import from sibling modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ingestion import config
from ingestion import database

def run_worker(county_name):
    """
    Function to be executed by each process.
    It calls the worker script as a separate command-line process.
    """
    logging.info(f"Orchestrator: Spawning worker for {county_name} county.")
    try:
        # We use subprocess to call the worker script. This ensures each worker
        # has a clean, separate memory space.
        command = [sys.executable, "-m", "ingestion.worker", "--county", county_name]

        # We run the process and capture its output
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True, # This will raise an exception if the worker returns a non-zero exit code
            cwd=config.BASE_DIR.parent # Run from the project root
        )
        logging.info(f"Worker for {county_name} finished successfully.")
        logging.debug(f"[{county_name} STDOUT]:\n{result.stdout}")
        if result.stderr:
             logging.warning(f"[{county_name} STDERR]:\n{result.stderr}")

    except subprocess.CalledProcessError as e:
        logging.error(f"Worker for {county_name} failed with exit code {e.returncode}.")
        logging.error(f"[{county_name} STDERR]:\n{e.stderr}")
    except Exception as e:
        logging.critical(f"An unexpected error occurred while running worker for {county_name}: {e}")

def main():
    """
    Main orchestrator for launching parallel scrapers.
    """
    config.setup_logging() # Orchestrator has its own log
    logging.info("--- Main Orchestrator Started ---")

    # On startup, reset any jobs that were interrupted mid-run
    # asyncio.run(database.reset_stale_targets()) # This needs to be run in an async context, worker can handle it.

    county_configs = config.load_county_configs()
    if not county_configs:
        logging.warning("No county configuration files found in /counties directory. Exiting.")
        return

    county_names = [cfg.get('county_name') for cfg in county_configs if cfg.get('county_name')]
    logging.info(f"Found configurations for counties: {', '.join(county_names)}")

    processes = []
    for county_name in county_names:
        process = multiprocessing.Process(target=run_worker, args=(county_name,))
        processes.append(process)
        process.start()

    # Wait for all worker processes to complete
    for process in processes:
        process.join()

    logging.info("--- All county workers have finished. Orchestrator shutting down. ---")

if __name__ == "__main__":
    main()
