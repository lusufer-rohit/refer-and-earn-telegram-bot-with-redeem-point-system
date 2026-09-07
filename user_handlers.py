import logging
import time
import asyncio
from typing import Optional
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import CallbackContext, MessageHandler, filters, CommandHandler

import database as db
import utils
import config as cfg
from config import ADMIN_IDS
from handlers import handle_message
from animations import (
    AnimationManager, create_animated_text, send_preset_animation,
    with_loading_animation, get_task_loading_message
)
import notifications

logger = logging.getLogger(__name__)

@with_loading_animation(get_task_loading_message('user_registration'))
async def start_command(update: Update, context: CallbackContext) -> None:
    """Handle the /start command."""
    if not update.effective_user or not update.message:
        return
        
    # Check group restriction
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or "User"
    
    if not username:
        await update.message.reply_text(
            "⚠️ You must set a username in your Telegram settings to use this bot.\n\n"
            "1. Go to Settings\n"
            "2. Edit Profile\n"
            "3. Set a username\n"
            "4. Come back and try again!"
        )
        return
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
        
    # Check if this is a referral and store it persistently
    referred_by = None
    if context.args and len(context.args) > 0:
        try:
            referred_by = int(context.args[0])
            if referred_by == user_id:
                referred_by = None
            else:
                context.user_data["pending_referral"] = referred_by
                db.save_pending_referral(user_id, referred_by)
        except ValueError:
            pass
    else:
        # If no args, check if there's a pending referral in disk or memory
        referred_by = db.get_pending_referral(user_id) or context.user_data.get("pending_referral")

    # FORCE MEMBERSHIP CHECK ON /START
    # Send "Please wait" message before checking membership
    wait_message = await update.message.reply_text(
        "⏳ Please wait a moment... Checking channel requirements..."
    )
    
    # Check if user is in all required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id, force_refresh=True
    )
    
    # Delete the wait message
    try:
        await wait_message.delete()
    except Exception:
        pass
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        # Check if user was previously verified
        user_data = db.get_user_data(user_id)
        was_verified = user_data.get("channel_status", False) if user_data else False
        
        message = "🚨 To use this bot, you must join our required channel first!" 
        if was_verified:
            message = "Badmossi ni mittr.... Rejoin the channel to use the bot"
            
        await update.message.reply_text(message, reply_markup=keyboard)
        return
    
    # Create or update user (now that membership is verified)
    user_data = db.create_or_update_user(
        user_id=user_id,
        username=username,
        first_name=first_name,
        referred_by=referred_by
    )
    
    # Clear pending referral after registration/verification
    db.clear_pending_referral(user_id)
    context.user_data.pop("pending_referral", None)
    
    # If user was referred and it's their first time / newly awarded
    is_new_user = user_data.get("is_new", False)
    
    # Notify admins if new user
    if is_new_user:
        all_user_data = db.get_user_data()
        total_users = len(all_user_data.get("users", {}))
        username_clean = str(username).replace("_", "\\_").replace("*", "\\*") if username else "No username"
        username_display = f"@{username_clean}" if username else "No username"
        msg = (
            f"New User ---\n"
            f"User id - `{user_id}`\n"
            f"username - {username_display}\n"
            f"Total User - {total_users}"
        )
        all_admins = set(ADMIN_IDS)
        for admin_id in all_admins:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id} about new user: {e}")
    
    # Process referral notification
    if is_new_user and referred_by:
        logger.info(f"Processing referral: User {user_id} referred by {referred_by}")
        try:
            all_user_data = db.get_user_data()
            ref_user = all_user_data.get("users", {}).get(str(referred_by), {})
            ref_username = ref_user.get("username")
            ref_username_clean = str(ref_username).replace("_", "\\_").replace("*", "\\*") if ref_username else "No username"
            ref_username_disp = f"@{ref_username_clean}" if ref_username else "No username"
            
            user_name_clean = str(username).replace("_", "\\_").replace("*", "\\*") if username else "No username"
            referred_username_disp = f"@{user_name_clean}" if username else "No username"
            new_balance = ref_user.get("points", 0)
            total_referrals = len(all_user_data.get("referrals", {}).get(str(referred_by), []))
        except Exception:
            ref_username_disp = "No username"
            referred_username_disp = f"@{username}" if username else "No username"
            new_balance = 0
            total_referrals = 0

        # Notify referrer with details
        try:
            await context.bot.send_message(
                chat_id=referred_by,
                text=(
                    "🎉 *Referral Successful!*\n\n"
                    f"New user: {referred_username_disp} (ID: `{user_id}`)\n"
                    f"You earned *+{cfg.get_referral_points()} points*.\n"
                    f"Your new balance: *{new_balance} points*.\n"
                    f"Total referrals: *{total_referrals}*"
                ),
                parse_mode="Markdown"
            )
        except telegram.error.Forbidden:
            logger.info(f"Could not notify referrer {referred_by}: Bot was blocked by the user")
        except Exception as e:
            logger.error(f"Failed to notify referrer {referred_by}: {e}")

        # Notify admins with full details
        try:
            admin_text = (
                "🧩 *Referral Completed*\n\n"
                f"Referrer: {ref_username_disp} (ID: `{referred_by}`)\n"
                f"New User: {referred_username_disp} (ID: `{user_id}`)\n"
                f"Points Awarded: *+{cfg.get_referral_points()}*\n"
                f"Referrer New Balance: *{new_balance}*\n"
                f"Referrer Total Referrals: *{total_referrals}*"
            )
            all_admins = set(ADMIN_IDS)
            for admin_id in all_admins:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id} about referral: {e}")
        except Exception as e:
            logger.error(f"Failed to build/send admin referral notification: {e}")
    
    # Send welcome message and main menu directly (tutorial bypassed)
    await send_welcome_message(update, context)

async def send_welcome_message(update: Update, context: CallbackContext) -> None:
    """Send the welcome message and main menu keyboard in private chats."""
    user_id = update.effective_user.id if update.effective_user else None
    
    # If in group, never send ReplyKeyboardMarkup
    if utils.is_group_chat(update):
        await utils.handle_group_restriction(update, context)
        return

    keyboard = utils.create_main_menu_keyboard(user_id)

    # Build attractive welcome with live stats
    try:
        all_user_data = db.get_user_data()
        total_users = len(all_user_data.get("users", {}))
    except Exception:
        total_users = 0

    try:
        available_by_cat = db.get_available_ott_accounts() or {}
        total_available = sum(len(v) for v in available_by_cat.values())
    except Exception:
        total_available = 0

    welcome_title = create_animated_text("Welcome to 127HUB OTT Bot", "sparkle")
    features = (
        "🚀 Instant Delivery | 🔒 Safe & Secure | 🕑 24×7 Support\n"
        "🎁 Daily Rewards | 🔗 Refer & Earn"
    )
    stats = (
        f"👥 Users: {total_users}  •  🔑 Accounts: {total_available}"
    )
    cta = (
        "\n\n➡️ Use the menu below to start: Claim Daily, Refer friends, Redeem accounts"
    )

    welcome_text = (
        f"{welcome_title}\n\n"
        f"✨ Win premium OTT accounts, earn points, and have fun!\n\n"
        f"{features}\n\n"
        f"{stats}\n"
        f"{cta}"
    )

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(
            welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: CallbackContext) -> None:
    """Handle the /help command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Build dynamic values
    ref_pts = cfg.get_referral_points()
    daily_pts = cfg.get_daily_points()
    try:
        from config import MIN_WITHDRAWAL_POINTS as _MINW
        min_w = _MINW
    except Exception:
        min_w = 100

    text = (
        "🔍 Help & Commands\n\n"
        "✨ Use the buttons below for quick actions.\n\n"
        "🎯 Basics\n"
        "• /start — Start the bot\n"
        "• /help — This help\n"
        f"• /daily — Claim daily reward (+{daily_pts})\n"
        "• /profile — Your profile\n"
        f"• /refer — Get your link (+{ref_pts}/referral)\n\n"
        "🎟 Accounts\n"
        "• /redeem — Redeem points for free accounts\n"
        "• /myredeems — See redeemed accounts\n\n"
        "🎉 Giveaways\n"
        "💳 Wallet\n"
        "• /wallet — Balance & options\n"
        "• /transfer [user_id] [points] — Send points\n\n"
        "• /leaderboard — Top referrers\n"
        "• /top — Top by points\n\n"
        f"ℹ️ Tips: Min withdrawal: {min_w} points. Join required channels to use all features."
    )

    # Quick action keyboard
    keyboard = InlineKeyboardMarkup([
        [
            utils.ColoredInlineButton("🎁 Daily", callback_data="daily"),
            utils.ColoredInlineButton("👤 Profile", callback_data="profile"),
            utils.ColoredInlineButton("🔗 Refer", callback_data="refer"),
        ],
        [
            utils.ColoredInlineButton("🎟 Redeem", callback_data="redeem"),
            utils.ColoredInlineButton("💳 Wallet", callback_data="wallet"),
        ],
        [
            utils.ColoredInlineButton("🔙 Menu", callback_data="main_menu"),
        ],
    ])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

@with_loading_animation(get_task_loading_message('daily_claim'))
async def daily_command(update: Update, context: CallbackContext) -> None:
    """Handle the /daily command for daily reward."""
    if not update.effective_user or not update.message:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Check if user can claim daily reward
    can_claim = db.can_claim_daily(user_id)
    
    if not can_claim:
        # Get status text
        status_text = utils.get_daily_status_text(user_id)
        
        await update.message.reply_text(
            status_text,
            parse_mode="Markdown"
        )
        return
    
    # Update daily claim
    success, new_balance = db.update_daily_claim(user_id)
    
    if success:
        keyboard = utils.create_main_menu_keyboard(user_id)
        
        # Send daily reward animation
        await send_preset_animation(update, context, "daily_reward")
        # Use asyncio sleep to avoid blocking the event loop
        await asyncio.sleep(0.6)
        
        reward_text = create_animated_text("Daily Reward Claimed!", "gift")
        
        await update.message.reply_text(
            f"{reward_text}\n\n"
            f"🎁 Daily Reward\n\n"
            f"You've claimed your daily reward!\n"
            f"💰 +{getattr(cfg, 'DAILY_REWARD_POINTS', 1)} point added to your balance.\n\n"
            f"⭐ New balance: {new_balance} points\n\n"
            f"⏰ Come back tomorrow for another reward!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "❌ Failed to claim daily reward. Please try again later."
        )

@with_loading_animation()
async def profile_command(update: Update, context: CallbackContext) -> None:
    """Handle the /profile command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Get profile text
    profile_text = utils.get_profile_text(user_id)
    
    # Create keyboard with quick actions
    keyboard = InlineKeyboardMarkup([
        [
            utils.ColoredInlineButton("🎁 Claim Daily", callback_data="claim_daily"),
            utils.ColoredInlineButton("👥 Refer Friends", callback_data="refer")
        ],
        [
            utils.ColoredInlineButton("🔄 Refresh", callback_data="refresh_profile"),
            utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
        ]
    ])
    
    await update.message.reply_text(
        profile_text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@with_loading_animation(get_task_loading_message('referral_processing'))
async def refer_command(update: Update, context: CallbackContext) -> None:
    """Handle the /refer command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Get user data
    user_data = db.get_user_data(user_id)
    # Get correct referral count from referrals dict
    referrals_data = db.get_user_data()
    user_id_str = str(user_id)
    referred_count = len(referrals_data.get("referrals", {}).get(user_id_str, []))
    points_earned = referred_count * cfg.get_referral_points()
    
    # Get referral link
    referral_link = await utils.get_referral_link(context.bot, user_id)
    
    # Create keyboard with quick open/share
    from urllib.parse import quote
    share_text = quote("Join this awesome bot and earn points!")
    share_url = f"https://t.me/share/url?url={quote(referral_link)}&text={share_text}"
    keyboard = InlineKeyboardMarkup([
        [
            utils.ColoredInlineButton("🔗 Open Link", url=referral_link),
            utils.ColoredInlineButton("📤 Share", url=share_url)
        ],
        [
            utils.ColoredInlineButton("🔄 Refresh Stats", callback_data="refresh_refer"),
            utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
        ]
    ])
    
    await update.message.reply_text(
        f"� Refer & Earn Program\n\n"
        f"Invite your friends and earn points for free premium accounts!\n\n"
        f"✨ Benefits:\n"
        f"• Free Premium Accounts\n"
        f"• Instant Withdrawals\n"
        f"• 24/7 Support\n"
        f"• Safe & Secure\n\n"
        f"💰 You earn: {cfg.get_referral_points()} points per referral\n\n"
        f"🔗 Your Referral Link:\n"
        f"`{referral_link}`\n\n"
        f"📊 Your Stats:\n"
        f"• Referrals: {referred_count}\n"
        f"• Earnings: {points_earned} points",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@with_loading_animation(get_task_loading_message('account_redemption'))
async def redeem_command(update: Update, context: CallbackContext) -> None:
    """Handle the /redeem command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Get user data
    user_data = db.get_user_data(user_id)
    points = user_data.get("points", 0)
    
    # Get available accounts keyboard
    keyboard = utils.get_available_accounts_keyboard()
    
    if not keyboard:
        # Create back button
        keyboard = InlineKeyboardMarkup([
            [
                utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
            ]
        ])
        
        await update.message.reply_text(
            f"🎟 Redeem Accounts\n\n"
            f"Sorry, no accounts are available for redemption at the moment.\n\n"
            f"Please check back later or contact an admin.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    await update.message.reply_text(
        f"🎟 Redeem Accounts\n\n"
        f"Your current balance: {points} points\n\n"
        f"Select a category to redeem an account:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@with_loading_animation()
async def myredeems_command(update: Update, context: CallbackContext) -> None:
    """Show user's redeemed accounts with expiry info."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return

    user_id = update.effective_user.id

    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text("⚠️ You are banned from using this bot.")
        return

    user = db.get_user_data(user_id)
    redeemed_ids = user.get("redeemed_accounts", []) if user else []
    if not redeemed_ids:
        await update.message.reply_text("You haven't redeemed any accounts yet.")
        return

    all_accounts = db.get_ott_accounts()
    account_by_id = {a.get("id"): a for a in all_accounts}

    lines = ["🗂️ Your Redeemed Accounts:\n"]
    for acc_id in redeemed_ids[:20]:
        acc = account_by_id.get(acc_id)
        if not acc:
            continue
        category = acc.get("category", "Unknown")
        redeemed_at = acc.get("redeemed_at") or int(time.time())
        validity_days = acc.get("validity_days", 30)
        expiry = datetime.fromtimestamp(redeemed_at) + timedelta(days=validity_days)
        status = "✅ Active" if expiry > datetime.now() else "⌛ Expired"
        lines.append(f"• {category} — {status} (expires: {expiry.strftime('%Y-%m-%d')})")

    if len(redeemed_ids) > 20:
        lines.append(f"…and {len(redeemed_ids) - 20} more")

    await update.message.reply_text("\n".join(lines))

    # Note: stray admin notification block removed (variables undefined)





@with_loading_animation(get_task_loading_message('stats_calculation'))
async def leaderboard_command(update, context):
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    user_id = update.effective_user.id
    all_joined, not_joined = await utils.check_all_channels_membership(context.bot, user_id)
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    try:
        from database import get_leaderboard, get_user_data
        leaderboard = get_leaderboard(10)
        all_user_data = get_user_data()
        if not leaderboard:
            keyboard = InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
            await update.message.reply_text(
                "No leaderboard data available yet.",
                reply_markup=keyboard
            )
            return
        current_user_position = None
        current_user_referrals = 0
        user_id_str = str(user_id)
        all_referrals = {}
        for referrer_id, referred_users in all_user_data.get("referrals", {}).items():
            if not all_user_data["users"].get(referrer_id, {}).get("banned", False):
                all_referrals[referrer_id] = len(referred_users)
        sorted_all = sorted(all_referrals.items(), key=lambda x: x[1], reverse=True)
        for pos, (ref_id, count) in enumerate(sorted_all, 1):
            if ref_id == user_id_str:
                current_user_position = pos
                current_user_referrals = count
                break
        text = "🏆 Top 10 Referrers 🏆\n\n"
        for idx, user in enumerate(leaderboard, 1):
            username = user.get("username", "")
            first_name = user.get("first_name", "Unknown")
            referrals = user.get("referrals", 0)
            points = referrals * cfg.get_referral_points()
            if all_user_data["users"].get(str(user["id"]), {}).get("banned", False):
                continue
            username = username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            first_name = first_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            text += f"{idx}. {first_name} (@{username})\n"
            text += f"   • Referrals: {referrals}\n"
            text += f"   • Points earned: {points}\n\n"
        if current_user_position and current_user_position > 10:
            text += f"\nYour position: #{current_user_position} with {current_user_referrals} referrals"
        keyboard = InlineKeyboardMarkup([
            [utils.ColoredInlineButton("🔄 Refresh", callback_data="refresh_leaderboard")],
            [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
        ])
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in leaderboard command: {e}")
        keyboard = InlineKeyboardMarkup([
            [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
        ])
        await update.message.reply_text(
            "❌ An error occurred while fetching the leaderboard. Please try again later.",
            reply_markup=keyboard
        )

@with_loading_animation(get_task_loading_message('points_transfer'))
async def transfer_command(update: Update, context: CallbackContext) -> None:
    """Handle the /transfer command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Check if arguments are provided
    if not context.args or len(context.args) != 2:
        await update.message.reply_text(
            "💸 Transfer Points\n\n"
            "Usage: `/transfer [user_id or @username] [points]`\n\n"
            "Example: `/transfer 123456789 50`\n"
            "Example: `/transfer @friend 50`\n\n"
            "This will transfer points to the specified user.",
            parse_mode="Markdown"
        )
        return
    
    recipient_input = context.args[0]
    points_input = context.args[1]
    
    # Resolve recipient
    recipient_id = None
    try:
        recipient_id = int(recipient_input)
    except ValueError:
        # Try finding by username
        recipient_id = db.get_user_id_by_username(recipient_input)
    
    if not recipient_id:
        await update.message.reply_text(
            f"❌ User '{recipient_input}' not found.\n"
            "Please check the User ID or Username and try again."
        )
        return
        
    try:
        points = int(points_input)
    except ValueError:
        await update.message.reply_text("❌ Points amount must be a number.")
        return
    
    if points <= 0:
        await update.message.reply_text("❌ Points amount must be greater than 0.")
        return
    
    if recipient_id == user_id:
        await update.message.reply_text("❌ You cannot transfer points to yourself.")
        return
    
    # Perform the transfer
    success, message = db.transfer_points(user_id, recipient_id, points)
    
    if success:
        # Get updated balances and user info
        sender_data = db.get_user_data(user_id)
        recipient_data = db.get_user_data(recipient_id)
        
        sender_balance = sender_data.get("points", 0)
        recipient_balance = recipient_data.get("points", 0)
        recipient_name = recipient_data.get("first_name", "User")
        
        await update.message.reply_text(
            f"✅ Transfer Successful!\n\n"
            f"💰 Transferred: {points} points\n"
            f"👤 To: {recipient_name} (ID: `{recipient_id}`)\n\n"
            f"💳 Your new balance: {sender_balance} points\n"
            f"📊 Recipient's balance: {recipient_balance} points",
            parse_mode="Markdown"
        )
        
        # Notify recipient
        try:
            sender_name = update.effective_user.first_name
            await context.bot.send_message(
                chat_id=recipient_id,
                text=f"🎉 You received points!\n\n"
                     f"💰 Amount: {points} points\n"
                     f"👤 From: {sender_name} (ID: `{user_id}`)\n\n"
                     f"💳 Your new balance: {recipient_balance} points",
                parse_mode="Markdown"
            )
        except telegram.error.Forbidden:
            logger.info(f"Could not notify recipient {recipient_id}: Bot was blocked by the user")
        except Exception as e:
            logger.error(f"Failed to notify recipient {recipient_id}: {e}")
    else:
        await update.message.reply_text(f"❌ Transfer failed: {message}")

@with_loading_animation(get_task_loading_message('wallet_balance'))
async def wallet_command(update: Update, context: CallbackContext) -> None:
    """Handle the /wallet command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Get wallet balance
    rupees, points = db.get_user_wallet_balance(user_id)
    
    # Create keyboard with wallet options
    keyboard = InlineKeyboardMarkup([
        [
            utils.ColoredInlineButton("💸 Transfer Points", callback_data="transfer_points")
        ],
        [
            utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
        ]
    ])
    
    await update.message.reply_text(
        f"💳 Your Wallet\n\n"
        f"💰 Balance: {points} points\n"
        f"💵 Value: ₹{rupees:.2f}\n\n"
        f"💱 Conversion Rate:\n"
        f"10 points = ₹5.00\n\n"
        f"Use your wallet balance to transfer points or make purchases!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@with_loading_animation(get_task_loading_message('stats_calculation'))
async def top_command(update: Update, context: CallbackContext) -> None:
    """Show top users by points."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    # Check if user is in required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id
    )
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await update.message.reply_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Get all user data
    all_user_data = db.get_user_data()
    users = all_user_data.get("users", {})
    
    if not users:
        await update.message.reply_text(
            "❌ No users found in the database."
        )
        return
    
    # Sort users by points
    sorted_users = sorted(
        users.items(),
        key=lambda x: x[1].get("points", 0),
        reverse=True
    )[:10]  # Get top 10 users
    
    # Format message
    header = "🏆 Top Users by Points\n\n"
    user_blocks = []
    
    for i, (user_id_str, user_data) in enumerate(sorted_users, 1):
        try:
            username = user_data.get("username", "No username")
            first_name = user_data.get("first_name", "Unknown")
            points = user_data.get("points", 0)
            
            # Skip users with 0 points
            if points == 0:
                continue
                
            # Escape special characters for Markdown
            username = username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            first_name = first_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            
            username_display = f"@{username}" if username != "No username" else "No username"
            
            block = (
                f"{i}. {first_name} ({username_display})\n"
                f"   Points: {points}\n\n"
            )
            user_blocks.append(block)
        except Exception as e:
            logger.error(f"Error processing user {user_id_str}: {e}")
            continue
    
    if not user_blocks:
        await update.message.reply_text(
            "❌ No users with points found."
        )
        return
    
    # Create keyboard
    keyboard = InlineKeyboardMarkup([
        [
            utils.ColoredInlineButton("🔄 Refresh", callback_data="refresh_top"),
            utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
        ]
    ])
    
    # Send the message
    await update.message.reply_text(
        header + "".join(user_blocks),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ==================== NOTIFICATION COMMANDS ====================






async def claim_gift_command(update: Update, context: CallbackContext) -> None:
    """Handle the /claimgift command."""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    user_id = update.effective_user.id
    # Ensure user exists so points can be updated
    try:
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or "User"
        db.create_or_update_user(user_id=user_id, username=username, first_name=first_name)
    except Exception:
        pass
    
    if not context.args:
        await update.message.reply_text("Please provide a gift code. Usage: /claimgift [CODE]")
        return

    raw = context.args[0]
    # Sanitize: allow alphanumeric and hyphens (trimmed and upper)
    code = raw.strip().upper()
    # Enforce cooldown of 5 minutes between gift code claims
    try:
        if not db.can_claim_gift(user_id, cooldown_seconds=300):
            await update.message.reply_text("⏳ Please wait 5 minutes between gift code claims.")
            return
    except Exception:
        pass
    try:
        gift_code = db.get_gift_code_by_code(code)
    except Exception:
        gift_code = None

    if not gift_code:
        await update.message.reply_text("❌ Invalid gift code.")
        return

    if not gift_code.get("enabled", True):
        await update.message.reply_text("❌ This gift code is currently disabled.")
        return

    # Support both "users_used" and "redeemed_by"
    redeemed_list = gift_code.get("redeemed_by") or gift_code.get("users_used") or []
    if user_id in redeemed_list:
        await update.message.reply_text("❌ You have already used this gift code.")
        return

    # Handle expiry (check "expiry_at" or calculate from "created_at" + "days")
    expiry_at = gift_code.get("expiry_at")
    if expiry_at is None and "created_at" in gift_code and "days" in gift_code:
        expiry_at = gift_code["created_at"] + (gift_code["days"] * 86400)
    
    if expiry_at and expiry_at <= int(time.time()):
        await update.message.reply_text("❌ This gift code has expired.")
        return

    if gift_code.get("usage_count", 0) >= gift_code.get("usage_limit", 1):
        await update.message.reply_text("❌ This gift code has reached its usage limit.")
        return

    # All checks passed, award points and persist safely
    points_to_add = int(gift_code.get("points", 0))
    try:
        success, new_balance = db.update_user_points(user_id, points_to_add)
    except Exception:
        success, new_balance = (False, 0)
    if not success:
        await update.message.reply_text("❌ Failed to update your points. Please try again later.")
        return
    try:
        db.use_gift_code(code, user_id)
    except Exception:
        await update.message.reply_text("⚠️ Code redeemed but failed to record usage. Please contact admin.")
        return
    try:
        db.update_gift_claim(user_id)
    except Exception:
        pass
    
    await update.message.reply_text(f"🎉 Congratulations! You have successfully redeemed the gift code and received {points_to_add} points.")



async def lovable_menu_command(update: Update, context: CallbackContext) -> None:
    """Show the FREE LOVABLE main submenu for all users."""
    if await utils.handle_group_restriction(update, context):
        return
    user_id = update.effective_user.id
    user_data = db.get_user_data(user_id) or {}
    points = user_data.get("points", 0)
    bal_display = f"{points:g}" if isinstance(points, (int, float)) else str(points)

    from utils import ColoredInlineButton

    menu_text = (
        "💜 *FREE LOVABLE EXTENSION & PRO ACCESS* 🚀\n\n"
        "Generate your free **Lovable Pro License Key** or **Lifetime Admin Panel** directly using your reward points!\n\n"
        f"💰 *Your Current Balance:* `{bal_display} Points`\n\n"
        "👇 *Select an option below:*"
    )
    keyboard = [
        [ColoredInlineButton("🔑 1 Month Key (10 Points)", callback_data="lovable_1month")],
        [ColoredInlineButton("👑 Admin Panel Lifetime (500 Points)", callback_data="lovable_admin_account")],
        [ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]
    ]
    if update.callback_query:
        await update.callback_query.message.edit_text(
            menu_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif update.message:
        await update.message.reply_text(
            menu_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_keyboard_menu(update: Update, context: CallbackContext) -> None:
    """Handle inputs from the main menu keyboard."""
    if not update.message or not update.message.text:
        return
    if await utils.handle_group_restriction(update, context):
        return
        
    text = update.message.text
    user_id = update.effective_user.id
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        return
        
    if "Claim Daily Reward" in text:
        await daily_command(update, context)
    elif "View My Profile" in text:
        await profile_command(update, context)
    elif "Refer & Earn Points" in text:
        await refer_command(update, context)
    elif "Redeem Points" in text:
        await redeem_command(update, context)
    elif "FREE LOVABLE" in text or "Free Lovable" in text or "Lovable" in text:
        await lovable_menu_command(update, context)
    elif "Exchange Account" in text:
        from utils import ColoredInlineButton
        keyboard = [[ColoredInlineButton("Gmail Account", callback_data="exchange_gmail")]]
        await update.message.reply_text(
            "🔄 *Exchange Account*\n\nPlease select the account type:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif "My Wallet Balance" in text:
        await wallet_command(update, context)
    elif "Transfer Points" in text:
        await update.message.reply_text("💸 *Transfer Points*\n\nTo transfer points, use the command:\n`/transfer [user_id] [amount]`", parse_mode="Markdown")
    elif "View Leaderboard" in text:
        await leaderboard_command(update, context)
    elif "Start/Restart" in text:
        await start_command(update, context)
    elif "Play Slot" in text:
        from utils import ColoredKeyboardButton
        from telegram import ReplyKeyboardMarkup
        
        # Show rules and the new keyboard
        rules_text = (
            "🎰 **Slot Machine Rules** 🎰\n\n"
            "• **Entry Fee**: 10 Points per spin.\n"
            "• **Jackpot (7️⃣7️⃣7️⃣)**: Win 100 Points! (1.5% chance)\n"
            "• **Mini Jackpot (🍇🍇🍇, 🍋🍋🍋, BAR BAR BAR)**: Win 50 Points! (4.6% chance)\n"
            "• **Small Win (Any Pair 🍋🍋🍇)**: Win 10 Points! (approx 56% chance)\n"
            "• **Overall Win Chance**: ~62.5%. It is completely random!\n\n"
            "Click **▶️ Play** below to spin!"
        )
        keyboard = [
            [ColoredKeyboardButton("▶️ Play", style="success"), ColoredKeyboardButton("🔙 Exit", style="danger")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
        
        await update.message.reply_text(rules_text, reply_markup=reply_markup, parse_mode="Markdown")
        
    elif "▶️ Play" in text:
        # Slot Machine Logic
        user_data = db.get_user_data(user_id)
        if not user_data:
            await update.message.reply_text("⚠️ User not found.")
            return
            
        cost = 10
        if user_data.get("points", 0) < cost:
            await update.message.reply_text(f"❌ You need at least {cost} points to play the Slot Machine!")
            return
            
        # Deduct points
        db.update_user_points(user_id, -cost)
        
        # Send slot machine dice
        msg = await context.bot.send_dice(chat_id=user_id, emoji="🎰")
        
        import asyncio
        await asyncio.sleep(2.0)
        
        value = msg.dice.value
        prize = 0
        result_title = ""
        
        if value == 64: # 777 Jackpot
            prize = 100
            result_title = "🎉 **JACKPOT! 777!** 🏆"
        elif value in [1, 22, 43]: # Other triples
            prize = 50
            result_title = "🎰 **Triple Match!** 🎰"
        else:
            # Check for pairs
            r1 = (value - 1) & 3
            r2 = ((value - 1) >> 2) & 3
            r3 = ((value - 1) >> 4) & 3
            if r1 == r2 or r2 == r3 or r1 == r3:
                prize = 10
                result_title = "✨ **Small Win!** ✨ (Pair Match)"
            else:
                prize = 0
                result_title = "😔 **Better luck next time!**"
            
        if prize > 0:
            db.update_user_points(user_id, prize)
            new_bal = user_data.get("points", 0) - cost + prize
            await update.message.reply_text(f"{result_title}\nYou won {prize} points!\nNew Balance: {new_bal} points", parse_mode="Markdown")
        else:
            new_bal = user_data.get("points", 0) - cost
            await update.message.reply_text(f"{result_title}\nNew Balance: {new_bal} points", parse_mode="Markdown")
            
    elif "🔙 Exit" in text:
        await start_command(update, context)
    elif "Check Channel Status" in text:
        is_member, not_joined = await utils.check_all_channels_membership(context.bot, user_id, force_refresh=True)
        if is_member:
            await update.message.reply_text("✅ You are a member of all required channels!")
        else:
            keyboard = utils.create_channels_keyboard(not_joined)
            await update.message.reply_text(
                "❌ You haven't joined all required channels yet.\n\n"
                "Please join them below, then check again:",
                reply_markup=keyboard
            )
    else:
        # If it's not a menu button, fall back to general message handling
        await handle_message(update, context)

import json

async def handle_web_app_data(update: Update, context: CallbackContext) -> None:
    """Handle data sent from the Mini App"""
    if not update.effective_user or not update.effective_message:
        return
        
    user_id = update.effective_user.id
    data_str = update.effective_message.web_app_data.data
    
    try:
        data = json.loads(data_str)
        action = data.get("action")
        
        if action == "daily":
            # Simulate daily command
            await daily_command(update, context)
        elif action == "refer":
            # Simulate refer command
            await refer_command(update, context)
        elif action == "redeem":
            # Simulate redeem command
            await redeem_command(update, context)
        elif action == "slot":
            # Slot Machine Logic
            user_data = db.get_user_data(user_id)
            if not user_data:
                await update.message.reply_text("⚠️ User not found.")
                return
                
            cost = 10
            if user_data.get("points", 0) < cost:
                await update.message.reply_text(f"❌ You need at least {cost} points to play the Slot Machine!")
                return
                
            # Deduct points
            db.update_user_points(user_id, -cost)
            
            # Send slot machine dice
            msg = await context.bot.send_dice(chat_id=user_id, emoji="🎰")
            
            # Slot values: 1 to 64
            # 64 = 777 (Jackpot), 1 = BAR BAR BAR, 22 = Grapes Grapes Grapes, 43 = Lemon Lemon Lemon
            # Let's give specific rewards for matching combinations:
            value = msg.dice.value
            
            # Calculate win
            win_amount = 0
            if value == 64: # 777 Jackpot
                win_amount = 500
                result_text = "🎉 **JACKPOT! 777!** 🎉\nYou won massive 500 points!"
            elif value in [1, 22, 43]: # Other matching triples
                win_amount = 50
                result_text = "🎰 **Triple Match!** 🎰\nYou won 50 points!"
            else:
                # Check for doubles (reel 1 == reel 2)
                # Reel math for telegram slots:
                r1 = (value - 1) & 3
                r2 = ((value - 1) >> 2) & 3
                r3 = ((value - 1) >> 4) & 3
                if r1 == r2 or r2 == r3 or r1 == r3:
                    win_amount = 5
                    result_text = "✨ **Small Win!** ✨\nYou got a pair and won 5 points!"
                else:
                    result_text = "❌ **No Match.** Better luck next time!"
            
            if win_amount > 0:
                db.update_user_points(user_id, win_amount)
                
            # Reply with result after a short delay (for animation)
            await asyncio.sleep(2)
            await update.message.reply_text(result_text, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Error handling web_app_data: {e}")
        await update.message.reply_text("⚠️ Failed to process Mini App data.")

async def broadcast_command(update: Update, context: CallbackContext) -> None:
    """
    Admin Broadcast Command:
    Spawns a detached background task with smooth pacing so the bot NEVER freezes for normal users.
    Usage:
    - /broadcast Hello users!
    - /broadcast Hello users! [Join Now | https://t.me/example]
    - /broadcast --pin Important Announcement!
    - Or reply to any message (Text, Photo, Video, Document, etc.) with /broadcast
    """
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not utils.is_admin(user_id):
        await update.message.reply_text("⛔ *Unauthorized:* This command is for administrators only.", parse_mode="Markdown")
        return
    
    msg_text = update.message.text or ""
    reply_msg = update.message.reply_to_message
    raw_args = msg_text.partition(' ')[2].strip() if ' ' in msg_text else ""
    
    pin_message = False
    if "--pin" in raw_args or msg_text.startswith("/broadcast_pin"):
        pin_message = True
        raw_args = raw_args.replace("--pin", "").strip()

    # Parse optional inline button [Button Title | https://url]
    button_markup = None
    import re
    btn_match = re.search(r'\[([^\|\]]+)\|([^\]]+)\]', raw_args)
    if btn_match:
        btn_title = btn_match.group(1).strip()
        btn_url = btn_match.group(2).strip()
        raw_args = raw_args[:btn_match.start()].strip() + " " + raw_args[btn_match.end():].strip()
        raw_args = raw_args.strip()
        try:
            button_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text=btn_title, url=btn_url)]])
        except Exception:
            button_markup = None

    has_content = bool(raw_args) or (reply_msg and (reply_msg.text or reply_msg.photo or reply_msg.video or reply_msg.document or reply_msg.audio or reply_msg.animation or reply_msg.voice))
    if not has_content:
        help_msg = (
            "📢 *Admin Broadcast Command Usage:*\n\n"
            "1️⃣ *Direct Text Broadcast:*\n"
            "`/broadcast Hello everyone! New update is live.`\n\n"
            "2️⃣ *With Button:*\n"
            "`/broadcast Join our backup channel! [Join Channel | https://t.me/lusufer127]`\n\n"
            "3️⃣ *Reply to Any Post:*\n"
            "Reply to any Photo, Video, Document, or Text post with `/broadcast`\n\n"
            "4️⃣ *Pin Message:*\n"
            "`/broadcast --pin Notice...` or `/broadcast_pin Notice...`"
        )
        await update.message.reply_text(help_msg, parse_mode="Markdown")
        return

    # Fetch all non-banned target users
    all_user_data = db.get_user_data()
    users_dict = (all_user_data or {}).get("users", {})
    target_user_ids = [int(uid) for uid, u in users_dict.items() if not u.get("banned")]

    total_targets = len(target_user_ids)
    if total_targets == 0:
        await update.message.reply_text("❌ No users found to broadcast to.")
        return

    status_msg = await update.message.reply_text(
        f"🚀 *Broadcast Launched in Background!*\n\n"
        f"👥 *Total Targets:* `{total_targets}` users\n"
        f"⚡ *Mode:* Non-blocking background worker\n"
        f"📌 *Pin:* `{'Yes' if pin_message else 'No'}`\n\n"
        "Bot commands and normal users will continue working with zero lag! 🏎️",
        parse_mode="Markdown"
    )

    # Spawn background worker so main bot loop is 100% free
    asyncio.create_task(_run_in_bot_broadcast_worker(
        bot=context.bot,
        status_msg=status_msg,
        target_user_ids=target_user_ids,
        reply_msg=reply_msg,
        raw_args=raw_args,
        button_markup=button_markup,
        pin_message=pin_message
    ))

async def _run_in_bot_broadcast_worker(bot, status_msg, target_user_ids, reply_msg, raw_args, button_markup, pin_message):
    """Background worker for in-bot broadcast to keep main bot responsive."""
    total_targets = len(target_user_ids)
    sent_count = 0
    fail_count = 0
    start_time = time.time()
    last_edit_time = time.time()

    for idx, target_id in enumerate(target_user_ids, 1):
        try:
            sent_msg = None
            if reply_msg:
                if reply_msg.text:
                    text_to_send = raw_args if raw_args else reply_msg.text
                    try:
                        sent_msg = await bot.send_message(
                            chat_id=target_id,
                            text=text_to_send,
                            parse_mode="Markdown",
                            reply_markup=button_markup or reply_msg.reply_markup
                        )
                    except Exception:
                        sent_msg = await bot.send_message(
                            chat_id=target_id,
                            text=text_to_send,
                            reply_markup=button_markup or reply_msg.reply_markup
                        )
                elif reply_msg.photo:
                    photo_file_id = reply_msg.photo[-1].file_id
                    caption_to_send = raw_args if raw_args else (reply_msg.caption or "")
                    try:
                        sent_msg = await bot.send_photo(
                            chat_id=target_id,
                            photo=photo_file_id,
                            caption=caption_to_send,
                            parse_mode="Markdown" if caption_to_send else None,
                            reply_markup=button_markup or reply_msg.reply_markup
                        )
                    except Exception:
                        sent_msg = await bot.send_photo(
                            chat_id=target_id,
                            photo=photo_file_id,
                            caption=caption_to_send,
                            reply_markup=button_markup or reply_msg.reply_markup
                        )
                elif reply_msg.video:
                    sent_msg = await bot.send_video(
                        chat_id=target_id,
                        video=reply_msg.video.file_id,
                        caption=raw_args if raw_args else (reply_msg.caption or ""),
                        reply_markup=button_markup or reply_msg.reply_markup
                    )
                elif reply_msg.document:
                    sent_msg = await bot.send_document(
                        chat_id=target_id,
                        document=reply_msg.document.file_id,
                        caption=raw_args if raw_args else (reply_msg.caption or ""),
                        reply_markup=button_markup or reply_msg.reply_markup
                    )
                elif reply_msg.animation:
                    sent_msg = await bot.send_animation(
                        chat_id=target_id,
                        animation=reply_msg.animation.file_id,
                        caption=raw_args if raw_args else (reply_msg.caption or ""),
                        reply_markup=button_markup or reply_msg.reply_markup
                    )
                elif reply_msg.audio:
                    sent_msg = await bot.send_audio(
                        chat_id=target_id,
                        audio=reply_msg.audio.file_id,
                        caption=raw_args if raw_args else (reply_msg.caption or ""),
                        reply_markup=button_markup or reply_msg.reply_markup
                    )
                elif reply_msg.voice:
                    sent_msg = await bot.send_voice(
                        chat_id=target_id,
                        voice=reply_msg.voice.file_id,
                        caption=raw_args if raw_args else (reply_msg.caption or ""),
                        reply_markup=button_markup or reply_msg.reply_markup
                    )
            else:
                try:
                    sent_msg = await bot.send_message(
                        chat_id=target_id,
                        text=raw_args,
                        parse_mode="Markdown",
                        reply_markup=button_markup
                    )
                except Exception:
                    sent_msg = await bot.send_message(
                        chat_id=target_id,
                        text=raw_args,
                        reply_markup=button_markup
                    )

            if pin_message and sent_msg:
                try:
                    await bot.pin_chat_message(chat_id=target_id, message_id=sent_msg.message_id, disable_notification=True)
                except Exception:
                    pass

            sent_count += 1
        except Exception as e_send:
            err_str = str(e_send)
            if "retry after" in err_str.lower():
                await asyncio.sleep(3.0)
            fail_count += 1

        # Periodic live status update in chat (every 25 users or 5 seconds)
        if (idx % 25 == 0 or idx == total_targets) and (time.time() - last_edit_time > 4.0):
            try:
                pct = int((idx / total_targets) * 100)
                await status_msg.edit_text(
                    f"🚀 *Broadcasting in Progress...*\n\n"
                    f"👥 *Total:* `{total_targets}` users\n"
                    f"📊 *Progress:* `{pct}%` ({idx}/{total_targets})\n"
                    f"✅ *Sent:* `{sent_count}`\n"
                    f"❌ *Failed:* `{fail_count}`\n"
                    f"⏱ *Elapsed:* `{int(time.time() - start_time)}s`",
                    parse_mode="Markdown"
                )
                last_edit_time = time.time()
            except Exception:
                pass

        # Smooth pacing (~8 msgs/sec): leaves 75% Telegram API quota for real-time users
        await asyncio.sleep(0.12)

    duration = int(time.time() - start_time)
    final_summary = (
        "🎉 *Broadcast Completed Successfully!* 📢\n\n"
        f"👥 *Total Targets:* `{total_targets}`\n"
        f"✅ *Delivered:* `{sent_count}`\n"
        f"❌ *Failed / Blocked:* `{fail_count}`\n"
        f"⏱ *Total Time:* `{duration}s`\n"
        f"🕒 *Completed At:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    )

    try:
        await status_msg.edit_text(final_summary, parse_mode="Markdown")
    except Exception:
        pass

    import uuid
    db.save_broadcast({
        "id": str(uuid.uuid4()),
        "title": "Telegram In-Bot Broadcast",
        "message": raw_args[:200] if raw_args else "Media Broadcast",
        "type": "announcement",
        "notify_admins": True,
        "total": total_targets,
        "sent": sent_count,
        "failed": fail_count,
        "created_at": start_time,
        "status": "Completed"
    })

def setup_user_handlers(dispatcher):
    """Register all user-related command handlers."""
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("daily", daily_command))
    dispatcher.add_handler(CommandHandler("profile", profile_command))
    dispatcher.add_handler(CommandHandler("refer", refer_command))
    dispatcher.add_handler(CommandHandler("redeem", redeem_command))
    dispatcher.add_handler(CommandHandler("myredeems", myredeems_command))
    dispatcher.add_handler(CommandHandler("leaderboard", leaderboard_command))
    dispatcher.add_handler(CommandHandler("top", top_command))

    dispatcher.add_handler(CommandHandler("claimgift", claim_gift_command))
    dispatcher.add_handler(CommandHandler("redeemcode", claim_gift_command))
    
    dispatcher.add_handler(CommandHandler("wallet", wallet_command))
    dispatcher.add_handler(CommandHandler("transfer", transfer_command))
    dispatcher.add_handler(CommandHandler("lovable", lovable_menu_command))
    
    # Admin In-Bot Broadcast commands
    dispatcher.add_handler(CommandHandler("broadcast", broadcast_command))
    dispatcher.add_handler(CommandHandler("bc", broadcast_command))
    dispatcher.add_handler(CommandHandler("broadcast_pin", broadcast_command))
    
    # Web App Data handler
    dispatcher.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_menu))
