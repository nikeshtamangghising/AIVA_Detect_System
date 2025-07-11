import logging
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any
import re

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, JobQueue
)
from config import settings
from database.database import init_db, get_db
from database.models import NumberRecord, DuplicateAlert

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=settings.LOG_LEVEL
)
logger = logging.getLogger(__name__)

# No pattern validation needed as per requirements

class AIVABot:
    def __init__(self):
        """Initialize the bot."""
        # Configure application with persistence and context types
        self.application = (
            Application.builder()
            .token(settings.BOT_TOKEN)
            .persistence(None)  # Disable persistence to avoid conflicts
            .concurrent_updates(True)  # Handle updates concurrently
            .build()
        )
        
        self.start_time = datetime.now()
        self.self_ping_url = getattr(settings, 'SELF_PING_URL', None)
        self.setup_handlers()
        self.setup_commands()
        
        # Schedule self-ping job if URL is provided
        if self.self_ping_url:
            self.application.job_queue.run_repeating(
                self.self_ping,
                interval=timedelta(minutes=25),  # Ping every 25 minutes (under 30 min free tier limit)
                first=10  # Start after 10 seconds
            )
        
    def setup_handlers(self):
        """Setup all command and message handlers."""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("number", self.add_number))
        # Support both /list_data and /listdata
        self.application.add_handler(CommandHandler("list_data", self.list_data))
        self.application.add_handler(CommandHandler("listdata", self.list_data))  # Alias without underscore
        self.application.add_handler(CommandHandler("remove", self.remove_number))
        self.application.add_handler(CommandHandler("status", self.status))
        
        # Message handler for phone number detection
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_message
        ))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    def setup_commands(self):
        """Setup bot commands for the menu."""
        commands = [
            ("start", "Start the bot"),
            ("help", "Show help information"),
            ("number", "Add number to watchlist"),
            ("list_data", "List all watched numbers"),
            ("remove", "Remove a number from watchlist"),
        ]
        
        # Set commands using set_my_commands
        async def set_commands():
            await self.application.bot.set_my_commands(
                [("/" + cmd, desc) for cmd, desc in commands]
            )
        
        self.application.job_queue.run_once(lambda _: set_commands(), 0)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a welcome message when the command /start is issued."""
        user = update.effective_user
        await update.message.reply_text(
            f'Hi {user.first_name}! I am AIVA Detect System.\n\n'
            'I help detect and prevent duplicate payments in your groups.\n\n'
            'Add me to your group and I will start monitoring for duplicate payments.\n\n'
            'Use /help to see all available commands.'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /help is issued."""
        help_text = (
            "🤖 *AIVA Detect System* 🤖\n\n"
            "*Available Commands:*\n"
            "• /start - Start the bot\n"
            "• /help - Show help\n"
            "• /status - Show status\n\n"
            "*Admin Commands:*\n"
            "• /number <number> - Add number to watchlist\n"
            "• /list_data - List all watched numbers\n"
            "• /remove <ID> - Remove a number from watchlist\n\n"
            "*How It Works:*\n"
            "1. Add numbers with `/number <number>`\n"
            "2. Check numbers with `/list_data`\n"
            "3. I'll notify about duplicates"
        )
        try:
            await update.message.reply_text(help_text, parse_mode='Markdown')
        except Exception as e:
            # Fallback to plain text if Markdown fails
            logging.warning(f"Markdown error: {e}")
            await update.message.reply_text(help_text.replace('*', '').replace('_', ''), parse_mode=None)
            
    async def remove_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove a number from the watchlist by ID."""
        if not context.args:
            await update.message.reply_text(
                "Please provide the ID of the number to remove.\n"
                "Example: `/remove 123`\n\n"
                "Use `/list_data` to see all numbers and their IDs.",
                parse_mode='Markdown'
            )
            return
            
        try:
            number_id = int(context.args[0])
            with get_db() as db:
                # Try to find the number record
                record = db.query(NumberRecord).filter_by(id=number_id, is_duplicate=False).first()
                
                if not record:
                    await update.message.reply_text("❌ Number not found. Use `/list_data` to see available numbers.", parse_mode='Markdown')
                    return
                
                # Delete the record
                db.delete(record)
                db.commit()
                
                await update.message.reply_text(f"✅ Successfully removed number `{record.number}` from the watchlist.", parse_mode='Markdown')
                
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Please provide a valid number ID.")
        except Exception as e:
            logger.error(f"Error removing number: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ An error occurred while removing the number. Please try again.")
    
    async def new_chat_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new chat members event."""
        for member in update.message.new_chat_members:
            if member.id == context.bot.id:
                # Bot was added to a group
                chat = update.effective_chat
                await self.handle_bot_added(chat, context.bot)
                break
    
    async def handle_bot_added(self, chat, bot):
        """Handle the event when bot is added to a group."""
        # Send welcome message to the group
        welcome_text = (
            "👋 *Welcome to AIVA Detect System!*\n\n"
            "I'll help you detect and prevent duplicate payments in this group.\n\n"
            "*How It Works:*\n"
            "1. Add me to your group\n"
            "2. I'll automatically detect numbers in messages\n"
            "3. If a duplicate number is found, I'll notify the group\n\n"
            "*Note:* Only group admins can manage my settings."
        )
        await bot.send_message(
            chat_id=chat.id,
            text=welcome_text,
            parse_mode='Markdown'
        )
        
        # Send private message to admins
        admins = await chat.get_administrators()
        for admin in admins:
            try:
                admin_text = (
                    f"👋 Hello! I've been added to *{chat.title}*.\n\n"
                    "*Admin Controls:*\n"
                    "• Use /number to add numbers to watchlist\n"
                    "• Use /list_data to view all watched numbers\n\n"
                    "I'll notify this group if I detect any duplicate numbers."
                )
                await bot.send_message(
                    chat_id=admin.user.id,
                    text=admin_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send admin message: {e}")
    
    # Payment detection and database methods will be added here
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and send a message to the user."""
        # Log the error
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # Try to send a message to the user
        try:
            # If we're handling a message, try to reply to it
            if update and hasattr(update, 'message') and update.message:
                await update.message.reply_text(
                    "❌ An unexpected error occurred. The admin has been notified."
                )
            # If we're in a callback query, answer it
            elif update and hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.answer(
                    "❌ An error occurred. Please try again.",
                    show_alert=True
                )
        except Exception as e:
            logger.error(f"Error in error handler while sending message: {e}")
        
        # Notify admins about the error
        try:
            error_message = (
                f"⚠️ *Error in bot* ⚠️\n\n"
                f"*Error:* {context.error.__class__.__name__}\n"
                f"*Message:* {str(context.error)}\n"
            )
            
            # Add update info if available
            if update and hasattr(update, 'effective_chat'):
                error_message += f"\n*Chat:* {update.effective_chat.title if hasattr(update.effective_chat, 'title') else 'Private'}"
                error_message += f"\n*User:* @{update.effective_user.username if update.effective_user.username else update.effective_user.id}"
            
            # Send to all admins
            for admin_id in settings.ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=error_message,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send error notification to admin {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in error handler while notifying admins: {e}")
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status and statistics."""
        try:
            with get_db() as db:
                # Get counts from database
                total_numbers = db.query(NumberRecord).count()
                unique_numbers = db.query(NumberRecord).filter(
                    NumberRecord.is_duplicate == False
                ).count()
                duplicates = total_numbers - unique_numbers
                
                # Calculate uptime
                uptime = datetime.now() - self.start_time
                hours, remainder = divmod(int(uptime.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                days, hours = divmod(hours, 24)
                
                # Format status message
                status_message = (
                    f"🤖 *AIVA Detect System Status*\n\n"
                    f"🕒 *Uptime:* {days}d {hours}h {minutes}m {seconds}s\n"
                    f"📊 *Numbers Tracked:* {unique_numbers}\n"
                    f"🔄 *Duplicates Detected:* {duplicates}\n"
                    f"📅 *Last Started:* {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    "✅ *Bot is running smoothly*"
                )
                
                # Send status message
                await update.message.reply_text(
                    status_message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                
        except Exception as e:
            logger.error(f"Error in status command: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Could not retrieve status information. Please try again later."
            )
    
    async def list_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all watched numbers."""
        try:
            with get_db() as db:
                # Get all non-duplicate records
                records = db.query(NumberRecord).filter(
                    NumberRecord.is_duplicate == False
                ).order_by(NumberRecord.created_at.desc()).all()
                
                if not records:
                    await update.message.reply_text("No numbers in the watchlist yet.")
                    return
                
                # Format the message
                message = ("📋 *Watched Numbers*\n\n" +
                         "\n".join(
                             f"{i+1}. `{record.number}` (ID: {record.id})"
                             for i, record in enumerate(records)
                         ) +
                         "\n\nUse `/remove <ID>` to remove a number from the watchlist.")
                
                # Send the message
                try:
                    await update.message.reply_text(
                        message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    # Fallback to plain text if markdown fails
                    logger.warning(f"Markdown error in list_data: {e}")
                    plain_message = message.replace('*', '').replace('`', '')
                    await update.message.reply_text(
                        plain_message,
                        disable_web_page_preview=True
                    )
                    
        except Exception as e:
            logger.error(f"Error in list_data: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while fetching the watchlist. Please try again later."
            )
    
    async def add_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a number to the watchlist."""
        if not context.args:
            await update.message.reply_text(
                "Please provide a number.\n"
                "Example: `/number 9841234567`\n\n"
                "Use /list_data to see all watched numbers.",
                parse_mode='Markdown'
            )
            return
                
        number = ' '.join(context.args)
        
        # Add to database
        with get_db() as db:
            # Check if already exists
            exists = db.query(NumberRecord).filter(
                NumberRecord.number == number,
                NumberRecord.is_duplicate == False
            ).first()
                
            if exists:
                await update.message.reply_text("ℹ️ This number is already in the watchlist.")
                return
                    
            # Add new number
            new_record = NumberRecord(
                number=number,
                user_id=update.effective_user.id,
                group_id=str(update.effective_chat.id) if update.effective_chat else None,
                is_duplicate=False
            )
            db.add(new_record)
            db.commit()
                
            await update.message.reply_text("✅ Number added to watchlist successfully!")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages and detect numbers."""
        if not update.message or not update.message.text:
            return
            
        message = update.message
        text = message.text
        
        # Skip if message is from a channel
        if message.sender_chat and message.sender_chat.type == "channel":
            return
            
        # Check for numbers in the message
        # Using a simple regex to find potential numbers
        # This is a basic pattern and might need adjustment based on your needs
        numbers = re.findall(r'\b\d{10,}\b', text)
        
        if not numbers:
            return
    
async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 *AIVA Detect System* 🤖\n\n"
        "*Available Commands:*\n"
        "• /start - Start the bot\n"
        "• /help - Show help\n"
        "• /status - Show status\n\n"
        "*Admin Commands:*\n"
        "• /number <number> - Add number to watchlist\n"
        "• /list_data - List all watched numbers\n"
        "• /remove <ID> - Remove a number from watchlist\n\n"
        "*How It Works:*\n"
        "1. Add numbers with `/number <number>`\n"
        "2. Check numbers with `/list_data`\n"
        "3. I'll notify about duplicates"
    )
    try:
        await update.message.reply_text(help_text, parse_mode='Markdown')
    except Exception as e:
        # Fallback to plain text if Markdown fails
        logging.warning(f"Markdown error: {e}")
        await update.message.reply_text(help_text.replace('*', '').replace('_', ''), parse_mode=None)
            
async def remove_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a number from the watchlist by ID."""
    if not context.args:
        await update.message.reply_text(
            "Please provide the ID of the number to remove.\n"
            "Example: `/remove 123`\n\n"
            "Use `/list_data` to see all numbers and their IDs.",
            parse_mode='Markdown'
        )
        return
            
    try:
        number_id = int(context.args[0])
        with get_db() as db:
            # Try to find the number record
            record = db.query(NumberRecord).filter_by(id=number_id, is_duplicate=False).first()
                
            if not record:
                await update.message.reply_text("❌ Number not found. Use `/list_data` to see available numbers.", parse_mode='Markdown')
                return
                
            # Delete the record
            db.delete(record)
            db.commit()
                
            await update.message.reply_text(f"✅ Successfully removed number `{record.number}` from the watchlist.", parse_mode='Markdown')
                
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Please provide a valid number ID.")
    except Exception as e:
        logger.error(f"Error removing number: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while removing the number. Please try again.")
    
async def new_chat_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new chat members event."""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            # Bot was added to a group
            chat = update.effective_chat
            await self.handle_bot_added(chat, context.bot)
            break
    
async def handle_bot_added(self, chat, bot):
    """Handle the event when bot is added to a group."""
    # Send welcome message to the group
    welcome_text = (
        "👋 *Welcome to AIVA Detect System!*\n\n"
        "I'll help you detect and prevent duplicate payments in this group.\n\n"
        "*How It Works:*\n"
        "1. Add me to your group\n"
        "2. I'll automatically detect numbers in messages\n"
        "3. If a duplicate number is found, I'll notify the group\n\n"
        "*Note:* Only group admins can manage my settings."
    )
    await bot.send_message(
        chat_id=chat.id,
        text=welcome_text,
        parse_mode='Markdown'
    )
        
    # Send private message to admins
    admins = await chat.get_administrators()
    for admin in admins:
        try:
            admin_text = (
                f"👋 Hello! I've been added to *{chat.title}*.\n\n"
                "*Admin Controls:*\n"
                "• Use /number to add numbers to watchlist\n"
                "• Use /list_data to view all watched numbers\n\n"
                "I'll notify this group if I detect any duplicate numbers."
            )
            await bot.send_message(
                chat_id=admin.user.id,
                text=admin_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send admin message: {e}")
    
# Payment detection and database methods will be added here
async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and detect numbers."""
    if not update.message or not update.message.text:
        return
            
    message = update.message
    text = message.text
        
    # Skip if message is from a channel
    if message.sender_chat and message.sender_chat.type == "channel":
        return
            
    # Check for numbers in the message
    # Using a simple regex to find potential numbers
    # This is a basic pattern and might need adjustment based on your needs
    numbers = re.findall(r'\b\d{10,}\b', text)
        
    if not numbers:
        return
            
    for number in numbers:
        await self.process_number(number, message, context.bot)

    async def process_number(self, number: str, message, bot):
        """Process a single number and check for duplicates."""
        try:
            with get_db() as db:
                # First check if this exact number already exists as a non-duplicate
                existing = db.query(NumberRecord).filter(
                    NumberRecord.number == number,
                    NumberRecord.is_duplicate == False
                ).first()
                
                if existing:
                    # Found a match - handle as duplicate
                    await self.handle_duplicate(existing, number, message, bot, db)
                    return True
                    
                # If we get here, it's either a new number or already marked as duplicate
                # Check if we've seen this number before (even as a duplicate)
                seen_before = db.query(NumberRecord).filter(
                    NumberRecord.number == number
                ).first()
                
                if not seen_before:
                    # This is a brand new number - add to database
                    new_record = NumberRecord(
                        number=number,
                        group_id=str(message.chat.id) if hasattr(message, 'chat') and message.chat else None,
                        message_id=message.message_id if hasattr(message, 'message_id') else None,
                        user_id=message.from_user.id if hasattr(message, 'from_user') and message.from_user else None,
                        is_duplicate=False
                    )
                    db.add(new_record)
                    db.commit()
                    logger.info(f"New number added to watchlist: {number}")
                
                return False
        except Exception as e:
            logger.error(f"Error in process_number: {e}", exc_info=True)
            return False

    async def handle_duplicate(self, existing_record, number: str, message, bot, db):
        """Handle a detected duplicate number."""
        try:
            # Create a new record marking it as a duplicate
            duplicate_record = NumberRecord(
                number=number,
                group_id=str(message.chat.id) if hasattr(message, 'chat') and message.chat else None,
                message_id=message.message_id if hasattr(message, 'message_id') else None,
                user_id=message.from_user.id if hasattr(message, 'from_user') and message.from_user else None,
                is_duplicate=True
            )
            db.add(duplicate_record)
            
            # Create a duplicate alert
            alert = DuplicateAlert(
                number=number,
                original_number_id=existing_record.id,
                duplicate_number_id=duplicate_record.id,
                status='pending'
            )
            db.add(alert)
            db.commit()
            
            # Prepare user-friendly alert message
            user = message.from_user if hasattr(message, 'from_user') and message.from_user else None
            username = f"@{user.username}" if user and user.username else (user.first_name if user else "a user")
            
            alert_text = (
                "🚨 *DOUBLE PAYMENT DETECTED* 🚨\n\n"
                f"⚠️ *HOLD - DO NOT PROCEED* ⚠️\n\n"
                f"📱 *Number:* `{number}`\n"
                f"📅 *First Added:* {existing_record.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"👤 *Reported by:* {username}\n\n"
                "*Please verify this transaction before proceeding with payment.*\n"
                "_This number has been previously processed._"
            )
            
            # Try to send the alert
            try:
                # First try to reply to the message
                await message.reply_text(
                    alert_text,
                    parse_mode='Markdown',
                    reply_to_message_id=message.message_id if hasattr(message, 'message_id') else None
                )
                logger.info(f"Sent duplicate alert for number: {number}")
                
            except Exception as e:
                logger.error(f"Failed to send alert as reply, trying direct message: {e}")
                try:
                    # If reply fails, try sending a direct message
                    chat_id = message.chat.id if hasattr(message, 'chat') and message.chat else None
                    if chat_id:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=alert_text,
                            parse_mode='Markdown'
                        )
                except Exception as e2:
                    logger.error(f"Failed to send duplicate alert: {e2}")
                    
        except Exception as e:
            logger.error(f"Error in handle_duplicate: {e}", exc_info=True)
            # Try to notify admins of the error
            try:
                if hasattr(message, 'chat') and message.chat:
                    await message.reply_text(
                        "⚠️ An error occurred while processing this payment. Please contact an admin.",
                        reply_to_message_id=message.message_id if hasattr(message, 'message_id') else None
                    )
            except:
                pass
                
        number = ' '.join(context.args)
        # No validation needed as per requirements
                
        # Add to database
        with get_db() as db:
            # Check if already exists
            exists = db.query(NumberRecord).filter_by(
                number=number,
                is_duplicate=False
            ).first()
                
            if exists:
                await update.message.reply_text("ℹ️ This number is already in the watchlist.")
                return
                    
            new_record = NumberRecord(
                number=number,
                user_id=update.effective_user.id,
                is_duplicate=False
            )
            db.add(new_record)
            db.commit()
                
        await update.message.reply_text("✅ Number added to watchlist successfully!")
    

    
    async def list_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all watched phone numbers with proper session management."""
        try:
            # Use the database context manager
            with get_db() as db:
                # Execute the query and get all results within the session
                records = db.query(NumberRecord).filter_by(is_duplicate=False).order_by(NumberRecord.created_at.desc()).all()
                
                if not records:
                    await update.message.reply_text("No phone numbers in watchlist yet.")
                    return
                
                # Create a formatted message with all records
                message = "📋 *Watched Numbers*\n\n"
                for i, record in enumerate(records, 1):
                    message += f"{i}. `{record.number}`"
                    if record.notes:
                        message += f" - {record.notes}"
                    message += f" (ID: {record.id})\n"
                
                # Add help text
                message += "\nUse `/remove <ID>` to remove a number from the watchlist."
                
                # Send the message with Markdown formatting
                try:
                    await update.message.reply_text(
                        message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    # Fall back to plain text if Markdown fails
                    logger.warning(f"Markdown error in list_data: {e}")
                    plain_message = message.replace('*', '').replace('`', '')
                    await update.message.reply_text(
                        plain_message,
                        disable_web_page_preview=True
                    )
        
        except Exception as e:
            logger.error(f"Error in list_data: {str(e)}", exc_info=True)
            try:
                await update.message.reply_text("❌ An error occurred while fetching the number list. Please try again.")
            except Exception as send_error:
                logger.error(f"Failed to send error message: {str(send_error)}")
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status and uptime."""
        uptime = datetime.now() - self.start_time
        days, seconds = uptime.days, uptime.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        status_text = (
            "🤖 *Bot Status*\n"
            f"• *Uptime:* {days}d {hours}h {minutes}m\n"
            f"• *Self-ping:* {'✅ Active' if self.self_ping_url else '❌ Inactive'}\n"
            f"• *Version:* 1.0.0\n\n"
            "_Use /help to see available commands_"
        )
        
        try:
            await update.message.reply_text(status_text, parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Markdown error in status, falling back to plain text: {e}")
            plain_text = status_text.replace('*', '').replace('_', '')
            await update.message.reply_text(plain_text)
    
    async def self_ping(self, context: ContextTypes.DEFAULT_TYPE):
        """Ping the self-ping URL to keep the bot alive."""
        if not self.self_ping_url:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.self_ping_url) as response:
                    if response.status == 200:
                        logger.info("Self-ping successful")
                    else:
                        logger.warning(f"Self-ping failed with status {response.status}")
        except Exception as e:
            logger.error(f"Error in self-ping: {e}")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the telegram.ext application with detailed logging."""
        # Log the full error with traceback
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # Get detailed error information
        error_type = type(context.error).__name__
        error_msg = str(context.error) or 'No error message'
        
        # Log the error with more context
        logger.error(f"Error type: {error_type}")
        logger.error(f"Error message: {error_msg}")
        
        # Log the update that caused the error
        if update:
            update_dict = update.to_dict() if hasattr(update, 'to_dict') else str(update)
            logger.error(f"Update that caused the error: {update_dict}")
        
        # Only send error message if it's a message update
        if update and hasattr(update, 'message') and update.message:
            try:
                # Send a more detailed error message to the user
                await update.message.reply_text(
                    f"❌ Error ({error_type}): {error_msg[:100]}...\n\n"
                    "The error has been logged and will be investigated."
                )
            except Exception as e:
                logger.error(f"Error sending error message: {e}")
        else:
            logger.error("No message in update to reply to")
    


def get_application():
    """Create and configure the bot application."""
    # Initialize the database
    init_db()
    
    # Create the bot
    bot = AIVABot()
    return bot.application

def main():
    """Start the bot."""
    try:
        # Initialize database first
        from database.database import init_db
        from database.models import Base
        from database.database import engine
        
        # Ensure tables are created
        Base.metadata.create_all(bind=engine)
        init_db()
        
        logger.info("Database initialization complete")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    application = get_application()
    
    # Check if running on Render
    is_render = os.getenv('RENDER', '').lower() == 'true'
    
    if is_render or os.getenv('USE_WEBHOOK', '').lower() == 'true':
        # Webhook mode for production
        logger.info("Starting in webhook mode")
        port = int(os.environ.get('PORT', 5000))
        webhook_url = os.getenv('WEBHOOK_URL')
        
        if not webhook_url:
            logger.warning("WEBHOOK_URL not set, using polling instead")
            application.run_polling()
        else:
            # Set webhook
            async def set_webhook():
                await application.bot.set_webhook(url=f"{webhook_url}/webhook")
            
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                secret_token=os.getenv('WEBHOOK_SECRET', 'your-secret-token'),
                webhook_url=webhook_url,
                drop_pending_updates=True
            )
    else:
        # Polling mode for development
        logger.info("Starting in polling mode")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
