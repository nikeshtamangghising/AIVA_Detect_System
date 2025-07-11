import logging
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import re

from telegram import Update, Message, User, Chat
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, JobQueue
)
from config import settings
from database.database import init_db, get_db, SessionLocal as Session
from database.models import IdentifierRecord, DuplicateAlert
from sqlalchemy import func

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=settings.LOG_LEVEL
)
logger = logging.getLogger(__name__)

class AIVABot:
    def __init__(self, token: str):
        """Initialize the bot."""
        self.application = Application.builder().token(token).build()
        self.start_time = datetime.now()
        self.self_ping_url = os.getenv('SELF_PING_URL')
        self._setup_handlers()
        self._setup_commands()
        logger.info("Bot initialized")
        
        # Initialize database
        try:
            init_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _setup_handlers(self):
        """Setup all command and message handlers."""
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("number", self.add_identifier))
        self.application.add_handler(CommandHandler("list", self.list_identifiers))
        self.application.add_handler(CommandHandler("list_data", self.list_identifiers))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("remove", self.remove_identifier))
        
        # Add message handler for processing messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        self.application.add_error_handler(self.error_handler)
        
        # Add job queue for self-ping
        self.job_queue = self.application.job_queue
        if self.job_queue and self.self_ping_url:
            self.job_queue.run_repeating(self.self_ping, interval=300.0, first=10.0)

    def _setup_commands(self):
        """Setup bot commands."""
        commands = [
            ("start", "Start the bot"),
            ("help", "Show help information"),
            ("number", "Add a number to monitor (e.g., /number 1234567890)"),
            ("list", "List all monitored numbers"),
            ("status", "Show bot status"),
            ("remove", "Remove a number (admin only)")
        ]
        self.application.bot.set_my_commands(commands)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a welcome message when the command /start is issued."""
        user = update.effective_user
        welcome_text = (
            f"👋 Hello {user.first_name}!\n\n"
            "I'm AIVA Detect Bot. I can help you monitor and detect duplicate identifiers.\n\n"
            "📋 *Available Commands:*\n"
            "/number <identifier> - Add an identifier to monitor\n"
            "/list - List all monitored identifiers\n"
            "/status - Show bot status\n"
            "/help - Show this help message"
        )
        
        if user.id in settings.ADMIN_IDS:
            welcome_text += "\n\n🔒 *Admin Commands:*\n"
            welcome_text += "/remove <id> - Remove an identifier (Admin only)\n"
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /help is issued."""
        help_text = (
            "🤖 *AIVA Detect Bot Help*\n\n"
            "I can help you monitor and detect duplicate identifiers.\n\n"
            "*Available Commands:*\n"
            "• /start - Start the bot and show welcome message\n"
            "• /help - Show this help message\n"
            "• /number <identifier> - Add an identifier to monitor\n"
            "• /list - List all monitored identifiers\n"
            "• /status - Show bot status and statistics"
        )
        
        if update.effective_user.id in settings.ADMIN_IDS:
            help_text += "\n\n*Admin Commands:*\n"
            help_text += "• /remove <id> - Remove an identifier"
        
        await update.message.reply_text(
            help_text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    def determine_identifier_type(self, identifier: str) -> str:
        """Determine the type of identifier based on its format."""
        # Simple check for email
        if '@' in identifier and '.' in identifier.split('@')[-1]:
            return 'email'
            
        # Check for potential phone number (digits only, 8-15 digits)
        if identifier.isdigit() and 8 <= len(identifier) <= 15:
            return 'phone'
            
        # Check for potential bank account number (usually 9-18 digits)
        if identifier.isdigit() and 9 <= len(identifier) <= 18:
            return 'bank_account'
            
        # Check for potential reference code (alphanumeric with dashes/underscores)
        if any(c.isalpha() for c in identifier) and any(c.isdigit() for c in identifier):
            return 'reference_code'
            
        # Default to 'other' for anything that doesn't match above patterns
        return 'other'

    async def add_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Add a new identifier to monitor."""
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide an identifier. Example: `/number 1234567890`",
                parse_mode='Markdown'
            )
            return
            
        identifier = ' '.join(context.args).strip()
        if not identifier:
            await update.message.reply_text("❌ Identifier cannot be empty.")
            return
            
        identifier_type = self.determine_identifier_type(identifier)
        
        try:
            with get_db() as db:
                # Check if identifier already exists
                existing = db.query(IdentifierRecord).filter(
                    IdentifierRecord.identifier == identifier,
                    IdentifierRecord.is_duplicate == False
                ).first()
                
                if existing:
                    await update.message.reply_text(
                        f"⚠️ This identifier is already being monitored."
                    )
                    return
                
                # Create new record
                new_record = IdentifierRecord(
                    identifier=identifier,
                    identifier_type=identifier_type,
                    user_id=update.effective_user.id,
                    is_duplicate=False
                )
                
                db.add(new_record)
                db.commit()
                
                await update.message.reply_text(
                    f"✅ Successfully added identifier: `{identifier}`\n"
                    f"Type: {identifier_type.upper() if identifier_type else 'UNKNOWN'}",
                    parse_mode='Markdown'
                )
                
                # Log the addition
                logger.info(f"New identifier added: {identifier} (Type: {identifier_type}) by user {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"Error in add_identifier: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while adding the identifier. Please try again later."
            )

    async def list_identifiers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """List all monitored identifiers."""
        try:
            with get_db() as db:
                # Get all non-duplicate identifiers
                records = db.query(IdentifierRecord).filter(
                    IdentifierRecord.is_duplicate == False
                ).order_by(IdentifierRecord.created_at.desc()).all()
                
                if not records:
                    await update.message.reply_text("No identifiers are currently being monitored.")
                    return
                
                # Format the response
                response = ["📋 *Monitored Identifiers*\n"]
                for i, record in enumerate(records, 1):
                    response.append(
                        f"{i}. `{record.identifier}`\n"
                        f"   Type: {record.identifier_type.upper() if record.identifier_type else 'UNKNOWN'}\n"
                        f"   Added: {record.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                        f"   ID: `{record.id}`"
                    )
                
                # Split long messages to avoid hitting Telegram's message length limit
                message = "\n\n".join(response)
                if len(message) > 4000:
                    # Split into multiple messages
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await update.message.reply_text(
                            chunk,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                else:
                    await update.message.reply_text(
                        message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                        
        except Exception as e:
            logger.error(f"Error in list_identifiers: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while fetching the identifier list. Please try again later."
            )

    async def remove_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Remove an identifier from monitoring (admin only)."""
        if update.effective_user.id not in settings.ADMIN_IDS:
            await update.message.reply_text("❌ This command is only available to administrators.")
            return
            
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide an ID to remove. Example: `/remove 123`\n"
                "Use `/list` to see all identifiers and their IDs.",
                parse_mode='Markdown'
            )
            return
            
        try:
            record_id = int(context.args[0])
            with get_db() as db:
                # Find and delete the record
                record = db.query(IdentifierRecord).get(record_id)
                if record:
                    db.delete(record)
                    db.commit()
                    await update.message.reply_text(
                        f"✅ Successfully removed identifier: `{record.identifier}`",
                        parse_mode='Markdown'
                    )
                    logger.info(f"Identifier {record_id} removed by admin {update.effective_user.id}")
                else:
                    await update.message.reply_text("❌ No identifier found with that ID.")
                    
        except ValueError:
            await update.message.reply_text("❌ Invalid ID format. Please provide a numeric ID.")
        except Exception as e:
            logger.error(f"Error in remove_identifier: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while removing the identifier. Please try again later."
            )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle any message that contains text but is not a command."""
        if not update.message or not update.message.text:
            return
            
        message = update.message
        text = message.text.strip()
        
        # Skip messages that start with a command
        if text.startswith('/'):
            return
            
        # Process the message to find potential identifiers
        try:
            # Simple extraction of potential identifiers (this can be enhanced)
            # For now, we'll just check the entire message as a potential identifier
            potential_identifiers = [text]
            
            for identifier in potential_identifiers:
                if not identifier.strip():
                    continue
                    
                with get_db() as db:
                    # Check if this identifier exists in our database
                    existing = db.query(IdentifierRecord).filter(
                        IdentifierRecord.identifier == identifier,
                        IdentifierRecord.is_duplicate == False
                    ).first()
                    
                    if existing:
                        # This is a duplicate!
                        await self.handle_duplicate(existing, identifier, message, context.bot, db, context)
                    
        except Exception as e:
            logger.error(f"Error in handle_message: {e}", exc_info=True)
            try:
                if update.effective_chat:
                    await update.message.reply_text(
                        "❌ An error occurred while processing your message. Please try again."
                    )
            except Exception as e2:
                logger.error(f"Failed to send error message: {e2}")

    async def handle_duplicate(self, existing_record, identifier: str, message: Message, bot, db: Session, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle a detected duplicate identifier."""
        logger.info(f"handle_duplicate: identifier={identifier}, chat_id={message.chat.id if hasattr(message, 'chat') and message.chat else None}")
        
        try:
            # Start a new nested transaction that we can roll back on error
            db.begin_nested()
            
            try:
                # Instead of creating a new record, we'll use the existing one
                # but still create an alert to track the duplicate detection
                
                # Create the duplicate alert
                alert = DuplicateAlert(
                    identifier=identifier,
                    original_id=existing_record.id,
                    status='pending'
                )
                
                db.add(alert)
                db.commit()
                logger.info(f"Successfully created duplicate alert for identifier: {identifier}")
                
            except Exception as e:
                # If anything goes wrong, roll back the nested transaction
                db.rollback()
                logger.error(f"Error creating duplicate alert for {identifier}: {e}", exc_info=True)
                # Re-raise to be caught by the outer exception handler
                raise
            
            # Get identifier type from the existing record
            identifier_type = existing_record.identifier_type or self.determine_identifier_type(identifier)
            
            # Prepare user information for the alert
            user = message.from_user if hasattr(message, 'from_user') and message.from_user else None
            username = f"@{user.username}" if user and user.username else (user.first_name if user else "a user")
            
            # Format the alert message
            alert_text = (
                "🚨 *DUPLICATE IDENTIFIER DETECTED* 🚨\n\n"
                f"⚠️ *TYPE:* {identifier_type.upper() if identifier_type else 'UNKNOWN'}\n"
                f"🔑 *Identifier:* `{identifier}`\n"
                f"📅 *First Seen:* {existing_record.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"👤 *Reported by:* {username}\n\n"
                "*Please verify this transaction before proceeding!*\n"
                "_This identifier has been previously processed._"
            )
            
            # Try to send the alert as a reply to the original message
            try:
                await message.reply_text(
                    alert_text,
                    parse_mode='Markdown',
                    reply_to_message_id=message.message_id if hasattr(message, 'message_id') else None,
                    disable_web_page_preview=True
                )
                logger.info(f"Alert sent for duplicate: {identifier} in chat_id={message.chat.id if hasattr(message, 'chat') and message.chat else None}")
                
            except Exception as e:
                logger.error(f"Failed to send alert as reply, trying direct message: {e}")
                try:
                    chat_id = message.chat.id if hasattr(message, 'chat') and message.chat else None
                    if chat_id:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=alert_text,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                        logger.info(f"Alert sent for duplicate (fallback): {identifier} in chat_id={chat_id}")
                except Exception as e2:
                    logger.error(f"Failed to send duplicate alert: {e2}")
                    # If all else fails, try to notify admins
                    await self.notify_admins(
                        bot,
                        f"⚠️ Failed to send duplicate alert for identifier {identifier} in chat {chat_id or 'unknown'}: {e2}"
                    )
                    
        except Exception as e:
            logger.error(f"Error in handle_duplicate: {e}", exc_info=True)
            try:
                if hasattr(message, 'chat') and message.chat:
                    await message.reply_text(
                        "❌ An error occurred while processing this identifier. The admin has been notified.",
                        parse_mode='Markdown'
                    )
                # Notify admins about the error
                await self.notify_admins(
                    bot,
                    f"❌ Error in handle_duplicate for identifier {identifier}: {str(e)}"
                )
            except Exception as e2:
                logger.error(f"Failed to send error notification: {e2}")

    async def notify_admins(self, bot, message: str) -> None:
        """Send a notification to all admin users."""
        if not hasattr(settings, 'admin_ids_list'):
            logger.error("ADMIN_IDS not properly configured in settings")
            return
            
        admin_ids = settings.admin_ids_list
        if not admin_ids:
            logger.warning("No admin IDs configured in ADMIN_IDS")
            return
            
        for admin_id in admin_ids:
            if not admin_id or not str(admin_id).isdigit():
                logger.warning(f"Skipping invalid admin ID: {admin_id}")
                continue
                
            try:
                await bot.send_message(
                    chat_id=int(admin_id),
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                logger.debug(f"Notification sent to admin {admin_id}")
            except Exception as e:
                if "chat not found" in str(e).lower():
                    logger.warning(f"Admin chat not found (ID: {admin_id}). They may need to start a chat with the bot first.")
                else:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show bot status and statistics."""
        try:
            with get_db() as db:
                # Get counts from database
                total_identifiers = db.query(IdentifierRecord).count()
                unique_identifiers = db.query(IdentifierRecord).filter(
                    IdentifierRecord.is_duplicate == False
                ).count()
                duplicates = total_identifiers - unique_identifiers
                
                # Get uptime
                uptime = datetime.now() - self.start_time
                days, seconds = uptime.days, uptime.seconds
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                
                # Get counts by identifier type
                type_counts = db.query(
                    IdentifierRecord.identifier_type,
                    func.count(IdentifierRecord.id)
                ).filter(
                    IdentifierRecord.is_duplicate == False
                ).group_by(IdentifierRecord.identifier_type).all()
                
                # Format type counts
                type_counts_text = "\n".join(
                    f"• {t[0].upper() if t[0] else 'UNKNOWN'}: {t[1]}" 
                    for t in sorted(type_counts, key=lambda x: x[1], reverse=True)
                )
                
                status_text = (
                    "🤖 *Bot Status*\n\n"
                    f"• *Uptime:* {days}d {hours}h {minutes}m\n"
                    f"• *Self-ping:* {'✅ Active' if self.self_ping_url else '❌ Inactive'}\n\n"
                    f"📊 *Statistics*\n"
                    f"• *Total Identifiers:* {total_identifiers}\n"
                    f"• *Unique Identifiers:* {unique_identifiers}\n"
                    f"• *Duplicates Detected:* {duplicates}\n\n"
                    f"📝 *Identifier Types*\n{type_counts_text}"
                )
                
                await update.message.reply_text(
                    status_text,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                
        except Exception as e:
            logger.error(f"Error in status: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while fetching status. Please try again later."
            )

    async def self_ping(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Ping the self-ping URL to keep the bot alive."""
        if not self.self_ping_url:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.self_ping_url) as response:
                    if response.status == 200:
                        logger.debug("Self-ping successful")
                    else:
                        logger.warning(f"Self-ping failed with status {response.status}")
        except Exception as e:
            logger.error(f"Error in self_ping: {e}")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the telegram.ext application with detailed logging."""
        # Log the error before we do anything else
        logger.error(
            "Exception while handling an update:",
            exc_info=context.error
        )
        
        # Try to get more context about the error
        error_info = {
            'error': str(context.error),
            'error_type': context.error.__class__.__name__,
            'update': str(update),
            'user_data': str(context.user_data),
            'chat_data': str(context.chat_data)
        }
        
        logger.error(f"Error details: {error_info}")
        
        # Try to notify the user about the error if we have a chat context
        try:
            if update and hasattr(update, 'effective_chat') and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ An error occurred while processing your request. The admin has been notified."
                )
                
            # Notify all admins about the error
            admin_message = (
                "⚠️ *Error in bot*\n\n"
                f"*Error:* {context.error.__class__.__name__}\n"
                f"*Details:* {str(context.error)}\n\n"
                f"*Update:* {str(update)[:200]}..."
            )
            
            await self.notify_admins(context.bot, admin_message)
            
        except Exception as e:
            logger.error(f"Error in error handler while notifying: {e}")


def get_application():
    """Create and configure the bot application."""
    token = os.getenv('BOT_TOKEN')
    if not token:
        error_msg = (
            "Error: BOT_TOKEN environment variable is not set.\n\n"
            "To fix this:\n"
            "1. Get your bot token from @BotFather on Telegram\n"
            "2. Add it to your environment variables:\n"
            "   - Local: Set BOT_TOKEN='your_token_here' in .env file\n"
            "   - Render: Add it in the Environment tab of your service settings\n"
            "   - Format: BOT_TOKEN=1234567890:ABCdefGHIjklmNOPQrstUVWXYZ"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    bot = AIVABot(token)
    return bot.application


def main():
    """Start the bot."""
    # Initialize database first
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    # Get the application
    application = get_application()
    
    # Determine running mode
    is_webhook = os.getenv('WEBHOOK_MODE', '').lower() == 'true'
    
    if is_webhook:
        # Webhook mode for production
        port = int(os.getenv('PORT', 8080))
        webhook_url = os.getenv('WEBHOOK_URL')
        secret_token = os.getenv('WEBHOOK_SECRET')
        
        if not webhook_url:
            raise ValueError("WEBHOOK_URL environment variable is required in webhook mode")
        
        # Log webhook configuration
        logger.info(f"Starting in WEBHOOK mode on port {port}")
        logger.info(f"Webhook URL: {webhook_url}")
        
        # Configure webhook
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            secret_token=secret_token,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    else:
        # Polling mode for development
        logger.info("Starting in POLLING mode")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )


if __name__ == "__main__":
    main()
