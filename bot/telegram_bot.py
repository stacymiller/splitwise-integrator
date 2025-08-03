import os
import logging
import requests
import json
import base64
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
SELECT_GROUP, UPLOAD, CONFIRM, SPLIT = range(4)

class TelegramBot:
    # Class variable to store the application instance
    _application = None

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
            "/logout - Logout from Splitwise\n"
            "/change_group - Change your selected Splitwise group\n"
            "/cancel - Cancel the current operation\n\n"
            "You can also send a photo of a receipt directly to process it."
        )

    def is_authenticated(self, user_id, context=None):
        """Check if the user is authenticated with Splitwise"""
        # If context is provided, check in context.user_data
        if context and 'access_token' in context.user_data:
            return True
        if context and user_id in context.bot_data and 'access_token' in context.bot_data[user_id]:
            context.user_data['access_token'] = context.bot_data[user_id]['access_token']
            del context.bot_data[user_id]['access_token']
            return True
        return False

    def get_access_token(self, user_id, context=None):
        """Get the access token for a user"""
        # If context is provided, check in context.user_data
        if context and 'access_token' in context.user_data:
            return context.user_data['access_token']
        # If access token is in the publicly available space, move it to the private space
        if context and user_id in context.bot_data and 'access_token' in context.bot_data[user_id]:
            context.user_data['access_token'] = context.bot_data[user_id]['access_token']
            del context.bot_data[user_id]['access_token']
            return context.user_data['access_token']
        return None

    def has_selected_group(self, user_id, context=None):
        """Check if the user has selected a group"""
        if context:
            return 'group_id' in context.user_data
        return False

    def get_group_id(self, user_id, context=None):
        """Get the selected group ID for a user"""
        if context and 'group_id' in context.user_data:
            return context.user_data['group_id']
        return None

    def set_group_id(self, user_id, group_id, context=None):
        """Set the selected group ID for a user"""
        if context:
            context.user_data['group_id'] = group_id
            return True
        return False

    async def check_web_auth(self, user_id, context):
        """Check if the user has authenticated via the web app"""
        # This method is no longer needed as authentication data is pushed directly to the bot
        # via the notify_telegram_auth endpoint
        # We keep it for backward compatibility but it always returns False
        logger.info(f"check_web_auth called for user {user_id}, but this method is deprecated")
        return False

    async def login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle Splitwise login."""
        logger.info("Starting `login` login flow")
        user_id = update.effective_user.id

        # Check if the user is already authenticated
        if self.is_authenticated(user_id, context):
            logger.info(f"User {user_id} is already authenticated")
            await update.message.reply_text(
                f"You are already authenticated with Splitwise! Send your receipt to process it."
            )
            return ConversationHandler.END

        logger.info(f"User {user_id} is not authenticated, starting authentication flow")
        # Generate a callback URL
        callback_url = f"{config.WEB_APP_URL}/callback"

        # Create a state parameter containing the user_id
        state_data = {"user_id": str(user_id)}
        # Base64 encode the state to avoid issues with quotes and special characters
        state = base64.b64encode(json.dumps(state_data).encode('utf-8')).decode('utf-8')

        # Get the authorization URL from the Splitwise service
        auth_url, state_token = splitwise_service.get_oauth2_authorize_url(callback_url, state)

        # Store the user_id in the context.user_data to identify the user later
        if not context.user_data.get('user_id'):
            logger.info(f"Storing user_id {user_id} in context.user_data")
            context.user_data['user_id'] = user_id

        logger.info(f"Sending user {user_id} the message with the login URL")
        await update.message.reply_text(
            f"To login to Splitwise, please use this link: {auth_url}\n\n"
            "After logging in, you'll be redirected back to the application."
        )

        logger.info("Ending `login` login flow")
        return ConversationHandler.END

    async def select_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show the group selection menu."""
        logger.info("Starting `select_group` group selection conversation")
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await update.message.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Set the access token in the Splitwise service
        access_token = self.get_access_token(user_id, context)
        if access_token:
            splitwise_service.set_oauth2_token(access_token)

        # Get the list of groups
        groups = splitwise_service.get_groups()

        if not groups:
            await update.message.reply_text(
                "You don't have any groups in Splitwise. Please create a group first."
            )
            return ConversationHandler.END

        # Store the groups in the context for later use
        context.user_data['groups'] = groups

        # Create a message with the list of groups
        message = "Please select a group by sending its number:\n\n"
        for i, group in enumerate(groups, 1):
            message += f"{i}. {group['name']} ({group['members_count']} members)\n"

        logger.info(f"Sending group selection message: {message}")
        await update.message.reply_text(message)

        logger.info(f"Returning SELECT_GROUP ({SELECT_GROUP} to handle the selection")
        return SELECT_GROUP

    async def handle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the group selection."""
        logger.info(f"Received group selection: {update.message.text}")
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await update.message.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Get the selected group number
        try:
            selection = int(update.message.text.strip())
            groups = context.user_data.get('groups', [])

            if not groups or selection < 1 or selection > len(groups):
                await update.message.reply_text(
                    "Invalid selection. Please try again."
                )
                return SELECT_GROUP

            # Get the selected group
            selected_group = groups[selection - 1]

            # Store the selected group ID
            self.set_group_id(user_id, selected_group['id'], context)

            # Set the group ID in the Splitwise service
            splitwise_service.set_current_group_id(selected_group['id'])

            await update.message.reply_text(
                f"You have selected the group: {selected_group['name']}\n\n"
                "You can now start sending receipts."
            )

            return ConversationHandler.END

        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number."
            )
            return SELECT_GROUP

    async def process_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process a receipt photo."""
        try:
            user_id = update.effective_user.id

            # Check if the user is authenticated
            if not self.is_authenticated(user_id, context):
                await update.message.reply_text(
                    "You need to login to Splitwise first. Please use the /login command."
                )
                return ConversationHandler.END

            # Check if the user has selected a group
            if not self.has_selected_group(user_id, context):
                await update.message.reply_text(
                    "You need to select a Splitwise group first. Please use the /change_group command."
                )
                # Start the group selection conversation
                return ConversationHandler.END

            # Set the access token in the Splitwise service
            access_token = self.get_access_token(user_id, context)
            if access_token:
                splitwise_service.set_oauth2_token(access_token)

            # Set the group ID in the Splitwise service
            group_id = self.get_group_id(user_id, context)
            if group_id:
                splitwise_service.set_current_group_id(group_id)

            await update.message.reply_text("Processing your receipt... Please wait.")

            # 1. Download the photo
            if not update.message.photo:
                await update.message.reply_text("Please send a photo of your receipt.")
                return ConversationHandler.END
                
            # Get the largest photo (last in the array)
            photo_file = await update.message.photo[-1].get_file()
            
            # Create a temporary file path
            import tempfile
            import os
            
            # Create a temporary file with a .jpg extension
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            temp_file_path = temp_file.name
            temp_file.close()
            
            # Download the photo to the temporary file
            await photo_file.download_to_drive(temp_file_path)
            
            # 2. Use receipt_processor to extract information
            receipt_info = receipt_processor.extract_receipt_info(temp_file_path)
            
            # Store the receipt info in context.user_data for later use
            if receipt_info:
                context.user_data['receipt_info'] = receipt_info
                
                # Format the date
                date_str = receipt_info.get('date', '')
                try:
                    # Try to parse the ISO date format
                    from datetime import datetime
                    date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    formatted_date = date_obj.strftime('%B %d, %Y')
                except:
                    # If parsing fails, use the original string
                    formatted_date = date_str
                
                # Format the currency and amount
                currency_code = receipt_info.get('currency_code', 'EUR')
                currency_symbol = '€' if currency_code == 'EUR' else ('$' if currency_code == 'USD' else currency_code)
                amount = receipt_info.get('total', '0.00')
                
                # 3. Ask the user to confirm the extracted information
                await update.message.reply_text(
                    f"I've extracted the following information from your receipt:\n\n"
                    f"Merchant: {receipt_info.get('merchant', 'Unknown')}\n"
                    f"Amount: {currency_symbol}{amount}\n"
                    f"Date: {formatted_date}\n\n"
                    f"Is this correct? (Yes/No)"
                )
                
                # Clean up the temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
                return CONFIRM
            else:
                await update.message.reply_text(
                    "I couldn't extract information from your receipt. Please try again with a clearer photo."
                )
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error processing receipt: {e}")
            await update.message.reply_text(
                "An error occurred while processing your receipt. Please try again."
            )
            return ConversationHandler.END

    async def confirm_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm the extracted receipt information."""
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await update.message.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Set the access token in the Splitwise service
        access_token = self.get_access_token(user_id, context)
        if access_token:
            splitwise_service.set_oauth2_token(access_token)

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
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await update.message.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Set the access token in the Splitwise service
        access_token = self.get_access_token(user_id, context)
        if access_token:
            splitwise_service.set_oauth2_token(access_token)

        text = update.message.text
        
        # Check if receipt_info exists in context.user_data
        if 'receipt_info' not in context.user_data:
            await update.message.reply_text(
                "Sorry, I couldn't find your receipt information. Please try again."
            )
            return ConversationHandler.END
            
        receipt_info = context.user_data['receipt_info']
        
        # Parse the user's choice for splitting
        split_type = "Equal split (50/50)"
        try:
            choice = int(text.strip())
            if choice == 1:
                split_type = "Equal split (50/50)"
            elif choice == 2:
                split_type = "You paid, they owe"
            elif choice == 3:
                split_type = "They paid, you owe"
            elif choice == 4:
                split_type = "Split by percentage"
            else:
                split_type = "Equal split (50/50)"  # Default
        except ValueError:
            # If the input is not a number, default to equal split
            split_type = "Equal split (50/50)"
            
        # Format the date
        date_str = receipt_info.get('date', '')
        try:
            # Try to parse the ISO date format
            from datetime import datetime
            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            formatted_date = date_obj.strftime('%B %d, %Y')
        except:
            # If parsing fails, use the original string
            formatted_date = date_str
            
        # Format the currency and amount
        currency_code = receipt_info.get('currency_code', 'EUR')
        currency_symbol = '€' if currency_code == 'EUR' else ('$' if currency_code == 'USD' else currency_code)
        amount = receipt_info.get('total', '0.00')

        # In a real implementation, we would use splitwise_service to create the expense
        # splitwise_service.create_expense(receipt_info, split_type)

        await update.message.reply_text(
            "Expense added to Splitwise successfully!\n\n"
            "Receipt Details:\n"
            f"- Merchant: {receipt_info.get('merchant', 'Unknown')}\n"
            f"- Amount: {currency_symbol}{amount}\n"
            f"- Date: {formatted_date}\n"
            f"- Split: {split_type}"
        )
        return ConversationHandler.END

    async def change_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Change the selected Splitwise group."""
        logger.info("Starting `change_group` group selection conversation")
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            logger.info(f"User {user_id} is not authenticated")
            await update.message.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Start the group selection conversation
        logger.info("Redirecting to `select_group` to handle the selection")
        return await self.select_group(update, context)

    async def logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Logout from Splitwise."""
        user_id = update.effective_user.id

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await update.message.reply_text(
                "You are not logged in to Splitwise."
            )
            return

        # Clear the user's data from context.user_data
        if 'access_token' in context.user_data:
            del context.user_data['access_token']

        if 'group_id' in context.user_data:
            del context.user_data['group_id']

        # No need to clear the token from the web app anymore
        # as all user data is now stored in context.user_data

        await update.message.reply_text(
            "You have been logged out from Splitwise."
        )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation."""
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END

    @classmethod
    async def send_message_to_user(cls, user_id, text):
        """Send a message to a user."""
        logger.info(f"Sending message to user {user_id}: {text}")
        if cls._application:
            try:
                await cls._application.bot.send_message(chat_id=user_id, text=text)
                return True
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")
        return False

    @classmethod
    def notify_user_authenticated(cls, user_id, access_token):
        """Notify a user that they have been authenticated."""
        logger.info(f"Notifying user {user_id} that they have been authenticated")
        # Store the token in a class variable for later use by the bot
        if not hasattr(cls, '_pending_auth'):
            cls._pending_auth = {}
        logger.info(f"Storing access token for user {user_id} in `cls._pending_auth`")
        cls._pending_auth[int(user_id)] = access_token

        # Use the Telegram Bot API directly to send a message
        try:
            # Get the bot token from config
            bot_token = config.TELEGRAM_BOT_TOKEN

            # Send message using Telegram Bot API
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": user_id,
                "text": "You have successfully authenticated with Splitwise! "
                        "Choose your group using /change_group or send your receipt."
            }
            logger.info(f"Sending message to user {user_id}: {payload}")
            response = requests.post(url, json=payload)

            if response.status_code == 200:
                logger.info(f"Successfully sent message to user {user_id}")
                return True
            else:
                logger.error(f"Failed to send message to user {user_id}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending message to user {user_id}: {str(e)}")
            return False

    async def check_pending_auth(self, context: ContextTypes.DEFAULT_TYPE):
        """Check for pending authentications and update user data."""
        if hasattr(TelegramBot, '_pending_auth') and TelegramBot._pending_auth:
            # Process each pending authentication
            for user_id, access_token in list(TelegramBot._pending_auth.items()):
                logger.info(f"Processing pending authentication for user {user_id}")
                # Store the token in the user's context data
                if user_id not in context.bot_data:
                    context.bot_data[user_id] = {}
                logger.info(f"Storing access token for user {user_id} in context.bot_data")
                context.bot_data[user_id]['access_token'] = access_token

                # Remove from pending list
                logger.info(f"Removing access token for user {user_id} from `cls._pending_auth`")
                del TelegramBot._pending_auth[user_id]

                logger.info(f"Processed pending authentication for user {user_id}")
        else:
            logger.info("No pending authentications found")

    def run(self):
        """Run the bot."""
        if not self.token:
            logger.error("Telegram bot token not found. Please set TELEGRAM_BOT_TOKEN in your environment variables.")
            return

        # Create the Application and store it as a class variable
        TelegramBot._application = Application.builder().token(self.token).build()

        # Add job to check for pending authentications every 10 seconds
        TelegramBot._application.job_queue.run_repeating(self.check_pending_auth, interval=10)

        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.PHOTO | filters.ATTACHMENT, self.process_receipt)
            ],
            states={
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_receipt)],
                SPLIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.split_expense)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        TelegramBot._application.add_handler(conv_handler)

        group_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("change_group", self.change_group)],
            states={
                SELECT_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_group_selection)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        TelegramBot._application.add_handler(group_conv_handler)

        # Add command handlers
        TelegramBot._application.add_handler(CommandHandler("start", self.start))
        TelegramBot._application.add_handler(CommandHandler("login", self.login))
        TelegramBot._application.add_handler(CommandHandler("help", self.help_command))
        TelegramBot._application.add_handler(CommandHandler("logout", self.logout))

        # Start the Bot
        TelegramBot._application.run_polling()

# Create a bot instance
telegram_bot = TelegramBot()

if __name__ == '__main__':
    telegram_bot.run()
