# 🚀 Lovable Pro Keygen, Direct Zip Download & Database Protection Updates

This document contains **all the exact code snippets and changes** made for the 127HUB Lovable Pro License generation, multi-phase progress animation, on-the-fly `.ZIP` download, group rate-limit fix, and database crash-proofing.

---

## 1. `config.py` Additions
Add the following configuration lines at the bottom of `config.py`:

```python
# 127HUB Reseller License Keygen Configuration
KEYGEN_API_URL = os.getenv("KEYGEN_API_URL", "https://ai.127hub.com/api/reseller/generate")
KEYGEN_API_KEY = os.getenv("KEYGEN_API_KEY", "127HUB-RES-A3B907130A1D98F987F55930728C5442")
KEYGEN_KEY_TYPE = os.getenv("KEYGEN_KEY_TYPE", "@REFER127BOT")
KEYGEN_DURATION_DAYS = int(os.getenv("KEYGEN_DURATION_DAYS", "30"))
KEYGEN_MAX_DEVICES = int(os.getenv("KEYGEN_MAX_DEVICES", "1"))
KEYGEN_STATS_URL = os.getenv("KEYGEN_STATS_URL", "https://ai.127hub.com/api/reseller/stats")
```

---

## 2. `handlers.py` Keygen Handler with Progress Animation & ZIP Dispatch
Replace the `lovable_1month` block in `handlers.py` (inside callback query router):

```python
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
```

---

## 3. `database.py` Atomic Save & Crash-Proof Protection
Replace `get_user_data` and `save_user_data` functions in `database.py`:

```python
# User data operations
def get_user_data(user_id: int = None) -> Dict:
    """Get all user data or specific user data with automatic fallback backup support."""
    data = None
    with data_lock:
        try:
            if os.path.exists(USER_DATA_FILE):
                with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
        except Exception as e:
            logger.error(f"Error reading primary user data: {e}. Trying backup...")
            # Try backup
            bak_file = f"{USER_DATA_FILE}.bak"
            if os.path.exists(bak_file):
                try:
                    with open(bak_file, 'r', encoding='utf-8') as f_bak:
                        data = json.load(f_bak)
                    logger.info("Successfully loaded user data from backup file.")
                except Exception as e_bak:
                    logger.critical(f"Error reading backup user data: {e_bak}")

    if not data or not isinstance(data, dict) or "users" not in data:
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
        try:
            # Wipe protection: Don't allow saving empty/near-empty data if existing DB is populated
            if os.path.exists(USER_DATA_FILE) and len(data.get("users", {})) < 5:
                try:
                    with open(USER_DATA_FILE, 'r', encoding='utf-8') as f_chk:
                        existing = json.load(f_chk)
                        if len(existing.get("users", {})) > 50:
                            logger.critical(f"BLOCKED potential data loss! Attempted to save {len(data.get('users', {}))} users over {len(existing.get('users', {}))} existing users.")
                            return False
                except Exception:
                    pass

            tmp_file = f"{USER_DATA_FILE}.tmp"
            bak_file = f"{USER_DATA_FILE}.bak"
            
            # Write to temporary file first
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())

            # Update backup if primary exists
            if os.path.exists(USER_DATA_FILE):
                try:
                    if os.path.exists(bak_file):
                        bak2_file = f"{USER_DATA_FILE}.bak2"
                        if os.path.exists(bak2_file):
                            os.remove(bak2_file)
                        os.rename(bak_file, bak2_file)
                    os.replace(USER_DATA_FILE, bak_file)
                except Exception as e_bak:
                    logger.debug(f"Notice updating user_data backup: {e_bak}")

            # Atomic replace
            os.replace(tmp_file, USER_DATA_FILE)
            return True
        except Exception as e:
            logger.error(f"Error saving user data: {e}")
            return False
```

---

## 4. `utils.py` Group Restriction Protection
In `utils.py`, ensure `handle_group_restriction` suppresses group message spam:

```python
async def handle_group_restriction(update: Update, context: CallbackContext) -> bool:
    """
    Check if the update is from a group chat and handle restrictions.
    Returns True if the message was handled and should be stopped, False otherwise.
    """
    if not update.effective_chat:
        return False
        
    chat_type = update.effective_chat.type
    if chat_type in ['group', 'supergroup']:
        if update.message and update.message.text:
            text = update.message.text.strip().lower()
            if text in ['/id', '!id', '/groupid', '!groupid']:
                return False
        # Suppress all general private workflows and membership checks inside groups
        return True
    return False
```
