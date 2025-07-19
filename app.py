import os
import threading
import logging
import config

# Import from core module
from core.receipt_processor import receipt_processor
from core.splitwise_service import splitwise_service

# Import from web module
from web.app import app as web_app

# Import from bot module
from bot.telegram_bot import telegram_bot

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_web_app():
    """Start the Flask web application"""
    web_app.run(debug=False, host='0.0.0.0', port=5001)

def start_telegram_bot():
    """Start the Telegram bot"""
    telegram_bot.run()

if __name__ == '__main__':
    # Check if Telegram bot token is set
    telegram_token = config.TELEGRAM_BOT_TOKEN

    # Start the web app in a separate thread
    web_thread = threading.Thread(target=start_web_app)
    web_thread.daemon = True
    web_thread.start()

    logger.info("Web application started on http://0.0.0.0:5001")

    # Start the Telegram bot if token is available
    if telegram_token:
        logger.info("Starting Telegram bot...")
        start_telegram_bot()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Telegram bot will not be started.")
        # Keep the main thread running with the web app
        web_thread.join()
