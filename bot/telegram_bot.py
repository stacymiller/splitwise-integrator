import base64
import datetime
import json
import logging
import mimetypes
import os

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

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
SELECT_GROUP, CONFIRM = range(2)

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

    async def extract_file_info(self, update: Update) -> str:
        """Extract file information from the message."""
        user_id = update.effective_user.id
        temp_file_path = None

        if update.message.photo:
            # Handle a photo: Get the largest photo (last in the array)
            file_obj = await update.message.photo[-1].get_file()
            mime_type = 'image/jpeg'
            suffix = '.jpg'
            original_filename = update.message.photo[-1].file_unique_id
            logger.info(f"Processing photo from user {user_id}")
        elif update.message.document:
            # Handle a document: Get the document file
            file_obj = await update.message.document.get_file()
            original_filename = update.message.document.file_name
            logger.info(f"Processing document '{original_filename}' from user {user_id}")

            mime_type = update.message.document.mime_type
            suffix = mimetypes.guess_extension(mime_type)
        else:
            logger.info(f"No photo or document found in message from user {user_id}")
            raise ValueError("I cannot find a photo in the message. Please send a photo or document of your receipt.")

        if not (mime_type.startswith('image/') or mime_type == 'application/pdf'):
            logger.warning(f"Unsupported file type: {mime_type}")
            raise ValueError(f"The file you sent is {mime_type}. I only support images and PDF files. "
                             f"Please try again with a different file type!")

        # Download the file to disk
        try:
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
            os.makedirs(uploads_dir, exist_ok=True)
            file_name = f"{user_id}_receipt_{datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S_%f')}{suffix}"
            file_path = os.path.join(uploads_dir, file_name)
            await file_obj.download_to_drive(file_path)
            logger.info(f"Downloaded {original_filename} to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error downloading file: {str(e)}")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up temporary file after error: {file_path}")
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up temporary file: {str(cleanup_error)}")
            raise ValueError("An error occurred while processing your file. Please try again with a different file.")

    async def process_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process a receipt photo or document (including PDF and various image formats)."""
        try:
            user_id = update.effective_user.id
            logger.info(f"Processing receipt for user {user_id}")

            # Check if the user is authenticated
            if self.is_authenticated(user_id, context):
                access_token = self.get_access_token(user_id, context)
                splitwise_service.set_oauth2_token(access_token)
            else:
                logger.info(f"User {user_id} is not authenticated")
                await update.message.reply_text(
                    "You need to login to Splitwise first. Please use the /login command."
                )
                return ConversationHandler.END

            # Check if the user has selected a group
            if self.has_selected_group(user_id, context):
                group_id = self.get_group_id(user_id, context)
                splitwise_service.set_current_group_id(group_id)
            else:
                logger.info(f"User {user_id} has not selected a group")
                await update.message.reply_text(
                    "You need to select a Splitwise group first. Please use the /change_group command."
                )
                # Start the group selection conversation
                return ConversationHandler.END

            await update.message.reply_text("Processing your receipt... Please wait.")

            try:
                logger.info("Looking for a file in the message")
                temp_file_path = await self.extract_file_info(update)
                context.user_data['receipt_file_path'] = temp_file_path
            except ValueError as e:
                logger.error(f"Error downloading file: {str(e)}")
                await update.message.reply_text(str(e))
                return ConversationHandler.END

            try:
                logger.info(f"Extracting receipt information from file: {temp_file_path}")
                receipt_info = receipt_processor.extract_receipt_info(temp_file_path)
                context.user_data['receipt_info'] = receipt_info
                logger.info(f"Successfully extracted receipt information: {receipt_info}")
            except Exception as e:
                logger.error(f"Error extracting receipt information: {str(e)}")
                await update.message.reply_text(str(e))
                return ConversationHandler.END

            # Ask the user to confirm the extracted information using inline buttons (Yes/No only)
            keyboard = [[
                InlineKeyboardButton("Yes", callback_data="yes"),
                InlineKeyboardButton("No", callback_data="no"),
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"I've extracted the following information from your receipt:\n\n"
                f"Merchant: {receipt_info.get('merchant', 'Unknown')}\n"
                f"Amount: {receipt_info.get('total', '0.00')}{receipt_info.get('currency_code', 'EUR')}\n"
                f"Date: {receipt_info['date'].strftime('%B %d, %Y')}\n\n"
                f"Is this correct?",
                reply_markup=reply_markup
            )

            return CONFIRM
        except Exception as e:
            logger.error(f"Error processing receipt: {e}")
            if 'receipt_file_path' in context.user_data and os.path.exists(context.user_data['receipt_file_path']):
                try:
                    os.remove(context.user_data['receipt_file_path'])
                    logger.info(f"Deleted persisted receipt file: {context.user_data['receipt_file_path']}")
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up persisted receipt file: {str(cleanup_error)}")
            await update.message.reply_text(
                "An error occurred while processing your receipt. Please try again."
            )
            return ConversationHandler.END

    async def confirm_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm the extracted receipt information."""
        user_id = update.effective_user.id
        # Target message for replies regardless of callback or message
        msg_target = update.callback_query.message if getattr(update, 'callback_query', None) else update.message

        # Helper to cleanup persisted receipt file & related context
        def _cleanup_persisted():
            receipt_file_path = context.user_data.get('receipt_file_path')
            if receipt_file_path:
                try:
                    import os
                    if os.path.exists(receipt_file_path):
                        os.unlink(receipt_file_path)
                        logger.info(f"Deleted persisted receipt file: {receipt_file_path}")
                except Exception as e:
                    logger.error(f"Failed to delete persisted receipt file {receipt_file_path}: {e}")
                finally:
                    context.user_data.pop('receipt_file_path', None)
            # Clear receipt_info as well at the end of the flow
            context.user_data.pop('receipt_info', None)

        # Check if the user is authenticated
        if not self.is_authenticated(user_id, context):
            await msg_target.reply_text(
                "You need to login to Splitwise first. Please use the /login command."
            )
            return ConversationHandler.END

        # Set the access token in the Splitwise service
        access_token = self.get_access_token(user_id, context)
        if access_token:
            splitwise_service.set_oauth2_token(access_token)

        cq = update.callback_query
        await cq.answer()
        # Hide the inline keyboard once it has been used
        try:
            await cq.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.warning(f"Failed to remove inline keyboard: {e}")
        data = (cq.data or '').lower()
        if data == 'yes':
            # Proceed to create the expense directly using the extracted split info from receipt_info
            if 'receipt_info' not in context.user_data:
                await msg_target.reply_text(
                    "Sorry, I couldn't find your receipt information. Please try again."
                )
                _cleanup_persisted()
                return ConversationHandler.END

            receipt_info = context.user_data['receipt_info']

            try:
                result = splitwise_service.create_expense(receipt_info)
            except Exception as e:
                logger.error(f"Error uploading expense: {str(e)}")
                await msg_target.reply_text(f"Error uploading expense: {str(e)}")
                _cleanup_persisted()
                return ConversationHandler.END

            if not result or 'human_readable_confirmation' not in result:
                await msg_target.reply_text(
                    "An error occurred while creating the expense. Please try again."
                )
                _cleanup_persisted()
                return ConversationHandler.END

            # Try to attach the receipt file to Splitwise expense if we have it
            receipt_file_path = context.user_data.get('receipt_file_path')
            if receipt_file_path:
                try:
                    splitwise_service.attach_receipt_to_expense(result['expense_id'], receipt_file_path)
                    attachment_note = "\nReceipt image/PDF has been attached to the expense."
                except Exception as attach_err:
                    logger.error(f"Failed to attach receipt for expense {result['expense_id']}: {attach_err}")
                    attachment_note = f"\nNote: failed to attach receipt: {attach_err}"
            else:
                attachment_note = "\nNote: No receipt file was found to attach."

            await msg_target.reply_text(
                "Expense added to Splitwise successfully!\n\n"
                f"{result['human_readable_confirmation']}"
                f"{attachment_note}"
            )
            _cleanup_persisted()
            return ConversationHandler.END
        else:
            await msg_target.reply_text(
                "I'm sorry about that. Please send the receipt again or try taking a clearer photo."
            )
            _cleanup_persisted()
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
                CONFIRM: [CallbackQueryHandler(self.confirm_receipt, pattern="^(yes|no)$")]
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
