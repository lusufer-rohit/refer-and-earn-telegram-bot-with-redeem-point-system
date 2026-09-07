import random
import logging
import time
from typing import List, Dict, Tuple, Optional, Union
import time
from datetime import datetime, timedelta
import asyncio

import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CallbackContext

import database as db

def get_auto_style(text: str, default: str = 'primary') -> str:
    text_lower = text.lower()
    if any(word in text_lower for word in ['back', 'close', 'cancel', 'delete', 'remove', 'ban', 'reject', '🔙', '❌']):
        return 'danger'
    if any(word in text_lower for word in ['success', 'confirm', 'pay', 'add', 'join', 'redeem', 'claim', 'approve', '✅']):
        return 'success'
    # 'secondary' is removed as it causes the keyboard to crash on supported clients
    return default

def ColoredInlineButton(*args, **kwargs):
    text = args[0] if args else kwargs.get('text', '')
    style = kwargs.pop('style', get_auto_style(text, 'primary'))
    icon_custom_emoji_id = kwargs.pop('icon_custom_emoji_id', None)
    api_kwargs = kwargs.get('api_kwargs', {})
    if style in ['primary', 'danger', 'success']:
        api_kwargs['style'] = style
    if icon_custom_emoji_id:
        api_kwargs['icon_custom_emoji_id'] = icon_custom_emoji_id
    if api_kwargs:
        kwargs['api_kwargs'] = api_kwargs
    return InlineKeyboardButton(*args, **kwargs)

def ColoredKeyboardButton(*args, **kwargs):
    text = args[0] if args else kwargs.get('text', '')
    style = kwargs.pop('style', get_auto_style(text, 'primary'))
    icon_custom_emoji_id = kwargs.pop('icon_custom_emoji_id', None)
    api_kwargs = kwargs.get('api_kwargs', {})
    if style in ['primary', 'danger', 'success']:
        api_kwargs['style'] = style
    if icon_custom_emoji_id:
        api_kwargs['icon_custom_emoji_id'] = icon_custom_emoji_id
    if api_kwargs:
        kwargs['api_kwargs'] = api_kwargs
    return KeyboardButton(*args, **kwargs)

from config import BOT_USERNAME, ADMIN_IDS, MAX_MEMBERS_CACHE_DURATION, NEGATIVE_MEMBERS_CACHE_DURATION
try:
    from config import OWNER_IDS as _OWNER_IDS
except Exception:
    _OWNER_IDS = []

from animations import AnimationManager, create_animated_text, ACTION_EMOJIS

logger = logging.getLogger(__name__)

# Cache for channel membership checks (user_id -> {channel_id: (is_member, timestamp)})
membership_cache = {}

async def check_user_in_channel(bot: telegram.Bot, user_id: int, 
                         chat_id: Union[str, int], force_refresh: bool = False) -> bool:
    """Check if a user is a member of a channel."""
    global membership_cache
    
    # Check cache first (separate TTLs for positive/negative)
    if not force_refresh and user_id in membership_cache and chat_id in membership_cache[user_id]:
        cached_result, timestamp = membership_cache[user_id][chat_id]
        ttl = MAX_MEMBERS_CACHE_DURATION if cached_result else NEGATIVE_MEMBERS_CACHE_DURATION
        if time.time() - timestamp < ttl:
            return cached_result
    
    # Normalize chat_id
    target_chat = chat_id
    try:
        if isinstance(chat_id, str) and (chat_id.startswith("-") or chat_id.isdigit()):
            target_chat = int(chat_id)
    except Exception:
        target_chat = chat_id

    try:
        # Get chat member status
        member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
        
        # Check if member is active (member, administrator, or creator)
        is_member = member.status in ['member', 'administrator', 'creator']
        
        # Cache the result
        if user_id not in membership_cache:
            membership_cache[user_id] = {}
        membership_cache[user_id][chat_id] = (is_member, time.time())
        
        return is_member
    except Exception as e:
        err_msg = str(e)
        # If Chat not found and target_chat is negative number without -100 prefix, try -100 prefix
        if "Chat not found" in err_msg and isinstance(target_chat, int) and target_chat < 0 and not str(target_chat).startswith("-100"):
            try:
                alt_chat = int(f"-100{abs(target_chat)}")
                member = await bot.get_chat_member(chat_id=alt_chat, user_id=user_id)
                is_member = member.status in ['member', 'administrator', 'creator']
                if user_id not in membership_cache:
                    membership_cache[user_id] = {}
                membership_cache[user_id][chat_id] = (is_member, time.time())
                return is_member
            except Exception:
                pass

        err_msg_lower = err_msg.lower()
        if any(msg in err_msg_lower for msg in [
            "member not found", 
            "user not found", 
            "participant_id_invalid", 
            "user_not_participant",
            "not a member",
            "user is not a member"
        ]):
            logger.debug(f"User {user_id} is not a member of channel {chat_id}")
        else:
            logger.warning(f"Channel membership check notice for user {user_id} in {chat_id}: {e}")
        # Fail closed on errors: treat as not a member and cache the negative result briefly
        if user_id not in membership_cache:
            membership_cache[user_id] = {}
        membership_cache[user_id][chat_id] = (False, time.time())
        return False

async def check_all_channels_membership(bot: telegram.Bot, user_id: int, force_refresh: bool = False) -> Tuple[bool, List[Dict]]:
    """Check if user is a member of all required channels.
    Returns (all_joined, not_joined_channels)"""
    try:
        channels = db.get_channels()
        
        # If no channels are required, user is considered to have joined all channels
        if not channels:
            return True, []
        
        not_joined = []
        all_joined = True
        
        # Admin exemption removed so admins can test membership blocks properly
            
        # Parallelize membership checks for speed
        async def check_one(ch):
            try:
                if "id" not in ch:
                    logger.error(f"Invalid channel data: {ch}")
                    return (ch, False)
                
                # Check channel type
                channel_type = ch.get("type", "telegram")
                
                if channel_type == "whatsapp":
                    # WhatsApp channels bypass logic:
                    # User explicitly requested to bypass WhatsApp checking.
                    # Always return True (assume joined)
                    return (ch, True)
                else:
                    # Telegram channel
                    is_member = await check_user_in_channel(bot, user_id, ch["id"], force_refresh=force_refresh)
                    return (ch, is_member)
            except Exception as e:
                logger.error(f"Error checking membership for channel {ch.get('id', 'unknown')}: {e}")
                return (ch, False)  # fail closed on errors

        results = await asyncio.gather(*(check_one(ch) for ch in channels))
        for ch, is_member in results:
            if not is_member:
                not_joined.append(ch)
                all_joined = False
        
        return all_joined, not_joined
    except Exception as e:
        logger.error(f"Error in check_all_channels_membership: {e}")
        # Fail closed on unexpected errors
        return False, []

def create_channels_keyboard(not_joined_channels: List[Dict]) -> InlineKeyboardMarkup:
    """Create keyboard with buttons to join required channels and verify membership."""
    keyboard = []
    
    for channel in not_joined_channels:
        keyboard.append([
            ColoredInlineButton(text=channel["button_name"], url=channel["link"])
        ])
    
    # Prominent Check/Verify button
    keyboard.append([
        ColoredInlineButton(text="✅ Joined / Verify Channels", callback_data="verify_membership")
    ])
        
    return InlineKeyboardMarkup(keyboard)

def is_group_chat(update: Update) -> bool:
    """Check if update is originating from a group or supergroup."""
    if not update:
        return False
    chat = update.effective_chat
    return chat is not None and chat.type in ["group", "supergroup"]

async def handle_group_restriction(update: Update, context: CallbackContext) -> bool:
    """
    Handle group chat interactions.
    Allow ID commands, but suppress general private bot workflows from running on group chatter.
    """
    if not is_group_chat(update):
        return False
        
    chat = update.effective_chat
    if chat:
        logger.debug(f"📢 GROUP ACTIVITY -> Title: '{chat.title}' | Chat ID: {chat.id}")

    if update.message and update.message.text:
        text = (update.message.text or "").strip()
        if text in ["/id", "!id", "/groupid", "!groupid"]:
            try:
                await update.message.reply_text(
                    f"🆔 *Chat Information:*\n\n"
                    f"📛 *Title:* `{chat.title}`\n"
                    f"🔢 *Chat ID:* `{chat.id}`",
                    parse_mode="Markdown"
                )
                return True
            except Exception as e:
                logger.error(f"Failed to reply with group id: {e}")
            return True
            
    # Suppress execution of private menus/membership checks inside groups
    return True

def create_main_menu_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """Create the main menu using colored keyboard buttons via api_kwargs."""
    keyboard = [
        [ColoredKeyboardButton("🔄 Start/Restart", style="primary"), ColoredKeyboardButton("🎰 Play Slot", style="danger")],
        [ColoredKeyboardButton("🎁 Claim Daily Reward", style="success"), ColoredKeyboardButton("👤 View My Profile", style="primary")],
        [ColoredKeyboardButton("🔗 Refer & Earn Points", style="primary"), ColoredKeyboardButton("🎟 Redeem Points", style="danger")],
        [ColoredKeyboardButton("💳 My Wallet Balance", style="success")],
        [ColoredKeyboardButton("💸 Transfer Points", style="danger"), ColoredKeyboardButton("🏆 View Leaderboard", style="primary")],
        [ColoredKeyboardButton("📢 Check Channel Status", style="danger")]
    ]
    
    # Add Exchange Account and FREE LOVABLE buttons
    keyboard.append([
        ColoredKeyboardButton("🔄 Exchange Account", style="primary"),
        ColoredKeyboardButton("💜 FREE LOVABLE", style="success")
    ])
        
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def is_admin(user_id: int) -> bool:
    """Check if a user is an admin (static only)."""
    return user_id in ADMIN_IDS

def is_owner(user_id: int) -> bool:
    """True if user is web/bot owner. Defaults to first ADMIN_IDS if OWNER_IDS not configured."""
    if _OWNER_IDS:
        return user_id in _OWNER_IDS
    # Fallback: first static admin treated as owner
    try:
        return bool(ADMIN_IDS and user_id == ADMIN_IDS[0])
    except Exception:
        return False

async def get_referral_link(bot: telegram.Bot, user_id: int) -> str:
    """Get a user's referral link."""
    username = await get_bot_username(bot)
    return f"https://t.me/{username}?start={user_id}"

async def get_bot_username(bot: telegram.Bot) -> str:
    """Get the bot's username."""
    global BOT_USERNAME
    
    if BOT_USERNAME is None:
        # Get bot info
        bot_info = await bot.get_me()
        BOT_USERNAME = bot_info.username
    
    return BOT_USERNAME

def parse_duration(duration_str: str) -> float:
    """Parse duration string like '30m', '24h', '7d' into hours (float)."""
    if not duration_str:
        return 24  # Default to 24 hours
    try:
        # Check if it's just a number (assume hours)
        hours = float(duration_str)
        return hours
    except ValueError:
        pass
    # Try to parse as duration string
    try:
        unit = duration_str[-1].lower()
        value = float(duration_str[:-1])
        if unit == 'm':
            return value / 60.0
        elif unit == 'h':
            return value
        elif unit == 'd':
            return value * 24
        elif unit == 'w':
            return value * 24 * 7
        else:
            return 24  # Default
    except (ValueError, IndexError):
        return 24  # Default

def clear_membership_cache():
    """Clear the membership cache."""
    global membership_cache
    membership_cache = {}

def format_time_elapsed(timestamp: int) -> str:
    """Format time elapsed since a timestamp."""
    now = int(time.time())
    diff = now - timestamp
    
    if diff < 60:
        return f"{diff} seconds ago"
    elif diff < 3600:
        minutes = diff // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < 86400:
        hours = diff // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = diff // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"

def random_winners(eligible_users: List[Dict], num_winners: int) -> List[Dict]:
    """Randomly select winners from eligible users."""
    if not eligible_users:
        return []
    
    # If fewer users than winners, all users win
    if len(eligible_users) <= num_winners:
        return eligible_users
    
    # Shuffle and select
    shuffled = eligible_users.copy()
    random.shuffle(shuffled)
    return shuffled[:num_winners]

async def broadcast_message(bot: telegram.Bot, users: List[int], 
                           message: str, parse_mode: str = None,
                           keyboard: InlineKeyboardMarkup = None) -> Tuple[int, int]:
    """Broadcast a message to a list of users.
    Returns (success_count, fail_count)"""
    success_count = 0
    fail_count = 0
    
    for user_id in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            success_count += 1
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.05)
            
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")
            fail_count += 1
    
    return success_count, fail_count

def get_daily_status_text(user_id: int) -> str:
    """Get text about daily reward status."""
    user_data = db.get_user_data(user_id)
    if not user_data:
        return "❌ User not found."
    
    last_daily = user_data.get("last_daily", 0)
    can_claim = db.can_claim_daily(user_id)
    
    if can_claim:
        import config
        return f"🎁 Daily Reward\n\nYou can claim your daily reward of {config.get_daily_points()} points!"
    else:
        # Calculate time until 24 hours pass
        wait_time = int(last_daily + 86400 - time.time())
        if wait_time < 0:
            wait_time = 0
            
        hours = wait_time // 3600
        minutes = (wait_time % 3600) // 60
        
        return (f"⏳ Daily Reward\n\n"
                f"You cannot claim your reward yet.\n"
                f"Next reward available in {hours}h {minutes}m.")

def get_profile_text(user_id: int) -> str:
    """Get formatted user profile card."""
    user_data = db.get_user_data(user_id)
    if not user_data:
        return "❌ User profile not found."
    
    points = user_data.get("points", 0)
    user_id_str = str(user_id)
    first_name = user_data.get("first_name", "") or "User"
    username = user_data.get("username", "")
    username_disp = f"@{username}" if username else "None"

    # Get referrals count safely
    all_data = db.get_user_data() or {}
    referrals_map = all_data.get("referrals", {}) if isinstance(all_data, dict) else {}
    referred_count = len(referrals_map.get(user_id_str, [])) if isinstance(referrals_map, dict) else 0
    
    # Check daily claim status
    last_claim = user_data.get("last_daily_claim", 0)
    current_time = int(time.time())
    can_claim = (current_time - last_claim) >= (24 * 3600)
    if can_claim:
        daily_status = "Ready to Claim 🎁"
    else:
        wait_seconds = (24 * 3600) - (current_time - last_claim)
        h = max(0, wait_seconds // 3600)
        m = max(0, (wait_seconds % 3600) // 60)
        daily_status = f"Next in {h}h {m}m ⏳"
    
    # Joined date
    join_date = (
        user_data.get("joined_at")
        or user_data.get("join_date")
        or user_data.get("created_at")
        or int(time.time())
    )
    join_str = datetime.fromtimestamp(join_date).strftime('%Y-%m-%d')
    redeemed_accounts = user_data.get("redeemed_accounts", [])
    redeemed_count = len(redeemed_accounts)

    profile_lines = [
        "👤 *USER PROFILE*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🆔 *User ID:* `{user_id}`",
        f"👤 *Name:* {first_name}",
        f"🏷️ *Username:* {username_disp}",
        f"💎 *Balance:* `{points}` Points",
        f"👥 *Total Referrals:* `{referred_count}`",
        f"⚡ *Daily Reward:* {daily_status}",
        f"🔑 *Redeemed Accounts:* `{redeemed_count}`",
        f"📅 *Member Since:* {join_str}",
        f"🛡️ *Status:* Active Member ✅",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 _Earn points by referring friends & claiming daily rewards!_"
    ]

    return "\n".join(profile_lines)

def get_available_accounts_keyboard() -> Optional[InlineKeyboardMarkup]:
    """Get keyboard with available OTT accounts for redemption."""
    try:
        # Get categories with available accounts
        accounts_by_category = db.get_available_ott_accounts()
        
        if not accounts_by_category:
            return None
        
        # Get categories info
        categories = db.get_categories()
        
        # Create buttons for each category
        keyboard = []
        
        for category, accounts in accounts_by_category.items():
            # Add defensive check for category existence
            if category and category in categories and categories[category].get("enabled", True):
                price = categories[category].get("price", 10)
                keyboard.append([
                    ColoredInlineButton(
                        f"{category} ({len(accounts)} available) - {price} points",
                        callback_data=f"redeem_{category}"
                    )
                ])
        
        if not keyboard:
            return None
        
        # Add back button
        keyboard.append([
            ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_available_accounts_keyboard: {e}")
        return None

def get_category_accounts_keyboard(category: str) -> Optional[InlineKeyboardMarkup]:
    """Get keyboard with accounts of a specific category."""
    try:
        # Validate category parameter
        if not category:
            return None
            
        accounts = db.get_ott_accounts(category)
        
        # Filter only available accounts
        available_accounts = [acc for acc in accounts if not acc.get("redeemed_by")]
        
        if not available_accounts:
            return None
        
        # Get category info
        categories = db.get_categories()
        if category not in categories:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Category '{category}' not found in categories list")
            return None
        
        price = categories[category].get("price", 10)
        
        # Create buttons for accounts (limit to 5 for UI)
        keyboard = []
        
        for i, account in enumerate(available_accounts[:5]):
            keyboard.append([
                ColoredInlineButton(
                    f"Redeem Account #{i+1} ({price} points)",
                    callback_data=f"confirm_redeem_{account['id']}"
                )
            ])
        
        # Add back buttons
        keyboard.append([
            ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
            ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_category_accounts_keyboard for category '{category}': {e}")
        return None

def get_products_keyboard() -> Optional[InlineKeyboardMarkup]:
    """Get keyboard with available OTT products for ordering."""
    try:
        products = db.list_products(enabled_only=True)
        if not products:
            return None
        keyboard = []
        for p in products:
            keyboard.append([
                ColoredInlineButton(
                    f"{p.get('name')} - ₹{p.get('price')}",
                    callback_data=f"order_product_{p.get('id')}"
                )
            ])
        keyboard.append([
            ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
        ])
        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error in get_products_keyboard: {e}")
        return None

    """Pick random winners from eligible users."""
    if not eligible_users or num_winners <= 0:
        return []
        
    # Ensure we don't try to pick more winners than available users
    num_winners = min(num_winners, len(eligible_users))
    
    return random.sample(eligible_users, num_winners)
