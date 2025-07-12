import logging
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import re
from functools import wraps

from telegram import Update, Message, User, Chat, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, JobQueue
)
from config import settings
from database.database import init_db, get_db
from database.models import IdentifierRecord, DuplicateAlert
from sqlalchemy import func
from sqlalchemy.orm import Session

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=settings.LOG_LEVEL
)
logger = logging.getLogger(__name__)


def admin_only(func):
    """Decorator to restrict access to admin users only."""
    @wraps(func)
    async def wrapped(self: 'AIVABot', update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user or not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is only available to administrators.")
            return
        return await func(self, update, context, *args, **kwargs)
    return wrapped


class AIVABot:
    def __init__(self, token: str):
        """Initialize the bot."""
        self.token = token
        self.start_time = datetime.now()
        self.self_ping_url = os.getenv('SELF_PING_URL')
        self.application = (
            Application.builder()
            .token(token)
            .post_init(self.post_init)
            .build()
        )
        self._setup_handlers()
        logger.info("Bot initialized")
        
        # Initialize database
        try:
            init_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    async def post_init(self) -> None:
        """Post-initialization hook."""
        await self.setup_commands()
        
        # Add job queue for self-ping
        self.job_queue = self.application.job_queue
        if self.job_queue and self.self_ping_url:
            # Run self-ping every 5 minutes, starting 10 seconds after bot starts
            self.job_queue.run_repeating(
                self.self_ping, 
                interval=300.0,  # 5 minutes
                first=10.0,      # Start after 10 seconds
                name="self_ping"
            )
            logger.info(f"Self-ping job scheduled with URL: {self.self_ping_url}")
        else:
            if not self.self_ping_url:
                logger.warning("SELF_PING_URL not set, self-ping functionality disabled")
            if not self.job_queue:
                logger.error("Job queue not available, self-ping functionality disabled")
            
        logger.info("Bot post-initialization complete")

    def is_admin(self, user_id: int) -> bool:
        """Check if a user is an admin."""
        return user_id in settings.admin_ids_list

    async def setup_commands(self) -> None:
        """Set up bot commands."""
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help information"),
            BotCommand("add", "Add an identifier to monitor"),
            BotCommand("list_data", "List all monitored numbers"),
            BotCommand("status", "Show bot status"),
        ]
        await self.application.bot.set_my_commands(commands)

    def _setup_handlers(self):
        """Setup all command and message handlers."""
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("add", self.add_identifier))
        self.application.add_handler(CommandHandler("add_identifier", self.add_identifier))
        self.application.add_handler(CommandHandler("list", self.list_identifiers))
        self.application.add_handler(CommandHandler("list_data", self.list_identifiers))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("remove", self.remove_identifier))
        
        # Add message handler for processing messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        self.application.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a welcome message when the command /start is issued."""
        user = update.effective_user
        first_name = self.escape_markdown_v2(user.first_name)
        
        welcome_text = (
            fr"👋 *Hello {first_name}*\!\n\n"
            r"I'm *AIVA Detect Bot*\. I can help you monitor and detect duplicate identifiers\.\n\n"
            r"*Available commands:*\n"
            r"• /add \- Add an identifier to monitor\n"
            r"• /add\_identifier \- Same as /add\n"
            r"• /list \- List all monitored identifiers\n"
            r"• /list\_data \- Same as /list\n"
            r"• /status \- Show bot status\n"
            r"• /help \- Show help message"
        )
        
        # Add admin-only commands if user is admin
        if self.is_admin(user.id):
            welcome_text += r"\n\n*Admin commands:*\n"
            welcome_text += r"• /remove \<id\> \- Remove an identifier\n"
            welcome_text += r"• /status \- Show detailed bot statistics"
            
        await update.message.reply_text(
            welcome_text,
            parse_mode='MarkdownV2',
            disable_web_page_preview=True
        )
        
        logger.info(f"Start command received from user {user.id} ({user.username or user.first_name})")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /help is issued."""
        help_text = (
            "*🤖 AIVA Detect Bot Help*\n\n"
            "I can help you monitor and detect duplicate identifiers\.\n\n"
            "*📋 Available Commands:*\n"
            r"• /start \- Show welcome message\n"
            r"• /help \- Show this help message\n"
            r"• /add \<identifier\> \- Add any identifier to monitor \[text, numbers, codes, etc\.\]\n"
            r"• /add\_identifier \<identifier\> \- Same as /add\n"
            r"• /list \- List all monitored identifiers\n"
            r"• /list\_data \- Same as /list\n"
            r"• /status \- Show bot status and statistics"
        )
        
        user = update.effective_user
        if self.is_admin(user.id):
            help_text += r"\n\n*Admin commands:*\n"
            help_text += r"• /remove \<id\> \- Remove an identifier\n"
            help_text += r"• /status \- Show detailed bot statistics"
        
        help_text += r"\n\n*💡 Tip:* The bot will automatically detect duplicates in any message you send, not just when using commands\!"
        
        await update.message.reply_text(
            help_text,
            parse_mode='MarkdownV2',
            disable_web_page_preview=True
        )

    def determine_identifier_type(self, identifier: str) -> str:
        """
        Determine the type of identifier based on its format.
        Returns a string describing the identifier type.
        """
        # Remove any whitespace for type detection
        clean_identifier = ''.join(identifier.split())
        
        # Check for empty string
        if not clean_identifier:
            return 'unknown'
            
        # Check for email
        if '@' in clean_identifier and '.' in clean_identifier.split('@')[-1]:
            return 'email'
            
        # Check if it's all digits (could be phone, account number, etc.)
        if clean_identifier.isdigit():
            length = len(clean_identifier)
            if 8 <= length <= 15:
                return 'phone'
            elif 16 <= length <= 20:
                return 'account_number'
            elif length > 20:
                return 'large_number'
            return 'numeric'
            
        # Check for alphanumeric with special characters (common in reference codes)
        if any(c.isalnum() for c in clean_identifier):
            # If it contains both letters and numbers, it's likely a reference code
            if any(c.isalpha() for c in clean_identifier) and any(c.isdigit() for c in clean_identifier):
                return 'reference_code'
            # If it's just letters, it's a text identifier
            elif clean_identifier.isalpha():
                return 'text'
                
        # Check for UUID format
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if re.match(uuid_pattern, clean_identifier.lower()):
            return 'uuid'
            
        # Default to 'custom' for anything that doesn't match above patterns
        return 'custom'

    async def add_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Add a new identifier to monitor. Accepts any string value as an identifier."""
        if not context.args:
            await update.message.reply_text(
                r"❌ Please provide an identifier. Example: `/add ABC123` or `/add 9876543210`",
                parse_mode='Markdown'
            )
            return
            
        identifier = ' '.join(context.args).strip()
        if not identifier:
            await update.message.reply_text(r"❌ Identifier cannot be empty.")
            return
            
        # No need to validate format - accept any string
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
                        r"⚠️ This identifier is already being monitored."
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
                
                # Escape markdown special characters in the identifier
                escaped_identifier = self.escape_markdown_v2(identifier)
                
                await update.message.reply_text(
                    fr"✅ Successfully added identifier: `{escaped_identifier}`\n"
                    fr"Type: `{identifier_type.upper() if identifier_type else 'UNKNOWN'}`",
                    parse_mode='MarkdownV2',
                    disable_web_page_preview=True
                )
                
                # Log the addition
                logger.info(f"New identifier added: {identifier} (Type: {identifier_type}) by user {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"Error in add_identifier: {e}", exc_info=True)
            await update.message.reply_text(
                r"❌ An error occurred while adding the identifier. Please try again later.",
                parse_mode='Markdown'
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
                response = [r"*📋 Monitored Identifiers*\n\n"]
                for i, record in enumerate(records, 1):
                    # Escape all dynamic content
                    escaped_identifier = self.escape_markdown_v2(record.identifier)
                    escaped_type = self.escape_markdown_v2(record.identifier_type.upper() if record.identifier_type else 'UNKNOWN')
                    added_date = record.created_at.strftime('%Y-%m-%d %H:%M')
                    
                    response.append(
                        fr"{i}\. `{escaped_identifier}`\n"
                        fr"   *Type:* `{escaped_type}`\n"
                        fr"   *Added:* `{added_date}`\n"
                        fr"   *ID:* `{record.id}`"
                    )
                
                # Split long messages to avoid hitting Telegram's message length limit
                message = "\n\n".join(response)
                if len(message) > 4000:
                    # Split into multiple messages
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await update.message.reply_text(
                            chunk,
                            parse_mode='MarkdownV2',
                            disable_web_page_preview=True
                        )
                else:
                    await update.message.reply_text(
                        message,
                        parse_mode='MarkdownV2',
                        disable_web_page_preview=True
                    )
                        
        except Exception as e:
            logger.error(f"Error in list_identifiers: {e}", exc_info=True)
            await update.message.reply_text(
                r"❌ An error occurred while fetching the identifier list\. Please try again later\.",
                parse_mode='MarkdownV2'
            )

    @admin_only
    async def remove_identifier(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Remove an identifier from monitoring (admin only)."""
        if not context.args:
            await update.message.reply_text(
                r"❌ Please provide an ID to remove. Example: `/remove 123`\n"
                r"Use `/list` to see all identifiers and their IDs.",
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
                        fr"✅ Successfully removed identifier: `{record.identifier}`",
                        parse_mode='Markdown'
                    )
                    logger.info(f"Identifier {record_id} removed by admin {update.effective_user.id}")
                else:
                    await update.message.reply_text(r"❌ No identifier found with that ID.")
                    
        except ValueError:
            await update.message.reply_text(r"❌ Invalid ID format. Please provide a numeric ID.")
        except Exception as e:
            logger.error(f"Error in remove_identifier: {e}", exc_info=True)
            await update.message.reply_text(
                r"❌ An error occurred while removing the identifier. Please try again later."
            )

    def escape_markdown_v2(self, text: str) -> str:
        """Escape special characters for MarkdownV2."""
        if not text:
            return ""
        # Define all special characters that need to be escaped in MarkdownV2
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        # Use a list comprehension to build the escaped string
        return ''.join(f'\{char}' if char in escape_chars else char for char in text)

    def extract_identifiers(self, text: str) -> list[str]:
        """Extract potential identifiers from a message text."""
        # Remove any URLs to avoid false positives
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        
        # Split by common separators and filter out short strings
        separators = r'[\s\n\t\r,;|]+'
        potential = []
        
        # First, check the entire message as-is
        potential.append(text.strip())
        
        # Then check individual parts
        parts = re.split(separators, text)
        for part in parts:
            part = part.strip()
            # Only consider parts that look like potential identifiers
            if len(part) >= 6:  # Minimum length to avoid too many false positives
                potential.append(part)
        
        # Remove duplicates while preserving order
        seen = set()
        return [x for x in potential if not (x in seen or seen.add(x))]

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle any message that contains text but is not a command."""
        try:
            message = update.message
            if not message or not message.text:
                return
                
            text = message.text.strip()
            
            # Ignore commands (they're handled by command handlers)
            if text.startswith('/'):
                return
                
            # Extract potential identifiers from the message
            potential_identifiers = self.extract_identifiers(text)
            found_duplicates = False
            
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
                        found_duplicates = True
                        await self.handle_duplicate(existing, identifier, message, context.bot, db, context)
            
            # If we didn't find any duplicates, log that we processed the message
            if not found_duplicates:
                logger.debug(f"Processed message with no duplicates found: {text[:50]}...")
                    
        except Exception as e:
            logger.error(f"Error in handle_message: {e}", exc_info=True)
            try:
                if update.effective_chat:
                    await update.message.reply_text(
                        r"❌ An error occurred while processing your message\. Please try again\.",
                        parse_mode='MarkdownV2'
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
            
            # Escape all dynamic content
            escaped_identifier = self.escape_markdown_v2(identifier)
            escaped_type = self.escape_markdown_v2(identifier_type.upper() if identifier_type else 'UNKNOWN')
            escaped_username = self.escape_markdown_v2(username)
            first_seen = existing_record.created_at.strftime('%Y-%m-%d %H:%M')
            
            # Format the alert message with MarkdownV2
            alert_text = (
                r"*🚨 DUPLICATE IDENTIFIER DETECTED 🚨*\n\n"
                fr"⚠️ *TYPE\:* `{escaped_type}`\n"
                fr"🔑 *Identifier\:* `{escaped_identifier}`\n"
                fr"📅 *First Seen\:* `{first_seen}`\n"
                fr"👤 *Reported by\:* {escaped_username}\n\n"
                r"*Please verify this transaction before proceeding\!*\n"
                r"_This identifier has been previously processed\._"
            )
            
            # Try to send the alert as a reply to the original message
            try:
                await message.reply_text(
                    alert_text,
                    parse_mode='MarkdownV2',
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
                            parse_mode='MarkdownV2',
                            disable_web_page_preview=True
                        )
                        logger.info(f"Alert sent for duplicate (fallback): {identifier} in chat_id={chat_id}")
                except Exception as e2:
                    logger.error(f"Failed to send duplicate alert: {e2}")
                    # If all else fails, try to notify admins with plain text
                    await self.notify_admins(
                        bot,
                        f"⚠️ Failed to send duplicate alert for identifier {escaped_identifier} in chat {chat_id or 'unknown'}: {e2}",
                        use_markdown=False
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

    async def notify_admins(self, bot, message: str, use_markdown: bool = True) -> None:
        """Send a notification to all admin users.
        
        Args:
            bot: The bot instance
            message: The message to send
            use_markdown: Whether to parse the message as MarkdownV2
        """
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
            logger.warning("Self-ping URL not configured")
            return
            
        logger.info(f"Performing self-ping to {self.self_ping_url}")
        try:
            timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.self_ping_url) as response:
                    status = response.status
                    text = await response.text()
                    if status == 200:
                        logger.info(f"Self-ping successful: {status} - {text[:100]}")
                    else:
                        logger.warning(f"Self-ping failed with status {status}: {text[:200]}")
        except asyncio.TimeoutError:
            logger.error("Self-ping request timed out after 10 seconds")
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error during self-ping: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in self_ping: {e}", exc_info=True)
            # Try to restart the job if it fails
            try:
                if self.job_queue:
                    self.job_queue.run_repeating(
                        self.self_ping,
                        interval=300.0,
                        first=60.0,  # Try again in 1 minute
                        name="self_ping_retry"
                    )
            except Exception as restart_error:
                logger.error(f"Failed to restart self-ping job: {restart_error}")

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
            'update': str(update)[:500] if update else 'None',  # Limit length
            'user_data': str(context.user_data)[:200] if context.user_data else '{}',
            'chat_data': str(context.chat_data)[:200] if context.chat_data else '{}'
        }
        
        logger.error(f"Error context: {error_info}")
        
        try:
            # Try to reply to the message that caused the error
            if update and hasattr(update, 'message') and update.message:
                await update.message.reply_text(
                    text="❌ An error occurred while processing your request. The admin has been notified.",
                    parse_mode='Markdown'
                )
                
            # Notify all admins about the error
            admin_message = (
                "⚠️ *Bot Error* ⚠️\n\n"
                f"*Type:* {context.error.__class__.__name__}\n"
                f"*Error:* {str(context.error)[:200]}"
            )
            
            # Truncate the update info to avoid message too long errors
            if update:
                update_info = str(update)[:150]
                if len(str(update)) > 150:
                    update_info += '...'
                admin_message += f"\n\n*Update:* `{update_info}`"
            
            await self.notify_admins(context.bot, admin_message)
            
        except Exception as e:
            logger.error(f"Error in error handler while notifying: {e}")
            # Try to log the original error at least
            try:
                logger.error(f"Original error: {str(context.error)}")
                if update:
                    logger.error(f"Update that caused error: {str(update)[:500]}")
            except Exception as log_err:
                logger.error(f"Failed to log error details: {log_err}")


def get_application() -> Application:
    """Create and configure the Telegram application."""
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set")
    
    bot = AIVABot(token)
    return bot.application


async def setup_webhook(application, webhook_url: str, secret_token: str) -> None:
    """Set up the webhook with the given URL and secret token."""
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=secret_token,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )
    logger.info("Webhook set successfully")

async def run_webhook(application, port: int, webhook_url: str, secret_token: str) -> None:
    """Run the application in webhook mode."""
    await application.initialize()
    await setup_webhook(application, webhook_url, secret_token)
    await application.start()
    
    # Start the webhook server
    await application.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="",
        webhook_url=webhook_url,
        secret_token=secret_token,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )
    logger.info("Bot is running in webhook mode")
    
    # Keep the application running
    while True:
        await asyncio.sleep(3600)  # Sleep for 1 hour

def run_polling_mode(application: Application):
    """Run the bot in polling mode for development."""
    logger.info("Starting in POLLING mode")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

async def run_webhook_mode(application: Application):
    """Configure and run the bot in webhook mode for production."""
    port = int(os.getenv('PORT', 10000))
    webhook_url = os.getenv('WEBHOOK_URL')
    secret_token = os.getenv('WEBHOOK_SECRET')

    if not secret_token:
        raise ValueError("WEBHOOK_SECRET environment variable is required in webhook mode")

    if not webhook_url:
        render_external_url = os.getenv('RENDER_EXTERNAL_URL')
        if render_external_url:
            webhook_url = f"{render_external_url}/webhook"
        else:
            raise ValueError("WEBHOOK_URL environment variable is required in webhook mode")
    
    logger.info(f"Starting in WEBHOOK mode on port {port}")
    logger.info(f"Webhook URL: {webhook_url}")
    
    await run_webhook(application, port, webhook_url, secret_token)

def main():
    """Start the bot."""
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    application = get_application()
    
    if 'RENDER' in os.environ or os.getenv('WEBHOOK_MODE', '').lower() == 'true':
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(run_webhook_mode(application))
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            # Graceful shutdown
            if loop.is_running():
                loop.run_until_complete(application.stop())
                loop.run_until_complete(application.shutdown())
            loop.close()
    else:
        run_polling_mode(application)


if __name__ == "__main__":
    main()
