import asyncio
import sqlite3
import random
import logging
import time
import os
import aiohttp
from aiohttp import web
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
BOT_TOKEN = "8519269631"
BOT_USERNAME = "@sfvolt_bot"
ADMIN_ID = 7255956225
ADMIN_CONTACT = "@sfvolt"

# --- FAMGATEWAY (famgateway.in) AUTO PAYMENT ---
FAMGATEWAY_API_KEY = ""
FAMGATEWAY_BASE = "https://famgateway.in"
MIN_DEPOSIT = 1.0
MAX_DEPOSIT = 50000.0

# --- GALUMODZ RESELLER API (automatic key supplier) ---
SFVOLT_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
sfvolt_API_KEY = "5d156aa13af9e36034687*******1"

USDT_TO_INR = 90.0
VIP_DISCOUNT_PERCENTAGE = 10.0
VIP_PRICE_INR = 1000.0

WELCOME_STICKER_ID = "CAACAgIAAxkBAAEU-WZmH_..."

FIXED_CATEGORIES = [
    "ANDROID NON ROOT PANEL",
    "ANDROID ROOT PANEL",
    "PC PANEL"
]

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
# 3. STRING RESOURCES
# ==============================================================================
DIVIDER_LINE = "─" * 56

START_MENU_EMOJIS = {
    'e_cart':  ('🛒', '5451937962629544243'),
    'e_crown': ('👑', '5433758796289685818'),
    'e_game':  ('🎮', '6050924877802640640'),
    'e_user':  ('👤', '5927266769281487788'),
    'e_100':   ('💯', '6001517283426439371'),
    'e_chart': ('📊', '6165617418187050280'),
    'e_flag':  ('🇮🇳', '6195196922379115661'),
    'e_mail':  ('📩', '6194884545112709374'),
    'e_money': ('💰', '6001434068435079689'),
    'e_tap':   ('👑', '6057415823222379852'),
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
        "• Flat 15% off on ALL products\n"
        "• Priority Support\n"
        "• Exclusive VIP-only giveaways\n\n"
        "💳 <b>VIP Price:</b> ₹299.00 (Lifetime)\n"
        "👤 <b>Your Status:</b> {vip_status}"
    ),
    "add_balance_menu": (
        "{add_balance} <b>ADD BALANCE</b> {info_icon}\n\n"
        "{info_icon} Select your preferred payment method. {check_icon}\n\n"
        "┣ {upi} UPI — Fast Indian payments {checkbox_icon}\n"
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

    for k, v in kwargs.items():
        template = template.replace("{" + k + "}", str(v))
    template = re.sub(r"\{e_[a-z0-9_]+\}", "", template)
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

def migrate_categories() -> None:
    done = get_setting("migration_done", "0")
    for slot, emoji_id in DEFAULT_EMOJIS.items():
        set_setting(f"emoji_{slot}", emoji_id)
    set_setting("ui_start_menu", UI_TEXTS['start_menu'])
    set_setting("ui_add_balance_menu", UI_TEXTS['add_balance_menu'])
    set_setting("ui_vip_menu", UI_TEXTS['vip_menu'])
    
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
    
    if done == "1":
        return
    
    mapping = {
        "android non root panel": "ANDROID NON ROOT PANEL",
        "android root panel": "ANDROID ROOT PANEL",
        "pc panel": "PC PANEL",
    }
    for old, new in mapping.items():
        db_query("UPDATE products SET category = ? WHERE LOWER(category) = ?", (new, old))
    
    set_setting("migration_done", "1")

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
                msg = "🚫 <b>ACCESS DENIED</b>\nYou have been banned from using this bot."
                if isinstance(event, Message): await event.answer(msg)
                elif isinstance(event, CallbackQuery): await event.answer(msg, show_alert=True)
                return
                
            status_check = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
            status = status_check[0] if status_check else 'ON'
            if status == 'OFF':
                msg = "⚠️ <b>Store Maintenance</b>\n\nThe store is currently offline for updates."
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
    
    wait_for_fampay_api = State()
    wait_for_fampay_upi = State()
    
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
# 9. FAMGATEWAY PAYMENT FUNCTIONS
# ==============================================================================
_FG_TIMEOUT = aiohttp.ClientTimeout(total=20)
_FG_MIN_GAP = 3.5
_fg_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
ORDER_VALID_SECONDS = 300
EXPIRY_GRACE_SECONDS = 90

def get_fg_key() -> str:
    for key in (get_setting("famgateway_api_key", ""), FAMGATEWAY_API_KEY):
        key = (key or "").strip()
        if key and not key.startswith("YOUR_"):
            return key
    return ""

def fg_amount_param(amount: float) -> str:
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
    conn = sqlite3.connect('sfvolt.db', timeout=15)
    try:
        if utr:
            dup = conn.execute(
                "SELECT 1 FROM transactions WHERE utr=? AND status='paid' AND order_id!=?", (utr, order_id)
            ).fetchone()
            if dup:
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
        if not info["credited"]:
            return await say(info["text"], back_kb())
        return

    past_expiry = bool(expires_at) and time.time() > expires_at + EXPIRY_GRACE_SECONDS
    if state == "expired" or (state in ("pending", "error") and past_expiry):
        db_query("UPDATE transactions SET status='expired' WHERE order_id=? AND status='pending'", (order_id,))
        return await say("⏳ <b>Payment link expired</b>\n\nNo payment was received for this order. Please create a new deposit.", _expired_kb())

    if state == "pending":
        text = (f"⏳ <b>Payment not received yet</b>\n\n💵 <b>Amount:</b> {fmt_curr(amount)}\n"
                f"🆔 <b>Order:</b> <code>{order_id}</code>\n\n"
                "Complete the payment using <b>Pay Now</b>, then tap <b>Verify Payment</b>.")
        if is_cb:
            return await reply_target.answer("⏳ Payment not received yet. Pay using Pay Now, then verify again.", show_alert=True)
        return await say(text, _pay_kb(order_id, checkout_url))

    err = msg or "Gateway busy"
    if is_cb:
        return await reply_target.answer(f"⚠️ {err}\nPlease try again in a few seconds.", show_alert=True)
    return await say(f"⚠️ <b>Gateway error:</b> {html.escape(err)}\nPlease tap Verify Payment again.", _pay_kb(order_id, checkout_url))

async def auto_verify_task() -> None:
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
                            await bot.send_message(user_id, f"⏳ <b>Payment link expired</b>\nOrder <code>{order_id}</code> was not paid in time.", reply_markup=_expired_kb(), parse_mode='HTML')
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
    except Exception as e:
        if "not modified" in str(e).lower():
            return
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
    text = f"💵 <b>— UPI DEPOSIT —</b> 💵\n\nSelect amount (₹1 – ₹50,000) or enter a custom amount."
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
    if not (MIN_DEPOSIT <= inr_amount <= MAX_DEPOSIT):
        return await message_obj.edit_text(f"❌ Deposit must be between ₹{MIN_DEPOSIT:g} and ₹{MAX_DEPOSIT:,.0f}.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')
    if not get_fg_key():
        return await message_obj.edit_text("⚠️ Payment gateway is currently offline.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

    result = await create_famgateway_order(user_id, inr_amount)
    if str(result.get("status", "")).lower() != "success":
        error_msg = html.escape(str(result.get("message") or "Unknown error"))
        return await message_obj.edit_text(f"❌ <b>Gateway Error:</b> {error_msg}", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    order_id = data.get("order_id")
    checkout_url = data.get("checkout_url")
    if not order_id or not checkout_url:
        return await message_obj.edit_text("❌ <b>Gateway Error:</b> invalid order response.", reply_markup=back_kb("gateway_inr"), parse_mode='HTML')

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
        f"2️⃣ After paying you come back to the bot automatically"
    )
    log_activity(user_id, "GENERATE_INVOICE_FAMGATEWAY", f"Amount: {inr_amount}, Order ID: {order_id}")
    await message_obj.edit_text(text, reply_markup=_pay_kb(order_id, checkout_url), parse_mode='HTML')

@dp.callback_query(F.data.startswith("verify_"))
async def manual_verify_callback(call: CallbackQuery):
    order_id = call.data.split("_", 1)[1]
    await run_payment_verification(call.from_user.id, order_id, call)

# ==============================================================================
# 13. SHOP
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
    await call.answer("⚠️ This duration is completely Out of Stock!", show_alert=True)

# ==============================================================================
# GALUMODZ RESELLER API HELPERS & FIXED BUY HANDLER
# ==============================================================================
USER_BUY_LOCKS: Dict[int, asyncio.Lock] = {}

def get_galu_api_key() -> str:
    return get_setting("galu_api_key", "") or GALU_API_KEY

async def galu_request(action: str, **fields) -> Tuple[bool, Any]:
    api_key = get_galu_api_key()
    payload = {"api_key": api_key, "action": action}
    payload.update({k: v for k, v in fields.items() if v not in (None, "")})
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(SFVOLT_API_URL, data=payload, headers={"X-API-Key": api_key}) as r:
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
    ok, data = await galu_request("buy", product_id=str(api_pid), duration=duration, quantity=quantity)
    if not ok:
        return False, str(data)
    if isinstance(data, dict) and data.get("status") == "success":
        key = data.get("key") or ((data.get("keys") or [None])[0])
        if key:
            return True, str(key)
        return False, "API returned success but no key."
    msg = (data.get("message") or data.get("error") or "Request failed") if isinstance(data, dict) else "Request failed"
    return False, str(msg)

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
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
    
    if user[0] < final_price: 
        return await call.answer(f"❌ Insufficient Balance! You need {fmt_curr(final_price)}.\nPlease Top Up your wallet.", show_alert=True)

    # --- STOCK & AVAILABILITY CHECK BEFORE DEDUCTING MONEY ---
    api_row = db_query("SELECT api_product_id, api_duration FROM products WHERE id=?", (prod_id,), fetchone=True)
    api_pid = (api_row[0] or