import telebot
from telebot import types
import sqlite3
import os
import logging
from datetime import datetime, timedelta
import time
import threading
from contextlib import contextmanager
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8801942768:AAGLzz_Xg_X6Gr8LHrN6RBxyKDiQH4O0HvE"
DB_NAME = "lovebot.db"
ADMIN_IDS = [0001]  # Список ID админов (замените на свои)
CHANNEL_ID = "@tavejr7"  # Замените на ваш канал

bot = telebot.TeleBot(TOKEN)

# --- ТОЛЬКО БАШКИРСКИЕ ГОРОДА ---
BASHKIR_CITIES = [
    "Уфа", "Агидель", "Баймак", "Белебей", "Белорецк", 
    "Бирск", "Благовещенск", "Давлеканово", "Дюртюли", 
    "Ишимбай", "Кумертау", "Межгорье", "Мелеуз", 
    "Нефтекамск", "Октябрьский", "Салават", "Сибай", 
    "Стерлитамак", "Туймазы", "Учалы", "Янаул"
]

# --- Работа с БД с использованием блокировок ---
db_lock = threading.Lock()

@contextmanager
def get_conn():
    """Получение соединения с БД с блокировкой"""
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def dict_from_row(row):
    """Преобразование sqlite3.Row в dict"""
    if row is None:
        return None
    return dict(row)

def init_db():
    """Инициализация базы данных"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей (расширенная)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    about TEXT,
                    photo_file_id TEXT,
                    is_registered INTEGER DEFAULT 0,
                    verified INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0,
                    admin_level INTEGER DEFAULT 0,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    balance INTEGER DEFAULT 0,
                    stars INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TIMESTAMP,
                    gender TEXT DEFAULT 'не указан',
                    looking_for_age_min INTEGER DEFAULT 14,
                    looking_for_age_max INTEGER DEFAULT 30,
                    looking_for_gender TEXT DEFAULT 'всех',
                    search_city TEXT,
                    tags TEXT,
                    is_chat_banned INTEGER DEFAULT 0,
                    is_like_banned INTEGER DEFAULT 0,
                    is_dislike_banned INTEGER DEFAULT 0,
                    is_draft_banned INTEGER DEFAULT 0,
                    is_search_banned INTEGER DEFAULT 0,
                    is_visible INTEGER DEFAULT 1
                )
            ''')
            
            # Таблица реакций
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER,
                    target_id INTEGER,
                    reaction TEXT CHECK(reaction IN ('like', 'dislike', 'draft')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, target_id)
                )
            ''')
            
            # Таблица чатов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1_id INTEGER,
                    user2_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                )
            ''')
            
            # Таблица сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    sender_id INTEGER,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES chats(id)
                )
            ''')
            
            # Таблица уведомлений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    from_user_id INTEGER,
                    type TEXT CHECK(type IN ('like', 'mutual_like', 'message')),
                    message TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица жалоб
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER,
                    reported_id INTEGER,
                    reason TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица штрафов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    admin_id INTEGER,
                    amount INTEGER,
                    reason TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP
                )
            ''')
            
            # Таблица транзакций (звезды)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    type TEXT CHECK(type IN ('purchase', 'fine', 'admin_gift', 'premium')),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица покупок премиума
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS premium_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    duration_days INTEGER,
                    amount_stars INTEGER,
                    amount_rub INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица логов администрации
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT,
                    target_id INTEGER,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица проверок на канал
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_checks (
                    user_id INTEGER PRIMARY KEY,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

init_db()

# Состояния пользователя
user_states = {}
temp_data = {}
states_lock = threading.Lock()

# --- Вспомогательные функции ---
def is_admin(tg_id):
    """Проверить, является ли пользователь админом"""
    if tg_id in ADMIN_IDS:
        return True
    user = get_user_by_tg_id(tg_id)
    return user and user.get('is_admin', 0) == 1

def get_admin_level(tg_id):
    """Получить уровень администратора"""
    if tg_id in ADMIN_IDS:
        return 3
    user = get_user_by_tg_id(tg_id)
    if user and user.get('is_admin', 0) == 1:
        return user.get('admin_level', 1)
    return 0

def safe_get_user(tg_id):
    """Безопасное получение пользователя"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            user = cursor.fetchone()
            if user:
                return dict_from_row(user)
            return None
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None

def get_user_by_tg_id(tg_id):
    return safe_get_user(tg_id)

def get_user_by_id(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            if user:
                return dict_from_row(user)
            return None
    except Exception as e:
        logger.error(f"Error getting user by id: {e}")
        return None

def get_user_id_by_tg(tg_id):
    user = get_user_by_tg_id(tg_id)
    return user['id'] if user else None

def update_last_active(tg_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE tg_id = ?", (tg_id,))
    except Exception as e:
        logger.error(f"Error updating last active: {e}")

def is_registered(tg_id):
    user = get_user_by_tg_id(tg_id)
    if user is None:
        return False
    return user.get('is_registered') == 1 and user.get('is_banned', 0) == 0

def safe_send_message(chat_id, text, **kwargs):
    try:
        if chat_id < 0:
            return None
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
        return None

def safe_send_photo(chat_id, photo, caption="", **kwargs):
    try:
        if chat_id < 0:
            return None
        return bot.send_photo(chat_id, photo=photo, caption=caption, **kwargs)
    except Exception as e:
        logger.error(f"Error sending photo to {chat_id}: {e}")
        return None

def add_notification(user_id, from_user_id, type, message=""):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notifications (user_id, from_user_id, type, message)
                VALUES (?, ?, ?, ?)
            ''', (user_id, from_user_id, type, message))
        return True
    except Exception as e:
        logger.error(f"Error adding notification: {e}")
        return False

def get_unread_notifications(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return []
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT n.*, u.name as from_name FROM notifications n
                JOIN users u ON n.from_user_id = u.id
                WHERE n.user_id = ? AND n.is_read = 0
                ORDER BY n.created_at DESC
            ''', (user_id,))
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return []

def mark_notifications_read(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE notifications SET is_read = 1 WHERE user_id = ?
            ''', (user_id,))
    except Exception as e:
        logger.error(f"Error marking notifications read: {e}")

def notify_user(tg_id, text, **kwargs):
    try:
        user = get_user_by_tg_id(tg_id)
        if not user:
            return False
        safe_send_message(tg_id, text, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error notifying user {tg_id}: {e}")
        return False

def add_stars(user_id, amount, description=""):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET stars = stars + ? WHERE id = ?', (amount, user_id))
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, 'admin_gift', ?)
            ''', (user_id, amount, description))
        return True
    except Exception as e:
        logger.error(f"Error adding stars: {e}")
        return False

def get_fines(tg_id, active_only=True):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return []
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute('''
                    SELECT * FROM fines WHERE user_id = ? AND status = 'active'
                    ORDER BY created_at DESC
                ''', (user_id,))
            else:
                cursor.execute('''
                    SELECT * FROM fines WHERE user_id = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error getting fines: {e}")
        return []

def is_user_fined(tg_id):
    return len(get_fines(tg_id)) > 0

def set_premium(user_id, days):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET 
                    is_premium = 1,
                    premium_until = datetime('now', '+' || ? || ' days')
                WHERE id = ?
            ''', (days, user_id))
        return True
    except Exception as e:
        logger.error(f"Error setting premium: {e}")
        return False

# --- Обработчики команд ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    tg_id = message.from_user.id
    
    if tg_id < 0:
        return
    
    # Если пользователь - бот, игнорируем
    try:
        if hasattr(message.from_user, 'is_bot') and message.from_user.is_bot:
            return
    except:
        pass
    
    # Проверяем, зарегистрирован ли пользователь
    if is_registered(tg_id):
        # Показываем меню
        show_main_menu(tg_id)
        return
    
    # Начинаем регистрацию
    with states_lock:
        temp_data[tg_id] = {}
        user_states[tg_id] = {'state': 'waiting_gender'}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_male = types.InlineKeyboardButton("👨 Мужской", callback_data="gender_male")
    btn_female = types.InlineKeyboardButton("👩 Женский", callback_data="gender_female")
    markup.add(btn_male, btn_female)
    
    safe_send_message(
        tg_id,
        "👋 Привет! Давай создадим твою анкету.\n\n"
        "Выбери свой пол:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('gender_'))
def process_gender(call):
    tg_id = call.from_user.id
    gender = call.data.split('_')[1]
    
    if gender == 'male':
        gender_text = 'мужской'
    else:
        gender_text = 'женский'
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['gender'] = gender_text
        user_states[tg_id] = {'state': 'waiting_name'}
    
    bot.answer_callback_query(call.id)
    safe_send_message(
        tg_id,
        "📝 Как тебя зовут? (от 2 до 50 символов)"
    )

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_name')
def process_name(message):
    tg_id = message.from_user.id
    name = message.text.strip()
    
    if len(name) < 2 or len(name) > 50:
        safe_send_message(tg_id, "❌ Имя должно быть от 2 до 50 символов. Попробуй ещё раз.")
        return
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['name'] = name
        user_states[tg_id] = {'state': 'waiting_age'}
    
    safe_send_message(tg_id, "📅 Сколько тебе лет? (от 14 до 100)")

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_age')
def process_age(message):
    tg_id = message.from_user.id
    
    try:
        age = int(message.text)
        if not (14 <= age <= 100):
            safe_send_message(tg_id, "❌ Возраст должен быть от 14 до 100 лет. Попробуй ещё раз.")
            return
    except ValueError:
        safe_send_message(tg_id, "❌ Введи число. Например: 25")
        return
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['age'] = age
        user_states[tg_id] = {'state': 'waiting_city'}
    
    cities_text = "🏙️ Доступные города Башкортостана:\n"
    cities_text += ", ".join(BASHKIR_CITIES)
    
    safe_send_message(
        tg_id,
        cities_text + "\n\n🌆 Напиши название своего города (только русские буквы, с большой буквы):"
    )

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_city')
def process_city(message):
    tg_id = message.from_user.id
    city = message.text.strip()
    
    if not re.match(r'^[А-Я][а-яё\- ]+$', city):
        safe_send_message(tg_id, "❌ Город должен быть написан на русском языке и начинаться с большой буквы. Например: Уфа")
        return
    
    if city not in BASHKIR_CITIES:
        cities_text = "❌ Город не найден. Доступны только города Башкортостана:\n\n"
        cities_text += ", ".join(BASHKIR_CITIES)
        safe_send_message(tg_id, cities_text)
        return
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['city'] = city
        user_states[tg_id] = {'state': 'waiting_tags'}
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    tags = ['Музыка', 'Спорт', 'Кино', 'Книги', 'Путешествия', 'Игры', 
            'Фотография', 'Рисование', 'Танцы', 'Готовка', 'Йога', 'Программирование']
    for tag in tags:
        markup.add(types.InlineKeyboardButton(tag, callback_data=f"tag_{tag}"))
    markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="tags_done"))
    
    safe_send_message(
        tg_id,
        "🏷️ Выбери свои интересы (можно несколько):",
        reply_markup=markup
    )

user_tags = {}

@bot.callback_query_handler(func=lambda call: call.data.startswith('tag_'))
def process_tag(call):
    tg_id = call.from_user.id
    tag = call.data.split('_', 1)[1]
    
    if tg_id not in user_tags:
        user_tags[tg_id] = []
    
    if tag in user_tags[tg_id]:
        user_tags[tg_id].remove(tag)
        action = "убрал"
    else:
        if len(user_tags[tg_id]) >= 10:
            bot.answer_callback_query(call.id, "❌ Можно выбрать не более 10 тегов")
            return
        user_tags[tg_id].append(tag)
        action = "добавил"
    
    bot.answer_callback_query(call.id, f"✅ {action} тег: {tag}")
    
    tags_text = "Выбрано: " + ", ".join(user_tags[tg_id]) if user_tags[tg_id] else "Пока ничего не выбрано"
    try:
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=f"🏷️ Выбери свои интересы (можно несколько):\n\n{tags_text}",
            reply_markup=call.message.reply_markup
        )
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "tags_done")
def tags_done(call):
    tg_id = call.from_user.id
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['tags'] = ','.join(user_tags.get(tg_id, []))
        user_states[tg_id] = {'state': 'waiting_about'}
    
    if tg_id in user_tags:
        del user_tags[tg_id]
    
    bot.answer_callback_query(call.id)
    safe_send_message(
        tg_id,
        "📝 Расскажи о себе в 1–2 предложениях:\n"
        "Чем занимаешься, что ищешь? (не более 500 символов)"
    )

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_about')
def process_about(message):
    tg_id = message.from_user.id
    about = message.text.strip()
    
    if len(about) > 500:
        safe_send_message(tg_id, "❌ Описание не должно превышать 500 символов. Попробуй короче.")
        return
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['about'] = about
        user_states[tg_id] = {'state': 'waiting_photo'}
    
    safe_send_message(
        tg_id,
        "📸 Пришли фото для анкеты\n"
        "(можно просто пропустить, нажав /skip)"
    )

@bot.message_handler(content_types=['photo'], 
                    func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def process_photo(message):
    tg_id = message.from_user.id
    photo_file_id = message.photo[-1].file_id
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['photo_file_id'] = photo_file_id
    
    finish_registration(tg_id)

@bot.message_handler(commands=['skip'], 
                    func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def skip_photo(message):
    tg_id = message.from_user.id
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['photo_file_id'] = None
    
    finish_registration(tg_id)

def finish_registration(tg_id):
    """Завершить регистрацию и сохранить данные в БД"""
    with states_lock:
        data = temp_data.get(tg_id, {})
    
    # Проверяем наличие всех обязательных данных
    required_fields = ['name', 'age', 'city', 'gender']
    for field in required_fields:
        if field not in data or not data[field]:
            with states_lock:
                if tg_id in temp_data:
                    del temp_data[tg_id]
                if tg_id in user_states:
                    del user_states[tg_id]
            safe_send_message(tg_id, "❌ Что-то пошло не так. Начни заново: /start")
            return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже пользователь
            cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
            existing = cursor.fetchone()
            
            if existing:
                # Обновляем существующего пользователя
                cursor.execute('''
                    UPDATE users SET 
                        name = ?, age = ?, city = ?, about = ?, photo_file_id = ?,
                        is_registered = 1, gender = ?, tags = ?, search_city = ?,
                        last_active = CURRENT_TIMESTAMP
                    WHERE tg_id = ?
                ''', (
                    data['name'], data['age'], data['city'], 
                    data.get('about', ''), data.get('photo_file_id'),
                    data['gender'], data.get('tags', ''), data['city'],
                    tg_id
                ))
            else:
                # Создаем нового пользователя
                cursor.execute('''
                    INSERT INTO users (
                        tg_id, name, age, city, about, photo_file_id, is_registered,
                        gender, tags, search_city
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ''', (
                    tg_id, data['name'], data['age'], data['city'], 
                    data.get('about', ''), data.get('photo_file_id'),
                    data['gender'], data.get('tags', ''), data['city']
                ))
            
            conn.commit()
        
        # Очищаем временные данные
        with states_lock:
            if tg_id in temp_data:
                del temp_data[tg_id]
            if tg_id in user_states:
                del user_states[tg_id]
        
        # Показываем профиль
        safe_send_message(tg_id, "✅ Профиль создан! Теперь можно искать анкеты.")
        show_profile(tg_id)
        
    except sqlite3.IntegrityError as e:
        logger.error(f"IntegrityError in finish_registration: {e}")
        safe_send_message(tg_id, "❌ Профиль уже существует. Используй /menu")
    except Exception as e:
        logger.error(f"Error in finish_registration: {e}")
        safe_send_message(tg_id, f"❌ Произошла ошибка при сохранении профиля. Попробуй позже.\nОшибка: {str(e)}")

# --- Показ анкет ---
def send_next_profile(tg_id):
    """Отправить следующую анкету пользователю"""
    user_id = get_user_id_by_tg(tg_id)
    
    if not user_id:
        safe_send_message(tg_id, "❌ Ты не зарегистрирован. Используй /start")
        return
    
    if is_user_fined(tg_id):
        show_fine_notification(tg_id)
        return
    
    user = get_user_by_tg_id(tg_id)
    if user and user.get('is_search_banned', 0) == 1:
        safe_send_message(tg_id, "❌ Поиск анкет заблокирован до оплаты штрафа.")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            user_settings = get_user_by_id(user_id)
            if not user_settings:
                safe_send_message(tg_id, "❌ Ошибка загрузки профиля")
                return
                
            looking_age_min = user_settings.get('looking_for_age_min', 14)
            looking_age_max = user_settings.get('looking_for_age_max', 30)
            looking_gender = user_settings.get('looking_for_gender', 'всех')
            search_city = user_settings.get('search_city', user_settings.get('city'))
            
            query = '''
                SELECT u.* FROM users u
                LEFT JOIN reactions r ON u.id = r.target_id AND r.user_id = ?
                WHERE u.id != ? 
                AND u.is_registered = 1
                AND u.is_banned = 0
                AND u.is_visible = 1
                AND u.age BETWEEN ? AND ?
            '''
            params = [user_id, user_id, looking_age_min, looking_age_max]
            
            if looking_gender != 'всех':
                query += " AND u.gender = ?"
                params.append(looking_gender)
            
            if search_city:
                query += " AND u.city = ?"
                params.append(search_city)
            
            query += " AND r.reaction IS NULL ORDER BY RANDOM() LIMIT 1"
            
            cursor.execute(query, params)
            target = cursor.fetchone()
            target = dict_from_row(target) if target else None
        
        if not target:
            safe_send_message(
                tg_id,
                "😔 Анкеты закончились.\n"
                "Попробуй изменить настройки поиска или зайди позже.\n"
                "/menu - главное меню"
            )
            return
        
        tags_list = target.get('tags', '').split(',') if target.get('tags') else []
        tags_text = "🏷️ " + ", ".join(tags_list) if tags_list else ""
        
        text = (
            f"🆔 ID: #{target['id']:05d}\n"
            f"👤 Имя: {target['name']}\n"
            f"🎂 Возраст: {target['age']} лет\n"
            f"🏙️ Город: {target['city']}\n"
            f"{tags_text}\n"
            f"📝 О себе: {target.get('about') or 'Не указано'}"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        btn_like = types.InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{target['id']}")
        btn_dislike = types.InlineKeyboardButton("👎 Дизлайк", callback_data=f"dislike_{target['id']}")
        btn_draft = types.InlineKeyboardButton("📝 В черновики", callback_data=f"draft_{target['id']}")
        btn_report = types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_{target['id']}")
        btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
        markup.add(btn_like, btn_dislike, btn_draft)
        markup.add(btn_report, btn_menu)
        
        if target.get('photo_file_id'):
            safe_send_photo(tg_id, photo=target['photo_file_id'], caption=text, reply_markup=markup)
        else:
            safe_send_message(tg_id, text, reply_markup=markup)
            
    except Exception as e:
        logger.error(f"Error sending profile: {e}")
        safe_send_message(tg_id, "❌ Ошибка при отправке анкеты. Попробуйте позже.")

# --- Обработка callback запросов ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    tg_id = call.from_user.id
    
    if tg_id < 0:
        return
    
    if not call.message:
        return
    
    # Проверка регистрации для всех действий кроме menu
    if not is_registered(tg_id) and call.data not in ['menu', 'check_subscription'] and not call.data.startswith('gender_') and not call.data.startswith('tag_') and call.data != 'tags_done':
        try:
            bot.answer_callback_query(call.id, "❌ Сначала зарегистрируйся: /start")
        except:
            pass
        return
    
    # Обработка меню
    if call.data == "menu":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_main_menu(tg_id)
        return
    
    if call.data == "search":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        send_next_profile(tg_id)
        return
    
    if call.data == "profile":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_profile(tg_id)
        return
    
    if call.data == "edit":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        edit_profile(tg_id)
        return
    
    if call.data == "matches":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_matches(tg_id)
        return
    
    if call.data == "chats":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_chats(tg_id)
        return
    
    if call.data == "notifications":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_notifications(tg_id)
        return
    
    if call.data == "donate":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_donate_menu(tg_id)
        return
    
    if call.data == "admin":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        cmd_admin(call.message)
        return
    
    # Обработка жалобы
    if call.data.startswith('report_'):
        try:
            target_id = int(call.data.split('_')[1])
            bot.answer_callback_query(call.id)
            user_states[tg_id] = {
                'state': 'report_reason',
                'target_id': target_id
            }
            safe_send_message(
                tg_id,
                "⚠️ Напишите причину жалобы (кратко, не менее 3 символов):"
            )
        except:
            pass
        return
    
    # Обработка реакций
    try:
        action, target_id_str = call.data.split('_', 1)
        target_id = int(target_id_str)
    except (ValueError, IndexError):
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка в данных")
        except:
            pass
        return
    
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка пользователя")
        except:
            pass
        return
    
    if user_id == target_id:
        try:
            bot.answer_callback_query(call.id, "❌ Нельзя реагировать на свою анкету!")
        except:
            pass
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reactions (user_id, target_id, reaction) VALUES (?, ?, ?)",
                (user_id, target_id, action)
            )
        
        try:
            bot.answer_callback_query(call.id, "✅ Реакция учтена!")
        except:
            pass
    except Exception as e:
        logger.error(f"Error saving reaction: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка при сохранении")
        except:
            pass
        return
    
    if action == 'like':
        target_user = get_user_by_id(target_id)
        if target_user:
            user_name = get_user_by_id(user_id)['name']
            add_notification(target_id, user_id, 'like', f"{user_name} поставил(а) тебе лайк!")
            notify_user(
                target_user['tg_id'],
                f"❤️ {user_name} поставил(а) тебе лайк!\n"
                f"Посмотри его/ее анкету: /menu"
            )
    
    send_next_profile(tg_id)

# --- Штрафы ---
def show_fine_notification(tg_id):
    user = get_user_by_tg_id(tg_id)
    if not user:
        return
        
    fines = get_fines(tg_id)
    total_fine = sum(fine['amount'] for fine in fines)
    
    if not fines:
        return
    
    text = "🚨 ВАС ОШТРАФОВАЛИ!\n\n"
    for fine in fines:
        if fine.get('status') == 'active':
            text += f"Нарушение: {fine.get('reason', 'Неизвестно')}\n"
            text += f"Сумма штрафа: {fine.get('amount', 0)} ⭐ Stars\n"
            text += f"Дата выдачи: {fine.get('created_at', '')}\n\n"
    
    text += "⚡ Последствия:\n"
    text += "❌ Заблокированы ЛАЙКИ (до оплаты)\n"
    text += "❌ Заблокированы ДИЗЛАЙКИ (до оплаты)\n"
    text += "❌ Заблокирован АНОНИМНЫЙ ЧАТ (до оплаты)\n"
    text += "❌ Заблокированы ЧЕРНОВИКИ (до оплаты)\n"
    text += "❌ Заблокирован ПОИСК АНКЕТ (до оплаты)\n\n"
    text += f"Ваш баланс: {user.get('stars', 0)} ⭐ Stars\n"
    text += f"Не хватает: {max(0, total_fine - user.get('stars', 0))} ⭐ Stars"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_pay = types.InlineKeyboardButton("💳 Оплатить штраф", callback_data=f"fine_pay_{total_fine}")
    btn_topup = types.InlineKeyboardButton("💰 Пополнить баланс", callback_data="donate")
    btn_appeal = types.InlineKeyboardButton("❌ Обжаловать", callback_data="fine_appeal")
    markup.add(btn_pay, btn_topup, btn_appeal)
    
    safe_send_message(tg_id, text, reply_markup=markup)

# --- Донат меню ---
def show_donate_menu(tg_id):
    user = get_user_by_tg_id(tg_id)
    if not user:
        safe_send_message(tg_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    premium_plans = [
        {"id": 1, "name": "👑 1 день", "stars": 9, "rub": 9},
        {"id": 2, "name": "👑 1 неделя", "stars": 49, "rub": 49},
        {"id": 4, "name": "👑 3 месяца", "stars": 199, "rub": 199},
        {"id": 5, "name": "👑 6 месяцев", "stars": 349, "rub": 349},
        {"id": 6, "name": "👑 12 месяцев", "stars": 599, "rub": 599},
    ]
    
    text = "💎 Донат меню\n\n"
    text += f"💰 Баланс: {user.get('stars', 0)} ⭐ Stars\n"
    text += f"👑 Премиум: {'Да' if user.get('is_premium') else 'Нет'}\n\n"
    text += "Выберите тариф:\n\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for plan in premium_plans:
        btn_text = f"{plan['name']} - {plan['stars']}⭐ / {plan['rub']}₽"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"donate_{plan['id']}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
    
    safe_send_message(tg_id, text, reply_markup=markup)

def handle_donate_purchase(call):
    tg_id = call.from_user.id
    plan_id = int(call.data.split('_')[1])
    
    premium_plans = {
        1: {"name": "1 день", "stars": 9, "days": 1},
        2: {"name": "1 неделя", "stars": 49, "days": 7},
        4: {"name": "3 месяца", "stars": 199, "days": 90},
        5: {"name": "6 месяцев", "stars": 349, "days": 180},
        6: {"name": "12 месяцев", "stars": 599, "days": 365},
    }
    
    plan = premium_plans.get(plan_id)
    if not plan:
        bot.answer_callback_query(call.id, "❌ Тариф не найден")
        return
    
    user = get_user_by_tg_id(tg_id)
    if not user:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден")
        return
    
    if user.get('stars', 0) < plan['stars']:
        bot.answer_callback_query(call.id, f"❌ Недостаточно звезд. Нужно: {plan['stars']}")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET stars = stars - ? WHERE id = ?', (plan['stars'], user['id']))
            
            if user.get('is_premium'):
                cursor.execute('''
                    UPDATE users SET premium_until = datetime(premium_until, '+' || ? || ' days')
                    WHERE id = ?
                ''', (plan['days'], user['id']))
            else:
                cursor.execute('''
                    UPDATE users SET 
                        is_premium = 1,
                        premium_until = datetime('now', '+' || ? || ' days')
                    WHERE id = ?
                ''', (plan['days'], user['id']))
        
        bot.answer_callback_query(call.id, f"✅ Премиум {plan['name']} активирован!")
        safe_send_message(tg_id, f"🎉 Поздравляем! Премиум на {plan['name']} активирован!")
        show_donate_menu(tg_id)
        
    except Exception as e:
        logger.error(f"Error purchasing premium: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка при покупке")

# --- Админ-панель ---
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    tg_id = message.from_user.id
    
    if not is_admin(tg_id):
        safe_send_message(tg_id, "❌ У вас нет прав администратора.")
        return
    
    level = get_admin_level(tg_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_stats = types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    btn_users = types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
    btn_reports = types.InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_reports")
    btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
    markup.add(btn_stats, btn_users, btn_reports, btn_menu)
    
    safe_send_message(
        tg_id,
        f"🔐 Админ-панель (Уровень {level})",
        reply_markup=markup
    )

# --- Основные функции ---
@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    tg_id = message.from_user.id
    show_profile(tg_id)

def show_profile(tg_id, chat_id=None):
    """Показать профиль пользователя"""
    if chat_id is None:
        chat_id = tg_id
        
    user = get_user_by_tg_id(tg_id)
    
    if not user:
        safe_send_message(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    tags_list = user.get('tags', '').split(',') if user.get('tags') else []
    tags_text = ", ".join(tags_list) if tags_list else "Не указаны"
    
    text = (
        f"👤 Твой профиль\n\n"
        f"🆔 ID: #{user['id']:05d}\n"
        f"👤 Имя: {user['name']}\n"
        f"🎂 Возраст: {user['age']} лет\n"
        f"🏙️ Город: {user['city']}\n"
        f"⚥ Пол: {user.get('gender') or 'Не указан'}\n"
        f"🏷️ Интересы: {tags_text}\n"
        f"📝 О себе: {user.get('about') or 'Не указано'}\n\n"
        f"💰 Баланс: {user.get('stars', 0)} ⭐ Stars\n"
        f"👑 Премиум: {'Да' if user.get('is_premium') else 'Нет'}\n"
        f"✅ Верификация: {'Подтвержден' if user.get('verified') else 'Не подтвержден'}"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_edit = types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit")
    btn_donate = types.InlineKeyboardButton("💎 Донат", callback_data="donate")
    btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
    markup.add(btn_edit, btn_donate, btn_menu)
    
    if user.get('photo_file_id'):
        safe_send_photo(chat_id, photo=user['photo_file_id'], caption=text, reply_markup=markup)
    else:
        safe_send_message(chat_id, text, reply_markup=markup)

def show_main_menu(tg_id):
    """Показать главное меню"""
    if not is_registered(tg_id):
        safe_send_message(tg_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    if is_user_fined(tg_id):
        show_fine_notification(tg_id)
        return
    
    notifications = get_unread_notifications(tg_id)
    notif_count = len(notifications) if notifications else 0
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_search = types.InlineKeyboardButton("🔍 Искать анкеты", callback_data="search")
    btn_profile = types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile")
    btn_edit = types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit")
    btn_matches = types.InlineKeyboardButton("💕 Мои лайки", callback_data="matches")
    btn_chats = types.InlineKeyboardButton("💬 Мои чаты", callback_data="chats")
    btn_notif = types.InlineKeyboardButton(f"📬 Уведомления ({notif_count})", callback_data="notifications")
    btn_donate = types.InlineKeyboardButton("💎 Донат", callback_data="donate")
    markup.add(btn_search, btn_profile, btn_edit, btn_matches, btn_chats, btn_notif, btn_donate)
    
    if is_admin(tg_id):
        btn_admin = types.InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")
        markup.add(btn_admin)
    
    text = "📋 Главное меню:"
    if notif_count > 0:
        text += f"\n\n🔔 У тебя {notif_count} новых уведомлений!"
    
    safe_send_message(tg_id, text, reply_markup=markup)

def edit_profile(tg_id, chat_id=None):
    if chat_id is None:
        chat_id = tg_id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_name = types.InlineKeyboardButton("✏️ Имя", callback_data="edit_name")
    btn_age = types.InlineKeyboardButton("✏️ Возраст", callback_data="edit_age")
    btn_city = types.InlineKeyboardButton("✏️ Город", callback_data="edit_city")
    btn_about = types.InlineKeyboardButton("✏️ О себе", callback_data="edit_about")
    btn_photo = types.InlineKeyboardButton("📸 Фото", callback_data="edit_photo")
    btn_back = types.InlineKeyboardButton("🔙 Назад", callback_data="menu")
    markup.add(btn_name, btn_age, btn_city, btn_about, btn_photo, btn_back)
    
    safe_send_message(chat_id, "📝 Что хочешь изменить?", reply_markup=markup)

def show_matches(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        safe_send_message(tg_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT u.* FROM users u
                JOIN reactions r ON u.id = r.user_id
                WHERE r.target_id = ? AND r.reaction = 'like'
            ''', (user_id,))
            rows = cursor.fetchall()
            matches = [dict_from_row(row) for row in rows] if rows else []
        
        if not matches:
            safe_send_message(tg_id, "😔 Пока нет лайков от других пользователей.")
            return
        
        text = "💕 Люди, которым ты понравился:\n\n"
        for match in matches:
            text += f"👤 {match['name']}, {match['age']} лет - ID: #{match['id']:05d}\n"
        
        safe_send_message(tg_id, text)
    except Exception as e:
        logger.error(f"Error showing matches: {e}")
        safe_send_message(tg_id, "❌ Ошибка при показе лайков")

def show_chats(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        safe_send_message(tg_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM chats 
                WHERE user1_id = ? OR user2_id = ?
            ''', (user_id, user_id))
            rows = cursor.fetchall()
            chats = [dict_from_row(row) for row in rows] if rows else []
        
        if not chats:
            safe_send_message(tg_id, "💭 У тебя пока нет чатов. Найди взаимный лайк!")
            return
        
        text = "💬 Твои чаты:\n\n"
        for chat in chats:
            other_id = chat['user2_id'] if chat['user1_id'] == user_id else chat['user1_id']
            other_user = get_user_by_id(other_id)
            if other_user:
                text += f"👤 {other_user['name']} - ID: #{other_id:05d}\n"
                text += f"📱 /chat_{other_id}\n\n"
        
        safe_send_message(tg_id, text)
    except Exception as e:
        logger.error(f"Error showing chats: {e}")
        safe_send_message(tg_id, "❌ Ошибка при показе чатов")

def show_notifications(tg_id):
    notifications = get_unread_notifications(tg_id)
    
    if not notifications:
        safe_send_message(tg_id, "📬 У тебя нет новых уведомлений.")
        mark_notifications_read(tg_id)
        return
    
    text = "📬 Твои уведомления:\n\n"
    for n in notifications:
        if n.get('type') == 'like':
            text += f"❤️ {n.get('from_name')} поставил(а) тебе лайк!\n"
        elif n.get('type') == 'mutual_like':
            text += f"💕 Взаимный лайк с {n.get('from_name')}!\n"
        elif n.get('type') == 'message':
            text += f"💬 {n.get('from_name')}: {n.get('message')}\n"
        text += f"⏰ {n.get('created_at')}\n\n"
    
    mark_notifications_read(tg_id)
    safe_send_message(tg_id, text)

# --- Запуск бота ---
if __name__ == '__main__':
    logger.info("Бот запущен...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)
