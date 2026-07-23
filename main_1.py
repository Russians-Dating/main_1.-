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

# !!! ВНИМАНИЕ: ЭТОТ ТОКЕН СКОМПРОМЕТИРОВАН. СГЕНЕРИРУЙ НОВЫЙ В @BotFather !!!
TOKEN = "8885788738:AAEEu1kTreUmFfysfrhL1rGms7t0hpaNyd8" 
DB_NAME = "lovebot.db"
ADMIN_IDS = []  # Список ID админов (например:)

bot = telebot.TeleBot(TOKEN)

# --- РОССИЙСКИЕ ГОРОДА ---
RUSSIAN_CITIES = {
    'москва': 'Москва', 'мск': 'Москва',
    'санкт-петербург': 'Санкт-Петербург', 'спб': 'Санкт-Петербург', 'питер': 'Санкт-Петербург',
    'владимир': 'Владимир', 'вологда': 'Вологда', 'воронеж': 'Воронеж', 'иваново': 'Иваново',
    'калуга': 'Калуга', 'кострома': 'Кострома', 'курск': 'Курск', 'липецк': 'Липецк',
    'орёл': 'Орёл', 'орел': 'Орёл', 'рязань': 'Рязань', 'смоленск': 'Смоленск', 'тамбов': 'Тамбов',
    'тверь': 'Тверь', 'тула': 'Тула', 'ярославль': 'Ярославль', 'белгород': 'Белгород',
    'брянск': 'Брянск', 'архангельск': 'Архангельск', 'калининград': 'Калининград',
    'петрозаводск': 'Петрозаводск', 'псков': 'Псков', 'сыктывкар': 'Сыктывкар', 'мурманск': 'Мурманск',
    'великий новгород': 'Великий Новгород', 'новгород': 'Великий Новгород',
    'краснодар': 'Краснодар', 'крд': 'Краснодар', 'сочи': 'Сочи',
    'ростов-на-дону': 'Ростов-на-Дону', 'ростов': 'Ростов-на-Дону',
    'волгоград': 'Волгоград', 'астрахань': 'Астрахань', 'севастополь': 'Севастополь',
    'симферополь': 'Симферополь', 'махачкала': 'Махачкала', 'грозный': 'Грозный',
    'владикавказ': 'Владикавказ', 'ставрополь': 'Ставрополь', 'пятигорск': 'Пятигорск',
    'кисловодск': 'Кисловодск', 'нижний новгород': 'Нижний Новгород', 'н новгород': 'Нижний Новгород', 'нн': 'Нижний Новгород',
    'казань': 'Казань', 'самара': 'Самара', 'уфа': 'Уфа', 'пермь': 'Пермь', 'саратов': 'Саратов',
    'тольятти': 'Тольятти', 'ижевск': 'Ижевск', 'ульяновск': 'Ульяновск', 'чебоксары': 'Чебоксары',
    'киров': 'Киров', 'йошкар-ола': 'Йошкар-Ола', 'саранск': 'Саранск', 'оренбург': 'Оренбург',
    'пенза': 'Пенза', 'набережные челны': 'Набережные Челны', 'екатеринбург': 'Екатеринбург',
    'екат': 'Екатеринбург', 'екб': 'Екатеринбург', 'челябинск': 'Челябинск', 'тюмень': 'Тюмень',
    'магнитогорск': 'Магнитогорск', 'нижний тагил': 'Нижний Тагил', 'сургут': 'Сургут',
    'новый уренгой': 'Новый Уренгой', 'ноябрьск': 'Ноябрьск', 'новосибирск': 'Новосибирск', 'нск': 'Новосибирск',
    'омск': 'Омск', 'красноярск': 'Красноярск', 'иркутск': 'Иркутск', 'кемерово': 'Кемерово',
    'барнаул': 'Барнаул', 'новокузнецк': 'Новокузнецк', 'томск': 'Томск', 'улан-удэ': 'Улан-Удэ',
    'чита': 'Чита', 'абакан': 'Абакан', 'горно-алтайск': 'Горно-Алтайск',
    'владивосток': 'Владивосток', 'хабаровск': 'Хабаровск', 'якутск': 'Якутск',
    'петропавловск-камчатский': 'Петропавловск-Камчатский', 'южно-сахалинск': 'Южно-Сахалинск',
    'магадан': 'Магадан', 'благовещенск': 'Благовещенск', 'комсомольск-на-амуре': 'Комсомольск-на-Амуре',
    'биробиджан': 'Биробиджан',
}

def normalize_city(city_name):
    if not city_name:
        return None
    city_lower = city_name.lower().strip()
    if city_lower in RUSSIAN_CITIES:
        return RUSSIAN_CITIES[city_lower]
    for key, value in RUSSIAN_CITIES.items():
        if city_lower in key or key in city_lower:
            return value
    return None

def get_city_suggestions(query):
    query = query.lower().strip()
    suggestions = []
    for key, value in RUSSIAN_CITIES.items():
        if query in key:
            suggestions.append(value)
    return suggestions

# --- Работа с БД ---
db_lock = threading.Lock()

@contextmanager
def get_conn():
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
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
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
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER,
                    target_id INTEGER,
                    reaction TEXT CHECK(reaction IN ('like', 'dislike', 'draft')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, target_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1_id INTEGER,
                    user2_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                )
            ''')
            
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
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_filters (
                    user_id INTEGER PRIMARY KEY,
                    age_min INTEGER DEFAULT 14,
                    age_max INTEGER DEFAULT 100,
                    city TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

init_db()

# Состояния
user_states = {}
temp_data = {}
states_lock = threading.Lock()

# --- Функции форматирования ---

def format_name(name):
    if not name: return "Не указано"
    name = name.strip()
    parts = name.split(' ')
    formatted_parts = []
    for part in parts:
        if part:
            formatted_parts.append(part.upper() + part[1:].lower())
    return ' '.join(formatted_parts)

def format_age(age):
    if not age: return "Не указан"
    try:
        age = int(age)
        if 11 <= age % 100 <= 14: suffix = "лет"
        elif age % 10 == 1: suffix = "год"
        elif 2 <= age % 10 <= 4: suffix = "года"
        else: suffix = "лет"
        return f"{age} {suffix}"
    except (ValueError, TypeError):
        return str(age)

def format_city(city):
    if not city: return "Не указан"
    return city

def format_about(text):
    if not text: return "Не указано"
    text = text.strip()
    if text: text = text.upper() + text[1:]
    lower_text = text.lower()
    
    if 'котик' in lower_text or 'кот' in lower_text: return f"🐱 {text}"
    elif 'соба' in lower_text or 'пёс' in lower_text: return f"🐶 {text}"
    elif 'спорт' in lower_text or 'фитнес' in lower_text: return f"🏋️ {text}"
    elif 'путешеств' in lower_text: return f"✈️ {text}"
    elif 'книг' in lower_text or 'чита' in lower_text: return f"📚 {text}"
    elif 'музык' in lower_text or 'песн' in lower_text: return f"🎵 {text}"
    elif 'кино' in lower_text or 'фильм' in lower_text: return f"🎬 {text}"
    elif 'игр' in lower_text: return f"🎮 {text}"
    elif 'еда' in lower_text or 'готов' in lower_text: return f"🍳 {text}"
    elif 'сон' in lower_text: return f"😴 {text}"
    elif 'работа' in lower_text: return f"💼 {text}"
    elif 'учёб' in lower_text or 'студ' in lower_text: return f"🎓 {text}"
    else: return f"📝 {text}"

def format_status(verified):
    return "✅ Подтвержден" if verified else "⏳ Не подтвержден"

def format_bool(value, true_text="Да", false_text="Нет"):
    return true_text if value else false_text

def format_user_profile(user, show_id=True, show_status=True):
    if not user: return "❌ Пользователь не найден"
    lines = []
    if show_id: lines.append(f"🆔 ID: #{user['id']:05d}")
    lines.append(f"👤 {format_name(user['name'])}, {format_age(user['age'])}")
    lines.append(f"📍 Город: {format_city(user['city'])}")
    lines.append(f"{format_about(user['about'])}")
    if show_status: lines.append(f"✅ {format_status(user.get('verified', 0))}")
    return '\n'.join(lines)

# --- Основные функции БД ---

def is_admin(tg_id):
    if tg_id in ADMIN_IDS: return True
    user = get_user_by_tg_id(tg_id)
    return user and user.get('is_admin', 0) == 1

def get_user_by_tg_id(tg_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
                return cursor.fetchone()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    return None

def get_user_by_id(user_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                return cursor.fetchone()
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

def is_registered(tg_id):
    user = get_user_by_tg_id(tg_id)
    return user is not None and user['is_registered'] == 1 and user.get('is_banned', 0) == 0

def update_last_active(tg_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE tg_id = ?", (tg_id,))
                return
        except:
            time.sleep(0.5)
            continue

def safe_send_message(chat_id, text, **kwargs):
    try:
        if chat_id < 0: return None
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")
        return None

def safe_send_photo(chat_id, photo, caption="", **kwargs):
    try:
        if chat_id < 0: return None
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
    if not user_id: return []
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
    user_id = get_user_id_by_tg(tg_id)
    if not user_id: return
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (user_id,))
    except Exception as e:
        logger.error(f"Error marking notifications read: {e}")

def notify_user(tg_id, text, **kwargs):
    try:
        user = get_user_by_tg_id(tg_id)
        if not user: return False
        safe_send_message(tg_id, text, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error notifying user {tg_id}: {e}")
        return False

def get_stats():
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_registered = 1")
            total_users = cursor.fetchone()['count']
            
            # Исправлен запрос: last_active вместо last_ac tive
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
            cursor.execute("SELECT COUNT(*) as count FROM reports WHERE status = 'pending'")
            total_reports = cursor.fetchone()['count']
            
            return {
                'total_users': total_users, 'active_users': active_users,
                'total_likes': total_likes, 'total_chats': total_chats,
                'total_messages': total_messages, 'total_reports': total_reports
            }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return None

def get_reports():
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, u1.name as reporter_name, u2.name as reported_name 
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

def get_user_reports_count(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM reports 
                WHERE reported_id = ? AND status = 'pending'
            ''', (user_id,))
            result = cursor.fetchone()
            return result['count'] if result else 0
    except Exception as e:
        logger.error(f"Error getting reports count: {e}")
        return 0

def get_user_reports_info(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, u.name as reporter_name 
                FROM reports r
                JOIN users u ON r.reporter_id = u.id
                WHERE r.reported_id = ? AND r.status = 'pending'
                ORDER BY r.created_at DESC
            ''', (user_id,))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting reports info: {e}")
        return []

def get_user_list(limit=50, offset=0):
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

def get_unverified_users():
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE verified = 0 AND is_registered = 1
                ORDER BY registration_date DESC
            ''')
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting unverified users: {e}")
        return []

def ban_user(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

def _update_user_field(user_id, field, value):
    allowed_fields = ["is_banned", "is_admin", "verified", "last_active"]
    if field not in allowed_fields:
        logger.warning(f"Попытка обновления запрещенного поля: {field}")
        return False
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            query = f"UPDATE users SET {field} = ? WHERE id = ?"
            cursor.execute(query, (value, user_id))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка при обновлении поля {field} для пользователя {user_id}: {e}", exc_info=True)
        return False

def unban_user(user_id): return _update_user_field(user_id, "is_banned", 0)
def make_admin(user_id): return _update_user_field(user_id, "is_admin", 1)
def revoke_admin(user_id): return _update_user_field(user_id, "is_admin", 0)

def verify_user(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET verified = 1 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error verifying user: {e}")
        return False

def unverify_user(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET verified = 0 WHERE id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"Error unverifying user: {e}")
        return False

def add_report(reporter_id, reported_id, reason):
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
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = ?", (report_id,))
        return True
    except Exception as e:
        logger.error(f"Error resolving report: {e}")
        return False

def resolve_report_with_notification(report_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, u1.tg_id as reporter_tg, u1.name as reporter_name,
                       u2.tg_id as reported_tg, u2.name as reported_name
                FROM reports r
                JOIN users u1 ON r.reporter_id = u1.id
                JOIN users u2 ON r.reported_id = u2.id
                WHERE r.id = ?
            ''', (report_id,))
            report = cursor.fetchone()
            
            if not report: return False
            
            cursor.execute("UPDATE reports SET status = 'resolved' WHERE id = ?", (report_id,))
            
            try:
                safe_send_message(
                    report['reporter_tg'],
                    f"ℹ️ **Результат рассмотрения жалобы**\n\n"
                    f"Ваша жалоба на пользователя **{report['reported_name']}** была рассмотрена.\n"
                    f"Статус: ✅ **Жалоба закрыта**\n"
                    f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Спасибо, что помогаете поддерживать порядок! 🙌",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Error notifying reporter: {e}")
            return True
    except Exception as e:
        logger.error(f"Error resolving report with notification: {e}")
        return False

def set_search_filters(user_id, age_min, age_max, city=None):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # ИСПРАВЛЕНО: VALUES вместо VALUE S
            cursor.execute('''
                INSERT OR REPLACE INTO search_filters (user_id, age_min, age_max, city)
                VALUES (?, ?, ?, ?)
            ''', (user_id, age_min, age_max, city))
        return True
    except Exception as e:
        logger.error(f"Error setting filters: {e}")
        return False

def get_search_filters(user_id):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM search_filters WHERE user_id = ?', (user_id,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting filters: {e}")
        return None

def get_reaction(user_id, target_id):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT reaction FROM reactions WHERE user_id = ? AND target_id = ?", 
                              (user_id, target_id))
                reaction = cursor.fetchone()
                return reaction['reaction'] if reaction else None
        except:
            time.sleep(0.5)
            continue
    return None

# --- Обработчики команд ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    tg_id = message.from_user.id
    if tg_id < 0: return
    
    try: update_last_active(tg_id)
    except: pass
    
    if is_registered(tg_id):
        notifications = get_unread_notifications(tg_id)
        if notifications:
            notif_text = "📬 У тебя есть новые уведомления:\n\n"
            for n in notifications:
                if n['type'] == 'like': notif_text += f"❤️ {n['from_name']} поставил(а) тебе лайк!\n"
                elif n['type'] == 'mutual_like': notif_text += f"💕 Взаимный лайк с {n['from_name']}!\n"
                elif n['type'] == 'message': notif_text += f"💬 Новое сообщение от {n['from_name']}: {n['message']}\n"
            safe_send_message(tg_id, notif_text)
            mark_notifications_read(tg_id)
        show_main_menu(message.chat.id, tg_id)
        return
    
    welcome_text = (
        "О, привет! 👀 Ты зашёл именно туда, где можно встретить «того самого» или «ту самую».\n\n"
        "«РусскиеЗнакомства» — это не просто сайт, а реальные люди, которые тоже хотят общения. "
        "Чтобы всё было по-честному, у нас есть модераторы — они следят за порядком, чтобы никаких "
        "фейков и хамства. Поэтому перед тем как искать, глянь наши правила — там всё по делу и без воды:\n"
        "👉 [Честные правила](https://t.me/your_rules_link)\n\n"
        "Ну что, показываю, кто тут рядом и готов к знакомству?"
    )
    
    markup = types.InlineKeyboardMarkup()
    btn_register = types.InlineKeyboardButton("ДАВАЙ СМОТРЕТЬ! 🔥", callback_data="start_registration")
    markup.add(btn_register)
    
    safe_send_message(tg_id, welcome_text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    tg_id = message.from_user.id
    if tg_id < 0: return
    show_main_menu(message.chat.id, tg_id)

@bot.message_handler(commands=['rules'])
def cmd_rules(message):
    tg_id = message.from_user.id
    
    # Используем тройные кавычки без экранирования \n и внутренних кавычек
    rules_text = """📋 **Правила «РусскиеЗнакомства»**

1️⃣ **Будьте вежливы** — уважайте других участников
2️⃣ **Никаких фейков** — только реальные люди
3️⃣ **Не спамьте** — это не место для рекламы
4️⃣ **18+ контент запрещен** — мы за чистоту
5️⃣ **Жалобы** — используйте кнопку «Пожаловаться»
6️⃣ **Модераторы** — всегда на страже порядка

Нарушители будут забанены без предупреждения! ⚠️"""

    markup = types.InlineKeyboardMarkup()
    btn_back = types.InlineKeyboardButton("🔙 Назад", callback_data="menu" if is_registered(tg_id) else "start_registration")
    markup.add(btn_back)
    
    safe_send_message(tg_id, rules_text, reply_markup=markup, parse_mode='Markdown')


@bot.message_handler(commands=['skip'], 
                    func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def skip_photo(message):
    tg_id = message.from_user.id
    safe_send_message(tg_id, "❌ Фото обязательно для регистрации! Пожалуйста, отправьте фото.")

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
    btn_verify = types.InlineKeyboardButton("✅ Верификация", callback_data="admin_verify")
    btn_search = types.InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_search")
    btn_broadcast = types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")
    btn_bans = types.InlineKeyboardButton("🚫 Забаненные", callback_data="admin_bans")
    btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")
    markup.add(btn_stats, btn_users, btn_reports, btn_verify, btn_search, btn_broadcast, btn_bans, btn_menu)
    
    safe_send_message(
        tg_id,
        "🔐 **Админ-панель**\n\n"
        "Выберите действие:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

# --- Регистрация ---

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_name')
def process_name(message):
    tg_id = message.from_user.id
    name = message.text.strip()
    if len(name) < 2 or len(name) > 50:
        safe_send_message(tg_id, "❌ Имя должно быть от 2 до 50 символов. Попробуй ещё раз.")
        return
    
    with states_lock:
        if tg_id in temp_data: temp_data[tg_id]['name'] = name
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
        if tg_id in temp_data: temp_data[tg_id]['age'] = age
        user_states[tg_id]['state'] = 'waiting_city'
    
    safe_send_message(tg_id, "🌆 Из какого ты города? Напиши название.")

@bot.message_handler(func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_city')
def process_city(message):
    tg_id = message.from_user.id
    city_input = message.text.strip()
    
    if not city_input:
        safe_send_message(tg_id, "❌ Город не может быть пустым. Напиши название города.")
        return
    
    normalized_city = normalize_city(city_input)
    
    if not normalized_city:
        suggestions = get_city_suggestions(city_input)
        
        if suggestions:
            suggestion_text = "❌ Город не найден. Возможно, вы имели в виду:\n\n"
            for city in suggestions[:5]:
                suggestion_text += f"• {city}\n"
            suggestion_text += "\nВыберите город из предложенных или введите название правильно."
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            for city in suggestions[:4]:
                btn = types.InlineKeyboardButton(f"📍 {city}", callback_data=f"city_{city}")
                markup.add(btn)
            
            btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data="city_cancel")
            markup.add(btn_cancel)
            
            safe_send_message(tg_id, suggestion_text, reply_markup=markup)
        else:
            error_text = (
                "❌ Город не найден в списке российских городов.\n\n"
                "Пожалуйста, введите название города правильно.\n"
                "Например: Москва, Санкт-Петербург, Казань, Екатеринбург, Уфа, Новосибирск"
            )
            safe_send_message(tg_id, error_text)
        return

    # Если город найден
    with states_lock:
        if tg_id in temp_data: temp_data[tg_id]['city'] = normalized_city
        user_states[tg_id]['state'] = 'waiting_about'
    
    safe_send_message(
        tg_id, 
        f"✅ Город сохранен: {normalized_city}\n\n"
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
        if tg_id in temp_data: temp_data[tg_id]['about'] = about
        user_states[tg_id]['state'] = 'waiting_photo'
    
    safe_send_message(
        tg_id, 
        "📸 **Отправьте фото для анкеты**\n\n"
        "Фото обязательно для регистрации!\n"
        "Отправьте ваше фото (одно фото).",
        parse_mode='Markdown'
    )

@bot.message_handler(content_types=['photo'], 
                    func=lambda m: m.from_user.id > 0 and user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def process_photo(message):
    tg_id = message.from_user.id
    photo_file_id = message.photo[-1].file_id
    
    with states_lock:
        if tg_id in temp_data: temp_data[tg_id]['photo_file_id'] = photo_file_id
    
    finish_registration(tg_id)

def finish_registration(tg_id):
    with states_lock:
        data = temp_data.get(tg_id, {})
    
    if not all(k in data for k in ['name', 'age', 'city']):
        with states_lock:
            if tg_id in temp_data: del temp_data[tg_id]
            if tg_id in user_states: del user_states[tg_id]
        safe_send_message(tg_id, "❌ Что-то пошло не так. Начни заново: /start")
        return
    
    if not data.get('photo_file_id'):
        safe_send_message(tg_id, "❌ Фото обязательно для регистрации! Пожалуйста, отправьте фото.")
        with states_lock: user_states[tg_id]['state'] = 'waiting_photo'
        return
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (tg_id, name, age, city, about, photo_file_id, is_registered)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (tg_id, data['name'], data['age'], data['city'], data.get('about'), data.get('photo_file_id')))
        
        with states_lock:
            if tg_id in temp_data: del temp_data[tg_id]
            if tg_id in user_states: del user_states[tg_id]
        
        safe_send_message(tg_id, "✅ Профиль создан! Начинаем поиск людей рядом.")
        send_next_profile(tg_id)
        
    except sqlite3.IntegrityError:
        safe_send_message(tg_id, "❌ Профиль уже существует. Используй /menu")
    except Exception as e:
        logger.error(f"Error in finish_registration: {e}")
        safe_send_message(tg_id, "❌ Произошла ошибка при сохранении профиля. Попробуй позже.")

# --- Основное меню ---

def show_main_menu(chat_id, tg_id):
    if not is_registered(tg_id):
        safe_send_message(
            chat_id,
            "❌ Сначала зарегистрируйся: /start",
            parse_mode="Markdown"
        )
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
    btn_rules = types.InlineKeyboardButton("📋 Правила", callback_data="rules")
    btn_filters = types.InlineKeyboardButton("⚙️ Фильтры", callback_data="filters")
    markup.add(btn_search, btn_profile, btn_edit, btn_matches, btn_chats, btn_notif, btn_rules, btn_filters)
    
    if is_admin(tg_id):
        btn_admin = types.InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")
        markup.add(btn_admin)
    
    text = (
        "🌟 **Добро пожаловать в «РусскиеЗнакомства»!**\n\n"
        "Здесь ты найдешь интересных людей для общения и знакомств. "
        "Будь собой и наслаждайся общением! 💕\n\n"
        f"📬 Уведомлений: {notif_count}"
    )
    
    safe_send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

# --- Поиск анкет ---

def send_next_profile(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        safe_send_message(tg_id, "❌ Ты не зарегистрирован. Используй /start")
        return

    user = get_user_by_id(user_id)
    if not user:
        safe_send_message(tg_id, "❌ Ошибка пользователя")
        return

    user_city = user['city']
    user_age = user['age']
    is_minor = user_age < 18

    # Формируем базовый запрос
    base_query = '''
        SELECT u.* FROM users u
        LEFT JOIN reactions r ON u.id = r.target_id AND r.user_id = ?
        WHERE u.id != ? 
        AND u.is_registered = 1
        AND u.is_banned = 0
        AND u.verified = 1
        AND u.city = ?
        AND r.reaction IS NULL
    '''

    params = [user_id, user_id, user_city]

    # Логика возраста (исправляет проблему с отступами, если она была здесь)
    if is_minor:
        base_query += " AND u.age BETWEEN 14 AND 17"
    else:
        base_query += " AND u.age >= 18"

    # Фильтры поиска
    filters = get_search_filters(user_id)
    if filters:
        if filters.get('age_min'):
            base_query += " AND u.age >= ?"
            params.append(filters['age_min'])
        if filters.get('age_max'):
            base_query += " AND u.age <= ?"
            params.append(filters['age_max'])

    base_query += " ORDER BY RANDOM() LIMIT 1"

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(base_query, params)
            target = cursor.fetchone()

        if not target:
            msg = "😔 Анкеты закончились.\n\n"
            msg += f"Мы показываем только людей из города {user_city}.\n"
            if is_minor:
                msg += "Вы ищете людей в возрасте 14–17 лет.\n"
            else:
                msg += "Вы ищете людей в возрасте 18+.\n"
            msg += "\nПопробуй позже или измени фильтры поиска."
            safe_send_message(tg_id, msg)
            return

        # Кнопки под анкетой
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_like = types.InlineKeyboardButton("❤️ Нравится", callback_data=f"like_{target['id']}")
        btn_dislike = types.InlineKeyboardButton("💔 Не нравится", callback_data=f"dislike_{target['id']}")
        btn_draft = types.InlineKeyboardButton("📝 В черновик", callback_data=f"draft_{target['id']}")
        btn_report = types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_{target['id']}")
        btn_menu = types.InlineKeyboardButton("📋 Меню", callback_data="menu")

        markup.add(btn_like, btn_dislike, btn_draft)
        markup.add(btn_report, btn_menu)

        profile_text = format_user_profile(target, show_id=False, show_status=True)

        # ИСПРАВЛЕНИЕ ОШИБКИ 1007: кавычки закрыты, проверка на наличие фото
        if target.get('photo_file_id'):
            safe_send_photo(
                tg_id, 
                photo=target['photo_file_id'], 
                caption=profile_text, 
                reply_markup=markup
            )
        else:
            safe_send_message(tg_id, profile_text, reply_markup=markup)

    except Exception as e:
        logger.error(f"Error in send_next_profile: {e}")
        safe_send_message(tg_id, "❌ Произошла ошибка при показе анкеты. Попробуй позже.")