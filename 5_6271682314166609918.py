# -*- coding: utf-8 -*-
import sqlite3
import time
import threading
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import random
import telebot
from telebot import types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from collections import Counter

# ============================
# 1. КОНФИГ
# ============================
TOKEN = "8885788738:AAEEu1kTreUmFfysfrhL1rGms7t0hpaNyd8"
ADMIN_IDS = []
CHANNEL_USERNAME = "@RussianDatingChannel"
BASHKIR_CITIES = [
    'Уфа', 'Агидель', 'Баймак', 'Белебей', 'Белорецк', 'Бирск',
    'Благовещенск', 'Давлеканово', 'Дюртюли', 'Ишимбай', 'Кумертау',
    'Межгорье', 'Мелеуз', 'Нефтекамск', 'Октябрьский', 'Салават',
    'Сибай', 'Стерлитамак', 'Туймазы', 'Учалы', 'Янаул'
]
RUSSIAN_CITIES_PATTERN = r'^[А-ЯЁ][а-яё]+(?:[- ][А-ЯЁ][а-яё]+)?$'

# ============================
# 2. БАЗА
# ============================
class Database:
    def __init__(self, db_path="bot_database.db"):
        self.db_path = db_path
        self.init_db()

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur, conn

    def _fetchone(self, query: str, params: tuple = ()) -> Optional[Dict]:
        cur, conn = self._execute(query, params)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def _fetchall(self, query: str, params: tuple = ()) -> List[Dict]:
        cur, conn = self._execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def _execute_no_fetch(self, query: str, params: tuple = ()):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        conn.close()

    def init_db(self):
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered BOOLEAN DEFAULT 0,
                name TEXT,
                age INTEGER,
                city TEXT,
                about TEXT,
                interests TEXT,
                tags TEXT,
                photo_file_id TEXT,
                verified INTEGER DEFAULT 0,
                verification_attempts INTEGER DEFAULT 0,
                verification_video_file_id TEXT,
                balance INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                premium_until TIMESTAMP,
                last_activity TIMESTAMP,
                registration_date TIMESTAMP,
                role TEXT DEFAULT 'user',
                visible BOOLEAN DEFAULT 1,
                category TEXT,
                user_id_str TEXT UNIQUE,
                gender TEXT DEFAULT 'male',
                search_gender TEXT DEFAULT 'all',
                search_age_min INTEGER DEFAULT 14,
                search_age_max INTEGER DEFAULT 19,
                search_city TEXT,
                has_subscribed BOOLEAN DEFAULT 0
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS fines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                violation TEXT,
                amount INTEGER,
                paid BOOLEAN DEFAULT 0,
                issued_date TIMESTAMP,
                paid_date TIMESTAMP,
                appeal_text TEXT,
                appeal_status TEXT DEFAULT 'none',
                admin_comment TEXT,
                admin_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                type TEXT,
                timestamp TIMESTAMP,
                is_mutual BOOLEAN DEFAULT 0,
                mutual_date TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users(user_id),
                FOREIGN KEY (to_user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_user_id INTEGER,
                added_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (target_user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_user_id INTEGER,
                reason TEXT,
                description TEXT,
                timestamp TIMESTAMP,
                status TEXT DEFAULT 'pending',
                admin_comment TEXT,
                fine_id INTEGER,
                FOREIGN KEY (reporter_id) REFERENCES users(user_id),
                FOREIGN KEY (reported_user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS verification_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_file_id TEXT,
                status TEXT DEFAULT 'pending',
                timestamp TIMESTAMP,
                admin_comment TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                description TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS anonymous_chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER,
                user2_id INTEGER,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user1_id) REFERENCES users(user_id),
                FOREIGN KEY (user2_id) REFERENCES users(user_id)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS daily_reactions (
                user_id INTEGER,
                date TEXT,
                likes_count INTEGER DEFAULT 0,
                dislikes_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        """)
        self._execute_no_fetch("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user_id INTEGER,
                details TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(user_id),
                FOREIGN KEY (target_user_id) REFERENCES users(user_id)
            )
        """)
        defaults = {
            'welcome_text': 'Ой, хәлдәр нисек? 👀 Попал куда надо! Здесь знакомятся не для галочки, а по-настоящему. Но просто так «здрасьте» не прокатит — сначала подпишись на наш ТГ-канал (там анонсы и живые истории), а потом листай анкеты. И да, модераторы уже вышли на охоту — фейки и хамы летят в баню! Правила внутри, без них никак.',
            'rules': 'Честные правила...',
            'min_age': '14',
            'max_age': '100',
            'moderation_enabled': '1',
            'drafts_enabled': '1',
            'id_format': '#XXXXX',
            'reaction_limit': '500',
            'auto_delete_enabled': '1'
        }
        for key, value in defaults.items():
            if not self.get_setting(key):
                self.set_setting(key, value)

    def get_setting(self, key: str) -> Optional[str]:
        row = self._fetchone("SELECT value FROM bot_settings WHERE key = ?", (key,))
        return row['value'] if row else None

    def set_setting(self, key: str, value: str):
        self._execute_no_fetch("REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))

    def get_user(self, user_id: int) -> Optional[Dict]:
        return self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def create_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        now = datetime.now().isoformat()
        import time
        gen_id = f"#{str(int(time.time()) % 100000).zfill(5)}"
        while self._fetchone("SELECT user_id FROM users WHERE user_id_str = ?", (gen_id,)):
            gen_id = f"#{str(random.randint(0, 99999)).zfill(5)}"
        self._execute_no_fetch("""
            INSERT INTO users (user_id, username, first_name, last_name, user_id_str, registration_date, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, last_name, gen_id, now, now))

    def update_user(self, user_id: int, **kwargs):
        if not kwargs:
            return
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        self._execute_no_fetch(f"UPDATE users SET {set_clause} WHERE user_id = ?", tuple(values))

    def set_registered(self, user_id: int):
        self.update_user(user_id, registered=1, registration_date=datetime.now().isoformat())

    def get_active_users(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM users WHERE visible = 1 AND status NOT IN ('blocked', 'hidden') AND registered = 1 AND verified = 1")

    def add_fine(self, user_id: int, violation: str, amount: int, admin_id: int = None) -> int:
        now = datetime.now().isoformat()
        cur, conn = self._execute("""
            INSERT INTO fines (user_id, violation, amount, issued_date, admin_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, violation, amount, now, admin_id))
        fine_id = cur.lastrowid
        conn.close()
        return fine_id

    def get_unpaid_fines(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM fines WHERE user_id = ? AND paid = 0", (user_id,))

    def get_total_unpaid_fine_amount(self, user_id: int) -> int:
        rows = self._fetchall("SELECT SUM(amount) as total FROM fines WHERE user_id = ? AND paid = 0", (user_id,))
        return rows[0]['total'] if rows and rows[0]['total'] else 0

    def pay_fine(self, fine_id: int):
        now = datetime.now().isoformat()
        self._execute_no_fetch("UPDATE fines SET paid = 1, paid_date = ? WHERE id = ?", (now, fine_id))

    def get_fines_history(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM fines WHERE user_id = ? ORDER BY issued_date DESC", (user_id,))

    def add_reaction(self, from_user_id: int, to_user_id: int, reaction_type: str):
        now = datetime.now().isoformat()
        self._execute_no_fetch("""
            INSERT INTO likes (from_user_id, to_user_id, type, timestamp)
            VALUES (?, ?, ?, ?)
        """, (from_user_id, to_user_id, reaction_type, now))

    def get_reaction(self, from_user_id: int, to_user_id: int) -> Optional[Dict]:
        return self._fetchone("SELECT * FROM likes WHERE from_user_id = ? AND to_user_id = ?", (from_user_id, to_user_id))

    def get_user_likes_received(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM likes WHERE to_user_id = ? AND type = 'like'", (user_id,))

    def get_user_likes_given(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM likes WHERE from_user_id = ? AND type = 'like'", (user_id,))

    def get_user_dislikes_given(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM likes WHERE from_user_id = ? AND type = 'dislike'", (user_id,))

    def get_mutual_likes(self, user_id: int) -> List[Dict]:
        received = self._fetchall("SELECT from_user_id FROM likes WHERE to_user_id = ? AND type = 'like'", (user_id,))
        received_ids = [r['from_user_id'] for r in received]
        if not received_ids:
            return []
        placeholders = ','.join(['?'] * len(received_ids))
        query = f"SELECT * FROM likes WHERE from_user_id = ? AND to_user_id IN ({placeholders}) AND type = 'like'"
        params = [user_id] + received_ids
        return self._fetchall(query, tuple(params))

    def delete_reaction(self, from_user_id: int, to_user_id: int):
        self._execute_no_fetch("DELETE FROM likes WHERE from_user_id = ? AND to_user_id = ?", (from_user_id, to_user_id))

    def add_draft(self, user_id: int, target_user_id: int):
        now = datetime.now().isoformat()
        self._execute_no_fetch("""
            INSERT INTO drafts (user_id, target_user_id, added_date)
            VALUES (?, ?, ?)
        """, (user_id, target_user_id, now))

    def remove_draft(self, user_id: int, target_user_id: int):
        self._execute_no_fetch("DELETE FROM drafts WHERE user_id = ? AND target_user_id = ?", (user_id, target_user_id))

    def get_drafts(self, user_id: int) -> List[Dict]:
        return self._fetchall("SELECT * FROM drafts WHERE user_id = ? ORDER BY added_date DESC", (user_id,))

    def add_report(self, reporter_id: int, reported_user_id: int, reason: str, description: str = ""):
        now = datetime.now().isoformat()
        cur, conn = self._execute("""
            INSERT INTO reports (reporter_id, reported_user_id, reason, description, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (reporter_id, reported_user_id, reason, description, now))
        report_id = cur.lastrowid
        conn.close()
        return report_id

    def get_pending_reports(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM reports WHERE status = 'pending' ORDER BY timestamp ASC")

    def resolve_report(self, report_id: int, admin_comment: str = "", status: str = 'resolved', fine_id: int = None):
        self._execute_no_fetch("""
            UPDATE reports SET status = ?, admin_comment = ?, fine_id = ? WHERE id = ?
        """, (status, admin_comment, fine_id, report_id))

    def add_verification_request(self, user_id: int, video_file_id: str):
        now = datetime.now().isoformat()
        self._execute_no_fetch("""
            INSERT INTO verification_requests (user_id, video_file_id, timestamp)
            VALUES (?, ?, ?)
        """, (user_id, video_file_id, now))

    def get_pending_verifications(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM verification_requests WHERE status = 'pending' ORDER BY timestamp ASC")

    def approve_verification(self, user_id: int, admin_comment: str = ""):
        self._execute_no_fetch("""
            UPDATE verification_requests SET status = 'approved', admin_comment = ? WHERE user_id = ? AND status = 'pending'
        """, (admin_comment, user_id))
        self.update_user(user_id, verified=1, verification_attempts=0)

    def reject_verification(self, user_id: int, admin_comment: str = ""):
        self._execute_no_fetch("""
            UPDATE verification_requests SET status = 'rejected', admin_comment = ? WHERE user_id = ? AND status = 'pending'
        """, (admin_comment, user_id))
        user = self.get_user(user_id)
        attempts = user.get('verification_attempts', 0) + 1
        if attempts >= 3:
            self.update_user(user_id, verified=-1, status='blocked', verification_attempts=attempts)
        else:
            self.update_user(user_id, verified=-1, verification_attempts=attempts)

    def add_transaction(self, user_id: int, amount: int, type_str: str, description: str = ""):
        now = datetime.now().isoformat()
        self._execute_no_fetch("""
            INSERT INTO transactions (user_id, amount, type, description, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, amount, type_str, description, now))

    def get_balance(self, user_id: int) -> int:
        user = self.get_user(user_id)
        return user['balance'] if user else 0

    def add_stars(self, user_id: int, amount: int, description: str = ""):
        user = self.get_user(user_id)
        if not user:
            return
        new_balance = user['balance'] + amount
        self.update_user(user_id, balance=new_balance)
        self.add_transaction(user_id, amount, 'bonus', description)

    def deduct_stars(self, user_id: int, amount: int, description: str = ""):
        user = self.get_user(user_id)
        if not user or user['balance'] < amount:
            return False
        new_balance = user['balance'] - amount
        self.update_user(user_id, balance=new_balance)
        self.add_transaction(user_id, -amount, 'purchase', description)
        return True

    def get_daily_reactions(self, user_id: int) -> Tuple[int, int]:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._fetchone("SELECT likes_count, dislikes_count FROM daily_reactions WHERE user_id = ? AND date = ?", (user_id, today))
        if row:
            return row['likes_count'], row['dislikes_count']
        return 0, 0

    def increment_reaction(self, user_id: int, reaction_type: str):
        today = datetime.now().strftime("%Y-%m-%d")
        if reaction_type == 'like':
            self._execute_no_fetch("""
                INSERT INTO daily_reactions (user_id, date, likes_count, dislikes_count)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(user_id, date) DO UPDATE SET likes_count = likes_count + 1
            """, (user_id, today))
        elif reaction_type == 'dislike':
            self._execute_no_fetch("""
                INSERT INTO daily_reactions (user_id, date, likes_count, dislikes_count)
                VALUES (?, ?, 0, 1)
                ON CONFLICT(user_id, date) DO UPDATE SET dislikes_count = dislikes_count + 1
            """, (user_id, today))

    def create_chat_session(self, user1_id: int, user2_id: int) -> int:
        now = datetime.now().isoformat()
        cur, conn = self._execute("""
            INSERT INTO anonymous_chat_sessions (user1_id, user2_id, start_time, status)
            VALUES (?, ?, ?, 'active')
        """, (user1_id, user2_id, now))
        session_id = cur.lastrowid
        conn.close()
        return session_id

    def end_chat_session(self, session_id: int):
        now = datetime.now().isoformat()
        self._execute_no_fetch("UPDATE anonymous_chat_sessions SET status = 'ended', end_time = ? WHERE id = ?", (now, session_id))

    def get_active_chat_for_user(self, user_id: int) -> Optional[Dict]:
        row = self._fetchone("""
            SELECT * FROM anonymous_chat_sessions
            WHERE (user1_id = ? OR user2_id = ?) AND status = 'active'
        """, (user_id, user_id))
        return row

    def get_chat_partner(self, user_id: int) -> Optional[int]:
        session = self.get_active_chat_for_user(user_id)
        if not session:
            return None
        if session['user1_id'] == user_id:
            return session['user2_id']
        else:
            return session['user1_id']

    def get_total_users(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM users")
        return row['count'] if row else 0

    def get_active_visible_users(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM users WHERE visible = 1 AND status NOT IN ('blocked', 'hidden') AND registered = 1 AND verified = 1")
        return row['count'] if row else 0

    def get_blocked_users(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM users WHERE status = 'blocked'")
        return row['count'] if row else 0

    def get_verification_pending(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM verification_requests WHERE status = 'pending'")
        return row['count'] if row else 0

    def get_verified_users(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM users WHERE verified = 1")
        return row['count'] if row else 0

    def get_total_likes(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM likes WHERE type = 'like'")
        return row['count'] if row else 0

    def get_total_mutual(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM likes WHERE is_mutual = 1")
        return row['count'] if row else 0

    def get_total_drafts(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM drafts")
        return row['count'] if row else 0

    def get_total_reports(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM reports")
        return row['count'] if row else 0

    def get_total_stars_in_system(self) -> int:
        row = self._fetchone("SELECT SUM(balance) as total FROM users")
        return row['total'] if row and row['total'] else 0

    def get_premium_users_count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) as count FROM users WHERE status IN ('premium', 'premium_plus')")
        return row['count'] if row else 0

    def get_today_stats(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        new_users = self._fetchone("SELECT COUNT(*) as count FROM users WHERE DATE(registration_date) = ?", (today,))
        likes_today = self._fetchone("SELECT COUNT(*) as count FROM likes WHERE type = 'like' AND DATE(timestamp) = ?", (today,))
        fines_today = self._fetchone("SELECT COUNT(*) as count FROM fines WHERE DATE(issued_date) = ?", (today,))
        return {
            'new_users': new_users['count'] if new_users else 0,
            'likes': likes_today['count'] if likes_today else 0,
            'fines': fines_today['count'] if fines_today else 0
        }

    def get_users_inactive_days(self, days: int) -> List[Dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return self._fetchall("SELECT user_id FROM users WHERE last_activity < ? AND visible = 1 AND status NOT IN ('blocked', 'hidden')", (cutoff,))

    def hide_user(self, user_id: int):
        self.update_user(user_id, visible=0)

    def delete_user(self, user_id: int):
        tables = ['fines', 'likes', 'drafts', 'reports', 'verification_requests', 'transactions', 'daily_reactions']
        for table in tables:
            self._execute_no_fetch(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        self._execute_no_fetch("DELETE FROM users WHERE user_id = ?", (user_id,))

    def add_admin_log(self, admin_id: int, action: str, target_user_id: int = None, details: str = ""):
        now = datetime.now().isoformat()
        self._execute_no_fetch("""
            INSERT INTO admin_logs (admin_id, action, target_user_id, details, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (admin_id, action, target_user_id, details, now))

    def get_admin_logs(self, limit: int = 50) -> List[Dict]:
        return self._fetchall("SELECT * FROM admin_logs ORDER BY timestamp DESC LIMIT ?", (limit,))


# ============================
# 3. FSM
# ============================
class UserStates(StatesGroup):
    reg_name = State()
    reg_age = State()
    reg_city = State()
    reg_about = State()
    reg_interests = State()
    reg_photo = State()
    reg_confirm = State()
    reg_gender = State()
    reg_search_gender = State()
    edit_choose = State()
    edit_name = State()
    edit_age = State()
    edit_city = State()
    edit_about = State()
    edit_interests = State()
    edit_photo = State()
    edit_gender = State()
    filter_age = State()
    filter_city = State()
    filter_gender = State()
    anon_waiting = State()
    anon_chat = State()
    admin_broadcast = State()
    admin_fine = State()
    admin_user_search = State()
    admin_give_stars = State()
    admin_verification_reject = State()
    admin_ban = State()
    admin_unban = State()
    admin_remove_fine = State()
    admin_add_admin = State()
    admin_remove_admin = State()
    report_reason = State()
    support = State()
    admin_fine_issue = State()
    admin_set_stars = State()
    admin_give_premium = State()
    admin_remove_premium = State()


# ============================
# 4. ОСНОВНОЙ КЛАСС БОТА
# ============================
class BotApp:
    def __init__(self, token):
        self.db = Database()
        self.bot = telebot.TeleBot(token, state_storage=StateMemoryStorage())
        self.temp_tags = {}
        self.user_filters = {}
        self.anon_waiting = []
        self.register_handlers()
        self.start_auto_delete_thread()

    def start_auto_delete_thread(self):
        def auto_delete_worker():
            while True:
                time.sleep(86400)
                self.check_inactive_users()
        thread = threading.Thread(target=auto_delete_worker, daemon=True)
        thread.start()

    def check_inactive_users(self):
        days_7 = self.db.get_users_inactive_days(7)
        for u in days_7:
            user_id = u['user_id']
            user = self.db.get_user(user_id)
            if user and user['visible'] and user['status'] not in ('blocked', 'hidden'):
                self.bot.send_message(user_id, "Напоминание об активности\n\nВы не заходили в бот 7 дней.\nЕсли вы не зайдёте в ближайшие 7 дней, ваша анкета будет скрыта.\nЗайдите в бот, чтобы оставаться на виду!", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ЗАЙТИ В БОТ", callback_data="stay_visible")))
        days_14 = self.db.get_users_inactive_days(14)
        for u in days_14:
            user_id = u['user_id']
            user = self.db.get_user(user_id)
            if user and user['visible'] and user['status'] not in ('blocked', 'hidden'):
                self.bot.send_message(user_id, "Второе предупреждение\n\nВы не заходили в бот уже 14 дней!\nВаша анкета будет СКРЫТА через 7 дней.\nДругие пользователи не смогут вас найти.\nЧтобы этого избежать, просто откройте бота и нажмите кнопку ниже.", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ОСТАТЬСЯ ВИДИМЫМ", callback_data="stay_visible")))
        days_30 = self.db.get_users_inactive_days(30)
        for u in days_30:
            user_id = u['user_id']
            user = self.db.get_user(user_id)
            if user and user['visible'] and user['status'] not in ('blocked', 'hidden'):
                self.db.hide_user(user_id)
                self.bot.send_message(user_id, "Ваша анкета скрыта\n\nВы не заходили в бот 30 дней.\nВаша анкета больше не видна другим пользователям.\nЧтобы восстановить анкету, нажмите кнопку ниже.", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("ВОССТАНОВИТЬ АНКЕТУ", callback_data="restore_profile")))
        days_60 = self.db.get_users_inactive_days(60)
        for u in days_60:
            user_id = u['user_id']
            user = self.db.get_user(user_id)
            if user:
                self.db.delete_user(user_id)
                self.bot.send_message(user_id, "Ваша анкета удалена\n\nВы не заходили в бот 60 дней.\nВаша анкета и все данные удалены из системы.\nЧтобы создать новую анкету, нажмите кнопку ниже.", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("СОЗДАТЬ АНКЕТУ ЗАНОВО", callback_data="restart_registration")))

    def register_handlers(self):
        # ===== ОБРАБОТЧИКИ СОСТОЯНИЙ (ДОЛЖНЫ БЫТЬ ПЕРВЫМИ!) =====
        # Регистрация
        self.bot.message_handler(state=UserStates.reg_gender)(self.reg_gender_handler)
        self.bot.message_handler(state=UserStates.reg_search_gender)(self.reg_search_gender_handler)
        self.bot.message_handler(state=UserStates.reg_name)(self.reg_name_handler)
        self.bot.message_handler(state=UserStates.reg_age)(self.reg_age_handler)
        self.bot.message_handler(state=UserStates.reg_city)(self.reg_city_handler)
        self.bot.message_handler(state=UserStates.reg_about)(self.reg_about_handler)
        self.bot.message_handler(state=UserStates.reg_interests)(self.reg_interests_handler)
        self.bot.message_handler(content_types=['photo'], state=UserStates.reg_photo)(self.reg_photo_handler)
        self.bot.message_handler(state=UserStates.reg_confirm)(self.reg_confirm_handler)

        # Редактирование
        self.bot.message_handler(state=UserStates.edit_name)(self.edit_name_handler)
        self.bot.message_handler(state=UserStates.edit_age)(self.edit_age_handler)
        self.bot.message_handler(state=UserStates.edit_city)(self.edit_city_handler)
        self.bot.message_handler(state=UserStates.edit_about)(self.edit_about_handler)
        self.bot.message_handler(state=UserStates.edit_interests)(self.edit_interests_handler)
        self.bot.message_handler(content_types=['photo'], state=UserStates.edit_photo)(self.edit_photo_handler)
        self.bot.message_handler(state=UserStates.edit_gender)(self.edit_gender_handler)

        # Фильтры
        self.bot.message_handler(state=UserStates.filter_age)(self.filter_age_handler)
        self.bot.message_handler(state=UserStates.filter_city)(self.filter_city_handler)
        self.bot.message_handler(state=UserStates.filter_gender)(self.filter_gender_handler)

        # Анонимный чат
        self.bot.message_handler(state=UserStates.anon_chat)(self.anon_chat_handler)
        self.bot.message_handler(state=UserStates.anon_waiting)(self.anon_waiting_handler)

        # Админ состояния
        self.bot.message_handler(state=UserStates.admin_broadcast)(self.admin_broadcast_message_handler)
        self.bot.message_handler(state=UserStates.admin_fine)(self.admin_fine_handler)
        self.bot.message_handler(state=UserStates.admin_user_search)(self.admin_user_search_handler)
        self.bot.message_handler(state=UserStates.admin_give_stars)(self.admin_give_stars_message_handler)
        self.bot.message_handler(state=UserStates.support)(self.support_handler)
        self.bot.message_handler(state=UserStates.admin_verification_reject)(self.admin_verification_reject_handler)
        self.bot.message_handler(state=UserStates.report_reason)(self.report_reason_handler)
        self.bot.message_handler(state=UserStates.admin_ban)(self.admin_ban_handler)
        self.bot.message_handler(state=UserStates.admin_unban)(self.admin_unban_handler)
        self.bot.message_handler(state=UserStates.admin_remove_fine)(self.admin_remove_fine_handler)
        self.bot.message_handler(state=UserStates.admin_add_admin)(self.admin_add_admin_handler)
        self.bot.message_handler(state=UserStates.admin_remove_admin)(self.admin_remove_admin_handler)
        self.bot.message_handler(state=UserStates.admin_fine_issue)(self.admin_fine_issue_handler)
        self.bot.message_handler(state=UserStates.admin_set_stars)(self.admin_set_stars_handler)
        self.bot.message_handler(state=UserStates.admin_give_premium)(self.admin_give_premium_handler)
        self.bot.message_handler(state=UserStates.admin_remove_premium)(self.admin_remove_premium_handler)

        # ===== ОБРАБОТЧИКИ КОМАНД =====
        self.bot.message_handler(commands=['start'])(self.cmd_start)
        self.bot.message_handler(commands=['profile'])(self.cmd_profile)
        self.bot.message_handler(commands=['mylikes'])(self.cmd_mylikes)
        self.bot.message_handler(commands=['mydislikes'])(self.cmd_mydislikes)
        self.bot.message_handler(commands=['drafts'])(self.cmd_drafts)
        self.bot.message_handler(commands=['anon'])(self.cmd_anon)
        self.bot.message_handler(commands=['shop'])(self.cmd_shop)
        self.bot.message_handler(commands=['balance'])(self.cmd_balance)
        self.bot.message_handler(commands=['premium'])(self.cmd_premium)
        self.bot.message_handler(commands=['limits'])(self.cmd_limits)
        self.bot.message_handler(commands=['fines'])(self.cmd_fines)
        self.bot.message_handler(commands=['stats'])(self.cmd_stats)
        self.bot.message_handler(commands=['rules'])(self.cmd_rules)
        self.bot.message_handler(commands=['support'])(self.cmd_support)
        self.bot.message_handler(commands=['help'])(self.cmd_help)
        self.bot.message_handler(commands=['admin'])(self.cmd_admin)
        self.bot.message_handler(commands=['logs'])(self.cmd_logs)
        self.bot.message_handler(commands=['ban'])(self.cmd_ban)
        self.bot.message_handler(commands=['unban'])(self.cmd_unban)
        self.bot.message_handler(commands=['fine'])(self.cmd_fine)
        self.bot.message_handler(commands=['remove_fine'])(self.cmd_remove_fine)
        self.bot.message_handler(commands=['add_admin'])(self.cmd_add_admin)
        self.bot.message_handler(commands=['remove_admin'])(self.cmd_remove_admin)
        self.bot.message_handler(commands=['check_verification'])(self.cmd_check_verification)
        self.bot.message_handler(commands=['give_stars'])(self.cmd_give_stars)
        self.bot.message_handler(commands=['set_stars'])(self.cmd_set_stars)
        self.bot.message_handler(commands=['give_premium'])(self.cmd_give_premium)
        self.bot.message_handler(commands=['remove_premium'])(self.cmd_remove_premium)

        # ===== ОБРАБОТЧИКИ КОЛБЭКОВ =====
        self.bot.callback_query_handler(func=lambda call: True)(self.handle_callback)

        # ===== ВИДЕО-КРУЖКИ =====
        self.bot.message_handler(content_types=['video_note'])(self.video_note_handler)

    # ==================== КОМАНДЫ ====================
    
    def cmd_start(self, message):
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        if not user:
            self.db.create_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
            user = self.db.get_user(user_id)
        
        if user['status'] == 'blocked':
            self.bot.send_message(user_id, "Ваш аккаунт заблокирован. Обратитесь в поддержку.")
            return
        
        # ВРЕМЕННО: принудительно отмечаем подписку для теста
        if not user['has_subscribed']:
            self.db.update_user(user_id, has_subscribed=1)
            user = self.db.get_user(user_id)
        
        if not user['has_subscribed']:
            welcome = self.db.get_setting('welcome_text') or "Ой, хәлдәр нисек? 👀 Попал куда надо! Здесь знакомятся не для галочки, а по-настоящему. Но просто так «здрасьте» не прокатит — сначала подпишись на наш ТГ-канал (там анонсы и живые истории), а потом листай анкеты. И да, модераторы уже вышли на охоту — фейки и хамы летят в баню! Правила внутри, без них никак."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📢 Подписаться на ТГ-канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"))
            markup.add(types.InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription"))
            self.bot.send_message(user_id, welcome, reply_markup=markup)
            return

        unpaid = self.db.get_total_unpaid_fine_amount(user_id)
        if unpaid > 0:
            self.bot.send_message(user_id, f"У вас есть неоплаченный штраф на сумму {unpaid} Stars. Оплатите его для доступа к функциям.", reply_markup=self.get_fine_pay_keyboard())
            return
        
        if not user['registered']:
            self.bot.set_state(user_id, UserStates.reg_gender)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("👨 Мужской", callback_data="gender_male"),
                types.InlineKeyboardButton("👩 Женский", callback_data="gender_female")
            )
            self.bot.send_message(user_id, "Выберите свой пол:", reply_markup=markup)
            return
        
        self.start_search(user_id)

    def cmd_profile(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        user = self.db.get_user(user_id)
        if not user:
            self.bot.send_message(user_id, "Профиль не найден. Начните с /start")
            return
        
        gender_text = "Мужской" if user.get('gender') == 'male' else "Женский"
        search_gender_text = "Мужской" if user.get('search_gender') == 'male' else "Женский" if user.get('search_gender') == 'female' else "Всех"
        
        text = f"📸 Фото\n\n"
        text += f"ID аккаунта: {user['user_id_str']}\n"
        text += f"👤 Имя: {user['name']}\n"
        text += f"🎂 Возраст: {user['age']} Лет\n"
        text += f"🏙️ Город: {user['city']}\n\n"
        text += f"🎯 Интересы: {user['interests']}\n\n"
        text += f"📝 О себе: {user['about']}\n\n"
        text += f"═══════════════════════════════\n"
        text += f"💰 Баланс: {user['balance']} Stars\n"
        text += f"👑 Премка: {'Да' if user['status'] in ('premium', 'premium_plus') else 'Нет'}\n"
        text += f"🔍 Ищу возраст: {user.get('search_age_min', 14)}–{user.get('search_age_max', 19)} лет\n"
        text += f"⚥ Ищу пол: {search_gender_text}\n"
        text += f"📍 Город поиска: {user.get('search_city', 'Не указан')}\n"
        text += f"⚥ Пол: {gender_text}\n"
        text += f"Верификация: {'✅ Пройдена' if user['verified'] == 1 else '❌ Не пройдена'}\n"
        text += f"Анкета активна: {'Да' if user['visible'] else 'Нет'}"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✏️ РЕДАКТИРОВАТЬ", callback_data="edit_profile"),
            types.InlineKeyboardButton("🙈 СКРЫТЬ АНКЕТУ", callback_data="hide_profile"),
            types.InlineKeyboardButton("🗑 УДАЛИТЬ", callback_data="delete_profile"),
            types.InlineKeyboardButton("📝 ЧЕРНОВИКИ", callback_data="view_drafts"),
            types.InlineKeyboardButton("🏷️ ТЕГИ", callback_data="edit_tags")
        )
        if user['photo_file_id']:
            self.bot.send_photo(user_id, user['photo_file_id'], caption=text, reply_markup=markup)
        else:
            self.bot.send_message(user_id, text, reply_markup=markup)

    def cmd_mylikes(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        received = self.db.get_user_likes_received(user_id)
        given = self.db.get_user_likes_given(user_id)
        mutual = self.db.get_mutual_likes(user_id)
        text = "❤️ Мои лайки\n\n"
        text += "Кто лайкнул меня: ({})\n".format(len(received))
        for idx, r in enumerate(received[:10], 1):
            user = self.db.get_user(r['from_user_id'])
            if user:
                text += f"{idx}. {user['name']}, {user['age']} лет, {user['city']} (ID: {user['user_id_str']}) - {r['timestamp'][:10]}\n"
        text += "\nЯ лайкнул: ({})\n".format(len(given))
        for idx, r in enumerate(given[:10], 1):
            user = self.db.get_user(r['to_user_id'])
            if user:
                text += f"{idx}. {user['name']}, {user['age']} лет, {user['city']} (ID: {user['user_id_str']}) - {r['timestamp'][:10]}\n"
        text += "\n💞 Взаимности: ({})\n".format(len(mutual))
        for idx, r in enumerate(mutual[:10], 1):
            user = self.db.get_user(r['to_user_id'])
            if user:
                text += f"{idx}. {user['name']} и ... - {r['mutual_date'][:10]}\n"
        self.bot.send_message(user_id, text)

    def cmd_mydislikes(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        dislikes = self.db.get_user_dislikes_given(user_id)
        text = "👎 Мои дизлайки ({})\n".format(len(dislikes))
        for idx, r in enumerate(dislikes[:20], 1):
            user = self.db.get_user(r['to_user_id'])
            if user:
                text += f"{idx}. {user['name']}, {user['age']} лет, {user['city']} (ID: {user['user_id_str']}) - {r['timestamp'][:10]}\n"
        self.bot.send_message(user_id, text)

    def cmd_drafts(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        drafts = self.db.get_drafts(user_id)
        if not drafts:
            self.bot.send_message(user_id, "У вас нет черновиков.")
            return
        for idx, d in enumerate(drafts[:10], 1):
            user = self.db.get_user(d['target_user_id'])
            if user:
                markup = types.InlineKeyboardMarkup(row_width=3)
                markup.add(
                    types.InlineKeyboardButton("❤️ ЛАЙК", callback_data=f"draft_like_{d['target_user_id']}"),
                    types.InlineKeyboardButton("👎 ДИЗЛАЙК", callback_data=f"draft_dislike_{d['target_user_id']}"),
                    types.InlineKeyboardButton("🗑 УДАЛИТЬ", callback_data=f"draft_delete_{d['target_user_id']}")
                )
                self.bot.send_message(user_id, f"{idx}. {user['name']} (ID: {user['user_id_str']}), {user['age']} лет, {user['city']}", reply_markup=markup)

    def cmd_anon(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        session = self.db.get_active_chat_for_user(user_id)
        if session:
            self.bot.send_message(user_id, "У вас уже есть активный чат. Напишите сообщение или завершите чат.")
            self.bot.set_state(user_id, UserStates.anon_chat)
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔍 НАЙТИ СОБЕСЕДНИКА", callback_data="anon_find"),
            types.InlineKeyboardButton("🚪 ВЫЙТИ", callback_data="anon_exit")
        )
        self.bot.send_message(user_id, "Анонимный чат\n\nЗдесь вы можете общаться анонимно!\nПравила анонимного чата:\n1. Ваше имя и фото скрыты\n2. Вы общаетесь с random пользователем\n3. Нельзя спрашивать личные данные\n4. Нарушители получают штраф\n\nХотите начать?", reply_markup=markup)

    def cmd_shop(self, message):
        user_id = message.from_user.id
        if not self.check_user_access(user_id):
            return
        user = self.db.get_user(user_id)
        text = f"🛒 Магазин\n\nВаш баланс: {user['balance']} Stars\n\n"
        text += "1 👑 1 день - 9 ⭐ (9 ₽)\n"
        text += "2 👑 1 неделя - 49 ⭐ (49 ₽)\n"
        text += "3 👑 1 месяц - 99 ⭐ (99 ₽)\n"
        text += "4 👑 3 месяца - 199 ⭐ (199 ₽)\n"
        text += "5 👑 6 месяцев - 349 ⭐ (349 ₽)\n"
        text += "6 👑 12 месяцев - 599 ⭐ (599 ₽)\n"
        text += "7 💎 Пополнить баланс\n"
        text += "8 🚀 Ускоренная верификация - 150 ⭐\n"
        text += "9 📝 Дополнительные черновики - 100 ⭐"
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [
            types.InlineKeyboardButton("1", callback_data="shop_1"),
            types.InlineKeyboardButton("2", callback_data="shop_2"),
            types.InlineKeyboardButton("3", callback_data="shop_3"),
            types.InlineKeyboardButton("4", callback_data="shop_4"),
            types.InlineKeyboardButton("5", callback_data="shop_5"),
            types.InlineKeyboardButton("6", callback_data="shop_6"),
            types.InlineKeyboardButton("7", callback_data="shop_topup"),
            types.InlineKeyboardButton("8", callback_data="shop_verif_fast"),
            types.InlineKeyboardButton("9", callback_data="shop_drafts")
        ]
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("🔙 НАЗАД", callback_data="shop_back"))
        self.bot.send_message(user_id, text, reply_markup=markup)

    def cmd_balance(self, message):
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        if user:
            self.bot.send_message(user_id, f"Ваш баланс: {user['balance']} Stars")

    def cmd_premium(self, message):
        self.cmd_shop(message)

    def cmd_limits(self, message):
        user_id = message.from_user.id
        likes, dislikes = self.db.get_daily_reactions(user_id)
        limit = int(self.db.get_setting('reaction_limit') or 500)
        text = f"Остаток реакций на сегодня: {limit - (likes + dislikes)}/{limit}\nЛайков: {likes}, Дизлайков: {dislikes}\nОбновление в 00:00"
        self.bot.send_message(user_id, text)

    def cmd_fines(self, message):
        user_id = message.from_user.id
        fines = self.db.get_fines_history(user_id)
        if not fines:
            self.bot.send_message(user_id, "У вас нет штрафов.")
            return
        unpaid = [f for f in fines if not f['paid']]
        paid = [f for f in fines if f['paid']]
        text = "📋 История штрафов\n\n"
        if unpaid:
            text += "Неоплаченные:\n"
            for f in unpaid:
                text += f"• {f['violation']} - {f['amount']} Stars (ждёт оплаты)\n"
        if paid:
            text += "Оплаченные:\n"
            for f in paid[:5]:
                text += f"• {f['violation']} - {f['amount']} Stars ({f['paid_date'][:10]})\n"
        total_paid = sum(f['amount'] for f in paid)
        text += f"\nВсего потрачено на штрафы: {total_paid} Stars"
        self.bot.send_message(user_id, text)

    def cmd_stats(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Только для администраторов.")
            return
        stats = self.get_admin_stats()
        self.bot.send_message(user_id, stats)

    def cmd_rules(self, message):
        rules = self.db.get_setting('rules') or "Честные правила..."
        self.bot.send_message(message.from_user.id, rules)

    def cmd_support(self, message):
        user_id = message.from_user.id
        self.bot.set_state(user_id, UserStates.support)
        self.bot.send_message(user_id, "Напишите ваше обращение в поддержку. Мы ответим в ближайшее время.")

    def cmd_help(self, message):
        help_text = "Доступные команды:\n/start - начать\n/profile - профиль\n/mylikes - мои лайки\n/mydislikes - мои дизлайки\n/drafts - черновики\n/anon - анонимный чат\n/shop - магазин\n/balance - баланс\n/premium - купить Premium\n/limits - лимиты\n/fines - штрафы\n/stats - статистика (админ)\n/rules - правила\n/support - поддержка\n/help - помощь"
        self.bot.send_message(message.from_user.id, help_text)

    def cmd_admin(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        stats = self.get_admin_stats()
        markup = self.get_admin_menu()
        self.bot.send_message(user_id, stats, reply_markup=markup)

    # ==================== РЕГИСТРАЦИЯ ====================

    def reg_gender_handler(self, message):
        user_id = message.from_user.id
        gender = message.text.strip().lower()
        if gender not in ['мужской', 'женский']:
            self.bot.send_message(user_id, "Пожалуйста, выберите 'мужской' или 'женский'.")
            return
        self.db.update_user(user_id, gender='male' if gender == 'мужской' else 'female')
        self.bot.set_state(user_id, UserStates.reg_search_gender)
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("👨 Мужской", callback_data="search_gender_male"),
            types.InlineKeyboardButton("👩 Женский", callback_data="search_gender_female"),
            types.InlineKeyboardButton("👥 Всех", callback_data="search_gender_all")
        )
        self.bot.send_message(user_id, "Кого вы ищете?", reply_markup=markup)

    def reg_search_gender_handler(self, message):
        user_id = message.from_user.id
        gender = message.text.strip().lower()
        if gender not in ['мужской', 'женский', 'всех']:
            self.bot.send_message(user_id, "Пожалуйста, выберите 'мужской', 'женский' или 'всех'.")
            return
        map_gender = {'мужской': 'male', 'женский': 'female', 'всех': 'all'}
        self.db.update_user(user_id, search_gender=map_gender[gender])
        self.bot.set_state(user_id, UserStates.reg_name)
        self.bot.send_message(user_id, "Как вас зовут? (Напишите имя)")

    def reg_name_handler(self, message):
        user_id = message.from_user.id
        name = message.text.strip()
        if len(name) < 2:
            self.bot.send_message(user_id, "Имя должно содержать хотя бы 2 символа. Попробуйте снова.")
            return
        self.db.update_user(user_id, name=name)
        self.bot.set_state(user_id, UserStates.reg_age)
        self.bot.send_message(user_id, "Сколько вам лет? (От 14 до 100 лет)")

    def reg_age_handler(self, message):
        user_id = message.from_user.id
        try:
            age = int(message.text.strip())
        except:
            self.bot.send_message(user_id, "Пожалуйста, введите число.")
            return
        if age < 14 or age > 100:
            self.bot.send_message(user_id, "Возраст должен быть от 14 до 100 лет.")
            return
        category = "14-17" if 14 <= age <= 17 else "18-100"
        self.db.update_user(user_id, age=age, category=category)
        self.bot.set_state(user_id, UserStates.reg_city)
        self.bot.send_message(user_id, "Из какого вы города? (Напишите город с большой буквы)\n\nДоступные города Башкортостана:\n" + ", ".join(BASHKIR_CITIES[:10]) + "...")

    def reg_city_handler(self, message):
        user_id = message.from_user.id
        city = message.text.strip()
        if not re.match(RUSSIAN_CITIES_PATTERN, city):
            self.bot.send_message(user_id, "Введите город с большой буквы, используя кириллицу. Например: Уфа")
            return
        if city not in BASHKIR_CITIES:
            self.bot.send_message(user_id, f"Пожалуйста, введите город из списка Башкортостана:\n" + ", ".join(BASHKIR_CITIES))
            return
        self.db.update_user(user_id, city=city)
        self.bot.set_state(user_id, UserStates.reg_about)
        self.bot.send_message(user_id, "Напишите о себе пару слов (Чем занимаетесь, что ищете и т.д.)")

    def reg_about_handler(self, message):
        user_id = message.from_user.id
        about = message.text.strip()
        if len(about) < 5:
            self.bot.send_message(user_id, "Расскажите о себе подробнее (минимум 5 символов).")
            return
        self.db.update_user(user_id, about=about)
        self.bot.set_state(user_id, UserStates.reg_interests)
        self.bot.send_message(user_id, "Ваши интересы? (Через запятую: кино, спорт, книги...)")

    def reg_interests_handler(self, message):
        user_id = message.from_user.id
        interests = message.text.strip()
        if len(interests) < 2:
            self.bot.send_message(user_id, "Введите хотя бы один интерес.")
            return
        self.db.update_user(user_id, interests=interests)
        self.send_tag_selection(user_id, "reg_tags")

    def reg_photo_handler(self, message):
        user_id = message.from_user.id
        if not message.photo:
            self.bot.send_message(user_id, "Пожалуйста, отправьте фото.")
            return
        file_id = message.photo[-1].file_id
        self.db.update_user(user_id, photo_file_id=file_id)
        self.bot.set_state(user_id, UserStates.reg_confirm)
        self.show_profile_for_confirm(user_id)

    def reg_confirm_handler(self, message):
        pass

    def show_profile_for_confirm(self, user_id):
        user = self.db.get_user(user_id)
        gender_text = "Мужской" if user.get('gender') == 'male' else "Женский"
        text = f"Профиль создан!\n\nИмя: {user['name']}\nВозраст: {user['age']}\nГород: {user['city']}\nО себе: {user['about']}\nИнтересы: {user['interests']}\nТеги: {user['tags']}\nПол: {gender_text}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ ВСЁ ВЕРНО", callback_data="confirm_reg_yes"))
        markup.add(types.InlineKeyboardButton("🔄 ИЗМЕНИТЬ", callback_data="confirm_reg_no"))
        if user['photo_file_id']:
            self.bot.send_photo(user_id, user['photo_file_id'], caption=text, reply_markup=markup)
        else:
            self.bot.send_message(user_id, text, reply_markup=markup)

    # ==================== АДМИН КОМАНДЫ ====================

    def cmd_logs(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        logs = self.db.get_admin_logs(50)
        if not logs:
            self.bot.send_message(user_id, "Логов нет.")
            return
        text = "📋 Логи действий администрации:\n\n"
        for log in logs:
            admin = self.db.get_user(log['admin_id'])
            target = self.db.get_user(log['target_user_id']) if log['target_user_id'] else None
            admin_name = admin['name'] if admin else "Unknown"
            target_name = f" (→ {target['name']})" if target else ""
            text += f"{log['timestamp'][:10]} {log['timestamp'][11:16]} - {admin_name}{target_name}: {log['action']}\n"
            if log['details']:
                text += f"  {log['details']}\n"
            if len(text) > 4000:
                self.bot.send_message(user_id, text)
                text = ""
        if text:
            self.bot.send_message(user_id, text)

    def cmd_ban(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /ban @username или /ban #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='blocked')
        self.db.add_admin_log(user_id, "Бан", target['user_id'], parts[1])
        self.bot.send_message(user_id, f"Пользователь {parts[1]} забанен.")

    def cmd_unban(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /unban @username или /unban #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='active')
        self.db.add_admin_log(user_id, "Разбан", target['user_id'], parts[1])
        self.bot.send_message(user_id, f"Пользователь {parts[1]} разбанен.")

    def cmd_fine(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 4:
            self.bot.send_message(user_id, "Использование: /fine @username #ID сумма причина")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            amount = int(parts[2])
        except:
            self.bot.send_message(user_id, "Сумма должна быть числом.")
            return
        reason = " ".join(parts[3:])
        self.db.add_fine(target['user_id'], reason, amount, user_id)
        self.db.add_admin_log(user_id, "Выдача штрафа", target['user_id'], f"{reason} - {amount} Stars")
        self.bot.send_message(user_id, f"Штраф выдан.")

    def cmd_remove_fine(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /remove_fine #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        unpaid = self.db.get_unpaid_fines(target['user_id'])
        if not unpaid:
            self.bot.send_message(user_id, "У пользователя нет неоплаченных штрафов.")
            return
        for f in unpaid:
            self.db.pay_fine(f['id'])
        self.db.add_admin_log(user_id, "Снятие штрафа", target['user_id'])
        self.bot.send_message(user_id, f"Все штрафы сняты у {parts[1]}.")

    def cmd_add_admin(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /add_admin @username или /add_admin #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], role='admin')
        self.db.add_admin_log(user_id, "Назначение администратора", target['user_id'], parts[1])
        self.bot.send_message(user_id, f"Пользователь {parts[1]} назначен администратором.")
        ADMIN_IDS.append(target['user_id'])

    def cmd_remove_admin(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /remove_admin @username или /remove_admin #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        if target['user_id'] in ADMIN_IDS:
            ADMIN_IDS.remove(target['user_id'])
        self.db.update_user(target['user_id'], role='user')
        self.db.add_admin_log(user_id, "Снятие администратора", target['user_id'], parts[1])
        self.bot.send_message(user_id, f"Пользователь {parts[1]} снят с должности.")

    def cmd_check_verification(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /check_verification @username или /check_verification #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        
        requests = self.db._fetchall("SELECT * FROM verification_requests WHERE user_id = ? ORDER BY timestamp DESC", (target['user_id'],))
        if not requests:
            self.bot.send_message(user_id, f"У пользователя {parts[1]} нет запросов на верификацию.")
            return
        
        text = f"📹 Запросы верификации для {parts[1]}:\n\n"
        for req in requests[:3]:
            text += f"Дата: {req['timestamp'][:10]}\nСтатус: {req['status']}\n"
            if req['video_file_id']:
                text += f"Видео: отправлено\n"
            text += "---\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ ОДОБРИТЬ", callback_data=f"admin_verif_approve_{target['user_id']}"),
            types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"admin_verif_reject_{target['user_id']}"),
            types.InlineKeyboardButton("📹 ПОСМОТРЕТЬ ВИДЕО", callback_data=f"admin_verif_video_{target['user_id']}")
        )
        self.bot.send_message(user_id, text, reply_markup=markup)

    def cmd_give_stars(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 3:
            self.bot.send_message(user_id, "Использование: /give_stars @username #ID количество")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            amount = int(parts[2])
        except:
            self.bot.send_message(user_id, "Сумма должна быть числом.")
            return
        self.db.add_stars(target['user_id'], amount, f"Выдано администратором")
        self.db.add_admin_log(user_id, "Выдача Stars", target['user_id'], f"{amount} Stars")
        self.bot.send_message(user_id, f"Пользователю {parts[1]} выдано {amount} Stars.")

    def cmd_set_stars(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 3:
            self.bot.send_message(user_id, "Использование: /set_stars @username #ID количество")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            amount = int(parts[2])
        except:
            self.bot.send_message(user_id, "Сумма должна быть числом.")
            return
        self.db.update_user(target['user_id'], balance=amount)
        self.db.add_admin_log(user_id, "Установка Stars", target['user_id'], f"{amount} Stars")
        self.bot.send_message(user_id, f"Баланс пользователя {parts[1]} установлен на {amount} Stars.")

    def cmd_give_premium(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 3:
            self.bot.send_message(user_id, "Использование: /give_premium @username #ID дни")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            days = int(parts[2])
        except:
            self.bot.send_message(user_id, "Количество дней должно быть числом.")
            return
        until = datetime.now() + timedelta(days=days)
        self.db.update_user(target['user_id'], status='premium', premium_until=until.isoformat())
        self.db.add_admin_log(user_id, "Выдача Premium", target['user_id'], f"{days} дней")
        self.bot.send_message(user_id, f"Premium выдан {parts[1]} на {days} дней.")

    def cmd_remove_premium(self, message):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            self.bot.send_message(user_id, "Нет доступа.")
            return
        parts = message.text.split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: /remove_premium @username или /remove_premium #ID")
            return
        target = self.find_user(parts[1])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='active', premium_until=None)
        self.db.add_admin_log(user_id, "Отзыв Premium", target['user_id'], parts[1])
        self.bot.send_message(user_id, f"Premium отозван у {parts[1]}.")

    def find_user(self, identifier):
        if identifier.startswith('#'):
            return self.db._fetchone("SELECT * FROM users WHERE user_id_str = ?", (identifier,))
        elif identifier.startswith('@'):
            username = identifier.replace('@', '')
            return self.db._fetchone("SELECT * FROM users WHERE username = ?", (username,))
        else:
            return self.db._fetchone("SELECT * FROM users WHERE user_id = ?", (identifier,))

    # ==================== РЕДАКТИРОВАНИЕ ====================

    def edit_name_handler(self, message):
        user_id = message.from_user.id
        name = message.text.strip()
        if len(name) < 2:
            self.bot.send_message(user_id, "Имя должно быть длиннее.")
            return
        self.db.update_user(user_id, name=name)
        self.bot.send_message(user_id, "Имя обновлено.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_age_handler(self, message):
        user_id = message.from_user.id
        try:
            age = int(message.text.strip())
        except:
            self.bot.send_message(user_id, "Введите число.")
            return
        if age < 14 or age > 100:
            self.bot.send_message(user_id, "Возраст от 14 до 100.")
            return
        category = "14-17" if 14 <= age <= 17 else "18-100"
        self.db.update_user(user_id, age=age, category=category)
        self.bot.send_message(user_id, "Возраст обновлён.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_city_handler(self, message):
        user_id = message.from_user.id
        city = message.text.strip()
        if not re.match(RUSSIAN_CITIES_PATTERN, city):
            self.bot.send_message(user_id, "Город с большой буквы на кириллице.")
            return
        if city not in BASHKIR_CITIES:
            self.bot.send_message(user_id, f"Пожалуйста, введите город из списка Башкортостана:\n" + ", ".join(BASHKIR_CITIES))
            return
        self.db.update_user(user_id, city=city)
        self.bot.send_message(user_id, "Город обновлён.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_about_handler(self, message):
        user_id = message.from_user.id
        about = message.text.strip()
        if len(about) < 5:
            self.bot.send_message(user_id, "Минимум 5 символов.")
            return
        self.db.update_user(user_id, about=about)
        self.bot.send_message(user_id, "Описание обновлено.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_interests_handler(self, message):
        user_id = message.from_user.id
        interests = message.text.strip()
        if len(interests) < 2:
            self.bot.send_message(user_id, "Введите хотя бы один интерес.")
            return
        self.db.update_user(user_id, interests=interests)
        self.bot.send_message(user_id, "Интересы обновлены.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_photo_handler(self, message):
        user_id = message.from_user.id
        if not message.photo:
            self.bot.send_message(user_id, "Отправьте фото.")
            return
        file_id = message.photo[-1].file_id
        self.db.update_user(user_id, photo_file_id=file_id)
        self.bot.send_message(user_id, "Фото обновлено.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    def edit_gender_handler(self, message):
        user_id = message.from_user.id
        gender = message.text.strip().lower()
        if gender not in ['мужской', 'женский']:
            self.bot.send_message(user_id, "Введите 'мужской' или 'женский'.")
            return
        self.db.update_user(user_id, gender='male' if gender == 'мужской' else 'female')
        self.bot.send_message(user_id, "Пол обновлён.")
        self.bot.set_state(user_id, None)
        self.cmd_profile(message)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def check_user_access(self, user_id):
        user = self.db.get_user(user_id)
        if not user:
            self.bot.send_message(user_id, "Пожалуйста, зарегистрируйтесь через /start")
            return False
        if user['status'] == 'blocked':
            self.bot.send_message(user_id, "Ваш аккаунт заблокирован.")
            return False
        unpaid = self.db.get_total_unpaid_fine_amount(user_id)
        if unpaid > 0:
            self.bot.send_message(user_id, f"У вас есть неоплаченный штраф на сумму {unpaid} Stars. Оплатите его.", reply_markup=self.get_fine_pay_keyboard())
            return False
        if not user['registered']:
            self.bot.send_message(user_id, "Завершите регистрацию через /start")
            return False
        return True

    def get_fine_pay_keyboard(self):
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("💳 ОПЛАТИТЬ ШТРАФ", callback_data="pay_fine"),
            types.InlineKeyboardButton("💰 ПОПОЛНИТЬ БАЛАНС", callback_data="shop_topup"),
            types.InlineKeyboardButton("❌ ОБЖАЛОВАТЬ", callback_data="appeal_fine")
        )
        return markup

    def get_admin_stats(self):
        total = self.db.get_total_users()
        active = self.db.get_active_visible_users()
        blocked = self.db.get_blocked_users()
        pending_verif = self.db.get_verification_pending()
        verified = self.db.get_verified_users()
        likes = self.db.get_total_likes()
        mutual = self.db.get_total_mutual()
        drafts = self.db.get_total_drafts()
        reports = self.db.get_total_reports()
        stars = self.db.get_total_stars_in_system()
        premium = self.db.get_premium_users_count()
        today = self.db.get_today_stats()
        text = f"📊 Статистика бота\n\nВсего пользователей: {total}\nАктивных анкет: {active}\nЗаблокированных: {blocked}\nНа верификации: {pending_verif}\nВерифицированных: {verified}\nВсего лайков: {likes}\nВзаимностей: {mutual}\nЧерновиков: {drafts}\nЖалоб: {reports}\nВсего Stars в системе: {stars}\nPremium пользователей: {premium}\n\nЗа сегодня:\nНовых: {today['new_users']}\nЛайков: {today['likes']}\nШтрафов: {today['fines']}"
        return text

    def get_admin_menu(self):
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            ("1️⃣ Жалобы", "admin_reports"),
            ("2️⃣ Пользователи", "admin_users"),
            ("3️⃣ Анкеты на проверку", "admin_verification"),
            ("4️⃣ Заблокированные", "admin_blocked"),
            ("5️⃣ Верификация", "admin_verification_pending"),
            ("6️⃣ Управление категориями", "admin_categories"),
            ("7️⃣ Статистика", "admin_stats"),
            ("8️⃣ Рассылка", "admin_broadcast"),
            ("9️⃣ Настройки бота", "admin_settings"),
            ("🔟 Управление штрафами", "admin_fines_manage"),
            ("1️⃣1️⃣ Управление Stars", "admin_stars_manage"),
            ("📋 Логи", "admin_logs")
        ]
        for label, callback in buttons:
            markup.add(types.InlineKeyboardButton(label, callback_data=callback))
        return markup

    def start_search(self, user_id):
        self.db.update_user(user_id, last_activity=datetime.now().isoformat())
        self.bot.send_message(user_id, "Ищем анкеты рядом с вами...\nЗагрузка...")
        self.show_next_profile(user_id)

    def show_next_profile(self, user_id):
        user = self.db.get_user(user_id)
        if not user or not user['visible']:
            return
        liked = self.db._fetchall("SELECT to_user_id FROM likes WHERE from_user_id = ?", (user_id,))
        liked_ids = [r['to_user_id'] for r in liked]
        drafted = self.db._fetchall("SELECT target_user_id FROM drafts WHERE user_id = ?", (user_id,))
        drafted_ids = [r['target_user_id'] for r in drafted]
        excluded = set(liked_ids + drafted_ids)
        filters = self.user_filters.get(user_id, {})
        query = "SELECT * FROM users WHERE visible = 1 AND status NOT IN ('blocked', 'hidden') AND registered = 1 AND verified = 1 AND user_id != ? AND category = ?"
        params = [user_id, user['category']]
        if filters.get('age_min'):
            query += " AND age >= ?"
            params.append(filters['age_min'])
        if filters.get('age_max'):
            query += " AND age <= ?"
            params.append(filters['age_max'])
        if filters.get('city'):
            query += " AND city = ?"
            params.append(filters['city'])
        if filters.get('gender'):
            query += " AND gender = ?"
            params.append(filters['gender'])
        if excluded:
            placeholders = ','.join(['?'] * len(excluded))
            query += f" AND user_id NOT IN ({placeholders})"
            params.extend(excluded)
        query += " ORDER BY RANDOM() LIMIT 1"
        candidates = self.db._fetchall(query, tuple(params))
        if not candidates:
            self.bot.send_message(user_id, "Анкеты рядом с вами закончились.\nПопробуйте изменить параметры поиска или зайдите позже — появятся новые люди.",
                                  reply_markup=types.InlineKeyboardMarkup().add(
                                      types.InlineKeyboardButton("🔄 ОБНОВИТЬ ПОИСК", callback_data="refresh_search"),
                                      types.InlineKeyboardButton("⚙️ НАСТРОЙКИ", callback_data="filter_menu")
                                  ))
            return
        target = candidates[0]
        self.send_profile(user_id, target)

    def send_profile(self, user_id, target):
        gender_text = "Мужской" if target.get('gender') == 'male' else "Женский"
        text = f"ID: {target['user_id_str']}\n"
        text += f"{target['name']}, {target['age']} лет\n"
        text += f"{target['city']}\n"
        text += f"{target['about']}\n"
        text += f"Интересы: {target['interests']}\n"
        text += f"Теги: {target['tags']}\n"
        text += f"Категория: {target['category']}\n"
        text += f"Пол: {gender_text}"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("❤️ ЛАЙК", callback_data=f"like_{target['user_id']}"),
            types.InlineKeyboardButton("👎 ДИЗЛАЙК", callback_data=f"dislike_{target['user_id']}"),
            types.InlineKeyboardButton("📝 В ЧЕРНОВИКИ", callback_data=f"draft_{target['user_id']}"),
            types.InlineKeyboardButton("⚠️ ЖАЛОБА", callback_data=f"report_{target['user_id']}"),
            types.InlineKeyboardButton("🔍 ФИЛЬТРЫ", callback_data="filter_menu")
        )
        if target['photo_file_id']:
            self.bot.send_photo(user_id, target['photo_file_id'], caption=text, reply_markup=markup)
        else:
            self.bot.send_message(user_id, text, reply_markup=markup)

    def get_all_tags(self):
        return [
            (1, "Музыка", "🎵"), (2, "Спорт", "⚽"), (3, "Книги", "📚"), (4, "Игры", "🎮"),
            (5, "Кино", "🎬"), (6, "Путешествия", "✈️"), (7, "Кулинария", "🍳"), (8, "Йога", "🧘"),
            (9, "Искусство", "🎨"), (10, "Животные", "🐾"), (11, "Природа", "🌿"), (12, "IT/Технологии", "💻"),
            (13, "Романтика", "❤️"), (14, "Дружба", "🤝"), (15, "Вечеринки", "🎉"), (16, "Саморазвитие", "🧠"),
            (17, "Бизнес", "💼"), (18, "Семья", "👪"), (19, "Религия", "⛪"), (20, "Политика", "🗳️"),
            (21, "Здоровье", "💪"), (22, "Творчество", "🎭")
        ]

    def send_tag_selection(self, user_id, state_name):
        tags = self.get_all_tags()
        markup = types.InlineKeyboardMarkup(row_width=5)
        buttons = []
        for tag_id, tag_name, emoji in tags:
            buttons.append(types.InlineKeyboardButton(f"{emoji} {tag_name}", callback_data=f"tag_select_{state_name}_{tag_id}"))
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("✅ ГОТОВО", callback_data=f"tag_done_{state_name}"))
        self.bot.send_message(user_id, "Выберите свои интересы (теги). Нажмите на номера тегов, которые хотите выбрать. (до 5)", reply_markup=markup)

    def handle_tag_selection(self, call, state_name):
        user_id = call.from_user.id
        if user_id not in self.temp_tags:
            self.temp_tags[user_id] = []
        tag_id = int(call.data.split('_')[-1])
        if tag_id in self.temp_tags[user_id]:
            self.temp_tags[user_id].remove(tag_id)
        else:
            if len(self.temp_tags[user_id]) >= 5:
                self.bot.answer_callback_query(call.id, "Вы можете выбрать не более 5 тегов.", show_alert=True)
                return
            self.temp_tags[user_id].append(tag_id)
        self.bot.answer_callback_query(call.id, f"Тег {'добавлен' if tag_id in self.temp_tags[user_id] else 'удалён'}")
        self.bot.delete_message(call.message.chat.id, call.message.message_id)
        self.send_tag_selection(user_id, state_name)

    def tag_done_handler(self, call, state_name):
        user_id = call.from_user.id
        if user_id not in self.temp_tags or not self.temp_tags[user_id]:
            self.bot.answer_callback_query(call.id, "Выберите хотя бы один тег.", show_alert=True)
            return
        tags_str = ",".join(map(str, self.temp_tags[user_id]))
        self.db.update_user(user_id, tags=tags_str)
        del self.temp_tags[user_id]
        self.bot.answer_callback_query(call.id, "Теги сохранены!")
        if state_name == "reg_tags":
            self.bot.set_state(user_id, UserStates.reg_photo)
            self.bot.send_message(user_id, "Отправьте своё фото (Оно будет в вашей анкете)")
        elif state_name == "edit_tags":
            self.bot.send_message(user_id, "Теги обновлены.")
            self.bot.set_state(user_id, None)
            self.cmd_profile(call.message)

    def start_registration(self, user_id):
        self.bot.set_state(user_id, UserStates.reg_name)
        self.bot.send_message(user_id, "Для начала создадим вашу анкету!\nКак вас зовут? (Напишите имя)")

    def start_edit_tags(self, user_id):
        self.bot.set_state(user_id, UserStates.edit_interests)
        self.send_tag_selection(user_id, "edit_tags")

    def get_edit_choose_keyboard(self):
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [
            types.InlineKeyboardButton("1", callback_data="edit_1"),
            types.InlineKeyboardButton("2", callback_data="edit_2"),
            types.InlineKeyboardButton("3", callback_data="edit_3"),
            types.InlineKeyboardButton("4", callback_data="edit_4"),
            types.InlineKeyboardButton("5", callback_data="edit_5"),
            types.InlineKeyboardButton("6", callback_data="edit_6"),
            types.InlineKeyboardButton("7", callback_data="edit_7"),
            types.InlineKeyboardButton("8", callback_data="edit_8"),
            types.InlineKeyboardButton("🔙 НАЗАД", callback_data="edit_back")
        ]
        markup.add(*buttons)
        return markup

    def handle_edit_callback(self, call):
        user_id = call.from_user.id
        data = call.data
        if data == "edit_back":
            self.cmd_profile(call.message)
            return
        if data == "edit_1":
            self.bot.set_state(user_id, UserStates.edit_name)
            self.bot.send_message(user_id, "Введите новое имя:")
            return
        if data == "edit_2":
            self.bot.set_state(user_id, UserStates.edit_age)
            self.bot.send_message(user_id, "Введите новый возраст (от 14 до 100):")
            return
        if data == "edit_3":
            self.bot.set_state(user_id, UserStates.edit_city)
            self.bot.send_message(user_id, "Введите новый город (с большой буквы):")
            return
        if data == "edit_4":
            self.bot.set_state(user_id, UserStates.edit_about)
            self.bot.send_message(user_id, "Введите новое описание:")
            return
        if data == "edit_5":
            self.bot.set_state(user_id, UserStates.edit_interests)
            self.bot.send_message(user_id, "Введите новые интересы через запятую:")
            return
        if data == "edit_6":
            self.bot.set_state(user_id, UserStates.edit_photo)
            self.bot.send_message(user_id, "Отправьте новое фото:")
            return
        if data == "edit_7":
            self.start_edit_tags(user_id)
            return
        if data == "edit_8":
            self.bot.set_state(user_id, UserStates.edit_gender)
            self.bot.send_message(user_id, "Введите новый пол (мужской или женский):")
            return

    # ==================== ФИЛЬТРЫ ====================

    def show_filter_menu(self, user_id):
        filters = self.user_filters.get(user_id, {})
        gender_text = "Мужской" if filters.get('gender') == 'male' else "Женский" if filters.get('gender') == 'female' else "Любой"
        text = "Настройки поиска\n\n"
        text += f"1 Возраст: {filters.get('age_min', 'любой')} - {filters.get('age_max', 'любой')}\n"
        text += f"2 Город: {filters.get('city', 'любой')}\n"
        text += f"3 Пол: {gender_text}\n"
        text += f"4 Теги: {filters.get('tags', 'любые')}\n"
        text += f"5 Категория: {filters.get('category', 'любая')}\n\nЧто хотите изменить?"
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("1", callback_data="filter_age"),
            types.InlineKeyboardButton("2", callback_data="filter_city"),
            types.InlineKeyboardButton("3", callback_data="filter_gender"),
            types.InlineKeyboardButton("4", callback_data="filter_tags"),
            types.InlineKeyboardButton("СБРОСИТЬ", callback_data="filter_reset"),
            types.InlineKeyboardButton("НАЙТИ", callback_data="filter_apply")
        )
        self.bot.send_message(user_id, text, reply_markup=markup)

    def filter_age_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        if '-' in text:
            parts = text.split('-')
            try:
                min_age = int(parts[0].strip())
                max_age = int(parts[1].strip())
                if min_age < 14 or max_age > 100 or min_age > max_age:
                    self.bot.send_message(user_id, "Некорректный диапазон.")
                    return
                if user_id not in self.user_filters:
                    self.user_filters[user_id] = {}
                self.user_filters[user_id]['age_min'] = min_age
                self.user_filters[user_id]['age_max'] = max_age
                self.bot.send_message(user_id, "Фильтр возраста сохранён.")
            except:
                self.bot.send_message(user_id, "Введите в формате 20-30")
                return
        else:
            self.bot.send_message(user_id, "Используйте дефис, например 20-30")
            return
        self.bot.set_state(user_id, None)
        self.show_filter_menu(user_id)

    def filter_city_handler(self, message):
        user_id = message.from_user.id
        city = message.text.strip()
        if not re.match(RUSSIAN_CITIES_PATTERN, city):
            self.bot.send_message(user_id, "Введите город с большой буквы.")
            return
        if city not in BASHKIR_CITIES:
            self.bot.send_message(user_id, f"Пожалуйста, введите город из списка Башкортостана:\n" + ", ".join(BASHKIR_CITIES))
            return
        if user_id not in self.user_filters:
            self.user_filters[user_id] = {}
        self.user_filters[user_id]['city'] = city
        self.bot.send_message(user_id, "Город сохранён.")
        self.bot.set_state(user_id, None)
        self.show_filter_menu(user_id)

    def filter_gender_handler(self, message):
        user_id = message.from_user.id
        gender = message.text.strip().lower()
        if gender not in ['мужской', 'женский']:
            self.bot.send_message(user_id, "Введите 'мужской' или 'женский'.")
            return
        if user_id not in self.user_filters:
            self.user_filters[user_id] = {}
        self.user_filters[user_id]['gender'] = 'male' if gender == 'мужской' else 'female'
        self.bot.send_message(user_id, "Пол сохранён.")
        self.bot.set_state(user_id, None)
        self.show_filter_menu(user_id)

    # ==================== МАГАЗИН ====================

    def show_topup_options(self, user_id):
        markup = types.InlineKeyboardMarkup(row_width=3)
        amounts = [50, 100, 250, 500, 1000, 2500]
        buttons = [types.InlineKeyboardButton(str(a), callback_data=f"topup_{a}") for a in amounts]
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("🔙 НАЗАД", callback_data="shop_back"))
        self.bot.send_message(user_id, "Выберите сумму Stars для пополнения:", reply_markup=markup)

    def handle_shop_selection(self, user_id, item):
        if item == "1":
            self.buy_premium(user_id, 1, 9)
        elif item == "2":
            self.buy_premium(user_id, 7, 49)
        elif item == "3":
            self.buy_premium(user_id, 30, 99)
        elif item == "4":
            self.buy_premium(user_id, 90, 199)
        elif item == "5":
            self.buy_premium(user_id, 180, 349)
        elif item == "6":
            self.buy_premium(user_id, 365, 599)
        elif item == "7":
            self.show_topup_options(user_id)
        elif item == "8":
            self.handle_shop_purchase_by_type(user_id, "shop_verif_fast")
        elif item == "9":
            self.handle_shop_purchase_by_type(user_id, "shop_drafts")
        else:
            self.bot.send_message(user_id, "Неверный выбор.")

    def buy_premium(self, user_id, days, cost):
        if self.db.deduct_stars(user_id, cost, f"Premium {days} дней"):
            until = datetime.now() + timedelta(days=days)
            self.db.update_user(user_id, status='premium', premium_until=until.isoformat())
            self.bot.send_message(user_id, f"Подписка Premium активирована на {days} дней. До: {until.strftime('%d.%m.%Y')}")
        else:
            self.bot.send_message(user_id, f"Недостаточно Stars. Нужно {cost} Stars.")

    def handle_shop_purchase(self, call):
        user_id = call.from_user.id
        data = call.data
        if data == "shop_verif_fast":
            if self.db.deduct_stars(user_id, 150, "Ускоренная верификация"):
                req = self.db._fetchone("SELECT * FROM verification_requests WHERE user_id = ? AND status = 'pending'", (user_id,))
                if req:
                    for admin in ADMIN_IDS:
                        self.bot.send_message(admin, f"🚀 Ускоренная верификация для пользователя {user_id}")
                    self.bot.send_message(user_id, "Ваша верификация будет проверена в течение 15 минут!")
                    self.bot.answer_callback_query(call.id, "Запрос отправлен!")
                else:
                    self.bot.send_message(user_id, "У вас нет активного запроса на верификацию.")
                    self.bot.answer_callback_query(call.id)
            else:
                self.bot.send_message(user_id, "Недостаточно Stars для ускоренной верификации (150 Stars).")
                self.bot.answer_callback_query(call.id)
        elif data == "shop_drafts":
            if self.db.deduct_stars(user_id, 100, "Дополнительные черновики"):
                self.bot.send_message(user_id, "Лимит черновиков увеличен до 100!")
                self.bot.answer_callback_query(call.id, "Черновики увеличены!")
            else:
                self.bot.send_message(user_id, "Недостаточно Stars для дополнительных черновиков (100 Stars).")
                self.bot.answer_callback_query(call.id)

    def handle_shop_purchase_by_type(self, user_id, purchase_type):
        if purchase_type == "shop_verif_fast":
            if self.db.deduct_stars(user_id, 150, "Ускоренная верификация"):
                req = self.db._fetchone("SELECT * FROM verification_requests WHERE user_id = ? AND status = 'pending'", (user_id,))
                if req:
                    for admin in ADMIN_IDS:
                        self.bot.send_message(admin, f"🚀 Ускоренная верификация для пользователя {user_id}")
                    self.bot.send_message(user_id, "Ваша верификация будет проверена в течение 15 минут!")
                else:
                    self.bot.send_message(user_id, "У вас нет активного запроса на верификацию.")
            else:
                self.bot.send_message(user_id, "Недостаточно Stars для ускоренной верификации (150 Stars).")
        elif purchase_type == "shop_drafts":
            if self.db.deduct_stars(user_id, 100, "Дополнительные черновики"):
                self.bot.send_message(user_id, "Лимит черновиков увеличен до 100!")
            else:
                self.bot.send_message(user_id, "Недостаточно Stars для дополнительных черновиков (100 Stars).")

    # ==================== АНОНИМНЫЙ ЧАТ ====================

    def start_anon_search(self, user_id):
        if user_id in self.anon_waiting:
            self.bot.send_message(user_id, "Вы уже в поиске. Подождите...")
            return
        self.anon_waiting.append(user_id)
        self.bot.set_state(user_id, UserStates.anon_waiting)
        self.bot.send_message(user_id, "🔍 Ищем собеседника... Пожалуйста, подождите")
        if len(self.anon_waiting) >= 2:
            user1 = self.anon_waiting.pop(0)
            user2 = self.anon_waiting.pop(0)
            self.db.create_chat_session(user1, user2)
            self.bot.send_message(user1, "Чат найден! Вы можете общаться анонимно.")
            self.bot.send_message(user2, "Чат найден! Вы можете общаться анонимно.")
            self.bot.set_state(user1, UserStates.anon_chat)
            self.bot.set_state(user2, UserStates.anon_chat)

    def anon_waiting_handler(self, message):
        self.bot.send_message(message.from_user.id, "Ищем собеседника... подождите.")

    def anon_chat_handler(self, message):
        user_id = message.from_user.id
        session = self.db.get_active_chat_for_user(user_id)
        if not session:
            self.bot.send_message(user_id, "Чат завершён. Начните новый через /anon")
            self.bot.set_state(user_id, None)
            return
        partner_id = self.db.get_chat_partner(user_id)
        if not partner_id:
            self.bot.send_message(user_id, "Ошибка чата.")
            return
        try:
            self.bot.send_message(partner_id, f"Аноним: {message.text}")
        except:
            self.bot.send_message(user_id, "Не удалось отправить сообщение.")

    # ==================== ОБРАБОТЧИКИ КОЛБЭКОВ ====================

    def handle_callback(self, call):
        user_id = call.from_user.id
        data = call.data

        # Подписка на канал
        if data == "check_subscription":
            try:
                member = self.bot.get_chat_member(CHANNEL_USERNAME, user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    self.db.update_user(user_id, has_subscribed=1)
                    self.bot.answer_callback_query(call.id, "Спасибо за подписку!")
                    self.cmd_start(call.message)
                else:
                    self.bot.answer_callback_query(call.id, "Вы не подписаны на канал.", show_alert=True)
            except:
                self.bot.answer_callback_query(call.id, "Проверьте подписку.", show_alert=True)
            return

        # Пол
        if data.startswith("gender_"):
            gender = data.split('_')[1]
            self.db.update_user(user_id, gender=gender)
            self.bot.answer_callback_query(call.id, f"Пол выбран: {'Мужской' if gender == 'male' else 'Женский'}")
            self.bot.set_state(user_id, UserStates.reg_search_gender)
            markup = types.InlineKeyboardMarkup(row_width=3)
            markup.add(
                types.InlineKeyboardButton("👨 Мужской", callback_data="search_gender_male"),
                types.InlineKeyboardButton("👩 Женский", callback_data="search_gender_female"),
                types.InlineKeyboardButton("👥 Всех", callback_data="search_gender_all")
            )
            self.bot.send_message(user_id, "Кого вы ищете?", reply_markup=markup)
            return

        # Поиск пола
        if data.startswith("search_gender_"):
            gender = data.split('_')[2]
            map_gender = {'male': 'male', 'female': 'female', 'all': 'all'}
            self.db.update_user(user_id, search_gender=map_gender[gender])
            self.bot.answer_callback_query(call.id, f"Ищем: {'Мужской' if gender == 'male' else 'Женский' if gender == 'female' else 'Всех'}")
            self.bot.set_state(user_id, UserStates.reg_name)
            self.bot.send_message(user_id, "Как вас зовут? (Напишите имя)")
            return

        # Теги
        if data.startswith("tag_select_"):
            parts = data.split('_')
            state_name = parts[2]
            self.handle_tag_selection(call, state_name)
            return

        if data.startswith("tag_done_"):
            state_name = data.split('_')[2]
            self.tag_done_handler(call, state_name)
            return

        # Подтверждение регистрации
        if data == "confirm_reg_yes":
            self.db.set_registered(user_id)
            self.db.update_user(user_id, visible=1, last_activity=datetime.now().isoformat())
            self.db.add_stars(user_id, 10, "Бонус за регистрацию")
            self.bot.send_message(user_id, "✅ Регистрация завершена!\n\nТеперь пройдите верификацию.\nОтправьте видео-кружок со словом «РусскиеЗнакомства»")
            self.bot.answer_callback_query(call.id, "Профиль создан!")
            return

        if data == "confirm_reg_no":
            self.bot.set_state(user_id, UserStates.edit_choose)
            self.bot.send_message(user_id, "Что вы хотите изменить?\n1 Имя\n2 Возраст\n3 Город\n4 О себе\n5 Интересы\n6 Фото\n7 Теги\n8 Пол",
                                  reply_markup=self.get_edit_choose_keyboard())
            self.bot.answer_callback_query(call.id)
            return

        # Реакции
        if data.startswith("like_"):
            target_id = int(data.split('_')[1])
            self.handle_like(call, target_id)
            return
        if data.startswith("dislike_"):
            target_id = int(data.split('_')[1])
            self.handle_dislike(call, target_id)
            return
        if data.startswith("draft_"):
            target_id = int(data.split('_')[1])
            self.handle_draft(call, target_id)
            return

        # Фильтры
        if data == "filter_menu":
            self.show_filter_menu(user_id)
            self.bot.answer_callback_query(call.id)
            return
        if data == "filter_age":
            self.bot.set_state(user_id, UserStates.filter_age)
            self.bot.send_message(user_id, "Введите диапазон возрастов через дефис, например: 20-30")
            return
        if data == "filter_city":
            self.bot.set_state(user_id, UserStates.filter_city)
            self.bot.send_message(user_id, "Введите город (с большой буквы):")
            return
        if data == "filter_gender":
            self.bot.set_state(user_id, UserStates.filter_gender)
            self.bot.send_message(user_id, "Введите пол для поиска (мужской или женский):")
            return
        if data == "filter_reset":
            self.user_filters[user_id] = {}
            self.bot.send_message(user_id, "Фильтры сброшены.")
            self.show_next_profile(user_id)
            return
        if data == "filter_apply":
            self.show_next_profile(user_id)
            return
        if data == "refresh_search":
            self.show_next_profile(user_id)
            return

        # Профиль
        if data == "edit_profile":
            self.bot.set_state(user_id, UserStates.edit_choose)
            self.bot.send_message(user_id, "Что вы хотите изменить?\n1 Имя\n2 Возраст\n3 Город\n4 О себе\n5 Интересы\n6 Фото\n7 Теги\n8 Пол",
                                  reply_markup=self.get_edit_choose_keyboard())
            self.bot.answer_callback_query(call.id)
            return
        if data == "hide_profile":
            self.db.update_user(user_id, visible=0)
            self.bot.answer_callback_query(call.id, "Анкета скрыта.")
            self.bot.send_message(user_id, "Ваша анкета скрыта.")
            return
        if data == "delete_profile":
            self.bot.send_message(user_id, "Вы уверены? Напишите 'ДА' для подтверждения.")
            self.bot.set_state(user_id, UserStates.support)
            return
        if data == "view_drafts":
            self.cmd_drafts(call.message)
            return
        if data == "edit_tags":
            self.start_edit_tags(user_id)
            return

        # Магазин
        if data.startswith("shop_"):
            shop_item = data.split('_')[1]
            if shop_item.isdigit():
                self.handle_shop_selection(user_id, shop_item)
            else:
                self.handle_shop_purchase(call)
            self.bot.answer_callback_query(call.id)
            return
        if data == "shop_topup":
            self.show_topup_options(user_id)
            return
        if data == "shop_back":
            self.cmd_shop(call.message)
            return
        if data.startswith("topup_"):
            amount = int(data.split('_')[1])
            self.db.add_stars(user_id, amount, f"Пополнение на {amount} Stars")
            self.bot.send_message(user_id, f"Баланс пополнен на {amount} Stars.")
            self.bot.answer_callback_query(call.id)
            return

        # Штрафы
        if data == "pay_fine":
            self.start_fine_payment(user_id)
            self.bot.answer_callback_query(call.id)
            return
        if data == "appeal_fine":
            self.start_appeal_fine(user_id)
            self.bot.answer_callback_query(call.id)
            return

        # Восстановление
        if data == "restore_profile":
            self.db.update_user(user_id, visible=1)
            self.bot.send_message(user_id, "Анкета восстановлена.")
            self.bot.answer_callback_query(call.id)
            return
        if data == "stay_visible":
            self.db.update_user(user_id, last_activity=datetime.now().isoformat())
            self.bot.send_message(user_id, "Активность обновлена.")
            self.bot.answer_callback_query(call.id)
            return
        if data == "restart_registration":
            self.db.delete_user(user_id)
            self.cmd_start(call.message)
            return
        if data == "start_search":
            self.start_search(user_id)
            self.bot.answer_callback_query(call.id)
            return

        # Админ
        if data.startswith("admin_"):
            self.handle_admin_callback(call)
            return

        self.bot.answer_callback_query(call.id, "Неизвестная команда")

    # ==================== АДМИН ОБРАБОТЧИКИ ====================

    def handle_admin_callback(self, call):
        admin_id = call.from_user.id
        if admin_id not in ADMIN_IDS:
            self.bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
            return
        data = call.data
        if data == "admin_reports":
            self.admin_reports_handler(call)
        elif data == "admin_users":
            self.admin_users_handler(call)
        elif data == "admin_verification":
            self.admin_verification_pending_handler(call)
        elif data == "admin_blocked":
            blocked = self.db._fetchall("SELECT user_id, name, user_id_str FROM users WHERE status = 'blocked'")
            if blocked:
                text = "Заблокированные пользователи:\n"
                for u in blocked:
                    text += f"{u['name']} (ID: {u['user_id_str']})\n"
                self.bot.send_message(admin_id, text)
            else:
                self.bot.send_message(admin_id, "Нет заблокированных.")
        elif data == "admin_verification_pending":
            self.admin_verification_pending_handler(call)
        elif data == "admin_categories":
            self.bot.send_message(admin_id, "Управление категориями (в разработке).")
        elif data == "admin_stats":
            self.cmd_stats(call.message)
        elif data == "admin_broadcast":
            self.admin_broadcast_handler(call)
        elif data == "admin_settings":
            self.admin_settings_handler(call)
        elif data == "admin_fines_manage":
            self.admin_fines_manage_handler(call)
        elif data == "admin_stars_manage":
            self.admin_stars_manage_handler(call)
        elif data == "admin_logs":
            self.cmd_logs(call.message)
        elif data.startswith("admin_report_"):
            self.admin_report_action(call)
        elif data.startswith("admin_verif_"):
            self.admin_verification_action(call)
        elif data == "admin_back":
            self.cmd_admin(call.message)
        elif data == "admin_give_stars":
            self.admin_give_stars_handler(call)
        else:
            self.bot.answer_callback_query(call.id, "Неизвестная админ-команда")

    def admin_reports_handler(self, call):
        admin_id = call.from_user.id
        reports = self.db.get_pending_reports()
        if not reports:
            self.bot.send_message(admin_id, "Нет новых жалоб.")
            return
        with self.bot.retrieve_data(admin_id) as data:
            data['reports_list'] = reports
            data['reports_index'] = 0
        self.show_report(admin_id, reports[0], 0)

    def show_report(self, admin_id, report, index):
        reported = self.db.get_user(report['reported_user_id'])
        reporter = self.db.get_user(report['reporter_id'])
        text = f"Жалоба #{report['id']} ({index+1})\nПользователь: {reported['name']} (ID: {reported['user_id_str']})\nПричина: {report['reason']}\nДата: {report['timestamp'][:10]}\nПожаловался: {reporter['name']}"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🚫 ЗАБЛОКИРОВАТЬ", callback_data=f"admin_report_block_{report['id']}"),
            types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"admin_report_reject_{report['id']}"),
            types.InlineKeyboardButton("💰 ВЫДАТЬ ШТРАФ", callback_data=f"admin_report_fine_{report['id']}"),
            types.InlineKeyboardButton("⏩ ДАЛЕЕ", callback_data=f"admin_report_next_{report['id']}")
        )
        self.bot.send_message(admin_id, text, reply_markup=markup)

    def admin_report_action(self, call):
        admin_id = call.from_user.id
        parts = call.data.split('_')
        action = parts[2]
        report_id = int(parts[3])
        report = self.db._fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if not report:
            self.bot.answer_callback_query(call.id, "Жалоба не найдена.")
            return
        if action == "block":
            self.db.update_user(report['reported_user_id'], status='blocked')
            self.db.resolve_report(report_id, "Заблокирован", 'resolved')
            self.db.add_admin_log(admin_id, "Блокировка", report['reported_user_id'])
            self.bot.send_message(admin_id, "Пользователь заблокирован.")
            self.bot.answer_callback_query(call.id, "Заблокирован")
        elif action == "reject":
            self.db.resolve_report(report_id, "Отклонено", 'rejected')
            self.db.add_admin_log(admin_id, "Отклонение жалобы")
            self.bot.send_message(admin_id, "Жалоба отклонена.")
            self.bot.answer_callback_query(call.id, "Отклонено")
        elif action == "fine":
            self.bot.set_state(admin_id, UserStates.admin_fine)
            with self.bot.retrieve_data(admin_id) as data_store:
                data_store['fine_report_id'] = report_id
                data_store['fine_user_id'] = report['reported_user_id']
            self.bot.send_message(admin_id, "Введите сумму штрафа:")
            self.bot.answer_callback_query(call.id)
        elif action == "next":
            with self.bot.retrieve_data(admin_id) as data_store:
                reports = data_store.get('reports_list', [])
                index = data_store.get('reports_index', 0) + 1
                if index < len(reports):
                    data_store['reports_index'] = index
                    self.show_report(admin_id, reports[index], index)
                else:
                    self.bot.send_message(admin_id, "Все жалобы просмотрены.")
                self.bot.answer_callback_query(call.id)

    def admin_fine_handler(self, message):
        admin_id = message.from_user.id
        try:
            amount = int(message.text.strip())
        except:
            self.bot.send_message(admin_id, "Введите число.")
            return
        with self.bot.retrieve_data(admin_id) as data:
            report_id = data.get('fine_report_id')
            user_id = data.get('fine_user_id')
        if not user_id:
            self.bot.send_message(admin_id, "Ошибка.")
            self.bot.set_state(admin_id, None)
            return
        self.db.add_fine(user_id, "Нарушение правил", amount, admin_id)
        self.db.add_admin_log(admin_id, "Выдача штрафа", user_id, f"{amount} Stars")
        self.bot.send_message(admin_id, f"Штраф {amount} Stars выдан.")
        self.bot.set_state(admin_id, None)

    def admin_users_handler(self, call):
        admin_id = call.from_user.id
        self.bot.set_state(admin_id, UserStates.admin_user_search)
        self.bot.send_message(admin_id, "Введите ID пользователя (например, #12345) или имя:")

    def admin_user_search_handler(self, message):
        admin_id = message.from_user.id
        query = message.text.strip()
        if query.startswith('#'):
            users = self.db._fetchall("SELECT * FROM users WHERE user_id_str = ?", (query,))
        else:
            users = self.db._fetchall("SELECT * FROM users WHERE name LIKE ?", ('%' + query + '%',))
        if not users:
            self.bot.send_message(admin_id, "Пользователи не найдены.")
            return
        for u in users[:5]:
            text = f"{u['name']} (ID: {u['user_id_str']}) - {u['age']} лет"
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("ПРОСМОТРЕТЬ", callback_data=f"admin_view_user_{u['user_id']}"),
                types.InlineKeyboardButton("ЗАБЛОКИРОВАТЬ", callback_data=f"admin_block_user_{u['user_id']}")
            )
            self.bot.send_message(admin_id, text, reply_markup=markup)
        self.bot.set_state(admin_id, None)

    def admin_verification_pending_handler(self, call):
        admin_id = call.from_user.id
        requests = self.db.get_pending_verifications()
        if not requests:
            self.bot.send_message(admin_id, "Нет запросов на верификацию.")
            return
        with self.bot.retrieve_data(admin_id) as data:
            data['verif_list'] = requests
            data['verif_index'] = 0
        self.show_verification_request(admin_id, requests[0], 0)

    def show_verification_request(self, admin_id, req, index):
        user = self.db.get_user(req['user_id'])
        text = f"Запрос верификации #{index+1}\nПользователь: {user['name']} (ID: {user['user_id_str']})"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ ОДОБРИТЬ", callback_data=f"admin_verif_approve_{req['user_id']}"),
            types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"admin_verif_reject_{req['user_id']}"),
            types.InlineKeyboardButton("📹 ПОСМОТРЕТЬ ВИДЕО", callback_data=f"admin_verif_video_{req['user_id']}"),
            types.InlineKeyboardButton("⏩ ДАЛЕЕ", callback_data=f"admin_verif_next_{req['user_id']}")
        )
        self.bot.send_message(admin_id, text, reply_markup=markup)

    def admin_verification_action(self, call):
        admin_id = call.from_user.id
        parts = call.data.split('_')
        action = parts[2]
        user_id = int(parts[3])
        if action == "approve":
            self.db.approve_verification(user_id, "Одобрено")
            self.db.add_stars(user_id, 15, "Бонус за верификацию")
            self.db.add_admin_log(admin_id, "Одобрение верификации", user_id)
            self.bot.send_message(user_id, "✅ Верификация пройдена! +15 Stars")
            self.bot.send_message(admin_id, "Верификация одобрена.")
            self.bot.answer_callback_query(call.id, "Одобрено")
        elif action == "reject":
            self.bot.send_message(admin_id, "Введите причину отклонения:")
            self.bot.set_state(admin_id, UserStates.admin_verification_reject)
            with self.bot.retrieve_data(admin_id) as data_store:
                data_store['reject_user_id'] = user_id
            self.bot.answer_callback_query(call.id)
        elif action == "video":
            req = self.db._fetchone("SELECT video_file_id FROM verification_requests WHERE user_id = ?", (user_id,))
            if req and req['video_file_id']:
                self.bot.send_video_note(admin_id, req['video_file_id'])
            self.bot.answer_callback_query(call.id)
        elif action == "next":
            with self.bot.retrieve_data(admin_id) as data_store:
                requests = data_store.get('verif_list', [])
                index = data_store.get('verif_index', 0) + 1
                if index < len(requests):
                    data_store['verif_index'] = index
                    self.show_verification_request(admin_id, requests[index], index)
                else:
                    self.bot.send_message(admin_id, "Все запросы обработаны.")
                self.bot.answer_callback_query(call.id)

    def admin_verification_reject_handler(self, message):
        admin_id = message.from_user.id
        reason = message.text.strip()
        with self.bot.retrieve_data(admin_id) as data:
            user_id = data.get('reject_user_id')
        if not user_id:
            self.bot.send_message(admin_id, "Ошибка.")
            self.bot.set_state(admin_id, None)
            return
        self.db.reject_verification(user_id, reason)
        self.db.add_admin_log(admin_id, "Отклонение верификации", user_id, reason)
        self.bot.send_message(user_id, f"❌ Верификация отклонена\nПричина: {reason}")
        self.bot.send_message(admin_id, "Верификация отклонена.")
        self.bot.set_state(admin_id, None)

    def admin_broadcast_handler(self, call):
        admin_id = call.from_user.id
        self.bot.set_state(admin_id, UserStates.admin_broadcast)
        self.bot.send_message(admin_id, "Введите текст для рассылки:")

    def admin_broadcast_message_handler(self, message):
        admin_id = message.from_user.id
        text = message.text
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ ОТПРАВИТЬ", callback_data="broadcast_send"),
            types.InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="broadcast_cancel")
        )
        with self.bot.retrieve_data(admin_id) as data:
            data['broadcast_text'] = text
        total = self.db.get_total_users()
        self.bot.send_message(admin_id, f"Подтвердите рассылку:\n\nТекст: {text}\n\nКому: Всем пользователям ({total})", reply_markup=markup)
        self.bot.set_state(admin_id, None)

    def admin_broadcast_send(self, call):
        admin_id = call.from_user.id
        with self.bot.retrieve_data(admin_id) as data:
            text = data.get('broadcast_text')
        if not text:
            self.bot.send_message(admin_id, "Ошибка.")
            return
        users = self.db._fetchall("SELECT user_id FROM users")
        sent = 0
        for u in users:
            try:
                self.bot.send_message(u['user_id'], text)
                sent += 1
            except:
                pass
        self.db.add_admin_log(admin_id, "Рассылка", None, f"Отправлено {sent} сообщений")
        self.bot.send_message(admin_id, f"Рассылка завершена. Отправлено {sent} сообщений.")
        self.bot.answer_callback_query(call.id)

    def admin_settings_handler(self, call):
        admin_id = call.from_user.id
        settings = self.db._fetchall("SELECT key, value FROM bot_settings")
        text = "Настройки бота:\n\n"
        for s in settings:
            text += f"{s['key']}: {s['value']}\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_back"))
        self.bot.send_message(admin_id, text, reply_markup=markup)

    def admin_fines_manage_handler(self, call):
        admin_id = call.from_user.id
        fines = self.db._fetchall("SELECT * FROM fines WHERE paid = 0")
        if not fines:
            self.bot.send_message(admin_id, "Нет активных штрафов.")
            return
        text = "📋 Активные штрафы:\n\n"
        for f in fines[:10]:
            user = self.db.get_user(f['user_id'])
            text += f"ID: {f['id']} | {user['name']} - {f['amount']} Stars\n"
        self.bot.send_message(admin_id, text)

    def admin_stars_manage_handler(self, call):
        admin_id = call.from_user.id
        self.bot.set_state(admin_id, UserStates.admin_give_stars)
        self.bot.send_message(admin_id, "Введите ID пользователя и сумму Stars через пробел, например: #12345 100")

    def admin_give_stars_handler(self, call):
        admin_id = call.from_user.id
        self.bot.set_state(admin_id, UserStates.admin_give_stars)
        self.bot.send_message(admin_id, "Введите ID пользователя и сумму Stars через пробел:")

    def admin_give_stars_message_handler(self, message):
        admin_id = message.from_user.id
        parts = message.text.strip().split()
        if len(parts) != 2:
            self.bot.send_message(admin_id, "Введите ID и сумму через пробел.")
            return
        user_id_str, amount_str = parts
        try:
            amount = int(amount_str)
        except:
            self.bot.send_message(admin_id, "Сумма должна быть числом.")
            return
        user = self.db._fetchone("SELECT * FROM users WHERE user_id_str = ?", (user_id_str,))
        if not user:
            self.bot.send_message(admin_id, "Пользователь не найден.")
            return
        self.db.add_stars(user['user_id'], amount, f"Выдано администратором")
        self.db.add_admin_log(admin_id, "Выдача Stars", user['user_id'], f"{amount} Stars")
        self.bot.send_message(admin_id, f"Пользователю {user_id_str} выдано {amount} Stars.")
        self.bot.set_state(admin_id, None)

    # ==================== РЕАКЦИИ ====================

    def handle_like(self, call, target_user_id):
        user_id = call.from_user.id
        likes_today, dislikes_today = self.db.get_daily_reactions(user_id)
        limit = int(self.db.get_setting('reaction_limit') or 500)
        if likes_today + dislikes_today >= limit:
            self.bot.answer_callback_query(call.id, "Лимит реакций исчерпан.", show_alert=True)
            return
        existing = self.db.get_reaction(user_id, target_user_id)
        if existing:
            self.bot.answer_callback_query(call.id, "Вы уже оценили эту анкету.", show_alert=True)
            return
        self.db.add_reaction(user_id, target_user_id, 'like')
        self.db.increment_reaction(user_id, 'like')
        mutual = self.db.get_reaction(target_user_id, user_id)
        if mutual and mutual['type'] == 'like':
            self.bot.send_message(user_id, "💞 Взаимный лайк!")
            self.bot.send_message(target_user_id, "💞 Взаимный лайк!")
            self.db.add_stars(user_id, 5, "Бонус за взаимность")
            self.db.add_stars(target_user_id, 5, "Бонус за взаимность")
        self.bot.answer_callback_query(call.id, "Лайк поставлен!")
        self.show_next_profile(user_id)

    def handle_dislike(self, call, target_user_id):
        user_id = call.from_user.id
        likes_today, dislikes_today = self.db.get_daily_reactions(user_id)
        limit = int(self.db.get_setting('reaction_limit') or 500)
        if likes_today + dislikes_today >= limit:
            self.bot.answer_callback_query(call.id, "Лимит реакций исчерпан.", show_alert=True)
            return
        existing = self.db.get_reaction(user_id, target_user_id)
        if existing:
            self.bot.answer_callback_query(call.id, "Вы уже оценили эту анкету.", show_alert=True)
            return
        self.db.add_reaction(user_id, target_user_id, 'dislike')
        self.db.increment_reaction(user_id, 'dislike')
        self.bot.answer_callback_query(call.id, "Пропускаем...")
        self.show_next_profile(user_id)

    def handle_draft(self, call, target_user_id):
        user_id = call.from_user.id
        existing = self.db.get_reaction(user_id, target_user_id)
        if existing:
            self.bot.answer_callback_query(call.id, "Вы уже оценили эту анкету.", show_alert=True)
            return
        draft_exists = self.db._fetchone("SELECT * FROM drafts WHERE user_id = ? AND target_user_id = ?", (user_id, target_user_id))
        if draft_exists:
            self.bot.answer_callback_query(call.id, "Анкета уже в черновиках.")
            return
        self.db.add_draft(user_id, target_user_id)
        self.bot.answer_callback_query(call.id, "Добавлено в черновики!")
        self.show_next_profile(user_id)

    # ==================== ШТРАФЫ ====================

    def start_fine_payment(self, user_id):
        unpaid = self.db.get_unpaid_fines(user_id)
        total = sum(f['amount'] for f in unpaid)
        if total == 0:
            self.bot.send_message(user_id, "У вас нет неоплаченных штрафов.")
            return
        if self.db.deduct_stars(user_id, total, "Оплата штрафа"):
            for f in unpaid:
                self.db.pay_fine(f['id'])
            self.bot.send_message(user_id, f"Штраф(ы) оплачены! Списано: {total} Stars.")
        else:
            self.bot.send_message(user_id, f"Недостаточно Stars. Нужно {total} Stars.")

    def start_appeal_fine(self, user_id):
        self.bot.send_message(user_id, "Напишите причину обжалования штрафа.")
        self.bot.set_state(user_id, UserStates.support)

    def support_handler(self, message):
        user_id = message.from_user.id
        text = message.text
        for admin_id in ADMIN_IDS:
            self.bot.send_message(admin_id, f"Обращение от {user_id}:\n{text}")
        self.bot.send_message(user_id, "Ваше обращение отправлено.")
        self.bot.set_state(user_id, None)

    def report_reason_handler(self, message):
        user_id = message.from_user.id
        reason = message.text.strip()
        with self.bot.retrieve_data(user_id) as data_store:
            reported_id = data_store.get('reported_user_id')
        if not reported_id:
            self.bot.send_message(user_id, "Ошибка.")
            self.bot.set_state(user_id, None)
            return
        self.db.add_report(user_id, reported_id, reason, reason)
        self.bot.send_message(user_id, "Жалоба отправлена.")
        self.bot.set_state(user_id, None)

    # ==================== ВИДЕО ====================

    def video_note_handler(self, message):
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        if not user or not user['registered']:
            self.bot.send_message(user_id, "Сначала завершите регистрацию.")
            return
        if user['verified'] == 1:
            self.bot.send_message(user_id, "Вы уже верифицированы.")
            return
        if message.video_note:
            file_id = message.video_note.file_id
            self.db.add_verification_request(user_id, file_id)
            self.db.update_user(user_id, verification_video_file_id=file_id)
            self.bot.send_message(user_id, "Кружок получен! Ожидайте проверки.")
            for admin_id in ADMIN_IDS:
                self.bot.send_message(admin_id, f"📹 Новый запрос на верификацию от {user['name']}")
                self.bot.send_video_note(admin_id, file_id)
        else:
            self.bot.send_message(user_id, "Отправьте видео-кружок.")

    # ==================== АДМИН ОБРАБОТЧИКИ ДОПОЛНИТЕЛЬНЫЕ ====================

    def admin_ban_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='blocked')
        self.db.add_admin_log(user_id, "Бан", target['user_id'], text)
        self.bot.send_message(user_id, f"Пользователь {text} забанен.")
        self.bot.set_state(user_id, None)

    def admin_unban_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='active')
        self.db.add_admin_log(user_id, "Разбан", target['user_id'], text)
        self.bot.send_message(user_id, f"Пользователь {text} разбанен.")
        self.bot.set_state(user_id, None)

    def admin_remove_fine_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        unpaid = self.db.get_unpaid_fines(target['user_id'])
        if not unpaid:
            self.bot.send_message(user_id, "Нет штрафов.")
            return
        for f in unpaid:
            self.db.pay_fine(f['id'])
        self.db.add_admin_log(user_id, "Снятие штрафа", target['user_id'])
        self.bot.send_message(user_id, f"Штрафы сняты у {text}.")
        self.bot.set_state(user_id, None)

    def admin_add_admin_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], role='admin')
        self.db.add_admin_log(user_id, "Назначение администратора", target['user_id'], text)
        self.bot.send_message(user_id, f"Пользователь {text} назначен администратором.")
        ADMIN_IDS.append(target['user_id'])
        self.bot.set_state(user_id, None)

    def admin_remove_admin_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        if target['user_id'] in ADMIN_IDS:
            ADMIN_IDS.remove(target['user_id'])
        self.db.update_user(target['user_id'], role='user')
        self.db.add_admin_log(user_id, "Снятие администратора", target['user_id'], text)
        self.bot.send_message(user_id, f"Пользователь {text} снят с должности.")
        self.bot.set_state(user_id, None)

    def admin_fine_issue_handler(self, message):
        user_id = message.from_user.id
        parts = message.text.strip().split()
        if len(parts) < 3:
            self.bot.send_message(user_id, "Использование: ID_пользователя сумма причина")
            return
        target = self.find_user(parts[0])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            amount = int(parts[1])
        except:
            self.bot.send_message(user_id, "Сумма должна быть числом.")
            return
        reason = " ".join(parts[2:])
        self.db.add_fine(target['user_id'], reason, amount, user_id)
        self.db.add_admin_log(user_id, "Выдача штрафа", target['user_id'], f"{reason} - {amount} Stars")
        self.bot.send_message(user_id, f"Штраф выдан.")
        self.bot.set_state(user_id, None)

    def admin_set_stars_handler(self, message):
        user_id = message.from_user.id
        parts = message.text.strip().split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: ID_пользователя количество")
            return
        target = self.find_user(parts[0])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            amount = int(parts[1])
        except:
            self.bot.send_message(user_id, "Сумма должна быть числом.")
            return
        self.db.update_user(target['user_id'], balance=amount)
        self.db.add_admin_log(user_id, "Установка Stars", target['user_id'], f"{amount} Stars")
        self.bot.send_message(user_id, f"Баланс установлен на {amount} Stars.")
        self.bot.set_state(user_id, None)

    def admin_give_premium_handler(self, message):
        user_id = message.from_user.id
        parts = message.text.strip().split()
        if len(parts) < 2:
            self.bot.send_message(user_id, "Использование: ID_пользователя дни")
            return
        target = self.find_user(parts[0])
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        try:
            days = int(parts[1])
        except:
            self.bot.send_message(user_id, "Количество дней должно быть числом.")
            return
        until = datetime.now() + timedelta(days=days)
        self.db.update_user(target['user_id'], status='premium', premium_until=until.isoformat())
        self.db.add_admin_log(user_id, "Выдача Premium", target['user_id'], f"{days} дней")
        self.bot.send_message(user_id, f"Premium выдан на {days} дней.")
        self.bot.set_state(user_id, None)

    def admin_remove_premium_handler(self, message):
        user_id = message.from_user.id
        text = message.text.strip()
        target = self.find_user(text)
        if not target:
            self.bot.send_message(user_id, "Пользователь не найден.")
            return
        self.db.update_user(target['user_id'], status='active', premium_until=None)
        self.db.add_admin_log(user_id, "Отзыв Premium", target['user_id'], text)
        self.bot.send_message(user_id, f"Premium отозван.")
        self.bot.set_state(user_id, None)

    # ==================== ЗАПУСК ====================

    def run(self):
        print("Бот запущен...")
        self.bot.infinity_polling()


if __name__ == "__main__":
    bot = BotApp(TOKEN)
    bot.run()