<div align="center">

<!-- Cyber Dark OLED Header Banner -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,50:161b22,100:1a1b27&height=230&section=header&text=Telegram%20Distribution%20Engine&fontSize=48&fontAlignY=38&desc=Refer%20%26%20Earn%20Bot%20%7C%20Redeem%20Points%20System%20%7C%20Flask%20Web%20Dashboard&descAlignY=62&descAlign=50&fontColor=58a6ff&descColor=8b949e&animation=fadeIn" width="100%" alt="Project Header Banner"/>

<!-- Dynamic Glowing Neon Typing SVG -->
<a href="https://github.com/lusufer-rohit/refer-and-earn-telegram-bot-with-redeem-point-system">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=20&pause=1000&color=00F5FF&center=true&vCenter=true&width=650&lines=%E2%9E%A4+Enterprise+Refer+%26+Earn+Telegram+Bot+Architecture;%E2%9E%A4+Integrated+Flask+Web+Admin+Dashboard+with+Real-Time+Metrics;%E2%9E%A4+Thread-Safe+Atomic+Storage+with+Dual-Rolling+Backups;%E2%9E%A4+Automated+Multi-Threaded+Task+Scheduler+%26+Broadcaster" alt="Typing SVG" />
</a>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-000000?style=for-the-badge&logo=python&logoColor=00F5FF&labelColor=050811" alt="Python Version"/>
  <img src="https://img.shields.io/badge/Telegram_API-v22%20Async-000000?style=for-the-badge&logo=telegram&logoColor=26A5E4&labelColor=050811" alt="Telegram API"/>
  <img src="https://img.shields.io/badge/Flask-Admin_Panel-000000?style=for-the-badge&logo=flask&logoColor=white&labelColor=050811" alt="Flask Panel"/>
  <img src="https://img.shields.io/badge/Storage-Atomic%20JSON-000000?style=for-the-badge&logo=codefactor&logoColor=00ff88&labelColor=050811" alt="Storage"/>
  <img src="https://img.shields.io/badge/License-MIT-000000?style=for-the-badge&logo=open-source-initiative&logoColor=BD93F9&labelColor=050811" alt="License"/>
</p>

---

</div>

## 📌 Executive Architecture Summary

**Telegram OTT Distribution & Redeem Engine** is an asynchronous, high-throughput backend ecosystem combining an interactive Telegram user bot with an administrative **Flask Web Panel** and a background automation scheduler.

Engineered for reliable digital inventory distribution, referral commission ledgers, account exchanges, and scheduled channel broadcasts with **zero external DBMS overhead**.

```mermaid
%%{init: {'theme':'dark', 'themeVariables': {'darkMode': true, 'background': '#050811', 'primaryColor': '#0D1117', 'primaryBorderColor': '#00F5FF', 'lineColor': '#00F5FF', 'textColor': '#E0E0E0'}}}%%
flowchart TD
    subgraph Telegram_Network [Telegram Cloud Infrastructure]
        Client[Telegram Users]
        Channel[Broadcast Channels & Groups]
    end

    subgraph Core_Engine [Application Server]
        Bot[Async Telegram Bot Engine
python-telegram-bot v22]
        Web[Flask Web Admin Panel
Jinja2 + RESTful API]
        Sched[Multi-Threaded Scheduler
Task Health & Cleanup]
    end

    subgraph Persistence [Data & Security Layer]
        Lock[Thread RLock Manager]
        JSON[(Atomic JSON Engine
Primary .json)]
        Bak[(Dual Rolling Backups
.bak + .bak2)]
    end

    Client <-->|Commands / Inline Menus| Bot
    Bot <--> Lock
    Web <--> Lock
    Sched <--> Lock
    Lock <--> JSON
    JSON -.->|Atomic os.replace| Bak
    Sched -.->|Auto-Post Announcements| Channel
```

---

## ⚡ Core Systems & Feature Matrix

### 🤖 1. Asynchronous Telegram User Bot
- **Interactive Inline Navigation**: Dynamic keyboard markup with animated status visualizers (`animations.py`).
- **Referral & Points Engine**: Multi-tier referral tracking, anti-abuse checks, and automated daily reward streaks.
- **Digital Account Redemption**: Instant digital account drop with quota caps, cooldowns, and category filtering.
- **Promotional Gift Codes**: Generate and redeem usage-capped or time-limited bonus codes.
- **Account Exchange Pipeline**: Peer submission pipeline for account swaps requiring admin verification.

### 🎛️ 2. Flask Administrative Web Portal
- **Real-Time Analytics**: Visual dashboard tracking registered users, active drops, referral traffic, and system logs.
- **Account Inventory Manager**: Batch upload, categorize, inspect, and delete digital accounts.
- **Campaign Broadcaster**: HTML/Markdown broadcast engine targeting specific user segments or public channels.
- **Audit & Exchange Approval**: Approve or reject pending account submissions with direct DM notifications.

### 🛡️ 3. Fault-Tolerant Atomic Storage
- **Thread-Safe Concurrency**: Concurrency managed via re-entrant thread locks (`threading.RLock`) across simultaneous Web & Bot threads.
- **Crash-Proof Atomic Write Protocol**: Writes staging buffers (`.tmp`), flushes file descriptors (`fsync`), and atomically replaces disk pointers (`os.replace`).
- **Continuous Rolling Rotation**: Always maintains `.bak` (previous state) and `.bak2` (fallback state) to eliminate data loss.
- **Zero Hardcoded Secrets**: Complete `.env` decoupling prevents credential leakage.

---

## 🛠️ Technology Stack

| Domain | Technology | Purpose |
|---|---|---|
| **Language** | Python 3.11+ | Primary high-performance asynchronous runtime |
| **Bot Framework** | `python-telegram-bot` 22.2 | Async event loop, inline menus, callbacks |
| **Web Framework** | Flask 3.1.0 + Jinja2 | Administrative interface & REST API endpoints |
| **Persistence** | Atomic JSON Storage Engine | Low-latency storage with thread locks & backups |
| **Scheduler** | Python Multi-threading | Background verification, channel hygiene, sync |
| **Security** | Environment Decoupling | Complete separation of tokens, secrets, and data |

---

## 🚀 Quickstart & Setup Guide

### 1. Clone & Enter Directory
```bash
git clone git@github.com:lusufer-rohit/refer-and-earn-telegram-bot-with-redeem-point-system.git
cd refer-and-earn-telegram-bot-with-redeem-point-system
```

### 2. Configure Virtual Environment
```bash
python -m venv venv

# Windows (PowerShell / CMD)
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your secrets:
```bash
cp .env.example .env
```

```ini
# Telegram Bot Token from @BotFather
TOKEN=your_telegram_bot_token_here

# Base URL for Web Panel (no trailing slash)
WEB_APP_URL=https://your-domain.com

# Channel ID for logs/announcements
CHANNEL_ID=-100xxxxxxxxxx

# Admin IDs & Usernames
ADMIN_IDS=123456789
ADMIN_USERNAMES=@your_username

# Web Admin Panel Credentials
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=your_secure_password
```

### 5. Launch Application
```bash
# Runs both the Telegram Bot and Flask Web Panel concurrently
python app.py
```
*Or on Windows, launch directly via `start.bat`.*

---

## 🌐 Web Admin Panel Endpoints

| Route | Method | Access | Description |
|---|---|---|---|
| `/` | `GET` | Public | Home landing page / WebApp entry |
| `/login` | `GET, POST` | Public | Secure admin authentication portal |
| `/dashboard` | `GET` | Admin | Real-time statistics, active users, metrics |
| `/users` | `GET` | Admin | User database, referral tree & points editor |
| `/accounts` | `GET, POST` | Admin | Digital inventory drop manager |
| `/broadcast` | `GET, POST` | Admin | Multi-channel & direct message broadcaster |
| `/exchanges` | `GET, POST` | Admin | Peer account exchange verification queue |
| `/codes` | `GET, POST` | Admin | Promotional gift code generation system |

---

## 📁 Repository Blueprint

```
├── app.py                     # Master launcher (Spawns Bot + Flask Server)
├── bot.py                     # Telegram Bot builder & core command routing
├── handlers.py                # Message handlers, inline callbacks & admin queries
├── user_handlers.py           # User-facing points, referral & redemption logic
├── database.py                # Thread-safe atomic JSON engine with dual backups
├── config.py                  # Dynamic .env loader & sanitized configuration
├── scheduler.py               # Periodic tasks, background health check & cleanups
├── notifications.py           # Broadcasting engine & direct notification dispatch
├── utils.py                   # Data sanitizers, validators & utility helpers
├── animations.py              # Visual message formatting & bot animations
├── templates/                 # Glassmorphic web panel templates
│   ├── dashboard.html         # Live telemetry & charts
│   ├── accounts.html          # Digital account inventory manager
│   ├── users.html             # User database & points controller
│   └── broadcast.html         # Multi-target broadcast interface
├── static/                    # Cascading style sheets & web assets
├── .env.example               # Safe environment template
├── requirements.txt           # Python dependency manifest
└── README.md                  # Comprehensive dark-mode documentation
```

---

## 🔒 Security & Version Control Notice

- **Database Protection**: All user databases, chat logs, account inventories, and backups are strictly ignored by `.gitignore`.
- **Zero Token Leakage**: Hardcoded credentials are fully deprecated in favor of dynamic `.env` injection.

---

## 👤 Author & Architecture

Architected by **[@lusufer-rohit](https://github.com/lusufer-rohit)**  
*Full-Stack Engineer & Automation Architect*

<div align="center">

<p>
  <a href="https://github.com/lusufer-rohit"><img src="https://img.shields.io/badge/GitHub-Profile-000000?style=for-the-badge&logo=github&logoColor=white&labelColor=050811" alt="GitHub"/></a>
  <a href="https://t.me/"><img src="https://img.shields.io/badge/Telegram-Contact-000000?style=for-the-badge&logo=telegram&logoColor=00F5FF&labelColor=050811" alt="Telegram"/></a>
</p>

<!-- Dark Wave Footer -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,50:161b22,100:1a1b27&height=110&section=footer" width="100%" alt="Footer Banner"/>

</div>