import logging
import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
import telegram.error
import io
import asyncio
import os
import time
from urllib.parse import quote
import httpx

import utils
import database as db
import config
from database import validate_code, redeem_code, get_user_data, save_user_data
from animations import AnimationManager, get_task_loading_message

logger = logging.getLogger(__name__)

async def safe_edit_message_text(query, text, parse_mode=None, reply_markup=None):
    """Safely edit a message's text, handling BadRequest, RetryAfter flood limits, and markdown errors."""
    try:
        current_text = query.message.text
        current_markup = query.message.reply_markup
        
        if (current_text == text and 
            ((current_markup is None and reply_markup is None) or 
             (current_markup and reply_markup and 
              current_markup.to_dict() == reply_markup.to_dict()))):
            try:
                await query.answer("Content is up to date")
            except Exception:
                pass
            return True
            
        await query.message.edit_text(
            text, 
            parse_mode=parse_mode, 
            reply_markup=reply_markup
        )
        return True
    except telegram.error.RetryAfter as e:
        logger.warning(f"Telegram flood limit in safe_edit_message_text: waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        try:
            await query.message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except Exception:
            return False
    except telegram.error.BadRequest as e:
        err_msg = str(e)
        if "Message is not modified" in err_msg:
            try:
                await query.answer("No changes to display")
            except Exception:
                pass
            return True
        elif "Can't parse entities" in err_msg or "entity" in err_msg.lower():
            logger.warning(f"Markdown parse error in safe_edit_message_text, falling back to unformatted text: {e}")
            try:
                clean_text = text.replace("*", "").replace("`", "").replace("_", "")
                await query.message.edit_text(clean_text, parse_mode=None, reply_markup=reply_markup)
                return True
            except Exception as e_fallback:
                logger.error(f"Fallback plain text edit also failed: {e_fallback}")
                return False
        else:
            logger.error(f"BadRequest error in safe_edit_message_text: {e}")
            return False
    except Exception as e:
        logger.error(f"Error in safe_edit_message_text: {e}")
        return False

async def handle_text(update: Update, context: CallbackContext) -> None:
    """Handle text messages that are not commands"""
    if not update.effective_user or not update.message:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    # Send "Please wait" message before checking membership
    wait_message = await update.message.reply_text(
        "⏳ Please wait a moment... System is checking your details..."
    )
    
    # Check if user is in all required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id, force_refresh=True
    )
    
    # Delete the wait message
    try:
        await wait_message.delete()
    except:
        pass
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        # Check if user was previously verified
        user_data = db.get_user_data(user_id)
        was_verified = user_data.get("channel_status", False) if user_data else False
        
        message = "🚨 To use this bot, wait 1minutes atlest and you must join our required channel first!" 
        if was_verified:
            message = "Badmossi ni mittr.... Rejoin the channel to use the bot"
            
        await update.message.reply_text(message, reply_markup=keyboard)
        return
    
    # Ignore messages that start with '.' 
    if text.startswith('.'):
        # Show menu for attempted commands
        keyboard = utils.create_main_menu_keyboard()
        await update.message.reply_text(
            "Please use the menu below or commands to interact with the bot:",
            reply_markup=keyboard
        )
        return
        
    # For other text messages, just ignore them
    return

async def handle_chat_join_request(update: Update, context: CallbackContext) -> None:
    """Auto-approve join requests for configured channels (if bot is admin)."""
    try:
        req = update.chat_join_request
        if not req:
            return
        chat_id = req.chat.id
        user_id = req.from_user.id
        # Approve only if channel is in our required channels list
        channels = db.get_channels()
        channel_ids = {c.get("id") for c in channels}
        if str(chat_id) in channel_ids or chat_id in channel_ids:
            try:
                await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
                logger.info(f"Approved join request for user {user_id} in chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to approve join request for {user_id} in {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Error in handle_chat_join_request: {e}")

async def handle_callback_query(update: Update, context: CallbackContext) -> None:
    """Handle callback queries from inline buttons"""
    if await utils.handle_group_restriction(update, context):
        return
    query = update.callback_query
    user_id = update.effective_user.id if update.effective_user else None
    callback_data = query.data
    logger.info(f"Callback query received: {callback_data} from user {user_id}")
    
    try:
        # Always attempt to answer callback query to stop loading indicator
        await query.answer()
    except telegram.error.BadRequest as e:
        if "Query is too old" in str(e):
            logger.warning(f"Ignoring 'Query is too old' for callback {callback_data}")
        else:
            logger.error(f"BadRequest error in handle_callback_query answer: {e}")
    except Exception as e:
        logger.error(f"Error answering callback query: {e}")
        
    if context.user_data is None:
        return
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await query.message.reply_text(
            "⚠️ You are banned from using this bot."
        )
        return
    
    logger.info(f"Processing callback_data: {callback_data}")
    
    # Handle main menu
    if callback_data == "main_menu":
        keyboard = utils.create_main_menu_keyboard()
        
        try:
            await query.message.delete()
        except Exception:
            pass
            
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Please select an option from the menu below:",
            reply_markup=keyboard
        )
        return
    
    # Send "Please wait" message before checking membership
    wait_message = await query.message.reply_text(
        "⏳ Please wait a moment... System is checking your details..."
    )
    
    # Check if user is in all required channels
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id, force_refresh=True
    )
    
    # Delete the wait message
    try:
        await wait_message.delete()
    except:
        pass
    
    if callback_data in ["check_membership", "verify_membership"]:
        try:
            # Force-refresh membership when user taps the button to make first-time join faster
            all_joined, not_joined = await utils.check_all_channels_membership(context.bot, user_id, force_refresh=True)
            if not all_joined:
                keyboard = utils.create_channels_keyboard(not_joined)
                
                # Check if user was previously verified
                user_data = db.get_user_data(user_id)
                was_verified = user_data.get("channel_status", False) if user_data else False
                
                message = "🚨 To use this bot, you must join our required channel first!"
                if was_verified:
                    message = "Badmossi ni mittr.... Rejoin the channel to use the bot"
                
                try:
                    await query.message.edit_text(message, reply_markup=keyboard)
                except Exception:
                    await query.answer("❌ You have not joined all required channels yet!", show_alert=True)
            else:
                # Process registration and referral awarding
                referred_by = db.get_pending_referral(user_id) or context.user_data.get("pending_referral")
                uname = query.from_user.username or ""
                fname = query.from_user.first_name or "User"
                user_data = db.create_or_update_user(
                    user_id=user_id,
                    username=uname,
                    first_name=fname,
                    referred_by=referred_by
                )
                db.clear_pending_referral(user_id)
                context.user_data.pop("pending_referral", None)

                is_new_user = user_data.get("is_new", False)
                if is_new_user and referred_by:
                    logger.info(f"Processing referral via verify: User {user_id} referred by {referred_by}")
                    try:
                        import config as cfg
                        all_user_data = db.get_user_data()
                        ref_user = all_user_data.get("users", {}).get(str(referred_by), {})
                        ref_username = ref_user.get("username")
                        ref_username_clean = str(ref_username).replace("_", "\\_").replace("*", "\\*") if ref_username else "No username"
                        ref_username_disp = f"@{ref_username_clean}" if ref_username else "No username"
                        user_name_clean = str(uname).replace("_", "\\_").replace("*", "\\*") if uname else "No username"
                        referred_username_disp = f"@{user_name_clean}" if uname else "No username"
                        new_balance = ref_user.get("points", 0)
                        total_referrals = len(all_user_data.get("referrals", {}).get(str(referred_by), []))
                        
                        # Notify referrer
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
                    except Exception as e:
                        logger.error(f"Error in referral handling on verify: {e}")

                try:
                    await query.message.delete()
                except Exception:
                    pass
                from user_handlers import send_welcome_message
                await send_welcome_message(update, context)
        except telegram.error.BadRequest as e:
            if "Message is not modified" in str(e):
                await query.answer("Your membership status hasn't changed")
            else:
                logger.error(f"BadRequest error in check_membership: {e}")
                await query.answer(f"Error: {str(e)[:200]}")
        except Exception as e:
            logger.error(f"Error in check_membership: {e}")
            await query.answer(f"An error occurred: {type(e).__name__}")
        return
    
    # For all other callbacks, ensure user is in all channels
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        
        await query.message.edit_text(
            "Badmossi ni mittr.... Rejoin the channel to use the bot",
            reply_markup=keyboard
        )
        return
    
    # Shopping/buy flow removed: catch any related callbacks early
    shopping_prefixes = (
        "shop_", "add_cart_", "remove_cart_", "payment_method_", "payment_confirmation_",
        "back_to_checkout_", "cancel_order_", "show_qr_", "copy_upi_", "view_order_",
        "enter_promo_", "view_promos_", "apply_promo_", "apply_specific_promo_",
        "remove_promo_", "proceed_payment_", "wallet_buy_", "wallet_confirm_", "add_cart_any_",
        "payment_", "proceed_payment_"
    )
    if (
        callback_data == "buy_account"
        or callback_data in ("shop_browse", "shop_cart", "shop_clear_cart", "shop_checkout", "shop_orders", "shop_info")
        or any(callback_data.startswith(p) for p in shopping_prefixes)
    ):
        await query.answer("🛍️ Shopping feature has been removed.")
        try:
            await query.message.edit_text(
                "🛍️ Shopping feature has been removed.",
                reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]])
            )
        except Exception:
            pass
        return

    # Handle daily reward
    if callback_data == "daily":
        # Show loading message (text only, no GIFs)
        loading_msg = None
        try:
            loading_msg = await AnimationManager.send_loading_animation(update, context, get_task_loading_message('daily_claim'))
            await asyncio.sleep(0.3)  # Brief visual feedback
        except Exception as e:
            logger.debug(f"Could not send loading message for daily: {e}")
        
        # Check if user can claim
        can_claim = db.can_claim_daily(user_id)
        
        if not can_claim:
            # Get status text
            status_text = utils.get_daily_status_text(user_id)
            
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔄 Refresh", callback_data="daily"),
                    utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
                ]
            ])
            
            await safe_edit_message_text(
                query,
                status_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        # Claim daily reward
        success, new_balance = db.update_daily_claim(user_id)
        
        # Clean up loading message before showing result
        if loading_msg:
            try:
                await asyncio.sleep(0.2)
                if hasattr(loading_msg, 'delete'):
                    await loading_msg.delete()
                else:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=loading_msg.message_id)
            except Exception as e:
                logger.debug(f"Could not clean up daily loading message: {e}")
        
        if success:
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
                ]
            ])
            
            await safe_edit_message_text(
                query,
                f"🎁 Daily Reward\n\n"
                f"You've claimed your daily reward!\n"
                f"+{config.get_daily_points()} points added to your balance.\n\n"
                f"New balance: {new_balance} points\n\n"
                f"Come back tomorrow for another reward!",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔄 Try Again", callback_data="daily"),
                    utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
                ]
            ])
            
            await safe_edit_message_text(
                query,
                "❌ Failed to claim daily reward. Please try again.",
                reply_markup=keyboard
            )
    
    # Handle profile
    elif callback_data == "profile" or callback_data == "refresh_profile":
        # Get profile text
        profile_text = utils.get_profile_text(user_id)
        
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
        
        await safe_edit_message_text(
            query,
            profile_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Handle refer
    elif callback_data == "refer" or callback_data == "refresh_refer":
        # Show loading message (text only, no GIFs)
        loading_msg = None
        try:
            loading_msg = await AnimationManager.send_loading_animation(update, context, get_task_loading_message('referral_processing'))
            await asyncio.sleep(0.3)  # Brief visual feedback
        except Exception as e:
            logger.debug(f"Could not send loading message for refer: {e}")
        
        # Get user data
        user_id_str = str(user_id)
        referrals_data = db.get_user_data() or {}
        referrals_map = referrals_data.get("referrals", {}) if isinstance(referrals_data, dict) else {}
        referred_count = len(referrals_map.get(user_id_str, [])) if isinstance(referrals_map, dict) else 0
        points_earned = referred_count * config.get_referral_points()
        
        # Get referral link
        referral_link = await utils.get_referral_link(context.bot, user_id)
        
        # Clean up loading message before showing result
        if loading_msg:
            try:
                await asyncio.sleep(0.2)
                if hasattr(loading_msg, 'delete'):
                    await loading_msg.delete()
                else:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=loading_msg.message_id)
            except Exception as e:
                logger.debug(f"Could not clean up refer loading message: {e}")
        
        # Add quick open/share buttons
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
        
        await safe_edit_message_text(
            query,
            f"🚀 Refer & Earn Program\n\n"
            f"Invite your friends and earn points for free premium accounts!\n\n"
            f"✨ Benefits:\n"
            f"• Free Premium Accounts\n"
            f"• Instant Withdrawals\n"
            f"• 24/7 Support\n"
            f"• Safe & Secure\n\n"
            f"💰 You earn: {config.get_referral_points()} points per referral\n\n"
            f"🔗 Your Referral Link:\n"
            f"`{referral_link}`\n\n"
            f"📊 Your Stats:\n"
            f"• Referrals: {referred_count}\n"
            f"• Earnings: {points_earned} points",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Handle redeem
    elif callback_data == "redeem":
        # Show loading message (text only, no GIFs)
        loading_msg = None
        try:
            loading_msg = await AnimationManager.send_loading_animation(update, context, get_task_loading_message('account_redemption'))
            await asyncio.sleep(0.3)  # Brief visual feedback
        except Exception as e:
            logger.debug(f"Could not send loading message for redeem: {e}")
        
        # Get user points
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        
        # Get available accounts keyboard
        keyboard = utils.get_available_accounts_keyboard()
        
        # Clean up loading message before showing result
        if loading_msg:
            try:
                await asyncio.sleep(0.2)
                if hasattr(loading_msg, 'delete'):
                    await loading_msg.delete()
                else:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=loading_msg.message_id)
            except Exception as e:
                logger.debug(f"Could not clean up redeem loading message: {e}")
        
        if not keyboard:
            # Create back button
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                f"🎟 Redeem Accounts\n\n"
                f"Sorry, no accounts are available for redemption at the moment.\n\n"
                f"Please check back later or contact an admin.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        await query.message.edit_text(
            f"🎟 Redeem Accounts\n\n"
            f"Your current balance: {points} points\n\n"
            f"Select a category to redeem an account:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Handle category selection for redemption
    elif callback_data.startswith("redeem_"):
        category = callback_data.replace("redeem_", "")
        
        # Get user points
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        
        # Get category info
        categories = db.get_categories()
        if category not in categories:
            # Invalid category, go back to main redeem
            await query.message.edit_text(
                "❌ Invalid category. Please try again.",
                reply_markup=utils.get_available_accounts_keyboard()
            )
            return
        
        price = categories[category].get("price", 10)
        
        # Check if user has enough points
        if points < price:
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                f"❌ You don't have enough points to redeem this account.\n\n"
                f"Required: {price} points\n"
                f"Your balance: {points} points\n\n"
                f"Earn more points by checking in daily and referring friends!",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        # Get accounts keyboard for this category
        keyboard = utils.get_category_accounts_keyboard(category)
        
        if not keyboard:
            # No accounts available in this category
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                f"❌ No accounts available in the {category} category.\n\n"
                f"Please select another category or check back later.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        await query.message.edit_text(
            f"🎟 {category} Accounts\n\n"
            f"Price: {price} points\n"
            f"Your balance: {points} points\n\n"
            f"Select an account to redeem:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Handle account redemption confirmation
    elif callback_data.startswith("confirm_redeem_"):
        try:
            account_id = int(callback_data.replace("confirm_redeem_", ""))
        except ValueError:
            # Invalid account ID, go back to main redeem
            await query.message.edit_text(
                "❌ Invalid account ID. Please try again.",
                reply_markup=utils.get_available_accounts_keyboard()
            )
            return
        
        # Get account info
        accounts = db.get_ott_accounts()
        account = next((a for a in accounts if a.get("id") == account_id), None)
        
        if not account:
            # Account not found
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                "❌ Account not found. It may have been redeemed already.",
                reply_markup=keyboard
            )
            return
        
        # Check if account is already redeemed; if so, try to pick another available in same category
        if account.get("redeemed_by"):
            accounts_same_cat = [a for a in accounts if a.get("category") == account.get("category") and not a.get("redeemed")]
            if accounts_same_cat:
                account = accounts_same_cat[0]
                account_id = account.get("id")
            else:
                keyboard = InlineKeyboardMarkup([
                    [
                        utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                        utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                    ]
                ])
                
                await query.message.edit_text(
                    "❌ This account has already been redeemed and no other accounts are available right now.",
                    reply_markup=keyboard
                )
                return
        
        category = account.get("category", "Unknown")
        
        # Get category info
        categories = db.get_categories()
        if category not in categories:
            # Invalid category
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                "❌ Category not found. Please try again.",
                reply_markup=keyboard
            )
            return
        
        price = categories[category].get("price", 10)
        
        # Get user points
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        
        # Check if user has enough points
        if points < price:
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                f"❌ You don't have enough points to redeem this account.\n\n"
                f"Required: {price} points\n"
                f"Your balance: {points} points\n\n"
                f"Earn more points by checking in daily and referring friends!",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        # Ask for final confirmation
        keyboard = InlineKeyboardMarkup([
            [
                utils.ColoredInlineButton("✅ Yes, Redeem", callback_data=f"final_redeem_{account_id}")
            ],
            [
                utils.ColoredInlineButton("❌ No, Cancel", callback_data=f"redeem_{category}")
            ]
        ])
        
        await query.message.edit_text(
            f"🎟 Confirm Redemption\n\n"
            f"Category: {category}\n"
            f"Price: {price} points\n"
            f"Your balance: {points} points\n\n"
            f"Are you sure you want to redeem this account?\n"
            f"This will deduct {price} points from your balance.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Handle final redemption
    elif callback_data.startswith("final_redeem_"):
        try:
            account_id = int(callback_data.replace("final_redeem_", ""))
        except ValueError:
            # Invalid account ID, go back to main redeem
            await query.message.edit_text(
                "❌ Invalid account ID. Please try again.",
                reply_markup=utils.get_available_accounts_keyboard()
            )
            return
        
        # Redeem the account (with fallback to next available in same category)
        try:
            success, account = db.redeem_ott_account(account_id, user_id)
        except Exception as e:
            logger.error(f"Exception in db.redeem_ott_account: {e}")
            success = False
            account = {}
        
        if not success:
            # Try to find another available account in the same category (race condition fallback)
            accounts = db.get_ott_accounts()
            current = next((a for a in accounts if a.get("id") == account_id), None)
            fallback_account = None
            if current:
                category = current.get("category")
                if category:
                    fallback_candidates = [a for a in accounts if a.get("category") == category and not a.get("redeemed")]
                    if fallback_candidates:
                        fallback_account = fallback_candidates[0]
                        success, account = db.redeem_ott_account(fallback_account.get("id"), user_id)
        
        if not success:
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("🔙 Back to Categories", callback_data="redeem"),
                    utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")
                ]
            ])
            
            await query.message.edit_text(
                "❌ Failed to redeem account. It may have been redeemed already or you don't have enough points.",
                reply_markup=keyboard
            )
            return
        
        # Get updated user points
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        
        # Get account details
        category = account.get("category", "Unknown")
        credentials = account.get("credentials", "Unknown")
        validity_days = account.get("validity_days", 30)
        watermark = account.get("watermark", "")
        
        # Send credentials as a text file to the user
        credentials_text = (
            f"Category: {category}\n"
            f"Credentials: {credentials}\n"
            f"Validity: {validity_days} days\n"
            f"Security Code: {watermark}\n"
            f"\nNote: Share responsibly. This code uniquely identifies your redemption.\n"
        )
        file_obj = io.BytesIO(credentials_text.encode("utf-8"))
        file_obj.name = f"{category}_credentials.txt"
        try:
            await context.bot.send_document(
                chat_id=user_id,
                document=file_obj,
                filename=file_obj.name,
                caption="Here are your redeemed account login details and if you got any problems contact us on @lusuferr / @lusuferchat_bot . Thank You for using our bot."
            )
        except Exception as e:
            logger.error(f"Failed to send credentials file to user {user_id}: {e}")
        
        # Notify admins
        from config import ADMIN_IDS
        all_admins = set(ADMIN_IDS)
        
        logger.info(f"Notifying {len(all_admins)} admins about redemption by user {user_id}")
        
        for admin_id in all_admins:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"👤 User <a href='tg://user?id={user_id}'>{html.escape(update.effective_user.first_name)}</a> (@{html.escape(update.effective_user.username or 'No Username')})\n"
                        f"ID: <code>{user_id}</code>\n"
                        f"redeemed an account in <b>{html.escape(category)}</b>\n"
                        f"Credentials: <code>{html.escape(credentials)}</code>\n"
                        f"Validity: {validity_days} days\n"
                        f"Watermark: <code>{html.escape(watermark)}</code>"
                    ),
                    parse_mode="HTML"
                )
                logger.debug(f"Successfully notified admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
        
        keyboard = InlineKeyboardMarkup([
            [
                utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
            ]
        ])
        
        await query.message.edit_text(
            f"✅ Account Redeemed Successfully!\n\n"
            f"Category: {category}\n"
            f"Credentials: {credentials}\n"
            f"Validity: {validity_days} days\n"
            f"Security Code: {watermark}\n\n"
            f"Your new balance: {points} points\n\n"
            f"Enjoy your premium account!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    
    # Order OTT flow
    elif callback_data.startswith("order_") or callback_data == "order_ott":
        await query.message.edit_text(
            "🛒 Order OTT feature has been removed.",
            reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]])
        )
        # Insert description as-is to allow Telegram HTML formatting
        desc_block = description or ""
        # Normalize line breaks and replace <br> tags with newlines to avoid HTML parse issues
        desc_html = desc_block.replace('\r\n','\n').replace('\r','\n')
        desc_html = desc_html.replace('<br />', '\n').replace('<br/>', '\n').replace('<br>', '\n')
        html_text = (
            f"🍪 {safe_title}\n\n"
            f"📝 Description:\n{desc_html}\n\n"
            f"🔗 Link: {html.escape(link) if link else 'Not provided'}\n\n"
            f"📊 Status: {status_emoji} {html.escape(status.title())}\n"
            f"🏷 Tags: {html.escape(tags_text)}\n\n"
            f"📅 Created: {html.escape(created_date)}\n"
            f"🔄 Updated: {html.escape(updated_date)}"
        )
        ok = await safe_edit_message_text(
            query,
            html_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        if not ok:
            # Fallback: escape description fully
            desc_html_safe = html.escape(desc_block).replace('\r\n','\n').replace('\r','\n')
            html_text_fb = (
                f"🍪 {safe_title}\n\n"
                f"📝 Description:\n{desc_html_safe}\n\n"
                f"🔗 Link: {html.escape(link) if link else 'Not provided'}\n\n"
                f"📊 Status: {status_emoji} {html.escape(status.title())}\n"
                f"🏷 Tags: {html.escape(tags_text)}\n\n"
                f"📅 Created: {html.escape(created_date)}\n"
                f"🔄 Updated: {html.escape(updated_date)}"
            )
            await safe_edit_message_text(
                query,
                html_text_fb,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    

    # Handle support
    elif callback_data == "support":
        context.user_data["support_mode"] = True
        await query.message.edit_text(
            "📝 Please type your message for the admin. They will reply to you as soon as possible.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
        )
        return
    # Handle claim gift
    elif callback_data == "claim_gift":
        context.user_data["claim_gift_mode"] = True
        await query.message.edit_text(
            "🎁 Please enter your gift code to claim your gift:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
        )
        return
    
    # Handle transfer points
    # Handle transfer points
    elif callback_data == "transfer_points" or callback_data == "transfer":
        # Set user in transfer mode
        context.user_data["transfer_mode"] = True
        
        await query.message.edit_text(
            "💸 Transfer Points\n\n"
            "Please send me the transfer details in this format:\n\n"
            "`/transfer user_id points`\n"
            "OR\n"
            "`/transfer @username points`\n\n"
            "Example: `/transfer 123456789 50`\n"
            "Example: `/transfer @friend 50`\n\n"
            "This will transfer points to the specified user.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="wallet")]
            ])
        )
        return
    # Handle buy with wallet
    # Wallet purchase features removed
    
    # Handle wallet buy category selection
    elif callback_data.startswith("wallet_buy_"):
        category = callback_data.replace("wallet_buy_", "")
        
        # Get accounts in this category
        accounts = db.get_buy_accounts(category)
        available_accounts = [acc for acc in accounts if not acc.get("redeemed")]
        
        if not available_accounts:
            await query.message.edit_text(
                f"❌ No accounts available in {category} at the moment.",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="buy_with_wallet")]
                ])
            )
            return
        
        # Get category info
        categories = db.get_buy_categories()
        category_info = categories.get(category, {})
        price_rupees = category_info.get("price", 0)
        
        # Get user wallet balance
        rupees, points = db.get_user_wallet_balance(user_id)
        required_points = db.convert_rupees_to_points(price_rupees)
        
        if points < required_points:
            await query.message.edit_text(
                f"❌ Insufficient wallet balance.\n\n"
                f"💳 Your balance: *{points} points* (₹{rupees:.2f})\n"
                f"💰 Required: *{required_points} points* (₹{price_rupees})\n\n"
                f"Earn more points to make this purchase!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="buy_with_wallet")]
                ])
            )
            return
        
        # Create purchase confirmation keyboard
        keyboard = InlineKeyboardMarkup([
            [
                utils.ColoredInlineButton("✅ Confirm Purchase", callback_data=f"wallet_confirm_{category}"),
                utils.ColoredInlineButton("❌ Cancel", callback_data="buy_with_wallet")
            ]
        ])
        
        await query.message.edit_text(
            f"🛒 Purchase Confirmation\n\n"
            f"📦 Category: {category}\n"
            f"💰 Price: ₹{price_rupees} ({required_points} points)\n"
            f"💳 Your balance: {points} points (₹{rupees:.2f})\n"
            f"💳 Balance after purchase: {points - required_points} points (₹{rupees - price_rupees:.2f})\n\n"
            f"Are you sure you want to purchase this account?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    # Handle wallet purchase confirmation
    elif callback_data.startswith("wallet_confirm_"):
        category = callback_data.replace("wallet_confirm_", "")
        
        # Get category info
        categories = db.get_buy_categories()
        category_info = categories.get(category, {})
        price_rupees = category_info.get("price", 0)
        
        # Get available account
        accounts = db.get_buy_accounts(category)
        available_accounts = [acc for acc in accounts if not acc.get("redeemed")]
        
        if not available_accounts:
            await query.message.edit_text(
                f"❌ No accounts available in {category} at the moment.",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="wallet")]
                ])
            )
            return
        
        # Use wallet for purchase
        success, message = db.use_wallet_for_purchase(user_id, price_rupees)
        
        if success:
            # Get the account to redeem
            account = available_accounts[0]
            
            # Mark account as redeemed
            success_redeem, redeemed_account = db.purchase_buy_account(account["id"], user_id, 0)  # 0 for wallet purchase
            
            if success_redeem:
                # Get updated wallet balance
                new_rupees, new_points = db.get_user_wallet_balance(user_id)
                
                # Send admin notification
                from config import ADMIN_IDS
                admin_text = (
                    f"💳 Wallet Purchase Completed\n\n"
                    f"👤 User: {update.effective_user.first_name}\n"
                    f"🆔 User ID: {user_id}\n"
                    f"📱 Username: @{update.effective_user.username or 'No username'}\n\n"
                    f"📦 Category: {category}\n"
                    f"💰 Amount: ₹{price_rupees} ({db.convert_rupees_to_points(price_rupees)} points)\n"
                    f"💳 New Balance: {new_points} points (₹{new_rupees:.2f})\n\n"
                    f"🔑 Account: {redeemed_account.get('credentials', 'N/A')}\n"
                    f"⏰ Validity: {redeemed_account.get('validity_days', 30)} days\n\n"
                    f"✅ Purchase completed automatically via wallet"
                )
                
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_text,
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify admin {admin_id} about wallet purchase: {e}")
                
                await query.message.edit_text(
                    f"✅ *Purchase Successful!*\n\n"
                    f"📦 Category: *{category}*\n"
                    f"💰 Paid: *₹{price_rupees}* ({db.convert_rupees_to_points(price_rupees)} points)\n"
                    f"💳 New balance: *{new_points} points* (₹{new_rupees:.2f})\n\n"
                    f"🔑 *Account Details:*\n"
                    f"```\n{redeemed_account.get('credentials', 'N/A')}\n```\n\n"
                    f"📅 Valid for: *{redeemed_account.get('validity_days', 30)} days*\n\n"
                    f"Thank you for your purchase!",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="wallet")]
                    ])
                )
            else:
                # Refund the points if account redemption failed
                db.update_user_points(user_id, db.convert_rupees_to_points(price_rupees))
                await query.message.edit_text(
                    f"❌ Purchase failed. Your points have been refunded.\n\n"
                    f"Please try again later or contact support.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="wallet")]
                    ])
                )
        else:
            await query.message.edit_text(
                f"❌ Purchase failed: {message}",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Wallet", callback_data="wallet")]
                ])
            )
        return
    
    # Handle wallet command
    elif callback_data == "wallet":
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
        
        await query.message.edit_text(
            f"💳 *Your Wallet*\n\n"
            f"💰 Balance: *{points} points*\n"
            f"💵 Value: *₹{rupees:.2f}*\n\n"
            f"💱 *Conversion Rate:*\n"
            f"10 points = ₹5.00\n\n"
            f"Use your wallet balance to transfer points or make purchases!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    # Handle refresh leaderboard
    elif callback_data == "refresh_leaderboard" or callback_data == "leaderboard":
        try:
            # Get leaderboard data
            from database import get_leaderboard, get_user_data
            leaderboard = get_leaderboard(10)
            all_user_data = get_user_data()
            
            if not leaderboard:
                keyboard = InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                ])
                await safe_edit_message_text(
                    query,
                    "No leaderboard data available yet.",
                    reply_markup=keyboard
                )
                return
            
            # Get current user's position
            current_user_position = None
            current_user_referrals = 0
            user_id_str = str(user_id)
            
            # Count all referrals for position calculation
            all_referrals = {}
            for referrer_id, referred_users in all_user_data.get("referrals", {}).items():
                if not all_user_data["users"].get(referrer_id, {}).get("banned", False):
                    all_referrals[referrer_id] = len(referred_users)
            
            # Sort all referrals to find current user's position
            sorted_all = sorted(all_referrals.items(), key=lambda x: x[1], reverse=True)
            for pos, (ref_id, count) in enumerate(sorted_all, 1):
                if ref_id == user_id_str:
                    current_user_position = pos
                    current_user_referrals = count
                    break
            
            # Format leaderboard text
            text = "🏆 Top 10 Referrers 🏆\n\n"
            
            for idx, user in enumerate(leaderboard, 1):
                username = user.get("username", "")
                first_name = user.get("first_name", "Unknown")
                referrals = user.get("referrals", 0)
                points = referrals * config.get_referral_points()
                
                # Skip banned users
                if all_user_data["users"].get(str(user["id"]), {}).get("banned", False):
                    continue
                    
                # Escape special characters for Markdown
                username = username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
                first_name = first_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
                
                text += f"{idx}. {first_name} (@{username})\n"
                text += f"   • Referrals: {referrals}\n"
                text += f"   • Points earned: {points}\n\n"
            
            # Add current user's position if not in top 10
            if current_user_position and current_user_position > 10:
                text += f"\nYour position: #{current_user_position} with {current_user_referrals} referrals"
            
            # Create keyboard with back button
            keyboard = InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔄 Refresh", callback_data="refresh_leaderboard")],
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
            
            await safe_edit_message_text(
                query,
                text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in refresh leaderboard: {e}")
            keyboard = InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
            await safe_edit_message_text(
                query,
                "❌ An error occurred while refreshing the leaderboard. Please try again later.",
                reply_markup=keyboard
            )
    elif callback_data == "refresh_top":
        try:
            # Get all user data
            all_user_data = db.get_user_data()
            users = all_user_data.get("users", {})
            
            if not users:
                await query.message.edit_text(
                    "❌ No users found in the database.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
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
                await query.message.edit_text(
                    "❌ No users with points found.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            # Create keyboard
            keyboard = InlineKeyboardMarkup([
                [
                    utils.ColoredInlineButton("�� Refresh", callback_data="refresh_top"),
                    utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")
                ]
            ])
            
            # Update the message
            await safe_edit_message_text(
                query,
                header + "".join(user_blocks),
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in refresh top: {e}")
            keyboard = InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
            await safe_edit_message_text(
                query,
                "❌ An error occurred while refreshing the top users. Please try again later.",
                reply_markup=keyboard
            )

    elif callback_data in ["exchange_gmail", "exchange_amazon"]:
        categories = db.get_categories()
        available_accounts = db.get_available_ott_accounts()
        keyboard_buttons = []
        for cat_name, cat_data in categories.items():
            if cat_data.get("enabled", True):
                count = len(available_accounts.get(cat_name, []))
                if count > 0:
                    keyboard_buttons.append([utils.ColoredInlineButton(f"Redeem {cat_name} ({count} available)", callback_data=f"check_exchange_cat_{cat_name}")])
        
        if not keyboard_buttons:
            keyboard_buttons.append([utils.ColoredInlineButton("❌ No Accounts Available to Exchange", callback_data="main_menu")])
        else:
            keyboard_buttons.append([utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")])
        
        instructions = (
            "📌 *Gmail Account Exchange Instructions*\n\n"
            "Follow these exact steps to exchange an account:\n\n"
            "1️⃣ Provide a valid and active **Gmail account** (`example@gmail.com`).\n"
            "2️⃣ ⚠️ **CRITICAL REQUIREMENT (2FA):** Make sure **2-Factor Authentication (2FA) / 2-Step Verification / Recovery OTP is completely DISABLED** on your Gmail.\n"
            "🚫 *If 2FA, phone verification, or prompt approval is enabled, your account will be strictly REJECTED immediately!* \n"
            "3️⃣ Keep the credentials ready in format: `email:password`\n\n"
            "Select the reward category you want to exchange for below. Once submitted, our team will review it."
        )
        await query.message.edit_text(
            instructions,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
        
    elif callback_data.startswith("check_exchange_cat_") or callback_data.startswith("check_amazon_cat_"):
        category = callback_data.replace("check_exchange_cat_", "").replace("check_amazon_cat_", "")
        context.user_data['awaiting_exchange_creds'] = category
        
        await query.message.edit_text(
            f"You selected *{category}*.\n\n"
            f"Please drop your Gmail credentials in this exact format:\n`email:password`\n\n"
            f"Example: `user@gmail.com:Pass123!`\n\n"
            f"⚠️ *Important Reminder:* 2FA must be turned OFF, otherwise your account will be rejected.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("Cancel", callback_data="exchange_gmail")]])
        )

    elif callback_data == "lovable_menu":
        from user_handlers import lovable_menu_command
        await lovable_menu_command(update, context)

    elif callback_data == "lovable_help":
        help_text = (
            "📥 *How to Download & Install Lovable Extension*\n\n"
            "1️⃣ Pick the build for your browser from:\n"
            "👉 [dl.eklas.dev](https://dl.eklas.dev)\n\n"
            "2️⃣ Available builds:\n"
            "• **Chrome**: Recommended latest desktop build\n"
            "• **Kiwi (Android)**: For Android phones\n"
            "• **Safari**: For Safari on macOS\n"
            "• **Firefox**: For Mozilla Firefox\n"
            "• **Chromium**: Edge, Brave, Opera, etc.\n\n"
            "3️⃣ Install the extension, open it, and paste your **1-Month Pro License Key** to activate!\n\n"
            "Click below to generate your 1 Month Key:"
        )
        keyboard = [
            [utils.ColoredInlineButton("🔑 Generate 1 Month Key (10 Pts)", callback_data="lovable_1month")],
            [utils.ColoredInlineButton("🌐 Open dl.eklas.dev", url="https://dl.eklas.dev")],
            [utils.ColoredInlineButton("🔙 Back", callback_data="lovable_menu")]
        ]
        await query.message.edit_text(help_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    elif callback_data == "lovable_admin_account":
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        cost = 500

        if points < cost:
            insufficient_text = (
                f"❌ *Insufficient Points!*\n\n"
                f"You need at least *{cost} Points* to generate a Lifetime Admin Panel Account.\n\n"
                f"💰 *Your Current Balance:* `{points} Points`\n"
                f"⚠️ *Required:* `{cost} Points` (Need `{cost - points}` more points)\n\n"
                f"💡 *How to earn points for free:*\n"
                f"• Claim your `/daily` bonus daily (+1 Point)\n"
                f"• Invite friends with `/refer` (+5 Points per friend!)"
            )
            keyboard = [
                [utils.ColoredInlineButton("🔗 Refer Friends & Earn Points", callback_data="refer_earn")],
                [utils.ColoredInlineButton("🔙 Back", callback_data="lovable_menu")]
            ]
            await query.message.edit_text(insufficient_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Deduct 500 points
        db.update_user_points(user_id, -cost)

        # Show loading message
        await query.message.edit_text("⏳ *Generating your Lifetime Admin Panel Account...*\nPlease wait a moment...", parse_mode="Markdown")

        # Call Keymint Admin Account API
        import httpx
        url = "https://keygen.eklas.dev/api/admin-account"
        payload = {"role": "admin"}
        api_success = False
        res_data = {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    res_data = resp.json()
                    if "username" in res_data and "password" in res_data:
                        api_success = True
        except Exception as e_api:
            logger.error(f"Error calling Admin Account API: {e_api}")

        if api_success:
            admin_username = res_data.get("username")
            admin_password = res_data.get("password")
            panel_url = res_data.get("panel_url", "https://io.eklas.dev")
            role = res_data.get("role", "admin").capitalize()

            raw_user = query.from_user.username or query.from_user.first_name or "User"
            safe_user = str(raw_user).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            username_tag = f"@{safe_user}" if query.from_user.username else safe_user

            # Record user activity
            db.record_user_activity(
                user_id,
                "Lovable Admin Panel Redeemed",
                f"Admin Account (Username: {admin_username})",
                points_impact=f"-{cost}"
            )

            new_bal = db.get_user_data(user_id).get("points", 0)
            bal_display = f"{new_bal:g}" if isinstance(new_bal, (int, float)) else str(new_bal)

            success_msg = (
                "🎉 *Lifetime Admin Panel Account Generated!* 🚀\n\n"
                "🔐 *Login Credentials:* (Tap to copy)\n"
                f"👤 *Username:* `{admin_username}`\n"
                f"🔑 *Password:* `{admin_password}`\n"
                f"🛡️ *Role:* `{role} (Lifetime Access)`\n\n"
                f"🌐 *Admin Panel URL:*\n"
                f"👉 [Open Admin Panel ({panel_url.replace('https://', '')})]({panel_url})\n\n"
                f"👤 *Issued To:* {username_tag}\n"
                f"💰 *Remaining Balance:* `{bal_display} Points`\n\n"
                "⚠️ *Important:* Save these credentials safely. They are generated securely and shown once."
            )
            keyboard = [
                [utils.ColoredInlineButton("🌐 Open Admin Panel", url=panel_url)],
                [utils.ColoredInlineButton("👑 Generate Another Admin", callback_data="lovable_admin_account")],
                [utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            await safe_edit_message_text(
                query,
                success_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            # Notify all admins about admin account redemption
            from config import ADMIN_IDS
            import time as _time
            admin_notif_text = (
                "👑 *New Lifetime Admin Panel Account Redeemed!*\n\n"
                f"👤 *User:* {username_tag}\n"
                f"🆔 *User ID:* `{user_id}`\n"
                f"👤 *Username:* `{admin_username}`\n"
                f"🔑 *Password:* `{admin_password}`\n"
                f"🌐 *Panel URL:* {panel_url}\n"
                f"💰 *Cost:* `-{cost} Points` (Remaining: `{bal_display} Points`)\n"
                f"🕒 *Time:* `{_time.strftime('%Y-%m-%d %H:%M:%S')}`"
            )
            for admin_id in (ADMIN_IDS or []):
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_notif_text,
                        parse_mode="Markdown"
                    )
                except Exception as e_adm:
                    logger.error(f"Failed to notify admin {admin_id} about Admin redemption: {e_adm}")
        else:
            # Refund points on failure
            db.update_user_points(user_id, cost)
            refund_bal = db.get_user_data(user_id).get("points", 0)
            error_msg = (
                "❌ *Admin Account Generation Failed*\n\n"
                "The server is temporarily busy. "
                f"Your *{cost} Points* have been **fully refunded** to your balance.\n\n"
                f"💰 *Current Balance:* `{refund_bal} Points`\n\n"
                "Please try again in a few moments."
            )
            keyboard = [
                [utils.ColoredInlineButton("🔄 Try Again", callback_data="lovable_admin_account")],
                [utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            await query.message.edit_text(
                error_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif callback_data == "lovable_1month" or callback_data.startswith("gen_lovable_"):
        user_data = db.get_user_data(user_id) or {}
        points = user_data.get("points", 0)
        cost = 10
        
        if points < cost:
            insufficient_text = (
                f"❌ *Insufficient Points!*\n\n"
                f"You need at least *{cost} Points* to generate a 1-Month Lovable Pro License Key.\n\n"
                f"💰 *Your Current Balance:* `{points} Points`\n"
                f"⚠️ *Required:* `{cost} Points` (Need `{cost - points}` more points)\n\n"
                f"💡 *How to earn points for free:*\n"
                f"• Claim your `/daily` bonus daily (+1 Point)\n"
                f"• Invite friends with `/refer` (+5 Points per friend!)"
            )
            keyboard = [
                [utils.ColoredInlineButton("🔗 Refer Friends & Earn Points", callback_data="refer_earn")],
                [utils.ColoredInlineButton("🔙 Back", callback_data="lovable_menu")]
            ]
            await query.message.edit_text(insufficient_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Deduct points
        db.update_user_points(user_id, -cost)
        
        # Step 1 Animation: Connecting & Authenticating
        try:
            await query.message.edit_text(
                "⚡ *[1/4] Connecting to Keygen Server...*\n"
                "`[■■□□□□□□□□] 25%`\n\n"
                "🔐 *Authenticating API credentials...*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        
        # Call 127HUB Reseller Keygen API
        import httpx
        from datetime import datetime, timedelta
        from config import KEYGEN_API_URL, KEYGEN_API_KEY, KEYGEN_KEY_TYPE, KEYGEN_DURATION_DAYS, KEYGEN_MAX_DEVICES

        # Extract user's exact real Telegram username
        user_db = db.get_user_data(user_id) or {}
        raw_tg_username = (
            query.from_user.username or 
            user_db.get("username") or 
            query.from_user.first_name or 
            f"user_{user_id}"
        )
        customer_username = str(raw_tg_username).lstrip("@").strip()

        headers = {
            "x-api-key": KEYGEN_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "type": KEYGEN_KEY_TYPE,
            "duration": KEYGEN_DURATION_DAYS,
            "unit": "days",
            "username": customer_username,
            "max_devices": KEYGEN_MAX_DEVICES,
            "device_limit": KEYGEN_MAX_DEVICES,
            "devices": KEYGEN_MAX_DEVICES
        }
        api_success = False
        res_data = {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(KEYGEN_API_URL, json=payload, headers=headers)
                if resp.status_code == 200:
                    res_data = resp.json()
                    if res_data.get("success") and ("key" in res_data or "license_key" in res_data):
                        api_success = True
                        res_data["license_key"] = res_data.get("key") or res_data.get("license_key")
                else:
                    logger.error(f"127HUB Keygen API returned status {resp.status_code}: {resp.text}")
        except Exception as e_api:
            logger.error(f"Error calling 127HUB Keygen API: {e_api}")

        if api_success:
            license_key = res_data.get("license_key")
            plan = "Pro"
            expires_at = res_data.get("expires_at", "")
            
            if not expires_at:
                expiry_str = (datetime.now() + timedelta(days=KEYGEN_DURATION_DAYS)).strftime("%Y-%m-%d")
            else:
                expiry_str = str(expires_at).split("T")[0] if "T" in str(expires_at) else str(expires_at)
                
            raw_user = query.from_user.username or query.from_user.first_name or "User"
            safe_user = str(raw_user).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            username_tag = f"@{safe_user}" if query.from_user.username else safe_user
            
            # Step 2 Animation: License Key Generated
            dev_limit_str = f"{KEYGEN_MAX_DEVICES} Device" if KEYGEN_MAX_DEVICES == 1 else f"{KEYGEN_MAX_DEVICES} Devices"
            try:
                await query.message.edit_text(
                    "🔑 *[2/4] License Key Minted Successfully!*\n"
                    "`[■■■■■□□□□□] 50%`\n\n"
                    f"👤 *Username:* `@{customer_username}`\n"
                    f"📱 *Device Limit:* `{dev_limit_str}`\n"
                    "⚙️ *Preparing on-the-fly zip download build...*",
                    parse_mode="Markdown"
                )
                await asyncio.sleep(0.7)
            except Exception:
                pass

            # Record user activity
            db.record_user_activity(
                user_id,
                "Lovable License Redeemed",
                f"1-Month {plan} (Key: {license_key})",
                points_impact=f"-{cost}"
            )
            
            new_bal = db.get_user_data(user_id).get("points", 0)
            bal_display = f"{new_bal:g}" if isinstance(new_bal, (int, float)) else str(new_bal)
            
            # Direct on-the-fly zip download URL from server
            download_zip_url = f"https://ai.127hub.com/api/update/download?key={license_key}"
            
            # Step 3 Animation: Packaging Extension ZIP
            try:
                await query.message.edit_text(
                    "📦 *[3/4] Packaging Extension & Fetching ZIP...*\n"
                    "`[■■■■■■■■□□] 75%`\n\n"
                    "📥 *Downloading full extension package from server...*",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            # Step 4 Animation: Delivering file
            dl_content = None
            try:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client_dl:
                    dl_resp = await client_dl.get(download_zip_url)
                    if dl_resp.status_code == 200 and dl_resp.content:
                        dl_content = dl_resp.content
            except Exception as e_file:
                logger.debug(f"Direct zip download failed: {e_file}")

            try:
                await query.message.edit_text(
                    "🚀 *[4/4] Finalizing & Delivering Package...*\n"
                    "`[■■■■■■■■■■] 100%`\n\n"
                    "📤 *Sending Lovable_Pro_Extension.zip to your chat...*",
                    parse_mode="Markdown"
                )
                await asyncio.sleep(0.6)
            except Exception:
                pass

            # Dispatch zip document directly into Telegram chat
            if dl_content:
                target_chat_id = query.message.chat_id if query.message else user_id
                doc_caption = (
                    "📦 *Lovable Pro Full Extension Package*\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔑 *License Key:* `{license_key}`\n"
                    f"📱 *Device Limit:* `{dev_limit_str}`\n"
                    f"⏳ *Valid For:* `30 Days`\n\n"
                    "👉 *Setup:* Extract this `.ZIP` file and load unpacked in Kiwi / Chrome / Edge extensions!"
                )
                try:
                    await context.bot.send_document(
                        chat_id=target_chat_id,
                        document=dl_content,
                        filename="Lovable_Pro_Extension.zip",
                        caption=doc_caption,
                        parse_mode="Markdown"
                    )
                except Exception:
                    try:
                        await context.bot.send_document(
                            chat_id=target_chat_id,
                            document=dl_content,
                            filename="Lovable_Pro_Extension.zip",
                            caption=doc_caption.replace("*", "").replace("`", "")
                        )
                    except Exception as e_send_doc:
                        logger.error(f"Failed to send zip document: {e_send_doc}")

            # Final success dashboard message edit
            success_msg = (
                "🎉 *Lovable Pro License Key Generated!* 🚀\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🔑 *License Key:* (Tap to copy)\n"
                f"`{license_key}`\n\n"
                f"📦 *Plan:* `{plan} (1 Month / 30 Days)`\n"
                f"👤 *Claimed by:* {username_tag}\n"
                f"📱 *Device Limit:* `{dev_limit_str}`\n"
                f"⏳ *Expiry Date:* `{expiry_str}`\n"
                f"💰 *Remaining Balance:* `{bal_display} Points`\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *Setup Instructions:*\n"
                "1. 📦 The **Lovable_Pro_Extension.zip** has been sent directly to this chat above! 👆\n"
                "2. You can also tap **📥 Direct Download Extension (.ZIP)** below anytime.\n"
                "3. Extract the `.zip` file in your browser extensions (*Developer Mode -> Load Unpacked*).\n"
                "4. Open the extension and paste your **Pro License Key** to activate!"
            )
            keyboard = [
                [utils.ColoredInlineButton("📥 Direct Download Extension (.ZIP)", url=download_zip_url)],
                [utils.ColoredInlineButton("🔑 Generate Another Key", callback_data="lovable_1month")],
                [utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            await safe_edit_message_text(
                query,
                success_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            # Notify all admins about key redemption
            from config import ADMIN_IDS
            import time as _time
            admin_notif_text = (
                "💜 *New Lovable Pro Key Redeemed!*\n\n"
                f"👤 *User:* {username_tag}\n"
                f"🆔 *User ID:* `{user_id}`\n"
                f"🔑 *License Key:*\n`{license_key}`\n\n"
                f"📦 *Plan:* `{plan} (1 Month / 30 Days)`\n"
                f"📱 *Device Limit:* `{dev_limit_str}`\n"
                f"⏳ *Expiry Date:* `{expiry_str}`\n"
                f"💰 *Cost:* `-10 Points` (Remaining: `{bal_display} Points`)\n"
                f"🕒 *Time:* `{_time.strftime('%Y-%m-%d %H:%M:%S')}`"
            )
            for admin_id in (ADMIN_IDS or []):
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_notif_text,
                        parse_mode="Markdown"
                    )
                except Exception as e_adm:
                    logger.error(f"Failed to notify admin {admin_id} about Lovable redemption: {e_adm}")
        else:
            # Refund points on failure
            db.update_user_points(user_id, cost)
            refund_bal = db.get_user_data(user_id).get("points", 0)
            error_msg = (
                "❌ *License Generation Failed*\n\n"
                "The key generator service is temporarily busy. "
                f"Your *{cost} Points* have been **fully refunded** to your balance.\n\n"
                f"💰 *Current Balance:* `{refund_bal} Points`\n\n"
                "Please try again in a few moments."
            )
            keyboard = [
                [utils.ColoredInlineButton("🔄 Try Again", callback_data="lovable_1month")],
                [utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            await safe_edit_message_text(
                query,
                error_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif callback_data.startswith("approve_exchange_"):
        if not utils.is_admin(user_id):
            return
        exchange_id = int(callback_data.replace("approve_exchange_", ""))
        context.user_data['awaiting_exchange_msg'] = {"id": exchange_id, "action": "approve"}
        await query.message.edit_text(
            "✅ *Approve Exchange*\n\n"
            "Please type a message to send to the user (e.g., 'DM me at @admin for your reward').",
            parse_mode="Markdown"
        )
        
    elif callback_data.startswith("reject_exchange_"):
        if not utils.is_admin(user_id):
            return
        exchange_id = int(callback_data.replace("reject_exchange_", ""))
        context.user_data['awaiting_exchange_msg'] = {"id": exchange_id, "action": "reject"}
        await query.message.edit_text(
            "❌ *Reject Exchange*\n\n"
            "Please type a reason for rejection to send to the user (e.g., 'Wrong password').",
            parse_mode="Markdown"
        )

async def handle_message(update, context):
    """Handle all incoming messages"""
    if not update.effective_user or not update.message or context.user_data is None:
        return
    if await utils.handle_group_restriction(update, context):
        return
    
    user_id = update.effective_user.id
    message = update.message

    # Log user messages early for live chat visibility
    try:
        if message.text and not message.text.startswith("/"):
            db.append_chat_message(user_id, from_admin=False, text=message.text)
        elif message.photo:
            file_id = message.photo[-1].file_id if message.photo else None
            caption = message.caption or ""
            db.append_chat_message(user_id, from_admin=False, text=caption, media_type="photo", file_id=file_id)
    except Exception as e:
        logger.debug(f"Chat log append failed: {e}")
    
    # If user is in claim gift flow, handle it immediately (bypass membership checks)
    if context.user_data.get("claim_gift_mode"):
        # Sanitize code input (allow alphanumeric and hyphens)
        code = (message.text or "").strip().upper()
        if not code:
            await message.reply_text("❌ Invalid gift code. Please try again.")
            return
        # Reuse the exact logic of /claimgift
        try:
            # Lazy import to avoid circular import at module load
            from user_handlers import claim_gift_command
            # Inject args for the command handler
            context.args = [code]
            await claim_gift_command(update, context)
        except Exception:
            # Fall back to local invalid message
            await message.reply_text("❌ Invalid or failed to redeem gift code. Please try again.")
        finally:
            context.user_data.pop("claim_gift_mode", None)
    # Handle admin message for exchange approval/rejection (immediate processing before channel checks)
    if context.user_data.get("awaiting_exchange_msg"):
        action_data = context.user_data.pop("awaiting_exchange_msg")
        exchange_id = action_data["id"]
        action = action_data["action"]
        admin_message = message.text or ""
        
        exchange = db.get_exchange_by_id(exchange_id)
        if not exchange:
            await message.reply_text("❌ Exchange not found in database.")
            return
            
        status = "approved" if action == "approve" else "rejected"
        db.update_exchange_status(exchange_id, status, admin_message)
        
        # Reward logic
        reward_text = ""
        if action == "approve":
            # Give the user an available account of the category
            available_accounts = db.get_available_ott_accounts().get(exchange["category"], [])
            if available_accounts:
                account_id = available_accounts[0]["id"]
                success, account = db.redeem_ott_account(account_id, exchange["user_id"], free=True)
                if success:
                    creds = account["credentials"].split(":", 1)
                    email = creds[0] if len(creds) > 0 else "N/A"
                    pwd = creds[1] if len(creds) > 1 else "N/A"
                    reward_text = (
                        f"🎉 *Reward Account Details*\n"
                        f"📦 Category: {account['category']}\n"
                        f"📧 Email: `{email}`\n"
                        f"🔑 Password: `{pwd}`\n"
                        f"⏳ Validity: {account.get('validity_days', 30)} days\n\n"
                    )
            
            if not reward_text:
                # Fallback: give them points
                price = db.get_categories().get(exchange["category"], {}).get("price", 10)
                db.update_user_points(exchange["user_id"], price)
                reward_text = f"🎁 *Reward Added*\nSorry, no {exchange['category']} accounts were in stock. We have credited *{price} points* to your wallet instead!\n\n"
            
        # Notify user
        try:
            status_emoji = "✅" if status == "approved" else "❌"
            user_msg = (
                f"{status_emoji} *Exchange Account Update*\n\n"
                f"Your submission for *{exchange['category']}* has been *{status.upper()}*.\n\n"
            )
            if reward_text:
                user_msg += reward_text
            
            user_msg += f"👨‍💻 *Admin Message*:\n`{admin_message}`"
            
            await context.bot.send_message(chat_id=exchange["user_id"], text=user_msg, parse_mode="Markdown")
            await message.reply_text(f"✅ Exchange marked as {status} and user has been notified.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]]))
        except Exception as e:
            await message.reply_text(f"✅ Exchange marked as {status}, but failed to notify user: {e}")
            
        return

    text = message.text or ""

    # Check if user is banned
    if db.is_user_banned(user_id):
        await message.reply_text("⚠️ You are banned from using this bot.")
        return
    
    # Send "Please wait" message before checking membership
    wait_message = await message.reply_text(
        "⏳ Please wait a moment... System is checking your details..."
    )
    
    # Check if user is in all required channels (use cache to reduce API calls)
    all_joined, not_joined = await utils.check_all_channels_membership(
        context.bot, user_id, force_refresh=False
    )
    
    # Delete the wait message
    try:
        await wait_message.delete()
    except:
        pass
    
    if not all_joined:
        keyboard = utils.create_channels_keyboard(not_joined)
        await message.reply_text(
            "🚨 To use this bot, you must join our required channel first!",
            reply_markup=keyboard
        )
        return
    
    # Handle support mode
    if context.user_data.get("support_mode"):
        # Send message to all admins
        from config import ADMIN_IDS
        support_text = (
            f"📝 *Support Message*\n\n"
            f"From: {update.effective_user.first_name}\n"
            f"User ID: `{user_id}`\n"
            f"Username: @{update.effective_user.username or 'No username'}\n\n"
            f"Message:\n{message.text}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=support_text,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to send support message to admin {admin_id}: {e}")
        
        # Clear support mode
        context.user_data.pop("support_mode", None)
        
        await message.reply_text(
            "✅ Your message has been sent to the admin. They will reply to you as soon as possible.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
            ])
        )
        return
    
    # Handle Gmail credentials check
    if context.user_data.get("awaiting_exchange_creds") or context.user_data.get("awaiting_amazon_creds"):
        if not text or ":" not in text:
            await message.reply_text("❌ Invalid format. Please drop your id:pass in format `email:password`")
            return
            
        email, password = text.split(":", 1)
        email = email.strip()
        password = password.strip()
        credentials = f"{email}:{password}"
        category = context.user_data.pop("awaiting_exchange_creds", None) or context.user_data.pop("awaiting_amazon_creds", None)
        
        # Save to DB
        exchange_id = db.add_pending_exchange(user_id, category, credentials)
        db.record_user_activity(user_id, "Exchange Submitted", f"Submitted Gmail account for {category}")
        
        # Send under review message
        await message.reply_text(
            "⏳ *Your account is under checking*\n\n"
            "Waiting for admin approval. You will receive a notification once it is reviewed.",
            parse_mode="Markdown"
        )
        
        # Notify admins
        from config import ADMIN_IDS
        admin_text = (
            f"🆕 *New Gmail Account Exchange*\n\n"
            f"User: `{user_id}`\n"
            f"Category: {category}\n"
            f"Credentials: `{credentials}`\n\n"
            f"Action required:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                utils.ColoredInlineButton("✅ Approve", callback_data=f"approve_exchange_{exchange_id}"),
                utils.ColoredInlineButton("❌ Reject", callback_data=f"reject_exchange_{exchange_id}")
            ]
        ])
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="Markdown", reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
                
        return
        
    # Handle order payment screenshot flow
    if context.user_data.get("awaiting_order_screenshot"):
        product = context.user_data.get("order_product")
        if not product:
            context.user_data.pop("awaiting_order_screenshot", None)
            await message.reply_text("❌ Order context missing. Please start again from the menu.")
            return
        if not message.photo:
            await message.reply_text("📸 Please send a payment screenshot to place the order.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("❌ Cancel", callback_data="cancel_order_flow")]]))
            return
        try:
            file_id = message.photo[-1].file_id
            user_note = message.caption or ""
            order_id = db.create_order(user_id, product, file_id, user_note=user_note)
            context.user_data.pop("awaiting_order_screenshot", None)
            context.user_data.pop("order_product", None)
            if order_id:
                await message.reply_text(
                    f"✅ Order placed!\n\nOrder ID: #{order_id}\nProduct: {product.get('name')}\nPrice: ₹{product.get('price')}\n\nAn admin will review your payment and contact you shortly.",
                    reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]])
                )
                # Notify admins
                try:
                    from config import ADMIN_IDS
                    for admin_id in ADMIN_IDS:
                        try:
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=(
                                    f"🆕 *New Order #{order_id}*\n"
                                    f"User: `{user_id}`\n"
                                    f"Product: {product.get('name')}\n"
                                    f"Price: ₹{product.get('price')}\n"
                                    f"Note: {user_note or '-'}\n\n"
                                    f"Review in web panel: Orders page."
                                ),
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.error(f"Notify admin {admin_id} failed: {e}")
                except Exception as e:
                    logger.error(f"Admin notify failed: {e}")
            else:
                await message.reply_text("❌ Failed to create order. Please try again.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Main Menu", callback_data="main_menu")]]))
            return
        except Exception as e:
            logger.error(f"Error handling order screenshot: {e}")
            await message.reply_text("❌ Error processing your order. Please try again.")
            return
    
    # Handle gift code claiming
    if context.user_data.get("claim_gift_mode"):
        # Sanitize code input (remove spaces but keep hyphens)
        code = (message.text or "").strip().upper()
        
        # Support both web-panel gift codes and bot one-time codes
        gift = db.get_gift_code_by_code(code)
        if gift:
            # Validate gift code constraints
            now = int(time.time())
            # Ensure user exists (some users may not have completed /start successfully)
            try:
                uname = update.effective_user.username if update.effective_user else ""
                fname = update.effective_user.first_name if update.effective_user else "User"
                db.create_or_update_user(user_id=user_id, username=uname or "", first_name=fname or "User")
            except Exception:
                pass
            # Enforce 5-minute cooldown between gift code claims
            try:
                if not db.can_claim_gift(user_id, cooldown_seconds=300):
                    remaining = 300 - (now - (db.get_user_data(user_id) or {}).get('last_gift_claim', 0))
                    if remaining < 0:
                        remaining = 0
                    minutes = remaining // 60
                    seconds = remaining % 60
                    await message.reply_text(
                        f"⏳ Please wait {minutes}m {seconds}s before claiming another gift code.",
                        reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]])
                    )
                    context.user_data.pop("claim_gift_mode", None)
                    return
            except Exception:
                pass
            # Check expiry (handle missing expiry_at via created_at + days)
            expiry_val = gift.get("expiry_at")
            if expiry_val is None and "created_at" in gift and "days" in gift:
                expiry_val = int(gift["created_at"]) + (int(gift["days"]) * 86400)
            
            # Support both "users_used" and "redeemed_by"
            redeemed_list = gift.get("redeemed_by") or gift.get("users_used") or []
            
            if not gift.get("enabled", True):
                await message.reply_text("❌ This gift code is currently disabled.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
            elif expiry_val and now > int(expiry_val):
                await message.reply_text("❌ This gift code has expired.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
            elif user_id in redeemed_list:
                await message.reply_text("❌ You have already used this gift code.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
            elif int(gift.get("usage_limit", 1)) <= int(gift.get("usage_count", 0)):
                await message.reply_text("❌ This gift code has reached its usage limit.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
            else:
                # Apply points and mark used
                success, new_balance = db.update_user_points(user_id, int(gift.get("points", 0)))
                if success and db.use_gift_code(code, user_id):
                    try:
                        db.update_gift_claim(user_id)
                    except Exception:
                        pass
                    # Try to update the channel post for this gift batch
                    try:
                        updated_gift = db.get_gift_code_by_code(code) or {}
                        batch_id = updated_gift.get("post_batch_id")
                        if batch_id:
                            chat_id, message_id = db.get_batch_post_info(batch_id)
                            if chat_id and message_id:
                                text = db.build_gift_post_text_for_batch(batch_id, bot_handle="@refer127bot")
                                # Try editing via bot first; fallback to HTTP API
                                edited = False
                                try:
                                    await context.bot.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=message_id,
                                        text=text,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True
                                    )
                                    edited = True
                                except Exception as e_edit:
                                    logger.error(f"Failed to edit gift post via bot API: {e_edit}")
                                if not edited:
                                    try:
                                        from app import get_config_value
                                        token = get_config_value('TOKEN', '')
                                        if token:
                                            api_url = f"https://api.telegram.org/bot{token}/editMessageText"
                                            async with httpx.AsyncClient(timeout=10.0) as http_client:
                                                await http_client.post(api_url, data={
                                                    'chat_id': chat_id,
                                                    'message_id': message_id,
                                                    'text': text,
                                                    'parse_mode': 'HTML',
                                                    'disable_web_page_preview': True
                                                })
                                            edited = True
                                    except Exception as e_http:
                                        logger.error(f"Failed to edit gift post via HTTP: {e_http}")
                    except Exception as e_upd:
                        logger.error(f"Error updating gift codes channel post: {e_upd}")
                    await message.reply_text(
                        f"🎉 Congratulations! You have successfully redeemed the gift code and received {gift.get('points', 0)} points.",
                        reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]])
                    )
                else:
                    await message.reply_text("❌ Failed to redeem the gift code. Please try again later.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
        else:
            # Fallback to old one-time code system
            if db.validate_code(code):
                points = db.redeem_code(code, user_id)
                if points:
                    await message.reply_text(
                        f"🎁 *Gift Code Redeemed!*\n\nYou received *{points} points*!",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]])
                    )
                else:
                    await message.reply_text("❌ This code has already been used.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
            else:
                await message.reply_text("❌ Invalid gift code. Please check and try again.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
        
        # Clear gift claiming mode
        context.user_data.pop("claim_gift_mode", None)
        return
    
    # Handle transfer mode
    if context.user_data.get("transfer_mode"):
        try:
            # Parse transfer details (format: user_id points)
            parts = message.text.strip().split()
            if len(parts) != 2:
                await message.reply_text(
                    "❌ Invalid format. Please use: `user_id points` or `@username points`\n\n"
                    "Example: `123456789 50`\n"
                    "Example: `@friend 50`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            target_input = parts[0]
            try:
                points_to_transfer = int(parts[1])
            except ValueError:
                await message.reply_text("❌ Points amount must be a number.")
                return

            # Resolve target user
            target_user_id = None
            try:
                target_user_id = int(target_input)
            except ValueError:
                target_user_id = db.get_user_id_by_username(target_input)
            
            if not target_user_id:
                await message.reply_text(
                    f"❌ User '{target_input}' not found.\n"
                    "Please check the User ID or Username and try again.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            if points_to_transfer <= 0:
                await message.reply_text(
                    "❌ Points must be greater than 0.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            if target_user_id == user_id:
                await message.reply_text(
                    "❌ You cannot transfer points to yourself.",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                return

            # Perform transfer
            success, msg_text = db.transfer_points(user_id, target_user_id, points_to_transfer)
            
            if success:
                target_user_data = db.get_user_data(target_user_id)
                recipient_name = target_user_data.get("first_name", "User")
                
                await message.reply_text(
                    f"✅ Transfer Successful!\n\n"
                    f"Transferred {points_to_transfer} points to {recipient_name} (`{target_user_id}`)",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
                
                # Notify target user
                try:
                    sender_name = update.effective_user.first_name
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"💰 You received {points_to_transfer} points from {sender_name} (`{user_id}`)!",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify target user {target_user_id}: {e}")
                
                # Clear transfer mode on success
                context.user_data.pop("transfer_mode", None)
            else:
                await message.reply_text(
                    f"❌ Transfer failed: {msg_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                    ])
                )
            
        except Exception as e:
            logger.error(f"Error in transfer mode: {e}")
            await message.reply_text(
                "❌ An error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Error in transfer mode: {e}")
            await message.reply_text(
                "❌ An error occurred during transfer.",
                reply_markup=InlineKeyboardMarkup([
                    [utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]
                ])
            )
        
        # Clear transfer mode
        context.user_data.pop("transfer_mode", None)
        return
        
    # Fallback: If user sends a code-like message directly, try to redeem as gift code
        # Sanitize code candidate (allow alphanumeric and hyphens)
        candidate = raw_text.strip().upper()
        if 6 <= len(candidate) <= 24:
            gift = db.get_gift_code_by_code(candidate)
            if gift:
                # Ensure user exists
                try:
                    uname = update.effective_user.username if update.effective_user else ""
                    fname = update.effective_user.first_name if update.effective_user else "User"
                    db.create_or_update_user(user_id=user_id, username=uname or "", first_name=fname or "User")
                except Exception:
                    pass
                now = int(time.time())
                # Cooldown
                try:
                    if not db.can_claim_gift(user_id, cooldown_seconds=300):
                        remaining = 300 - (now - (db.get_user_data(user_id) or {}).get('last_gift_claim', 0))
                        if remaining < 0:
                            remaining = 0
                        minutes = remaining // 60
                        seconds = remaining % 60
                        await message.reply_text(
                            f"⏳ Please wait {minutes}m {seconds}s before claiming another gift code.",
                            reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]])
                        )
                        return
                except Exception:
                    pass
                # Check expiry (handle missing expiry_at via created_at + days)
                expiry_val = gift.get("expiry_at")
                if expiry_val is None and "created_at" in gift and "days" in gift:
                    expiry_val = int(gift["created_at"]) + (int(gift["days"]) * 86400)
                
                # Support both "users_used" and "redeemed_by"
                redeemed_list = gift.get("redeemed_by") or gift.get("users_used") or []

                if not gift.get("enabled", True):
                    await message.reply_text("❌ This gift code is currently disabled.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
                    return
                if expiry_val and now > int(expiry_val):
                    await message.reply_text("❌ This gift code has expired.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
                    return
                if user_id in redeemed_list:
                    await message.reply_text("❌ You have already used this gift code.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
                    return
                if int(gift.get("usage_limit", 1)) <= int(gift.get("usage_count", 0)):
                    await message.reply_text("❌ This gift code has reached its usage limit.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
                    return
                success, _ = db.update_user_points(user_id, int(gift.get("points", 0)))
                if success and db.use_gift_code(candidate, user_id):
                    try:
                        db.update_gift_claim(user_id)
                    except Exception:
                        pass
                    await message.reply_text(
                        f"🎉 Congratulations! You have successfully redeemed the gift code and received {gift.get('points', 0)} points.",
                        reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]])
                    )
                else:
                    await message.reply_text("❌ Failed to redeem the gift code. Please try again later.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Back to Menu", callback_data="main_menu")]]))
                return
    
    # Handle pending OTT order screenshot flow
    if context.user_data.get("pending_order_product_id"):
        pid = context.user_data.get("pending_order_product_id")
        if message.photo:
            file_id = message.photo[-1].file_id
            caption = message.caption or ""
            product = db.get_product_by_id(pid)
            if not product:
                await message.reply_text("❌ Product unavailable. Please start again.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Menu", callback_data="main_menu")]]))
                context.user_data.pop("pending_order_product_id", None)
                return
            order_id = db.create_order(user_id, product, file_id, user_note=caption or "")
            context.user_data.pop("pending_order_product_id", None)
            if order_id:
                await message.reply_text(
                    f"✅ Your order has been submitted for review.\n\nOrder ID: #{order_id}\nProduct: {product.get('name')}\nPrice: ₹{product.get('price')}\n\nWe will contact you shortly.",
                    reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Menu", callback_data="main_menu")]])
                )
                # Notify admins with the screenshot
                try:
                    from config import ADMIN_IDS
                    for admin_id in ADMIN_IDS:
                        try:
                            await context.bot.send_photo(
                                chat_id=admin_id,
                                photo=file_id,
                                caption=f"🛒 New Order #{order_id}\nUser: {user_id}\nProduct: {product.get('name')}\nPrice: ₹{product.get('price')}\nNote: {caption}"
                            )
                        except Exception as e:
                            logger.error(f"Notify admin photo failed: {e}")
                except Exception:
                    pass
            else:
                await message.reply_text("❌ Failed to create order. Please try again later.", reply_markup=InlineKeyboardMarkup([[utils.ColoredInlineButton("🔙 Menu", callback_data="main_menu")]]))
            return
        else:
            await message.reply_text("Please send a payment screenshot (photo) to submit your order.")
            return

    # Payment screenshot handling removed (shopping disabled)
    
    # For other text messages, just ignore them
    return



async def error_handler(update: object, context: CallbackContext) -> None:
    """Handle errors gracefully without log spam."""
    err = context.error
    err_str = str(err) if err else ""
    
    # 1. Gracefully ignore common non-critical client/network conditions
    if isinstance(err, (telegram.error.Forbidden, telegram.error.NetworkError)) or "blocked by the user" in err_str or "user is deactivated" in err_str:
        logger.debug(f"User interaction notice (blocked/network): {err}")
        return
        
    if isinstance(err, telegram.error.RetryAfter) or "Flood control" in err_str:
        logger.warning(f"Telegram rate limit notice: {err}")
        return
        
    if isinstance(err, telegram.error.BadRequest) and any(
        x in err_str for x in [
            "Message is not modified",
            "Chat not found",
            "Message to edit not found",
            "Message to be replied not found",
            "Query is too old",
            "have no rights to send a message",
            "message to delete not found"
        ]
    ):
        logger.debug(f"Non-critical Telegram BadRequest ignored: {err}")
        return

    # 2. Log actual unhandled exceptions
    logger.error(f"Exception while handling an update: {err}", exc_info=True)

    # 3. Try to send error message to user
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred while processing your request. Please try again later."
            )
    except Exception:
        pass
    
    # 4. Notify admins about critical exceptions only
    try:
        from config import ADMIN_IDS
        error_text = (
            f"🚨 *Bot Error*\n\n"
            f"Error: `{html.escape(str(err))}`\n"
        )
        if update:
            error_text += f"Update: `{html.escape(str(update)[:100])}`...\n"
             
        error_text += f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=error_text,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to notify admins about error: {e}")
