# 🔑 Keymint API Integration Guide (License & Admin Generator)

This document contains complete documentation, API endpoints, request/response formats, and ready-to-use Python snippets for **Keymint** (`https://keygen.eklas.dev/`).

---

## 📌 1. Overview

* **Base URL:** `https://keygen.eklas.dev`
* **Content-Type:** `application/json`
* **Authentication:** No API key required in headers (handled server-side).
* **Rate Limits:** ~10 requests per 10 minutes.

---

## 🚀 2. Endpoints Reference

### A. License Key Generator

Creates a production-ready license key with customizable plan, duration, and activations.

* **Endpoint:** `POST https://keygen.eklas.dev/api/license`
* **Headers:**
  ```http
  Content-Type: application/json
  ```
* **Request Body (JSON):**
  ```json
  {
    "plan": "Pro",
    "durationValue": 30,
    "durationUnit": "day",
    "maxActivations": 5
  }
  ```

#### Parameters:
| Field | Type | Required | Allowed Values / Description |
| :--- | :---: | :---: | :--- |
| `plan` | `string` | Yes | `"Pro"`, `"Business"`, `"Enterprise"`, `"Starter"` |
| `durationValue` | `number` | Yes | Number of time units (e.g. `1`, `7`, `30`, `365`) |
| `durationUnit` | `string` | Yes | `"day"`, `"week"`, `"month"`, `"year"` |
| `maxActivations`| `number` | Yes | Max allowed devices/activations (`1` - `10000`) |

* **Success Response (200 OK):**
  ```json
  {
    "status": "active",
    "license_key": "EKLAS-HELY-EPV4-XYJB-HCP2",
    "plan": "Pro",
    "expires_at": "2026-09-17T11:42:10.583Z"
  }
  ```

---

### B. Admin Account Generator

Generates a secure administrative username and password with instant access.

* **Endpoint:** `POST https://keygen.eklas.dev/api/admin-account`
* **Headers:**
  ```http
  Content-Type: application/json
  ```
* **Request Body (JSON):**
  ```json
  {
    "role": "admin"
  }
  ```

#### Parameters:
| Field | Type | Required | Description |
| :--- | :---: | :---: | :--- |
| `role` | `string` | Yes | Target account role (`"admin"`) |

* **Success Response (200 OK):**
  ```json
  {
    "username": "38347984",
    "password": "6GNJr5wmfKKvhM",
    "role": "admin",
    "panel_url": "https://io.eklas.dev"
  }
  ```

---

## 💻 3. cURL Examples

### Generate License:
```bash
curl -X POST "https://keygen.eklas.dev/api/license" \
     -H "Content-Type: application/json" \
     -d '{
       "plan": "Pro",
       "durationValue": 30,
       "durationUnit": "day",
       "maxActivations": 5
     }'
```

### Generate Admin Account:
```bash
curl -X POST "https://keygen.eklas.dev/api/admin-account" \
     -H "Content-Type: application/json" \
     -d '{"role": "admin"}'
```

---

## 🐍 4. Python Implementation Snippets

### Synchronous (`requests`):
```python
import requests

BASE_URL = "https://keygen.eklas.dev"

def generate_license(plan="Pro", duration_value=30, duration_unit="day", max_activations=5):
    """
    Generate a new license key.
    Returns: dict with 'license_key', 'plan', 'expires_at' or None on failure.
    """
    url = f"{BASE_URL}/api/license"
    payload = {
        "plan": plan,
        "durationValue": duration_value,
        "durationUnit": duration_unit,
        "maxActivations": max_activations
    }
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if res.status_code == 200:
            return res.json()
        return {"error": res.text}
    except Exception as e:
        return {"error": str(e)}

def generate_admin():
    """
    Generate a new admin account credentials.
    Returns: dict with 'username', 'password', 'panel_url' or None on failure.
    """
    url = f"{BASE_URL}/api/admin-account"
    payload = {"role": "admin"}
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if res.status_code == 200:
            return res.json()
        return {"error": res.text}
    except Exception as e:
        return {"error": str(e)}
```

---

### Asynchronous (`httpx` or `aiohttp` for Telegram Bot handlers):
```python
import httpx

BASE_URL = "https://keygen.eklas.dev"

async def async_generate_license(plan="Pro", duration_value=30, duration_unit="day", max_activations=5):
    url = f"{BASE_URL}/api/license"
    payload = {
        "plan": plan,
        "durationValue": duration_value,
        "durationUnit": duration_unit,
        "maxActivations": max_activations
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        if res.status_code == 200:
            return res.json()
        return None

async def async_generate_admin():
    url = f"{BASE_URL}/api/admin-account"
    payload = {"role": "admin"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        if res.status_code == 200:
            return res.json()
        return None
```

---

## 🤖 5. Telegram Bot Handler Integration Example

```python
# In user_handlers.py or handlers.py
async def genkey_command(update: Update, context: CallbackContext):
    """Admin command to generate a key on demand: /genkey [plan] [days]"""
    user_id = update.effective_user.id
    if not utils.is_admin(user_id):
        return

    plan = context.args[0] if context.args and len(context.args) > 0 else "Pro"
    days = int(context.args[1]) if context.args and len(context.args) > 1 else 30

    data = await async_generate_license(plan=plan, duration_value=days)
    if data and "license_key" in data:
        await update.message.reply_text(
            f"🔑 *New License Generated*\n\n"
            f"• Key: `{data['license_key']}`\n"
            f"• Plan: *{data['plan']}*\n"
            f"• Expires: `{data['expires_at']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Failed to generate license key.")
```
