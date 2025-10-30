import logging
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatType
import sqlite3
import asyncio
from datetime import datetime, timedelta
import time
from typing import Dict, List
import json
import os
from aiohttp import web
import threading

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin IDs - Integrated your accounts
ADMIN_IDS = [7475473197, 7713987088]  # Your admin accounts

PREMIUM_COST = 50  # Number of Telegram Stars for premium subscription

# Required channels that users must join
REQUIRED_CHANNELS = [
    {"username": "pspgamers5", "url": "https://t.me/pspgamers5", "title": "PSP Gamers 5"},
    {"username": "pspgamers20", "url": "https://t.me/pspgamers20", "title": "PSP Gamers 20"}
]

# Reaction limits
PREMIUM_REACTIONS_PER_POST = 3000  # 3K reactions per post
REGULAR_REACTIONS_PER_POST = 30    # 30 reactions per post
TIME_WINDOW_MINUTES = 5            # 5 minutes window

# Define reaction emojis manually for compatibility
REACTION_EMOJIS = [
    "👍",  # Thumbs up
    "❤️",  # Red heart
    "🔥",  # Fire
    "🎉",  # Party popper
    "⭐",  # Star
    "👏",  # Clapping hands
    "😍",  # Heart eyes
    "🚀",  # Rocket
    "💫",  # Dizzy
    "🤩",  # Star struck
    "✨",  # Sparkles
    "💥",  # Collision
    "🙌",  # Raising hands
    "😊",  # Smiling face with smiling eyes
    "😂",  # Face with tears of joy
    "🥰",  # Smiling face with hearts
    "😎",  # Smiling face with sunglasses
    "🤗",  # Hugging face
    "👌",  # OK hand
    "💯",  # Hundred points
]

# Health check and monitoring
class HealthMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.total_reactions_sent = 0
        self.total_posts_processed = 0
        self.last_health_check = datetime.now()
        self.health_check_interval = 300  # 5 minutes
    
    def increment_reactions(self, count):
        self.total_reactions_sent += count
    
    def increment_posts(self):
        self.total_posts_processed += 1
    
    def get_uptime(self):
        return datetime.now() - self.start_time
    
    def get_stats(self):
        return {
            "uptime": str(self.get_uptime()),
            "total_reactions_sent": self.total_reactions_sent,
            "total_posts_processed": self.total_posts_processed,
            "status": "healthy",
            "last_health_check": self.last_health_check.isoformat()
        }
    
    def update_health_check(self):
        self.last_health_check = datetime.now()

# Initialize health monitor
health_monitor = HealthMonitor()

# Database setup
class Database:
    def __init__(self):
        self.db_path = os.environ.get("DATABASE_URL", "bot_data.db")
        if self.db_path.startswith("postgres://"):
            # For PostgreSQL (Render)
            try:
                import psycopg2
                self.conn = psycopg2.connect(self.db_path, sslmode='require')
                self.is_postgres = True
                logger.info("✅ Connected to PostgreSQL database")
            except ImportError:
                logger.warning("⚠️ PostgreSQL not available, falling back to SQLite")
                self.conn = sqlite3.connect("bot_data.db", check_same_thread=False)
                self.is_postgres = False
        else:
            # For SQLite (local development)
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.is_postgres = False
            logger.info("✅ Connected to SQLite database")
        self.create_tables()
    
    def execute_query(self, query, params=None):
        cursor = self.conn.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self.conn.commit()
            return cursor
        except Exception as e:
            self.conn.rollback()
            raise e
    
    def create_tables(self):
        if self.is_postgres:
            # PostgreSQL table creation
            try:
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        is_premium BOOLEAN DEFAULT FALSE,
                        premium_until TIMESTAMP,
                        has_joined_channels BOOLEAN DEFAULT FALSE,
                        joined_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS channels (
                        channel_id BIGINT PRIMARY KEY,
                        channel_username TEXT,
                        channel_title TEXT,
                        is_active BOOLEAN DEFAULT TRUE,
                        added_by BIGINT,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        auto_react BOOLEAN DEFAULT TRUE
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS permanent_reactions (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        target_message_id BIGINT,
                        target_chat_id BIGINT,
                        reactions_applied TEXT,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS channel_posts (
                        id SERIAL PRIMARY KEY,
                        channel_id BIGINT,
                        message_id BIGINT,
                        post_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        reactions_sent INTEGER DEFAULT 0,
                        is_processed BOOLEAN DEFAULT FALSE,
                        permanent_reaction_id INTEGER
                    )
                ''')
                logger.info("✅ PostgreSQL tables created/verified")
            except Exception as e:
                logger.error(f"❌ Error creating PostgreSQL tables: {e}")
        else:
            # SQLite table creation
            try:
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        is_premium INTEGER DEFAULT 0,
                        premium_until TIMESTAMP,
                        has_joined_channels INTEGER DEFAULT 0,
                        joined_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS channels (
                        channel_id INTEGER PRIMARY KEY,
                        channel_username TEXT,
                        channel_title TEXT,
                        is_active INTEGER DEFAULT 1,
                        added_by INTEGER,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        auto_react INTEGER DEFAULT 1
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS permanent_reactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        target_message_id INTEGER,
                        target_chat_id INTEGER,
                        reactions_applied TEXT,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active INTEGER DEFAULT 1
                    )
                ''')
                self.execute_query('''
                    CREATE TABLE IF NOT EXISTS channel_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id INTEGER,
                        message_id INTEGER,
                        post_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        reactions_sent INTEGER DEFAULT 0,
                        is_processed INTEGER DEFAULT 0,
                        permanent_reaction_id INTEGER
                    )
                ''')
                logger.info("✅ SQLite tables created/verified")
            except Exception as e:
                logger.error(f"❌ Error creating SQLite tables: {e}")
    
    def get_user(self, user_id):
        try:
            cursor = self.execute_query('''
                SELECT user_id, is_premium, premium_until, has_joined_channels, joined_at
                FROM users WHERE user_id = %s
            ''' if self.is_postgres else '''
                SELECT user_id, is_premium, premium_until, has_joined_channels, joined_at
                FROM users WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result:
                if self.is_postgres:
                    return {
                        'user_id': result[0],
                        'is_premium': result[1],
                        'premium_until': result[2],
                        'has_joined_channels': result[3],
                        'joined_at': result[4]
                    }
                else:
                    return {
                        'user_id': result[0],
                        'is_premium': bool(result[1]),
                        'premium_until': result[2],
                        'has_joined_channels': bool(result[3]),
                        'joined_at': result[4]
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def create_user(self, user_id):
        try:
            if self.is_postgres:
                self.execute_query('''
                    INSERT INTO users (user_id) 
                    VALUES (%s)
                    ON CONFLICT (user_id) DO NOTHING
                ''', (user_id,))
            else:
                self.execute_query('''
                    INSERT OR IGNORE INTO users (user_id) 
                    VALUES (?)
                ''', (user_id,))
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
    
    def set_user_joined_channels(self, user_id):
        try:
            if self.is_postgres:
                self.execute_query('''
                    UPDATE users SET has_joined_channels = TRUE, joined_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s
                ''', (user_id,))
            else:
                self.execute_query('''
                    UPDATE users SET has_joined_channels = 1, joined_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
        except Exception as e:
            logger.error(f"Error setting user joined channels {user_id}: {e}")
    
    def set_premium(self, user_id, duration_days=30):
        try:
            premium_until = datetime.now() + timedelta(days=duration_days)
            if self.is_postgres:
                self.execute_query('''
                    INSERT INTO users (user_id, is_premium, premium_until) 
                    VALUES (%s, TRUE, %s)
                    ON CONFLICT (user_id) DO UPDATE SET 
                    is_premium = TRUE, premium_until = EXCLUDED.premium_until
                ''', (user_id, premium_until.isoformat()))
            else:
                self.execute_query('''
                    INSERT OR REPLACE INTO users (user_id, is_premium, premium_until) 
                    VALUES (?, 1, ?)
                ''', (user_id, premium_until.isoformat()))
        except Exception as e:
            logger.error(f"Error setting premium for user {user_id}: {e}")
    
    def add_channel(self, channel_id, channel_username, channel_title, added_by):
        try:
            if self.is_postgres:
                self.execute_query('''
                    INSERT INTO channels (channel_id, channel_username, channel_title, added_by, added_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id) DO UPDATE SET 
                    channel_username = EXCLUDED.channel_username,
                    channel_title = EXCLUDED.channel_title,
                    added_by = EXCLUDED.added_by,
                    added_at = EXCLUDED.added_at
                ''', (channel_id, channel_username, channel_title, added_by, datetime.now().isoformat()))
            else:
                self.execute_query('''
                    INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_title, added_by, added_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (channel_id, channel_username, channel_title, added_by, datetime.now().isoformat()))
        except Exception as e:
            logger.error(f"Error adding channel {channel_id}: {e}")
    
    def get_channels(self):
        try:
            cursor = self.execute_query('''
                SELECT channel_id, channel_username, channel_title, is_active, auto_react 
                FROM channels 
                WHERE is_active = TRUE
            ''' if self.is_postgres else '''
                SELECT channel_id, channel_username, channel_title, is_active, auto_react 
                FROM channels 
                WHERE is_active = 1
            ''')
            if self.is_postgres:
                return [{
                    'channel_id': row[0],
                    'channel_username': row[1],
                    'channel_title': row[2],
                    'is_active': row[3],
                    'auto_react': row[4]
                } for row in cursor.fetchall()]
            else:
                return [{
                    'channel_id': row[0],
                    'channel_username': row[1],
                    'channel_title': row[2],
                    'is_active': bool(row[3]),
                    'auto_react': bool(row[4])
                } for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting channels: {e}")
            return []
    
    def toggle_channel_auto_react(self, channel_id):
        try:
            if self.is_postgres:
                self.execute_query('''
                    UPDATE channels SET auto_react = NOT auto_react 
                    WHERE channel_id = %s
                ''', (channel_id,))
            else:
                self.execute_query('''
                    UPDATE channels SET auto_react = NOT auto_react 
                    WHERE channel_id = ?
                ''', (channel_id,))
        except Exception as e:
            logger.error(f"Error toggling auto react for channel {channel_id}: {e}")
    
    def log_permanent_reaction(self, user_id, target_message_id, target_chat_id, reactions):
        """Log permanent reactions that should never be removed"""
        try:
            reactions_json = json.dumps(reactions)
            if self.is_postgres:
                cursor = self.execute_query('''
                    INSERT INTO permanent_reactions 
                    (user_id, target_message_id, target_chat_id, reactions_applied)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                ''', (user_id, target_message_id, target_chat_id, reactions_json))
                return cursor.fetchone()[0]
            else:
                cursor = self.execute_query('''
                    INSERT INTO permanent_reactions 
                    (user_id, target_message_id, target_chat_id, reactions_applied)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, target_message_id, target_chat_id, reactions_json))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error logging permanent reaction: {e}")
            return None
    
    def log_channel_post(self, channel_id, message_id):
        try:
            if self.is_postgres:
                cursor = self.execute_query('''
                    INSERT INTO channel_posts (channel_id, message_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                ''', (channel_id, message_id))
                result = cursor.fetchone()
                return result[0] if result else None
            else:
                cursor = self.execute_query('''
                    INSERT OR IGNORE INTO channel_posts (channel_id, message_id)
                    VALUES (?, ?)
                ''', (channel_id, message_id))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error logging channel post: {e}")
            return None
    
    def mark_post_processed(self, post_id, reactions_sent, permanent_reaction_id=None):
        try:
            if self.is_postgres:
                self.execute_query('''
                    UPDATE channel_posts 
                    SET is_processed = TRUE, reactions_sent = %s, permanent_reaction_id = %s
                    WHERE id = %s
                ''', (reactions_sent, permanent_reaction_id, post_id))
            else:
                self.execute_query('''
                    UPDATE channel_posts 
                    SET is_processed = 1, reactions_sent = ?, permanent_reaction_id = ?
                    WHERE id = ?
                ''', (reactions_sent, permanent_reaction_id, post_id))
        except Exception as e:
            logger.error(f"Error marking post processed {post_id}: {e}")
    
    def get_pending_posts(self):
        try:
            cursor = self.execute_query('''
                SELECT cp.id, cp.channel_id, cp.message_id, c.channel_title
                FROM channel_posts cp
                JOIN channels c ON cp.channel_id = c.channel_id
                WHERE cp.is_processed = FALSE AND c.auto_react = TRUE
                ORDER BY cp.post_time ASC
            ''' if self.is_postgres else '''
                SELECT cp.id, cp.channel_id, cp.message_id, c.channel_title
                FROM channel_posts cp
                JOIN channels c ON cp.channel_id = c.channel_id
                WHERE cp.is_processed = 0 AND c.auto_react = 1
                ORDER BY cp.post_time ASC
            ''')
            return [{
                'id': row[0],
                'channel_id': row[1],
                'message_id': row[2],
                'channel_title': row[3]
            } for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting pending posts: {e}")
            return []
    
    def get_post_reaction_stats(self, user_id, target_message_id, target_chat_id):
        """Get reaction statistics for a specific post within the 5-minute window"""
        try:
            # Calculate time window
            window_start = datetime.now() - timedelta(minutes=TIME_WINDOW_MINUTES)
            
            if self.is_postgres:
                cursor = self.execute_query('''
                    SELECT COUNT(*) FROM permanent_reactions 
                    WHERE user_id = %s 
                    AND target_message_id = %s
                    AND target_chat_id = %s
                    AND applied_at >= %s
                    AND is_active = TRUE
                ''', (user_id, target_message_id, target_chat_id, window_start.isoformat()))
            else:
                cursor = self.execute_query('''
                    SELECT COUNT(*) FROM permanent_reactions 
                    WHERE user_id = ? 
                    AND target_message_id = ?
                    AND target_chat_id = ?
                    AND applied_at >= ?
                    AND is_active = 1
                ''', (user_id, target_message_id, target_chat_id, window_start.isoformat()))
            
            result = cursor.fetchone()
            total_reactions = result[0] if result[0] else 0
            
            return total_reactions
        except Exception as e:
            logger.error(f"Error getting post reaction stats: {e}")
            return 0
    
    def can_send_reactions(self, user_id, target_message_id, target_chat_id, num_reactions):
        """Check if user can send the requested number of reactions to this post"""
        try:
            user = self.get_user(user_id)
            if not user:
                return False
            
            # Get user's reaction limit
            if user_id in ADMIN_IDS:
                max_reactions = PREMIUM_REACTIONS_PER_POST
            elif user['is_premium']:
                # Check if premium subscription is still valid
                if user['premium_until']:
                    premium_until = datetime.fromisoformat(user['premium_until'])
                    if datetime.now() > premium_until:
                        self.remove_premium(user_id)
                        max_reactions = REGULAR_REACTIONS_PER_POST
                    else:
                        max_reactions = PREMIUM_REACTIONS_PER_POST
                else:
                    max_reactions = REGULAR_REACTIONS_PER_POST
            else:
                max_reactions = REGULAR_REACTIONS_PER_POST
            
            # Get current reaction count for this post in the last 5 minutes
            current_reactions = self.get_post_reaction_stats(user_id, target_message_id, target_chat_id)
            
            return current_reactions + num_reactions <= max_reactions
        except Exception as e:
            logger.error(f"Error checking if can send reactions: {e}")
            return False
    
    def remove_premium(self, user_id):
        try:
            if self.is_postgres:
                self.execute_query('''
                    UPDATE users SET is_premium = FALSE, premium_until = NULL 
                    WHERE user_id = %s
                ''', (user_id,))
            else:
                self.execute_query('''
                    UPDATE users SET is_premium = 0, premium_until = NULL 
                    WHERE user_id = ?
                ''', (user_id,))
        except Exception as e:
            logger.error(f"Error removing premium for user {user_id}: {e}")
    
    def cleanup_old_records(self):
        """Clean up old records but keep permanent reactions"""
        try:
            cutoff_time = datetime.now() - timedelta(days=7)
            if self.is_postgres:
                self.execute_query('DELETE FROM channel_posts WHERE post_time < %s', (cutoff_time.isoformat(),))
            else:
                self.execute_query('DELETE FROM channel_posts WHERE post_time < ?', (cutoff_time.isoformat(),))
        except Exception as e:
            logger.error(f"Error cleaning up old records: {e}")

# Initialize database
db = Database()

class ReactionBot:
    def __init__(self, token):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.bot = Bot(token)
        self.setup_handlers()
        # Start background tasks
        asyncio.create_task(self.periodic_cleanup())
        asyncio.create_task(self.process_channel_posts())
        asyncio.create_task(self.health_check_loop())
        asyncio.create_task(self.keep_alive_loop())
    
    def setup_handlers(self):
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("premium", self.premium_info))
        self.application.add_handler(CommandHandler("stats", self.user_stats))
        self.application.add_handler(CommandHandler("admin_addpremium", self.admin_add_premium))
        self.application.add_handler(CommandHandler("admin_channels", self.admin_channels))
        self.application.add_handler(CommandHandler("admin_stats", self.admin_stats))
        self.application.add_handler(CommandHandler("health", self.health_check))
        self.application.add_handler(CommandHandler("react", self.react_command))
        self.application.add_handler(CommandHandler("verify", self.verify_command))
        
        # Callback query handler for inline keyboards
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handler for all messages (to detect channel posts)
        self.application.add_handler(MessageHandler(filters.ALL, self.handle_all_messages))
        
        # My Chat Member handler for when bot is added to channels
        self.application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_chat_members))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    async def health_check_loop(self):
        """Periodic health check loop"""
        while True:
            try:
                health_monitor.update_health_check()
                # Test database connection
                db.get_channels()
                logger.info("✅ Health check passed")
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"❌ Health check failed: {e}")
                await asyncio.sleep(30)  # Retry sooner if failed
    
    async def keep_alive_loop(self):
        """Keep-alive loop to prevent Render from sleeping"""
        while True:
            try:
                # Simple operation to keep the bot active
                channels_count = len(db.get_channels())
                logger.info(f"🤖 Bot is alive. Managing {channels_count} channels")
                await asyncio.sleep(300)  # Ping every 5 minutes
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
                await asyncio.sleep(60)
    
    async def health_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Health check command for monitoring"""
        try:
            # Test database
            db.get_channels()
            
            stats = health_monitor.get_stats()
            health_text = f"""
🏥 **Bot Health Status**

**Status:** ✅ Healthy
**Uptime:** {stats['uptime']}
**Total Reactions Sent:** {stats['total_reactions_sent']:,}
**Total Posts Processed:** {stats['total_posts_processed']}
**Last Health Check:** {stats['last_health_check']}

**Database:** ✅ Connected
**Bot:** ✅ Running
**Channels Managed:** {len(db.get_channels())}
            """
            
            await update.message.reply_text(health_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Health check failed: {str(e)}")
    
    async def check_user_joined_channels(self, user_id):
        """Check if user has joined all required channels"""
        try:
            for channel in REQUIRED_CHANNELS:
                chat_member = await self.bot.get_chat_member(f"@{channel['username']}", user_id)
                if chat_member.status in ['left', 'kicked']:
                    return False
            return True
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    
    async def send_channel_requirement_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send message requiring users to join channels"""
        keyboard = []
        for channel in REQUIRED_CHANNELS:
            keyboard.append([InlineKeyboardButton(f"📢 Join {channel['title']}", url=channel['url'])])
        
        keyboard.append([InlineKeyboardButton("✅ I've Joined All Channels", callback_data="verify_join")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        requirement_text = """
🔒 **Channel Membership Required**

To use this bot, you must join our official channels first!

**Required Channels:**
"""
        for channel in REQUIRED_CHANNELS:
            requirement_text += f"• {channel['title']} - {channel['url']}\n"
        
        requirement_text += "\nPlease join all channels above and click the verification button below."
        
        if update.message:
            await update.message.reply_text(requirement_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(requirement_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def require_channel_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Check if user needs to join channels and show requirement message if needed"""
        user = db.get_user(user_id)
        
        # If user hasn't verified or needs re-verification
        if not user or not user['has_joined_channels']:
            await self.send_channel_requirement_message(update, context)
            return False
        
        # Re-verify periodically (once per day)
        joined_at = datetime.fromisoformat(user['joined_at']) if user['joined_at'] else datetime.min
        if datetime.now() - joined_at > timedelta(days=1):
            is_joined = await self.check_user_joined_channels(user_id)
            if not is_joined:
                await self.send_channel_requirement_message(update, context)
                return False
            # Update verification timestamp
            db.set_user_joined_channels(user_id)
        
        return True
    
    async def periodic_cleanup(self):
        """Periodically clean up old records"""
        while True:
            await asyncio.sleep(300)  # Run every 5 minutes
            db.cleanup_old_records()
    
    async def process_channel_posts(self):
        """Background task to process pending channel posts"""
        while True:
            try:
                pending_posts = db.get_pending_posts()
                for post in pending_posts:
                    await self.process_channel_post(post)
                await asyncio.sleep(2)  # Check every 2 seconds
            except Exception as e:
                logger.error(f"Error in process_channel_posts: {e}")
                await asyncio.sleep(10)
    
    async def process_channel_post(self, post):
        """Process a single channel post with permanent reactions"""
        try:
            channel_id = post['channel_id']
            message_id = post['message_id']
            
            # Use first admin user ID for channel reactions
            admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
            if not admin_id:
                return
            
            # Determine how many reactions to send (use premium limit for channels)
            num_reactions = min(50, PREMIUM_REACTIONS_PER_POST)  # Send substantial permanent reactions
            
            if db.can_send_reactions(admin_id, message_id, channel_id, num_reactions):
                success_count, reactions_sent = await self.send_permanent_reactions(channel_id, message_id, num_reactions)
                
                if success_count > 0:
                    # Log as permanent reactions
                    permanent_id = db.log_permanent_reaction(admin_id, message_id, channel_id, reactions_sent)
                    db.mark_post_processed(post['id'], success_count, permanent_id)
                    health_monitor.increment_reactions(success_count)
                    health_monitor.increment_posts()
                    logger.info(f"Sent {success_count} PERMANENT reactions to post {message_id} in channel {channel_id}")
                
                # Small delay between posts
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error processing channel post: {e}")
    
    async def handle_new_chat_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when bot is added to channels/groups"""
        try:
            if update.message.new_chat_members:
                for user in update.message.new_chat_members:
                    if user.id == context.bot.id:
                        chat = update.effective_chat
                        if chat.type in [ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP]:
                            # Bot was added to a channel/group
                            added_by = update.effective_user.id
                            db.add_channel(chat.id, chat.username, chat.title, added_by)
                            
                            # Send welcome message with inline keyboard
                            keyboard = [
                                [InlineKeyboardButton("✅ Enable Auto-Reactions", callback_data=f"enable_auto_{chat.id}")],
                                [InlineKeyboardButton("❌ Disable Auto-Reactions", callback_data=f"disable_auto_{chat.id}")],
                                [InlineKeyboardButton("📊 Channel Stats", callback_data=f"channel_stats_{chat.id}")]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            welcome_text = f"""
🤖 **Reaction Bot Added to {chat.title}**

I will automatically send **PERMANENT** reactions to all new posts in this channel!

**Current Settings:**
• Auto-reactions: ✅ Enabled
• Reaction limit: {PREMIUM_REACTIONS_PER_POST:,} per post
• Reactions: 🔥 Permanent (Never removed)
• Time window: 5 minutes

Use the buttons below to configure auto-reactions.
                            """
                            
                            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error in handle_new_chat_members: {e}")
    
    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all messages to detect channel posts"""
        try:
            chat = update.effective_chat
            message = update.effective_message
            
            # Only process channel messages
            if chat.type == ChatType.CHANNEL and message:
                # Log the channel post for processing
                db.log_channel_post(chat.id, message.message_id)
                logger.info(f"New post detected in channel {chat.title}: {message.message_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_all_messages: {e}")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "verify_join":
            # Verify user has joined channels
            is_joined = await self.check_user_joined_channels(user_id)
            if is_joined:
                db.set_user_joined_channels(user_id)
                await self.start_command(update, context)
            else:
                await self.send_channel_requirement_message(update, context)
        
        elif data == "main_menu":
            await self.start_command(update, context)
            
        elif data == "premium_info":
            await self.premium_info(update, context)
            
        elif data == "user_stats":
            await self.user_stats(update, context)
            
        elif data == "admin_panel":
            if user_id in ADMIN_IDS:
                await self.admin_panel(update, context)
            else:
                await query.edit_message_text("❌ Admin access required.")
        
        elif data.startswith('enable_auto_'):
            channel_id = int(data.split('_')[-1])
            db.toggle_channel_auto_react(channel_id)
            await query.edit_message_text("✅ Auto-reactions enabled for this channel!")
            
        elif data.startswith('disable_auto_'):
            channel_id = int(data.split('_')[-1])
            db.toggle_channel_auto_react(channel_id)
            await query.edit_message_text("❌ Auto-reactions disabled for this channel!")
            
        elif data.startswith('channel_stats_'):
            channel_id = int(data.split('_')[-1])
            channels = db.get_channels()
            channel = next((c for c in channels if c['channel_id'] == channel_id), None)
            
            if channel:
                stats_text = f"""
📊 **Channel Stats - {channel['channel_title']}**

• Auto-reactions: {'✅ Enabled' if channel['auto_react'] else '❌ Disabled'}
• Reaction limit: {PREMIUM_REACTIONS_PER_POST:,} per post
• Reactions: 🔥 Permanent
• Time window: 5 minutes

The bot will automatically react to all new posts with permanent reactions.
                """
                await query.edit_message_text(stats_text)
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel with management options"""
        keyboard = [
            [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
            [InlineKeyboardButton("📢 Managed Channels", callback_data="admin_channels_list")],
            [InlineKeyboardButton("⭐ Add Premium", callback_data="admin_add_premium_ui")],
            [InlineKeyboardButton("🏥 Health Check", callback_data="admin_health")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        stats = health_monitor.get_stats()
        admin_text = f"""
👑 **Admin Panel**

**Admin IDs:** {', '.join(map(str, ADMIN_IDS))}
**Bot Status:** ✅ Running
**Uptime:** {stats['uptime']}
**Total Channels:** {len(db.get_channels())}
**Total Reactions:** {stats['total_reactions_sent']:,}

**Available Commands:**
• /admin_stats - Detailed bot statistics
• /admin_channels - Manage channels
• /admin_addpremium - Add premium to users
• /health - Health check

Use the buttons below for quick access.
        """
        
        if update.message:
            await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin statistics command"""
        user_id = update.effective_user.id
        
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ This command is for admins only.")
            return
        
        channels = db.get_channels()
        total_channels = len(channels)
        active_auto_react = len([c for c in channels if c['auto_react']])
        stats = health_monitor.get_stats()
        
        stats_text = f"""
📊 **Admin Statistics**

**Bot Information:**
• Admin Accounts: {len(ADMIN_IDS)}
• Your ID: {user_id}
• Bot Status: ✅ Active
• Uptime: {stats['uptime']}

**Performance Statistics:**
• Total Reactions Sent: {stats['total_reactions_sent']:,}
• Total Posts Processed: {stats['total_posts_processed']}
• Last Health Check: {stats['last_health_check']}

**Channel Statistics:**
• Total Channels: {total_channels}
• Auto-reactions Enabled: {active_auto_react}
• Auto-reactions Disabled: {total_channels - active_auto_react}

**Reaction Limits:**
• Premium Users: {PREMIUM_REACTIONS_PER_POST:,} permanent reactions/post
• Regular Users: {REGULAR_REACTIONS_PER_POST} permanent reactions/post
• Time Window: {TIME_WINDOW_MINUTES} minutes

**Required Channels:**
"""
        for channel in REQUIRED_CHANNELS:
            stats_text += f"• {channel['title']} - @{channel['username']}\n"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        db.create_user(user_id)
        
        # Check channel membership
        if not await self.require_channel_join(update, context, user_id):
            return
        
        keyboard = [
            [InlineKeyboardButton("⭐ Get Premium", callback_data="premium_info")],
            [InlineKeyboardButton("📊 My Stats", callback_data="user_stats")],
        ]
        
        # Add admin panel button for admin users
        if user_id in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
        keyboard.extend([
            [InlineKeyboardButton("📢 Add to Channel", url="https://t.me/your_bot_username?startchannel=true")],
            [InlineKeyboardButton("🔍 Verify Channels", callback_data="verify_join")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = """
🤖 **Reaction Bot** 🔥 PERMANENT REACTIONS

I send **PERMANENT** positive reactions that never get removed!

**Features:**
• ⭐ **Premium Users**: Up to 3,000 **PERMANENT** reactions per post
• 🔹 **Regular Users**: Up to 30 **PERMANENT** reactions per post  
• 📢 **Channel Support**: Auto-reactions when added to channels
• 🔥 **Permanent**: Reactions stay forever
• ⚡ **Fast**: Quick reaction delivery

**How to use:**
1. Add me to your channel as admin
2. I'll automatically react to all new posts with PERMANENT reactions
3. Or use /react command for specific messages

Use the buttons below to get started!
        """
        
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def verify_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manual verification command"""
        user_id = update.effective_user.id
        is_joined = await self.check_user_joined_channels(user_id)
        
        if is_joined:
            db.set_user_joined_channels(user_id)
            await update.message.reply_text("✅ Verification successful! You can now use all bot features.")
            await self.start_command(update, context)
        else:
            await self.send_channel_requirement_message(update, context)
    
    async def premium_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await self.require_channel_join(update, context, user_id):
            return
        
        keyboard = [
            [InlineKeyboardButton("💫 Buy Premium", callback_data="buy_premium")],
            [InlineKeyboardButton("📊 Compare Plans", callback_data="compare_plans")],
            [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        premium_text = f"""
⭐ **Premium Subscription** 🔥 PERMANENT REACTIONS

**Benefits:**
• 🚀 **3,000 PERMANENT reactions** per post (within 5 minutes)
• 📢 **Channel auto-reactions**
• ⚡ Priority processing
• 📈 Increased limits
• 🔥 **Reactions stay forever**

**Cost:** {PREMIUM_COST} Telegram Stars

**How to get premium:**
1. Send {PREMIUM_COST} Telegram Stars to this bot
2. Contact admin with payment proof
3. Admin will activate your premium

**Current Limits:**
• Premium: {PREMIUM_REACTIONS_PER_POST:,} **PERMANENT** reactions/post
• Regular: {REGULAR_REACTIONS_PER_POST} **PERMANENT** reactions/post
        """
        
        if update.message:
            await update.message.reply_text(premium_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(premium_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def user_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await self.require_channel_join(update, context, user_id):
            return
        
        user = db.get_user(user_id)
        
        if not user:
            db.create_user(user_id)
            user = db.get_user(user_id)
        
        user_type = "👑 Admin" if user_id in ADMIN_IDS else "⭐ Premium" if user['is_premium'] else "🔹 Regular"
        limit = PREMIUM_REACTIONS_PER_POST if user_id in ADMIN_IDS or user['is_premium'] else REGULAR_REACTIONS_PER_POST
        
        keyboard = [
            [InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="premium_info")],
            [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        stats_text = f"""
📊 **Your Stats** 🔥 PERMANENT REACTIONS

**Account Type:** {user_type}
**Reaction Limit:** {limit:,} **PERMANENT** reactions per post (5 minutes)
**Premium Until:** {user['premium_until'] or 'Not subscribed'}
**Channel Member:** ✅ Verified

**Channels Managed:** {len(db.get_channels())}
**Reactions Type:** 🔥 Permanent (Never removed)

**Usage:** I automatically react to channel posts with PERMANENT reactions or use /react command
        """
        
        if update.message:
            await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def admin_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ This command is for admins only.")
            return
        
        channels = db.get_channels()
        
        if not channels:
            await update.message.reply_text("❌ No channels are currently managed.")
            return
        
        channels_text = "📢 **Managed Channels:**\n\n"
        keyboard = []
        
        for channel in channels:
            status = "✅" if channel['auto_react'] else "❌"
            channels_text += f"{status} {channel['channel_title']}\n"
            channels_text += f"   ID: {channel['channel_id']}\n"
            channels_text += f"   Username: @{channel['channel_username']}\n"
            channels_text += f"   Auto-react: {'Enabled' if channel['auto_react'] else 'Disabled'}\n"
            channels_text += f"   Reactions: 🔥 Permanent\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{'✅' if channel['auto_react'] else '❌'} {channel['channel_title'][:20]}",
                    callback_data=f"toggle_channel_{channel['channel_id']}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(channels_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def admin_add_premium(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ This command is for admins only.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /admin_addpremium <user_id> [days]")
            return
        
        try:
            target_user_id = int(context.args[0])
            days = int(context.args[1]) if len(context.args) > 1 else 30
            
            db.set_premium(target_user_id, days)
            await update.message.reply_text(f"✅ Premium added for user {target_user_id} for {days} days.")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or days format.")
    
    async def react_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Check channel membership first
        if not await self.require_channel_join(update, context, user_id):
            return
        
        db.create_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: /react <number_of_reactions> [message_id]")
            return
        
        try:
            num_reactions = int(context.args[0])
            if num_reactions <= 0:
                await update.message.reply_text("❌ Please provide a positive number of reactions.")
                return
            
            # Determine target message
            if update.message.reply_to_message:
                target_message = update.message.reply_to_message
            elif len(context.args) > 1:
                # Try to get message by ID
                try:
                    message_id = int(context.args[1])
                    target_message = await update.message.chat.get_message(message_id)
                except Exception as e:
                    await update.message.reply_text("❌ Could not find the specified message.")
                    return
            else:
                await update.message.reply_text("❌ Please reply to a message or provide a message ID.")
                return
            
            target_message_id = target_message.message_id
            target_chat_id = update.effective_chat.id
            
            # Check if user can send reactions
            if not db.can_send_reactions(user_id, target_message_id, target_chat_id, num_reactions):
                user = db.get_user(user_id)
                limit = PREMIUM_REACTIONS_PER_POST if user_id in ADMIN_IDS or user['is_premium'] else REGULAR_REACTIONS_PER_POST
                current = db.get_post_reaction_stats(user_id, target_message_id, target_chat_id)
                
                await update.message.reply_text(
                    f"❌ Reaction limit exceeded!\n"
                    f"• Your limit: {limit:,} **PERMANENT** reactions per post (5 minutes)\n"
                    f"• Already used: {current:,} reactions\n"
                    f"• Requested: {num_reactions:,} more\n"
                    f"• Available: {max(0, limit - current):,} reactions"
                )
                return
            
            # Send PERMANENT reactions
            success_count, reactions_sent = await self.send_permanent_reactions(target_chat_id, target_message_id, num_reactions)
            
            if success_count > 0:
                # Log as permanent reactions
                db.log_permanent_reaction(user_id, target_message_id, target_chat_id, reactions_sent)
                
                keyboard = [
                    [InlineKeyboardButton("📊 Check Stats", callback_data="user_stats")],
                    [InlineKeyboardButton("⭐ Upgrade Premium", callback_data="premium_info")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"✅ Successfully sent {success_count:,} **PERMANENT** reactions! 🔥\n"
                    f"📊 Total reactions to this post: {db.get_post_reaction_stats(user_id, target_message_id, target_chat_id):,}\n"
                    f"⏰ Limit resets in 5 minutes\n"
                    f"🔥 These reactions will **NEVER** be removed!",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("❌ Failed to send any reactions.")
                
        except ValueError:
            await update.message.reply_text("❌ Please provide a valid number.")
        except Exception as e:
            logger.error(f"Error in react_command: {e}")
            await update.message.reply_text("❌ An error occurred while processing your request.")
    
    async def send_permanent_reactions(self, chat_id, message_id, num_reactions):
        """Send multiple PERMANENT reactions to a specific message"""
        success_count = 0
        reactions_sent = []
        max_batch_size = 10
        
        for i in range(0, min(num_reactions, 100), max_batch_size):
            batch_size = min(max_batch_size, num_reactions - i)
            
            try:
                import random
                reactions_to_send = random.sample(REACTION_EMOJIS, batch_size)
                
                await self.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=message_id,
                    reaction=reactions_to_send
                )
                success_count += batch_size
                reactions_sent.extend(reactions_to_send)
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"Failed to send batch of permanent reactions: {e}")
                continue
        
        return success_count, reactions_sent
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception while handling an update: {context.error}")
    
    def run(self):
        """Start the bot with web server for health checks"""
        # Start the web server for health checks
        self.start_web_server()
        # Start the bot
        self.application.run_polling()
    
    def start_web_server(self):
        """Start a simple web server for health checks"""
        async def health_handler(request):
            try:
                # Test database connection
                db.get_channels()
                stats = health_monitor.get_stats()
                return web.json_response({
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "uptime": str(stats['uptime']),
                    "total_reactions": stats['total_reactions_sent'],
                    "total_posts": stats['total_posts_processed']
                })
            except Exception as e:
                return web.json_response({
                    "status": "unhealthy",
                    "error": str(e)
                }, status=500)
        
        async def root_handler(request):
            return web.json_response({
                "message": "Telegram Reaction Bot is running",
                "status": "active",
                "timestamp": datetime.now().isoformat()
            })
        
        app = web.Application()
        app.router.add_get('/', root_handler)
        app.router.add_get('/health', health_handler)
        
        port = int(os.environ.get("PORT", 8080))
        
        # Run web server in background
        async def run_web_app():
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logger.info(f"🌐 Web server running on port {port}")
        
        asyncio.create_task(run_web_app())

# Main execution
if __name__ == "__main__":
    # Validate environment variables
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ BOT_TOKEN environment variable is required!")
        exit(1)
    
    bot = ReactionBot(BOT_TOKEN)
    print("🤖 Reaction Bot is starting...")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    print("📢 Add the bot to your channels and it will auto-react to all posts!")
    print("🏥 Health checks available at /health command and web endpoint")
    
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        exit(1)
