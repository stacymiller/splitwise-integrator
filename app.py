import os
import threading
import logging
import config

from web.app import app as web_app

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

def cleanup():
    """Cleanup function to stop tunnel on exit"""
    global tunnel
    if tunnel:
        tunnel.stop()

if __name__ == '__main__':
    if config.MODE == config.AppMode.dev:
        from tunnel_manager import CloudflareTunnel, update_splitwise_callback
        import atexit

        logger.info("Development mode enabled - starting cloudflared tunnel...")
        tunnel = CloudflareTunnel(port=5001)

        atexit.register(cleanup)

        try:
            public_url = tunnel.start()
            config.WEB_APP_URL = public_url

            logger.info("=" * 60)
            logger.info("📝 TODO: Update the following:")
            logger.info(f"1. BotFather Mini App URL: {public_url} at http://t.me/BotFather")
            logger.info(f"2. Splitwise OAuth callback: {public_url}/callback at https://secure.splitwise.com/oauth_clients/8978/edit")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Failed to start tunnel: {e}")
            exit(1)

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
