-- schema.sql for Henry County Scraper (PostgreSQL)

-- Drop tables if they exist to ensure a clean slate on setup.
-- The "CASCADE" option will also drop any dependent objects.
DROP TABLE IF EXISTS scraping_targets CASCADE;
DROP TABLE IF EXISTS scraped_pages CASCADE;
DROP TABLE IF EXISTS downloaded_documents CASCADE;
DROP TABLE IF EXISTS business_listings CASCADE;
DROP TABLE IF EXISTS rss_articles CASCADE;


-- The master table for the scraping queue, to be updated by other agents.
CREATE TABLE scraping_targets (
    id SERIAL PRIMARY KEY,
    url VARCHAR(2048) NOT NULL UNIQUE,
    category VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending', -- e.g., pending, in_progress, completed, failed
    last_scraped_timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table to store information about every URL encountered.
CREATE TABLE scraped_pages (
    id SERIAL PRIMARY KEY,
    url VARCHAR(2048) NOT NULL UNIQUE,
    source_site VARCHAR(255),
    content_type VARCHAR(255),
    status VARCHAR(50) NOT NULL, -- e.g., 'processed_text', 'downloaded_binary', 'skipped_size', 'skipped_mime'
    text_content TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Table to track downloaded documents (binaries, PDFs, images for OCR).
CREATE TABLE downloaded_documents (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES scraped_pages(id) ON DELETE CASCADE,
    filepath VARCHAR(2048) NOT NULL,
    file_type VARCHAR(255),
    ocr_text TEXT,
    download_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Table for structured business listings.
CREATE TABLE business_listings (
    id SERIAL PRIMARY KEY,
    source VARCHAR(255) NOT NULL,
    business_name VARCHAR(512) NOT NULL,
    address TEXT,
    phone_number VARCHAR(50),
    website VARCHAR(2048),
    scraped_from_url VARCHAR(2048),
    -- To avoid duplicates from the same source
    UNIQUE(source, business_name)
);

-- Table for articles from RSS feeds.
CREATE TABLE rss_articles (
    id SERIAL PRIMARY KEY,
    source_feed VARCHAR(255) NOT NULL,
    title VARCHAR(1024) NOT NULL,
    link VARCHAR(2048) NOT NULL UNIQUE,
    summary TEXT,
    published_date VARCHAR(255), -- Stored as text as formats vary wildly
    scraped_timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Optional: Add indexes for faster queries on frequently searched columns.
CREATE INDEX idx_scraping_targets_status ON scraping_targets(status);
CREATE INDEX idx_scraped_pages_url ON scraped_pages(url);
CREATE INDEX idx_rss_articles_link ON rss_articles(link);
