import logging
import time
import asyncio
from datetime import datetime, timedelta
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, Forbidden, RetryAfter

import database as db
import utils
import notifications

logger = logging.getLogger(__name__)

async def check_channel_membership(bot):
    """Check if active users are still in required channels (batched & lightweight)."""
    try:
        # Clear membership cache periodically
        utils.clear_membership_cache()
        
        # Get all channels
        channels = db.get_channels()
        if not channels:
            return
        
        telegram_channels = [ch for ch in channels if ch.get("type", "telegram") != "whatsapp"]
        if not telegram_channels:
            return
        
        # Get user data
        all_user_data = db.get_user_data()
        users = (all_user_data or {}).get("users", {})
        if not users:
            return

        now = int(time.time())
        # Only check active users (e.g. have points > 0 or joined/active in last 30 days)
        # Skip banned, blocked, deactivated or unreachable users
        candidates = []
        for uid_str, udata in users.items():
            if udata.get("banned") or udata.get("bot_blocked") or udata.get("deactivated") or udata.get("unreachable"):
                continue
            # Active candidate if points > 0 or active in last 30 days
            points = udata.get("points", 0)
            last_active = udata.get("last_active", udata.get("joined_at", 0))
            if points > 0 or (now - last_active) < (30 * 86400):
                candidates.append((uid_str, udata))

        # Check a batch of up to 100 users per run to prevent scheduler overlap
        batch = candidates[:100]
        checked_count = 0
        status_changed_count = 0

        for user_id_str, user_data in batch:
            try:
                user_id = int(user_id_str)
                all_joined = True
                
                for channel in telegram_channels:
                    try:
                        in_ch = await utils.check_user_in_channel(bot, user_id, channel["id"])
                        if not in_ch:
                            all_joined = False
                    except (Forbidden, BadRequest):
                        all_joined = False
                        break

                # Update user's channel status in database if changed
                prev_status = user_data.get("channel_status")
                if prev_status != all_joined:
                    db.update_user_channel_status(user_id, all_joined)
                    status_changed_count += 1
                    try:
                        db.record_channel_event(user_id, "joined" if all_joined else "left")
                    except Exception:
                        pass
                
                checked_count += 1
                # Small throttle to protect Telegram API
                await asyncio.sleep(0.05)
            except Exception as e_user:
                logger.debug(f"Membership check skipped for {user_id_str}: {e_user}")

        logger.info(f"✅ Channel membership check completed: {checked_count} active users checked, {status_changed_count} status changes")

    except Exception as e:
        logger.error(f"Error in check_channel_membership: {e}")

async def cleanup_expired_codes():
    """Clean up expired gift codes."""
    try:
        current_time = int(time.time())
        gift_codes_data = db.get_gift_codes()
        codes_list = gift_codes_data.get("codes", []) if isinstance(gift_codes_data, dict) else []
        
        deleted = 0
        for c in codes_list:
            if c.get("expires_at", 0) and c.get("expires_at", 0) <= current_time:
                code_str = c.get("code")
                if code_str:
                    db.delete_gift_code(code_str)
                    deleted += 1
        if deleted > 0:
            logger.info(f"Deleted {deleted} expired gift codes")
                    
    except Exception as e:
        logger.error(f"Error cleaning up expired codes: {e}")

async def send_daily_reminders(bot):
    """Send daily reward reminders to reachable active users with automatic block detection."""
    try:
        all_user_data = db.get_user_data()
        users = (all_user_data or {}).get("users", {})
        if not users:
            return
            
        current_time = int(time.time())
        sent_count = 0
        blocked_count = 0
        skipped_count = 0
        db_dirty = False
        
        for user_id_str, user_data in users.items():
            try:
                user_id = int(user_id_str)
                
                # Skip banned, blocked, or unreachable users
                if user_data.get("banned") or user_data.get("bot_blocked") or user_data.get("deactivated") or user_data.get("unreachable"):
                    skipped_count += 1
                    continue
                
                # Check if user can claim daily reward (strict 24h)
                last_daily = user_data.get("last_daily", 0)
                if (current_time - last_daily) >= 86400:
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text="🎁 *Daily Reward Ready!*\n\nDon't forget to claim your free daily points. Use /daily or tap the button below!",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🎁 Claim Daily Reward", callback_data="claim_daily")]
                            ])
                        )
                        sent_count += 1
                        await asyncio.sleep(0.05) # Polite throttle (20 msg/sec max)

                    except RetryAfter as e_retry:
                        # Obey Telegram flood limit
                        await asyncio.sleep(e_retry.retry_after + 1)
                        try:
                            await bot.send_message(
                                chat_id=user_id,
                                text="🎁 Don't forget to claim your daily reward! Use /daily to get free points."
                            )
                            sent_count += 1
                        except Exception:
                            pass

                    except Forbidden as e_forbid:
                        # User blocked bot or account deactivated - record permanently
                        err_str = str(e_forbid).lower()
                        if "deactivated" in err_str:
                            user_data["deactivated"] = True
                        else:
                            user_data["bot_blocked"] = True
                        user_data["unreachable"] = True
                        db_dirty = True
                        blocked_count += 1
                        logger.debug(f"Marked user {user_id} as unreachable: {e_forbid}")

                    except BadRequest as e_bad:
                        err_str = str(e_bad).lower()
                        if "chat not found" in err_str or "can't initiate" in err_str:
                            user_data["unreachable"] = True
                            db_dirty = True
                            blocked_count += 1
                            logger.debug(f"User {user_id} cannot be messaged: {e_bad}")
                        else:
                            logger.debug(f"BadRequest for user {user_id}: {e_bad}")

                    except Exception as e_msg:
                        logger.debug(f"Failed to message user {user_id}: {e_msg}")

            except (ValueError, TypeError):
                continue
                
        # Persist updated unreachable statuses atomically
        if db_dirty:
            all_user_data["users"] = users
            db.save_user_data(all_user_data)
            logger.info(f"💾 Updated {blocked_count} newly identified unreachable users in database")

        logger.info(f"📢 Daily reminders completed: {sent_count} sent, {blocked_count} newly marked unreachable, {skipped_count} skipped")

    except Exception as e:
        logger.error(f"Error sending daily reminders: {e}")

async def cleanup_old_notifications():
    """Clean up notifications older than 30 days."""
    try:
        deleted_count = notifications.cleanup_old_notifications(days_old=30)
        if deleted_count:
            logger.info(f"Deleted {deleted_count} old notifications")
    except Exception as e:
        logger.error(f"Error cleaning up old notifications: {e}")
