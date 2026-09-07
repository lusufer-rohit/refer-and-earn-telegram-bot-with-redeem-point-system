import json
import os
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
import time
import secrets
import threading
from config import (
    USER_DATA_FILE, 
    OTT_ACCOUNTS_FILE, 
    CATEGORIES_FILE, 
    CHANNELS_FILE,
    CHAT_MESSAGES_FILE,
    CHANNEL_STATS_FILE,
    CODES_FILE,
    USER_ACTIVITY_FILE,
    PENDING_REFERRALS_FILE,
)

logger = logging.getLogger(__name__)

# Re-entrant thread lock for all database operations
data_lock = threading.RLock()

def _save_json_atomic(filepath: str, data: Any, indent: int = 2, make_backup: bool = True) -> bool:
    """Save JSON data to file atomically with safe temp write, flush, fsync, dual backup rotation, and os.replace."""
    try:
        # Ensure parent directory exists
        parent_dir = os.path.dirname(os.path.abspath(filepath))
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        tmp_file = f"{filepath}.tmp"
        bak_file = f"{filepath}.bak"
        
        # Write to temporary file first
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
            
        # Update backup if primary exists and make_backup is True
        if make_backup and os.path.exists(filepath):
            try:
                if os.path.exists(bak_file):
                    bak2_file = f"{filepath}.bak2"
                    if os.path.exists(bak2_file):
                        try:
                            os.remove(bak2_file)
                        except Exception:
                            pass
                    try:
                        os.rename(bak_file, bak2_file)
                    except Exception:
                        pass
                os.replace(filepath, bak_file)
            except Exception as e_bak:
                logger.debug(f"Notice updating backup for {filepath}: {e_bak}")
                
        # Atomic replace
        os.replace(tmp_file, filepath)
        return True
    except Exception as e:
        logger.error(f"Error saving JSON atomically to {filepath}: {e}")
        tmp_file = f"{filepath}.tmp"
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        return False

def _load_json_safe(filepath: str, default: Any = None) -> Any:
    """Load JSON data from file with automatic recovery from backup (.bak/.bak2) on corruption or read failure."""
    if default is None:
        default = {}
    data = None
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        except Exception as e:
            logger.error(f"Error reading primary {filepath}: {e}. Attempting backup recovery...")
            
    if data is None:
        for bak_suffix in [".bak", ".bak2"]:
            bak_file = f"{filepath}{bak_suffix}"
            if os.path.exists(bak_file):
                try:
                    with open(bak_file, 'r', encoding='utf-8') as f_bak:
                        content_bak = f_bak.read().strip()
                        if content_bak:
                            data = json.loads(content_bak)
                            logger.info(f"Successfully recovered {filepath} from {bak_file}")
                            # Auto-restore primary file
                            _save_json_atomic(filepath, data, make_backup=False)
                            break
                except Exception as e_bak:
                    logger.critical(f"Error reading backup {bak_file}: {e_bak}")
                    
    if data is None:
        return default
    return data

# Initialize database files if not exist
def init_database():
    """Initialize all database files if they don't exist."""
    files = {
        USER_DATA_FILE: {"users": {}, "referrals": {}},
        OTT_ACCOUNTS_FILE: {"accounts": []},
        CATEGORIES_FILE: {"categories": {}},
        CHANNELS_FILE: {"channels": []},
        CHAT_MESSAGES_FILE: {"messages": []},
        CHANNEL_STATS_FILE: {"events": []},
        USER_ACTIVITY_FILE: {"activities": []},
    }
    
    for file_name, default_data in files.items():
        if not os.path.exists(file_name):
            _save_json_atomic(file_name, default_data, indent=2, make_backup=False)
            logger.info(f"Created database file: {file_name}")
            
    from config import BROADCAST_HISTORY_FILE
    if not os.path.exists(BROADCAST_HISTORY_FILE):
        _save_json_atomic(BROADCAST_HISTORY_FILE, {"history": []}, indent=2, make_backup=False)

# User data operations
def get_user_data(user_id: int = None) -> Dict:
    """Get all user data or specific user data with automatic fallback backup support."""
    with data_lock:
        data = _load_json_safe(USER_DATA_FILE, {"users": {}, "referrals": {}})

    if not isinstance(data, dict) or "users" not in data:
        if user_id is not None:
            return None
        return {"users": {}, "referrals": {}}

    if user_id is not None:
        user_id_str = str(user_id)
        return data["users"].get(user_id_str)
    return data

def save_user_data(data: Dict) -> bool:
    """Save user data to file atomically with automatic dual backups and wipe protection."""
    if not isinstance(data, dict) or "users" not in data:
        logger.error("save_user_data called with invalid data structure, skipping save.")
        return False
        
    with data_lock:
        # Wipe protection: Don't allow saving empty/near-empty data if existing DB is populated
        if os.path.exists(USER_DATA_FILE) and len(data.get("users", {})) < 5:
            try:
                existing = _load_json_safe(USER_DATA_FILE, {})
                if len(existing.get("users", {})) > 50:
                    logger.critical(f"BLOCKED potential data loss! Attempted to save {len(data.get('users', {}))} users over {len(existing.get('users', {}))} existing users.")
                    return False
            except Exception:
                pass

        return _save_json_atomic(USER_DATA_FILE, data, indent=2, make_backup=True)

def get_user_id_by_username(username: str) -> Optional[int]:
    """Get user ID by username (case-insensitive, handles @ prefix)."""
    if not username:
        return None
        
    target_username = username.strip().lower()
    if target_username.startswith('@'):
        target_username = target_username[1:]
        
    data = get_user_data()
    users = data.get("users", {})
    
    for user_id_str, user_data in users.items():
        stored_username = user_data.get("username", "")
        if stored_username and stored_username.lower() == target_username:
            try:
                return int(user_id_str)
            except ValueError:
                continue
                
    return None

# --- Channel membership stats ---
def _load_channel_stats() -> Dict:
    with data_lock:
        return _load_json_safe(CHANNEL_STATS_FILE, {"events": []})

def _save_channel_stats(data: Dict) -> bool:
    with data_lock:
        return _save_json_atomic(CHANNEL_STATS_FILE, data, indent=2)

def record_channel_event(user_id: int, action: str, timestamp: Optional[int] = None) -> bool:
    """Record a join/leave event for channel membership tracking."""
    if action not in ("joined", "left"):
        return False
    data = _load_channel_stats()
    events = data.get("events", [])
    events.append({
        "user_id": int(user_id),
        "action": action,
        "timestamp": int(timestamp or time.time())
    })
    # Keep only recent events to avoid unbounded growth
    if len(events) > 2000:
        events = events[-2000:]
    data["events"] = events
    return _save_channel_stats(data)

def get_channel_events(limit: int = 200) -> List[Dict]:
    """Return recent channel membership events (newest first)."""
    data = _load_channel_stats()
    events = data.get("events", [])
    events = sorted(events, key=lambda e: e.get("timestamp", 0), reverse=True)
    return events[:limit]

def get_channel_daily_stats(days: int = 7) -> List[Dict]:
    """Aggregate daily join/leave counts for the last N days."""
    data = _load_channel_stats()
    events = data.get("events", [])
    now = int(time.time())
    cutoff = now - days * 86400
    daily: Dict[str, Dict[str, int]] = {}
    for e in events:
        ts = int(e.get("timestamp", 0) or 0)
        if ts < cutoff:
            continue
        day = time.strftime('%Y-%m-%d', time.localtime(ts))
        bucket = daily.setdefault(day, {"joined": 0, "left": 0})
        action = e.get("action")
        if action == "joined":
            bucket["joined"] += 1
        elif action == "left":
            bucket["left"] += 1
    # Return sorted by date descending
    return [
        {"date": d, "joined": counts.get("joined", 0), "left": counts.get("left", 0)}
        for d, counts in sorted(daily.items(), key=lambda kv: kv[0], reverse=True)
    ]

def save_pending_referral(user_id: int, referrer_id: int) -> None:
    """Save a pending referral persistently to disk."""
    if not user_id or not referrer_id or int(user_id) == int(referrer_id):
        return
    with data_lock:
        data = _load_json_safe(PENDING_REFERRALS_FILE, {})
        data[str(user_id)] = int(referrer_id)
        _save_json_atomic(PENDING_REFERRALS_FILE, data, indent=2)

def get_pending_referral(user_id: int) -> Optional[int]:
    """Get pending referrer for a user."""
    if not user_id:
        return None
    with data_lock:
        data = _load_json_safe(PENDING_REFERRALS_FILE, {})
        val = data.get(str(user_id))
        return int(val) if val else None

def clear_pending_referral(user_id: int) -> None:
    """Clear pending referral for a user."""
    if not user_id:
        return
    with data_lock:
        data = _load_json_safe(PENDING_REFERRALS_FILE, {})
        if str(user_id) in data:
            del data[str(user_id)]
            _save_json_atomic(PENDING_REFERRALS_FILE, data, indent=2)

def create_or_update_user(user_id: int, username: str, first_name: str, 
                          referred_by: Optional[int] = None) -> Dict:
    """Create a new user or update existing user in the database, reliably awarding referrals."""
    user_id_str = str(user_id)
    current_time = int(time.time())
    
    with data_lock:
        data = get_user_data() or {"users": {}, "referrals": {}}
            
        if "users" not in data:
            data["users"] = {}
        if "referrals" not in data:
            data["referrals"] = {}

        # Check if this is a brand new user
        is_new_user = user_id_str not in data["users"]
        referral_awarded = False
        
        if is_new_user:
            # New user creation
            data["users"][user_id_str] = {
                "id": user_id,
                "username": username,
                "first_name": first_name,
                "points": 0,
                "joined_at": current_time,
                "last_active": current_time,
                "last_daily": 0,
                "redeemed_accounts": [],
                "banned": False,
                "bot_blocked": False,
                "deactivated": False,
                "unreachable": False,
                "referred_by": referred_by
            }
            
            # Process referral if provided
            if referred_by is not None and int(referred_by) != int(user_id):
                referred_by_str = str(referred_by)
                if referred_by_str not in data["referrals"]:
                    data["referrals"][referred_by_str] = []
                
                if user_id_str not in data["referrals"][referred_by_str]:
                    data["referrals"][referred_by_str].append(user_id_str)
                
                import config
                referral_points = config.get_referral_points()
                
                if referred_by_str in data["users"]:
                    data["users"][referred_by_str]["points"] += referral_points
                    referral_awarded = True
                    logger.info(f"Added {referral_points} referral points to user {referred_by} for new user {user_id}")
        else:
            # Update existing user profile & restore active status
            data["users"][user_id_str]["username"] = username
            data["users"][user_id_str]["first_name"] = first_name
            data["users"][user_id_str]["last_active"] = current_time
            data["users"][user_id_str]["bot_blocked"] = False
            data["users"][user_id_str]["deactivated"] = False
            data["users"][user_id_str]["unreachable"] = False

            # If existing user was never referred before, and has referred_by now:
            existing_ref = data["users"][user_id_str].get("referred_by")
            if existing_ref is None and referred_by is not None and int(referred_by) != int(user_id):
                referred_by_str = str(referred_by)
                # Ensure user is not already listed in any referral list
                already_in_referrals = any(user_id_str in r_list for r_list in data["referrals"].values())
                if not already_in_referrals:
                    data["users"][user_id_str]["referred_by"] = int(referred_by)
                    if referred_by_str not in data["referrals"]:
                        data["referrals"][referred_by_str] = []
                    if user_id_str not in data["referrals"][referred_by_str]:
                        data["referrals"][referred_by_str].append(user_id_str)
                    
                    import config
                    referral_points = config.get_referral_points()
                    if referred_by_str in data["users"]:
                        data["users"][referred_by_str]["points"] += referral_points
                        referral_awarded = True
                        logger.info(f"Attached missing referral: Added {referral_points} points to user {referred_by} for {user_id}")
        
        save_user_data(data)
        
        # Return user data with is_new and referral_awarded flags
        result = data["users"][user_id_str].copy()
        result["is_new"] = is_new_user or referral_awarded
        result["referral_awarded"] = referral_awarded
        
    return result

def attach_referral_if_missing(referred_user_id: int, referrer_user_id: int) -> bool:
    """Safely attach a missing referral to a user."""
    if not referred_user_id or not referrer_user_id or int(referred_user_id) == int(referrer_user_id):
        return False
    user_data = create_or_update_user(referred_user_id, "", "", referred_by=referrer_user_id)
    return user_data.get("referral_awarded", False)

def update_user_points(user_id: int, points_change: int) -> Tuple[bool, int]:
    """Update a user's points balance. Returns (success, new_balance)."""
    user_id_str = str(user_id)
    
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False, 0
        
        data["users"][user_id_str]["points"] += points_change
        # Ensure points don't go below zero
        if data["users"][user_id_str]["points"] < 0:
            data["users"][user_id_str]["points"] = 0
        
        new_balance = data["users"][user_id_str]["points"]
        save_user_data(data)
            
    record_user_activity(user_id, "Points Update", f"Points adjusted by {points_change}", f"{'+' if points_change > 0 else ''}{points_change}")
    return True, new_balance

def update_daily_claim(user_id: int) -> Tuple[bool, int]:
    """Mark user as claimed daily reward. Returns (success, new_balance)."""
    user_id_str = str(user_id)
    
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False, 0
        
        current_time = int(time.time())
        data["users"][user_id_str]["last_daily"] = current_time
        
        # Add points from config
        import config
        data["users"][user_id_str]["points"] += config.get_daily_points()
        
        new_balance = data["users"][user_id_str]["points"]
        save_user_data(data)
            
    record_user_activity(user_id, "Daily Bonus", "Claimed daily bonus reward", f"+{config.get_daily_points()}")
    return True, new_balance

def can_claim_daily(user_id: int) -> bool:
    """Check if user can claim daily reward."""
    user_data = get_user_data(user_id)
    if not user_data:
        return False
    
    last_daily = user_data.get("last_daily", 0)
    current_time = int(time.time())
    
    # Check if 24 hours (86400 seconds) have passed
    return (current_time - last_daily) >= 86400

def get_leaderboard(limit: int = 10) -> List[Dict]:
    """Get top users by referral count."""
    data = get_user_data()
    
    # Count referrals for each user
    referral_counts = {}
    for referrer_id, referred_users in data.get("referrals", {}).items():
        referral_counts[referrer_id] = len(referred_users)
    
    # Sort by referral count
    sorted_users = sorted(
        referral_counts.items(), 
        key=lambda x: x[1], 
        reverse=True
    )[:limit]
    
    # Build leaderboard with user details
    leaderboard = []
    for user_id_str, count in sorted_users:
        if user_id_str in data.get("users", {}):
            user = data["users"][user_id_str]
            leaderboard.append({
                "id": user["id"],
                "username": user["username"],
                "first_name": user["first_name"],
                "referrals": count
            })
    
    return leaderboard

def ban_user(user_id: int, ban_status: bool = True) -> bool:
    """Ban or unban a user."""
    user_id_str = str(user_id)
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False
        
        data["users"][user_id_str]["banned"] = ban_status
        save_user_data(data)
            
    action_text = "Banned" if ban_status else "Unbanned"
    record_user_activity(user_id, action_text, f"User was {action_text.lower()} by admin")
    return True

def is_user_banned(user_id: int) -> bool:
    """Check if user is banned."""
    user_data = get_user_data(user_id)
    if not user_data:
        return False
    
    return user_data.get("banned", False)

def reset_user_points(user_id: int) -> bool:
    """Reset a user's points to zero."""
    user_id_str = str(user_id)
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False
        
        data["users"][user_id_str]["points"] = 0
        save_user_data(data)
    return True

def set_user_points(user_id: int, new_points: int) -> bool:
    """Set a user's points to a specific value."""
    user_id_str = str(user_id)
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False
            
        data["users"][user_id_str]["points"] = max(0, int(new_points))
        save_user_data(data)
            
    record_user_activity(user_id, "Points Set", f"Admin set points to {new_points}", f"={new_points}")
    return True

def delete_user(user_id: int) -> bool:
    """Delete a user permanently from the database."""
    try:
        user_id_str = str(user_id)
        with data_lock:
            data = get_user_data()
            if data and "users" in data and user_id_str in data["users"]:
                del data["users"][user_id_str]
                save_user_data(data)
                return True
        return False
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        return False

# User Activity Log operations with Auto-Archiving
def record_user_activity(user_id: int, action_type: str, details: str, points_impact: str = "N/A") -> bool:
    """Record a user activity event with auto-archiving to keep database fast."""
    try:
        with data_lock:
            data = _load_json_safe(USER_ACTIVITY_FILE, {"activities": []})
            activities = data.get("activities", [])
            new_activity = {
                "id": len(activities) + 1,
                "user_id": int(user_id),
                "type": action_type,
                "details": details,
                "points_impact": points_impact,
                "timestamp": int(time.time())
            }
            activities.append(new_activity)
            
            # Auto-archive if size exceeds 4,000 items
            if len(activities) > 4000:
                to_archive = activities[:-2500]
                data["activities"] = activities[-2500:]
                try:
                    archive_file = "user_activity_archive.json"
                    arch_data = _load_json_safe(archive_file, {"activities": []})
                    arch_data.setdefault("activities", []).extend(to_archive)
                    _save_json_atomic(archive_file, arch_data, indent=2, make_backup=False)
                except Exception as e_arch:
                    logger.error(f"Error archiving old user activities: {e_arch}")
            else:
                data["activities"] = activities
            
            _save_json_atomic(USER_ACTIVITY_FILE, data, indent=2, make_backup=False)
        return True
    except Exception as e:
        logger.error(f"Error recording user activity: {e}")
        return False

def get_user_activities(user_id: int) -> List[Dict]:
    """Get custom activities for a user."""
    try:
        with data_lock:
            data = _load_json_safe(USER_ACTIVITY_FILE, {"activities": []})
        activities = data.get("activities", [])
        return [a for a in activities if a.get("user_id") == int(user_id)]
    except Exception as e:
        logger.error(f"Error getting user activities: {e}")
        return []

# OTT Account operations
def get_ott_accounts(category: str = None) -> List[Dict]:
    """Get all OTT accounts or accounts of a specific category."""
    try:
        with data_lock:
            data = _load_json_safe(OTT_ACCOUNTS_FILE, {"accounts": []})
        accounts = data.get("accounts", [])
        if category:
            return [acc for acc in accounts if acc.get("category") == category]
        return accounts
    except Exception as e:
        logger.error(f"Unexpected error in get_ott_accounts: {e}")
        return []

def save_ott_accounts(accounts: List[Dict]) -> bool:
    """Save OTT accounts to file atomically."""
    with data_lock:
        return _save_json_atomic(OTT_ACCOUNTS_FILE, {"accounts": accounts}, indent=2)

def add_ott_account(category: str, credentials: str, validity_days: int) -> bool:
    """Add a new OTT account to the database."""
    accounts = get_ott_accounts()
    categories = get_categories()
    if category not in categories:
        return False
    
    price = categories[category].get("price", 10)
    new_account = {
        "id": len(accounts) + 1,
        "category": category,
        "credentials": credentials,
        "price": price,
        "validity_days": validity_days,
        "added_at": int(time.time()),
        "redeemed": False,
        "redeemed_by": None,
        "redeemed_at": None
    }
    accounts.append(new_account)
    return save_ott_accounts(accounts)

def redeem_ott_account(account_id: int, user_id: int, free: bool = False) -> Tuple[bool, Dict]:
    """Mark an OTT account as redeemed by a user."""
    user_id_str = str(user_id)
    
    with data_lock:
        accounts_data = _load_json_safe(OTT_ACCOUNTS_FILE, {"accounts": []})
        accounts = accounts_data.get("accounts", [])
            
        for i, account in enumerate(accounts):
            if account["id"] == account_id and not account["redeemed"]:
                # Get category info to get price
                categories = get_categories()
                category = account["category"]
                if category not in categories:
                    return False, {}
                    
                price = categories[category].get("price", 10)
                
                # Load user data atomically
                data = get_user_data()
                if not data or "users" not in data or user_id_str not in data["users"]:
                    return False, {}
                    
                current_points = data["users"][user_id_str].get("points", 0)
                if not free:
                    if current_points < price:
                        return False, {}
                    # Deduct points
                    data["users"][user_id_str]["points"] = current_points - price
                
                # Mark account as redeemed
                accounts[i]["redeemed"] = True
                accounts[i]["redeemed_by"] = user_id
                accounts[i]["redeemed_at"] = int(time.time())
                # Generate unique watermark code and store
                rand = secrets.token_hex(2)
                watermark = f"WM-{user_id}-{account_id}-{rand}".upper()
                accounts[i]["watermark"] = watermark
                
                # Add to user's redeemed accounts
                if "redeemed_accounts" not in data["users"][user_id_str]:
                    data["users"][user_id_str]["redeemed_accounts"] = []
                
                data["users"][user_id_str]["redeemed_accounts"].append(account_id)
                try:
                    wm_map = data["users"][user_id_str].get("redemption_watermarks", {})
                    wm_map[str(account_id)] = watermark
                    data["users"][user_id_str]["redemption_watermarks"] = wm_map
                except Exception:
                    pass
                
                # Save both data sources atomically
                saved_user = save_user_data(data)
                saved_ott = save_ott_accounts(accounts)
                    
                if saved_user and saved_ott:
                    return True, accounts[i]
                else:
                    return False, {}
        
        return False, {}

def get_available_ott_accounts() -> Dict[str, List[Dict]]:
    """Get available OTT accounts grouped by category."""
    try:
        accounts = get_ott_accounts()
        available = [acc for acc in accounts if not acc.get("redeemed", False)]
        
        grouped = {}
        for account in available:
            category = account.get("category")
            if category:
                if category not in grouped:
                    grouped[category] = []
                grouped[category].append(account)
        
        return grouped
    except Exception as e:
        logger.error(f"Error in get_available_ott_accounts: {e}")
        return {}

# ---------------- Chat storage ----------------

def _load_chat_messages() -> Dict:
    with data_lock:
        return _load_json_safe(CHAT_MESSAGES_FILE, {"messages": []})

def _save_chat_messages(data: Dict) -> bool:
    with data_lock:
        return _save_json_atomic(CHAT_MESSAGES_FILE, data, indent=2)

def append_chat_message(user_id: int, from_admin: bool, text: str = "", media_type: str = None,
                        file_id: str = None, admin_id: int = None) -> bool:
    """Append a chat message to the log with auto-pruning."""
    data = _load_chat_messages()
    messages = data.get("messages", [])
    msg = {
        "id": len(messages) + 1,
        "user_id": int(user_id),
        "from_admin": bool(from_admin),
        "text": text or "",
        "media_type": media_type or "",
        "file_id": file_id or "",
        "admin_id": int(admin_id) if admin_id is not None else None,
        "created_at": int(time.time())
    }
    messages.append(msg)
    # Prune if message log grows beyond 2500 items
    if len(messages) > 2500:
        messages = messages[-2000:]
    data["messages"] = messages
    return _save_chat_messages(data)

def get_user_chat_messages(user_id: int, limit: int = 50) -> List[Dict]:
    """Get recent chat messages for a user (ascending by time)."""
    data = _load_chat_messages()
    msgs = [m for m in data.get("messages", []) if m.get("user_id") == int(user_id)]
    msgs = sorted(msgs, key=lambda m: m.get("created_at", 0))
    return msgs[-limit:]

def get_recent_conversations(limit: int = 50) -> List[Dict]:
    """Get recent conversations by last message time."""
    data = _load_chat_messages()
    msgs = data.get("messages", [])
    by_user = {}
    for m in msgs:
        uid = m.get("user_id")
        ts = m.get("created_at", 0)
        last_text = m.get("text") or ""
        if not last_text and m.get("media_type"):
            last_text = f"[{m.get('media_type')}]"
        if uid not in by_user or ts > by_user[uid].get("last_ts", 0):
            by_user[uid] = {
                "user_id": uid,
                "last_ts": ts,
                "last_text": last_text,
                "from_admin": m.get("from_admin", False)
            }
    convs = sorted(by_user.values(), key=lambda c: c.get("last_ts", 0), reverse=True)
    return convs[:limit]


# Category operations
def get_categories() -> Dict:
    """Get all OTT categories."""
    try:
        with data_lock:
            data = _load_json_safe(CATEGORIES_FILE, {"categories": {}})
        return data.get("categories", {})
    except Exception as e:
        logger.error(f"Error reading categories: {e}")
        return {}

def save_categories(categories: Dict) -> bool:
    """Save categories to file atomically."""
    with data_lock:
        return _save_json_atomic(CATEGORIES_FILE, {"categories": categories}, indent=2)

def add_category(name: str, price: int = 10, validity_days: int = 30) -> bool:
    """Add a new OTT category."""
    categories = get_categories()
    if name in categories:
        return False
    categories[name] = {
        "name": name,
        "price": price,
        "enabled": True,
        "validity_days": validity_days
    }
    return save_categories(categories)

def set_category_price(name: str, price: int) -> bool:
    """Set price for a category."""
    categories = get_categories()
    if name not in categories:
        return False
    categories[name]["price"] = price
    return save_categories(categories)

def set_category_status(name: str, enabled: bool) -> bool:
    """Enable or disable a category."""
    categories = get_categories()
    if name not in categories:
        return False
    categories[name]["enabled"] = enabled
    return save_categories(categories)

def set_category_validity(name: str, days: int) -> bool:
    """Set validity days for a category."""
    categories = get_categories()
    if name not in categories:
        return False
    categories[name]["validity_days"] = days
    return save_categories(categories)

def remove_category(name: str) -> bool:
    """Remove a category."""
    categories = get_categories()
    if name not in categories:
        return False
    del categories[name]
    return save_categories(categories)

# Channel operations
def get_channels() -> List[Dict]:
    """Get all required channels."""
    try:
        with data_lock:
            data = _load_json_safe(CHANNELS_FILE, {"channels": []})
        return data.get("channels", [])
    except Exception as e:
        logger.error(f"Error reading channels: {e}")
        return []

def save_channels(channels: List[Dict]) -> bool:
    """Save channels to file atomically."""
    with data_lock:
        return _save_json_atomic(CHANNELS_FILE, {"channels": channels}, indent=2)

def add_channel(channel_id: str, name: str, link: str, button_name: str, channel_type: str = "telegram") -> bool:
    """Add a new required channel."""
    channels = get_channels()
    for channel in channels:
        if channel["id"] == channel_id:
            return False
    new_channel = {
        "id": channel_id,
        "name": name,
        "link": link,
        "button_name": button_name,
        "type": channel_type
    }
    channels.append(new_channel)
    return save_channels(channels)

def remove_channel(channel_id: str) -> bool:
    """Remove a channel by ID."""
    channels = get_channels()
    original_len = len(channels)
    channels = [ch for ch in channels if ch["id"] != channel_id]
    if len(channels) < original_len:
        return save_channels(channels)
    return False

# Zero-cost giveaway winner tracking
def has_won_zero_cost(user_id: int) -> bool:
    """Return True if the user has already won a zero-cost giveaway."""
    user = get_user_data(user_id)
    return bool(user and user.get("won_zero_cost", False))

def record_zero_cost_wins(user_ids: List[int]) -> None:
    """Mark a list of users as having won a zero-cost giveaway."""
    if not user_ids:
        return
    data = get_user_data()
    changed = False
    for uid in user_ids:
        uid_str = str(uid)
        if uid_str in data.get("users", {}):
            if not data["users"][uid_str].get("won_zero_cost", False):
                data["users"][uid_str]["won_zero_cost"] = True
                changed = True
    if changed:
        save_user_data(data)

# Giveaway operations
def get_giveaways() -> List[Dict]:
    """Get all giveaways."""
    try:
        with data_lock:
            data = _load_json_safe(GIVEAWAYS_FILE, {"giveaways": []})
        return data.get("giveaways", [])
    except Exception as e:
        logger.error(f"Error reading giveaways: {e}")
        return []

def save_giveaways(giveaways: List[Dict]) -> bool:
    """Save giveaways to file atomically."""
    with data_lock:
        return _save_json_atomic(GIVEAWAYS_FILE, {"giveaways": giveaways}, indent=2)

def add_giveaway(min_points: int, num_winners: int, duration_hours: int, created_by: int, eligibility: str = "exactly", title: str = "Giveaway", description: str = "", entry_cost: int = 0) -> int:
    """Add a new giveaway and return its ID."""
    giveaways = get_giveaways()
    current_time = int(time.time())
    end_time = current_time + (float(duration_hours) * 3600)
    new_giveaway = {
        "id": len(giveaways) + 1,
        "min_points": min_points,
        "num_winners": num_winners,
        "created_at": current_time,
        "end_time": int(end_time),
        "created_by": created_by,
        "completed": False,
        "winners": [],
        "eligibility_type": eligibility,
        "title": title,
        "description": description,
        "entry_cost": entry_cost
    }
    giveaways.append(new_giveaway)
    if save_giveaways(giveaways):
        return new_giveaway["id"]
    return -1

from typing import Tuple

def create_giveaway(giveaway_data: Dict) -> Tuple[bool, int]:
    """Create a giveaway from a dict payload."""
    try:
        min_points = int(giveaway_data.get("min_points", 0))
        num_winners = int(giveaway_data.get("num_winners", 1))
        duration_hours = int(giveaway_data.get("duration_hours", 24))
        created_by = int(giveaway_data.get("created_by", 1))
        eligibility_type = giveaway_data.get("eligibility_type", "exactly")
        title = giveaway_data.get("title", "Giveaway")
        description = giveaway_data.get("description", "")
        entry_cost = int(giveaway_data.get("entry_cost", 0))

        giveaway_id = add_giveaway(
            min_points=min_points,
            num_winners=num_winners,
            duration_hours=duration_hours,
            created_by=created_by,
            eligibility=eligibility_type,
            title=title,
            description=description,
            entry_cost=entry_cost,
        )
        return (giveaway_id > 0, giveaway_id)
    except Exception as e:
        logger.error(f"Failed to create giveaway: {e}")
        return (False, -1)

def complete_giveaway(giveaway_id: int, winners: List[int]) -> bool:
    """Mark a giveaway as completed with winners."""
    giveaways = get_giveaways()
    for i, giveaway in enumerate(giveaways):
        if giveaway["id"] == giveaway_id:
            giveaways[i]["completed"] = True
            giveaways[i]["winners"] = winners
            return save_giveaways(giveaways)
    return False

def end_giveaway(giveaway_id: int) -> bool:
    """End a giveaway immediately and pick winners."""
    try:
        giveaway_id = int(giveaway_id)
        g = get_giveaway_by_id(giveaway_id)
        if not g or g.get("completed"):
            return False

        participants = g.get("participants", [])
        num_winners = int(g.get("num_winners", 1))
        
        import random
        if len(participants) <= num_winners:
            winners = participants
        else:
            winners = random.sample(participants, num_winners)
            
        return complete_giveaway(giveaway_id, winners)
    except Exception as e:
        logger.error(f"Error ending giveaway: {e}")
        return False

def cancel_giveaway(giveaway_id: int) -> bool:
    """Cancel (delete) a giveaway."""
    try:
        giveaway_id = int(giveaway_id)
        giveaways = get_giveaways()
        initial_len = len(giveaways)
        giveaways = [g for g in giveaways if g.get("id") != giveaway_id]
        if len(giveaways) < initial_len:
            return save_giveaways(giveaways)
        return False
    except Exception as e:
        logger.error(f"Error canceling giveaway: {e}")
        return False

def get_active_giveaways() -> List[Dict]:
    """Get all active (not completed) giveaways."""
    giveaways = get_giveaways()
    current_time = int(time.time())
    return [
        g for g in giveaways 
        if not g["completed"] and g["end_time"] > current_time
    ]

def get_giveaway_by_id(giveaway_id: int) -> Optional[Dict]:
    """Return a giveaway dict by id, or None."""
    giveaways = get_giveaways()
    for g in giveaways:
        if g.get("id") == giveaway_id:
            return g
    return None

def update_giveaway_fields(giveaway_id: int, **fields) -> bool:
    """Update specific fields on a giveaway and persist."""
    giveaways = get_giveaways()
    updated = False
    for i, g in enumerate(giveaways):
        if g.get("id") == giveaway_id:
            g.update(fields)
            giveaways[i] = g
            updated = True
            break
    if not updated:
        return False
    return save_giveaways(giveaways)

def get_eligible_users_for_giveaway_type(required_points: int, eligibility_type: str = "exactly") -> List[Dict]:
    """Get users eligible for a giveaway based on eligibility type."""
    data = get_user_data()
    eligible_users = []
    for user_id, user_data in data.get("users", {}).items():
        if user_data.get("banned", False):
            continue
        if eligibility_type == "atleast":
            if user_data.get("points", 0) >= required_points:
                eligible_users.append(user_data)
        else:
            if user_data.get("points", 0) == required_points:
                eligible_users.append(user_data)
    return eligible_users

# Tutorial operations (Bypassed - Always complete)
def get_user_tutorial_progress(user_id: int) -> Dict:
    """Get a user's tutorial progress."""
    return {"completed": True, "current_step": 7, "steps_completed": [1, 2, 3, 4, 5, 6, 7]}

def update_tutorial_progress(user_id: int, step_completed: int, tutorial_completed: bool = True) -> bool:
    """Update a user's tutorial progress."""
    return True

def is_tutorial_completed(user_id: int) -> bool:
    """Check if a user has completed the tutorial."""
    return True

def join_giveaway(giveaway_id: int, user_id: int) -> bool:
    """Add a user to a giveaway's participants list."""
    giveaways = get_giveaways()
    for g in giveaways:
        if g["id"] == giveaway_id:
            if "participants" not in g:
                g["participants"] = []
            if user_id not in g["participants"]:
                user_data = get_user_data(user_id)
                if not user_data:
                    logger.error(f"User {user_id} not found when trying to join giveaway {giveaway_id}")
                    return False
                
                current_points = user_data.get("points", 0)
                entry_cost = g.get("entry_cost", 0)
                
                if current_points < entry_cost:
                    logger.warning(f"User {user_id} insufficient points for giveaway {giveaway_id}")
                    return False
                
                if entry_cost > 0:
                    success, new_balance = update_user_points(user_id, -entry_cost)
                    if not success:
                        return False
                
                g["participants"].append(user_id)
                save_giveaways(giveaways)
                return True
            else:
                return False
    return False

def leave_giveaway(giveaway_id: int, user_id: int) -> bool:
    """Remove a user from a giveaway's participants list."""
    giveaways = get_giveaways()
    for g in giveaways:
        if g["id"] == giveaway_id and "participants" in g:
            if user_id in g["participants"]:
                g["participants"].remove(user_id)
                save_giveaways(giveaways)
                return True
    return False

def is_user_in_giveaway(giveaway_id: int, user_id: int) -> bool:
    """Check if a user is participating in a giveaway."""
    giveaways = get_giveaways()
    for g in giveaways:
        if g["id"] == giveaway_id and "participants" in g:
            return user_id in g["participants"]
    return False

def get_user_giveaway_history(user_id: int) -> list:
    """Return a list of giveaways the user has participated in."""
    giveaways = get_giveaways()
    return [g for g in giveaways if "participants" in g and user_id in g["participants"]]

def get_giveaway_participants(giveaway_id: int) -> List[int]:
    """Return the participants list for a giveaway id."""
    g = get_giveaway_by_id(giveaway_id)
    if not g:
        return []
    return g.get("participants", [])

CODES_FILE = "codes.json"

def get_codes() -> Dict[str, Dict]:
    """Get all codes from the codes.json file."""
    with data_lock:
        return _load_json_safe(CODES_FILE, {})

def save_codes(codes: Dict[str, Dict]) -> bool:
    """Save codes atomically."""
    with data_lock:
        return _save_json_atomic(CODES_FILE, codes, indent=2)

def create_code(points: int) -> str:
    """Create a new one-time code with a points value."""
    import secrets
    code = secrets.token_hex(4).upper()
    codes = get_codes()
    codes[code] = {
        "points": points, 
        "used": False, 
        "used_by": None, 
        "used_at": None,
        "created_at": int(time.time())
    }
    save_codes(codes)
    return code

def validate_code(code: str) -> Optional[Dict]:
    codes = get_codes()
    code_data = codes.get(code)
    if code_data and not code_data["used"]:
        return code_data
    return None

def redeem_code(code: str, user_id: int) -> Optional[int]:
    codes = get_codes()
    code_data = codes.get(code)
    if code_data and not code_data["used"]:
        code_data["used"] = True
        code_data["used_by"] = user_id
        code_data["used_at"] = int(time.time())
        save_codes(codes)
        # Add points to user
        from database import update_user_points
        success, new_balance = update_user_points(user_id, code_data["points"])
        if success:
            return new_balance
        else:
            return None
    return None

def create_bulk_codes(points: int, count: int) -> list:
    """Create multiple one-time codes with a points value."""
    import secrets
    codes = get_codes()
    new_codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()
        while code in codes:
            code = secrets.token_hex(4).upper()
        codes[code] = {
            "points": points, 
            "used": False, 
            "used_by": None, 
            "used_at": None,
            "created_at": int(time.time())
        }
        new_codes.append(code)
    save_codes(codes)
    return new_codes

def can_claim_gift(user_id: int, cooldown_seconds: int = 86400) -> bool:
    """Check if user can claim a gift code (default: 24h cooldown).

    If the user record does not exist yet or there is no last claim timestamp,
    allow claiming (no cooldown enforced for first claim).
    """
    data = get_user_data()
    user_id_str = str(user_id)
    user_rec = data.get("users", {}).get(user_id_str)
    if not user_rec:
        return True
    last_gift_claim = user_rec.get("last_gift_claim", 0)
    current_time = int(time.time())
    return (current_time - last_gift_claim) >= cooldown_seconds

def update_gift_claim(user_id: int) -> None:
    """Update the last gift claim time for a user."""
    data = get_user_data()
    user_id_str = str(user_id)
    if user_id_str in data["users"]:
        data["users"][user_id_str]["last_gift_claim"] = int(time.time())
        save_user_data(data)

def remove_user(user_id: int) -> bool:
    """Remove a user from the database."""
    data = get_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        return False
    
    # Remove user from users dict
    del data["users"][user_id_str]
    
    # Remove user from referrals
    if user_id_str in data["referrals"]:
        del data["referrals"][user_id_str]
    
    # Remove user from other users' referral lists
    for referrer_id, referrals in data["referrals"].items():
        if user_id_str in referrals:
            referrals.remove(user_id_str)
    
    return save_user_data(data)

# Shopping Cart operations

    return results

# Add missing helper functions for web app
def add_user_points(user_id: int, points: int) -> bool:
    """Add points to a user."""
    data = get_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        return False
    
    data["users"][user_id_str]["points"] += points
    return save_user_data(data)

def remove_user_points(user_id: int, points: int) -> bool:
    """Remove points from a user."""
    data = get_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        return False
    
    data["users"][user_id_str]["points"] -= points
    # Ensure points don't go below zero
    if data["users"][user_id_str]["points"] < 0:
        data["users"][user_id_str]["points"] = 0
        
    return save_user_data(data)

def transfer_points(from_user_id: int, to_user_id: int, points: int) -> Tuple[bool, str]:
    """Transfer points from one user to another."""
    if points <= 0:
        return False, "Points must be greater than 0"
    
    if from_user_id == to_user_id:
        return False, "Cannot transfer points to yourself"
    
    from_user_str = str(from_user_id)
    to_user_str = str(to_user_id)
    
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data:
            return False, "Database error"
        
        # Check if both users exist
        if from_user_str not in data.get("users", {}):
            return False, "Sender not found"
        if to_user_str not in data.get("users", {}):
            return False, "Recipient not found"
        
        # Check if sender has enough points
        sender_points = data["users"][from_user_str].get("points", 0)
        if sender_points < points:
            return False, f"Insufficient points. You have {sender_points} points"
        
        # Perform the transfer
        data["users"][from_user_str]["points"] -= points
        data["users"][to_user_str]["points"] += points
        
        if save_user_data(data):
            return True, f"Successfully transferred {points} points"
        else:
            return False, "Transfer failed"

def update_user_channel_status(user_id: int, status: bool) -> bool:
    """Safely update a user's channel join status."""
    user_id_str = str(user_id)
    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False
            
        data["users"][user_id_str]["channel_status"] = status
        data["users"][user_id_str]["channel_status_changed_at"] = int(time.time())
        return save_user_data(data)

def get_user_wallet_balance(user_id: int) -> Tuple[float, int]:
    """Get user's wallet balance in rupees and points."""
    data = get_user_data(user_id)
    if not data:
        return 0.0, 0
    
    points = data.get("points", 0)
    # Convert points to rupees (10 points = 5rs)
    rupees = (points * 5) / 10
    return rupees, points

def convert_points_to_rupees(points: int) -> float:
    """Convert points to rupees."""
    return (points * 5) / 10

def convert_rupees_to_points(rupees: float) -> int:
    """Convert rupees to points."""
    return int((rupees * 10) / 5)

def use_wallet_for_purchase(user_id: int, amount_rupees: float) -> Tuple[bool, str]:
    """Use wallet balance for purchase."""
    if amount_rupees <= 0:
        return False, "Amount must be greater than 0"
    
    user_id_str = str(user_id)
    required_points = convert_rupees_to_points(amount_rupees)

    with data_lock:
        data = get_user_data()
        if not data or "users" not in data or user_id_str not in data["users"]:
            return False, "User not found"
        
        current_points = data["users"][user_id_str].get("points", 0)
        if current_points < required_points:
            return False, f"Insufficient wallet balance. You need {required_points} points (₹{amount_rupees})"
        
        # Deduct points
        data["users"][user_id_str]["points"] -= required_points
        if save_user_data(data):
            return True, f"Successfully used {required_points} points (₹{amount_rupees}) from wallet"
        else:
            return False, "Purchase failed"

def unban_user(user_id: int) -> bool:
    """Unban a user."""
    return ban_user(user_id, False)

def get_notifications() -> list:
    """Get all notifications from the system."""
    return []

def create_notification(notif_type: str, title: str, message: str) -> bool:
    """Create a notification."""
    return True

GIFT_CODES_FILE = CODES_FILE

# --- Gift Code Functions ---

def get_gift_codes():
    """Load all gift codes from JSON file."""
    with data_lock:
        return _load_json_safe(GIFT_CODES_FILE, {"codes": [], "next_id": 1})

def save_gift_codes(data):
    """Save gift codes to JSON file atomically."""
    with data_lock:
        return _save_json_atomic(GIFT_CODES_FILE, data, indent=2)

def create_gift_code(code, points, expiry_days=30, usage_limit=1):
    """Creates a new gift code."""
    data = get_gift_codes()
    
    # Check if code already exists
    for existing_code in data["codes"]:
        if existing_code["code"].upper() == code.upper():
            return False, "Code already exists"

    expiry_timestamp = int(time.time()) + (expiry_days * 24 * 60 * 60)
    
    new_code = {
        "id": data["next_id"],
        "code": code.upper(),
        "points": int(points),
        "expiry_at": expiry_timestamp,
        "usage_limit": int(usage_limit),
        "usage_count": 0,
        "users_used": [],
        "created_at": int(time.time()),
        "enabled": True
    }
    
    data["codes"].append(new_code)
    data["next_id"] += 1
    
    if save_gift_codes(data):
        return True, new_code
    else:
        return False, "Failed to save data"



def use_gift_code(code, user_id):
    """Marks a gift code as used by a user (handles both redeemed_by and users_used)."""
    data = get_gift_codes()
    for c in data["codes"]:
        if c["code"].upper() == code.upper():
            c["usage_count"] = c.get("usage_count", 0) + 1
            
            # Update whichever list exists, favoring redeemed_by
            if "redeemed_by" in c:
                if user_id not in c["redeemed_by"]:
                    c["redeemed_by"].append(user_id)
            elif "users_used" in c:
                if user_id not in c["users_used"]:
                    c["users_used"].append(user_id)
            else:
                c["redeemed_by"] = [user_id]
                
            c["updated_at"] = int(time.time())
            return save_gift_codes(data)
    return False

# --- End Gift Code Functions ---

# --- Bulk Gift Code Utilities ---
def _generate_unique_gift_code(prefix: str, existing_codes: set[str]) -> str:
    """Generate a unique code with given prefix."""
    import secrets, string
    base = prefix.upper()
    # Keep appending 6 random alnum characters until unique
    for _ in range(10000):
        suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        code = f"{base}{suffix}"
        if code not in existing_codes:
            return code
    raise RuntimeError("Failed to generate unique gift code")

def bulk_create_gift_codes(prefix: str, points: int, count: int, expiry_days: int = 30, usage_limit: int = 1):
    """Create multiple gift codes with a common prefix. Returns list of created code dicts."""
    if count <= 0:
        return []
    data = get_gift_codes()
    existing = {c["code"].upper() for c in data.get("codes", [])}
    created = []
    next_id = int(data.get("next_id", 1))
    now = int(time.time())
    expiry_ts = now + (int(expiry_days) * 24 * 60 * 60)
    for _ in range(int(count)):
        code = _generate_unique_gift_code(prefix, existing)
        existing.add(code)
        entry = {
            "id": next_id,
            "code": code,
            "points": int(points),
            "expiry_at": expiry_ts,
            "usage_limit": int(usage_limit),
            "usage_count": 0,
            "users_used": [],
            "created_at": now,
            "enabled": True,
        }
        data.setdefault("codes", []).append(entry)
        next_id += 1
        created.append(entry)
    data["next_id"] = next_id
    save_gift_codes(data)
    return created

def delete_gift_code_by_id(code_id: int) -> bool:
    """Delete a gift code by numeric ID."""
    data = get_gift_codes()
    before = len(data.get("codes", []))
    data["codes"] = [c for c in data.get("codes", []) if int(c.get("id", 0)) != int(code_id)]
    after = len(data.get("codes", []))
    if after != before:
        return save_gift_codes(data)
    return False

def delete_gift_code_by_code(code: str) -> bool:
    """Delete a gift code by exact code string (case-insensitive)."""
    data = get_gift_codes()
    code_up = code.upper()
    before = len(data.get("codes", []))
    data["codes"] = [c for c in data.get("codes", []) if c.get("code", "").upper() != code_up]
    after = len(data.get("codes", []))
    if after != before:
        return save_gift_codes(data)
    return False

def delete_gift_codes_by_prefix(prefix: str) -> int:
    """Delete all gift codes whose code starts with the prefix. Returns number removed."""
    data = get_gift_codes()
    pref = prefix.upper()
    before = len(data.get("codes", []))
    data["codes"] = [c for c in data.get("codes", []) if not c.get("code", "").upper().startswith(pref)]
    removed = before - len(data.get("codes", []))
    if removed > 0:
        save_gift_codes(data)
    return removed

# --- Posting & Batch Utilities for Gift Codes ---

def gift_codes_attach_post_info(codes_list: list, chat_id: int, message_id: int, batch_id: str, prefix: str) -> bool:
    """Attach channel post info to a list of gift code dicts (by code)."""
    data = get_gift_codes()
    code_set = {str(c['code']).upper() if isinstance(c, dict) else str(c).upper() for c in codes_list}
    updated = False
    for c in data.get("codes", []):
        if str(c.get("code","")).upper() in code_set:
            # chat_id can be numeric (-100...) or a string like @channelusername; don't force cast
            c["post_chat_id"] = chat_id
            # message_id should be int; cast defensively
            try:
                c["post_message_id"] = int(message_id)
            except Exception:
                c["post_message_id"] = message_id
            c["post_batch_id"] = str(batch_id)
            c["post_prefix"] = str(prefix)
            updated = True
    return save_gift_codes(data) if updated else True

def get_gift_codes_by_batch(batch_id: str) -> list:
    data = get_gift_codes()
    return [c for c in data.get("codes", []) if str(c.get("post_batch_id","")) == str(batch_id)]

def get_batch_post_info(batch_id: str):
    """Return (chat_id, message_id) for a batch id, or (None, None)."""
    codes = get_gift_codes_by_batch(batch_id)
    if not codes:
        return None, None
    c = codes[0]
    return c.get("post_chat_id"), c.get("post_message_id")

def build_gift_post_text_for_batch(batch_id: str, bot_handle: str = "@refer127bot") -> str:
    """Build the channel post text showing active codes and used code details."""
    import html as _html
    from datetime import datetime
    codes = get_gift_codes_by_batch(batch_id)
    if not codes:
        return "<b>Gift Codes</b>\nNo codes found."
    first = codes[0]
    prefix = first.get("post_prefix") or ""
    points = first.get("points", 0)
    expiry_ts = first.get("expiry_at", 0)
    expiry_str = time.strftime('%Y-%m-%d', time.localtime(expiry_ts)) if expiry_ts else 'N/A'
    active = []
    used = []
    for c in sorted(codes, key=lambda x: x.get("id", 0)):
        usage = int(c.get("usage_count", 0) or 0)
        limit = int(c.get("usage_limit", 1) or 1)
        if c.get("enabled", True) and usage < limit:
            active.append(c)
        else:
            used.append(c)
    remaining = len(active)
    total = len(codes)
    header = (
        "<b>🎁🔥 Gift Code Bonanza! 🔥🎁</b>\n"
        "<i>Grab them before they expire</i> ✨\n\n"
        f"<b>Prefix:</b> <code>{_html.escape(prefix)}</code>\n"
        f"<b>Reward:</b> <b>{points} points</b> per code\n"
        f"<b>Expires:</b> <b>{expiry_str}</b>\n"
        f"<b>Remaining:</b> {remaining} / {total}\n\n"
        "<b>Codes:</b>\n"
    )
    lines = []
    for c in active[:100]:
        lines.append(f"• /claimgift {_html.escape(c.get('code',''))}")
    if not lines:
        lines.append("<i>None</i>")
    used_lines = []
    for c in used:
        users_used = c.get("users_used", []) or []
        if users_used:
            uid = users_used[-1]
            u = get_user_data(int(uid)) or {}
            uname = u.get("first_name") or "User"
            handle = u.get("username") or ""
            used_at = int(c.get("updated_at", c.get("expiry_at", 0)) or 0)
            if not used_at:
                used_at = int(time.time())
            ts_str = datetime.fromtimestamp(used_at).strftime("%Y-%m-%d %H:%M")
            used_lines.append(
                f"• <code>{_html.escape(c.get('code',''))}</code> — Redeemed by "
                f"<a href=\"tg://user?id={uid}\">{_html.escape(uname)}</a>"
                f"{(' (@'+_html.escape(handle)+')') if handle else ''} — {ts_str}"
            )
        else:
            used_lines.append(f"• <code>{_html.escape(c.get('code',''))}</code> — <i>Redeemed</i>")
    used_block = "<b>Used Codes:</b>\n" + ("\n".join(used_lines) if used_lines else "<i>None</i>")
    howto = (
        "\n\n<b>How to claim:</b>\n"
        f"• Open the bot {bot_handle}\n"
        "• Paste the code using <b>/claimgift CODE</b>\n"
        "• First come, first served ⏳"
    )
    return header + "\n".join(lines) + "\n\n" + used_block + howto




def get_giveaways():
    """Get all giveaways."""
    try:
        if os.path.exists(GIVEAWAYS_FILE):
             with open(GIVEAWAYS_FILE, 'r') as f:
                data = json.load(f)
                return data.get("giveaways", [])
    except Exception as e:
        logger.error(f"Error loading giveaways: {e}")
    return []

def get_channels() -> List[Dict]:
    """Get all channels."""
    try:
        with open(CHANNELS_FILE, 'r') as f:
            data = json.load(f)
            return data.get("channels", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception as e:
        logger.error(f"Error reading channels: {e}")
        return []

def get_categories() -> Dict:
    """Get all categories."""
    try:
        with open(CATEGORIES_FILE, 'r') as f:
            data = json.load(f)
            return data.get("categories", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        logger.error(f"Error reading categories: {e}")
        return {}

        return []



# Duplicate add_channel and delete_channel removed.
# Ensuring delete_channel alias exists for compatibility
delete_channel = remove_channel

def add_category(name, price, validity, type='redeem'):
    """Add a new category."""
    try:
        existing = get_categories()
        if name in existing:
            return False
            
        existing[name] = {
            "price": float(price),
            "validity_days": int(validity),
            "type": type
        }
        
        with data_lock:
            with open(CATEGORIES_FILE, 'w') as f:
                json.dump({"categories": existing}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error adding category: {e}")
        return False

def edit_category(old_name, new_name, price, validity, type='redeem'):
    """Edit an existing category."""
    try:
        existing = get_categories()
        if old_name not in existing:
            return False
            
        # If renaming, check if new name exists
        if old_name != new_name and new_name in existing:
            return False
            
        # Remove old entry if renaming
        if old_name != new_name:
            del existing[old_name]
            
        existing[new_name] = {
            "price": float(price),
            "validity_days": int(validity),
            "type": type
        }
        
        with data_lock:
            with open(CATEGORIES_FILE, 'w') as f:
                json.dump({"categories": existing}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error editing category: {e}")
        return False

def delete_category(name, type='redeem'):
    """Delete a category."""
    try:
        existing = get_categories()
        if name not in existing:
            return False
            
        del existing[name]
        
        with data_lock:
            with open(CATEGORIES_FILE, 'w') as f:
                json.dump({"categories": existing}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
        return False

def add_gift_code(code, points, days, usage_limit):
    """Add a new gift code."""
    try:
        data = get_gift_codes()
        codes = data.get("codes", [])
        
        # Check uniqueness
        if any(c["code"] == code for c in codes):
            return False
            
        new_code = {
            "id": len(codes) + 1,
            "code": code,
            "points": int(points),
            "days": int(days) if days else 0,
            "usage_limit": int(usage_limit),
            "usage_count": 0,
            "created_at": int(time.time()),
            "enabled": True,
            "redeemed_by": []
        }
        
        codes.append(new_code)
        
        # Save usually happens to 'codes.json' or whatever file
        # CODES_FILE is imported from config
        path = CODES_FILE
        with data_lock:
            with open(path, 'w') as f:
                json.dump({"codes": codes}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error adding gift code: {e}")
        return False

def delete_gift_code(code_str):
    """Delete a gift code by code string."""
    try:
        data = get_gift_codes()
        codes = data.get("codes", [])
        initial = len(codes)
        codes = [c for c in codes if c["code"] != code_str]
        
        if len(codes) == initial:
            return False
            
        # CODES_FILE is imported from config
        path = CODES_FILE
        with data_lock:
            with open(path, 'w') as f:
                json.dump({"codes": codes}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error deleting gift code: {e}")
        return False

def delete_gift_codes_by_prefix(prefix):
    """Delete gift codes starting with prefix."""
    try:
        data = get_gift_codes()
        codes = data.get("codes", [])
        initial = len(codes)
        codes = [c for c in codes if not c["code"].startswith(prefix)]
        
        # CODES_FILE is imported from config
        path = CODES_FILE
        with data_lock:
            with open(path, 'w') as f:
                json.dump({"codes": codes}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error deleting gift codes prefix: {e}")
        return False

def bulk_delete_gift_codes(ids):
    """Delete multiple gift codes by ID."""
    try:
        data = get_gift_codes()
        codes = data.get("codes", [])
        initial = len(codes)
        # Filter out codes whose ID is in the list
        codes = [c for c in codes if c.get("id") not in ids]
        
        # CODES_FILE is imported from config
        path = CODES_FILE
        with data_lock:
            with open(path, 'w') as f:
                json.dump({"codes": codes}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error bulk deleting gift codes: {e}")
        return False

def delete_ott_account(account_id):
    """Delete an OTT account."""
    try:
        accounts = get_ott_accounts()
        initial = len(accounts)
        accounts = [a for a in accounts if str(a.get("id")) != str(account_id)]
        
        if len(accounts) == initial:
            return False
            
        return save_ott_accounts(accounts)
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        return False

def edit_ott_account(account_id, category, credentials, validity_days):
    """Edit an OTT account."""
    try:
        accounts = get_ott_accounts()
        for a in accounts:
            if str(a.get("id")) == str(account_id):
                a["category"] = category
                a["credentials"] = credentials
                a["validity_days"] = int(validity_days)
                a["price"] = get_categories().get(category, {}).get("price", 10)
                return save_ott_accounts(accounts)
        return False
    except Exception as e:
        logger.error(f"Error editing account: {e}")
        return False

def bulk_delete_ott_accounts(ids):
    """Delete multiple OTT accounts."""
    try:
        accounts = get_ott_accounts()
        accounts = [a for a in accounts if str(a.get("id")) not in ids]
        return save_ott_accounts(accounts)
    except Exception as e:
        logger.error(f"Error bulk deleting accounts: {e}")
        return False

# Removed duplicate code block (add_giveaway, end_giveaway, etc) that was shadowing the actual implementation.


def get_gift_code_by_code(code: str) -> Optional[Dict]:
    """Get a gift code by its code string (case-insensitive)."""
    try:
        data = get_gift_codes()
        codes = data.get("codes", [])
        code_upper = code.strip().upper()
        
        for c in codes:
            if c.get("code", "").upper() == code_upper:
                return c

        return None
    except Exception as e:
        logger.error(f"Error getting gift code by code: {e}")
        return None

from datetime import datetime, timedelta
import random

def get_channel_growth_data(days: int = 7) -> List[Dict]:
    """Get channel growth data (mocked for now)."""
    try:
        # Generate mock data for the chart
        data = []
        today = datetime.now()
        
        for i in range(days):
            d = today - timedelta(days=i)
            # Format: 'Jan 01' or '2023-01-01'
            date_str = d.strftime("%d %b")
            
            # Simple random mock data
            data.append({
                "date": date_str,
                "joined": random.randint(5, 25),
                "left": random.randint(0, 5)
            })
            
        # Return sorted by date (oldest first) so chart is left-to-right
        data.sort(key=lambda x: datetime.strptime(x['date'] + f" {today.year}", "%d %b %Y"))
        return data
        
    except Exception as e:
        logger.error(f"Error generating channel growth data: {e}")
        return []

# System Config Support
SYSTEM_CONFIG_FILE = "system_config.json"

def get_system_config(key: str, default: Any = None) -> Any:
    """Get a system configuration value."""
    try:
        with data_lock:
            data = _load_json_safe(SYSTEM_CONFIG_FILE, {})
        return data.get(key, default)
    except Exception as e:
        logger.error(f"Error reading system config: {e}")
        return default

def set_system_config(key: str, value: Any) -> bool:
    """Set a system configuration value atomically."""
    try:
        with data_lock:
            data = _load_json_safe(SYSTEM_CONFIG_FILE, {})
            data[key] = value
            return _save_json_atomic(SYSTEM_CONFIG_FILE, data, indent=2)
    except Exception as e:
        logger.error(f"Error saving system config: {e}")
        return False

# --- User History Deletion Management ---

def delete_user_history_item(user_id: int, item_type: str, item_id: str) -> bool:
    """Deletes a single redemption history item and restocks it."""
    with data_lock:
        if item_type == "OTT Account":
            try:
                ott_data = _load_json_safe(OTT_ACCOUNTS_FILE, {"accounts": []})
                accounts = ott_data.get("accounts", [])
                changed = False
                for acc in accounts:
                    if str(acc.get("id")) == str(item_id) and str(acc.get("redeemed_by")) == str(user_id):
                        acc["redeemed_by"] = None
                        acc["redeemed_at"] = None
                        acc["watermark"] = None
                        acc["status"] = "available"
                        changed = True
                        break
                if changed:
                    _save_json_atomic(OTT_ACCOUNTS_FILE, ott_data, indent=2)
                    
                    try:
                        user_data = get_user_data() or {"users": {}}
                        users = user_data.get("users", {})
                        uid_str = str(user_id)
                        if uid_str in users and "redeemed_accounts" in users[uid_str]:
                            val_to_remove = int(item_id) if item_id.isdigit() else item_id
                            if val_to_remove in users[uid_str]["redeemed_accounts"]:
                                users[uid_str]["redeemed_accounts"].remove(val_to_remove)
                            elif str(item_id) in users[uid_str]["redeemed_accounts"]:
                                users[uid_str]["redeemed_accounts"].remove(str(item_id))
                                
                            save_user_data(user_data)
                    except Exception as e:
                        logger.error(f"Error removing watermark from user list: {e}")
                    return True
            except Exception as e:
                logger.error(f"Error deleting OTT history item: {e}")
                return False
                
        elif item_type == "Gift Code":
            try:
                codes = _load_json_safe(CODES_FILE, {"codes": []})
                codes_list = codes.get("codes", []) if isinstance(codes, dict) else codes
                changed = False
                for c in codes_list:
                    if isinstance(c, dict) and str(c.get("code")) == str(item_id):
                        matched_user = False
                        
                        if str(c.get("used_by")) == str(user_id):
                            c["used_by"] = None
                            c["used"] = False
                            changed = True
                            matched_user = True
                            
                        if "users_used" in c:
                            if user_id in c["users_used"]:
                                c["users_used"].remove(user_id)
                                c["usage_count"] = max(0, c.get("usage_count", 1) - 1)
                                changed = True
                                matched_user = True
                            elif str(user_id) in c["users_used"]:
                                c["users_used"].remove(str(user_id))
                                c["usage_count"] = max(0, c.get("usage_count", 1) - 1)
                                changed = True
                                matched_user = True
                                
                        if "redeemed_by" in c:
                            if user_id in c["redeemed_by"]:
                                c["redeemed_by"].remove(user_id)
                                changed = True
                                matched_user = True
                            elif str(user_id) in c["redeemed_by"]:
                                c["redeemed_by"].remove(str(user_id))
                                changed = True
                                matched_user = True
                                
                        if matched_user:
                            break
                
                if changed:
                    if isinstance(codes, dict):
                        codes["codes"] = codes_list
                    return _save_json_atomic(CODES_FILE, codes if isinstance(codes, dict) else {"codes": codes_list}, indent=2)
            except Exception as e:
                logger.error(f"Error deleting Gift Code history item: {e}")
                return False
                
    return False

def delete_all_user_history(user_id: int) -> bool:
    """Deletes and restocks all user history (bulk delete)."""
    success = False
    with data_lock:
        try:
            ott_data = _load_json_safe(OTT_ACCOUNTS_FILE, {"accounts": []})
            accounts = ott_data.get("accounts", [])
            ott_changed = False
            for acc in accounts:
                if str(acc.get("redeemed_by")) == str(user_id):
                    acc["redeemed_by"] = None
                    acc["redeemed_at"] = None
                    acc["watermark"] = None
                    acc["status"] = "available"
                    ott_changed = True
            
            if ott_changed:
                _save_json_atomic(OTT_ACCOUNTS_FILE, ott_data, indent=2)
                success = True
        except Exception as e:
            logger.error(f"Error bulk deleting OTT history: {e}")

        try:
            user_data = get_user_data() or {"users": {}}
            users = user_data.get("users", {})
            uid_str = str(user_id)
            if uid_str in users:
                if "redeemed_accounts" in users[uid_str]:
                    users[uid_str]["redeemed_accounts"] = []
                if "redemption_watermarks" in users[uid_str]:
                    users[uid_str]["redemption_watermarks"] = {}
                save_user_data(user_data)
        except Exception as e:
            logger.error(f"Error clearing user mapped history: {e}")

        try:
            codes = _load_json_safe(CODES_FILE, {"codes": []})
            codes_list = codes.get("codes", []) if isinstance(codes, dict) else codes
            code_changed = False
            for c in codes_list:
                if isinstance(c, dict):
                    if str(c.get("used_by")) == str(user_id):
                        c["used_by"] = None
                        c["used"] = False
                        code_changed = True
                        
                    if "users_used" in c:
                        if user_id in c["users_used"]:
                            c["users_used"].remove(user_id)
                            c["usage_count"] = max(0, c.get("usage_count", 1) - 1)
                            code_changed = True
                        elif str(user_id) in c["users_used"]:
                            c["users_used"].remove(str(user_id))
                            c["usage_count"] = max(0, c.get("usage_count", 1) - 1)
                            code_changed = True
                            
                    if "redeemed_by" in c:
                        if user_id in c["redeemed_by"]:
                            c["redeemed_by"].remove(user_id)
                            code_changed = True
                        elif str(user_id) in c["redeemed_by"]:
                            c["redeemed_by"].remove(str(user_id))
                            code_changed = True
            if code_changed:
                if isinstance(codes, dict):
                    codes["codes"] = codes_list
                _save_json_atomic(CODES_FILE, codes if isinstance(codes, dict) else {"codes": codes_list}, indent=2)
                success = True
        except Exception as e:
            logger.error(f"Error bulk deleting Gift Code history: {e}")
            
    return success

# ---------------------
# Broadcast History
# ---------------------
def get_broadcast_history() -> List[Dict]:
    try:
        from config import BROADCAST_HISTORY_FILE
        with data_lock:
            data = _load_json_safe(BROADCAST_HISTORY_FILE, {"history": []})
            return data.get("history", [])
    except Exception as e:
        logger.error(f"Error reading broadcast history: {e}")
    return []

def save_broadcast(broadcast_data: Dict) -> None:
    try:
        from config import BROADCAST_HISTORY_FILE
        with data_lock:
            data = _load_json_safe(BROADCAST_HISTORY_FILE, {"history": []})
            existing = [b for b in data.get("history", []) if b.get("id") == broadcast_data.get("id")]
            if existing:
                existing[0].update(broadcast_data)
            else:
                data.setdefault("history", []).insert(0, broadcast_data)
            _save_json_atomic(BROADCAST_HISTORY_FILE, data, indent=2)
    except Exception as e:
        logger.error(f"Error saving broadcast history: {e}")

def get_scheduled_broadcasts() -> List[Dict]:
    return [b for b in get_broadcast_history() if b.get("status") == "Scheduled"]

def cancel_scheduled_broadcast(broadcast_id: str) -> bool:
    try:
        from config import BROADCAST_HISTORY_FILE
        with data_lock:
            data = _load_json_safe(BROADCAST_HISTORY_FILE, {"history": []})
            for b in data.get("history", []):
                if b.get("id") == broadcast_id and b.get("status") == "Scheduled":
                    b["status"] = "Cancelled"
                    _save_json_atomic(BROADCAST_HISTORY_FILE, data, indent=2)
                    return True
    except Exception as e:
        logger.error(f"Error cancelling broadcast: {e}")
    return False

# --- Pending Exchanges ---
from config import BASE_DIR
PENDING_EXCHANGES_FILE = os.path.join(BASE_DIR, "data", "pending_exchanges.json")

def _load_pending_exchanges() -> list:
    with data_lock:
        data = _load_json_safe(PENDING_EXCHANGES_FILE, [])
        return data if isinstance(data, list) else []

def _save_pending_exchanges(data: list) -> bool:
    with data_lock:
        return _save_json_atomic(PENDING_EXCHANGES_FILE, data, indent=2)

def add_pending_exchange(user_id: int, category: str, credentials: str) -> int:
    exchanges = _load_pending_exchanges()
    for e in exchanges:
        if (e.get("credentials") == credentials 
            and e.get("status") == "pending" 
            and e.get("user_id") == user_id):
            return e.get("id", -1)
    
    exchange_id = 1 if not exchanges else max(e.get("id", 0) for e in exchanges) + 1
    
    exchange = {
        "id": exchange_id,
        "user_id": user_id,
        "category": category,
        "credentials": credentials,
        "status": "pending",
        "timestamp": int(time.time()),
        "admin_message": ""
    }
    exchanges.append(exchange)
    _save_pending_exchanges(exchanges)
    return exchange_id

def get_pending_exchanges() -> list:
    all_exchanges = _load_pending_exchanges()
    return [e for e in all_exchanges if e.get("status") in ["pending", "approved"]]

def get_exchange_by_id(exchange_id: int) -> dict:
    exchanges = _load_pending_exchanges()
    for e in exchanges:
        if e.get("id") == exchange_id:
            return e
    return None

def update_exchange_status(exchange_id: int, status: str, admin_message: str = "") -> bool:
    exchanges = _load_pending_exchanges()
    for i, e in enumerate(exchanges):
        if e.get("id") == exchange_id:
            exchanges[i]["status"] = status
            if admin_message:
                exchanges[i]["admin_message"] = admin_message
            return _save_pending_exchanges(exchanges)
    return False
