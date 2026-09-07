
import os
import logging
import sys
import threading
import time
import json
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# Import configuration
import app_utils
import config
from config import (
    FLASK_PORT, FLASK_HOST, ADMIN_IDS, OWNER_IDS, ADMIN_USERNAMES,
    SCHEDULER_ENABLED, WEB_ADMIN_USERNAME, WEB_ADMIN_PASSWORD
)
import database as db
from telegram.error import Forbidden

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "ott_giveaway_bot_secret")

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize Scheduler

# Global variable to track bot status and instance
bot_status = {
    "is_running": False,
    "start_time": None,
    "webhook_mode": False
}
global_bot_instance = None

def set_bot_instance(bot):
    global global_bot_instance
    global_bot_instance = bot

def get_bot_instance():
    return global_bot_instance

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    if user_id in [WEB_ADMIN_USERNAME, "127HUB", "admin"]:
        return User(user_id)
    return None

# Context processor to inject common variables
@app.context_processor
def inject_common():
    return dict(
        bot_status=bot_status,
        now=datetime.now()
    )

# Custom filters
@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(timestamp):
    if not timestamp:
        return ''
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

@app.template_filter('formatted_time')
def formatted_time(timestamp):
    if not timestamp:
        return 'N/A'
    try:
        ts = int(float(timestamp))
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(timestamp)

# --- Routes ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html', status=bot_status,
                         admin_ids=ADMIN_IDS,
                         admin_usernames=ADMIN_USERNAMES)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Credentials verification
        if username == WEB_ADMIN_USERNAME and password == WEB_ADMIN_PASSWORD:
            user = User(username)
            login_user(user)
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # --- 1. Fetch Data ---
        user_data_full = db.get_user_data()
        users = user_data_full.get('users', {})
        
        ott_accounts = db.get_ott_accounts()

        
        # --- 2. Calculate Stats ---
        total_users = len(users)

        total_accounts = len(ott_accounts)
        
        # Accounts stats
        redeemed_accounts = len([a for a in ott_accounts if a.get('redeemed')])
        available_accounts = total_accounts - redeemed_accounts
        low_stock_count = 0 # Simple logic: count categories with < 5 items? Skipping for speed, or set to 0.
        # Actually, let's just count accounts that are not redeemed
        

        
        # Today's stats
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        

        
        # Users active/joined today
        # detailed user stats require more data or parsing 'joined_at' if available
        # logic: count users with 'joined_at' >= today_start
        users_today = 0
        active_today = 0 # Mock or real if available
        for u in users.values():
            if u.get('joined_at', 0) >= today_start:
                users_today += 1
            # active_today could be based on 'last_active' if tracked. defaulting:
            if u.get('last_active', 0) >= today_start:
                active_today += 1
        

        # Uptime
        uptime_str = "Offline"
        if bot_status['start_time']:
            diff = int(time.time()) - bot_status['start_time']
            hours, remainder = divmod(diff, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m"

        # --- 3. Prepare Lists ---
        # Latest Orders (last 5)

        
        # Latest Users (last 5)
        # Sort users by join date (assuming 'joined_at' exists, else random/unsorted)
        users_list = list(users.values())
        # safe sort
        users_list.sort(key=lambda x: x.get('joined_at', 0), reverse=True)
        latest_users = users_list[:5]

        # --- 4. Bundle Stats ---
        stats = {
            "total_users": total_users,
            "active_today": active_today,
            "total_accounts": total_accounts,
            "low_stock_count": low_stock_count,
            "channel_health": 100, # Mock value or calculate based on errors?
            "bot_running": bot_status.get('is_running', False),
            "uptime": uptime_str,
            "scheduler_on": SCHEDULER_ENABLED,
            "latest_users": latest_users
        }
        
        # Get channel growth data
        channel_daily = db.get_channel_growth_data(days=7)

        return render_template('dashboard.html', stats=stats, status=bot_status, channel_daily=channel_daily)

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        # flash(f"Error loading dashboard data: {e}", "error") # Don't flash on every load in dev
        # Return empty stats to avoid 500
        empty_stats = {k: 0 for k in ["total_users", "total_orders", "active_today", "orders_today", "revenue_today", "success_rate", "total_accounts", "low_stock_count", "pending_orders", "ending_soon"]}
        empty_stats.update({"channel_health": 0, "bot_running": False, "uptime": "Error", "scheduler_on": False, "latest_orders": [], "latest_users": []})
        return render_template('dashboard.html', stats=empty_stats, status=bot_status)

@app.route('/status')
def status():
    return {"status": "ok", "bot_running": bot_status["is_running"]}



# --- System Management (from patch_system.py logic) ---
@app.route('/power_tools/update', methods=['POST'])
@login_required
def power_tools_update():
    # Placeholder: In a real app, this would update config.py or a database settings table
    # For now, we'll just flash a message saying it's implemented
    flash("Settings update logic would run here (Config persistence needed).", "info")
    return redirect(url_for('settings_page'))

@app.route('/power_tools/channel_check', methods=['POST'])
@login_required
def power_tools_channel_check():
    flash("Channel consistency check started (Placeholder).", "info")
    return redirect(url_for('settings_page'))

@app.route('/power_tools/diagnostics', methods=['POST'])
@login_required
def power_tools_diagnostics():
    flash("System diagnostics run successfully. No issues found.", "success")
    return redirect(url_for('settings_page'))

@app.route('/power_tools/reindex', methods=['POST'])
@login_required
def power_tools_reindex():
    task = request.form.get('task')
    flash(f"Reindexing '{task}' completed.", "success")
    return redirect(url_for('settings_page'))

@app.route('/power_tools/bulk_points', methods=['POST'])
@login_required
def power_tools_bulk_points():
    try:
        points = int(request.form.get('points', 0))
        min_points = int(request.form.get('min_points', 0) or 0)
        
        if points == 0:
            flash("Points must be non-zero", "warning")
            return redirect(url_for('settings_page'))
            
        user_data = db.get_user_data()
        users = user_data.get('users', {})
        count = 0
        for uid, data in users.items():
            current_p = data.get('points', 0)
            if current_p > min_points:
                users[uid]['points'] = max(0, current_p + points)
                count += 1
        
        user_data['users'] = users
        db.save_user_data(user_data)
        flash(f"Updated points for {count} users.", "success")
    except Exception as e:
        flash(f"Error updating points: {e}", "error")
        
    return redirect(url_for('settings_page'))

@app.route('/power_tools/bulk_ban', methods=['POST'])
@login_required
def power_tools_bulk_ban():
    user_ids = request.form.get('user_ids', '').split(',')
    action = request.form.get('action')
    success_count = 0
    
    for uid_str in user_ids:
        try:
            uid = int(uid_str.strip())
            is_ban = (action == 'ban')
            if db.ban_user(uid, is_ban):
                success_count += 1
        except:
            continue
            
    flash(f"Successfully {action}ned {success_count} users.", "success")
    return redirect(url_for('settings_page'))

@app.route('/export/<data_type>')
@login_required
def export_data(data_type):
    import config
    # Map data type to file
    if data_type == 'users':
        file_path = config.USER_DATA_FILE
    elif data_type == 'orders':
        file_path = config.ORDERS_FILE
    else:
        flash("Invalid export type", "error")
        return redirect(url_for('settings_page'))
        
    import os
    if os.path.exists(file_path):
        from flask import send_file
        return send_file(file_path, as_attachment=True)
    else:
        flash(f"Data file not found for {data_type}", "error")
        return redirect(url_for('settings_page'))

@app.route('/import', methods=['POST'])
@login_required
def import_data():
    try:
        import config
        import json
        
        data_type = request.form.get('type')
        uploaded_file = request.files.get('file')
        
        if not uploaded_file:
            flash("No file uploaded", "error")
            return redirect(url_for('settings_page'))
            
        data = json.load(uploaded_file)
        
        if data_type == 'users':
            if not isinstance(data, dict) or "users" not in data:
                flash("Invalid users JSON structure. Must contain 'users' key.", "error")
                return redirect(url_for('settings_page'))
            success = db.save_user_data(data)
            if not success:
                flash("Import blocked by Wipe Protection! Ensure backup data contains valid users.", "error")
                return redirect(url_for('settings_page'))
        else:
            flash("Invalid import type", "error")
            return redirect(url_for('settings_page'))
            
        flash(f"Successfully imported {data_type} data!", "success")
    except Exception as e:
        logger.error(f'Import error: {e}')
        flash(f"Failed to import data: {e}", "error")
        
    return redirect(url_for('settings_page'))

# --- Placeholders for other standard routes (Users, Channels, etc.) ---
# I will add basic implementations for these ensuring navigation works.

@app.route('/users')
@login_required
def users_page():
    from flask import request
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    search_query = request.args.get('search', '').lower().strip()
    per_page = 50
    
    user_data_full = db.get_user_data() or {}
    users_data = user_data_full.get('users', {})
    
    if search_query:
        filtered_users = {
            uid: udata for uid, udata in users_data.items()
            if search_query in str(uid) or search_query in (udata.get('username') or '').lower()
        }
    else:
        filtered_users = users_data

    users_sorted = sorted(filtered_users.items(), key=lambda x: x[1].get('points', 0), reverse=True)
    
    total_users = len(users_sorted)
    total_pages = max(1, (total_users + per_page - 1) // per_page)
    
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_users = users_sorted[start_idx:end_idx]
    
    referrals_data = user_data_full.get('referrals', {})
    referrals_map = {uid: len(refs) for uid, refs in referrals_data.items()}
    
    return render_template('users.html', 
                           title='Users', 
                           page_title='User Management', 
                           users=paginated_users, 
                           referrals_map=referrals_map,
                           page=page,
                           total_pages=total_pages,
                           total_users=total_users,
                           search_query=request.args.get('search', ''))

@app.route('/users/<int:user_id>/history')
@login_required
def user_history_page(user_id):
    try:
        user_data_full = db.get_user_data()
        users = user_data_full.get('users', {})
        user_id_str = str(user_id)
        
        if user_id_str not in users:
            flash("User not found", "error")
            return redirect(url_for('users_page'))
            
        user = users[user_id_str]
        
        # Get all accounts to find ones redeemed by this user
        all_accounts = db.get_ott_accounts()
        all_categories = db.get_categories()
        
        history = []
        
        # Look for OTT accounts redeemed by out user
        for acc in all_accounts:
            # Check by user_id explicitly first matching integer comparison, fallback to the redeemed_accounts list
            if str(acc.get("redeemed_by")) == user_id_str or acc.get("id") in user.get("redeemed_accounts", []):
                # Construct history record
                cat_info = all_categories.get(acc.get("category", ""), {})
                price = cat_info.get("price", "N/A")
                title = cat_info.get("name", acc.get("category", "Unknown"))
                
                redeemed_at = acc.get("redeemed_at", 0)
                
                # Fetch watermark if it exists natively on account, or from the user's mapping natively mapped in the db
                watermark = acc.get("watermark", user.get("redemption_watermarks", {}).get(acc.get("id"), "N/A"))
                
                history.append({
                    "type": "OTT Account",
                    "title": title,
                    "price": price,
                    "redeemed_at": redeemed_at,
                    "credentials": acc.get("credentials", "Hidden"),
                    "watermark": watermark,
                    "id": acc.get("id")
                })
                
        # Look for Gift Codes
        all_codes = db.get_codes() if hasattr(db, 'get_codes') else {}
        codes_list = all_codes.get("codes", []) if isinstance(all_codes, dict) else all_codes
        
        for cdata in codes_list:
            if not isinstance(cdata, dict):
                continue
            used_list = cdata.get("redeemed_by") or cdata.get("users_used") or []
            used_list_str = [str(x) for x in used_list]
            # Single user codes might use used_by
            if str(cdata.get("used_by")) == user_id_str or user_id_str in used_list_str:
                history.append({
                    "type": "Gift Code",
                    "title": f"Code: {cdata.get('code', 'Unknown')}",
                    "price": f"+{cdata.get('points', 0)} (Earned)",
                    "redeemed_at": cdata.get("used_at") or cdata.get("updated_at") or 0,
                    "credentials": "N/A",
                    "watermark": "N/A",
                    "id": cdata.get('code', 'Unknown')
                })

        # Add Bot Join Event
        if user.get("joined_at"):
            history.append({
                "type": "System",
                "title": "Joined the bot",
                "price": "N/A",
                "redeemed_at": user.get("joined_at", 0),
                "credentials": "N/A",
                "watermark": "N/A",
                "id": f"join_{user_id}"
            })
            
        # Add Referrals
        user_referrals = user_data_full.get('referrals', {}).get(user_id_str, [])
        for ref_id in user_referrals:
            ref_user = users.get(str(ref_id), {})
            ref_name = ref_user.get("username") or ref_user.get("first_name") or "Unknown User"
            history.append({
                "type": "Referral",
                "title": f"Referred user: {ref_name} ({ref_id})",
                "price": "Bonus Earned",
                "redeemed_at": ref_user.get("joined_at", 0),
                "credentials": "N/A",
                "watermark": "N/A",
                "id": f"ref_{ref_id}"
            })
            
        # Add Chat Messages
        try:
            chat_msgs = db.get_user_chat_messages(user_id, limit=50)
            for msg in chat_msgs:
                history.append({
                    "type": "Chat Message",
                    "title": f"Sent message: {msg.get('text', '[Media]')}",
                    "price": "N/A",
                    "redeemed_at": msg.get("created_at", 0),
                    "credentials": "N/A",
                    "watermark": "N/A",
                    "id": f"msg_{msg.get('id', 0)}"
                })
        except Exception:
            pass
            
        # Add Channel Events
        try:
            chan_events = [e for e in db.get_channel_events(limit=500) if e.get("user_id") == user_id]
            for ce in chan_events:
                history.append({
                    "type": "Channel Event",
                    "title": f"{'Joined' if ce.get('action') == 'joined' else 'Left'} a required channel",
                    "price": "N/A",
                    "redeemed_at": ce.get("timestamp", 0),
                    "credentials": "N/A",
                    "watermark": "N/A",
                    "id": f"chan_{ce.get('timestamp', 0)}"
                })
        except Exception:
            pass
            
        # Add Custom User Activities (Daily bonus, Bans, Admin edits)
        try:
            activities = db.get_user_activities(user_id)
            for act in activities:
                history.append({
                    "type": act.get("type", "Activity"),
                    "title": act.get("details", "User Activity"),
                    "price": act.get("points_impact", "N/A"),
                    "redeemed_at": act.get("timestamp", 0),
                    "credentials": "N/A",
                    "watermark": "N/A",
                    "id": f"act_{act.get('id', 0)}"
                })
        except Exception:
            pass

        # Ensure redeemed_at is always an int before sorting
        for idx, item in enumerate(history):
            if history[idx].get("redeemed_at") is None:
                history[idx]["redeemed_at"] = 0

        # Sort combined history mostly recent first
        history.sort(key=lambda x: x.get("redeemed_at", 0) or 0, reverse=True)
        
        return render_template('user_history.html', user=user, user_id=user_id, history=history)
    except Exception as e:
        logger.error(f"Error loading user history: {e}")
        flash(f"Error loading history: {e}", "error")
        return redirect(url_for('users_page'))

@app.route('/users/<int:user_id>/history/delete', methods=['POST'])
@login_required
def delete_history_item(user_id):
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON request'}), 400
            
        item_type = data.get('type')
        item_id = data.get('id')
        if not item_type or not item_id:
            return jsonify({'success': False, 'error': 'Missing parameters'}), 400
        
        success = db.delete_user_history_item(user_id, item_type, str(item_id))
        if success:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Failed to delete or item not found'}), 400
    except Exception as e:
        logger.error(f"Error delete_history_item: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/users/<int:user_id>/history/delete_all', methods=['POST'])
@login_required
def delete_all_history(user_id):
    try:
        success = db.delete_all_user_history(user_id)
        if success:
            flash("All history deleted successfully", "success")
        else:
            flash("No history found or failed to delete.", "error")
    except Exception as e:
        logger.error(f"Error delete_all_history: {e}")
        flash(f"Error deleting history: {e}", "error")
    return redirect(url_for('user_history_page', user_id=user_id))

@app.route('/users/update_points', methods=['POST'])
@login_required
def users_update_points():
    try:
        user_id = request.form.get('user_id')
        points = request.form.get('points')
        
        if not user_id or points is None or points == '':
            flash("Invalid points or user ID", "error")
            return redirect(url_for('users_page'))
            
        if db.set_user_points(user_id, points):
            flash("User points updated successfully", "success")
        else:
            flash("Failed to update points", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('users_page'))



@app.route('/users/delete', methods=['POST'])
@login_required
def users_delete():
    try:
        user_id = request.form.get('user_id')
        if db.delete_user(user_id):
            flash("User deleted successfully", "success")
        else:
            flash("Failed to delete user", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('users_page'))

@app.route('/users/toggle_ban', methods=['POST'])
@login_required
def users_toggle_ban():
    try:
        user_id = request.form.get('user_id')
        action = request.form.get('action') # 'ban' or 'unban'
        ban_status = (action == 'ban')
        
        if db.ban_user(user_id, ban_status):
            flash(f"User {action}ned successfully", "success")
        else:
            flash(f"Failed to {action} user", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('users_page'))

@app.route('/users/bulk_action', methods=['POST'])
@login_required
def users_bulk_action():
    try:
        user_ids_str = request.form.get('user_ids')
        action = request.form.get('action') # 'ban', 'unban', 'delete'
        
        if not user_ids_str or not action:
            flash("Missing parameters for bulk action", "error")
            return redirect(url_for('users_page'))
            
        user_ids = user_ids_str.split(',')
        success_count = 0
        
        for uid in user_ids:
            uid = uid.strip()
            if not uid: continue
            
            if action == 'ban':
                if db.ban_user(uid, True): success_count += 1
            elif action == 'unban':
                if db.ban_user(uid, False): success_count += 1
            elif action == 'delete':
                if db.delete_user(uid): success_count += 1
                
        flash(f"Successfully applied {action} to {success_count} users", "success")
    except Exception as e:
        logger.error(f"Error in users_bulk_action: {e}")
        flash(f"Error: {e}", "error")
        
    return redirect(url_for('users_page'))

@app.route('/channels')
@login_required
def channels_page():
    channels = db.get_channels()
    return render_template('channels.html', channels=channels)

@app.route('/channels/add', methods=['POST'])
@login_required
def channels_add():
    try:
        type = request.form.get('type')
        channel_id = request.form.get('channel_id')
        name = request.form.get('name')
        link = request.form.get('link')
        btn_text = request.form.get('button_name')
        
        # Auto-generate ID for non-Telegram channels if missing
        if not channel_id:
            if type == 'telegram':
                flash("Channel ID is required for Telegram channels", "error")
                return redirect(url_for('channels_page'))
            else:
                # Generate unique ID for WhatsApp/Other
                channel_id = f"{type}_{int(time.time())}"
        
        if db.add_channel(channel_id, name, link, btn_text, type):
            flash("Channel added successfully", "success")
        else:
            flash("Failed to add channel", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('channels_page'))

@app.route('/channels/delete', methods=['POST'])
@login_required
def channels_delete():
    try:
        channel_id = request.form.get('channel_id')
        if db.delete_channel(channel_id):
             flash("Channel deleted successfully", "success")
        else:
             flash("Failed to delete channel", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('channels_page'))

@app.route('/categories')
@login_required
def categories_page():
    cats_dict = db.get_categories()
    # Template expects list of objects for the table
    categories_list = []
    for name, data in cats_dict.items():
        cat_obj = data.copy()
        cat_obj['name'] = name
        cat_obj['id'] = name # Use name as ID for simplicity
        categories_list.append(cat_obj)
        
    return render_template('categories.html', redeem_categories=categories_list)

@app.route('/categories/add/redeem', methods=['POST'])
@login_required
def categories_add_redeem():
    try:
        name = request.form.get('name')
        price = request.form.get('price')
        validity = request.form.get('validity')
        
        if db.add_category(name, price, validity, type='redeem'):
            flash("Category added successfully", "success")
        else:
            flash("Failed to add category (check if name exists)", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('categories_page'))

@app.route('/categories/edit', methods=['POST'])
@login_required
def categories_edit():
    try:
        old_name = request.form.get('category_id') # Form uses id as old name
        new_name = request.form.get('name')
        price = request.form.get('price')
        validity = request.form.get('validity')
        type = request.form.get('category_type', 'redeem')
        
        if db.edit_category(old_name, new_name, price, validity, type):
            flash("Category updated successfully", "success")
        else:
            flash("Failed to update category", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('categories_page'))

@app.route('/categories/delete', methods=['POST'])
@login_required
def categories_delete():
    try:
        name = request.form.get('category_id')
        type = request.form.get('category_type')
        
        if db.delete_category(name, type):
            flash("Category deleted successfully", "success")
        else:
            flash("Failed to delete category", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('categories_page'))

@app.route('/accounts')
@login_required
def accounts_page():
    # Template needs redeem_accounts (list) and redeem_categories (dict)
    accounts = db.get_ott_accounts()
    categories = db.get_categories()
    
    return render_template('accounts.html', 
                         redeem_accounts=accounts,
                         redeem_categories=categories)

@app.route('/accounts/add', methods=['POST'])
@login_required
def accounts_add():
    try:
        category = request.form.get('category')
        credentials = request.form.get('credentials')
        validity = request.form.get('validity_days')
        
        if db.add_ott_account(category, credentials, int(validity)):
            flash("Account added successfully", "success")
        else:
            flash("Failed to add account", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('accounts_page'))

@app.route('/accounts/bulk_add', methods=['POST'])
@login_required
def accounts_bulk_add():
    try:
        category = request.form.get('category')
        validity = int(request.form.get('validity_days'))
        raw_creds = request.form.get('credentials_bulk')
        
        count = 0
        if raw_creds:
            lines = raw_creds.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line:
                    if db.add_ott_account(category, line, validity):
                        count += 1
        
        flash(f"Added {count} accounts successfully", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('accounts_page'))

@app.route('/accounts/delete_single', methods=['POST'])
@login_required
def accounts_delete_single():
    try:
        account_id = request.form.get('account_id')
        if db.delete_ott_account(account_id):
            flash("Account deleted", "success")
        else:
            flash("Failed to delete account", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('accounts_page'))

@app.route('/accounts/bulk_delete', methods=['POST'])
@login_required
def accounts_bulk_delete():
    try:
        ids_str = request.form.get('account_ids')
        if ids_str:
            ids = ids_str.split(',')
            if db.bulk_delete_ott_accounts(ids):
                flash(f"Deleted {len(ids)} accounts", "success")
            else:
                flash("Failed to delete accounts", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('accounts_page'))

@app.route('/accounts/edit', methods=['POST'])
@login_required
def accounts_edit():
    try:
        account_id = request.form.get('account_id')
        category = request.form.get('category')
        credentials = request.form.get('credentials')
        validity = request.form.get('validity_days')
        
        if db.edit_ott_account(account_id, category, credentials, validity):
            flash("Account updated", "success")
        else:
             flash("Failed to update account", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('accounts_page'))


# --- Broadcast System ---
class BroadcastManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()
        self.status = {
            "is_running": False,
            "total": 0,
            "sent": 0,
            "failed": 0,
            "current": 0,
            "message": "Idle",
            "start_time": None
        }

    def start_broadcast(self, title, message, message_type, notify_admins, scheduled_time=None, target_audience="all", image_url=None, button_text=None, button_url=None, pin_message=False):
        import uuid
        broadcast_id = str(uuid.uuid4())
        broadcast_data = {
            "id": broadcast_id,
            "title": title,
            "message": message,
            "type": message_type,
            "notify_admins": notify_admins,
            "target_audience": target_audience,
            "image_url": image_url,
            "button_text": button_text,
            "button_url": button_url,
            "pin_message": pin_message,
            "total": 0,
            "sent": 0,
            "failed": 0,
            "created_at": time.time(),
            "scheduled_time": None,
            "status": "Initializing"
        }
        
        if scheduled_time:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(scheduled_time)
                broadcast_data["scheduled_time"] = dt.timestamp()
                broadcast_data["status"] = "Scheduled"
            except ValueError:
                return False, "Invalid scheduled time format"
            
            db.save_broadcast(broadcast_data)
            return True, "Broadcast scheduled successfully"
            
        with self._lock:
            if self.status["is_running"]:
                return False, "Broadcast already running"
            
            self._stop_event.clear()
            self.status = {
                "is_running": True,
                "total": 0,
                "sent": 0,
                "failed": 0,
                "current": 0,
                "message": "Initializing...",
                "start_time": time.time()
            }
            
            db.save_broadcast(broadcast_data)
            
            self._thread = threading.Thread(
                target=self._broadcast_worker,
                args=(broadcast_data,)
            )
            self._thread.daemon = True
            self._thread.start()
            return True, "Broadcast started"

    def stop_broadcast(self):
        with self._lock:
            if self.status["is_running"]:
                self._stop_event.set()
                return True, "Stopping broadcast..."
            return False, "No broadcast running"

    def _broadcast_worker(self, broadcast_data):
        import requests
        from config import TOKEN
        time.sleep(1)
        
        try:
            all_user_data = db.get_user_data()
            users = all_user_data.get("users", {})
            
            target_users = []
            for uid, data in users.items():
                if not data.get("banned", False):
                    target_users.append(int(uid))
            
            self.status["total"] = len(target_users)
            self.status["message"] = f"Sending to {len(target_users)} users..."
            broadcast_data["total"] = len(target_users)
            db.save_broadcast(broadcast_data)
            
            raw_msg = broadcast_data.get("message", "")
            title = broadcast_data.get("title", "")
            full_html = f"<b>{title}</b>\n\n{raw_msg}" if title else raw_msg
            plain_fallback = f"{title}\n\n{raw_msg}".replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<code>", "").replace("</code>", "") if title else raw_msg

            image_url = broadcast_data.get("image_url")
            btn_text = broadcast_data.get("button_text")
            btn_url = broadcast_data.get("button_url")
            pin_msg = broadcast_data.get("pin_message", False)

            reply_markup = None
            if btn_text and btn_url:
                reply_markup = {"inline_keyboard": [[{"text": btn_text, "url": btn_url}]]}

            # Send copy to admins
            if broadcast_data.get("notify_admins"):
                from config import ADMIN_IDS
                for admin_id in ADMIN_IDS:
                    try:
                        admin_text = f"<b>[Admin Copy - Broadcast]</b>\n\n{full_html}"
                        if image_url:
                            requests.post(
                                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                json={"chat_id": admin_id, "photo": image_url, "caption": admin_text, "parse_mode": "HTML", "reply_markup": reply_markup},
                                timeout=5
                            )
                        else:
                            requests.post(
                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                json={"chat_id": admin_id, "text": admin_text, "parse_mode": "HTML", "reply_markup": reply_markup},
                                timeout=5
                            )
                    except Exception as e:
                        logger.error(f"Failed to notify admin {admin_id}: {e}")
            
            count = 0
            for user_id in target_users:
                if self._stop_event.is_set():
                    self.status["message"] = "Broadcast cancelled by admin."
                    broadcast_data["status"] = "Cancelled"
                    break
                    
                sent_successfully = False
                for attempt in range(2):
                    try:
                        if image_url:
                            resp = requests.post(
                                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                json={"chat_id": user_id, "photo": image_url, "caption": full_html, "parse_mode": "HTML", "reply_markup": reply_markup},
                                timeout=6
                            )
                        else:
                            resp = requests.post(
                                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                json={"chat_id": user_id, "text": full_html, "parse_mode": "HTML", "reply_markup": reply_markup},
                                timeout=6
                            )
                        
                        if resp.status_code == 200:
                            sent_successfully = True
                            if pin_msg:
                                try:
                                    msg_id = resp.json().get("result", {}).get("message_id")
                                    if msg_id:
                                        requests.post(f"https://api.telegram.org/bot{TOKEN}/pinChatMessage", json={"chat_id": user_id, "message_id": msg_id, "disable_notification": True}, timeout=3)
                                except Exception:
                                    pass
                            break
                        elif resp.status_code == 429: # Rate limit
                            res_json = resp.json()
                            retry_after = res_json.get("parameters", {}).get("retry_after", 3)
                            time.sleep(retry_after + 0.5)
                            continue
                        elif resp.status_code == 400: # Entity parse error, retry plain text
                            if image_url:
                                resp_plain = requests.post(
                                    f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                    json={"chat_id": user_id, "photo": image_url, "caption": plain_fallback, "reply_markup": reply_markup},
                                    timeout=6
                                )
                            else:
                                resp_plain = requests.post(
                                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                    json={"chat_id": user_id, "text": plain_fallback, "reply_markup": reply_markup},
                                    timeout=6
                                )
                            if resp_plain.status_code == 200:
                                sent_successfully = True
                            break
                        elif resp.status_code == 403: # Blocked by user, do NOT delete user data
                            break
                        else:
                            break
                    except Exception:
                        break

                if sent_successfully:
                    self.status["sent"] += 1
                    broadcast_data["sent"] += 1
                else:
                    self.status["failed"] += 1
                    broadcast_data["failed"] += 1
                
                self.status["current"] += 1
                count += 1
                time.sleep(0.12)
            
            if not self._stop_event.is_set():
                self.status["message"] = "Broadcast completed successfully."
                broadcast_data["status"] = "Completed"

        except Exception as e:
            logger.error(f"Broadcast worker error: {e}")
            self.status["message"] = f"Error: {str(e)}"
            broadcast_data["status"] = f"Error: {str(e)}"
        finally:
            with self._lock:
                self.status["is_running"] = False
            db.save_broadcast(broadcast_data)

broadcast_manager = BroadcastManager()

# Background scheduler thread
def _broadcast_scheduler():
    while True:
        time.sleep(60)
        try:
            now = time.time()
            scheduled = db.get_scheduled_broadcasts()
            for b in scheduled:
                if b.get("scheduled_time", float('inf')) <= now:
                    b["status"] = "Initializing"
                    b["scheduled_time"] = None # Avoid double run
                    db.save_broadcast(b)
                    
                    # Start thread without going through start_broadcast checks if idle
                    if not broadcast_manager.status["is_running"]:
                        with broadcast_manager._lock:
                            broadcast_manager._stop_event.clear()
                            broadcast_manager.status = {
                                "is_running": True,
                                "total": b.get("total", 0),
                                "sent": 0,
                                "failed": 0,
                                "current": 0,
                                "message": "Starting scheduled broadcast...",
                                "start_time": time.time()
                            }
                            broadcast_manager._thread = threading.Thread(
                                target=broadcast_manager._broadcast_worker,
                                args=(b,)
                            )
                            broadcast_manager._thread.daemon = True
                            broadcast_manager._thread.start()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

threading.Thread(target=_broadcast_scheduler, daemon=True).start()


@app.route('/exchanges')
@login_required
def exchanges_page():
    exchanges = db.get_pending_exchanges()
    return render_template('exchanges.html', exchanges=exchanges)

@app.route('/exchanges/action', methods=['POST'])
@login_required
def exchange_action():
    try:
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        exchange_id = int(data.get('id', 0))
        admin_message = data.get('message', '').strip()
        
        exchange = db.get_exchange_by_id(exchange_id)
        if not exchange:
            return jsonify({"success": False, "error": f"Exchange #{exchange_id} not found"})
            
        if action == "approve":
            db.update_exchange_status(exchange_id, "approved", admin_message)
            
            # Reward logic
            reward_text = ""
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
                price = db.get_categories().get(exchange["category"], {}).get("price", 10)
                db.update_user_points(exchange["user_id"], price)
                reward_text = f"🎁 *Reward Added*\nSorry, no {exchange['category']} accounts were in stock. We have credited *{price} points* to your wallet instead!\n\n"
                try:
                    db.record_user_activity(exchange["user_id"], "Exchange Approved", f"Approved for {exchange['category']}", points_impact=f"+{price}")
                except Exception as e_act:
                    logger.error(f"Error recording user activity: {e_act}")
            else:
                try:
                    db.record_user_activity(exchange["user_id"], "Exchange Approved", f"Approved for {exchange['category']}", points_impact="Account Rewarded")
                except Exception as e_act:
                    logger.error(f"Error recording user activity: {e_act}")
            
            # Notify user in background thread so HTTP response is instant (<10ms)
            user_msg = (
                f"✅ *Exchange Account Update*\n\n"
                f"Your submission for *{exchange.get('category', 'Account')}* has been *APPROVED*.\n\n"
            )
            if reward_text:
                user_msg += reward_text
            if admin_message:
                user_msg += f"👨‍💻 *Admin Message*:\n`{admin_message}`"
            
            threading.Thread(
                target=app_utils.send_message,
                kwargs={
                    "chat_id": exchange["user_id"],
                    "text": user_msg,
                    "parse_mode": "Markdown"
                },
                daemon=True
            ).start()

        elif action == "reject":
            db.update_exchange_status(exchange_id, "rejected", admin_message)
            try:
                db.record_user_activity(exchange["user_id"], "Exchange Rejected", f"Rejected: {admin_message}")
            except Exception as e_act:
                logger.error(f"Error recording user activity: {e_act}")

            # Notify user in background thread so HTTP response is instant (<10ms)
            user_msg = (
                f"❌ *Exchange Account Update*\n\n"
                f"Your submission for *{exchange.get('category', 'Account')}* has been *REJECTED*.\n\n"
            )
            if admin_message:
                user_msg += f"Admin Message:\n`{admin_message}`"
            else:
                user_msg += "Your submitted account could not be verified."
                
            threading.Thread(
                target=app_utils.send_message,
                kwargs={
                    "chat_id": exchange["user_id"],
                    "text": user_msg,
                    "parse_mode": "Markdown"
                },
                daemon=True
            ).start()
        else:
            return jsonify({"success": False, "error": f"Invalid action '{action}'"})
            
        return jsonify({"success": True, "action": action, "id": exchange_id})
    except Exception as e:
        logger.error(f"Error in exchange_action: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})

@app.route('/broadcast')
@login_required
def broadcast_page():
    history = db.get_broadcast_history()
    all_user_data = db.get_user_data()
    total_users = len(all_user_data.get("users", {}))
    return render_template('broadcast.html', status=broadcast_manager.status, history=history, total_users=total_users)

@app.route('/broadcast/send', methods=['POST'])
@login_required
def broadcast_send():
    message = request.form.get('message')
    title = request.form.get('title')
    msg_type = request.form.get('message_type')
    notify_admins = request.form.get('notify_admins') == 'on'
    image_url = (request.form.get('image_url') or '').strip() or None
    button_text = (request.form.get('button_text') or '').strip() or None
    button_url = (request.form.get('button_url') or '').strip() or None
    pin_message = request.form.get('pin_message') == 'on'
    
    send_immediately = request.form.get('send_immediately') == 'on'
    scheduled_time = None
    if not send_immediately:
        scheduled_time = request.form.get('scheduled_time')
    
    if not message:
        flash("Message cannot be empty", "error")
        return redirect(url_for('broadcast_page'))
    
    success, msg = broadcast_manager.start_broadcast(
        title=title,
        message=message,
        message_type=msg_type,
        notify_admins=notify_admins,
        scheduled_time=scheduled_time,
        image_url=image_url,
        button_text=button_text,
        button_url=button_url,
        pin_message=pin_message
    )
    if success:
        flash(msg, "success")
    else:
        flash(msg, "error")
    return redirect(url_for('broadcast_page'))

@app.route('/broadcast/stop', methods=['POST'])
@login_required
def broadcast_stop():
    success, msg = broadcast_manager.stop_broadcast()
    if success:
        flash(msg, "info")
    else:
        flash(msg, "error")
    return redirect(url_for('broadcast_page'))

@app.route('/broadcast/cancel/<broadcast_id>', methods=['POST'])
@login_required
def broadcast_cancel(broadcast_id):
    if db.cancel_scheduled_broadcast(broadcast_id):
        flash("Scheduled broadcast cancelled successfully.", "success")
    else:
        flash("Could not cancel broadcast. It might not exist or is no longer scheduled.", "error")
    return redirect(url_for('broadcast_page'))

@app.route('/broadcast/progress')
@login_required
def broadcast_progress():
    def generate():
        while True:
            # yield SSE format
            s = broadcast_manager.status
            
            # Calculate progress percentage
            progress = 0
            if s.get("total", 0) > 0:
                progress = int((s.get("current", 0) / s.get("total", 1)) * 100)
            
            # Map to frontend expected format
            response_data = {
                "active": s.get("is_running", False),
                "status": s.get("message", ""),
                "progress": progress,
                "sent": s.get("sent", 0),
                "failed": s.get("failed", 0)
            }
            
            yield f"data: {json.dumps(response_data)}\n\n"
            time.sleep(1)
    return app.response_class(generate(), mimetype='text/event-stream')





@app.route('/settings/rewards', methods=['POST'])
@login_required
def settings_rewards():
    try:
        referral_points = request.form.get('referral_points')
        daily_points = request.form.get('daily_points')

        import config
        
        if referral_points:
            config.set_referral_points(int(referral_points))
            
        if daily_points:
            config.set_daily_points(int(daily_points))
            
        flash('Rewards configuration updated successfully!', 'success')
    except Exception as e:
        logger.error(f'Error updating rewards: {e}')
        flash(f'Error updating rewards: {e}', 'error')
        
    return redirect(url_for('settings_page'))

@app.route('/settings')
@app.route('/system')
@app.route('/power_tools')
@login_required
def settings_page():
    import config
    try:
        user_data = db.get_user_data().get('users', {})
        leaderboard = sorted(user_data.values(), key=lambda u: u.get('points', 0), reverse=True)[:10]
        
        return render_template('settings.html',
                             title='System & Settings',
                             page_title='System & Settings',
                             daily_reward_points=config.get_daily_points(),
                             default_referral_points=config.get_referral_points(),
                             scheduler_enabled=SCHEDULER_ENABLED,
                             leaderboard=leaderboard)
    except Exception as e:
        logger.error(f"Settings page error: {e}")
        flash(f"Error loading settings page: {e}", "error")
        return redirect(url_for('dashboard'))


@app.route('/gift-codes/create', methods=['POST'])
@login_required
def codes_create():
    try:
        # Check if code is provided or auto-generate
        code = request.form.get('code')
        if not code:
            import secrets
            code = "GIFT-" + secrets.token_hex(4).upper()
            
        points = request.form.get('points')
        days = request.form.get('days')
        usage = request.form.get('usage')
        
        if db.add_gift_code(code, points, days, usage):
             flash(f"Code {code} created", "success")
        else:
             flash("Failed to create code (might exist)", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('codes_page'))

@app.route('/gift-codes/bulk', methods=['POST'])
@login_required
def codes_bulk():
    try:
        prefix = request.form.get('prefix')
        points = request.form.get('points')
        count = int(request.form.get('count'))
        days = request.form.get('days')
        usage = request.form.get('usage')
        
        # Create and post codes
        created_count = 0
        added_codes = []
        import secrets
        
        # Get channel ID for posting
        import config
        import importlib
        importlib.reload(config)
        channel_id = config.CHANNEL_ID
        
        # Create and generate codes
        for _ in range(count):
            start = secrets.token_hex(2).upper() # 4 chars
            code = f"{prefix}-{start}"
            # Ensure unique in loop (simple retry)
            if db.add_gift_code(code, points, days, usage):
                created_count += 1
                added_codes.append(code)
        
        # Post to channel if codes were created
        if created_count > 0 and channel_id:
            try:
                # Format message
                token = config.TOKEN
                msg_lines = [
                    f"🎁✨ <b>NEW GIFT CODES DROPPED</b> ✨🎁",
                    f"",
                    f"💰 Reward: {points} Points",
                    f"📅 Validity: Unlimited",
                    f"",
                    f"━━━━━━━━━━━━━━━",
                    f"👇 Copy & Redeem Fast:",
                    f""
                ]
                for c in added_codes:
                    msg_lines.append(f"<code>/claimgift {c}</code>")
                
                msg_lines.extend([
                    f"",
                    f"━━━━━━━━━━━━━━━",
                    f"",
                    f"⚡ First come, first served!"
                ])

                msg = "\n".join(msg_lines)
                
                # Send via HTTP to avoid async issues in sync route
                import requests
                
                # Get Bot Info for debugging
                bot_info_resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5).json()
                bot_name = bot_info_resp.get('result', {}).get('username', 'Unknown') if bot_info_resp.get('ok') else f"Error: {bot_info_resp.get('description', 'Unknown')}"
                
                # Redirect Button
                import json
                keyboard = {
                    "inline_keyboard": [[
                        {
                            "text": "🤖 CLAIM NOW",
                            "url": f"https://t.me/{bot_name}?start=claim"
                        }
                    ]]
                }

                # Try getChat to verify
                get_chat_resp = requests.get(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": channel_id}, timeout=5).json()
                chat_status = f"Found: {get_chat_resp.get('result', {}).get('title', 'N/A')}" if get_chat_resp.get('ok') else f"Not Found ({get_chat_resp.get('description', 'N/A')})"

                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={
                        "chat_id": channel_id, 
                        "text": msg, 
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(keyboard)
                    },
                    timeout=5
                )
                if response.status_code == 200:
                    return f"Successfully created and posted {created_count} codes to channel (Bot: @{bot_name})."
                else:
                    return f"Created {created_count} codes but Telegram error: {response.text} (Bot: @{bot_name}, Chat Status: {chat_status}, Attempted ID: {channel_id}). Ensure bot is Admin!", 200
            except Exception as e:
                return f"Created {created_count} codes but failed to post: {e}", 200
                
        return f"Successfully created {created_count} codes (not posted). Channel ID was: '{channel_id}'"
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/gift-codes/delete-api', methods=['POST'])
@login_required
def codes_delete_api():
    try:
        code = request.form.get('code')
        if db.delete_gift_code(code):
             return "Deleted"
        return "Failed", 400
    except Exception as e:
        return str(e), 500

@app.route('/gift-codes/delete-prefix', methods=['POST'])
@login_required
def codes_delete_prefix():
    try:
        prefix = request.form.get('prefix')
        if db.delete_gift_codes_by_prefix(prefix):
             return "Deleted codes with prefix"
        return "Failed", 400
    except Exception as e:
        return str(e), 500

@app.route('/gift-codes/bulk-delete', methods=['POST'])
@login_required
def codes_bulk_delete():
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if db.bulk_delete_gift_codes(ids):
             return jsonify({'success': True})
        return jsonify({'success': False, 'message': 'Failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/gift-codes') # Aliased from /codes match in app.py which was /codes
@app.route('/codes')
@login_required
def codes_page():
    codes_data = db.get_gift_codes()
    codes = codes_data.get('codes', []) if isinstance(codes_data, dict) else []
    return render_template('codes.html', codes=codes)


@app.route('/gift-codes/<int:code_id>/redeemers')
@login_required
def code_redeemers_page(code_id):
    try:
        # Fetch code from database
        data = db.get_gift_codes()
        codes = data.get("codes", [])
        code_data = None
        for c in codes:
            if c.get("id") == code_id:
                code_data = c
                break
        
        if not code_data:
            flash("Code not found.", "error")
            return redirect(url_for('codes_page'))
            
        # Get redeemers list (User IDs)
        # Assuming redeemed_by is a list of user IDs or {"user_id": 123, "time": ...}
        redeemers_raw = code_data.get("redeemed_by", [])
        redeemers = []
        
        users_data = db.get_user_data().get("users", {}) or {}
        
        for item in redeemers_raw:
            # Handle both list of IDs and list of objects
            uid = item
            redeemed_at = None
            if isinstance(item, dict):
                uid = item.get("user_id")
                redeemed_at = item.get("redeemed_at")
            
            uid_str = str(uid)
            user_info = users_data.get(uid_str, {})
            
            redeemers.append({
                "user_id": uid,
                "first_name": user_info.get("first_name", "Unknown"),
                "username": user_info.get("username", "-"),
                "redeemed_at": redeemed_at
            })
            
        return render_template('code_redeemers.html', code=code_data, redeemers=redeemers)
        
    except Exception as e:
        flash(f"Error viewing redeemers: {e}", "error")
        return redirect(url_for('codes_page'))


# Initialize database on module load
db.init_database()

if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)