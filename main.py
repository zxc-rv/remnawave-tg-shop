import asyncio
import logging
import signal
import sys

from dotenv import load_dotenv

from bot.main_bot import run_bot
from config.settings import get_settings, Settings
from db.database_setup import init_db, init_db_connection


# Global variable to track shutdown
shutdown_event = None


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logging.info(f"Received signal {signum}. Initiating graceful shutdown...")
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()


async def main():
    global shutdown_event

    load_dotenv()
    settings = get_settings()

    session_factory = init_db_connection(settings)
    if not session_factory:
        logging.critical(
            "Failed to initialize DB connection and session factory. Exiting.")
        return

    await init_db(settings, session_factory)

    # Create shutdown event
    shutdown_event = asyncio.Event()

    # Set up signal handlers for graceful shutdown
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logging.info("Signal handlers registered for SIGTERM and SIGINT")
    else:
        # For Windows, we'll rely on KeyboardInterrupt handling
        logging.info("Windows platform detected, relying on KeyboardInterrupt handling")

    try:
        await run_bot(settings, shutdown_event)
    except asyncio.CancelledError:
        logging.info("Main task was cancelled")
    except Exception as e:
        logging.error(f"Error in main: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped manually")
    except Exception as e_global:
        logging.critical(f"Global unhandled exception in main: {e_global}",
                         exc_info=True)
        sys.exit(1)
