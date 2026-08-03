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
import os

# ============================
# 1. КОНФИГУРАЦИЯ
# ============================
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_IDS = []
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@RussianDatingChannel")
MASTER_ADMIN_ID = int(os.environ.get("MASTER_ADMIN_ID", "0"))

BASHKIR_CITIES = [
    'Уфа', 'Агидель', 'Баймак', 'Белебей', 'Белорецк', 'Бирск',
    'Благовещенск', 'Давлеканово', 'Дюртюли', 'Ишимбай', 'Кумертау',
    'Межгорье', 'Мелеуз', 'Нефтекамск', 'Октябрьский', 'Салават',
    'Сибай', 'Стерлитамак', 'Туймазы', 'Учалы', 'Янаул'
]
RUSSIAN_CITIES_PATTERN = r'^[А-ЯЁ][а-яё]+(?:[- ][А-ЯЁ][а-яё]+)?$'

# ============================
# 2. БАЗА ДАННЫХ
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
                admin_level INTEGER DEFAULT 1,
                visible BOOLEAN DEFAULT 1,
                category TEXT,
                user_id_str TEXT UNIQUE,
                language TEXT DEFAULT 'ru',
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
            'welcome_text': 'Ой, хәлдәр нисек? 👀 Попал куда надо! Здесь знакомятся по-настоящему. Подпишись на ТГ-канал и вперед!',
            'rules': 'Правила общения: Без спама, без оскорблений.',
            'min_age': '14',
            'max_age': '100'
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

    def add_fine(self, user_id: int, violation: str, amount: int, admin_id: int = None) -> int:
        now = datetime.now().isoformat()
        cur, conn = self._execute("""
            INSERT INTO fines (user_id, violation, amount, issued_date, admin_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, violation, amount, now, admin_id))
        fine_id = cur.lastrowid
        conn.close()
        self.update_user(user_id, visible=0)
        return fine_id

    def get_total_unpaid_fine_amount(self, user_id: int) -> int:
        rows = self._fetchall("SELECT SUM(amount) as total FROM fines WHERE user_id = ? AND paid = 0", (user_id,))
        return rows[0]['total'] if rows and rows[0]['total'] else 0

    def pay_fine(self, user_id: int):
        now = datetime.now().isoformat()
        self._execute_no_fetch("UPDATE fines SET paid = 1, paid_date = ? WHERE user_id = ? AND paid = 0", (now, user_id))
        self.update_user(user_id, visible=1)

# ============================
# 3. FSM СОСТОЯНИЯ
# ============================
class UserStates(StatesGroup):
    reg_language = State()
    reg_gender = State()
    reg_search_gender = State()
    reg_name = State()
    reg_age = State()
    reg_city = State()
    reg_about = State()
    reg_photo = State()
    reg_confirm = State()
    anon_chat = State()
    anon_waiting = State()

# ============================
# 4. БОТ ЛОГИКА
# ============================
class BotApp:
    def __init__(self, token):
        self.db = Database()
        self.bot = telebot.TeleBot(token, state_storage=StateMemoryStorage())
        self.register_handlers()

    def check_user_access(self, user_id: int) -> bool:
        user = self.db.get_user(user_id)
        if not user:
            return False
        if user.get('status') == 'blocked':
            self.bot.send_message(user_id, "❌ Ваш аккаунт заблокирован администратором.")
            return False
        unpaid = self.db.get_total_unpaid_fine_amount(user_id)
        if unpaid > 0:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(f"💳 Оплатить штраф ({unpaid} Stars)", callback_data="pay_fine"))
            self.bot.send_message(user_id, f"⚠️ Доступ ограничен! У вас есть неоплаченный штраф на сумму {unpaid} Stars.", reply_markup=markup)
            return False
        return True

    def register_handlers(self):
        self.bot.message_handler(commands=['start'])(self.cmd_start)
        self.bot.message_handler(state=UserStates.reg_language)(self.reg_language_handler)
        self.bot.message_handler(state=UserStates.reg_gender)(self.reg_gender_handler)
        self.bot.message_handler(state=UserStates.reg_search_gender)(self.reg_search_gender_handler)
        self.bot.message_handler(state=UserStates.reg_name)(self.reg_name_handler)
        self.bot.message_handler(state=UserStates.reg_age)(self.reg_age_handler)
        self.bot.message_handler(state=UserStates.reg_city)(self.reg_city_handler)
        self.bot.message_handler(state=UserStates.reg_about)(self.reg_about_handler)
        self.bot.message_handler(content_types=['photo'], state=UserStates.reg_photo)(self.reg_photo_handler)
        self.bot.callback_query_handler(func=lambda call: True)(self.handle_callback)

    def cmd_start(self, message):
        user_id = message.from_user.id
        user = self.db.get_user(user_id)
        if not user:
            self.db.create_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
            user = self.db.get_user(user_id)

        if not self.check_user_access(user_id):
            return

        if not user['registered']:
            self.bot.set_state(user_id, UserStates.reg_language)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
                types.InlineKeyboardButton("🇧🇦 Башҡортса", callback_data="lang_ba")
            )
            self.bot.send_message(user_id, "🌐 Выберите язык интерфейса:", reply_markup=markup)
        else:
            self.bot.send_message(user_id, f"👋 С возвращением, {user['name']}! Используйте меню для поиска анкет.")

    def reg_language_handler(self, message):
        pass # Обрабатывается через callback

    def reg_gender_handler(self, message):
        pass # Обрабатывается через callback

    def reg_search_gender_handler(self, message):
        pass # Обрабатывается через callback

    def reg_name_handler(self, message):
        user_id = message.from_user.id
        name = message.text.strip()
        if len(name) < 2 or len(name) > 30:
            self.bot.send_message(user_id, "⚠️ Имя должно содержать от 2 до 30 символов.")
            return
        self.db.update_user(user_id, name=name)
        self.bot.set_state(user_id, UserStates.reg_age)
        self.bot.send_message(user_id, "🎂 Укажите ваш возраст (от 14 до 100):")

    def reg_age_handler(self, message):
        user_id = message.from_user.id
        try:
            age = int(message.text.strip())
            if not (14 <= age <= 100):
                self.bot.send_message(user_id, "⚠️ Возраст должен быть в диапазоне от 14 до 100 лет.")
                return
            category = "14-17" if age < 18 else "18-100"
            self.db.update_user(user_id, age=age, category=category)
            self.bot.set_state(user_id, UserStates.reg_city)
            self.bot.send_message(user_id, "🏙️ Напишите ваш город (с большой буквы, например: Уфа или Москва):")
        except ValueError:
            self.bot.send_message(user_id, "⚠️ Пожалуйста, введите возраст числом.")

    def reg_city_handler(self, message):
        user_id = message.from_user.id
        city = message.text.strip()
        if not city[0].isupper():
            self.bot.send_message(user_id, "⚠️ Введите название города с заглавной буквы (например: Уфа, Стерлитамак).")
            return
        self.db.update_user(user_id, city=city)
        self.bot.set_state(user_id, UserStates.reg_about)
        self.bot.send_message(user_id, "📝 Расскажите немного о себе (до 300 символов):")

    def reg_about_handler(self, message):
        user_id = message.from_user.id
        about = message.text.strip()
        if len(about) > 300:
            self.bot.send_message(user_id, "⚠️ Описание слишком длинное. Максимум 300 символов.")
            return
        self.db.update_user(user_id, about=about)
        self.bot.set_state(user_id, UserStates.reg_photo)
        self.bot.send_message(user_id, "📸 Загрузите ваше фото для анкеты:")

    def reg_photo_handler(self, message):
        user_id = message.from_user.id
        photo_id = message.photo[-1].file_id
        self.db.update_user(user_id, photo_file_id=photo_id, registered=1, visible=1)
        self.bot.delete_state(user_id)
        self.bot.send_message(user_id, "🎉 Регистрация успешно завершена! Ваша анкета опубликована.")

    def handle_callback(self, call):
        user_id = call.from_user.id
        data = call.data

        if data.startswith("lang_"):
            lang = data.split("_")[1]
            self.db.update_user(user_id, language=lang)
            self.bot.set_state(user_id, UserStates.reg_gender)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("👨 Мужской", callback_data="gender_male"),
                types.InlineKeyboardButton("👩 Женский", callback_data="gender_female")
            )
            self.bot.edit_message_text("Укажите ваш пол:", user_id, call.message.message_id, reply_markup=markup)

        elif data.startswith("gender_"):
            gender = data.split("_")[1]
            self.db.update_user(user_id, gender=gender)
            self.bot.set_state(user_id, UserStates.reg_search_gender)
            markup = types.InlineKeyboardMarkup(row_width=3)
            markup.add(
                types.InlineKeyboardButton("👨 Парней", callback_data="sgender_male"),
                types.InlineKeyboardButton("👩 Девушек", callback_data="sgender_female"),
                types.InlineKeyboardButton("🌈 Всех", callback_data="sgender_all")
            )
            self.bot.edit_message_text("Кого вы ищете?", user_id, call.message.message_id, reply_markup=markup)

        elif data.startswith("sgender_"):
            sgender = data.split("_")[1]
            self.db.update_user(user_id, search_gender=sgender)
            self.bot.set_state(user_id, UserStates.reg_name)
            self.bot.send_message(user_id, "👤 Введите ваше имя:")

        elif data == "pay_fine":
            self.db.pay_fine(user_id)
            self.bot.answer_callback_query(call.id, "✅ Штраф успешно оплачен! Ограничения сняты.")
            self.bot.send_message(user_id, "Вы снова можете пользоваться ботом. Введите /start")

if __name__ == "__main__":
    app = BotApp(TOKEN)
    print("Бот успешно запущен...")
    app.bot.infinity_polling()