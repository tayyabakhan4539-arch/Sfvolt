import asyncio
import sqlite3
import random
import logging
import time
import aiohttp
import hmac
import hashlib
import json
import html
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    SendMessage, EditMessageText, EditMessageCaption,
    SendPhoto, SendDocument, SendVideo, SendAnimation,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, Dice, BufferedInputFile
)

# ==============================================================================
# 1. BOT CONFIGURATION & CONSTANTS
# ==============================================================================
BOT_TOKEN = ""
BOT_USERNAME = "@sfvolt_bot"
ADMIN_ID = 7255956225
ADMIN_CONTACT = "@sfvolt"

# --- FAMGATEWAY (famgateway.in) AUTO PAYMENT ---
# Get your key (sk_live_...) from https://famgateway.in/dashboard.php
# You can also set/change it from the bot: Admin Panel -> FamPay Setup
FAMGATEWAY_API_KEY = ""
FAMGATEWAY_BASE = "https://famgateway.in"
MIN_DEPOSIT = 1.0
MAX_DEPOSIT = 50000.0

# --- GALUMODZ RESELLER API (automatic key supplier) ---
SFVOLT_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
sfvolt_API_KEY = "5d156aa13af9e36034687*******1"  # Better: admin can override via settings key 'sfvolt_api_key'

USDT_TO_INR = 90.0
VIP_DISCOUNT_PERCENTAGE = 10.0
VIP_PRICE_INR = 1000.0

WELCOME_STICKER_ID = "CAACAgIAAxkBAAEU-WZmH_..."  # Replace with your sticker ID

FIXED_CATEGORIES = [
    "ANDROID NON ROOT PANEL",
    "ANDROID ROOT PANEL",
    "PC PANEL"
]

# ==============================================================================
# YOUR PREMIUM EMOJIS – all required emoji IDs (updated with new premium ones)
# ==============================================================================
DEFAULT_EMOJIS = {
    'product_store': '6163205892834598715',
    'profile': '5258011929993026890',
    'add_balance': '5985630530111020079',
    'history': '6032594876506312598',
    'support': '5967280668885913944',
    'back': '5877536313623711363',
    'upi': '5807750375033278838',
    'reseller': '5886505193180239900',
    'tutorial': '6005986106703613755',
    'telegram': '5875465628285931233',
    'whatsapp': '5954224165874569584',
    'welcome': '5994502837327892086',
    'vip': '5206607081334906820',
    'category_android_non_root': '6161172706856282588',
    'category_android_root': '6161449831031118974',
    'category_pc': '5350554349074391003',
    'grid_id': '5474625972751837256',
    'name': '5215399540814781035',
    'account_level': '6129584162992034014',
    'regular_user': '5904630315946611415',
    'wallet': '6210859306602995217',
    'current_balance': '5316711376876485361',
    'global_stats': '6161437856662298090',
    'total_orders': '6160968017304888311',
    'total_spent': '5197503331215361533',
    'joined_grid': '5433614043006903194',
    'info_icon': '6037421444789440735',
    'check_icon': '6161241250239356403',
    'checkbox_icon': '6161437856662298090',
    'shield_icon': '6086672466132865380',
    'money_icon': '5890848474563352982',
    'redeem_icon': '5377624166436445368',
    'wallet_left': '6210859306602995217',
    'wallet_right': '5305699699204837855',
    'point_down': '6161302621027049305',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def fmt_curr(amount: float) -> str:
    return f"₹{amount:,.2f}"

def safe_float(val, default=0.0):
    """Safely convert a value to float, return default if fails."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

# ==============================================================================
# 2. DATABASE FUNCTIONS
# ==============================================================================
def db_query(query: str, params: tuple = (), fetchone: bool = False, fetchall: bool = False, commit: bool = True) -> Any:
    conn = sqlite3.connect('sfvolt.db')
    c = conn.cursor()
    try:
        c.execute(query, params)
        if fetchone:
            res = c.fetchone()
        elif fetchall:
            res = c.fetchall()
        else:
            res = None
        if commit: conn.commit()
        return res
    except Exception as e:
        logger.error(f"DB Error: {e} | Query: {query} | Params: {params}")
        if commit: conn.rollback()
        return None
    finally:
        conn.close()

def get_setting(key: str, default: str = "") -> str:
    val = db_query("SELECT value FROM settings WHERE key=?", (key,), fetchone=True)
    return val[0] if val and val[0] else default

def set_setting(key: str, value: str) -> None:
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

def log_activity(user_id: int, action: str, details: str = "") -> None:
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db_query(
            "INSERT INTO activity_logs (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, action, details, timestamp)
        )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")

def get_emoji(slot: str, default_id: str = None) -> str:
    stored = get_setting(f"emoji_{slot}", "")
    emoji_id = stored if stored and stored.isdigit() else (default_id or DEFAULT_EMOJIS.get(slot, ""))
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">✨</tg-emoji>'
    return "✨"

def get_emoji_fb(slot: str, fallback: str, default_id: str = "") -> str:
    """Premium emoji (admin-set ID, else built-in ID), otherwise the normal emoji."""
    stored = get_setting(f"emoji_{slot}", "")
    emoji_id = stored if stored and stored.isdigit() else default_id
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def get_emoji_icon(slot: str, default_id: str = None) -> str:
    stored = get_setting(f"emoji_{slot}", "")
    emoji_id = stored if stored and stored.isdigit() else (default_id or DEFAULT_EMOJIS.get(slot, ""))
    return emoji_id

# ==============================================================================
# 3. STRING RESOURCES – using placeholders for premium emojis
# ==============================================================================
# Divider under the blocks of the main menu. Make it longer/shorter if it wraps differently on your phone.
DIVIDER_LINE = "─" * 56

# Main-menu emoji slots: slot -> normal emoji shown until you set a premium emoji ID for it
# (Admin Panel -> Edit All Emojis, or see /emojiid to read IDs from any message).
START_MENU_EMOJIS = {
    # slot: (normal emoji fallback, premium emoji ID)
    'e_cart':  ('🛒', '5451937962629544243'),   # 🛒 — SFVOLT STORE — 🛒
    'e_crown': ('👑', '5433758796289685818'),   # 👑 Welcome
    'e_game':  ('🎮', '6050924877802640640'),   # Premium Game Keys
    'e_user':  ('👤', '5927266769281487788'),   # Instant Delivery 24/7
    'e_100':   ('💯', '6001517283426439371'),   # 100% Secure Payment
    'e_chart': ('📊', '6165617418187050280'),   # Best Prices Guaranteed
    'e_flag':  ('🇮🇳', '6195196922379115661'),  # Safe And Trusted
    'e_mail':  ('📩', '6194884545112709374'),   # Professional Support
    'e_money': ('💰', '6001434068435079689'),   # Wallet Balance
    'e_tap':   ('👑', '6057415823222379852'),   # Tap Shop Now to Start!
}

UI_TEXTS = {
    "start_menu": (
        "<blockquote>{e_cart} <b>— SFVOLT STORE —</b> {e_cart}</blockquote>"
        "{e_crown} Welcome, <b>{first_name}</b>!\n\n"
        "<blockquote>"
        "{e_game} Premium Game Keys\n"
        "{e_user} Instant Delivery 24/7\n"
        "{e_100} 100% Secure Payment\n"
        "{e_chart} Best Prices Guaranteed\n"
        "{e_flag} Safe And Trusted\n"
        "{e_mail} Professional Support"
        "</blockquote>\n"
        + DIVIDER_LINE + "\n\n"
        "<blockquote>{e_money} <b>Wallet Balance:</b> {balance}</blockquote>\n"
        + DIVIDER_LINE + "\n\n"
        "{e_tap} <b>Tap Shop Now to Start!</b>"
    ),
    "vip_menu": (
        "🌟 <b><u>VIP MEMBERSHIP CLUB</u></b> 🌟\n\n"
        "Unlock premium benefits and permanent discounts!\n\n"
        "💎 <b>VIP Benefits:</b>\n"
        "• Flat 15% off on ALL products (Stacks with Reseller!)\n"
        "• Priority Support\n"
        "• Exclusive VIP-only giveaways\n\n"
        "💳 <b>VIP Price:</b> ₹299.00 (Lifetime)\n"
        "👤 <b>Your Status:</b> {vip_status}"
    ),
    "add_balance_menu": (
        "{add_balance} <b>ADD BALANCE</b> {info_icon}\n\n"
        "{info_icon} Select your preferred payment method. {check_icon}\n\n"
        "┣ {upi} UPI — Fast Indian payments {checkbox_icon}\n"
        ""
        "{shield_icon} Payments are verified securely. {check_icon}"
    )
}

def get_ui_text(key: str, **kwargs) -> str:
    val = db_query("SELECT value FROM settings WHERE key=?", (f"ui_{key}",), fetchone=True)
    template = val[0] if val and val[0] else UI_TEXTS.get(key, "")

    emoji_map = {
        '{product_store}': get_emoji('product_store'),
        '{profile}': get_emoji('profile'),
        '{add_balance}': get_emoji('add_balance'),
        '{history}': get_emoji('history'),
        '{tutorial}': get_emoji('tutorial'),
        '{support}': get_emoji('support'),
        '{telegram}': get_emoji('telegram'),
        '{whatsapp}': get_emoji('whatsapp'),
        '{upi}': get_emoji('upi'),
        '{binance}': get_emoji('binance'),
        '{info_icon}': get_emoji('info_icon'),
        '{check_icon}': get_emoji('check_icon'),
        '{checkbox_icon}': get_emoji('checkbox_icon'),
        '{shield_icon}': get_emoji('shield_icon'),
        '{money_icon}': get_emoji('money_icon'),
        '{redeem_icon}': get_emoji('redeem_icon'),
        '{wallet_left}': get_emoji('wallet_left'),
        '{wallet_right}': get_emoji('wallet_right'),
        '{point_down}': get_emoji('point_down'),
    }
    for placeholder, emoji_tag in emoji_map.items():
        template = template.replace(placeholder, emoji_tag)
    for slot, (fb, default_id) in START_MENU_EMOJIS.items():
        template = template.replace("{" + slot + "}", get_emoji_fb(slot, fb, default_id))

    # Fill values safely: never fails, even if the template has a placeholder we don't know.
    for k, v in kwargs.items():
        template = template.replace("{" + k + "}", str(v))
    template = re.sub(r"\{e_[a-z0-9_]+\}", "", template)   # unknown emoji slots -> removed, never shown raw
    return template

# ==============================================================================
# 4. DATABASE INITIALISATION & MIGRATION
# ==============================================================================
def init_db() -> None:
    conn = sqlite3.connect('sfvolt.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            phone TEXT, 
            first_name TEXT, 
            username TEXT,
            balance REAL DEFAULT 0.0, 
            account_type TEXT DEFAULT 'Regular', 
            orders_count INTEGER DEFAULT 0, 
            spent REAL DEFAULT 0.0, 
            last_spin TEXT, 
            joined_date TEXT,
            is_reseller INTEGER DEFAULT 0,
            reseller_since TEXT,
            total_saved REAL DEFAULT 0.0,
            is_banned INTEGER DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0,
            vip_since TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            category TEXT, 
            panel_name TEXT DEFAULT '',
            name TEXT, 
            price_inr REAL, 
            reseller_price REAL DEFAULT 0.0,
            stock INTEGER, 
            apk_link TEXT, 
            validity TEXT DEFAULT 'Lifetime', 
            device_limit TEXT DEFAULT '1 Device',
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS product_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            product_id INTEGER, 
            key_text TEXT, 
            is_used INTEGER DEFAULT 0
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            product_name TEXT, 
            price_paid REAL, 
            delivered_key TEXT, 
            purchase_date TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            message TEXT, 
            status TEXT DEFAULT 'Open',
            created_at TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, 
            value TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY, 
            amount REAL, 
            uses_left INTEGER
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS redeemed (
            user_id INTEGER, 
            code TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            order_id TEXT PRIMARY KEY, 
            user_id INTEGER, 
            amount_inr REAL, 
            status TEXT, 
            timestamp INTEGER,
            qr_url TEXT,
            upi_id TEXT,
            expires_at INTEGER,
            checkout_url TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            utr TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS crypto_txns (
            txid TEXT PRIMARY KEY, 
            user_id INTEGER, 
            amount_usdt REAL, 
            timestamp INTEGER
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS spin_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            amount REAL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp TEXT
        )
    ''')

    migrations = [
        "ALTER TABLE users ADD COLUMN is_vip INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN vip_since TEXT",
        "ALTER TABLE products ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE tickets ADD COLUMN created_at TEXT",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN warnings INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN panel_name TEXT DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN qr_url TEXT",
        "ALTER TABLE transactions ADD COLUMN upi_id TEXT",
        "ALTER TABLE transactions ADD COLUMN expires_at INTEGER",
        "ALTER TABLE transactions ADD COLUMN checkout_url TEXT",
        "ALTER TABLE transactions ADD COLUMN chat_id INTEGER",
        "ALTER TABLE transactions ADD COLUMN message_id INTEGER",
        "ALTER TABLE transactions ADD COLUMN utr TEXT",
        "ALTER TABLE products ADD COLUMN api_product_id TEXT DEFAULT ''",
        "ALTER TABLE products ADD COLUMN api_duration TEXT DEFAULT ''"
    ]
    for mig in migrations:
        try: c.execute(mig)
        except sqlite3.OperationalError: pass

    # Old-gateway (fampay.anujbots.xyz) orders can never be verified on FamGateway -> close them.
    c.execute("UPDATE transactions SET status='expired' WHERE status='pending' AND order_id LIKE 'FAMPAY%'")
    

    default_settings = [
        ('reseller_system_status', 'ON'),
        ('bot_status', 'ON'),
        ('how_to_video', 'None'),
        ('famgateway_api_key', FAMGATEWAY_API_KEY),
        ('binance_api', ''),
        ('binance_secret', ''),
        ('binance_address', ''),
        ('vip_status', 'OFF'),
        ('reseller_setup_fee', '200.0'),
        ('reseller_min_balance', '500.0'),
        ('migration_done', '0'),
        ('support_telegram', 'https://t.me/YourSupport'),
        ('support_whatsapp', 'https://wa.me/YourNumber'),
        ('ui_start_menu', UI_TEXTS['start_menu']),
        ('ui_vip_menu', UI_TEXTS['vip_menu']),
        ('ui_add_balance_menu', UI_TEXTS['add_balance_menu']),
    ]
    for slot, emoji_id in DEFAULT_EMOJIS.items():
        default_settings.append((f"emoji_{slot}", emoji_id))
    for slot, (fb, default_id) in START_MENU_EMOJIS.items():
        default_settings.append((f"emoji_{slot}", default_id))
    
    for key, val in default_settings:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()


    # Removed feature settings are intentionally ignored by the UI.
    # Their old database values may remain, but no button or handler exposes them.

def migrate_categories() -> None:
    done = get_setting("migration_done", "0")
    
    # ALWAYS force update emojis and UI texts regardless of migration status
    logger.info("Forcing emoji and UI text updates...")
    
    # Remove legacy Ludo Spin / Download Files settings from existing databases
    db_query("DELETE FROM settings WHERE key IN ('emoji_ludo_spin', 'emoji_download', 'ui_download_files', 'ui_lucky_dice_result', 'all_files_link', 'spin_status', 'daily_spin_limit', 'emoji_referral')")

    # Update all emoji settings
    for slot, emoji_id in DEFAULT_EMOJIS.items():
        set_setting(f"emoji_{slot}", emoji_id)
    
    # Force update UI texts
    set_setting("ui_start_menu", UI_TEXTS['start_menu'])
    set_setting("ui_add_balance_menu", UI_TEXTS['add_balance_menu'])
    set_setting("ui_vip_menu", UI_TEXTS['vip_menu'])
    logger.info("UI texts and emojis updated with new placeholders and IDs.")
    
    # Fix any corrupted price columns (one-time cleanup)
    conn = sqlite3.connect('sfvolt.db')
    c = conn.cursor()
    products = c.execute("SELECT id, price_inr, reseller_price FROM products").fetchall()
    for prod in products:
        pid = prod[0]
        for col in ['price_inr', 'reseller_price']:
            val = prod[1] if col == 'price_inr' else prod[2]
            if val is None or val == "":
                new_val = 0.0
            else:
                try:
                    new_val = float(val)
                except (ValueError, TypeError):
                    new_val = 0.0
            c.execute(f"UPDATE products SET {col}=? WHERE id=?", (new_val, pid))
    conn.commit()
    conn.close()
    logger.info("Fixed any non-numeric price columns.")
    
    if done == "1":
        return
    
    logger.info("Running category migration...")
    
    mapping = {
        "android non root panel": "ANDROID NON ROOT PANEL",
        "android root panel": "ANDROID ROOT PANEL",
        "pc panel": "PC PANEL",
    }
    for old, new in mapping.items():
        db_query("UPDATE products SET category = ? WHERE LOWER(category) = ?", (new, old))
    
    db_query("UPDATE products SET category = 'ANDROID NON ROOT PANEL' WHERE LOWER(category) NOT IN (?, ?, ?)",
             ("android non root panel", "android root panel", "pc panel"))
    
    set_setting("migration_done", "1")
    logger.info("Category migration complete.")

# ==============================================================================
# 5. MIDDLEWARES & SECURITY
# ==============================================================================
async def hacker_loading(message: Message, text: str = "Decrypting Data") -> Message:
    msg = await message.answer(f"⚡ {text}\n[□□□] 0%")
    await asyncio.sleep(0.3)
    await msg.edit_text(f"⚡ {text}\n[■□□] 33%", parse_mode='HTML')
    await asyncio.sleep(0.3)
    await msg.edit_text(f"⚡ {text}\n[■■□] 66%", parse_mode='HTML')
    await asyncio.sleep(0.3)
    await msg.edit_text(f"⚡ {text}\n[■■■] 100%", parse_mode='HTML')
    return msg

class GlobalSecurityMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.last_action_times = {}

    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        now = time.time()
        if user_id in self.last_action_times:
            if now - self.last_action_times[user_id] < 0.3:
                return
        self.last_action_times[user_id] = now

        if user_id != ADMIN_ID:
            user_info = db_query("SELECT is_banned FROM users WHERE user_id=?", (user_id,), fetchone=True)
            if user_info and user_info[0] == 1:
                msg = "🚫 <b>ACCESS DENIED</b>\nYou have been banned from using this bot.\nContact support if you think this is a mistake."
                if isinstance(event, Message): await event.answer(msg)
                elif isinstance(event, CallbackQuery): await event.answer(msg, show_alert=True)
                return
                
            status_check = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
            status = status_check[0] if status_check else 'ON'
            if status == 'OFF':
                msg = "⚠️ <b>Store Maintenance</b>\n\nThe store is currently offline for updates. Please check back later!"
                if isinstance(event, Message): await event.answer(msg)
                elif isinstance(event, CallbackQuery): await event.answer("⚠️ Bot is currently OFF for Maintenance.", show_alert=True)
                return
                
        return await handler(event, data)

dp.message.middleware(GlobalSecurityMiddleware())
dp.callback_query.middleware(GlobalSecurityMiddleware())

# ==============================================================================
# 6. FSM STATES
# ==============================================================================
class UserStates(StatesGroup):
    wait_for_ticket = State()
    wait_for_redeem = State()
    wait_for_crypto_txid = State()
    custom_amount_input = State()

class AdminStates(StatesGroup):
    add_prod_category = State()
    add_prod_panel_name = State()
    add_prod_name = State()
    add_prod_validity = State()
    add_prod_device_limit = State()
    add_prod_price = State()
    add_prod_reseller_price = State()
    add_prod_apk = State()
    add_prod_keys = State()
    add_prod_api_pid = State()
    add_prod_api_duration = State()
    wait_for_api_pid = State()
    wait_for_api_duration = State()
    
    edit_prod_field = State()
    wait_for_new_value = State()
    wait_for_add_keys = State()
    wait_for_delete_key = State()
    
    broadcast_msg = State()
    add_coupon_code = State()
    add_coupon_amount = State()
    add_coupon_uses = State()
    
    # FamPay states
    wait_for_fampay_api = State()
    wait_for_fampay_upi = State()
    
    # Binance states
    wait_for_binance_api = State()
    wait_for_binance_secret = State()
    wait_for_binance_address = State()
    
    ticket_reply_msg = State()
    reseller_manage_id = State()
    manage_target_user = State()
    wait_for_add_money = State()
    wait_for_minus_money = State()
    wait_for_warning = State()
    
    wait_for_howto_video = State()
    
    edit_ui_text = State()
    edit_reseller_price = State()
    wait_for_reseller_setup_fee = State()
    wait_for_reseller_min_balance = State()
    confirm_ban = State()
    
    wait_for_support_telegram = State()
    wait_for_support_whatsapp = State()
    wait_for_category_emoji = State()
    wait_for_panel_emoji_id = State()
    wait_for_emoji_slot = State()

# ==============================================================================
# 7. KEYBOARDS
# ==============================================================================
def get_category_emoji(category: str) -> str:
    slot_map = {
        "ANDROID NON ROOT PANEL": "category_android_non_root",
        "ANDROID ROOT PANEL": "category_android_root",
        "PC PANEL": "category_pc",
    }
    slot = slot_map.get(category)
    if slot:
        return get_emoji_icon(slot, DEFAULT_EMOJIS.get(slot, ""))
    return ""

def get_panel_emoji(panel_name: str) -> str:
    stored = get_setting(f"panel_emoji_{panel_name}", "")
    if stored and stored.isdigit():
        return stored
    return get_emoji_icon("product_store")

def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Verify Contact", request_contact=True)]], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )

def main_menu_kb(user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    status_check = db_query("SELECT value FROM settings WHERE key='reseller_system_status'", fetchone=True)
    sys_status = status_check[0] if status_check else 'ON'
    vip_sys_check = db_query("SELECT value FROM settings WHERE key='vip_status'", fetchone=True)
    vip_system = vip_sys_check[0] if vip_sys_check else 'OFF'
    
    is_reseller = False
    if user_id:
        user_check = db_query("SELECT is_reseller FROM users WHERE user_id=?", (user_id,), fetchone=True)
        if user_check:
            is_reseller = bool(user_check[0])

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="Product Store", callback_data="menu_shop",
            icon_custom_emoji_id=get_emoji_icon("product_store"),
            style="danger"
        )
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="My Profile", callback_data="menu_profile",
            icon_custom_emoji_id=get_emoji_icon("profile"),
            style="primary"
        ),
        InlineKeyboardButton(
            text="Add Balance", callback_data="menu_add_balance",
            icon_custom_emoji_id=get_emoji_icon("add_balance"),
            style="primary"
        )
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="Tutorials", callback_data="menu_how_to",
            icon_custom_emoji_id=get_emoji_icon("tutorial"),
            style="success"
        ),
        InlineKeyboardButton(
            text="Support", callback_data="menu_support",
            icon_custom_emoji_id=get_emoji_icon("support"),
            style="danger"
        )
    ])
    
    extras_row = []
    if sys_status == 'ON' or is_reseller:
        extras_row.append(InlineKeyboardButton(
            text="Reseller Panel", callback_data="menu_reseller_dash",
            icon_custom_emoji_id=get_emoji_icon("reseller"),
            style="primary"
        ))
    if vip_system == 'ON':
        extras_row.append(InlineKeyboardButton(
            text="VIP Club", callback_data="menu_vip_dash",
            style="danger"
        ))
    if extras_row:
        kb.inline_keyboard.append(extras_row)
        
    return kb

def back_kb(callback: str = "back_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="BACK", callback_data=callback,
                icon_custom_emoji_id=get_emoji_icon("back"),
                style="danger"
            )
        ]]
    )

def admin_kb() -> InlineKeyboardMarkup:
    status = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
    status_val = status[0] if status else 'ON'
    vip_status = db_query("SELECT value FROM settings WHERE key='vip_status'", fetchone=True)
    vip_val = vip_status[0] if vip_status else 'OFF'
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Bot Statistics", callback_data="admin_view_stats", style="primary")],
        [InlineKeyboardButton(text="👥 User Control Panel", callback_data="admin_user_control_start", style="primary")],
        [
            InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_prod", style="primary"),
            InlineKeyboardButton(text="📦 Manage Products", callback_data="admin_manage_prods", style="primary")
        ],
        [
            InlineKeyboardButton(text="👑 Reseller Mgmt", callback_data="admin_reseller_menu", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎟 Create Coupon", callback_data="admin_create_coupon", style="primary"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast_btn", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎫 View Tickets", callback_data="admin_view_tickets", style="primary"),
            InlineKeyboardButton(text="📹 Tutorial Video", callback_data="admin_set_video", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎨 Edit All Emojis", callback_data="admin_edit_emojis", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚙️ FamPay Setup", callback_data="admin_setup_fampay", style="primary"),
        ],
        [
            InlineKeyboardButton(text="✏️ Edit UI Texts", callback_data="admin_edit_ui_menu", style="primary"),
            InlineKeyboardButton(text="📝 Edit Reseller Price", callback_data="admin_edit_reseller_price", style="primary")
        ],
        [
            InlineKeyboardButton(text="💰 Reseller Fee", callback_data="admin_set_reseller_fee", style="primary"),
            InlineKeyboardButton(text="💳 Min Balance", callback_data="admin_set_reseller_min", style="primary")
        ],
        [
            InlineKeyboardButton(text="📞 Set Support Links", callback_data="admin_set_support_links", style="primary"),
            InlineKeyboardButton(text="🎨 Set Category Emojis", callback_data="admin_set_category_emojis", style="primary")
        ],
        [
            InlineKeyboardButton(text="🖼 Set Panel Emojis", callback_data="admin_set_panel_emojis", style="primary")
        ],
        [
            InlineKeyboardButton(
                text=f"Bot Status: {status_val} {'🟢' if status_val == 'ON' else '🔴'}",
                callback_data="admin_toggle_bot",
                style="success" if status_val == 'ON' else "danger"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"VIP System: {vip_val} {'🟢' if vip_val == 'ON' else '🔴'}",
                callback_data="admin_toggle_vip_sys",
                style="success" if vip_val == 'ON' else "danger"
            )
        ]
    ])
    return kb

def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Back to Admin", callback_data="admin_panel_back",
            icon_custom_emoji_id=get_emoji_icon("back"),
            style="danger"
        )
    ]])

# ==============================================================================
# 8. NOTIFICATIONS
# ==============================================================================
async def send_advanced_notification(user_id: int, notif_type: str, amount: float, product: str = None, key: str = None, gateway: str = "FamPay") -> None:
    user_info = db_query("SELECT first_name, phone, username, is_reseller, is_vip FROM users WHERE user_id=?", (user_id,), fetchone=True)
    
    name = user_info[0] if user_info else "Unknown"
    phone = user_info[1] if user_info and user_info[1] else "Not Provided"
    username = f"@{user_info[2]}" if user_info and user_info[2] else "None"
    
    tags = []
    if user_info and user_info[3]: tags.append("👑 Reseller")
    if user_info and user_info[4]: tags.append("🌟 VIP")
    tag_str = " | ".join(tags) if tags else "👤 Regular"
        
    time_now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    
    if notif_type == "ORDER":
        title = "🛒 <b>NEW ORDER PROCESSED!</b> 🛒"
        details = (f"📦 <b>Product:</b> {product}\n🔑 <b>Key:</b> <code>{key}</code>\n💰 <b>Amount Paid:</b> ₹{amount:.2f}\n📅 <b>Time:</b> {time_now}")
    else:
        title = "💰 <b>NEW WALLET DEPOSIT!</b> 💰"
        details = (f"💵 <b>Amount Added:</b> ₹{amount:.2f}\n🧾 <b>Gateway:</b> {gateway}\n🆔 <b>Reference:</b> <code>{product}</code>\n📅 <b>Time:</b> {time_now}")

    msg = f"{title}\n━━━━━━━━━━━━━━━━━━\n👤 <b>Name:</b> {name}\n🆔 <b>User ID:</b> <code>{user_id}</code>\n📱 <b>Phone:</b> {phone}\n🔗 <b>Username:</b> {username}\n🏷 <b>Status:</b> {tag_str}\n━━━━━━━━━━━━━━━━━━\n{details}"
    try: 
        await bot.send_message(ADMIN_ID, msg, parse_mode='HTML')
    except Exception as e: 
        logger.error(f"Failed to send admin notification: {e}")

# ==============================================================================
# 9. FAMGATEWAY PAYMENT FUNCTIONS  (hosted checkout link -> auto return -> auto credit)
# ==============================================================================
_FG_TIMEOUT = aiohttp.ClientTimeout(total=20)
_FG_MIN_GAP = 3.5          # FamGateway asks for >= 3s between status polls of one order
_fg_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
ORDER_VALID_SECONDS = 300  # FamGateway orders live for 5 minutes
EXPIRY_GRACE_SECONDS = 90  # still check the gateway a bit after expiry (late bank mail)

def get_fg_key() -> str:
    """Return the active FamGateway API key (admin-set value first, then the constant)."""
    for key in (get_setting("famgateway_api_key", ""), FAMGATEWAY_API_KEY):
        key = (key or "").strip()
        if key and not key.startswith("YOUR_"):
            return key
    return ""

def fg_amount_param(amount: float) -> str:
    """500.0 -> '500', 99.5 -> '99.50' (exact amount, no stray decimals)."""
    amount = round(float(amount), 2)
    return str(int(amount)) if amount == int(amount) else f"{amount:.2f}"

async def _fg_get(path: str, params: Dict[str, str]) -> Dict[str, Any]:
    url = f"{FAMGATEWAY_BASE}{path}"
    try:
        async with aiohttp.ClientSession(
            timeout=_FG_TIMEOUT,
            headers={"User-Agent": "FamGateway-Bot/2.0", "Accept": "application/json"},
        ) as session:
            async with session.get(url, params=params) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return {"status": "error", "message": f"Invalid gateway response (HTTP {resp.status})"}
                if not isinstance(data, dict):
                    return {"status": "error", "message": "Unexpected gateway response"}
                return data
    except asyncio.TimeoutError:
        return {"status": "error", "message": "Gateway timeout, please try again"}
    except Exception as e:
        logger.error(f"FamGateway request failed ({path}): {type(e).__name__}")
        return {"status": "error", "message": "Could not reach payment gateway"}

async def create_famgateway_order(user_id: int, amount: float) -> Dict[str, Any]:
    key = get_fg_key()
    if not key:
        return {"status": "error", "message": "Gateway API key not configured"}
    redirect_url = f"https://t.me/{BOT_USERNAME.lstrip('@')}?start=paid"
    return await _fg_get("/api/qr.php", {
        "api_key": key,
        "amount": fg_amount_param(amount),
        "redirect_url": redirect_url,
        "customer_name": f"TG {user_id}",
    })

async def verify_fampay_payment(order_id: str) -> Dict[str, Any]:
    """Ask FamGateway for the order status (short cache keeps us under the polling limit)."""
    key = get_fg_key()
    if not key:
        return {"status": "error", "message": "Gateway API key not configured"}
    now = time.time()
    cached = _fg_cache.get(order_id)
    if cached and now - cached[0] < _FG_MIN_GAP:
        return cached[1]
    result = await _fg_get("/api/verify-order.php", {"api_key": key, "order_id": order_id})
    _fg_cache[order_id] = (time.time(), result)
    if len(_fg_cache) > 500:
        for k in sorted(_fg_cache, key=lambda x: _fg_cache[x][0])[:250]:
            _fg_cache.pop(k, None)
    return result

def parse_fg_status(result: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str]:
    """-> (state, data, message); state in success | pending | expired | error"""
    st = str(result.get("status", "")).strip().lower()
    msg = str(result.get("message") or "")
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if st in ("success", "paid", "completed"):
        return "success", data, msg
    if st in ("expired", "failed", "cancelled", "canceled"):
        return "expired", data, msg
    if st in ("pending", "created", "waiting", "processing", "unpaid"):
        return "pending", data, msg
    if "expired" in msg.lower():
        return "expired", data, msg
    return "error", data, msg

def _parse_expiry(data: Dict[str, Any]) -> int:
    now = int(time.time())
    default = now + ORDER_VALID_SECONDS
    for field in ("expires_at", "expires_at_ist"):
        val = data.get(field)
        if val in (None, ""):
            continue
        ts = None
        try:
            ts = int(float(val))
        except (TypeError, ValueError):
            try:
                ts = int(datetime.strptime(str(val), "%d-%m-%Y %H:%M:%S").timestamp())
            except Exception:
                ts = None
        if ts and now < ts <= now + 3600:
            return ts
    return default

def credit_if_unpaid(order_id: str, user_id: int, amount: float, utr: str) -> bool:
    """Atomically mark the order paid and credit the wallet. True only for the first caller."""
    conn = sqlite3.connect('sfvolt.db', timeout=15)
    try:
        if utr:
            dup = conn.execute(
                "SELECT 1 FROM transactions WHERE utr=? AND status='paid' AND order_id!=?", (utr, order_id)
            ).fetchone()
            if dup:
                logger.warning(f"Duplicate UTR {utr} rejected for order {order_id}")
                return False
        cur = conn.execute(
            "UPDATE transactions SET status='paid', utr=? WHERE order_id=? AND status!='paid'", (utr or None, order_id)
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"credit_if_unpaid failed for {order_id}: {e}")
        return False
    finally:
        conn.close()

def _pay_kb(order_id: str, checkout_url: Optional[str]) -> InlineKeyboardMarkup:
    rows = []
    if checkout_url:
        rows.append([InlineKeyboardButton(text="💳 Pay Now", url=checkout_url, style="success")])
    rows.append([InlineKeyboardButton(text="🔄 Verify Payment", callback_data=f"verify_{order_id}", style="primary")])
    rows.append([InlineKeyboardButton(text="Cancel", callback_data="menu_add_balance", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _expired_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ New Deposit", callback_data="gateway_inr", style="primary")],
        [InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")],
    ])

async def _drop_payment_message(chat_id: Optional[int], message_id: Optional[int]) -> None:
    """Remove the old 'Pay Now' message so no stale payment button is left behind."""
    if not chat_id or not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            pass

def _success_text(amount: float, utr: str, sender: str, ptime: str, balance: float, auto: bool = False) -> str:
    head = "✨ <b>PAYMENT RECEIVED!</b>" if auto else "🎉 <b>PAYMENT VERIFIED!</b>"
    lines = [head, "", f"✅ {fmt_curr(amount)} has been added to your wallet.",
             f"💰 <b>New Balance:</b> {fmt_curr(balance)}"]
    if utr: lines.append(f"🧾 UTR: <code>{html.escape(str(utr))}</code>")
    if sender: lines.append(f"👤 Sender: {html.escape(str(sender))}")
    if ptime: lines.append(f"📅 Time: {html.escape(str(ptime))}")
    return "\n".join(lines)

async def finalize_payment(order_id: str, gw_data: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    """
    Credit the wallet for a verified order (safe against double credit).
    source: 'callback' (user pressed Verify), 'deeplink' (came back from checkout), 'auto' (background task)
    Returns dict(amount, utr, balance, text, credited) or None if the order is unknown.
    """
    txn = db_query("SELECT user_id, amount_inr, chat_id, message_id FROM transactions WHERE order_id=?", (order_id,), fetchone=True)
    if not txn:
        return None
    owner_id, req_amount, chat_id, message_id = txn
    amount = safe_float(gw_data.get("amount"), 0.0)
    if amount <= 0:
        amount = safe_float(req_amount)
    utr = str(gw_data.get("utr") or "")
    sender = str(gw_data.get("sender_name") or "")
    ptime = str(gw_data.get("payment_time_ist") or gw_data.get("payment_time") or "")
    transaction_id = str(gw_data.get("transaction_id") or order_id)

    credited = credit_if_unpaid(order_id, owner_id, amount, utr)
    bal_row = db_query("SELECT balance FROM users WHERE user_id=?", (owner_id,), fetchone=True)
    balance = safe_float(bal_row[0]) if bal_row else 0.0
    text = _success_text(amount, utr, sender, ptime, balance, auto=(source == "auto"))
    result = {"amount": amount, "utr": utr, "balance": balance, "text": text, "credited": credited, "owner": owner_id}
    if not credited:
        return result

    # Clean up the payment message (QR / Pay button) now that money is in.
    if source == "callback":
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=back_kb(), parse_mode='HTML')
        except Exception:
            pass
    else:
        await _drop_payment_message(chat_id, message_id)
        if source == "auto":
            try:
                await bot.send_message(owner_id, text, reply_markup=back_kb(), parse_mode='HTML')
            except Exception as e:
                logger.warning(f"Could not notify user {owner_id}: {e}")

    await send_advanced_notification(owner_id, "DEPOSIT", amount, product=transaction_id, gateway="FamGateway")
    log_activity(owner_id, "DEPOSIT_SUCCESS", f"Amount: {amount}, Gateway: FamGateway ({source}), Order: {order_id}, UTR: {utr}")
    return result

async def run_payment_verification(user_id: int, order_id: str, reply_target: Any) -> None:
    """
    Manual verification. reply_target is either the CallbackQuery of the Verify button,
    or a bot Message (the 'Verifying...' message after returning from checkout).
    """
    is_cb = isinstance(reply_target, CallbackQuery)

    async def say(text: str, kb: Optional[InlineKeyboardMarkup] = None, alert: bool = False):
        try:
            if is_cb:
                if alert:
                    await reply_target.answer(re.sub(r"<[^>]+>", "", text), show_alert=True)
                else:
                    await reply_target.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
            else:
                await reply_target.edit_text(text, reply_markup=kb, parse_mode='HTML')
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                logger.warning(f"say() failed: {e}")
        except Exception as e:
            logger.warning(f"say() failed: {e}")

    txn = db_query("SELECT user_id, amount_inr, status, expires_at, checkout_url FROM transactions WHERE order_id=?", (order_id,), fetchone=True)
    if not txn or txn[0] != user_id:
        return await say("❌ Invalid order. Please create a new deposit request.", _expired_kb(), alert=is_cb)
    _, amount, status, expires_at, checkout_url = txn

    if status == 'paid':
        bal = db_query("SELECT balance FROM users WHERE user_id=?", (user_id,), fetchone=True)
        text = f"✅ This payment was already credited to your wallet.\n💰 <b>Balance:</b> {fmt_curr(safe_float(bal[0]) if bal else 0)}"
        return await say(text, back_kb(), alert=False)

    if is_cb:
        try: await reply_target.answer("🔍 Checking payment...")
        except Exception: pass

    result = await verify_fampay_payment(order_id)
    state, data, msg = parse_fg_status(result)

    if state == "success":
        info = await finalize_payment(order_id, data, "callback" if is_cb else "deeplink")
        if info is None:
            return await say("❌ Invalid order.", _expired_kb())
        if not is_cb:
            return await say(info["text"], back_kb())
        # callback: finalize already edited the message when credited
        if not info["credited"]:
            return await say(info["text"], back_kb())
        return

    past_expiry = bool(expires_at) and time.time() > expires_at + EXPIRY_GRACE_SECONDS
    if state == "expired" or (state in ("pending", "error") and past_expiry):
        db_query("UPDATE transactions SET status='expired' WHERE order_id=? AND status='pending'", (order_id,))
        return await say("⏳ <b>Payment link expired</b>\n\nNo payment was received for this order. If money was debited, it will be returned by your bank.\nPlease create a new deposit.", _expired_kb())

    if state == "pending":
        text = (f"⏳ <b>Payment not received yet</b>\n\n💵 <b>Amount:</b> {fmt_curr(amount)}\n"
                f"🆔 <b>Order:</b> <code>{order_id}</code>\n\n"
                "Complete the payment using <b>Pay Now</b>, then tap <b>Verify Payment</b>.\n"
                "<i>Already paid? Wait 10-20 seconds and verify again.</i>")
        if is_cb:
            return await reply_target.answer("⏳ Payment not received yet.\nPay using the Pay Now button, then verify again.", show_alert=True)
        return await say(text, _pay_kb(order_id, checkout_url))

    # gateway / network error
    err = msg or "Gateway busy"
    if is_cb:
        return await reply_target.answer(f"⚠️ {err}\nPlease try again in a few seconds.", show_alert=True)
    return await say(f"⚠️ <b>Gateway error:</b> {html.escape(err)}\nPlease tap Verify Payment again.", _pay_kb(order_id, checkout_url))

async def auto_verify_task() -> None:
    """Background poller: credits wallets automatically as soon as FamGateway confirms payment."""
    while True:
        try:
            await asyncio.sleep(5)
            if not get_fg_key():
                continue
            pending = db_query("SELECT order_id, user_id, expires_at, chat_id, message_id FROM transactions WHERE status='pending'", fetchall=True) or []
            for order_id, user_id, expires_at, chat_id, message_id in pending:
                try:
                    result = await verify_fampay_payment(order_id)
                    state, data, msg = parse_fg_status(result)
                    if state == "success":
                        await finalize_payment(order_id, data, "auto")
                    elif state == "expired" or (expires_at and time.time() > expires_at + EXPIRY_GRACE_SECONDS):
                        db_query("UPDATE transactions SET status='expired' WHERE order_id=? AND status='pending'", (order_id,))
                        await _drop_payment_message(chat_id, message_id)
                        try:
                            await bot.send_message(user_id, f"⏳ <b>Payment link expired</b>\nOrder <code>{order_id}</code> was not paid in time. Create a new deposit if you still want to add balance.", reply_markup=_expired_kb(), parse_mode='HTML')
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"auto_verify error for {order_id}: {e}")
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"auto_verify_task loop error: {e}")

# ==============================================================================
# 10. ONBOARDING & START
# ==============================================================================
async def handle_payment_return(message: Message, payload: str) -> None:
    """User came back from the FamGateway checkout page (t.me/<bot>?start=paid)."""
    user_id = message.from_user.id
    if payload.startswith("v_") and len(payload) > 2:
        order_id = payload[2:]
    else:
        row = db_query("SELECT order_id FROM transactions WHERE user_id=? AND order_id NOT LIKE 'FAMPAY%' ORDER BY timestamp DESC LIMIT 1", (user_id,), fetchone=True)
        if not row:
            await message.answer("ℹ️ No recent deposit found. Use <b>Add Balance</b> to start one.", reply_markup=back_kb(), parse_mode='HTML')
            return
        order_id = row[0]
    msg = await message.answer("🔄 <b>Verifying your payment...</b>", parse_mode='HTML')
    await run_payment_verification(user_id, order_id, msg)

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if payload == "paid" or payload.startswith("v_"):
        await handle_payment_return(message, payload)
        return

    try: await message.answer_sticker(WELCOME_STICKER_ID)
    except: pass 

    user = db_query("SELECT phone FROM users WHERE user_id=?", (message.from_user.id,), fetchone=True)
    current_username = message.from_user.username or ""
    db_query("UPDATE users SET username=? WHERE user_id=?", (current_username, message.from_user.id))

    if not user or not user[0]:
        db_query("INSERT OR IGNORE INTO users (user_id, first_name, username, joined_date) VALUES (?, ?, ?, ?)",
                 (message.from_user.id, message.from_user.first_name, current_username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        log_activity(message.from_user.id, "ACCOUNT_CREATED")

    log_activity(message.from_user.id, "CMD_START")
    await send_main_menu(message)

async def send_main_menu(ctx: Any):
    bal_row = db_query("SELECT balance FROM users WHERE user_id=?", (ctx.from_user.id,), fetchone=True)
    balance = safe_float(bal_row[0]) if bal_row else 0.0
    text = get_ui_text("start_menu", first_name=html.escape(ctx.from_user.first_name or "User"), balance=fmt_curr(balance))
    kb = main_menu_kb(ctx.from_user.id)
    async def _send(t: str):
        if isinstance(ctx, Message):
            return await ctx.answer(t, reply_markup=kb, parse_mode='HTML')
        return await ctx.message.edit_text(t, reply_markup=kb, parse_mode='HTML')
    try:
        res = await _send(text)
        sent_entities = getattr(res, "entities", None) or []
        if "<tg-emoji" in text and not any(e.type == "custom_emoji" for e in sent_entities):
            logger.warning("Telegram dropped the premium emojis in the main menu. The bot owner needs Telegram Premium (or the bot needs a Fragment username). Run /testemoji.")
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.warning(f"Main menu send failed with premium emojis ({e}); retrying with normal emojis.")
        plain = re.sub(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', r'\1', text)
        await _send(plain)

@dp.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    log_activity(call.from_user.id, "RETURN_MAIN_MENU")
    await send_main_menu(call)

# ==============================================================================
# 11. ADD BALANCE
# ==============================================================================
@dp.callback_query(F.data == "menu_add_balance")
async def select_gateway_menu(call: CallbackQuery):
    log_activity(call.from_user.id, "VIEW_ADD_BALANCE")
    text = get_ui_text("add_balance_menu")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="UPI PAY", callback_data="gateway_inr", icon_custom_emoji_id=get_emoji_icon("upi"), style="primary")
        ],
        [
            InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")
        ]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

# ==============================================================================
# 12. FAMPAY UPI PAYMENT FLOW
# ==============================================================================
@dp.callback_query(F.data == "gateway_inr")
async def add_balance_inr(call: CallbackQuery):
    text = f"💵 <b>— UPI DEPOSIT —</b> 💵\n\nSelect amount (₹1 – ₹50,000) or enter a custom amount.\n<i>You will get a secure Pay Now link. After paying, you return here automatically and your balance is added.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₹10", callback_data="pay_10", style="primary"), InlineKeyboardButton(text="₹50", callback_data="pay_50", style="primary"), InlineKeyboardButton(text="₹100", callback_data="pay_100", style="primary")],
        [InlineKeyboardButton(text="₹200", callback_data="pay_200", style="primary"), InlineKeyboardButton(text="₹500", callback_data="pay_500", style="primary")],
        [InlineKeyboardButton(text="₹1000", callback_data="pay_1000", style="primary"), InlineKeyboardButton(text="₹2000", callback_data="pay_2000", style="primary")],
        [InlineKeyboardButton(text="✏️ Custom Amount", callback_data="custom_deposit_keypad", style="primary")],
        [InlineKeyboardButton(text="Back", callback_data="menu_add_balance", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "custom_deposit_keypad")
async def show_custom_keypad(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.custom_amount_input)
    await state.update_data(amount_str="0")
    await show_keypad(call.message)

async def show_keypad(message: Message, amount_str: str = "0"):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="      1      ", callback_data="kp_1", style="primary"), InlineKeyboardButton(text="      2      ", callback_data="kp_2", style="primary"), InlineKeyboardButton(text="      3      ", callback_data="kp_3", style="primary")],
        [InlineKeyboardButton(text="      4      ", callback_data="kp_4", style="primary"), InlineKeyboardButton(text="      5      ", callback_data="kp_5", style="primary"), InlineKeyboardButton(text="      6      ", callback_data="kp_6", style="primary")],
        [InlineKeyboardButton(text="      7      ", callback_data="kp_7", style="primary"), InlineKeyboardButton(text="      8      ", callback_data="kp_8", style="primary"), InlineKeyboardButton(text="      9      ", callback_data="kp_9", style="primary")],
        [InlineKeyboardButton(text="    ⌫    ", callback_data="kp_backspace", style="danger"), InlineKeyboardButton(text="      0      ", callback_data="kp_0", style="primary"), InlineKeyboardButton(text="    C    ", callback_data="kp_clear", style="danger")],
        [InlineKeyboardButton(text=f"✅ Confirm (₹{amount_str})", callback_data="kp_confirm", style="success")],
        [InlineKeyboardButton(text="Cancel", callback_data="gateway_inr", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    text = f"💵 <b>Enter Amount (₹):</b>\n\nCurrent: ₹{amount_str}"
    await message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("kp_"), UserStates.custom_amount_input)
async def keypad_handler(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amount_str = data.get("amount_str", "0")
    action = call.data.split("_")[1]
    if action == "confirm":
        if amount_str == "0":
            await call.answer("Amount cannot be zero.", show_alert=True)
            return
        try:
            amount = float(amount_str)
            if amount < MIN_DEPOSIT:
                await call.answer(f"Minimum deposit is ₹{MIN_DEPOSIT:g}.", show_alert=True)
                return
            if amount > MAX_DEPOSIT:
                await call.answer(f"Maximum deposit is ₹{MAX_DEPOSIT:,.0f}.", show_alert=True)
                return
            await state.clear()
            await call.message.edit_text("⏳ <b>Creating secure payment link...</b>", parse_mode='HTML')
            await generate_fampay_order(call.from_user.id, amount, call.message)
        except ValueError:
            await call.answer("Invalid amount.", show_alert=True)
        return
    if action == "backspace":
        if len(amount_str) > 1: amount_str = amount_str[:-1]
        else: amount_str = "0"
    elif action == "clear":
        amount_str = "0"
    else:
        if amount_str == "0": amount_str = action
        else: amount_str += action
        if len(amount_str) > 6 or float(amount_str) > MAX_DEPOSIT:
            await call.answer(f"Maximum deposit is ₹{MAX_DEPOSIT:,.0f}.", show_alert=True)
            return
    await state.update_data(amount_str=amount_str)
    await show_keypad(call.message, amount_str)
    await call.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def process_fampay_payment_callback(call: CallbackQuery):
    try:
        inr_amount = float(call.data.split("_")[1])
    except ValueError:
        return await call.answer("Invalid amount.", show_alert=True)
    if not (MIN_DEPOSIT <= inr_amount <= MAX_DEPOSIT):
        return await call.answer(f"Deposit must be between ₹{MIN_DEPOSIT:g} and ₹{MAX_DEPOSIT:,.0f}.", show_alert=True)
    await call.message.edit_text("⏳ <b>Creating secure payment link...</b>", parse_mode='HTML')
    await generate_fampay_order(call.from_user.id, inr_amount, call.message)

async def generate_fampay_order(user_id: int, inr_amount: float, message_obj: Message) -> None:
    """Create a FamGateway order and show a Pay Now (checkout) button - no QR."""
    if not (MIN_DEPOSIT <= inr_amount <= MAX_DEPOSIT):
        return await message_obj.edit_text(f"❌ Deposit must be between ₹{MIN_DEPOSIT:g} and ₹{MAX_DEPOSIT:,.0f}.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')
    if not get_fg_key():
        return await message_obj.edit_text("⚠️ Payment gateway is currently offline. Admin needs to set the API key.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

    result = await create_famgateway_order(user_id, inr_amount)
    if str(result.get("status", "")).lower() != "success":
        error_msg = html.escape(str(result.get("message") or "Unknown error"))
        return await message_obj.edit_text(f"❌ <b>Gateway Error:</b> {error_msg}", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    order_id = data.get("order_id")
    checkout_url = data.get("checkout_url")
    if not order_id or not checkout_url:
        return await message_obj.edit_text("❌ <b>Gateway Error:</b> invalid order response. Please try again.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

    now = int(time.time())
    expires_ts = _parse_expiry(data)
    db_query(
        "INSERT OR REPLACE INTO transactions (order_id, user_id, amount_inr, status, timestamp, qr_url, upi_id, expires_at, checkout_url, chat_id, message_id) "
        "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
        (order_id, user_id, inr_amount, now, data.get("qr_url"), None, expires_ts, checkout_url, message_obj.chat.id, message_obj.message_id)
    )

    minutes = max(1, round((expires_ts - now) / 60))
    text = (
        f"🧾 <b>PAYMENT READY</b>\n\n"
        f"💵 <b>Amount:</b> {fmt_curr(inr_amount)}\n"
        f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
        f"⏳ <b>Valid for:</b> {minutes} minutes\n\n"
        f"📱 <b>How to Pay:</b>\n"
        f"1️⃣ Tap <b>Pay Now</b> and pay on the secure page\n"
        f"2️⃣ After paying you come back to the bot automatically\n"
        f"3️⃣ Balance is added instantly (you can also tap <b>Verify Payment</b>)"
    )
    log_activity(user_id, "GENERATE_INVOICE_FAMGATEWAY", f"Amount: {inr_amount}, Order ID: {order_id}")
    await message_obj.edit_text(text, reply_markup=_pay_kb(order_id, checkout_url), parse_mode='HTML')

@dp.callback_query(F.data.startswith("verify_"))
async def manual_verify_callback(call: CallbackQuery):
    order_id = call.data.split("_", 1)[1]
    await run_payment_verification(call.from_user.id, order_id, call)

# ==============================================================================
# 13. BINANCE CRYPTO PAYMENT
# ==============================================================================
@dp.callback_query(F.data == "gateway_crypto")
async def add_balance_crypto(call: CallbackQuery, state: FSMContext):
    address_check = db_query("SELECT value FROM settings WHERE key='binance_address'", fetchone=True)
    if not address_check or not address_check[0]:
        return await call.message.edit_text("⚠️ Binance Gateway is currently offline. Admin has not set a deposit address.", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')
    deposit_address = address_check[0]
    msg = (f"🪙 <b>— BINANCE USDT DEPOSIT —</b> 🪙\n\n💵 <b>Exchange Rate:</b> 1 USDT = ₹{USDT_TO_INR}\n⚠️ <b>Network:</b> Please send via <b>TRC20</b> or <b>BEP20</b>.\n\n👇 <b>Send your USDT to this exact address:</b>\n<code>{deposit_address}</code>\n\n━━━━━━━━━━━━━━━━━━\n✅ <b>After sending the USDT, reply to this message with your exact TxID (Transaction Hash) to instantly claim your balance.</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data="menu_add_balance", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]])
    await call.message.edit_text(msg, reply_markup=kb, parse_mode='HTML')
    await state.set_state(UserStates.wait_for_crypto_txid)

@dp.message(UserStates.wait_for_crypto_txid)
async def process_crypto_txid(m: Message, state: FSMContext):
    txid = m.text.strip()
    user_id = m.from_user.id
    if len(txid) < 10: return await m.answer("❌ That doesn't look like a valid TxID. Please try again.")
    if db_query("SELECT txid FROM crypto_txns WHERE txid=?", (txid,), fetchone=True):
        return await m.answer("⚠️ This Transaction ID has already been claimed in the system!", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')
    api_key_check = db_query("SELECT value FROM settings WHERE key='binance_api'", fetchone=True)
    secret_key_check = db_query("SELECT value FROM settings WHERE key='binance_secret'", fetchone=True)
    if not api_key_check or not secret_key_check:
        return await m.answer("⚠️ Binance API is missing on the server. Contact Support.", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')
    await m.answer("🔄 <b>Verifying your TxID with Binance Blockchain...</b>\n<i>This may take up to 30 seconds...</i>", parse_mode='HTML')
    api_key = api_key_check[0]; secret_key = secret_key_check[0]
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {'X-MBX-APIKEY': api_key}
    url = f"https://api.binance.com/sapi/v1/capital/deposit/hisrec?{query_string}&signature={signature}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    try: history = await resp.json(content_type=None)
                    except: history = []
                    found = False
                    for deposit in history:
                        if deposit.get("txId") == txid and deposit.get("status") == 1:
                            found = True
                            usdt_amount = float(deposit.get("amount"))
                            inr_amount = usdt_amount * USDT_TO_INR
                            db_query("INSERT INTO crypto_txns (txid, user_id, amount_usdt, timestamp) VALUES (?, ?, ?, ?)", (txid, user_id, usdt_amount, int(time.time())))
                            db_query("UPDATE users SET balance = balance + ? WHERE user_id=?", (inr_amount, user_id))
                            await m.answer(f"🎉 <b>CRYPTO DEPOSIT SUCCESSFUL!</b>\n\n✅ We safely received <b>{usdt_amount} USDT</b>.\n💰 <b>{fmt_curr(inr_amount)}</b> has been added to your balance!", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
                            await send_advanced_notification(user_id, "DEPOSIT", inr_amount, product=txid, gateway="Binance Crypto")
                            log_activity(user_id, "CRYPTO_DEPOSIT", f"TxID: {txid}, Amount: {inr_amount}")
                            await state.clear()
                            break
                    if not found: await m.answer("❌ <b>TxID Not Found or Still Pending!</b>\nMake sure the transaction is fully confirmed. Try again in 5 mins.", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')
                else: await m.answer(f"⚠️ <b>Binance Server Error:</b> HTTP {resp.status}.", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')
        except Exception as e: await m.answer(f"⚠️ <b>Connection Error:</b> {str(e)}", reply_markup=back_kb("menu_add_balance"), parse_mode='HTML')

# ==============================================================================
# 14. SHOP – with uppercase categories and new point_down emoji
# ==============================================================================
@dp.callback_query(F.data == "menu_shop")
async def view_shop_panels(call: CallbackQuery):
    log_activity(call.from_user.id, "VIEW_SHOP")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text = f"{get_emoji('product_store')} <b><u>SELECT PRODUCT PANEL</u></b>\n━━━━━━━━━━━━━━━━━━\n\n{get_emoji('point_down')} <b>Choose a panel to view its packages:</b>"
    for cat in FIXED_CATEGORIES:
        count = db_query("SELECT COUNT(*) FROM products WHERE category LIKE ? AND is_active=1", (cat + '%',), fetchone=True)[0]
        emoji_id = get_category_emoji(cat)
        kb.inline_keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"cat_{cat[:30]}", icon_custom_emoji_id=emoji_id, style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("cat_"))
async def view_panel_names(call: CallbackQuery):
    category = call.data.split("cat_", 1)[1]
    panel_names = db_query("SELECT DISTINCT panel_name FROM products WHERE category LIKE ? AND is_active=1 AND panel_name != ''", (category + '%',), fetchall=True)
    if not panel_names:
        prods = db_query("SELECT id, name, price_inr, stock, reseller_price, validity, device_limit FROM products WHERE category LIKE ? AND is_active=1", (category + '%',), fetchall=True)
        if not prods: return await call.answer("❌ No products available in this category yet.", show_alert=True)
        await show_products_for_panel(call, prods, category)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text = f"{get_emoji('product_store')} <b><u>{category.upper()} PANELS</u></b>\n━━━━━━━━━━━━━━━━━━\n\n{get_emoji('point_down')} <b>Choose a panel name:</b>"
    for pn in panel_names:
        panel = pn[0]
        emoji_id = get_panel_emoji(panel) or get_emoji_icon("product_store")
        kb.inline_keyboard.append([InlineKeyboardButton(text=panel, callback_data=f"pnl_{category[:30]}_{panel[:30]}", icon_custom_emoji_id=emoji_id, style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK TO PANELS", callback_data="menu_shop", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("pnl_"))
async def view_products_for_panel(call: CallbackQuery):
    parts = call.data.split("pnl_", 1)[1].split("_", 1)
    if len(parts) != 2: return await call.answer("Invalid selection.", show_alert=True)
    category, panel_name = parts[0], parts[1]
    prods = db_query("SELECT id, name, price_inr, stock, reseller_price, validity, device_limit FROM products WHERE category LIKE ? AND panel_name LIKE ? AND is_active=1", (category + '%', panel_name + '%'), fetchall=True)
    if not prods: return await call.answer("No products found for this panel.", show_alert=True)
    await show_products_for_panel(call, prods, f"{category} - {panel_name}")

async def show_products_for_panel(call: CallbackQuery, prods: List[Tuple], header: str):
    user = db_query("SELECT is_reseller, is_vip FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    is_reseller = bool(user[0]) if user else False
    is_vip = bool(user[1]) if user else False
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text = f"{get_emoji('product_store')} <b><u>{header.upper()} PACKAGES</u></b>\n━━━━━━━━━━━━━━━━━━\n\n"
    for p in prods:
        prod_id, package_name, normal_price, stock, reseller_price, validity, device = p
        normal_price = safe_float(normal_price)
        reseller_price = safe_float(reseller_price)
        base_price = reseller_price if is_reseller else normal_price
        if is_vip: display_price = base_price - (base_price * (VIP_DISCOUNT_PERCENTAGE / 100))
        else: display_price = base_price
        stock_status = "✅ In Stock" if stock > 0 else "❌ Out of Stock"
        text += f"{get_emoji('product_store')} ⏱ <b>Validity: {package_name}</b>\n"
        if is_reseller or is_vip:
            text += f"💰 Regular Price: <s>{fmt_curr(normal_price)}</s>\n"
            if is_reseller and not is_vip: text += f"👑 <b>Reseller Price: {fmt_curr(display_price)}</b>\n"
            elif is_vip and not is_reseller: text += f"🌟 <b>VIP Price: {fmt_curr(display_price)}</b>\n"
            else: text += f"👑🌟 <b>Super Price: {fmt_curr(display_price)}</b>\n"
        else: text += f"💰 Price: {fmt_curr(normal_price)}\n"
        text += f"📱 Limit: {device} | 📦 {stock_status}\n\n"
        if stock > 0:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"Buy {package_name} - {fmt_curr(display_price)}", callback_data=f"buy_{prod_id}", icon_custom_emoji_id=get_emoji_icon("product_store"), style="success")])
        else:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ {package_name} (Out of Stock)", callback_data="ignore_stock_click", style="danger")])
    text += f"{get_emoji('point_down')} <b>Select package below to instantly purchase:</b>"
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK TO PANELS", callback_data="menu_shop", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "ignore_stock_click")
async def ignore_stock_click(call: CallbackQuery):
    await call.answer("⚠️ This duration is completely Out of Stock! Admins have been notified to refill.", show_alert=True)

# ==============================================================================
# GALUMODZ RESELLER API HELPERS
# ==============================================================================
USER_BUY_LOCKS: Dict[int, asyncio.Lock] = {}

def get_galu_api_key() -> str:
    return get_setting("galu_api_key", "") or GALU_API_KEY

async def galu_request(action: str, **fields) -> Tuple[bool, Any]:
    """Call the reseller API. Returns (True, json_dict) or (False, error_text)."""
    api_key = get_galu_api_key()
    payload = {"api_key": api_key, "action": action}
    payload.update({k: v for k, v in fields.items() if v not in (None, "")})
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(GALU_API_URL, data=payload, headers={"X-API-Key": api_key}) as r:
                text = await r.text()
                try:
                    return True, json.loads(text)
                except ValueError:
                    return False, f"Invalid response (HTTP {r.status}): {text[:200]}"
    except asyncio.TimeoutError:
        return False, "TIMEOUT"
    except aiohttp.ClientError as e:
        return False, f"Connection error: {e}"

async def galu_buy(api_pid: str, duration: str = "", quantity: int = 1) -> Tuple[bool, str]:
    """Buy a key from the supplier. Returns (True, key) or (False, error_message)."""
    ok, data = await galu_request("buy", product_id=str(api_pid), duration=duration, quantity=quantity)
    if not ok:
        return False, str(data)
    if isinstance(data, dict) and data.get("status") == "success":
        key = data.get("key") or ((data.get("keys") or [None])[0])
        if key:
            return True, str(key)
        logger.error(f"GALU API success but no key in response: {data}")
        return False, "API returned success but no key. Check supplier orders."
    msg = (data.get("message") or data.get("error") or "Request failed") if isinstance(data, dict) else "Request failed"
    return False, str(msg)

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
    """Wrapper: one purchase at a time per user (stops double-click double-buy)."""
    lock = USER_BUY_LOCKS.setdefault(call.from_user.id, asyncio.Lock())
    if lock.locked():
        return await call.answer("⏳ Your previous purchase is still processing...", show_alert=True)
    async with lock:
        await _process_buy(call)

async def _process_buy(call: CallbackQuery):
    prod_id = int(call.data.split("_")[1])
    prod = db_query("SELECT name, price_inr, stock, apk_link, validity, device_limit, category, reseller_price, panel_name FROM products WHERE id=?", (prod_id,), fetchone=True)
    user = db_query("SELECT balance, is_reseller, total_saved, is_vip FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    if not prod: return await call.answer("❌ Critical Error: Item not found in DB!", show_alert=True)
    normal_price = safe_float(prod[1])
    reseller_price = safe_float(prod[7])
    is_reseller = bool(user[1]); is_vip = bool(user[3])
    base_price = reseller_price if is_reseller else normal_price
    if is_vip: final_price = base_price - (base_price * (VIP_DISCOUNT_PERCENTAGE / 100))
    else: final_price = base_price
    savings = normal_price - final_price
    if user[0] < final_price: return await call.answer(f"❌ Insufficient Balance! You need {fmt_curr(final_price)}.\nPlease Top Up your wallet.", show_alert=True)
    # --- Auto key from reseller API (if this product is linked) ---
    api_row = db_query("SELECT api_product_id, api_duration FROM products WHERE id=?", (prod_id,), fetchone=True)
    api_pid = (api_row[0] or "").strip() if api_row else ""
    api_dur = (api_row[1] or "").strip() if api_row else ""
    api_delivered = ""
    if api_pid:
        await call.answer("⏳ Generating your key, please wait...")
        ok, result = await galu_buy(api_pid, api_dur, 1)
        if not ok:
            log_activity(call.from_user.id, "API_BUY_FAILED", f"prod={prod_id} api_pid={api_pid} err={result}")
            if result == "TIMEOUT":
                user_msg = "⚠️ Supplier took too long to respond. You were NOT charged. Please try again in a minute."
                try: await bot.send_message(ADMIN_ID, f"⚠️ API TIMEOUT on product #{prod_id} (user {call.from_user.id}). The supplier may have processed it - check Reseller API orders.", parse_mode='HTML')
                except Exception: pass
            else:
                user_msg = f"❌ Could not generate key right now. You were NOT charged.\nReason: {html.escape(result)}\nContact: {ADMIN_CONTACT}"
                try: await bot.send_message(ADMIN_ID, f"⚠️ <b>API BUY FAILED</b>\nProduct #{prod_id} | User <code>{call.from_user.id}</code>\n<code>{html.escape(result)}</code>", parse_mode='HTML')
                except Exception: pass
            return await call.message.answer(user_msg, parse_mode='HTML')
        api_delivered = result
    db_query("UPDATE users SET balance=?, spent=spent+?, orders_count=orders_count+1, total_saved=total_saved+? WHERE user_id=?", (user[0] - final_price, final_price, savings, call.from_user.id))
    delivered_key = ""
    if api_delivered:
        delivered_key = api_delivered
    elif prod[2] > 0:
        key_data = db_query("SELECT id, key_text FROM product_keys WHERE product_id=? AND is_used=0 LIMIT 1", (prod_id,), fetchone=True)
        if key_data:
            delivered_key = key_data[1]
            db_query("UPDATE product_keys SET is_used=1 WHERE id=?", (key_data[0],))
            db_query("UPDATE products SET stock=stock-1 WHERE id=?", (prod_id,))
        else: delivered_key = "OUT_OF_STOCK_CONTACT_ADMIN_CODE_01"
    else: delivered_key = "OUT_OF_STOCK_CONTACT_ADMIN_CODE_02"
    if user[1]: 
        commission = final_price * 0.15 
        db_query("UPDATE users SET balance=balance+?, referral_earned=referral_earned+? WHERE user_id=?", (commission, commission, user[1]))
    product_full_name = f"{prod[6]} - {prod[8]} ({prod[0]})"
    db_query("INSERT INTO orders (user_id, product_name, price_paid, delivered_key, purchase_date) VALUES (?, ?, ?, ?, ?)", (call.from_user.id, product_full_name, final_price, delivered_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    log_activity(call.from_user.id, "PURCHASE_SUCCESS", f"Product: {product_full_name}, Paid: {final_price}")
    await send_advanced_notification(call.from_user.id, "ORDER", final_price, product=product_full_name, key=delivered_key)
    msg = (f"✅ <b>PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━\n📦 <b>Panel:</b> {prod[6]}\n📁 <b>Panel Name:</b> {prod[8]}\n⏱ <b>Package:</b> {prod[0]}\n💰 <b>Amount Deducted:</b> {fmt_curr(final_price)}\n📱 <b>Device Limit:</b> {prod[5]}\n━━━━━━━━━━━━━━━━━━\n")
    if prod[3] and prod[3].startswith("http"): msg += f"📥 <b>APK Link:</b> <a href='{prod[3]}'>Click Here to Download</a>\n\n"
    if "OUT_OF_STOCK" in delivered_key:
        msg += f"⚠️ <b>CRITICAL INVENTORY ALERT</b>\nYour money was deducted, but the key vault was empty. Contact Admin immediately with this message: {ADMIN_CONTACT}\n"
    else:
        msg += f"🔑 <b>Your Exclusive Key:</b>\n<code>{delivered_key}</code>\n\n<i>For any issues or guide, tap Support or contact: {ADMIN_CONTACT}</i>"
    await call.message.edit_text(msg, reply_markup=back_kb("menu_shop"), disable_web_page_preview=True, parse_mode='HTML')

# ==============================================================================
# 15. USER DASHBOARD, FILES, VIP, RESELLER, ORDERS, PROFILE
# ==============================================================================

@dp.callback_query(F.data == "menu_vip_dash")
async def vip_dashboard(call: CallbackQuery):
    u = db_query("SELECT balance, is_vip, vip_since FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    is_vip = bool(u[1])
    status_str = "🟢 Active (Lifetime)" if is_vip else "🔴 Not Subscribed"
    text = get_ui_text("vip_menu", vip_status=status_str)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if is_vip:
        text += f"\n📅 <b>Member Since:</b> {u[2]}\n\nEnjoy your permanent 15% discount!"
    else:
        text += f"\n\n💳 <b>Your Current Balance:</b> {fmt_curr(u[0])}\n"
        if u[0] >= VIP_PRICE_INR: kb.inline_keyboard.append([InlineKeyboardButton(text=f"✅ Purchase VIP for {fmt_curr(VIP_PRICE_INR)}", callback_data="execute_vip_upgrade", style="success")])
        else:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ Need {fmt_curr(VIP_PRICE_INR)} to Upgrade", callback_data="ignore_stock_click", style="danger")])
            kb.inline_keyboard.append([InlineKeyboardButton(text="💳 Add Balance Now", callback_data="menu_add_balance", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "execute_vip_upgrade")
async def execute_vip_upgrade(call: CallbackQuery):
    u = db_query("SELECT balance, is_vip FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    if u[1]: return await call.answer("⚠️ You are already a VIP Member!", show_alert=True)
    if u[0] < VIP_PRICE_INR: return await call.answer(f"❌ Your balance dropped below {VIP_PRICE_INR}.", show_alert=True)
    new_balance = u[0] - VIP_PRICE_INR
    now_date = datetime.now().strftime("%Y-%m-%d")
    db_query("UPDATE users SET balance=?, is_vip=1, vip_since=? WHERE user_id=?", (new_balance, now_date, call.from_user.id))
    log_activity(call.from_user.id, "UPGRADED_VIP")
    try: await bot.send_message(ADMIN_ID, f"🌟 <b>NEW VIP UPGRADE</b>\n👤 User ID: <code>{call.from_user.id}</code>", parse_mode='HTML')
    except: pass
    await call.answer("🎉 Upgrade Successful! You are now a VIP Member.", show_alert=True)
    await vip_dashboard(call)

@dp.callback_query(F.data == "menu_reseller_dash")
async def reseller_dashboard(call: CallbackQuery):
    u = db_query("SELECT balance, is_reseller, reseller_since, total_saved FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    status_check = db_query("SELECT value FROM settings WHERE key='reseller_system_status'", fetchone=True)
    system_status = status_check[0] if status_check else "ON"
    setup_fee = safe_float(get_setting("reseller_setup_fee", "200.0"))
    min_balance = safe_float(get_setting("reseller_min_balance", "500.0"))
    if u[1]: 
        text = (f"{get_emoji('shield_icon')} <b><u>— RESELLER DASHBOARD —</u></b> {get_emoji('shield_icon')}\n\n🟢 <b>Status:</b> Active\n📅 <b>Since:</b> {u[2]}\n{get_emoji('money_icon')} <b>Total Saved:</b> {fmt_curr(u[3])}\n\n🎉 You are enjoying exclusive wholesale prices on all products!")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]])
        await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        return
    if system_status == "OFF": return await call.answer("⚠️ Wholesale / Reseller registrations are currently closed by Admin.", show_alert=True)
    text = (f"⚡ <b><u>— BECOME A RESELLER —</u></b> ⚡\n\nUpgrade your account to access wholesale <b>Reseller Prices</b>!\n\n📋 <b>Requirements to Upgrade:</b>\n1️⃣ Must have a minimum balance of <b>{fmt_curr(min_balance)}</b>.\n2️⃣ A one-time setup fee of <b>{fmt_curr(setup_fee)}</b> will be deducted.\n\n💳 <b>Your Current Balance:</b> {fmt_curr(u[0])}\n")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if u[0] >= min_balance: kb.inline_keyboard.append([InlineKeyboardButton(text=f"✅ Pay {fmt_curr(setup_fee)} & Become Reseller", callback_data="execute_reseller_upgrade", style="success")])
    else:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ Insufficient Balance (Need {fmt_curr(min_balance)})", callback_data="ignore_stock_click", style="danger")])
        kb.inline_keyboard.append([InlineKeyboardButton(text="💳 Add Balance", callback_data="menu_add_balance", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "execute_reseller_upgrade")
async def execute_reseller_upgrade(call: CallbackQuery):
    setup_fee = safe_float(get_setting("reseller_setup_fee", "200.0"))
    min_balance = safe_float(get_setting("reseller_min_balance", "500.0"))
    u = db_query("SELECT balance, is_reseller FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    if u[1]: return await call.answer("⚠️ You are already a Reseller!", show_alert=True)
    if u[0] < min_balance: return await call.answer(f"❌ Your balance dropped below {fmt_curr(min_balance)}. Please top up.", show_alert=True)
    new_balance = u[0] - setup_fee
    db_query("UPDATE users SET balance=?, is_reseller=1, reseller_since=?, account_type='Reseller' WHERE user_id=?", (new_balance, datetime.now().strftime("%Y-%m-%d"), call.from_user.id))
    log_activity(call.from_user.id, "UPGRADED_RESELLER")
    try: await bot.send_message(ADMIN_ID, f"👑 <b>NEW RESELLER UPGRADE</b>\n👤 User ID: <code>{call.from_user.id}</code>", parse_mode='HTML')
    except: pass
    await call.answer("🎉 Upgrade Successful! Welcome to the Reseller tier.", show_alert=True)
    await reseller_dashboard(call)

@dp.callback_query(F.data == "menu_orders")
async def my_orders(call: CallbackQuery):
    orders = db_query("SELECT product_name, delivered_key, purchase_date, price_paid FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (call.from_user.id,), fetchall=True)
    if not orders: return await call.message.edit_text("🧾 You haven't made any purchases yet. Your vault is empty.", reply_markup=back_kb(), parse_mode='HTML')
    text = "🧾 <b><u>— YOUR RECENT ORDERS (LAST 10) —</u></b> 🧾\n\n"
    for o in orders: text += f"📦 <b>{o[0]}</b> ({fmt_curr(o[3])})\n🔑 <code>{o[1]}</code>\n📅 <i>{o[2]}</i>\n━━━━━━━━━━━━━━━━\n"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode='HTML')

@dp.callback_query(F.data == "menu_profile")
async def show_profile(call: CallbackQuery):
    u = db_query("SELECT user_id, first_name, account_type, balance, orders_count, spent, joined_date, is_reseller, reseller_since, total_saved, is_vip FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    acc_type_display = []
    if u[7]: acc_type_display.append(f"{get_emoji('reseller')} Reseller")
    if u[10]: acc_type_display.append(f"{get_emoji('vip')} VIP")
    type_str = " | ".join(acc_type_display) if acc_type_display else f"{get_emoji('regular_user')} Regular User"
    text = (
        f"{get_emoji('grid_id')} <b><u>— YOUR SECURE PROFILE —</u></b> {get_emoji('grid_id')}\n\n"
        f"{get_emoji('grid_id')} <b>Grid ID:</b> <code>{u[0]}</code>\n"
        f"{get_emoji('name')} <b>Name:</b> {u[1]}\n"
        f"{get_emoji('account_level')} <b>Account Level:</b> {type_str}\n\n"
        f"{get_emoji('wallet_left')} <b>— Wallet —</b> {get_emoji('wallet_right')}\n"
        f"{get_emoji('wallet_left')} <b>Current Balance:</b> {fmt_curr(u[3])} {get_emoji('wallet_right')}\n\n"
        f"{get_emoji('global_stats')} <b>— Global Statistics —</b>\n"
        f"{get_emoji('total_orders')} <b>Total Orders:</b> {u[4]}\n"
        f"{get_emoji('total_spent')} <b>Total Spent:</b> {fmt_curr(u[5])}\n"
    )
    if u[7]:
        text += f"{get_emoji('shield_icon')} <b>— RESELLER METRICS —</b> {get_emoji('shield_icon')}\n{get_emoji('money_icon')} <b>Total Saved via Reseller:</b> {fmt_curr(u[9])}\n\n"
    text += f"{get_emoji('joined_grid')} <b>Joined Grid:</b> {u[6]}\n\n"

    # Purchase history is shown directly inside Profile.
    orders = db_query(
        "SELECT delivered_key FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,), fetchall=True
    )
    text += "🧾 <b><u>— PURCHASE HISTORY —</u></b> 🧾\n\n"
    if orders:
        for o in orders:
            text += f"🔑 <code>{o[0]}</code>\n"
    else:
        text += "📭 <i>No purchases yet.</i>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Redeem Promo Code",
            callback_data="redeem_coupon",
            icon_custom_emoji_id=get_emoji_icon('redeem_icon'),
            style="success"
        )],
        [InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "redeem_coupon")
async def redeem_coupon_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("🎟 <b>Please enter your VIP / Promo redeem code below:</b>", reply_markup=back_kb("menu_profile"), parse_mode='HTML')
    await state.set_state(UserStates.wait_for_redeem)

@dp.message(UserStates.wait_for_redeem)
async def process_redeem(m: Message, state: FSMContext):
    code = m.text.strip().upper()
    user_id = m.from_user.id
    if db_query("SELECT * FROM redeemed WHERE user_id=? AND code=?", (user_id, code), fetchone=True):
        await m.answer("❌ Anti-Fraud Alert: You already redeemed this unique code!", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
        await state.clear()
        return
    coupon = db_query("SELECT amount, uses_left FROM coupons WHERE code=?", (code,), fetchone=True)
    if not coupon: await m.answer("❌ Invalid or Expired Code!", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
    elif coupon[1] <= 0: await m.answer("❌ This code's usage limit has been fully claimed by other users.", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
    else:
        db_query("UPDATE users SET balance = balance + ? WHERE user_id=?", (coupon[0], user_id))
        db_query("UPDATE coupons SET uses_left = uses_left - 1 WHERE code=?", (code,))
        db_query("INSERT INTO redeemed (user_id, code) VALUES (?, ?)", (user_id, code))
        log_activity(user_id, "PROMO_REDEEMED", f"Code: {code}, Amount: {coupon[0]}")
        await m.answer(f"🎉 <b>Success!</b>\nSafely added {fmt_curr(coupon[0])} to your balance!", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
        try:
            user_info = db_query("SELECT first_name FROM users WHERE user_id=?", (user_id,), fetchone=True)
            uname = user_info[0] if user_info else "Unknown User"
            await bot.send_message(ADMIN_ID, f"🎟 <b>PROMO CODE REDEEMED!</b>\n👤 User: {uname} (<code>{user_id}</code>)\n🔖 Code: <b>{code}</b>\n💵 Amount: {fmt_curr(coupon[0])}", parse_mode='HTML')
        except Exception: pass
    await state.clear()

@dp.callback_query(F.data == "menu_how_to")
async def tutorial_system(call: CallbackQuery):
    video_link_query = db_query("SELECT value FROM settings WHERE key='how_to_video'", fetchone=True)
    video_link = video_link_query[0] if video_link_query and video_link_query[0] != 'None' else None
    text = (f"{get_emoji('tutorial')} <b><u>— TUTORIALS & GUIDE —</u></b> {get_emoji('tutorial')}\n\n1️⃣ Add funds via <b>Add Balance</b>\n2️⃣ Navigate to <b>Product Store</b>\n3️⃣ Choose your desired Panel and Package validity.\n4️⃣ The Key and Installation APK link will be instantly provided.")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if video_link: kb.inline_keyboard.append([InlineKeyboardButton(text="Watch Full Video Tutorial", url=video_link, icon_custom_emoji_id=get_emoji_icon("tutorial"), style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "menu_support")
async def support_center(call: CallbackQuery):
    telegram_link = get_setting("support_telegram", "https://t.me/YourSupport")
    whatsapp_link = get_setting("support_whatsapp", "https://wa.me/YourNumber")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Contact on Telegram", url=telegram_link, icon_custom_emoji_id=get_emoji_icon("telegram"), style="primary")],
        [InlineKeyboardButton(text="Contact on WhatsApp", url=whatsapp_link, icon_custom_emoji_id=get_emoji_icon("whatsapp"), style="primary")],
        [InlineKeyboardButton(text="🎫 Open New Ticket", callback_data="open_ticket", style="primary"), InlineKeyboardButton(text="📋 My Open Tickets", callback_data="my_tickets", style="primary")], 
        [InlineKeyboardButton(text="BACK", callback_data="back_main", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text(f"{get_emoji('telegram')}{get_emoji('whatsapp')} <b><u>— PREMIUM SUPPORT CENTER —</u></b>\n\nContact us via Telegram or WhatsApp for instant help, or open a support ticket for admin assistance.", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "my_tickets")
async def view_my_tickets(call: CallbackQuery):
    tickets = db_query("SELECT id, message, status, created_at FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 5", (call.from_user.id,), fetchall=True)
    if not tickets: return await call.message.edit_text("📋 You do not have any active or previous support tickets.", reply_markup=back_kb("menu_support"), parse_mode='HTML')
    text = "📋 <b><u>— Your Recent Tickets —</u></b> 📋\n\n"
    for t in tickets:
        status_icon = "🟢" if t[2] == 'Open' else "🔴"
        text += f"🎫 <b>Ticket #{t[0]}</b> | Status: {status_icon} <b>{t[2]}</b>\n📅 <i>{t[3]}</i>\n📝 <i>{t[1][:80]}...</i>\n\n"
    await call.message.edit_text(text, reply_markup=back_kb("menu_support"), parse_mode='HTML')

@dp.callback_query(F.data == "open_ticket")
async def open_ticket_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("📝 <b>Please type your issue/message below in detail:</b>", reply_markup=back_kb("menu_support"), parse_mode='HTML')
    await state.set_state(UserStates.wait_for_ticket)

@dp.message(UserStates.wait_for_ticket)
async def process_ticket(m: Message, state: FSMContext):
    db_query("INSERT INTO tickets (user_id, message, created_at) VALUES (?, ?, ?)", (m.from_user.id, m.text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    await m.answer("✅ <b>Ticket Submitted Successfully!</b> Admins will reply soon.", reply_markup=main_menu_kb(m.from_user.id), parse_mode='HTML')
    try: await bot.send_message(ADMIN_ID, f"🚨 <b>NEW SUPPORT TICKET</b>\nFrom: <code>{m.from_user.id}</code>\nMsg: {m.text}", parse_mode='HTML')
    except: pass
    log_activity(m.from_user.id, "OPENED_TICKET")
    await state.clear()

# ==============================================================================
# 18. ADMIN PANEL
# ==============================================================================
@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    await message.answer("⚙️ <b>Advanced Admin Terminal</b>\n<i>Authorized Access Granted.</i>", reply_markup=admin_kb(), parse_mode='HTML')

@dp.callback_query(F.data == "admin_panel_back")
async def back_to_admin(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("⚙️ <b>Advanced Admin Terminal</b>\n<i>Authorized Access Granted.</i>", reply_markup=admin_kb(), parse_mode='HTML')

@dp.callback_query(F.data == "admin_toggle_vip_sys")
async def toggle_vip_sys(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    res = db_query("SELECT value FROM settings WHERE key='vip_status'", fetchone=True)
    current = res[0] if res else 'OFF'
    new_status = 'ON' if current == 'OFF' else 'OFF'
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('vip_status', ?)", (new_status,))
    await call.message.edit_reply_markup(reply_markup=admin_kb())

@dp.callback_query(F.data == "admin_user_control_start")
async def admin_user_control_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Download Full User List", callback_data="admin_download_userlist", style="success")],
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text("💻 <b>User Control Terminal</b>\n\n✏️ Enter the <b>User ID</b> or <b>@Username</b> you want to investigate or manage:\n\n👇 <b>OR</b> download the full user CSV format list:", reply_markup=kb, parse_mode='HTML')
    await state.set_state(AdminStates.manage_target_user)

@dp.callback_query(F.data == "admin_download_userlist")
async def admin_download_userlist(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    users = db_query("SELECT username, user_id, phone, balance, orders_count, is_vip, is_reseller FROM users", fetchall=True)
    if not users: return await call.answer("❌ No users found in the database.", show_alert=True)
    file_content = "FULL DATABASE DUMP\n" + "="*100 + "\n"
    for u in users:
        uname = u[0] if u[0] else "No_Username"
        uid = u[1]
        phone = u[2] if u[2] else "No_Phone"
        bal = u[3]
        orders = u[4]
        vip_status = "YES" if u[5] else "NO"
        res_status = "YES" if u[6] else "NO"
        file_content += f"UID: {uid} | UNAME: {uname} | PHONE: {phone} | BAL: ₹{bal:.2f} | BUY: {orders} | VIP: {vip_status} | RES: {res_status}\n"
    doc = BufferedInputFile(file_content.encode('utf-8'), filename=f"DB_{datetime.now().strftime('%Y%m%d')}.txt")
    await call.message.answer_document(document=doc, caption="📋 <b>Database export complete.</b>", parse_mode='HTML')
    await call.answer()

@dp.message(AdminStates.manage_target_user)
async def process_user_lookup(m: Message, state: FSMContext):
    target = m.text.strip()
    if target.startswith('@'): target = target[1:]
    loader_msg = await hacker_loading(m, "Querying User Database")
    user_q = db_query("SELECT user_id, first_name, username, balance, is_reseller, orders_count, spent, joined_date, is_banned, warnings, is_vip FROM users WHERE user_id=? OR username=? COLLATE NOCASE", (target, target), fetchone=True)
    if not user_q: return await loader_msg.edit_text("❌ Target not found in the grid. Check ID/Username syntax.", reply_markup=admin_back_kb(), parse_mode='HTML')
    u_id, u_name, u_user, bal, is_res, orders, spent, joined, is_banned, warnings, is_vip = user_q
    await state.update_data(target_u_id=u_id)
    status_emoji = "🔴 BANNED" if is_banned else "🟢 ACTIVE"
    tags = []
    if is_res: tags.append("👑 Reseller")
    if is_vip: tags.append("🌟 VIP")
    type_str = " | ".join(tags) if tags else "👤 Regular"
    text = (f"🛡 <b><u>USER CONTROL TERMINAL</u></b> 🛡\n━━━━━━━━━━━━━━━━━━\n📛 <b>Name:</b> {u_name} (@{u_user})\n🆔 <b>ID:</b> <code>{u_id}</code>\n📊 <b>Status:</b> {status_emoji}\n🔰 <b>Type:</b> {type_str}\n⚠️ <b>Warnings Issued:</b> {warnings}\n━━━━━━━━━━━━━━━━━━\n💰 <b>Wallet Balance:</b> {fmt_curr(bal)}\n📦 <b>Orders:</b> {orders} | 💸 <b>Total Spent:</b> {fmt_curr(spent)}\n📅 <b>Joined:</b> {joined}")
    ban_btn_text = "Unban ✅" if is_banned else "Ban 🚫"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Add Funds ➕", callback_data=f"usrctrl_add_{u_id}", style="success"), InlineKeyboardButton(text="Minus Funds ➖", callback_data=f"usrctrl_min_{u_id}", style="danger")],
        [InlineKeyboardButton(text=ban_btn_text, callback_data=f"usrctrl_ban_{u_id}", style="danger"), InlineKeyboardButton(text="Warn User ⚠️", callback_data=f"usrctrl_warn_{u_id}", style="danger")],
        [InlineKeyboardButton(text="Give VIP 🌟" if not is_vip else "Remove VIP 🚫", callback_data=f"usrctrl_vip_{u_id}", style="success")],
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await loader_msg.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("usrctrl_"))
async def handle_user_actions(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split("_")[1]
    u_id = int(call.data.split("_")[2])
    await state.update_data(target_u_id=u_id)
    if action == "ban":
        current_status = db_query("SELECT is_banned FROM users WHERE user_id=?", (u_id,), fetchone=True)[0]
        if current_status == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Yes, Ban", callback_data=f"confirm_ban_{u_id}", style="danger"), InlineKeyboardButton(text="❌ Cancel", callback_data="admin_user_control_start", style="danger")]
            ])
            await call.message.edit_text(f"⚠️ Are you sure you want to <b>BAN</b> user <code>{u_id}</code>?", reply_markup=kb, parse_mode='HTML')
            await state.set_state(AdminStates.confirm_ban)
        else:
            db_query("UPDATE users SET is_banned=0 WHERE user_id=?", (u_id,))
            await call.answer("✅ User unbanned successfully!", show_alert=True)
            m = call.message; m.text = str(u_id); await process_user_lookup(m, state)
    elif action == "vip":
        current_status = db_query("SELECT is_vip FROM users WHERE user_id=?", (u_id,), fetchone=True)[0]
        if current_status == 1:
            db_query("UPDATE users SET is_vip=0 WHERE user_id=?", (u_id,))
            await call.answer("✅ VIP Removed!", show_alert=True)
        else:
            db_query("UPDATE users SET is_vip=1, vip_since=? WHERE user_id=?", (datetime.now().strftime("%Y-%m-%d"), u_id))
            await call.answer("✅ VIP Granted!", show_alert=True)
        m = call.message; m.text = str(u_id); await process_user_lookup(m, state)
    elif action == "add":
        await call.message.edit_text("💰 Enter the amount to <b>ADD</b> to this user's wallet:", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_add_money)
    elif action == "min":
        await call.message.edit_text("💸 Enter the amount to <b>DEDUCT</b> from this user's wallet:", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_minus_money)
    elif action == "warn":
        await call.message.edit_text("⚠️ Type the strict warning message you want to send directly to this user:", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_warning)

@dp.callback_query(F.data.startswith("confirm_ban_"))
async def confirm_ban(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    u_id = int(call.data.split("_")[2])
    db_query("UPDATE users SET is_banned=1 WHERE user_id=?", (u_id,))
    await call.answer("🔴 User has been banned!", show_alert=True)
    await state.clear()
    m = call.message; m.text = str(u_id); await process_user_lookup(m, state)

@dp.message(AdminStates.wait_for_add_money)
async def exec_add_money(m: Message, state: FSMContext):
    try:
        amt = float(m.text)
        data = await state.get_data()
        u_id = data['target_u_id']
        db_query("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, u_id))
        await m.answer(f"✅ Successfully added {fmt_curr(amt)} to target <code>{u_id}</code>.", reply_markup=admin_kb(), parse_mode='HTML')
        try: await bot.send_message(u_id, f"💰 <b>Wallet Top-up!</b>\nAdmin has manually added {fmt_curr(amt)} to your wallet.", parse_mode='HTML')
        except: pass
        await state.clear()
    except ValueError: await m.answer("❌ Critical Error: Input must be a valid number.")

@dp.message(AdminStates.wait_for_minus_money)
async def exec_minus_money(m: Message, state: FSMContext):
    try:
        amt = float(m.text)
        data = await state.get_data()
        u_id = data['target_u_id']
        db_query("UPDATE users SET balance = balance - ? WHERE user_id=?", (amt, u_id))
        await m.answer(f"✅ Successfully deducted {fmt_curr(amt)} from target <code>{u_id}</code>.", reply_markup=admin_kb(), parse_mode='HTML')
        await state.clear()
    except ValueError: await m.answer("❌ Critical Error: Input must be a valid number.")

@dp.message(AdminStates.wait_for_warning)
async def exec_warn_user(m: Message, state: FSMContext):
    data = await state.get_data()
    u_id = data['target_u_id']
    warn_text = m.text
    db_query("UPDATE users SET warnings = warnings + 1 WHERE user_id=?", (u_id,))
    await m.answer(f"✅ Official warning dispatched to <code>{u_id}</code>.", reply_markup=admin_kb(), parse_mode='HTML')
    try: await bot.send_message(u_id, f"⚠️ <b>OFFICIAL WARNING FROM SYSTEM ADMIN:</b>\n\n{warn_text}\n\n<i>Subsequent infractions may lead to an automated grid ban.</i>", parse_mode='HTML')
    except: pass
    await state.clear()

# ==============================================================================
# 19. ADMIN STATISTICS
# ==============================================================================
@dp.callback_query(F.data == "admin_view_stats")
async def admin_dashboard_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    t_users = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    t_resellers = db_query("SELECT COUNT(*) FROM users WHERE is_reseller=1", fetchone=True)[0]
    t_vip = db_query("SELECT COUNT(*) FROM users WHERE is_vip=1", fetchone=True)[0]
    t_prods = db_query("SELECT COUNT(*) FROM products", fetchone=True)[0]
    t_keys = db_query("SELECT COUNT(*) FROM product_keys WHERE is_used=0", fetchone=True)[0]
    t_rev = db_query("SELECT SUM(spent) FROM users", fetchone=True)[0] or 0.0
    today_str = datetime.now().strftime("%Y-%m-%d")
    msg = (f"📊 <b><u>GRID INTELLIGENCE DASHBOARD</u></b> 📊\n━━━━━━━━━━━━━━━━━━\n👥 <b>Total Grid Users:</b> {t_users}\n👑 <b>Wholesale Resellers:</b> {t_resellers}\n🌟 <b>Elite VIP Members:</b> {t_vip}\n━━━━━━━━━━━━━━━━━━\n📦 <b>Active Products:</b> {t_prods}\n🔑 <b>Unused Keys in Vault:</b> {t_keys}\n💰 <b>Total Gross Revenue:</b> {fmt_curr(t_rev)}\n━━━━━━━━━━━━━━━━━━")
    await call.message.edit_text(msg, reply_markup=admin_back_kb(), parse_mode='HTML')

# ==============================================================================
# 20. ADMIN PRODUCT MANAGEMENT
# ==============================================================================
@dp.callback_query(F.data == "admin_add_prod")
async def add_prod_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for cat in FIXED_CATEGORIES:
        emoji_id = get_category_emoji(cat)
        kb.inline_keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"addprod_cat_{cat}", icon_custom_emoji_id=emoji_id, style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Cancel", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("<b>Step 1:</b> Choose the <b>Category</b> for this product:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("addprod_cat_"))
async def add_prod_category_selected(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    category = call.data.split("addprod_cat_", 1)[1]
    await state.update_data(cat=category)
    await call.message.edit_text(f"<b>Step 2:</b> Enter <b>PANEL NAME</b>\n(e.g., 'MST PANEL', 'DRIP PANEL'):", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_panel_name)

@dp.message(AdminStates.add_prod_panel_name)
async def add_prod_panel_name(m: Message, state: FSMContext):
    await state.update_data(panel_name=m.text)
    await m.answer("<b>Step 3:</b> Enter <b>PACKAGE DURATION/DATE NAME</b>\n(e.g., '7 Days', '1 Month'):", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_name)

@dp.message(AdminStates.add_prod_name)
async def add_prod_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("⏳ Enter Time Validity String (e.g., '24 Hours'):", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_validity)

@dp.message(AdminStates.add_prod_validity)
async def add_prod_validity(m: Message, state: FSMContext):
    await state.update_data(validity=m.text)
    await m.answer("📱 Enter strict Device Enforcement Limit (e.g., '1 Device HWID'):", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_device_limit)

@dp.message(AdminStates.add_prod_device_limit)
async def add_prod_device_limit(m: Message, state: FSMContext):
    await state.update_data(device_limit=m.text)
    await m.answer("💰 Enter standard **User Price** in Rupees (₹) (e.g., 500):", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_price)

@dp.message(AdminStates.add_prod_price)
async def add_prod_price(m: Message, state: FSMContext):
    try:
        await state.update_data(price=float(m.text))
        await m.answer("👑 Enter wholesale **Reseller Price** in Rupees (₹) (e.g., 300):", parse_mode='HTML')
        await state.set_state(AdminStates.add_prod_reseller_price)
    except ValueError: await m.answer("❌ Invalid input datatype! Must be numerical.")

@dp.message(AdminStates.add_prod_reseller_price)
async def add_prod_reseller_price(m: Message, state: FSMContext):
    try:
        await state.update_data(reseller_price=float(m.text))
        await m.answer("🔗 Enter direct APK/Payload Download Link (or type 'none' to omit):", parse_mode='HTML')
        await state.set_state(AdminStates.add_prod_apk)
    except ValueError: await m.answer("❌ Invalid input datatype! Must be numerical.")

@dp.message(AdminStates.add_prod_apk)
async def add_prod_apk(m: Message, state: FSMContext):
    await state.update_data(apk="" if m.text.lower() == 'none' else m.text)
    await m.answer("🔌 <b>API PID</b>\n\nSend the <b>PID (CODE)</b> from the Reseller API table (e.g. <code>151</code>) for automatic keys.\n\nOr type <code>none</code> to add keys manually.", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_api_pid)

@dp.message(AdminStates.add_prod_api_pid)
async def add_prod_api_pid(m: Message, state: FSMContext):
    txt = (m.text or "").strip()
    if txt.lower() in ("none", "no", "skip", ""):
        await m.answer("📥 <b>Vault Injection Phase</b>\n\nPaste all the license <b>Keys</b> exactly as formatted (1 key per newline):", parse_mode='HTML')
        return await state.set_state(AdminStates.add_prod_keys)
    await state.update_data(api_pid=txt)
    await m.answer("⏱ Send the API <b>duration</b> name (e.g. <code>1 Day</code>, <code>7 Days</code>).\nType <code>none</code> if the PID is not shared.", parse_mode='HTML')
    await state.set_state(AdminStates.add_prod_api_duration)

@dp.message(AdminStates.add_prod_api_duration)
async def add_prod_api_duration(m: Message, state: FSMContext):
    txt = (m.text or "").strip()
    duration = "" if txt.lower() in ("none", "no", "skip", "") else txt
    data = await state.get_data()
    db_query(
        "INSERT INTO products (category, panel_name, name, price_inr, reseller_price, stock, apk_link, validity, device_limit, api_product_id, api_duration) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (data['cat'], data['panel_name'], data['name'], data['price'], data['reseller_price'], 999, data['apk'], data['validity'], data['device_limit'], data['api_pid'], duration)
    )
    await m.answer(f"✅ <b>Product added with AUTO KEY (API)!</b>\n\n📦 {html.escape(str(data['cat']))} -> {html.escape(str(data['panel_name']))} -> {html.escape(str(data['name']))}\n🔌 API PID: <code>{html.escape(data['api_pid'])}</code>{' | ' + html.escape(duration) if duration else ''}\n💰 User Price: {fmt_curr(data['price'])} | 👑 Reseller: {fmt_curr(data['reseller_price'])}", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.message(AdminStates.add_prod_keys)
async def add_prod_keys(m: Message, state: FSMContext):
    keys = [k.strip() for k in m.text.strip().split('\n') if k.strip()]
    data = await state.get_data()
    stock = len(keys)
    conn = sqlite3.connect('sfvolt.db')
    c = conn.cursor()
    c.execute("INSERT INTO products (category, panel_name, name, price_inr, reseller_price, stock, apk_link, validity, device_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (data['cat'], data['panel_name'], data['name'], data['price'], data['reseller_price'], stock, data['apk'], data['validity'], data['device_limit']))
    prod_id = c.lastrowid
    for k in keys: c.execute("INSERT INTO product_keys (product_id, key_text) VALUES (?, ?)", (prod_id, k))
    conn.commit()
    conn.close()
    await m.answer(f"✅ <b>Data Deployment Successful!</b>\n\n📦 Panel '{data['cat']}' -> Panel Name '{data['panel_name']}' -> Package '{data['name']}'\n🔒 Vault Stock: {stock} Keys injected.\n💰 User Price: {fmt_curr(data['price'])} | 👑 Reseller: {fmt_curr(data['reseller_price'])}", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_manage_prods")
async def admin_manage_prods(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    prods = db_query("SELECT id, name, category, panel_name, stock, is_active FROM products ORDER BY category, panel_name", fetchall=True)
    if not prods: return await call.message.edit_text("📦 Store Database is completely empty.", reply_markup=admin_back_kb(), parse_mode='HTML')
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in prods:
        status_dot = "🟢" if p[5] else "🔴"
        panel_name = p[3] if p[3] is not None else ""
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{status_dot} [{p[2]}] {panel_name} - {p[1]} (Stock: {p[4]})", callback_data=f"admin_view_p_{p[0]}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("📦 <b>Database Editor: Select Node to modify</b>", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("admin_view_p_"))
async def admin_view_product(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    try:
        p_id = int(call.data.split("_")[3])
        prod = db_query("SELECT * FROM products WHERE id=?", (p_id,), fetchone=True)
        if not prod: return await call.answer("❌ Architecture fault: Node lost!", show_alert=True)
        panel_name = prod[2] if prod[2] is not None else ""
        price_inr = safe_float(prod[4])
        reseller_price = safe_float(prod[5])
        text = (f"📦 <b><u>NODE DEEP DIVE DETAILS</u></b>\n━━━━━━━━━━━━━━━━━━\n<b>ID:</b> <code>{prod[0]}</code>\n<b>Panel Group:</b> {prod[1]}\n<b>Panel Name:</b> {panel_name}\n<b>Package Date/Time:</b> {prod[3]}\n<b>Standard Price:</b> {fmt_curr(price_inr)}\n👑 <b>Wholesale Price:</b> {fmt_curr(reseller_price)}\n<b>Vault Stock:</b> {prod[6]}\n<b>Payload Link:</b> {prod[7] if prod[7] else 'None'}\n<b>Time Config:</b> {prod[8]}\n<b>HWID Limit:</b> {prod[9]}\n<b>Visibility:</b> {'Active' if prod[10] else 'Hidden'}\n━━━━━━━━━━━━━━━━━━")
        api_row = db_query("SELECT api_product_id, api_duration FROM products WHERE id=?", (p_id,), fetchone=True)
        api_pid_now = (api_row[0] or "").strip() if api_row else ""
        api_dur_now = (api_row[1] or "").strip() if api_row else ""
        text += f"\n🔌 <b>API PID:</b> {('<code>' + html.escape(api_pid_now) + '</code>' + (' | ' + html.escape(api_dur_now) if api_dur_now else '') + ' (AUTO KEY ✅)') if api_pid_now else 'Not linked (manual keys)'}"
        toggle_btn_text = "Hide Product 👁‍🗨" if prod[10] else "Unhide Product 👁"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Edit Panel Group 🏷️", callback_data=f"edit_p_{p_id}_cat", style="primary"), InlineKeyboardButton(text="Edit Panel Name 🏷️", callback_data=f"edit_p_{p_id}_panel_name", style="primary")],
            [InlineKeyboardButton(text="Edit Package Name ✏️", callback_data=f"edit_p_{p_id}_name", style="primary")],
            [InlineKeyboardButton(text="Edit Price 💰", callback_data=f"edit_p_{p_id}_price", style="primary"), InlineKeyboardButton(text="Edit R-Price 👑", callback_data=f"edit_p_{p_id}_rprice", style="primary")],
            [InlineKeyboardButton(text="Edit Validity ⏳", callback_data=f"edit_p_{p_id}_validity", style="primary"), InlineKeyboardButton(text="Edit Device 📱", callback_data=f"edit_p_{p_id}_device", style="primary")],
            [InlineKeyboardButton(text="Edit APK Link 🔗", callback_data=f"edit_p_{p_id}_apk", style="primary"), InlineKeyboardButton(text="Add Keys ➕", callback_data=f"edit_p_{p_id}_keys", style="success")],
            [InlineKeyboardButton(text="🔌 Set / Change API PID", callback_data=f"edit_p_{p_id}_apipid", style="success")],
            [InlineKeyboardButton(text="Delete Key 🗑", callback_data=f"delkey_p_{p_id}", style="danger"), InlineKeyboardButton(text=toggle_btn_text, callback_data=f"toggle_p_{p_id}", style="danger")],
            [InlineKeyboardButton(text="Nuke Full Node 🗑", callback_data=f"delete_p_{p_id}", style="danger"), InlineKeyboardButton(text="BACK", callback_data="admin_manage_prods", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
        ])
        await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in admin_view_product: {e}")
        await call.message.edit_text(f"❌ Error loading product: {str(e)}", reply_markup=admin_back_kb(), parse_mode='HTML')

@dp.callback_query(F.data.startswith("toggle_p_"))
async def admin_toggle_product(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    p_id = int(call.data.split("_")[2])
    current = db_query("SELECT is_active FROM products WHERE id=?", (p_id,), fetchone=True)[0]
    new_val = 0 if current == 1 else 1
    db_query("UPDATE products SET is_active=? WHERE id=?", (new_val, p_id))
    await call.answer("Visibility updated successfully!", show_alert=True)
    await admin_view_product(call)

# ==============================================================================
# FIX: Edit product field – correctly handle different data types and multi-word fields
# ==============================================================================
@dp.callback_query(F.data.startswith("edit_p_"))
async def start_edit_product(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    # Use split with maxsplit=3 to keep field name intact (may contain underscores)
    parts = call.data.split("_", 3)
    if len(parts) < 4:
        return await call.answer("Invalid callback data.", show_alert=True)
    p_id = int(parts[2])
    field = parts[3]
    await state.update_data(edit_p_id=p_id, edit_field=field)
    if field == 'apipid':
        await call.message.edit_text("🔌 Send the <b>API PID (CODE)</b> for this product (e.g. <code>151</code>).\n\nType <code>off</code> to remove API link and use manual keys.", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_api_pid)
    elif field == 'keys':
        await call.message.edit_text("📥 <b>Vault Injection</b>\nPaste the <b>NEW KEYS</b> to append to the stock (1 key per line):", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_add_keys)
    else:
        field_name_map = {'cat': 'New Panel Group/Category Name', 'panel_name': 'New Panel Name', 'name': 'New Package/Date Name', 'price': 'New Standard Price in ₹', 'rprice': 'New Reseller Price in ₹', 'validity': 'New Time Validity String', 'device': 'New HWID Limit String', 'apk': 'New Payload Link (or type "none")'}
        await call.message.edit_text(f"✏️ Input the required data for: <b>{field_name_map.get(field, field)}</b>", reply_markup=admin_back_kb(), parse_mode='HTML')
        await state.set_state(AdminStates.wait_for_new_value)

@dp.message(AdminStates.wait_for_new_value)
async def process_edit_value(m: Message, state: FSMContext):
    data = await state.get_data()
    p_id = data['edit_p_id']; field = data['edit_field']; new_val = m.text.strip()
    
    # Convert price fields to float, others remain strings
    if field in ['price', 'rprice']:
        try:
            new_val = float(new_val)
        except ValueError:
            return await m.answer("❌ Invalid number format. Please enter a valid price (e.g., 500).")
    elif field == 'apk':
        new_val = "" if new_val.lower() == 'none' else new_val
    # For panel_name, cat, name, validity, device – keep as string
    
    db_col_map = {'cat': 'category', 'panel_name': 'panel_name', 'name': 'name', 'price': 'price_inr', 'rprice': 'reseller_price', 'validity': 'validity', 'device': 'device_limit', 'apk': 'apk_link'}
    db_query(f"UPDATE products SET {db_col_map[field]}=? WHERE id=?", (new_val, p_id))
    await m.answer("✅ <b>Node updated gracefully!</b>", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.message(AdminStates.wait_for_api_pid)
async def process_edit_api_pid(m: Message, state: FSMContext):
    data = await state.get_data()
    p_id = data['edit_p_id']
    txt = (m.text or "").strip()
    if txt.lower() in ("off", "none", "remove"):
        db_query("UPDATE products SET api_product_id='', api_duration='' WHERE id=?", (p_id,))
        await state.clear()
        return await m.answer("✅ API link removed. This product uses manual keys again.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.update_data(new_api_pid=txt)
    await m.answer("⏱ Send the API <b>duration</b> name (e.g. <code>1 Day</code>).\nType <code>none</code> if the PID is not shared.", parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_api_duration)

@dp.message(AdminStates.wait_for_api_duration)
async def process_edit_api_duration(m: Message, state: FSMContext):
    data = await state.get_data()
    p_id = data['edit_p_id']; pid = data['new_api_pid']
    txt = (m.text or "").strip()
    duration = "" if txt.lower() in ("none", "no", "skip", "") else txt
    db_query("UPDATE products SET api_product_id=?, api_duration=?, stock=999 WHERE id=?", (pid, duration, p_id))
    await state.clear()
    await m.answer(f"✅ <b>API linked!</b> PID <code>{html.escape(pid)}</code>{' | ' + html.escape(duration) if duration else ''}\nKeys now come automatically on every purchase.", reply_markup=admin_kb(), parse_mode='HTML')

@dp.message(AdminStates.wait_for_add_keys)
async def process_add_keys(m: Message, state: FSMContext):
    data = await state.get_data()
    p_id = data['edit_p_id']
    keys = [k.strip() for k in m.text.strip().split('\n') if k.strip()]
    if len(keys) == 0: return await m.answer("❌ Protocol breach: Zero valid keys found.", reply_markup=admin_kb(), parse_mode='HTML')
    conn = sqlite3.connect('sfvolt.db')
    c = conn.cursor()
    for k in keys: c.execute("INSERT INTO product_keys (product_id, key_text) VALUES (?, ?)", (p_id, k))
    c.execute("UPDATE products SET stock = stock + ? WHERE id=?", (len(keys), p_id))
    conn.commit(); conn.close()
    await m.answer(f"✅ <b>Vault Secure!</b> {len(keys)} new keys appended and encrypted.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data.startswith("delete_p_"))
async def admin_delete_product(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    p_id = int(call.data.split("_")[2])
    db_query("DELETE FROM products WHERE id=?", (p_id,))
    db_query("DELETE FROM product_keys WHERE product_id=?", (p_id,))
    await call.answer("☢️ Nuclear wipe successful! Node and vault deleted.", show_alert=True)
    await admin_manage_prods(call)

@dp.callback_query(F.data.startswith("delkey_p_"))
async def admin_delete_key_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    p_id = int(call.data.split("_")[2])
    await state.update_data(del_p_id=p_id)
    await call.message.edit_text("🗑 Send the <b>exact string match</b> of the key you wish to purge from the vault:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_delete_key)

@dp.message(AdminStates.wait_for_delete_key)
async def process_delete_key(m: Message, state: FSMContext):
    data = await state.get_data()
    p_id = data['del_p_id']
    key_to_delete = m.text.strip()
    key_data = db_query("SELECT id, is_used FROM product_keys WHERE product_id=? AND key_text=?", (p_id, key_to_delete), fetchone=True)
    if not key_data: return await m.answer("❌ Key not found. Check logs and try again.", reply_markup=admin_back_kb(), parse_mode='HTML')
    if key_data[1] == 1: return await m.answer("⚠️ Action Blocked: This key has already been dispatched to a user.", reply_markup=admin_back_kb(), parse_mode='HTML')
    db_query("DELETE FROM product_keys WHERE id=?", (key_data[0],))
    db_query("UPDATE products SET stock = stock - 1 WHERE id=?", (p_id,))
    await m.answer(f"✅ Key <code>{key_to_delete}</code> securely purged from vault.\n📦 Database indices updated.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

# ==============================================================================
# 21. ADMIN TICKETS, BROADCAST, COUPONS
# ==============================================================================
@dp.callback_query(F.data == "admin_view_tickets")
async def admin_view_tickets(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    tickets = db_query("SELECT id, user_id, message, created_at FROM tickets WHERE status='Open' LIMIT 1", fetchall=True)
    if not tickets: return await call.answer("✅ Zero pending issues. Grid is clean!", show_alert=True)
    t = tickets[0]
    text = (f"🎫 <b><u>ACTIVE TICKET #{t[0]}</u></b>\n👤 <b>Origin UID:</b> <code>{t[1]}</code>\n📅 <b>Timestamp:</b> {t[3]}\n\n📝 <b>Payload:</b>\n{t[2]}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Formulate Reply", callback_data=f"reply_ticket_{t[0]}_{t[1]}", style="primary")],
        [InlineKeyboardButton(text="❌ Force Close Ticket", callback_data=f"close_ticket_{t[0]}", style="danger")],
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket(call: CallbackQuery):
    ticket_id = call.data.split("_")[2]
    db_query("UPDATE tickets SET status='Closed' WHERE id=?", (ticket_id,))
    await call.answer("✅ Status set to Closed.", show_alert=True)
    await admin_view_tickets(call) 

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    ticket_id, user_id = data[2], data[3]
    await state.update_data(ticket_id=ticket_id, user_id=user_id)
    await call.message.edit_text(f"💬 Formulating reply for node <code>{user_id}</code>.\n\nType your message payload:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.ticket_reply_msg)

@dp.message(AdminStates.ticket_reply_msg)
async def send_ticket_reply(m: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await bot.send_message(data['user_id'], f"📞 <b>Admin Reply (Ref #{data['ticket_id']}):</b>\n\n{m.text}", parse_mode='HTML')
        db_query("UPDATE tickets SET status='Closed' WHERE id=?", (data['ticket_id'],))
        await m.answer("✅ Payload delivered and connection closed successfully.", reply_markup=admin_kb(), parse_mode='HTML')
    except Exception as e: await m.answer(f"❌ Transmission Error: {e}", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_broadcast_btn")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("📢 <b>Mass Broadcast Protocol</b>\n\nSend the rich message payload you wish to transmit globally across the grid:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.broadcast_msg)

@dp.message(AdminStates.broadcast_msg)
async def admin_broadcast_send(message: Message, state: FSMContext):
    users = db_query("SELECT user_id FROM users", fetchall=True)
    sent, failed = 0, 0
    m = await message.answer("⏳ Broadcast protocol initiated... Do not interrupt.", parse_mode='HTML')
    for u in users:
        try:
            await message.send_copy(chat_id=u[0])
            sent += 1
        except Exception: failed += 1
        await asyncio.sleep(0.06) 
    await m.edit_text(f"✅ <b>Global Broadcast Complete!</b>\n\n🟢 Nodes reached: {sent}\n🔴 Nodes failed/blocked: {failed}", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_create_coupon")
async def admin_create_coupon_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("🎟 Enter a highly secure alphanumeric sequence for the Promo Code:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.add_coupon_code)

@dp.message(AdminStates.add_coupon_code)
async def admin_coupon_code(m: Message, state: FSMContext):
    await state.update_data(code=m.text.strip().upper())
    await m.answer("💰 Enter the monetary reward payload in <b>RUPEES (₹)</b>:", parse_mode='HTML')
    await state.set_state(AdminStates.add_coupon_amount)

@dp.message(AdminStates.add_coupon_amount)
async def admin_coupon_amount(m: Message, state: FSMContext):
    try:
        await state.update_data(amount=float(m.text)) 
        await m.answer("👥 Enter the exact maximum threshold uses for this code:", parse_mode='HTML')
        await state.set_state(AdminStates.add_coupon_uses)
    except ValueError: await m.answer("❌ Non-numerical data detected. Aborting.")

@dp.message(AdminStates.add_coupon_uses)
async def admin_coupon_uses(m: Message, state: FSMContext):
    try:
        uses = int(m.text)
        data = await state.get_data()
        db_query("INSERT OR REPLACE INTO coupons (code, amount, uses_left) VALUES (?, ?, ?)", (data['code'], data['amount'], uses))
        await m.answer(f"✅ Protocol <b>{data['code']}</b> encoded!\nReward Vector: {fmt_curr(data['amount'])}\nThreshold Limit: {uses} executions.", reply_markup=admin_kb(), parse_mode='HTML')
        await state.clear()
    except ValueError: await m.answer("❌ Non-numerical data detected. Aborting.")

# ==============================================================================
# 22. ADMIN RESELLER & SPIN SETTINGS
# ==============================================================================
@dp.callback_query(F.data == "admin_reseller_menu")
async def admin_reseller_menu(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    status_check = db_query("SELECT value FROM settings WHERE key='reseller_system_status'", fetchone=True)
    sys_status = status_check[0] if status_check else "ON"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Grant Reseller Rights", callback_data="reseller_make", style="success"), InlineKeyboardButton(text="➖ Revoke Reseller", callback_data="reseller_remove", style="danger")],
        [InlineKeyboardButton(text="📋 Audit Active Resellers", callback_data="reseller_view", style="primary")],
        [InlineKeyboardButton(text=f"{'🟢' if sys_status == 'ON' else '🔴'} Auto-Upgrade System: {sys_status}", callback_data="admin_toggle_reseller_sys", style="success" if sys_status == 'ON' else "danger")], 
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text("👑 <b>Wholesale Reseller Protocols</b>\nSelect administrative action:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "admin_toggle_reseller_sys")
async def toggle_reseller_sys(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    res = db_query("SELECT value FROM settings WHERE key='reseller_system_status'", fetchone=True)
    current = res[0] if res else 'ON'
    new_status = 'OFF' if current == 'ON' else 'ON'
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('reseller_system_status', ?)", (new_status,))
    await admin_reseller_menu(call)

@dp.callback_query(F.data.in_(["reseller_make", "reseller_remove"]))
async def reseller_prompt_id(call: CallbackQuery, state: FSMContext):
    action = call.data
    await state.update_data(reseller_action=action)
    await call.message.edit_text("👤 Identify target node. Input <b>User ID</b> or <b>@username</b>:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.reseller_manage_id)

@dp.message(AdminStates.reseller_manage_id)
async def process_reseller_manage(m: Message, state: FSMContext):
    data = await state.get_data()
    target = m.text.strip()
    if target.startswith('@'): target = target[1:]
    user_q = db_query("SELECT user_id, first_name FROM users WHERE user_id=? OR username=? COLLATE NOCASE", (target, target), fetchone=True)
    if not user_q: return await m.answer("❌ Target completely ghosted. Not in database.", reply_markup=admin_back_kb(), parse_mode='HTML')
    u_id, u_name = user_q[0], user_q[1]
    if data['reseller_action'] == "reseller_make":
        db_query("UPDATE users SET is_reseller=1, reseller_since=?, account_type='Reseller' WHERE user_id=?", (datetime.now().strftime("%Y-%m-%d"), u_id))
        await m.answer(f"✅ Credentials upgraded. <b>{u_name}</b> (<code>{u_id}</code>) has reseller rights.", reply_markup=admin_kb(), parse_mode='HTML')
    else:
        db_query("UPDATE users SET is_reseller=0, account_type='Regular' WHERE user_id=?", (u_id,))
        await m.answer(f"✅ Credentials revoked. <b>{u_name}</b> (<code>{u_id}</code>) is back to regular user.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "reseller_view")
async def reseller_view(call: CallbackQuery):
    resellers = db_query("SELECT user_id, first_name, username FROM users WHERE is_reseller=1", fetchall=True)
    if not resellers: return await call.message.edit_text("📋 Zero active resellers found.", reply_markup=admin_back_kb(), parse_mode='HTML')
    text = "👑 <b><u>ACTIVE RESELLER AUDIT LOG</u></b> 👑\n━━━━━━━━━━━━━━━━━━\n"
    for r in resellers:
        uname = f"(@{r[2]})" if r[2] else ""
        text += f"👤 {r[1]} {uname}\n🆔 <code>{r[0]}</code>\n\n"
    await call.message.edit_text(text, reply_markup=admin_back_kb(), parse_mode='HTML')


@dp.callback_query(F.data == "admin_toggle_bot")
async def toggle_bot(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    res = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
    current = res[0] if res else 'ON'
    new_status = 'OFF' if current == 'ON' else 'ON'
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('bot_status', ?)", (new_status,))
    await call.message.edit_reply_markup(reply_markup=admin_kb())


@dp.callback_query(F.data == "admin_set_video")
async def admin_set_video_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("📹 Input direct streaming / YouTube Link for Tutorial system:\n<i>(Or type 'None' to clear registry):</i>", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_howto_video)

@dp.message(AdminStates.wait_for_howto_video)
async def exec_set_video(m: Message, state: FSMContext):
    link = m.text.strip()
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('how_to_video', ?)", (link,))
    await m.answer("✅ Routing complete. Video linked.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()


@dp.callback_query(F.data == "admin_edit_emojis")
async def admin_edit_emojis(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    rows = db_query("SELECT key, value FROM settings WHERE key LIKE 'emoji_%' ORDER BY key", fetchall=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for row in rows:
        key = row[0]
        slot = key.replace("emoji_", "")
        current_id = row[1] if row[1] else "Not set"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{slot} (ID: {current_id})", callback_data=f"edit_emoji_{slot}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("🎨 <b>Edit All Emojis</b>\nChoose an emoji slot to change its ID:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("edit_emoji_"))
async def admin_edit_emoji_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    slot = call.data.split("edit_emoji_", 1)[1]
    await state.update_data(emoji_slot=slot)
    current = get_setting(f"emoji_{slot}", "Not set")
    await call.message.edit_text(f"✏️ Enter new emoji ID for <b>{slot}</b>:\nCurrent: {current}\n(Leave empty to reset to default)", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_emoji_slot)

@dp.message(AdminStates.wait_for_emoji_slot)
async def save_emoji_slot(m: Message, state: FSMContext):
    data = await state.get_data()
    slot = data['emoji_slot']
    new_id = m.text.strip()
    if new_id == "":
        db_query("DELETE FROM settings WHERE key=?", (f"emoji_{slot}",))
        await m.answer(f"✅ Reset emoji for '{slot}' to default.", reply_markup=admin_kb(), parse_mode='HTML')
    else:
        if not new_id.isdigit():
            await m.answer("❌ Invalid ID! Must be numeric.", reply_markup=admin_kb(), parse_mode='HTML')
            return
        set_setting(f"emoji_{slot}", new_id)
        await m.answer(f"✅ Emoji for '{slot}' updated to ID {new_id}.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_edit_ui_menu")
async def admin_edit_ui_menu(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Edit Start Menu Text", callback_data="edit_ui_start", style="primary")],
        [InlineKeyboardButton(text="Edit VIP Menu Text", callback_data="edit_ui_vip", style="primary")],
        [InlineKeyboardButton(text="Edit Add Balance Text", callback_data="edit_ui_add_balance", style="primary")],
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text("✏️ <b>Edit User Interface Texts</b>\nSelect which text you want to modify:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("edit_ui_"))
async def admin_edit_ui_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    ui_key = call.data.split("_")[2]
    await state.update_data(ui_key=ui_key)
    current_text = get_ui_text(ui_key)
    await call.message.edit_text(f"📝 Send the new text for <b>{ui_key.upper()}</b> menu.\n\nCurrent text:\n{current_text}", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.edit_ui_text)

@dp.message(AdminStates.edit_ui_text)
async def admin_save_ui_text(m: Message, state: FSMContext):
    data = await state.get_data()
    ui_key = data['ui_key']
    new_text = m.text
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"ui_{ui_key}", new_text))
    await m.answer(f"✅ UI text <b>{ui_key}</b> updated successfully!", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_edit_reseller_price")
async def admin_edit_reseller_price_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    prods = db_query("SELECT id, name, category, panel_name, reseller_price FROM products ORDER BY category, panel_name", fetchall=True)
    if not prods: return await call.message.edit_text("No products to edit.", reply_markup=admin_back_kb(), parse_mode='HTML')
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in prods:
        panel_name = p[3] if p[3] is not None else ""
        r_price = safe_float(p[4])
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{p[2]} - {panel_name} - {p[1]} (₹{r_price:.2f})", callback_data=f"edit_reseller_{p[0]}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("👑 <b>Edit Reseller Price per Product</b>\nSelect a product to change its wholesale price:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("edit_reseller_"))
async def admin_edit_reseller_price_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    prod_id = int(call.data.split("_")[2])
    await state.update_data(edit_reseller_prod_id=prod_id)
    await call.message.edit_text("💰 Enter the new <b>Reseller Price</b> in Rupees (₹) for this product:", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.edit_reseller_price)

@dp.message(AdminStates.edit_reseller_price)
async def admin_save_reseller_price(m: Message, state: FSMContext):
    try:
        new_price = float(m.text)
        data = await state.get_data()
        prod_id = data['edit_reseller_prod_id']
        db_query("UPDATE products SET reseller_price=? WHERE id=?", (new_price, prod_id))
        await m.answer(f"✅ Reseller price updated to {fmt_curr(new_price)} for product ID {prod_id}.", reply_markup=admin_kb(), parse_mode='HTML')
        await state.clear()
    except ValueError: await m.answer("❌ Invalid number. Please enter a valid price.")

@dp.callback_query(F.data == "admin_set_reseller_fee")
async def admin_set_reseller_fee(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("💰 Enter the new <b>Reseller Setup Fee</b> in Rupees (₹):\nCurrent: " + get_setting("reseller_setup_fee", "200.0"), reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_reseller_setup_fee)

@dp.message(AdminStates.wait_for_reseller_setup_fee)
async def admin_save_reseller_fee(m: Message, state: FSMContext):
    try:
        fee = float(m.text)
        set_setting("reseller_setup_fee", str(fee))
        await m.answer(f"✅ Reseller setup fee updated to {fmt_curr(fee)}.", reply_markup=admin_kb(), parse_mode='HTML')
        await state.clear()
    except ValueError: await m.answer("❌ Invalid number. Please enter a valid amount.")

@dp.callback_query(F.data == "admin_set_reseller_min")
async def admin_set_reseller_min(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("💳 Enter the new <b>Minimum Balance</b> required to become reseller (₹):\nCurrent: " + get_setting("reseller_min_balance", "500.0"), reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_reseller_min_balance)

@dp.message(AdminStates.wait_for_reseller_min_balance)
async def admin_save_reseller_min(m: Message, state: FSMContext):
    try:
        min_bal = float(m.text)
        set_setting("reseller_min_balance", str(min_bal))
        await m.answer(f"✅ Minimum reseller balance updated to {fmt_curr(min_bal)}.", reply_markup=admin_kb(), parse_mode='HTML')
        await state.clear()
    except ValueError: await m.answer("❌ Invalid number. Please enter a valid amount.")

@dp.callback_query(F.data == "admin_set_support_links")
async def admin_set_support_links(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Set Telegram Link", callback_data="admin_set_telegram", style="primary")],
        [InlineKeyboardButton(text="📱 Set WhatsApp Link", callback_data="admin_set_whatsapp", style="primary")],
        [InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")]
    ])
    await call.message.edit_text("📌 <b>Support Contact Links</b>\nSet the URLs for Telegram and WhatsApp support:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data == "admin_set_telegram")
async def admin_set_telegram(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("✈️ Enter the Telegram contact URL (e.g., https://t.me/YourSupport):", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_support_telegram)

@dp.message(AdminStates.wait_for_support_telegram)
async def save_telegram_link(m: Message, state: FSMContext):
    link = m.text.strip()
    set_setting("support_telegram", link)
    await m.answer("✅ Telegram support link updated!", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_set_whatsapp")
async def admin_set_whatsapp(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("📱 Enter the WhatsApp contact URL (e.g., https://wa.me/1234567890):", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_support_whatsapp)

@dp.message(AdminStates.wait_for_support_whatsapp)
async def save_whatsapp_link(m: Message, state: FSMContext):
    link = m.text.strip()
    set_setting("support_whatsapp", link)
    await m.answer("✅ WhatsApp support link updated!", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_set_category_emojis")
async def admin_set_category_emojis(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for cat in FIXED_CATEGORIES:
        current = get_setting(f"cat_emoji_{cat}", "Not set")
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{cat} (ID: {current})", callback_data=f"set_cat_emoji_{cat}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("🎨 <b>Set Category Emojis</b>\nChoose a category to set its custom emoji ID:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("set_cat_emoji_"))
async def admin_set_category_emoji_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    category = call.data.split("set_cat_emoji_", 1)[1]
    await state.update_data(cat_emoji_category=category)
    await call.message.edit_text(f"🎨 Enter the emoji ID for <b>{category}</b>:\n(Leave empty to reset to default)", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_category_emoji)

@dp.message(AdminStates.wait_for_category_emoji)
async def save_category_emoji(m: Message, state: FSMContext):
    data = await state.get_data()
    category = data['cat_emoji_category']
    emoji_id = m.text.strip()
    if emoji_id == "":
        db_query("DELETE FROM settings WHERE key=?", (f"cat_emoji_{category}",))
        await m.answer(f"✅ Reset emoji for {category} to default.", reply_markup=admin_kb(), parse_mode='HTML')
    else:
        if not emoji_id.isdigit():
            await m.answer("❌ Invalid ID! Must be numeric.", reply_markup=admin_kb(), parse_mode='HTML')
            return
        set_setting(f"cat_emoji_{category}", emoji_id)
        await m.answer(f"✅ Emoji set for {category} successfully!", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

@dp.callback_query(F.data == "admin_set_panel_emojis")
async def admin_set_panel_emojis(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    panels = db_query("SELECT DISTINCT panel_name FROM products WHERE panel_name != '' ORDER BY panel_name", fetchall=True)
    if not panels:
        await call.message.edit_text("No panel names found in products.", reply_markup=admin_back_kb(), parse_mode='HTML')
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for p in panels:
        panel = p[0]
        current = get_setting(f"panel_emoji_{panel}", "Not set")
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{panel} (ID: {current})", callback_data=f"set_panel_emoji_{panel}", style="primary")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Back to Admin", callback_data="admin_panel_back", icon_custom_emoji_id=get_emoji_icon("back"), style="danger")])
    await call.message.edit_text("🖼 <b>Set Panel Emojis</b>\nChoose a panel name to set its custom emoji ID:", reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith("set_panel_emoji_"))
async def admin_set_panel_emoji_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    panel_name = call.data.split("set_panel_emoji_", 1)[1]
    await state.update_data(panel_emoji_name=panel_name)
    await call.message.edit_text(f"🎨 Enter the emoji ID for panel <b>{panel_name}</b>:\n(Leave empty to reset to default)", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_panel_emoji_id)

@dp.message(AdminStates.wait_for_panel_emoji_id)
async def save_panel_emoji(m: Message, state: FSMContext):
    data = await state.get_data()
    panel_name = data['panel_emoji_name']
    emoji_id = m.text.strip()
    if emoji_id == "":
        db_query("DELETE FROM settings WHERE key=?", (f"panel_emoji_{panel_name}",))
        await m.answer(f"✅ Reset emoji for panel '{panel_name}'.", reply_markup=admin_kb(), parse_mode='HTML')
    else:
        if not emoji_id.isdigit():
            await m.answer("❌ Invalid ID! Must be numeric.", reply_markup=admin_kb(), parse_mode='HTML')
            return
        set_setting(f"panel_emoji_{panel_name}", emoji_id)
        await m.answer(f"✅ Emoji set for panel '{panel_name}'!", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

# ==============================================================================
# 23. ADMIN FAMPAY SETUP
# ==============================================================================
@dp.callback_query(F.data == "admin_setup_fampay")
async def setup_fampay_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    key = get_fg_key()
    shown = f"{key[:8]}... (hidden)" if key else "Not set"
    await call.message.edit_text(
        f"⚙️ <b>FAMGATEWAY SETUP</b>\n\n"
        f"🔑 Current API Key: {shown}\n\n"
        f"Send your <b>FamGateway API Key</b> (starts with <code>sk_live_</code>):\n<i>(Type /cancel to abort)</i>",
        reply_markup=admin_back_kb(), parse_mode='HTML'
    )
    await state.set_state(AdminStates.wait_for_fampay_api)

@dp.message(AdminStates.wait_for_fampay_api)
async def setup_fampay_api(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID: return
    if (m.text or "").strip() == '/cancel':
        await state.clear()
        return await m.answer("Sequence killed.", reply_markup=admin_kb(), parse_mode='HTML')
    api_key = (m.text or "").strip()
    if len(api_key) < 10 or " " in api_key:
        return await m.answer("❌ That does not look like a valid API key. Send the <code>sk_live_...</code> key again or /cancel.", parse_mode='HTML')
    set_setting("famgateway_api_key", api_key)
    try: await m.delete()  # don't leave the secret key in chat history
    except Exception: pass
    await m.answer("✅ <b>FamGateway configured!</b>\n\n🔑 API Key: Saved\nPayments are now live: users get a Pay Now link and are credited automatically.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

# ==============================================================================
# 24. ADMIN BINANCE SETUP
# ==============================================================================
@dp.callback_query(F.data == "admin_setup_binance")
async def setup_binance_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("🪙 <b>CRYPTO NODE INIT: Step 1/3</b>\nInput Master <b>Binance API Key</b>:\n<i>(Type /cancel to halt protocol)</i>", reply_markup=admin_back_kb(), parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_binance_api)

@dp.message(AdminStates.wait_for_binance_api)
async def setup_binance_api(m: Message, state: FSMContext):
    if m.text == '/cancel':
        await state.clear()
        return await m.answer("Sequence aborted.", reply_markup=admin_kb(), parse_mode='HTML')
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('binance_api', ?)", (m.text.strip(),))
    await m.answer("🪙 <b>CRYPTO NODE INIT: Step 2/3</b>\nNow inject the highly secure <b>Binance Secret Key</b>:", parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_binance_secret)

@dp.message(AdminStates.wait_for_binance_secret)
async def setup_binance_secret(m: Message, state: FSMContext):
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('binance_secret', ?)", (m.text.strip(),))
    await m.answer("🪙 <b>CRYPTO NODE INIT: Step 3/3</b>\nFinal variable: Set the public <b>USDT Deposit Address (TRC20/BEP20)</b>\nUsers will broadcast to this ledger:", parse_mode='HTML')
    await state.set_state(AdminStates.wait_for_binance_address)

@dp.message(AdminStates.wait_for_binance_address)
async def setup_binance_address(m: Message, state: FSMContext):
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES ('binance_address', ?)", (m.text.strip(),))
    await m.answer("✅ <b>Blockchain node synchronized.</b> Crypto gateway is fully armed.", reply_markup=admin_kb(), parse_mode='HTML')
    await state.clear()

# ==============================================================================
# 24b. ADMIN: RESELLER API COMMANDS
# ==============================================================================
@dp.message(Command("testemoji"))
async def cmd_testemoji(m: Message):
    """Admin: checks whether Telegram really accepts the premium emojis from this bot."""
    if m.from_user.id != ADMIN_ID: return
    lines, total = [], 0
    for slot, (fb, default_id) in START_MENU_EMOJIS.items():
        stored = get_setting(f"emoji_{slot}", "")
        emoji_id = stored if stored and stored.isdigit() else default_id
        total += 1
        lines.append(f"{get_emoji_fb(slot, fb, default_id)} {slot} — <code>{emoji_id}</code>")
    try:
        res = await m.answer("🧪 <b>Premium emoji test</b>\n" + "\n".join(lines), parse_mode='HTML')
    except Exception as e:
        return await m.answer(f"❌ Telegram rejected the message:\n<code>{html.escape(str(e))}</code>", parse_mode='HTML')
    accepted = sum(1 for e in (res.entities or []) if e.type == "custom_emoji")
    if accepted >= total:
        await m.answer(f"✅ Telegram accepted all {accepted}/{total} premium emojis. Code is fine - if you still see normal emojis, restart the bot with the new Main.py and send /start again.", parse_mode='HTML')
    elif accepted == 0:
        await m.answer("⚠️ Telegram accepted 0 premium emojis - it silently turned them into normal emojis.\n\nThis is a Telegram rule, not a code problem: premium emojis in a bot's messages work only if the <b>bot owner's account has Telegram Premium</b> (or the bot has a Fragment username).", parse_mode='HTML')
    else:
        await m.answer(f"⚠️ Telegram accepted only {accepted}/{total}. The others have wrong/non-existent IDs - check the ones that show as normal emoji above.", parse_mode='HTML')

@dp.message(Command("emojiid"))
async def cmd_emojiid(m: Message):
    """Admin: send /emojiid together with premium emojis, or reply to a message that has them."""
    if m.from_user.id != ADMIN_ID: return
    ents = list(m.entities or []) + list(m.caption_entities or [])
    src_text = m.text or m.caption or ""
    if m.reply_to_message:
        r = m.reply_to_message
        ents = list(r.entities or []) + list(r.caption_entities or [])
        src_text = r.text or r.caption or ""
    lines = []
    for e in ents:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            # Telegram offsets are in UTF-16 units
            u16 = src_text.encode("utf-16-le")
            ch = u16[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le", errors="ignore")
            lines.append(f"{len(lines) + 1}. {ch} → <code>{e.custom_emoji_id}</code>")
    if not lines:
        return await m.answer("Send <code>/emojiid</code> with premium emojis in the same message, or reply <code>/emojiid</code> to a message that contains them.", parse_mode='HTML')
    await m.answer("🎨 <b>Premium emoji IDs</b>\n" + "\n".join(lines) + "\n\nSet them in Admin → Edit All Emojis (slots e_cart, e_crown, e_game, e_user, e_100, e_chart, e_flag, e_mail, e_money, e_tap).", parse_mode='HTML')

@dp.message(Command("linkapi"))
async def cmd_linkapi(m: Message):
    if m.from_user.id != ADMIN_ID: return
    parts = (m.text or "").split(maxsplit=3)
    if len(parts) < 3:
        return await m.answer(
            "Usage:\n<code>/linkapi BOT_PRODUCT_ID API_PID [DURATION]</code>\n"
            "Example: <code>/linkapi 5 151 1 Day</code>\n"
            "Unlink: <code>/linkapi 5 off</code>", parse_mode='HTML')
    try: p_id = int(parts[1])
    except ValueError: return await m.answer("❌ BOT_PRODUCT_ID must be a number.")
    if not db_query("SELECT id FROM products WHERE id=?", (p_id,), fetchone=True):
        return await m.answer("❌ Product not found in bot.")
    if parts[2].lower() == "off":
        db_query("UPDATE products SET api_product_id='', api_duration='' WHERE id=?", (p_id,))
        return await m.answer(f"✅ Product #{p_id} unlinked from API (uses local keys again).")
    api_pid = parts[2].strip()
    duration = parts[3].strip() if len(parts) > 3 else ""
    # stock is only for display on API products; keys come live from the supplier
    db_query("UPDATE products SET api_product_id=?, api_duration=?, stock=999 WHERE id=?", (api_pid, duration, p_id))
    await m.answer(f"✅ Product #{p_id} linked to API PID <code>{html.escape(api_pid)}</code>"
                   f"{' | duration <code>' + html.escape(duration) + '</code>' if duration else ''}\n"
                   f"Keys will now be generated automatically on purchase.", parse_mode='HTML')

@dp.message(Command("apibalance"))
async def cmd_apibalance(m: Message):
    if m.from_user.id != ADMIN_ID: return
    ok, data = await galu_request("balance")
    if not ok: return await m.answer(f"❌ {html.escape(str(data))}", parse_mode='HTML')
    await m.answer(f"💰 <b>Supplier wallet</b>\n<code>{html.escape(json.dumps(data, indent=2)[:3500])}</code>", parse_mode='HTML')

@dp.message(Command("apiproducts"))
async def cmd_apiproducts(m: Message):
    if m.from_user.id != ADMIN_ID: return
    ok, data = await galu_request("products")
    if not ok: return await m.answer(f"❌ {html.escape(str(data))}", parse_mode='HTML')
    raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    await m.answer_document(BufferedInputFile(raw, filename="api_products.json"), caption="Supplier products (PIDs & stock)")

# ==============================================================================
# 24c. GLOBAL PREMIUM EMOJI ENGINE
#      Every normal emoji we have a premium ID for is converted automatically in
#      ALL messages and in the icon of ALL inline buttons - on every screen.
# ==============================================================================
AUTO_EMOJI_MAP: Dict[str, str] = {}
_AUTO_EMOJI_RE = None
_AUTO_EMOJI_ONLY_RE = None

def _norm_emoji(ch: str) -> str:
    return ch.replace("\ufe0f", "").strip()

def rebuild_auto_emoji() -> None:
    """Load defaults + admin-learned emojis and rebuild the regex."""
    global AUTO_EMOJI_MAP, _AUTO_EMOJI_RE, _AUTO_EMOJI_ONLY_RE
    m: Dict[str, str] = {}
    for slot, (fb, default_id) in START_MENU_EMOJIS.items():
        m.setdefault(_norm_emoji(fb), default_id)
    try:
        m.update(json.loads(get_setting("auto_emoji_map", "{}") or "{}"))
    except ValueError:
        logger.warning("auto_emoji_map setting is corrupted; using defaults only.")
    AUTO_EMOJI_MAP = {k: str(v) for k, v in m.items() if k and str(v).isdigit()}
    if not AUTO_EMOJI_MAP:
        _AUTO_EMOJI_RE = _AUTO_EMOJI_ONLY_RE = None
        return
    alt = "|".join(re.escape(k) + "\ufe0f?" for k in sorted(AUTO_EMOJI_MAP, key=len, reverse=True))
    _AUTO_EMOJI_ONLY_RE = re.compile("(" + alt + ")")
    _AUTO_EMOJI_RE = re.compile(r"(<tg-emoji\b[^>]*>.*?</tg-emoji>)|(<[^>]+>)|(" + alt + ")", re.DOTALL)

def save_auto_emoji_map(custom: Dict[str, str]) -> None:
    set_setting("auto_emoji_map", json.dumps(custom, ensure_ascii=False))
    rebuild_auto_emoji()

def load_custom_auto_emoji() -> Dict[str, str]:
    try:
        return json.loads(get_setting("auto_emoji_map", "{}") or "{}")
    except ValueError:
        return {}

def premium_ify(text: str) -> str:
    """Wrap every known normal emoji in <tg-emoji> (skips ones already premium and anything inside tags)."""
    if not text or _AUTO_EMOJI_RE is None:
        return text
    count = 0
    def _repl(mo):
        nonlocal count
        if mo.group(1) or mo.group(2):
            return mo.group(0)
        emoji_id = AUTO_EMOJI_MAP.get(_norm_emoji(mo.group(3)))
        if not emoji_id or count >= 90:      # Telegram allows ~100 entities per message
            return mo.group(0)
        count += 1
        return f'<tg-emoji emoji-id="{emoji_id}">{mo.group(3)}</tg-emoji>'
    return _AUTO_EMOJI_RE.sub(_repl, text)

def premium_buttons(markup):
    """Move a leading emoji of an inline button's text into its premium icon."""
    if _AUTO_EMOJI_ONLY_RE is None or not isinstance(markup, InlineKeyboardMarkup):
        return markup
    changed = False
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for b in row:
            if not getattr(b, "icon_custom_emoji_id", None) and b.text:
                mo = _AUTO_EMOJI_ONLY_RE.match(b.text.lstrip())
                if mo:
                    rest = b.text.lstrip()[mo.end():].strip()
                    emoji_id = AUTO_EMOJI_MAP.get(_norm_emoji(mo.group(1)))
                    if emoji_id and rest:
                        b = b.model_copy(update={"text": rest, "icon_custom_emoji_id": emoji_id})
                        changed = True
            new_row.append(b)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if changed else markup

class PremiumEmojiMiddleware(BaseRequestMiddleware):
    TEXT_METHODS = (SendMessage, EditMessageText)
    CAPTION_METHODS = (EditMessageCaption, SendPhoto, SendDocument, SendVideo, SendAnimation)

    async def __call__(self, make_request, bot, method):
        field = "text" if isinstance(method, self.TEXT_METHODS) else ("caption" if isinstance(method, self.CAPTION_METHODS) else None)
        if field is None:
            return await make_request(bot, method)
        orig_text = getattr(method, field, None)
        orig_markup = getattr(method, "reply_markup", None)
        pm = getattr(method, "parse_mode", None)
        html_mode = pm is not None and not (isinstance(pm, str) and pm.upper() != "HTML")
        new_text = premium_ify(orig_text) if (isinstance(orig_text, str) and html_mode) else orig_text
        new_markup = premium_buttons(orig_markup) if orig_markup is not None else orig_markup
        if new_text == orig_text and new_markup is orig_markup:
            return await make_request(bot, method)
        try:
            setattr(method, field, new_text)
            if new_markup is not orig_markup:
                method.reply_markup = new_markup
            return await make_request(bot, method)
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "not modified" in msg or not any(w in msg for w in ("entit", "emoji", "parse", "button", "icon")):
                raise
            logger.warning(f"Premium emoji conversion rejected by Telegram ({e}); sending original.")
            setattr(method, field, orig_text)
            method.reply_markup = orig_markup
            return await make_request(bot, method)

def _entity_emojis(m: Message) -> List[Tuple[str, str]]:
    """(normal emoji char, premium id) for every premium emoji in the message or in the message replied to."""
    src = m.reply_to_message or m
    text = src.text or src.caption or ""
    ents = list(src.entities or []) + list(src.caption_entities or [])
    u16 = text.encode("utf-16-le")
    out = []
    for e in ents:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            ch = u16[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le", errors="ignore")
            out.append((_norm_emoji(ch), e.custom_emoji_id))
    return out

@dp.message(Command("learnemoji"))
async def cmd_learnemoji(m: Message):
    """Admin: send premium emojis (with /learnemoji) or reply /learnemoji to a message that has them."""
    if m.from_user.id != ADMIN_ID: return
    found = _entity_emojis(m)
    if not found:
        return await m.answer("Send <code>/learnemoji</code> together with premium emojis (e.g. <code>/learnemoji ✅❌📦🔑</code> using your premium emojis), or reply <code>/learnemoji</code> to a message that has them.\n\nThe bot then uses those premium emojis automatically on EVERY screen and button.", parse_mode='HTML')
    custom = load_custom_auto_emoji()
    for ch, cid in found:
        custom[ch] = cid
    save_auto_emoji_map(custom)
    await m.answer("✅ <b>Learned %d premium emoji(s)</b>\n%s\n\nThey now replace the normal emoji everywhere (messages + button icons)." % (len(found), " ".join(c for c, _ in found)), parse_mode='HTML')

@dp.message(Command("setemoji"))
async def cmd_setemoji(m: Message):
    if m.from_user.id != ADMIN_ID: return
    parts = (m.text or "").split()
    if len(parts) != 3 or not parts[2].isdigit():
        return await m.answer("Usage: <code>/setemoji ✅ 5368324170671202286</code>", parse_mode='HTML')
    custom = load_custom_auto_emoji()
    custom[_norm_emoji(parts[1])] = parts[2]
    save_auto_emoji_map(custom)
    await m.answer(f"✅ {parts[1]} will now show as premium emoji <code>{parts[2]}</code> everywhere.", parse_mode='HTML')

@dp.message(Command("delemoji"))
async def cmd_delemoji(m: Message):
    if m.from_user.id != ADMIN_ID: return
    parts = (m.text or "").split()
    if len(parts) != 2:
        return await m.answer("Usage: <code>/delemoji ✅</code>", parse_mode='HTML')
    custom = load_custom_auto_emoji()
    custom.pop(_norm_emoji(parts[1]), None)
    save_auto_emoji_map(custom)
    await m.answer("✅ Removed.")

@dp.message(Command("listemoji"))
async def cmd_listemoji(m: Message):
    if m.from_user.id != ADMIN_ID: return
    lines = [f"{k} → <code>{v}</code>" for k, v in AUTO_EMOJI_MAP.items()]
    await m.answer("🎨 <b>Auto premium emojis (%d)</b>\n%s" % (len(lines), "\n".join(lines) if lines else "none"), parse_mode='HTML')

# ==============================================================================
# 25. BOOTSTRAPPING & MAIN
# ==============================================================================
async def main() -> None:
    init_db()
    logger.info("Initializing DB structure...")
    migrate_categories()
    rebuild_auto_emoji()
    bot.session.middleware(PremiumEmojiMiddleware())
    logger.info(f"Global premium emoji engine active ({len(AUTO_EMOJI_MAP)} emojis).")
    asyncio.create_task(auto_verify_task())
    logger.info("FamPay Auto-Verifier Daemon Running in Background.")
    logger.info("🚀 CORE SYSTEM IS FULLY OPERATIONAL...")
    try:
        await dp.start_polling(bot)
    except Exception as err:
        logger.error(f"Critical System Failure in Polling: {err}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logger.info("System shutting down gracefully. Goodbye.")wn gracefully. Goodbye.")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("System shutting down gracefully. Goodbye.")wn gracefully. Goodbye.")
