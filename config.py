# Configuration file for the OTT Giveaway Bot
import os
import logging
import json

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# Base directory for all data files (absolute paths to avoid CWD issues)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _path_in_base(filename: str) -> str:
    return os.path.join(BASE_DIR, filename)

# Auto-load .env if available
_env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception as _e:
        logger.warning(f"Could not load .env file: {_e}")

# Persistent payment config file
PAYMENT_CONFIG_FILE = _path_in_base("payment_config.json")

def _deep_update(base: dict, overrides: dict) -> dict:
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base

def load_payment_config() -> dict | None:
    try:
        if os.path.exists(PAYMENT_CONFIG_FILE):
            with open(PAYMENT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {PAYMENT_CONFIG_FILE}: {e}")
    return None

def persist_payment_methods() -> None:
    try:
        data = {
            "payment_methods": PAYMENT_METHODS,
            "upi_config": UPI_CONFIG,
        }
        with open(PAYMENT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to persist payment methods: {e}")



# Bot token from Telegram BotFather (loaded from .env or environment variable)
TOKEN = os.getenv("TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# HTTPS URL where the web panel is hosted. Required for Telegram Mini App.
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://your-bot-panel.com")

# Channel ID for broadcast and logs (optional)
CHANNEL_ID = os.getenv("CHANNEL_ID", "-100xxxxxxxxxx")

# Admin IDs and usernames
_admin_ids_env = os.getenv("ADMIN_IDS", "8922585790")
ADMIN_IDS = [int(i.strip()) for i in _admin_ids_env.split(",") if i.strip().isdigit()] or [8922585790]
OWNER_IDS = ADMIN_IDS
_admin_usernames_env = os.getenv("ADMIN_USERNAMES", "@lusuferr")
ADMIN_USERNAMES = [u.strip() for u in _admin_usernames_env.split(",") if u.strip()] or ["@lusuferr"]

# Web Admin Panel Credentials
WEB_ADMIN_USERNAME = os.getenv("WEB_ADMIN_USERNAME", "admin")
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "admin123")

# Optional: Main channel ID for announcements/auto-posts
# You can set this via env var MAIN_CHANNEL_ID. If empty, we'll fall back to the
# first channel in `channels.json` for posting announcements.
MAIN_CHANNEL_ID = os.environ.get("MAIN_CHANNEL_ID", "")

# Points system settings
DAILY_REWARD_POINTS = 1
# Minimum points required to withdraw/redeem (can be updated from web panel)
MIN_WITHDRAWAL_POINTS = 100
# Backward-compat alias used by some admin commands
MIN_WITHDRAWAL_AMOUNT = MIN_WITHDRAWAL_POINTS

REFERRAL_CONFIG_FILE = _path_in_base("referral_config.json")
PENDING_REFERRALS_FILE = _path_in_base("pending_referrals.json")

def get_referral_points():
    if os.path.exists(REFERRAL_CONFIG_FILE):
        try:
            with open(REFERRAL_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return int(data.get("referral_points", 2))
        except Exception:
            return 2
    return 2

def set_referral_points(points: int):
    data = {}
    if os.path.exists(REFERRAL_CONFIG_FILE):
        try:
            with open(REFERRAL_CONFIG_FILE, 'r') as f:
                data = json.load(f)
        except Exception:
            pass
    data["referral_points"] = points
    with open(REFERRAL_CONFIG_FILE, 'w') as f:
        json.dump(data, f)

def get_daily_points():
    if os.path.exists(REFERRAL_CONFIG_FILE):
        try:
            with open(REFERRAL_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return int(data.get("daily_points", 1))
        except Exception:
            return 1
    return 1

def set_daily_points(points: int):
    data = {}
    if os.path.exists(REFERRAL_CONFIG_FILE):
        try:
            with open(REFERRAL_CONFIG_FILE, 'r') as f:
                data = json.load(f)
        except Exception:
            pass
    data["daily_points"] = points
    with open(REFERRAL_CONFIG_FILE, 'w') as f:
        json.dump(data, f)


# Points system settings
DEFAULT_REFERRAL_POINTS = get_referral_points()

# File names for data persistence (absolute paths)
USER_DATA_FILE = _path_in_base("user_data.json")
USER_ACTIVITY_FILE = _path_in_base("user_activity.json")
OTT_ACCOUNTS_FILE = _path_in_base("ott_accounts.json")
CATEGORIES_FILE = _path_in_base("categories.json")
CHANNELS_FILE = _path_in_base("channels.json")
CODES_FILE = _path_in_base("codes.json")
# Chat messages
CHAT_MESSAGES_FILE = _path_in_base("chat_messages.json")
CHANNEL_STATS_FILE = _path_in_base("channel_stats.json")
OTT_PRODUCTS_FILE = _path_in_base("ott_products.json")
# OTT products and orders
PRODUCTS_FILE = _path_in_base("products.json")
ORDERS_FILE = _path_in_base("orders.json")

# Buy account system files (separate from redeem system)
BUY_ACCOUNTS_FILE = _path_in_base("buy_accounts.json")
BUY_CATEGORIES_FILE = _path_in_base("buy_categories.json")
BROADCAST_HISTORY_FILE = _path_in_base("broadcast_history.json")

# Bot settings
BOT_USERNAME = "refer127bot"
MAX_MEMBERS_CACHE_DURATION = 300  # Cache membership check for 5 minutes (positive results)
NEGATIVE_MEMBERS_CACHE_DURATION = 60  # Cache negative results for 1 minute

# Webhook settings (for production)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.environ.get("PORT", 8000))

# Flask settings
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5001))
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")

# Scheduler settings
CHECK_MEMBERSHIP_INTERVAL = 1800  # Check every 30 minutes (reduced API load)

SCHEDULER_CONFIG_FILE = _path_in_base("scheduler_config.json")

def get_scheduler_interval():
    """Get scheduler interval in seconds (default 1800 = 30 mins)."""
    try:
        if os.path.exists(SCHEDULER_CONFIG_FILE):
             with open(SCHEDULER_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return int(data.get("interval_seconds", 1800))
    except Exception:
        pass
    return 1800

def set_scheduler_interval(seconds: int):
    """Set scheduler interval in seconds."""
    try:
        with open(SCHEDULER_CONFIG_FILE, 'w') as f:
            json.dump({"interval_seconds": int(seconds)}, f)
        return True
    except Exception:
        return False

# Feature flags
POWER_TOOLS_ENABLED = os.environ.get("POWER_TOOLS_ENABLED", "true").lower() != "false"
# Scheduler master switch (can be toggled from web panel)
SCHEDULER_ENABLED = True
# Dev convenience: auto-reload whole process on code/template changes
AUTO_RELOAD = os.environ.get("AUTO_RELOAD", "true").lower() != "false"

# Payment settings - UPI only (PayPal removed)
PAYMENT_METHODS = {
    "upi": {
        "enabled": True,
        "upi_id": "lusufer@slc",  # Your actual UPI ID
        "receiver_name": "Lusufer",  # Your actual name
        "details": "🏦 *UPI Payment*\n📱 UPI ID: `lusufer@slc`\n👤 Name: Lusufer",
        "instructions": "🔸 Scan the QR code below OR\n🔸 Send money to UPI ID: `lusufer@slc`\n🔸 Include Order ID in payment note\n🔸 Click 'I've Paid' after payment\n🔸 Share payment screenshot if asked"
    },
    "bank": {
        "enabled": False,
        "details": "Bank payments are currently disabled",
        "instructions": "Please use UPI payment method"
    },
    "wallet": {
        "enabled": False,
        "details": "Wallet payments are currently disabled", 
        "instructions": "Please use UPI payment method"
    }
}

# UPI QR Code Configuration
UPI_CONFIG = {
    "upi_id": "lusufer@slc",  # Your UPI ID
    "receiver_name": "Lusufer",  # Your name
    "merchant_code": "",  # Optional: Your merchant code if any
    "qr_api_url": "https://api.qrserver.com/v1/create-qr-code/",  # QR code generation API
}

# Load persisted payment config (if any) and merge it into defaults
try:
    _loaded_cfg = load_payment_config()
    if _loaded_cfg:
        if isinstance(_loaded_cfg.get("payment_methods"), dict):
            _deep_update(PAYMENT_METHODS, _loaded_cfg["payment_methods"]) 
        if isinstance(_loaded_cfg.get("upi_config"), dict):
            _deep_update(UPI_CONFIG, _loaded_cfg["upi_config"]) 
except Exception as _e:
    logger.error(f"Error applying persisted payment config: {_e}")

# PayPal Configuration - REMOVED
# PayPal payment method has been disabled

# Shopping feature control
SHOPPING_ENABLED = True  # Master switch for buy account feature

# Order settings
ORDER_EXPIRY_HOURS = 24  # Orders expire after 24 hours if not paid
MANUAL_VERIFICATION_TIMEOUT = 48  # Hours to wait for admin verification

# Shopping cart settings
CART_EXPIRY_HOURS = 24  # Cart expires after 24 hours
MAX_CART_ITEMS = 10  # Maximum items allowed in cart

# ANIMATIONS AND IMAGES CONFIGURATION
# ===================================

# Animation settings
ANIMATIONS_ENABLED = True
IMAGES_ENABLED = True

# Bot animations and images
BOT_ANIMATIONS = {
    "welcome": "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif",  # Welcome animation
    "success": "https://media.giphy.com/media/26ufnwz3wDUli7GU0/giphy.gif",  # Success animation
    "loading": "https://media.giphy.com/media/l3nWhI38IWDofyDrW/giphy.gif",  # Loading animation
    "error": "https://media.giphy.com/media/l2SpMUEMRJkkqYcta/giphy.gif",    # Error animation
    "money": "https://media.giphy.com/media/67ThRZlYBvibtdF9JH/giphy.gif",   # Money/payment animation
    "gift": "https://media.giphy.com/media/l0HlMr2G3EKFgpUY0/giphy.gif",    # Gift animation
    "celebration": "https://media.giphy.com/media/26u4lOMA8JKSnL9Uk/giphy.gif", # Celebration animation
    # Additional loading animations for variety
    "processing": "https://media.giphy.com/media/xTkcEQACH24SMPxIQg/giphy.gif", # Processing animation
    "thinking": "https://media.giphy.com/media/a5viI92PAF89q/giphy.gif",       # Thinking animation
}

# Category images/icons
CATEGORY_IMAGES = {
    "Netflix": "https://upload.wikimedia.org/wikipedia/commons/0/08/Netflix_2015_logo.svg",
    "Netflix-4K": "https://i.imgur.com/netflix4k.png",
    "Amazon Prime": "https://upload.wikimedia.org/wikipedia/commons/f/f1/Prime_Video.png",
    "Disney+": "https://upload.wikimedia.org/wikipedia/commons/3/36/Disney%2B_logo.svg",
    "Hulu": "https://upload.wikimedia.org/wikipedia/commons/e/e4/Hulu_Logo.svg",
    "HBO Max": "https://upload.wikimedia.org/wikipedia/commons/1/17/HBO_Max_Logo.svg",
    "Spotify": "https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg",
    "YouTube Premium": "https://upload.wikimedia.org/wikipedia/commons/b/b8/YouTube_Logo_2017.svg"
}

# Payment method images
PAYMENT_METHOD_IMAGES = {
    "upi": "https://upload.wikimedia.org/wikipedia/commons/e/e1/UPI-Logo-vector.svg",
    "bank": "https://cdn-icons-png.flaticon.com/512/214/214344.png",
    "wallet": "https://cdn-icons-png.flaticon.com/512/3135/3135715.png"
}

# Status icons/animations
STATUS_ANIMATIONS = {
    "pending": "⏳",
    "awaiting_screenshot": "📸",
    "awaiting_verification": "🔄",
    "completed": "✅",
    "cancelled": "❌",
    "rejected": "❌",
    "paid": "💳"
}

# Emoji animations for different actions
ACTION_EMOJIS = {
    "shopping": "🛍️",
    "cart": "🛒", 
    "payment": "💳",
    "delivery": "📦",
    "points": "⭐",
    "redeem": "🎁",
    "admin": "👨‍💼",
    "user": "👤",
    "channel": "📢",
    "stats": "📊",
    "settings": "⚙️"
}

# 127HUB Reseller License Keygen Configuration
KEYGEN_API_URL = os.getenv("KEYGEN_API_URL", "https://ai.127hub.com/api/reseller/generate")
KEYGEN_API_KEY = os.getenv("KEYGEN_API_KEY", "127HUB-RES-A3B907130A1D98F987F55930728C5442")
KEYGEN_KEY_TYPE = os.getenv("KEYGEN_KEY_TYPE", "@REFER127BOT")
KEYGEN_DURATION_DAYS = int(os.getenv("KEYGEN_DURATION_DAYS", "30"))
KEYGEN_MAX_DEVICES = int(os.getenv("KEYGEN_MAX_DEVICES", "1"))
KEYGEN_STATS_URL = os.getenv("KEYGEN_STATS_URL", "https://ai.127hub.com/api/reseller/stats")