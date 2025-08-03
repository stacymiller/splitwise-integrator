import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Splitwise API configuration
SPLITWISE_CONSUMER_KEY = os.getenv('SPLITWISE_CONSUMER_KEY')
SPLITWISE_CONSUMER_SECRET = os.getenv('SPLITWISE_CONSUMER_SECRET')
SPLITWISE_GROUP_ID = os.getenv('SPLITWISE_GROUP_ID')

# OpenAI API configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Telegram Bot configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Web app configuration
WEB_APP_URL = os.getenv('WEB_APP_URL', 'http://localhost:5001')

# Flask configuration
UPLOAD_FOLDER = 'uploads'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
TEMPLATES_AUTO_RELOAD = True

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
