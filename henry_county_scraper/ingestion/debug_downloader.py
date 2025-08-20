import asyncio
import aiohttp

async def debug_download():
    """
    A simple script to download a single, known-problematic URL
    and print the full exception if one occurs.
    """
    url = "https://henrycountyohio.gov/DocumentCenter/View/633/Precinct-15-HamlerMarion-Township-PDF"
    print(f"--- Attempting to download: {url} ---")

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

        # Create a connector with SSL verification disabled
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            async with session.get(url, timeout=60) as response:
                print(f"Response status: {response.status}")
                response.raise_for_status() # Raise an exception for bad status codes

                content = await response.read()
                print(f"Successfully downloaded {len(content)} bytes.")

    except Exception as e:
        print("\n--- ERROR ---")
        print(f"An exception of type {type(e).__name__} occurred.")
        print(f"Error details: {e}")
        print("\n--- END ERROR ---")

if __name__ == "__main__":
    asyncio.run(debug_download())
