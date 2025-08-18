import asyncio
import logging
from playwright.async_api import async_playwright

async def main():
    """
    Debug script to get the HTML of the main RSS index page.
    """
    url = "https://henrycountyohio.gov/rss.aspx"
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info(f"--- Fetching HTML for: {url} ---")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            content = await page.content()
            print("--- START RSS INDEX HTML CONTENT ---")
            print(content)
            print("--- END RSS INDEX HTML CONTENT ---")
        except Exception as e:
            logging.error(f"Failed to fetch page: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
