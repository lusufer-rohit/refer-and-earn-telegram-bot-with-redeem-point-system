import os
import logging
import sys
from threading import Thread

# Import the correct app and shared status
from app import app, bot_status
from bot import setup_bot
from config import FLASK_PORT, FLASK_HOST

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
# Silence noisy HTTP loggers that flood terminal with every API request
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def run_flask():
    """Run the Flask app"""
    # Use the app instance from app.py
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)

# Initialize the database
import database as db
db.init_database()
logger.info("Database initialized")

# Start bot in a separate thread
try:
    # bot_status is imported from app.py, so it's the SHARED object
    bot_thread = Thread(target=setup_bot, args=(bot_status,))
    bot_thread.daemon = True
    bot_thread.start()
    logger.info("Bot thread started")
except Exception as e:
    logger.error(f"Failed to start bot thread: {e}", exc_info=True)

# Start the application directly
if __name__ == "__main__":
    run_flask()
