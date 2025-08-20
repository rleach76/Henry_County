import asyncpg
import os
import logging

# --- DATABASE CONFIG ---
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "password")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "henry_county_db")
DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Global connection pool variable
pool = None

async def create_connection_pool():
    """Creates the asyncpg connection pool."""
    global pool
    try:
        pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
        logging.info("Database connection pool created successfully.")
    except Exception as e:
        logging.critical(f"Failed to create database connection pool: {e}")
        raise

async def close_connection_pool():
    """Closes the asyncpg connection pool."""
    global pool
    if pool:
        await pool.close()
        logging.info("Database connection pool closed.")

async def init_db():
    """Initializes the database by connecting and running the schema.sql file."""
    try:
        dir_path = os.path.dirname(os.path.realpath(__file__))
        schema_path = os.path.join(dir_path, 'schema.sql')
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        # Use the pool to get a connection for initialization
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)
        logging.info("Database initialized successfully from schema.sql.")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to initialize database. {e}")
        raise

async def reset_stale_targets(county_name=None):
    """Resets stale targets using a connection from the pool."""
    try:
        async with pool.acquire() as conn:
            if county_name:
                query = "UPDATE scraping_targets SET status = 'pending' WHERE county_name = $1 AND status IN ('in_progress', 'failed')"
                result = await conn.execute(query, county_name)
            else:
                query = "UPDATE scraping_targets SET status = 'pending' WHERE status IN ('in_progress', 'failed')"
                result = await conn.execute(query)

            # The result from execute is a string like 'UPDATE 5'. We extract the number.
            num_updated = result.split()[-1]
            logging.info(f"Reset status to 'pending' for {num_updated} targets.")
    except Exception as e:
        logging.error(f"Failed to reset stale targets: {e}")
