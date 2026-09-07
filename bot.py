import logging
import logging.handlers
import os
import time
from threading import Thread
import asyncio
import sys
from pathlib import Path
import schedule
import json
import requests
import datetime

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ChatJoinRequestHandler
)

import database as db
from config import TOKEN, WEBHOOK_URL, WEBHOOK_PORT, WEB_ADMIN_USERNAME, WEB_ADMIN_PASSWORD
import handlers
import user_handlers


# Import web admin for integrated startup
# Import web admin for integrated startup
from app import app as web_app, set_bot_instance, bot_status

logger = logging.getLogger(__name__)

# Global bot instance for sync
global_bot_instance = None
# Sync status_dict with app.py's bot_status
# Global status and port
status_dict = bot_status
CURRENT_WEB_PORT = 5000  # Default, will be updated by start_web_admin
# Add missing keys required by bot.py
if "startup_broadcast_sent" not in status_dict:
    status_dict["startup_broadcast_sent"] = False
if "shutdown_broadcast_sent" not in status_dict:
    status_dict["shutdown_broadcast_sent"] = False
def _notify_admins_http(text: str, parse_mode: str = "HTML", pin: bool = False) -> None:
    """Send a message to all admins via Telegram HTTP API.
    Safe to call from any thread and during shutdown.
    """
    try:
        from config import TOKEN as CFG_TOKEN, ADMIN_IDS as CFG_ADMINS
        # Merge static and dynamic admins
        effective_admins = list({*(CFG_ADMINS or [])})
        for admin_id in effective_admins:
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{CFG_TOKEN}/sendMessage",
                    data={"chat_id": admin_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True},
                    timeout=8,
                )
                if pin and response.status_code == 200:
                    try:
                        msg_data = response.json()
                        message_id = msg_data.get("result", {}).get("message_id")
                        if message_id:
                            requests.post(
                                f"https://api.telegram.org/bot{CFG_TOKEN}/pinChatMessage",
                                data={"chat_id": admin_id, "message_id": message_id},
                                timeout=8,
                            )
                    except Exception:
                        pass
            except BaseException:
                continue
    except BaseException:
        pass


def _broadcast_to_all_users_http(text: str, parse_mode: str = "HTML") -> None:
    """Broadcast a message to all non-banned users via Telegram HTTP API.
    Safe during startup/shutdown. Best-effort with simple throttling.
    """
    try:
        from config import TOKEN as CFG_TOKEN
        all_user_data = db.get_user_data()
        users = (all_user_data or {}).get("users", {})
        if not users:
            return
        api_url = f"https://api.telegram.org/bot{CFG_TOKEN}/sendMessage"
        sent = 0
        for user_id_str, u in users.items():
            try:
                if u.get("banned"):
                    continue
                user_id = int(user_id_str)
                requests.post(
                    api_url,
                    data={
                        "chat_id": user_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                    timeout=8,
                )
                sent += 1
                # light throttle to reduce rate limits
                if sent % 20 == 0:
                    time.sleep(0.25)
            except BaseException:
                continue
    except BaseException:
        pass



def start_heartbeat():
    """Periodically write bot status to a file."""
    def heartbeat():
        while True:
            try:
                with open("bot_status.json", "w") as f:
                    json.dump(status_dict, f)
                time.sleep(5)  # Update every 5 seconds
            except Exception as e:
                logger.error(f"Error in heartbeat thread: {e}")
                time.sleep(10)

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    logger.info("❤️ Bot heartbeat started")

def configure_file_logging():
    """Attach a rotating file handler to the root logger for /logs page."""
    try:
        log_filename = 'bot.log'
        root_logger = logging.getLogger()
        # Avoid duplicate handlers
        for h in root_logger.handlers:
            if isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, 'baseFilename', '').endswith(log_filename):
                return
            if isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith(log_filename):
                return

        file_handler = logging.handlers.RotatingFileHandler(
            log_filename, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

        # Also attach to werkzeug to capture web requests in the same file
        try:
            werk_logger = logging.getLogger('werkzeug')
            werk_logger.addHandler(file_handler)
        except Exception:
            pass
    except Exception as e:
        # Fall back silently; logs will still go to stdout
        logging.getLogger(__name__).error(f"Failed to configure file logging: {e}")

def start_web_sync_monitor():
    """Start monitoring for web panel changes"""
    def monitor_changes(bot_instance):
        sync_file = "web_changes_sync.flag"
        last_check = 0
        
        while True:
            try:
                # Check for sync file changes
                if os.path.exists(sync_file):
                    file_time = os.path.getmtime(sync_file)
                    if file_time > last_check:
                        last_check = file_time
                        logger.info("🔄 Web panel changes detected - refreshing bot data...")
                        
                        # Refresh database connections/cache
                        # Force reload of categories and other data
                        try:
                            # Clear any cached data if your database has caching
                            # Re-initialize database connections if needed
                            db.init_database()
                    
                            logger.info("✅ Bot data refreshed successfully")
                        except Exception as e:
                            logger.error(f"❌ Error refreshing bot data: {e}")
                            
                time.sleep(2)  # Check every 2 seconds
            except Exception as e:
                logger.error(f"Error in sync monitor: {e}")
                time.sleep(5)
    
    # We need to pass the bot instance to the monitor function
    # This will be called from setup_bot with the bot instance
    return monitor_changes

def start_connectivity_monitor():
    """Monitor Telegram API reachability to detect internet disconnect/reconnect.
    Sends a one-time message to users/admins on disconnect (best-effort), and a
    one-time recovery message on reconnect. Runs in a daemon thread.
    """
    def monitor():
        was_online = True
        consecutive_failures = 0
        status_dict["network_online"] = True
        while True:
            try:
                # Lightweight health check
                r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=5)
                online = bool(r.ok)
            except Exception:
                online = False

            if online:
                if not was_online:
                    # Transition: offline -> online
                    status_dict["network_online"] = True
                    try:
                        recovery_msg = (
                            "✅ <b>Connection Restored</b>\n\n"
                            "We are back online now.\n"
                            "Thanks for staying with us! ✨"
                        )
                        _broadcast_to_all_users_http(recovery_msg)
                    except Exception:
                        pass
                was_online = True
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                # Consider offline after a few consecutive failures to avoid flapping
                if was_online and consecutive_failures >= 3:
                    was_online = False
                    status_dict["network_online"] = False
                    # Attempt to notify admins (and users best-effort)
                    try:
                        admin_msg = (
                            "⚠️ <b>Connectivity Issue Detected</b>\n\n"
                            "Bot appears to have lost internet connectivity."
                        )
                        _notify_admins_http(admin_msg)
                    except Exception:
                        pass
                    try:
                        maint_msg = (
                            "⚠️ <b>Temporary Network Issue</b>\n\n"
                            "We are experiencing internet connectivity problems.\n"
                            "Some features may be unavailable.\n\n"
                            "We will notify you once we're back online."
                        )
                        _broadcast_to_all_users_http(maint_msg)
                    except Exception:
                        pass

            time.sleep(10)

    t = Thread(target=monitor, daemon=True)
    t.start()
    logger.info("🌐 Connectivity monitor started")
    return t

def start_web_admin():
    """Start the web admin panel in a separate thread"""
    global CURRENT_WEB_PORT
    try:
        from config import FLASK_PORT
        import socket
        
        # Find available port
        def find_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                s.listen(1)
                port = s.getsockname()[1]
            return port
        
        # Try FLASK_PORT first, then fallback to others if needed
        web_port = None
        ports_to_try = [FLASK_PORT] + list(range(5002, 5010))
        for port in ports_to_try:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    web_port = port
                    break
            except OSError:
                continue
        
        if web_port is None:
            web_port = find_free_port()
        
        CURRENT_WEB_PORT = web_port
        
        # Output access information (ASCII-safe for Windows consoles)
        logger.info("\n" + "="*60)
        logger.info("TELEGRAM BOT & WEB ADMIN PANEL STARTED")
        logger.info("="*60)
        logger.info("Telegram Bot: Running...")
        logger.info(f"Web Admin Panel: http://localhost:{web_port}")
        logger.info("Login Credentials:")
        logger.info(f"   Username: {WEB_ADMIN_USERNAME}")
        logger.info(f"   Password: {WEB_ADMIN_PASSWORD}")
        logger.info("="*60)
        logger.info("Open the web link in your browser to access admin panel")
        logger.info("Web panel changes will auto-sync to bot")
        logger.info("="*60 + "\n")
        
        # web app is now started in main.py's main thread
        
        # Start sync monitor
        start_web_sync_monitor()

        # Notify admins that bot + web panel have started (with login details)
        try:
            panel_url = f"http://localhost:{web_port}"
            # Determine LAN accessible URL
            try:
                import socket as _sock
                _s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
                _s.connect(("8.8.8.8", 80))
                lan_ip = _s.getsockname()[0]
                _s.close()
            except Exception:
                lan_ip = None
            lan_url = f"http://{lan_ip}:{web_port}" if lan_ip else None
            # If you have configured public URL, prefer it (optional)
            from config import WEBHOOK_URL as CFG_WEBHOOK
            if CFG_WEBHOOK:
                # Not strictly the same as panel URL, but keep localhost for panel by default
                pass
            # Try to include bot username link
            try:
                bot_info = web_app.config.get('bot_username') if hasattr(web_app, 'config') else None
            except Exception:
                bot_info = None
            # Build message with both Localhost and LAN URLs
            startup_lines = [
                "✅ <b>Bot Started</b>",
                "",
                f"🌐 <b>Web Panel (Local):</b> <a href=\"{panel_url}\">{panel_url}</a>",
            ]
            if lan_url:
                startup_lines.append(f"🌐 <b>Web Panel (LAN):</b> <a href=\"{lan_url}\">{lan_url}</a>")
            startup_lines.append(f"🔐 <b>Login:</b> Username: <code>{WEB_ADMIN_USERNAME}</code> | Password: <code>{WEB_ADMIN_PASSWORD}</code>")
            try:
                from utils import get_bot_username as _get_bot_username
                # Use a direct API call via application bot not available here; fallback to HTTP link with token hidden
                # So we will just show a generic link hint
                startup_lines.append("🤖 <b>Bot:</b> Open your bot in Telegram and use /og for admin help")
            except Exception:
                pass
            startup_lines.append(f"🕒 <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}")
            startup_msg = "\n".join(startup_lines)
            _notify_admins_http(startup_msg, pin=True)
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"Error starting web admin: {e}")
        logger.error("Failed to start web admin panel")

def setup_bot(status_dict):
    """Set up and run the Telegram bot"""
    try:
        # Ensure a dedicated event loop exists in this thread
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Initialize database
        db.init_database()

            
        logger.info(f"Bot token: {TOKEN[:5]}...{TOKEN[-5:]}")
        
        # Create application with increased timeouts
        from telegram.request import HTTPXRequest
        request = HTTPXRequest(connection_pool_size=8, read_timeout=60, write_timeout=60, connect_timeout=60)
        
        async def post_init(app):
            from telegram import MenuButtonDefault
            try:
                await app.bot.set_chat_menu_button(menu_button=MenuButtonDefault())
                logger.info("✅ Global MenuButton set to default successfully")
            except Exception as e:
                logger.error(f"Failed to set global menu button: {e}")
                
        builder = Application.builder().token(TOKEN).request(request).post_init(post_init)
        try:
            from telegram.ext import AIORateLimiter
            builder = builder.rate_limiter(AIORateLimiter())
        except (ImportError, RuntimeError, Exception) as e_lim:
            logger.debug(f"AIORateLimiter optional dependency skipped: {e_lim}")
            
        application = builder.build()
        
        # Store admin IDs in bot_data for access in error handler
        from config import ADMIN_IDS
        application.bot_data['admin_ids'] = list({*(ADMIN_IDS or [])})
        
        # Set bot instance for web admin real-time sync
        set_bot_instance(application.bot)
        
        # Register handlers
        register_handlers(application)
        
        # Set up error handler
        application.add_error_handler(handlers.error_handler)
        
        # Start the web sync monitor with bot instance
        monitor_function = start_web_sync_monitor()
        sync_thread = Thread(target=monitor_function, args=(application.bot,), daemon=True)
        sync_thread.start()
        logger.info("🔄 Web panel sync monitor started")

        # Start connectivity monitor
        start_connectivity_monitor()
        
        # Update status
        status_dict["is_running"] = True
        status_dict["start_time"] = int(time.time())

        # Notify admins that bot + web panel have started
        try:
            from config import FLASK_PORT
            panel_url = f"http://localhost:{FLASK_PORT}"
            # Determine LAN accessible URL
            try:
                import socket as _sock
                _s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
                _s.connect(("8.8.8.8", 80))
                lan_ip = _s.getsockname()[0]
                _s.close()
            except Exception:
                lan_ip = None
            lan_url = f"http://{lan_ip}:{FLASK_PORT}" if lan_ip else None
            
            # Build message with both Localhost and LAN URLs
            import time as _time
            startup_lines = [
                "✅ <b>Bot Started</b>",
                "",
                f"🌐 <b>Web Panel (Local):</b> <a href=\"{panel_url}\">{panel_url}</a>",
            ]
            if lan_url:
                startup_lines.append(f"🌐 <b>Web Panel (LAN):</b> <a href=\"{lan_url}\">{lan_url}</a>")
            startup_lines.append(f"🔐 <b>Login:</b> Username: <code>{WEB_ADMIN_USERNAME}</code> | Password: <code>{WEB_ADMIN_PASSWORD}</code>")
            startup_lines.append("🤖 <b>Bot:</b> Open your bot in Telegram and use /og for admin help")
            startup_lines.append(f"🕒 <b>Time:</b> {_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            import asyncio as _asyncio
            def _send_admin_startup():
                try:
                    time.sleep(2) # Brief wait for network readiness
                    from config import WEB_APP_URL
                    if WEB_APP_URL:
                        startup_lines.append(f"🌍 <b>Web Panel (Domain):</b> <a href=\"{WEB_APP_URL}\">{WEB_APP_URL}</a>")
                    msg = "\n".join(startup_lines)
                    logger.info("Sending bot startup notification to admins...")
                    _notify_admins_http(msg, pin=True)
                    logger.info("📢 Startup broadcast sent to admins.")
                except Exception as e:
                    logger.error(f"Error in admin startup notification: {e}")
            
            from threading import Thread as _Thread
            _Thread(target=_send_admin_startup, daemon=True).start()
        except Exception as e:
            logger.error(f"Error sending startup broadcast: {e}")

        # --- JobQueue Scheduler Setup ---
        # Define wrappers for scheduler functions
        async def job_check_membership(context):
            from scheduler import check_channel_membership
            await check_channel_membership(context.bot)

        async def job_daily_reminders(context):
            from scheduler import send_daily_reminders
            await send_daily_reminders(context.bot)
            
        async def job_cleanup_notifications(context):
            from scheduler import cleanup_old_notifications
            await cleanup_old_notifications()

        # Register jobs
        jq = application.job_queue
        if jq:
            # Check membership every 30 mins (reduced to save API calls)
            jq.run_repeating(job_check_membership, interval=1800, first=30, name="check_membership")
            # Daily reminders at 09:00
            import datetime as _dt
            jq.run_daily(job_daily_reminders, time=_dt.time(hour=9, minute=0, tzinfo=None), name="daily_reminders") 
            # Cleanup notifications daily at 02:00
            jq.run_daily(job_cleanup_notifications, time=_dt.time(hour=2, minute=0, tzinfo=None), name="cleanup_notifications")
            logger.info("✅ JobQueue scheduler configured")
        else:
            logger.error("❌ JobQueue not available in application")

        # Start polling or webhook based on environment
        if WEBHOOK_URL:
            # Use webhook
            status_dict["webhook_mode"] = True
            application.run_webhook(
                listen="0.0.0.0",
                port=WEBHOOK_PORT,
                url_path=TOKEN,
                webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
            )
            logger.info(f"Bot started with webhook mode at {WEBHOOK_URL}")
        else:
            # Use polling
            status_dict["webhook_mode"] = False
            application.run_polling(stop_signals=None, close_loop=False)
            logger.info("Bot started with polling mode")

        # Note: Post-start broadcast logic handled above.
        
        # Don't use application.idle() in a thread as it causes signal handler issues
        # Just keep the thread running
        while True:
            time.sleep(10)
            
    except Exception as e:
        logger.error(f"Error in setup_bot: {e}", exc_info=True)
        status_dict["is_running"] = False
        status_dict["webhook_mode"] = False

def register_handlers(application):
    """Register all handlers: user commands, admin commands, and callbacks."""
    # Register all user command handlers
    user_handlers.setup_user_handlers(application)
    
    # Core callbacks and message handlers
    application.add_handler(CallbackQueryHandler(handlers.handle_callback_query))
    application.add_handler(ChatJoinRequestHandler(handlers.handle_chat_join_request))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message, block=False))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.handle_message))

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)
    # Ensure logs also go to bot.log for the web log viewer
    configure_file_logging()
    # Start auto-reloader (process-level) for dev convenience
    try:
        from config import AUTO_RELOAD as _AR
    except Exception:
        _AR = True
    if _AR:
        def _watch_and_reload():
            try:
                root = Path(__file__).resolve().parent
                exclude_dirs = {'venv', '.git', '__pycache__'}
                exts = {'.py', '.html', '.css', '.js'}
                def snapshot():
                    mt = {}
                    for p in root.rglob('*'):
                        try:
                            if not p.is_file():
                                continue
                            if any(part in exclude_dirs for part in p.parts):
                                continue
                            if p.suffix.lower() not in exts:
                                continue
                            mt[str(p)] = p.stat().st_mtime
                        except Exception:
                            continue
                    return mt
                prev = snapshot()
                while True:
                    time.sleep(1.0)
                    cur = snapshot()
                    if cur != prev:
                        logger.info("♻️  Detected code/template change. Restarting process...")
                        # Flush logs before restart
                        for h in logging.getLogger().handlers:
                            try:
                                h.flush()
                            except Exception:
                                pass
                        import subprocess
                        subprocess.Popen([sys.executable] + sys.argv, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                        os._exit(0)
                    prev = cur
            except Exception as e:
                logger.error(f"Auto-reload watcher error: {e}")
        Thread(target=_watch_and_reload, daemon=True).start()
    
    try:
        logger.info("Starting Telegram Bot and Web Admin Panel...")
        
        # Start bot heartbeat
        start_heartbeat()
        
        # Start web admin panel in a separate thread
        web_thread = Thread(target=start_web_admin, daemon=True)
        web_thread.start()
        
        # Give web server a moment to start
        time.sleep(2)
        
        # Start telegram bot
        setup_bot(status_dict)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n⏹️  Bot and Web Admin Panel stopped by user")
        # User maintenance broadcast disabled (admins will still be notified below)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
    finally:
        # Clean up status file on exit
        if os.path.exists("bot_status.json"):
            os.remove("bot_status.json")
        logger.info("Bot shutdown complete")
        print("🔄 Shutdown complete")
        # Notify admins about shutdown (user broadcast disabled)
        try:
            uptime = 0
            if status_dict.get("start_time"):
                uptime = int(time.time()) - int(status_dict.get("start_time"))
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            seconds = uptime % 60
            stop_msg = (
                f"⛔ <b>Bot Stopped</b>\n\n"
                f"⏱️ <b>Uptime:</b> {hours}h {minutes}m {seconds}s\n"
                f"🕒 <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            _notify_admins_http(stop_msg)
        except BaseException:
            pass
