import asyncpg
import os
import logging

# --- DATABASE CONFIG ---
# For a real application, these should come from environment variables or a secrets management system.
# For this task, we use defaults assuming a local Dockerized PostgreSQL instance.
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "password")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "henry_county_db")

# DSN (Data Source Name) connection string
DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

async def get_db_connection():
    """
    Returns a connection to the PostgreSQL database.
    The caller is responsible for closing the connection.
    """
    try:
        return await asyncpg.connect(dsn=DSN)
    except asyncpg.exceptions.InvalidPasswordError as e:
        logging.critical(f"Database connection failed: Invalid password. Please check credentials. {e}")
        raise
    except ConnectionRefusedError as e:
        logging.critical(f"Database connection failed: Connection refused. Is the database server running at {DB_HOST}:{DB_PORT}? {e}")
        raise
    except Exception as e:
        logging.critical(f"An unexpected error occurred while connecting to the database: {e}")
        raise

async def init_db():
    """
    Initializes the database by connecting to PostgreSQL and running the schema.sql file.
    """
    try:
        # Construct path to schema file
        dir_path = os.path.dirname(os.path.realpath(__file__))
        schema_path = os.path.join(dir_path, 'schema.sql')

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        conn = await get_db_connection()
        try:
            await conn.execute(schema_sql)
            logging.info("Database initialized successfully from schema.sql.")
        finally:
            await conn.close()

    except FileNotFoundError:
        logging.critical(f"CRITICAL: schema.sql not found at {schema_path}. Cannot initialize database.")
        raise
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to initialize database. {e}")
        raise

# Note: The individual scraper functions will need to be updated to use asyncpg's
# query syntax (e.g., using $1, $2 for placeholders instead of ?).
# This will be done when refactoring the scrapers themselves.
