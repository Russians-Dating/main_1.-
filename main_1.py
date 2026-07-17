import telebot
from telebot import types
import sqlite3
import os
import logging
from datetime import datetime, timedelta
import time
import threading
from contextlib import contextmanager

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8784413364:AAFWU5jqnRW4hBDONzcDDb_s9B4NzvzoxD4"
DB_NAME = "lovebot.db"
ADMIN_IDS = [00001]  # Список ID админов (замените на свои)

bot = telebot.TeleBot(TOKEN)

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

def init_db():
    """Инициализация базы данных"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
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
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица лайков/дизлайков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER,
                    target_id INTEGER,
                    reaction TEXT CHECK(reaction IN ('like', 'dislike', 'draft')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, target_id)
                )
            ''')
            
            # Таблица для чатов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1_id INTEGER,
                    user2_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                )
            ''')
            
            # Таблица для сообщений
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
            
            # Таблица для уведомлений
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
            
            # Таблица для жалоб
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

def safe_get_user(tg_id):
    """Безопасное получение пользователя"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
                user = cursor.fetchone()
                return user
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                logger.error(f"Error getting user: {e}")
                return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    return None

def get_user_by_tg_id(tg_id):
    return safe_get_user(tg_id)

def get_user_by_id(user_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                return user
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting user by id: {e}")
            return None
    return None

def get_user_id_by_tg(tg_id):
    user = get_user_by_tg_id(tg_id)
    return user['id'] if user else None

def update_last_active(tg_id):
    """Обновить время последней активности"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE tg_id = ?", (tg_id,))
                return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                logger.error(f"Error updating last active: {e}")
                return
        except Exception as e:
            logger.error(f"Error updating last active: {e}")
            return

def is_registered(tg_id):
    user = get_user_by_tg_id(tg_id)
    return user is not None and user['is_registered'] == 1 and user.get('is_banned', 0) == 0

def get_reaction(user_id, target_id):
    """Получить реакцию пользователя на анкету"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT reaction FROM reactions WHERE user_id = ? AND target_id = ?", 
                              (user_id, target_id))
                reaction = cursor.fetchone()
                return reaction['reaction'] if reaction else None
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                logger.error(f"Error getting reaction: {e}")
                return None
        except Exception as e:
            logger.error(f"Error getting reaction: {e}")
            return None
    return None

def safe_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения"""
    try:
        if chat_id < 0:
            return None
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
        return None

def safe_send_photo(chat_id, photo, caption="", **kwargs):
    """Безопасная отправка фото"""
    try:
        if chat_id < 0:
            return None
        return bot.send_photo(chat_id, photo=photo, caption=caption, **kwargs)
    except Exception as e:
        logger.error(f"Error sending photo to {chat_id}: {e}")
        return None

def add_notification(user_id, from_user_id, type, message=""):
    """Добавить уведомление пользователю"""
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
    """Получить непрочитанные уведомления"""
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
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return []

def mark_notifications_read(tg_id):
    """Отметить все уведомления как прочитанные"""
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
    """Отправить уведомление пользователю"""
    try:
        user = get_user_by_tg_id(tg_id)
        if not user:
            logger.warning(f"User {tg_id} not found for notification")
            return False
        
        safe_send_message(tg_id, text, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error notifying user {tg_id}: {e}")
        return False

def get_stats():
    """Получить статистику бота"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_registered = 1")
            total_users = cursor.fetchone()['count']
            
            cursor.execute('''
                SELECT COUNT(*) as count FROM users 
                WHERE is_registered = 1 AND last_active > datetime('now', '-7 days')
            ''')
            active_users = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM reactions WHERE reaction = 'like'")
            total_likes = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM chats")
            total_chats = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM messages")
            total_messages = cursor.fetchone()['count']
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'total_likes': total_likes,
                'total_chats': total_chats,
                'total_messages': total_messages
            }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return None

def get_reports():
    """Получить все жалобы"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, 
                       u1.name as reporter_name, 
                       u2.name as reported_name 
                FROM reports r
                JOIN users u1 ON r.reporter_id = u1.id
                JOIN users u2 ON r.reported_id = u2.id
                WHERE r.status = 'pending'
                ORDER BY r.created_at DESC
            ''')
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting reports: {e}")
        return []

def get_user_list(limit=50, offset=0):
    """Получить список пользователей"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE is_registered = 1
                ORDER BY registration_date DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting user list: {e}")
        return []

def ban_user(user_id):
    """Забанить пользователя"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

def unban_user(user_id):
    """Разбанить пользователя"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        return False

def make_admin(user_id):
    """Сделать пользователя админом"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error making admin: {e}")
        return False

def remove_admin(user_id):
    """Убрать права админа"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        return False

def add_report(reporter_id, reported_id, reason):
    """Добавить жалобу"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO reports (reporter_id, reported_id, reason)
                VALUES (?, ?, ?)
            ''', (reporter_id, reported_id, reason))
        return True
    except Exception as e:
        logger.error(f"Error adding report: {e}")
        return False

def resolve_report(report_id):
    """Закрыть жалобу"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = ?", (report_id,))
    except Exception as e:
        logger.error(f"Error resolving report: {e}")

# --- Обработчики команд ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    tg_id = message.from_user.id
    
    if tg_id < 0:
        return
    
    try:
        update_last_active(tg_id)
    except:
        pass
    
    if is_registered(tg_id):
        notifications = get_unread_notifications(tg_id)
        if notifications:
            notif_text = "📬 У тебя есть новые уведомления:\n\n"
            for n in notifications:
                if n['type'] == 'like':
                    notif_text += f"❤️ {n['from_name']} поставил(а) тебе лайк!\n"
                elif n['type'] == 'mutual_like':
                    notif_text += f"💕 Взаимный лайк с {n['from_name']}!\n"
                elif n['type'] == 'message':
                    notif_text += f"💬 Новое сообщение от {n['from_name']}: {n['message']}\n"
            safe_send_message(tg_id, notif_text)
            mark_notifications_read(tg_id)
        
        show_main_menu(message.chat.id, tg_id)
        return
    
    with states_lock:
        temp_data[tg_id] = {}
        user_states[tg_id] = {'state': 'waiting_name'}
    
    safe_send_message(
        tg_id, 
        "👋 Привет! Я бот для знакомств.\n\n"
        "Давай создадим твою анкету!\n"
        "Как тебя зовут?"
    )

@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    tg_id = message.from_user.id
    if tg_id < 0:
        return
    show_main_menu(message.chat.id, tg_id)

def show_main_menu(chat_id, tg_id):
    """Показать главное меню"""
    if not is_registered(tg_id):
        safe_send_message(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    notifications = get_unread_notifications(tg_id)
    notif_count = len(notifications)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_search = types.InlineKeyboardButton("🔍 Искать анкеты", callback_data="search")
    btn_profile = types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile")
    btn_edit = types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit")
    btn_matches = types.InlineKeyboardButton("💕 Мои лайки", callback_data="matches")
    btn_chats = types.InlineKeyboardButton("💬 Мои чаты", callback_data="chats")
    btn_notif = types.InlineKeyboardButton(f"📬 Уведомления ({notif_count})", callback_data="notifications")
    markup.add(btn_search, btn_profile, btn_edit, btn_matches, btn_chats, btn_notif)
    
    # Кнопка админки для админов
    if is_admin(tg_id):
        btn_admin = types.InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")
        markup.add(btn_admin)
    
    text = "📋 Главное меню:"
    if notif_count > 0:
        text += f"\n\n🔔 У тебя {notif_count} новых уведомлений!"
    
    safe_send_message(chat_id, text, reply_markup=markup)

# --- Регистрация ---
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
        user_states[tg_id]['state'] = 'waiting_age'
    
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
        user_states[tg_id]['state'] = 'waiting_city'
    
    safe_send_message(tg_id, "🌆 Из какого ты города? Напиши название.")

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_city')
def process_city(message):
    tg_id = message.from_user.id
    city = message.text.strip()
    
    if not city:
        safe_send_message(tg_id, "❌ Город не может быть пустым. Напиши название города.")
        return
    
    with states_lock:
        if tg_id in temp_data:
            temp_data[tg_id]['city'] = city
        user_states[tg_id]['state'] = 'waiting_about'
    
    safe_send_message(
        tg_id, 
        "📝 Расскажи о себе в 1–2 предложениях:\n"
        "Чем занимаешься, что ищешь?"
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
        user_states[tg_id]['state'] = 'waiting_photo'
    
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
    
    if not all(k in data for k in ['name', 'age', 'city']):
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
            cursor.execute('''
                INSERT INTO users (tg_id, name, age, city, about, photo_file_id, is_registered)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (tg_id, data['name'], data['age'], data['city'], data.get('about'), data.get('photo_file_id')))
        
        with states_lock:
            if tg_id in temp_data:
                del temp_data[tg_id]
            if tg_id in user_states:
                del user_states[tg_id]
        
        safe_send_message(tg_id, "✅ Профиль создан! Начинаем поиск людей рядом.")
        send_next_profile(tg_id)
        
    except sqlite3.IntegrityError:
        safe_send_message(tg_id, "❌ Профиль уже существует. Используй /menu")
    except Exception as e:
        logger.error(f"Error in finish_registration: {e}")
        safe_send_message(tg_id, "❌ Произошла ошибка при сохранении профиля. Попробуй позже.")

# --- Поиск анкет ---
def send_next_profile(tg_id):
    """Отправить следующую анкету пользователю"""
    user_id = get_user_id_by_tg(tg_id)
    
    if not user_id:
        safe_send_message(tg_id, "❌ Ты не зарегистрирован. Используй /start")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT u.* FROM users u
                LEFT JOIN reactions r ON u.id = r.target_id AND r.user_id = ?
                WHERE u.id != ? 
                AND u.is_registered = 1
                AND u.is_banned = 0
                AND r.reaction IS NULL
                ORDER BY RANDOM() 
                LIMIT 1
            ''', (user_id, user_id))
            
            target = cursor.fetchone()
        
        if not target:
            safe_send_message(
                tg_id, 
                "😔 Анкеты закончились.\n"
                "Попробуй позже или измени фильтры поиска.\n"
                "Используй /menu для перехода в главное меню."
            )
            return
        
        text = (
            f"👤 {target['name']}, {target['age']} лет\n"
            f"📍 {target['city']}\n"
            f"📝 {target['about'] or 'Нет описания'}\n"
            f"🆔 ID: #{target['id']:05d}"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        btn_like = types.InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{target['id']}")
        btn_dislike = types.InlineKeyboardButton("👎 Дизлайк", callback_data=f"dislike_{target['id']}")
        btn_draft = types.InlineKeyboardButton("📝 В черновики", callback_data=f"draft_{target['id']}")
        btn_report = types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_{target['id']}")
        btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
        markup.add(btn_like, btn_dislike, btn_draft)
        markup.add(btn_report, btn_menu)
        
        if target['photo_file_id']:
            safe_send_photo(tg_id, photo=target['photo_file_id'], caption=text, reply_markup=markup)
        else:
            safe_send_message(tg_id, text, reply_markup=markup)
            
    except Exception as e:
        logger.error(f"Error sending profile: {e}")
        safe_send_message(tg_id, "❌ Ошибка при отправке анкеты")

# --- Обработка действий с анкетами ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    tg_id = call.from_user.id
    
    if tg_id < 0:
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка")
        except:
            pass
        return
    
    if not call.message:
        try:
            bot.answer_callback_query(call.id, "❌ Сообщение не найдено")
        except:
            pass
        return
    
    if not is_registered(tg_id):
        try:
            bot.answer_callback_query(call.id, "❌ Сначала зарегистрируйся: /start")
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
    
    try:
        update_last_active(tg_id)
    except:
        pass
    
    # Обработка меню
    if call.data == "menu":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        show_main_menu(call.message.chat.id, tg_id)
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
        show_profile(tg_id, call.message.chat.id)
        return
    
    if call.data == "edit":
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
        edit_profile(tg_id, call.message.chat.id)
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
                "⚠️ Напишите причину жалобы (кратко):"
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
    
    if user_id == target_id:
        try:
            bot.answer_callback_query(call.id, "❌ Нельзя реагировать на свою анкету!")
        except:
            pass
        return
    
    existing = get_reaction(user_id, target_id)
    
    if existing:
        try:
            bot.answer_callback_query(call.id, "⏳ Ты уже реагировал на эту анкету.")
        except:
            pass
        return
    
    # Записываем реакцию
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
    
    # Если лайк — отправляем уведомление владельцу анкеты
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
            
            check_mutual_like(tg_id, user_id, target_id)
    
    send_next_profile(tg_id)

def check_mutual_like(tg_id, user_id, target_id):
    """Проверить взаимный лайк и создать чат"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 1 FROM reactions 
                WHERE user_id = ? AND target_id = ? AND reaction = 'like'
            ''', (target_id, user_id))
            
            mutual = cursor.fetchone()
            
            if mutual:
                cursor.execute('''
                    INSERT OR IGNORE INTO chats (user1_id, user2_id)
                    VALUES (?, ?)
                ''', (min(user_id, target_id), max(user_id, target_id)))
                
                cursor.execute("SELECT name, tg_id FROM users WHERE id = ?", (target_id,))
                target = cursor.fetchone()
                cursor.execute("SELECT name, tg_id FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                
                if target and user:
                    add_notification(user_id, target_id, 'mutual_like', f"Взаимный лайк с {target['name']}!")
                    add_notification(target_id, user_id, 'mutual_like', f"Взаимный лайк с {user['name']}!")
                    
                    notify_user(
                        tg_id,
                        f"💕 Взаимный лайк с {target['name']}!\n"
                        f"Теперь вы можете общаться!\n"
                        f"Напиши ему/ей: /chat_{target_id}"
                    )
                    
                    notify_user(
                        target['tg_id'],
                        f"💕 Взаимный лайк с {user['name']}!\n"
                        f"Теперь вы можете общаться!\n"
                        f"Напиши ему/ей: /chat_{user_id}"
                    )
        
    except Exception as e:
        logger.error(f"Error checking mutual like: {e}")

# --- Обработка жалоб ---
@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'report_reason')
def process_report(message):
    tg_id = message.from_user.id
    reason = message.text.strip()
    
    if len(reason) < 3:
        safe_send_message(tg_id, "❌ Причина жалобы должна содержать минимум 3 символа.")
        return
    
    state = user_states.get(tg_id, {})
    target_id = state.get('target_id')
    
    if not target_id:
        safe_send_message(tg_id, "❌ Ошибка. Попробуйте снова.")
        return
    
    user_id = get_user_id_by_tg(tg_id)
    
    if add_report(user_id, target_id, reason):
        safe_send_message(tg_id, "✅ Жалоба отправлена! Администрация рассмотрит её.")
        
        # Уведомляем админов
        for admin_id in ADMIN_IDS:
            try:
                safe_send_message(
                    admin_id,
                    f"⚠️ Новая жалоба!\n"
                    f"От: {get_user_by_id(user_id)['name']}\n"
                    f"На: {get_user_by_id(target_id)['name']}\n"
                    f"Причина: {reason}"
                )
            except:
                pass
    else:
        safe_send_message(tg_id, "❌ Ошибка при отправке жалобы.")
    
    del user_states[tg_id]

# --- Уведомления ---
def show_notifications(tg_id):
    """Показать уведомления"""
    notifications = get_unread_notifications(tg_id)
    
    if not notifications:
        safe_send_message(tg_id, "📬 У тебя нет новых уведомлений.")
        mark_notifications_read(tg_id)
        return
    
    text = "📬 Твои уведомления:\n\n"
    for n in notifications:
        if n['type'] == 'like':
            text += f"❤️ {n['from_name']} поставил(а) тебе лайк!\n"
        elif n['type'] == 'mutual_like':
            text += f"💕 Взаимный лайк с {n['from_name']}! Напиши ему/ей: /chat_{n['from_user_id']}\n"
        elif n['type'] == 'message':
            text += f"💬 {n['from_name']}: {n['message']}\n"
        text += f"⏰ {n['created_at']}\n\n"
    
    mark_notifications_read(tg_id)
    safe_send_message(tg_id, text)

# --- Профиль ---
@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    tg_id = message.from_user.id
    show_profile(tg_id, message.chat.id)

def show_profile(tg_id, chat_id=None):
    """Показать профиль пользователя"""
    if chat_id is None:
        chat_id = tg_id
        
    user = get_user_by_tg_id(tg_id)
    
    if not user:
        safe_send_message(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    text = (
        f"👤 Твой профиль\n\n"
        f"🆔 ID: #{user['id']:05d}\n"
        f"👤 Имя: {user['name']}\n"
        f"📅 Возраст: {user['age']}\n"
        f"📍 Город: {user['city']}\n"
        f"📝 О себе: {user['about'] or 'Не указано'}\n"
        f"✅ Статус: {'Подтвержден' if user['verified'] else 'Не подтвержден'}"
    )
    
    markup = types.InlineKeyboardMarkup()
    btn_edit = types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit")
    btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
    markup.add(btn_edit, btn_menu)
    
    if user['photo_file_id']:
        safe_send_photo(chat_id, photo=user['photo_file_id'], caption=text, reply_markup=markup)
    else:
        safe_send_message(chat_id, text, reply_markup=markup)

# --- Редактирование профиля ---
def edit_profile(tg_id, chat_id=None):
    """Редактирование профиля"""
    if chat_id is None:
        chat_id = tg_id
        
    user = get_user_by_tg_id(tg_id)
    
    if not user:
        safe_send_message(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_name = types.InlineKeyboardButton("✏️ Имя", callback_data="edit_name")
    btn_age = types.InlineKeyboardButton("✏️ Возраст", callback_data="edit_age")
    btn_city = types.InlineKeyboardButton("✏️ Город", callback_data="edit_city")
    btn_about = types.InlineKeyboardButton("✏️ О себе", callback_data="edit_about")
    btn_photo = types.InlineKeyboardButton("📸 Фото", callback_data="edit_photo")
    btn_back = types.InlineKeyboardButton("🔙 Назад", callback_data="menu")
    markup.add(btn_name, btn_age, btn_city, btn_about, btn_photo, btn_back)
    
    safe_send_message(chat_id, "📝 Что хочешь изменить?", reply_markup=markup)

# --- Показать матчи ---
def show_matches(tg_id):
    """Показать пользователей, которые поставили лайк"""
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
            
            matches = cursor.fetchall()
        
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

# --- Показать чаты ---
def show_chats(tg_id):
    """Показать активные чаты пользователя"""
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
            
            chats = cursor.fetchall()
        
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

# --- Команды чата ---
@bot.message_handler(func=lambda m: m.from_user.id > 0 and m.text and m.text.startswith('/chat_'))
def handle_chat_command(message):
    """Обработчик команды /chat_ID"""
    tg_id = message.from_user.id
    user_id = get_user_id_by_tg(tg_id)
    
    if not user_id:
        safe_send_message(tg_id, "❌ Сначала зарегистрируйся: /start")
        return
    
    try:
        target_id = int(message.text.split('_')[1])
    except (IndexError, ValueError):
        safe_send_message(tg_id, "❌ Неверный формат команды")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM chats 
                WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
            ''', (user_id, target_id, target_id, user_id))
            
            chat = cursor.fetchone()
        
        if not chat:
            safe_send_message(tg_id, "❌ У вас нет общего чата. Нет взаимного лайка.")
            return
        
        target_user = get_user_by_id(target_id)
        if not target_user:
            safe_send_message(tg_id, "❌ Пользователь не найден")
            return
        
        safe_send_message(
            tg_id,
            f"💬 Чат с {target_user['name']}\n\n"
            f"Просто напиши сообщение, и оно будет отправлено.\n"
            f"(для выхода используй /menu)"
        )
        
        with states_lock:
            user_states[tg_id] = {
                'state': 'in_chat',
                'chat_id': chat['id'],
                'target_id': target_id
            }
    except Exception as e:
        logger.error(f"Error in chat command: {e}")
        safe_send_message(tg_id, "❌ Ошибка при открытии чата")

# --- Обработчик сообщений в чате ---
@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'in_chat')
def chat_message_handler(message):
    """Обработчик сообщений в чате"""
    tg_id = message.from_user.id
    
    with states_lock:
        state = user_states.get(tg_id, {})
        chat_id = state.get('chat_id')
        target_id = state.get('target_id')
    
    if not chat_id or not target_id:
        safe_send_message(tg_id, "❌ Ошибка чата. Используй /menu")
        return
    
    sender = get_user_by_tg_id(tg_id)
    if not sender:
        safe_send_message(tg_id, "❌ Ошибка: пользователь не найден")
        return
    
    target_user = get_user_by_id(target_id)
    if not target_user:
        safe_send_message(tg_id, "❌ Ошибка: получатель не найден")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (chat_id, sender_id, message)
                VALUES (?, ?, ?)
            ''', (chat_id, tg_id, message.text))
    except Exception as e:
        logger.error(f"Error saving message: {e}")
        safe_send_message(tg_id, "❌ Ошибка при отправке сообщения")
        return
    
    user_name = sender['name']
    
    add_notification(target_id, tg_id, 'message', message.text)
    
    notify_user(
        target_user['tg_id'],
        f"💬 Новое сообщение от {user_name}:\n\n{message.text}\n\n"
        f"Ответь: /chat_{tg_id}"
    )
    
    safe_send_message(tg_id, "✅ Сообщение отправлено!")

# --- Админ-команды ---
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    tg_id = message.from_user.id
    
    if not is_admin(tg_id):
        safe_send_message(tg_id, "❌ У вас нет прав администратора.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_stats = types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    btn_users = types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
    btn_reports = types.InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_reports")
    btn_search = types.InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_search")
    btn_broadcast = types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")
    btn_bans = types.InlineKeyboardButton("🚫 Забаненные", callback_data="admin_bans")
    btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
    markup.add(btn_stats, btn_users, btn_reports, btn_search, btn_broadcast, btn_bans, btn_menu)
    
    safe_send_message(
        tg_id,
        "🔐 Админ-панель\n\n"
        "Выберите действие:",
        reply_markup=markup
    )

# --- Админ-обработчики ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    tg_id = call.from_user.id
    
    if not is_admin(tg_id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав администратора.")
        return
    
    action = call.data.replace('admin_', '')
    
    if action == 'stats':
        show_admin_stats(tg_id)
    elif action == 'users':
        show_admin_users(tg_id, 0)
    elif action == 'reports':
        show_admin_reports(tg_id)
    elif action == 'search':
        bot.answer_callback_query(call.id)
        user_states[tg_id] = {'state': 'admin_search'}
        safe_send_message(tg_id, "🔍 Введите ID или имя пользователя для поиска:")
    elif action == 'broadcast':
        bot.answer_callback_query(call.id)
        user_states[tg_id] = {'state': 'admin_broadcast'}
        safe_send_message(tg_id, "📢 Введите сообщение для рассылки:")
    elif action == 'bans':
        show_admin_bans(tg_id)
    elif action.startswith('users_'):
        page = int(action.split('_')[1])
        show_admin_users(tg_id, page)
    elif action.startswith('ban_'):
        user_id = int(action.split('_')[1])
        if ban_user(user_id):
            bot.answer_callback_query(call.id, "✅ Пользователь забанен")
            show_admin_users(tg_id, 0)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при бане")
    elif action.startswith('unban_'):
        user_id = int(action.split('_')[1])
        if unban_user(user_id):
            bot.answer_callback_query(call.id, "✅ Пользователь разбанен")
            show_admin_bans(tg_id)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при разбане")
    elif action.startswith('make_admin_'):
        user_id = int(action.split('_')[1])
        if make_admin(user_id):
            bot.answer_callback_query(call.id, "✅ Права админа выданы")
            show_admin_users(tg_id, 0)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка")
    elif action.startswith('remove_admin_'):
        user_id = int(action.split('_')[1])
        if remove_admin(user_id):
            bot.answer_callback_query(call.id, "✅ Права админа убраны")
            show_admin_users(tg_id, 0)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка")
    elif action.startswith('resolve_'):
        report_id = int(action.split('_')[1])
        resolve_report(report_id)
        bot.answer_callback_query(call.id, "✅ Жалоба закрыта")
        show_admin_reports(tg_id)
    elif action.startswith('view_user_'):
        user_id = int(action.split('_')[1])
        view_user_profile(tg_id, user_id)
    
    bot.answer_callback_query(call.id)

def show_admin_stats(tg_id):
    """Показать статистику"""
    stats = get_stats()
    if not stats:
        safe_send_message(tg_id, "❌ Ошибка получения статистики")
        return
    
    text = (
        "📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🟢 Активные (7 дней): {stats['active_users']}\n"
        f"❤️ Всего лайков: {stats['total_likes']}\n"
        f"💕 Взаимных лайков: {stats['total_chats']}\n"
        f"💬 Всего сообщений: {stats['total_messages']}\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    btn_back = types.InlineKeyboardButton("🔙 Назад", callback_data="admin")
    markup.add(btn_back)
    
    safe_send_message(tg_id, text, reply_markup=markup)

def show_admin_users(tg_id, page):
    """Показать список пользователей"""
    users = get_user_list(limit=10, offset=page*10)
    
    if not users:
        safe_send_message(tg_id, "❌ Пользователи не найдены")
        return
    
    text = f"👥 Пользователи (страница {page+1}):\n\n"
    for user in users:
        status = "🚫" if user['is_banned'] else "✅"
        admin = "👑" if user['is_admin'] else ""
        text += f"{status} #{user['id']:05d} {user['name']}, {user['age']} лет {admin}\n"
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    if page > 0:
        markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data=f"admin_users_{page-1}"))
    if len(users) == 10:
        markup.add(types.InlineKeyboardButton("Вперед ▶️", callback_data=f"admin_users_{page+1}"))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin"))
    
    safe_send_message(tg_id, text, reply_markup=markup)

def show_admin_reports(tg_id):
    """Показать жалобы"""
    reports = get_reports()
    
    if not reports:
        safe_send_message(tg_id, "✅ Нет активных жалоб")
        return
    
    text = "⚠️ Активные жалобы:\n\n"
    for report in reports:
        text += (
            f"ID: #{report['id']}\n"
            f"От: {report['reporter_name']}\n"
            f"На: {report['reported_name']}\n"
            f"Причина: {report['reason']}\n"
            f"Дата: {report['created_at']}\n"
        )
        
        markup = types.InlineKeyboardMarkup()
        btn_view = types.InlineKeyboardButton("👤 Просмотр", callback_data=f"admin_view_user_{report['reported_id']}")
        btn_resolve = types.InlineKeyboardButton("✅ Закрыть", callback_data=f"admin_resolve_{report['id']}")
        btn_ban = types.InlineKeyboardButton("🚫 Забанить", callback_data=f"admin_ban_{report['reported_id']}")
        markup.add(btn_view, btn_resolve, btn_ban)
        
        safe_send_message(tg_id, text, reply_markup=markup)
        text = ""

def show_admin_bans(tg_id):
    """Показать забаненных пользователей"""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE is_banned = 1 AND is_registered = 1
                ORDER BY registration_date DESC
            ''')
            users = cursor.fetchall()
        
        if not users:
            safe_send_message(tg_id, "✅ Нет забаненных пользователей")
            return
        
        text = "🚫 Забаненные пользователи:\n\n"
        for user in users:
            text += f"#{user['id']:05d} {user['name']}, {user['age']} лет\n"
            
            markup = types.InlineKeyboardMarkup()
            btn_unban = types.InlineKeyboardButton("🔓 Разбанить", callback_data=f"admin_unban_{user['id']}")
            markup.add(btn_unban)
            
            safe_send_message(tg_id, text, reply_markup=markup)
            text = ""
            
    except Exception as e:
        logger.error(f"Error showing bans: {e}")
        safe_send_message(tg_id, "❌ Ошибка")

def view_user_profile(tg_id, user_id):
    """Просмотр профиля пользователя админом"""
    user = get_user_by_id(user_id)
    if not user:
        safe_send_message(tg_id, "❌ Пользователь не найден")
        return
    
    text = (
        f"👤 Профиль пользователя #{user['id']:05d}\n\n"
        f"Имя: {user['name']}\n"
        f"Возраст: {user['age']}\n"
        f"Город: {user['city']}\n"
        f"О себе: {user['about'] or 'Не указано'}\n"
        f"Статус: {'✅ Активен' if user['is_banned'] == 0 else '🚫 Забанен'}\n"
        f"Админ: {'👑 Да' if user['is_admin'] else 'Нет'}\n"
        f"Регистрация: {user['registration_date']}\n"
        f"Активен: {user['last_active']}\n"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if user['is_banned']:
        btn_ban = types.InlineKeyboardButton("🔓 Разбанить", callback_data=f"admin_unban_{user['id']}")
    else:
        btn_ban = types.InlineKeyboardButton("🚫 Забанить", callback_data=f"admin_ban_{user['id']}")
    
    if user['is_admin']:
        btn_admin = types.InlineKeyboardButton("👑 Убрать админа", callback_data=f"admin_remove_admin_{user['id']}")
    else:
        btn_admin = types.InlineKeyboardButton("👑 Сделать админом", callback_data=f"admin_make_admin_{user['id']}")
    
    btn_back = types.InlineKeyboardButton("🔙 Назад", callback_data="admin")
    markup.add(btn_ban, btn_admin, btn_back)
    
    if user['photo_file_id']:
        safe_send_photo(tg_id, photo=user['photo_file_id'], caption=text, reply_markup=markup)
    else:
        safe_send_message(tg_id, text, reply_markup=markup)

# --- Обработчики админ-состояний ---
@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'admin_search')
def admin_search_user(message):
    tg_id = message.from_user.id
    query = message.text.strip()
    
    if not is_admin(tg_id):
        safe_send_message(tg_id, "❌ У вас нет прав администратора.")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            if query.isdigit():
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE id = ? AND is_registered = 1
                ''', (int(query),))
            else:
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE name LIKE ? AND is_registered = 1
                    LIMIT 10
                ''', (f'%{query}%',))
            
            users = cursor.fetchall()
        
        if not users:
            safe_send_message(tg_id, f"❌ Пользователь '{query}' не найден")
            return
        
        if len(users) == 1:
            view_user_profile(tg_id, users[0]['id'])
        else:
            text = "🔍 Найденные пользователи:\n\n"
            for user in users:
                text += f"#{user['id']:05d} {user['name']}, {user['age']} лет\n"
            text += "\nВведите ID для просмотра профиля:"
            user_states[tg_id] = {'state': 'admin_view_user', 'users': [u['id'] for u in users]}
            safe_send_message(tg_id, text)
            
    except Exception as e:
        logger.error(f"Error searching user: {e}")
        safe_send_message(tg_id, "❌ Ошибка поиска")

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'admin_view_user')
def admin_view_user(message):
    tg_id = message.from_user.id
    try:
        user_id = int(message.text.strip())
        view_user_profile(tg_id, user_id)
        del user_states[tg_id]
    except ValueError:
        safe_send_message(tg_id, "❌ Введите корректный ID")

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'admin_broadcast')
def admin_broadcast(message):
    tg_id = message.from_user.id
    text = message.text
    
    if not is_admin(tg_id):
        safe_send_message(tg_id, "❌ У вас нет прав администратора.")
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tg_id FROM users WHERE is_registered = 1 AND is_banned = 0")
            users = cursor.fetchall()
        
        if not users:
            safe_send_message(tg_id, "❌ Нет пользователей для рассылки")
            return
        
        sent = 0
        failed = 0
        
        safe_send_message(tg_id, f"📤 Начинаю рассылку для {len(users)} пользователей...")
        
        for user in users:
            try:
                safe_send_message(
                    user['tg_id'],
                    f"📢 Администрация бота:\n\n{text}\n\n"
                    f"_Это сообщение отправлено всем пользователям._",
                    parse_mode='Markdown'
                )
                sent += 1
                time.sleep(0.1)
            except Exception as e:
                failed += 1
                logger.error(f"Failed to send broadcast to {user['tg_id']}: {e}")
        
        safe_send_message(
            tg_id,
            f"✅ Рассылка завершена!\n"
            f"Отправлено: {sent}\n"
            f"Не доставлено: {failed}"
        )
        
        del user_states[tg_id]
        
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        safe_send_message(tg_id, "❌ Ошибка при рассылке")

# --- Запуск бота ---
if __name__ == '__main__':
    logger.info("Бот запущен...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)
