import requests
import json
import logging
import database as db
from config import TOKEN, CHANNEL_ID, BOT_USERNAME

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    """Send a message using Requests (Synchronous). Fallback to plain text if Markdown parsing fails."""
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        response = requests.post(url, json=payload, timeout=10)
        res_data = response.json() if response.text else {}
        
        # If Telegram returned an entity parsing error (e.g. unescaped characters in reason), retry with plain text
        if not res_data.get("ok") and parse_mode:
            payload.pop("parse_mode", None)
            response = requests.post(url, json=payload, timeout=10)
            res_data = response.json() if response.text else {}
            
        return res_data
    except Exception as e:
        logger.error(f"Failed to send sync message to {chat_id}: {e}")
        return None

