-- schema.sql for Henry County Scraper (PostgreSQL)

-- This schema is designed to be idempotent. Using `CREATE TABLE IF NOT EXISTS`
-- ensures that running the seeder multiple times will not cause errors or delete data.

-- Master queue for URLs to be scraped
CREATE TABLE IF NOT EXISTS scraping_targets (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    category VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    scrape_frequency VARCHAR(50) DEFAULT 'once',
    last_scraped_timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, url)
);

CREATE TABLE IF NOT EXISTS rss_feed_entries (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    feed_url TEXT NOT NULL,
    entry_id TEXT NOT NULL, -- The unique ID from the feed (e.g., guid)
    title TEXT,
    link TEXT,
    published_date TIMESTAMPTZ,
    summary TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, feed_url, entry_id)
);

-- Stores versioned text content from scraped pages/documents
CREATE TABLE IF NOT EXISTS scraped_pages (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source_site VARCHAR(255),
    content_type VARCHAR(255),
    status VARCHAR(50) NOT NULL,
    text_content TEXT,
    content_hash VARCHAR(64), -- SHA-256 hash of text_content
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(url, version)
);

-- Tracks downloaded binary files (parent record for images, zips, etc.)
CREATE TABLE IF NOT EXISTS downloaded_documents (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    page_id INTEGER REFERENCES scraped_pages(id) ON DELETE CASCADE,
    filepath VARCHAR(2048) NOT NULL,
    file_type VARCHAR(255),
    content_hash VARCHAR(64), -- SHA-256 hash of the file bytes
    ocr_text TEXT,
    download_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Stores structured business listing data
CREATE TABLE IF NOT EXISTS business_listings (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    business_name VARCHAR(512) NOT NULL,
    address TEXT,
    phone_number VARCHAR(50),
    website VARCHAR(2048),
    scraped_from_url VARCHAR(2048),
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(county_name, source, business_name)
);

-- Stores structured data from RSS feeds
CREATE TABLE IF NOT EXISTS rss_articles (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    source_feed VARCHAR(255) NOT NULL,
    title VARCHAR(1024) NOT NULL,
    link VARCHAR(2048) NOT NULL UNIQUE,
    summary TEXT,
    content_hash VARCHAR(64), -- SHA-256 hash of summary
    published_date VARCHAR(255),
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Stores text content from files found inside zip archives
CREATE TABLE IF NOT EXISTS archived_files (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    parent_zip_id INTEGER REFERENCES downloaded_documents(id) ON DELETE CASCADE,
    filename_in_zip VARCHAR(1024) NOT NULL,
    file_type VARCHAR(255),
    text_content TEXT,
    content_hash VARCHAR(64),
    processed_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Stores data from the Recorder's Office (Kofile)
CREATE TABLE IF NOT EXISTS recorder_records (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    document_number VARCHAR(255) NOT NULL,
    document_type VARCHAR(255),
    recording_date DATE,
    grantor TEXT, -- The seller or giver
    grantee TEXT, -- The buyer or receiver
    description TEXT,
    scraped_from_url TEXT,
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, document_number)
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_scraping_targets_county_status ON scraping_targets(county_name, status);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_county_url ON scraped_pages(county_name, url);
CREATE INDEX IF NOT EXISTS idx_rss_articles_county_link ON rss_articles(county_name, link);
CREATE INDEX IF NOT EXISTS idx_recorder_records_doc_number ON recorder_records(county_name, document_number);

-- Stores data from Sheriff Sales (RealAuction)
CREATE TABLE IF NOT EXISTS sheriff_sales (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    case_number VARCHAR(255) NOT NULL,
    sale_date TIMESTAMPTZ,
    property_address TEXT,
    plaintiff TEXT,
    defendant TEXT,
    appraisal_value NUMERIC(12, 2),
    status VARCHAR(100),
    scraped_from_url TEXT,
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, case_number, sale_date)
);

CREATE INDEX IF NOT EXISTS idx_sheriff_sales_case_number ON sheriff_sales(county_name, case_number);

-- Stores property data from the Auditor's Office (ARC)
CREATE TABLE IF NOT EXISTS auditor_properties (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    parcel_id VARCHAR(255) NOT NULL,
    property_address TEXT,
    owner_name TEXT,
    assessed_value_total NUMERIC(12, 2),
    tax_district VARCHAR(255),
    school_district VARCHAR(255),
    land_use_code VARCHAR(100),
    scraped_from_url TEXT,
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, parcel_id)
);

CREATE INDEX IF NOT EXISTS idx_auditor_properties_parcel_id ON auditor_properties(county_name, parcel_id);

-- Stores data from the Clerk of Courts (CourtView)
CREATE TABLE IF NOT EXISTS court_cases (
    id SERIAL PRIMARY KEY,
    county_name VARCHAR(255) NOT NULL,
    case_number VARCHAR(255) NOT NULL,
    case_type VARCHAR(100),
    filing_date DATE,
    plaintiffs TEXT,
    defendants TEXT,
    status VARCHAR(100),
    scraped_from_url TEXT,
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(county_name, case_number)
);

CREATE INDEX IF NOT EXISTS idx_court_cases_case_number ON court_cases(county_name, case_number);
