import os
from pathlib import Path

# --- PATH CONFIG ---
# Use pathlib for robust path construction.
# This assumes the script is run from the project's root directory.
BASE_DIR = Path(__file__).resolve().parent.parent

DB_FILE = BASE_DIR / "storage" / "henry_county_data.db"
DOWNLOAD_DIR = BASE_DIR / "downloads"
LOGS_DIR = BASE_DIR / "logs"

# --- SCRAPING TARGETS ---
URLS_TO_SCRAPE = {
    "government": [
        "https://www.henrycountyohio.gov/",
        "https://henrycountyohio.gov/BusinessDirectoryii.aspx",
        "https://henrycountyohio.gov/35/Business",
        "https://www.napoleonohio.com/",
        "https://www.henrycountyohio.gov/167/Airport",
        "https://villageofdeshler.com/",
        "https://benefits.ohio.gov/wps/portal/gov/obssp/help-center/contact-us/henry-county",
        "https://henrycohd.org/",
    ],
    "business_and_economic": [
        "https://www.henrycountychamber.org/member-directory/",
        "https://www.henryhas.com/agriculture-businesses/",
        "http://www.henrycountyhospital.org",
        "https://www.ohiobiz.com/",
        "https://www.toledoblade.com/business",
    ],
    "news_and_obituaries": [
        "https://www.loc.gov/item/sn86079021",
        "https://ldsgenealogy.com/OH/Henry-County-Newspapers-and-Obituaries.htm",
        "https://www.obitsarchive.com/obituaries/usa/ohio/napoleon/northwest-signal",
        "https://www.legacy.com/us/obituaries/local/ohio/henry-county",
        "https://www.legacy.com/us/obituaries/local/ohio/napoleon",
        "https://www.wtol.com/",
        "https://www.13abc.com/",
        "https://www.toledoblade.com/",
    ],
    "funeral_homes": [
        "https://www.zachrichfuneralhome.com/obituaries",
        "https://www.hoeningfuneralhome.com/obituaries/obituary-listings",
        "https://www.rodenbergergray.com/",
    ],
    "genealogy": [
         "https://henrycountyfamilies.org/index.php/henry-county-vital-records/",
    ],
    "rss_feeds": {
        "county_pages": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=76&CID=All-0",
        "county_agendas": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=65&CID=All-0",
        "county_alerts": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=63&CID=All-0",
        "county_calendar": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=58&CID=All-calendar.xml",
        "county_jobs": "https://henrycountyohio.gov/RSSFeed.aspx?CommunityJobs=False&ModID=66&CID=All-0",
        "county_news": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml",
        "county_photos": "https://henrycountyohio.gov/RSSFeed.aspx?ModID=53&CID=All-0",
        "supreme_court_happening": "https://www.supremecourt.ohio.gov/RSS/CNO/happening.aspx",
        "wtol_news": "https://feeds.feedblitz.com/wtol/news",
        "toledo_blade_news": "https://www.toledoblade.com/rss/",
    },
    "facebook_pages": [
        # Commented out as they require logins and specialized scraping
    ]
}

# --- SAFE FETCH CONFIG ---
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
