import os
import yaml
import logging
from pathlib import Path

# --- PATH CONFIG ---
BASE_DIR = Path(__file__).resolve().parent.parent
COUNTIES_DIR = BASE_DIR / "ingestion" / "counties"
LOGS_DIR = BASE_DIR / "logs"
DOWNLOAD_DIR = BASE_DIR / "downloads"
STORAGE_DIR = BASE_DIR / "storage"

# --- GLOBAL SCRAPER CONFIG ---
MIME_TYPE_ALLOWLIST = [
    "text/html", "text/plain", "application/json", "application/xml",
    "application/rss+xml", "application/atom+xml", "image/svg+xml",
    "application/zip", "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
OCR_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/gif"]
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

def setup_logging(log_filename="scraper.log"):
    """Creates necessary directories, rotates old logs, and sets up process-safe logging."""
    from datetime import datetime

    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(STORAGE_DIR, exist_ok=True)

    log_file = LOGS_DIR / log_filename

    # Reset any existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(process)d - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

def load_county_configs():
    """Loads all county configuration files from the /counties directory."""
    configs = []
    if not COUNTIES_DIR.exists():
        os.makedirs(COUNTIES_DIR)
        return configs

    for filepath in COUNTIES_DIR.glob("*.yaml"):
        with open(filepath, 'r') as f:
            try:
                config_data = yaml.safe_load(f)
                if config_data:
                    configs.append(config_data)
            except yaml.YAMLError as e:
                print(f"Error loading YAML file {filepath}: {e}")
    return configs
