"""
Animation and Image Support Module for Telegram Bot
Handles sending animations, images, and visual elements

Note: Loading messages are TEXT-ONLY (no GIFs or animations) for better performance
and they are automatically cleaned up after task completion.
"""

import logging
import time
import asyncio
import threading
from typing import Optional, Union, Callable, Any
from functools import wraps

from telegram import Update, InputMediaPhoto, InputMediaAnimation
from telegram.ext import CallbackContext
from telegram.error import TelegramError

from config import (
    BOT_ANIMATIONS, CATEGORY_IMAGES, PAYMENT_METHOD_IMAGES,
    STATUS_ANIMATIONS, ACTION_EMOJIS, ANIMATIONS_ENABLED, IMAGES_ENABLED
)

logger = logging.getLogger(__name__)

# Store active loading messages for cleanup
_active_loading_messages = {}

class LoadingContext:
    """Context manager for loading text messages (no GIFs/animations)."""
    
    def __init__(self, update: Update, context: CallbackContext, message: str = "⏳ Processing your request...", 
                 animation_type: str = "loading", auto_delete: bool = True):
        self.update = update
        self.context = context
        self.message = message
        self.animation_type = animation_type
        self.auto_delete = auto_delete
        self.loading_message = None
        self.chat_id = None
        
    async def __aenter__(self):
        """Start the loading message."""
        if self.update.effective_chat:
            self.chat_id = self.update.effective_chat.id
            try:
                # Send text-only loading message (no GIFs or animations)
                self.loading_message = await AnimationManager.send_loading_animation(
                    self.update, self.context, self.message
                )
                
                # Store for potential cleanup
                if self.loading_message and self.chat_id:
                    _active_loading_messages[self.chat_id] = self.loading_message
                    
            except Exception as e:
                err_str = str(e)
                if any(x in err_str for x in ["blocked", "Flood control", "Chat not found", "deactivated"]):
                    logger.debug(f"Notice sending loading message: {e}")
                else:
                    logger.warning(f"Failed to send loading message: {e}")
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up loading message - ALWAYS delete it after task completion."""
        if self.loading_message and self.chat_id:
            try:
                # Small delay to let users see the loading message briefly
                await asyncio.sleep(0.3)
                
                # Always try to delete the loading message
                if hasattr(self.loading_message, 'delete'):
                    await self.loading_message.delete()
                elif hasattr(self.loading_message, 'message_id'):
                    await self.context.bot.delete_message(
                        chat_id=self.chat_id, 
                        message_id=self.loading_message.message_id
                    )
                
                # Remove from active messages
                _active_loading_messages.pop(self.chat_id, None)
                logger.debug(f"Successfully deleted loading message for chat {self.chat_id}")
                
            except Exception as e:
                logger.debug(f"Could not delete loading message for chat {self.chat_id}: {e}")
                # Try alternative cleanup method
                try:
                    await self.context.bot.delete_message(
                        chat_id=self.chat_id,
                        message_id=self.loading_message.message_id
                    )
                    _active_loading_messages.pop(self.chat_id, None)
                    logger.debug(f"Alternative cleanup successful for chat {self.chat_id}")
                except Exception as e2:
                    logger.debug(f"Alternative cleanup also failed for chat {self.chat_id}: {e2}")
                    # Force remove from active messages even if deletion failed
                    _active_loading_messages.pop(self.chat_id, None)

def with_loading_animation(message: str = None, animation_type: str = "loading", auto_delete: bool = True):
    """
    Decorator to automatically show loading text message before executing a handler function.
    No GIFs or animations are shown - only text messages for better performance.
    
    Args:
        message: Custom loading message (optional)
        animation_type: Type of loading animation (optional, not used for text-only loading)
        auto_delete: Whether to auto-delete loading message after function execution
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs) -> Any:
            # Determine the appropriate loading message
            loading_message = message
            if not loading_message:
                # Generate context-aware loading message based on function name
                func_name = func.__name__.lower()
                if 'daily' in func_name:
                    loading_message = "⏳ Checking your daily reward..."
                elif 'profile' in func_name:
                    loading_message = "⏳ Loading your profile..."
                elif 'refer' in func_name:
                    loading_message = "⏳ Generating referral information..."
                elif 'redeem' in func_name:
                    loading_message = "⏳ Loading available accounts..."
                elif 'giveaway' in func_name:
                    loading_message = "⏳ Loading giveaway information..."
                elif 'stats' in func_name:
                    loading_message = "⏳ Calculating statistics..."
                elif 'export' in func_name:
                    loading_message = "⏳ Preparing export file..."
                elif 'broadcast' in func_name:
                    loading_message = "⏳ Sending messages to users..."
                elif 'leaderboard' in func_name or 'top' in func_name:
                    loading_message = "⏳ Loading leaderboard data..."
                elif 'payment' in func_name or 'order' in func_name:
                    loading_message = "⏳ Processing payment information..."
                elif 'verify' in func_name:
                    loading_message = "⏳ Verifying order..."
                else:
                    loading_message = "⏳ Processing your request..."
            
            # Use loading context manager (text-only, no GIFs)
            async with LoadingContext(update, context, loading_message, animation_type, auto_delete):
                # Execute the original function
                return await func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator

def with_callback_loading_animation(message: str = None, animation_type: str = "loading"):
    """
    Decorator specifically for callback query handlers that need loading text messages (no GIFs).
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs) -> Any:
            query = update.callback_query
            
            # Answer the callback query immediately to stop the loading indicator
            if query:
                try:
                    await query.answer()
                except telegram.error.BadRequest as e:
                    if "Query is too old" in str(e):
                        logger.warning(f"Ignoring 'Query is too old' in callback loading animation")
                    else:
                        logger.error(f"BadRequest error answering callback in loading animation: {e}")
                except Exception as e:
                    logger.error(f"Error answering callback in loading animation: {e}")
            
            # Determine loading message based on callback data
            loading_message = message
            if not loading_message and query:
                callback_data = query.data.lower()
                if 'daily' in callback_data:
                    loading_message = "⏳ Processing daily reward..."
                elif 'profile' in callback_data or 'refresh_profile' in callback_data:
                    loading_message = "⏳ Refreshing profile data..."
                elif 'refer' in callback_data:
                    loading_message = "⏳ Loading referral stats..."
                elif 'redeem' in callback_data:
                    loading_message = "⏳ Processing redemption..."
                elif 'leaderboard' in callback_data or 'top' in callback_data:
                    loading_message = "⏳ Updating leaderboard..."
                elif 'giveaway' in callback_data:
                    loading_message = "⏳ Loading giveaway details..."
                else:
                    loading_message = "⏳ Processing your selection..."
            
            # Show text-only loading message for callbacks
            loading_msg = None
            try:
                if update.effective_chat:
                    loading_msg = await AnimationManager.send_loading_animation(update, context, loading_message)
                    await asyncio.sleep(0.3)  # Brief delay for visual feedback
            except Exception as e:
                logger.debug(f"Could not send loading message for callback: {e}")
            
            # Execute the original function
            result = await func(update, context, *args, **kwargs)
            
            # Clean up loading message after function execution
            if loading_msg and update.effective_chat:
                try:
                    await asyncio.sleep(0.2)  # Brief delay before cleanup
                    if hasattr(loading_msg, 'delete'):
                        await loading_msg.delete()
                    else:
                        await context.bot.delete_message(
                            chat_id=update.effective_chat.id,
                            message_id=loading_msg.message_id
                        )
                except Exception as e:
                    logger.debug(f"Could not clean up loading message for callback: {e}")
            
            return result
        
        return wrapper
    return decorator

class AnimationManager:
    """Manager for sending animations and images."""
    
    @staticmethod
    async def send_animation(context: CallbackContext, chat_id: int, animation_type: str, 
                      caption: str = "", parse_mode: str = "Markdown") -> bool:
        """Send an animation based on type."""
        if not ANIMATIONS_ENABLED:
            return False
            
        try:
            animation_url = BOT_ANIMATIONS.get(animation_type)
            if not animation_url:
                logger.warning(f"Animation type '{animation_type}' not found")
                return False
                
            await context.bot.send_animation(
                chat_id=chat_id,
                animation=animation_url,
                caption=caption,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send animation {animation_type}: {e}")
            return False
    
    @staticmethod
    async def send_image(context: CallbackContext, chat_id: int, image_url: str,
                  caption: str = "", parse_mode: str = "Markdown") -> bool:
        """Send an image."""
        if not IMAGES_ENABLED:
            return False
            
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=caption,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send image: {e}")
            return False
    
    @staticmethod
    async def send_category_image(context: CallbackContext, chat_id: int, category: str,
                           caption: str = "") -> bool:
        """Send a category-specific image."""
        image_url = CATEGORY_IMAGES.get(category)
        if not image_url:
            return False
        return await AnimationManager.send_image(context, chat_id, image_url, caption)
    
    @staticmethod
    async def send_payment_method_image(context: CallbackContext, chat_id: int, method: str,
                                 caption: str = "") -> bool:
        """Send a payment method image."""
        image_url = PAYMENT_METHOD_IMAGES.get(method)
        if not image_url:
            return False
        return await AnimationManager.send_image(context, chat_id, image_url, caption)
    
    @staticmethod
    def get_status_emoji(status: str) -> str:
        """Get emoji for a status."""
        return STATUS_ANIMATIONS.get(status, "❓")
    
    @staticmethod
    def get_action_emoji(action: str) -> str:
        """Get emoji for an action."""
        return ACTION_EMOJIS.get(action, "⚡")
    
    @staticmethod
    async def send_welcome_animation(update: Update, context: CallbackContext) -> bool:
        """Send welcome animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "welcome", 
            "🎉 Welcome to our bot!"
        )
    
    @staticmethod
    async def send_success_animation(update: Update, context: CallbackContext, message: str) -> bool:
        """Send success animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "success", message
        )
    
    @staticmethod
    async def send_loading_animation(update: Update, context: CallbackContext, message: str = ""):
        """Send a text-only loading message (no GIFs or animations)."""
        if not update.effective_chat:
            return None
            
        try:
            # Send simple text message for loading (no GIFs or animations)
            loading_text = message if message else "⏳ Processing your request..."
            
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=loading_text,
                parse_mode="Markdown"
            )
            
            # Store for cleanup
            if update.effective_chat.id:
                _active_loading_messages[update.effective_chat.id] = sent_message
            
            return sent_message
            
        except Exception as e:
            err_str = str(e)
            if any(x in err_str for x in ["blocked", "Flood control", "Chat not found", "deactivated"]):
                logger.debug(f"Notice sending loading animation: {e}")
            else:
                logger.warning(f"Failed to send loading animation: {e}")
            return None
    
    @staticmethod
    async def send_error_animation(update: Update, context: CallbackContext, message: str) -> bool:
        """Send error animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "error", message
        )
    
    @staticmethod
    async def send_payment_animation(update: Update, context: CallbackContext, message: str) -> bool:
        """Send payment animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "payment", message
        )
    
    @staticmethod
    async def send_gift_animation(update: Update, context: CallbackContext, message: str) -> bool:
        """Send gift animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "gift", message
        )
    
    @staticmethod
    async def send_celebration_animation(update: Update, context: CallbackContext, message: str) -> bool:
        """Send celebration animation."""
        if not update.effective_chat:
            return False
        return await AnimationManager.send_animation(
            context, update.effective_chat.id, "celebration", message
        )

def create_animated_text(text: str, animation_type: str = "sparkle") -> str:
    """Create animated text using emojis."""
    animations = {
        "sparkle": "✨",
        "star": "⭐",
        "fire": "🔥",
        "heart": "💖",
        "money": "💰",
        "gift": "🎁",
        "celebration": "🎉",
        "success": "🎊",
        "loading": "⏳",
        "warning": "⚠️",
        "error": "❌",
        "info": "ℹ️"
    }
    
    emoji = animations.get(animation_type, "✨")
    return f"{emoji} {text} {emoji}"

def format_with_emojis(text: str, **kwargs) -> str:
    """Format text with action emojis."""
    for action, emoji in ACTION_EMOJIS.items():
        if action in kwargs and kwargs[action]:
            text = text.replace(f"{{{action}}}", emoji)
    
    return text

def create_progress_bar(percentage: int, length: int = 10) -> str:
    """Create a visual progress bar."""
    filled = int(length * percentage / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percentage}%"

def animate_countdown(seconds: int) -> str:
    """Create countdown animation text."""
    if seconds > 3600:  # More than 1 hour
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"⏰ {hours}h {minutes}m remaining"
    elif seconds > 60:  # More than 1 minute
        minutes = seconds // 60
        secs = seconds % 60
        return f"⏰ {minutes}m {secs}s remaining"
    else:
        return f"⏰ {seconds}s remaining"

def get_loading_dots(step: int) -> str:
    """Get animated loading dots."""
    dots = ["", ".", "..", "..."]
    return f"Loading{dots[step % 4]}"

# Animation presets for common scenarios
ANIMATION_PRESETS = {
    "order_completed": {
        "type": "celebration",
        "text": "🎉 *Order Completed Successfully!* 🎉\n\nYour accounts have been delivered!"
    },
    "payment_received": {
        "type": "money", 
        "text": "💰 *Payment Received!* 💰\n\nProcessing your order..."
    },
    "giveaway_won": {
        "type": "gift",
        "text": "🎁 *Congratulations!* 🎁\n\nYou won the giveaway!"
    },
    "daily_reward": {
        "type": "gift",
        "text": "⭐ *Daily Reward Claimed!* ⭐\n\nCome back tomorrow for more!"
    },
    "points_added": {
        "type": "success",
        "text": "✨ *Points Added!* ✨\n\nKeep earning and redeeming!"
    },
    "account_redeemed": {
        "type": "success", 
        "text": "🎊 *Account Redeemed!* 🎊\n\nEnjoy your premium access!"
    }
}

async def send_preset_animation(update: Update, context: CallbackContext, preset: str, 
                         custom_text: str = None) -> bool:
    """Send a preset animation scenario."""
    if preset not in ANIMATION_PRESETS:
        logger.warning(f"Animation preset '{preset}' not found")
        return False
    
    preset_data = ANIMATION_PRESETS[preset]
    text = custom_text or preset_data["text"]
    animation_type = preset_data["type"]
    
    return await AnimationManager.send_animation(
        context, update.effective_chat.id, animation_type, text
    )

def cleanup_loading_messages():
    """Clean up all active loading text messages."""
    global _active_loading_messages
    for chat_id, message in _active_loading_messages.items():
        try:
            if hasattr(message, 'delete'):
                message.delete()
        except Exception as e:
            logger.debug(f"Could not clean up loading message for chat {chat_id}: {e}")
    _active_loading_messages.clear()

def get_task_loading_message(task_name: str) -> str:
    """Get appropriate loading message for specific tasks."""
    messages = [
        "⏳ Processing your request...",
        "🪐 Aligning the planets...",
        "🐹 Feeding the hamsters...",
        "📡 Contacting the mothership...",
        "🧹 Sweeping the digital dust...",
        "🔋 Charging flux capacitor...",
        "🏃‍♂️ Running really fast...",
        "🧠 Thinking hard...",
        "🔍 Looking for clues...",
        "🎲 Rolling the dice...",
    ]
    
    task_messages = {
        'account_redemption': ['⏳ Processing account redemption...', '🎁 Wrapping your gift...', '🎟️ Checking tickets...'],
        'payment_verification': ['⏳ Verifying payment...', '💸 Counting coins...', '🏦 Calling the bank...'],
        'giveaway_join': ['⏳ Joining giveaway...', '🤞 Crossing fingers...', '🎫 Printing ticket...'],
        'channel_check': ['⏳ Checking memberships...', '📋 Checking the list...', '🕵️‍♂️ Verifying credentials...'],
        'daily_claim': ['⏳ Processing daily reward...', '✨ Polishing your reward...', '🌟 Gathering stardust...'],
    }
    
    import random
    if task_name in task_messages:
        return random.choice(task_messages[task_name])
    
    return random.choice(messages)
 