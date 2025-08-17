import os

# --- PATH CONFIG ---
# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
# This makes the project more portable.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_FILE = os.path.join(BASE_DIR, "storage", "henry_county_data.db")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")


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
        "https://henrycohd.org/", # Added from new list
    ],
    "business_and_economic": [
        "https://www.henrycountychamber.org/member-directory/",
        "https://www.henryhas.com/agriculture-businesses/",
        "http://www.henrycountyhospital.org",
        "https://www.ohiobiz.com/",
        "https://www.toledoblade.com/business", # Added from new list
    ],
    "news_and_obituaries": [
        "https://www.loc.gov/item/sn86079021",
        "https://ldsgenealogy.com/OH/Henry-County-Newspapers-and-Obituaries.htm",
        "https://www.obitsarchive.com/obituaries/usa/ohio/napoleon/northwest-signal",
        "https://www.legacy.com/us/obituaries/local/ohio/henry-county",
        "https://www.legacy.com/us/obituaries/local/ohio/napoleon",
        "https://www.wtol.com/", # Added from new list
        "https://www.13abc.com/", # Added from new list
        "https://www.toledoblade.com/", # Added from new list
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
        "county_pages": "https://henrycountyohio.gov/rss.aspx?FeedType=Pages",
        "county_agenda": "https://henrycountyohio.gov/rss.aspx?FeedType=Agendas",
        "county_alerts": "https://henrycountyohio.gov/rss.aspx?FeedType=Alerts",
        "county_calendar": "https://henrycountyohio.gov/rss.aspx?FeedType=Calendar",
        "county_jobs": "https://henrycountyohio.gov/rss.aspx?FeedType=Jobs",
        "county_news_flash": "https://henrycountyohio.gov/rss.aspx?FeedType=NewsFlash",
        "county_photos": "https://henrycountyohio.gov/rss.aspx?FeedType=PhotoGallery",
        "supreme_court_happening": "https://www.supremecourt.ohio.gov/RSS/CNO/happening.aspx",
        "wtol_news": "https://feeds.feedblitz.com/wtol/news",
        "toledo_blade_news": "https://www.toledoblade.com/rss/",
    },
    "facebook_pages": [
        # Commented out as they require logins and specialized scraping
        # "https://www.facebook.com/HenryCountySheriffOH",
        # "https://www.facebook.com/HenryCountyEMA/",
        # "https://www.facebook.com/henrycountychamber/",
        # "https://www.facebook.com/HENRYHasIt/",
        # "https://www.facebook.com/napoleonohio/",
        # "https://www.facebook.com/deshlerohio/",
        # "https://www.facebook.com/LibertyCenterOhio/",
        # "https://www.facebook.com/NapoleonPublicLibrary/",
        # "https://www.facebook.com/rodenbergergray/",
        # "https://www.facebook.com/zachrichfuneralhome/",
    ]
}

# --- SAFE FETCH CONFIG ---
MIME_TYPE_ALLOWLIST = [
    "text/html",
    "text/plain",
    "application/json",
    "application/xml", # Important for RSS feeds
    "application/rss+xml", # Important for RSS feeds
    "application/atom+xml", # Important for RSS feeds
    "image/svg+xml", # SVGs are text-based XML
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", # .docx
]
OCR_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/gif"]
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
