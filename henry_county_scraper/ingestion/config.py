import os
import yaml
from pathlib import Path

# --- PATH CONFIG ---
# This establishes the base directory for the project.
BASE_DIR = Path(__file__).resolve().parent.parent
COUNTIES_DIR = BASE_DIR / "ingestion" / "counties"
LOGS_DIR = BASE_DIR / "logs"
DOWNLOAD_DIR = BASE_DIR / "downloads"

# --- GLOBAL SCRAPER CONFIG ---
MIME_TYPE_ALLOWLIST = [
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "image/svg+xml",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
OCR_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/gif"]
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

def load_county_configs():
    """
    Loads all county configuration files from the /counties directory.
    """
    configs = []
    if not COUNTIES_DIR.exists():
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
