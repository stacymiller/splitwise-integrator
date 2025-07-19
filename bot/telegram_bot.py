import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import config
from core.receipt_processor import receipt_processor
from core.splitwise_service import splitwise_service

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
UPLOAD, CONFIRM, SPLIT = range(3)

class TelegramBot:
    def __init__(self):
        # Get the Telegram bot token from the config
        self.token = config.TELEGRAM_BOT_TOKEN

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send a message when the command /start is issued."""
        user = update.effective_user
        await update.message.reply_text(
            f"Hi {user.first_name}! I'm the Splitwise Receipt Bot. "
            f"Send me a photo of a receipt, and I'll help you add it to Splitwise.\n\n"
            f"Use /help to see available commands."
        )
        return ConversationHandler.END

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /help is issued."""
        await update.message.reply_text(
            "Here are the available commands:\n\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/login - Login to Splitwise\n"
            "/cancel - Cancel the current operation\n\n"
            "You can also send a photo of a receipt directly to process it."
        )

    async def login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle Splitwise login."""
        # This is a placeholder for the Splitwise login functionality
        # The actual implementation would involve OAuth2 authentication
        await update.message.reply_text(
            "To login to Splitwise, please use this link: [Splitwise Login Link]\n\n"
            "After logging in, you'll be redirected back to the bot."
        )

    async def process_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process a receipt photo."""
        # This is a placeholder for the receipt processing functionality
        await update.message.reply_text("Processing your receipt... Please wait.")

        # In the actual implementation, we would:
        # 1. Download the photo
        # 2. Use receipt_processor to extract information
        # 3. Ask the user to confirm the extracted information

        await update.message.reply_text(
            "I've extracted the following information from your receipt:\n\n"
            "Merchant: Example Store\n"
            "Amount: €10.00\n"
            "Date: January 1, 2024\n\n"
            "Is this correct? (Yes/No)"
        )
        return CONFIRM

    async def confirm_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm the extracted receipt information."""
        text = update.message.text.lower()
        if text == 'yes':
            await update.message.reply_text(
                "Great! How would you like to split this expense?\n\n"
                "1. Equal split\n"
                "2. You paid, they owe\n"
                "3. They paid, you owe\n"
                "4. Split by percentage"
            )
            return SPLIT
        else:
            await update.message.reply_text(
                "I'm sorry about that. Please send the receipt again or try taking a clearer photo."
            )
            return ConversationHandler.END

    async def split_expense(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle expense splitting."""
        text = update.message.text

        # In the actual implementation, we would:
        # 1. Parse the user's choice
        # 2. Ask for additional information if needed
        # 3. Use splitwise_service to create the expense

        await update.message.reply_text(
            "Expense added to Splitwise successfully!\n\n"
            "Receipt Details:\n"
            "- Merchant: Example Store\n"
            "- Amount: €10.00\n"
            "- Date: January 1, 2024\n"
            "- Split: Equal split (50/50)"
        )
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation."""
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END

    def run(self):
        """Run the bot."""
        if not self.token:
            logger.error("Telegram bot token not found. Please set TELEGRAM_BOT_TOKEN in your environment variables.")
            return

        # Create the Application
        application = Application.builder().token(self.token).build()

        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start),
                MessageHandler(filters.PHOTO, self.process_receipt)
            ],
            states={
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_receipt)],
                SPLIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.split_expense)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        application.add_handler(conv_handler)

        # Add command handlers
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("login", self.login))

        # Start the Bot
        application.run_polling()

# Create a bot instance
telegram_bot = TelegramBot()

if __name__ == '__main__':
    telegram_bot.run()
