import sqlite3
import threading
from contextlib import contextmanager
from config import DB_NAME, logger, ADMIN_IDS
from utils import safe_send_message

db_lock = threading.RLock()


@contextmanager
def get_conn():
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def dict_from_row(row):
    return dict(row) if row is not None else None


# ==========================================================
#              ПОЛЬЗОВАТЕЛИ
# ==========================================================

def safe_get_user(tg_id):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            return dict_from_row(cur.fetchone())
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None


def get_user_by_tg_id(tg_id):
    return safe_get_user(tg_id)


def get_user_by_id(user_id):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            return dict_from_row(cur.fetchone())
    except Exception as e:
        logger.error(f"Error getting user by id: {e}")
        return None


def get_user_id_by_tg(tg_id):
    u = get_user_by_tg_id(tg_id)
    return u['id'] if u else None


def is_admin(tg_id):
    if tg_id in ADMIN_IDS:
        return True
    u = get_user_by_tg_id(tg_id)
    return bool(u and u.get('is_admin') == 1)


def get_admin_level(tg_id):
    if tg_id in ADMIN_IDS:
        return 3
    u = get_user_by_tg_id(tg_id)
    if u and u.get('is_admin') == 1:
        return u.get('admin_level', 1)
    return 0


def update_last_active(tg_id):
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE tg_id = ?",
                (tg_id,)
            )
    except Exception as e:
        logger.error(f"Error updating last active: {e}")


def is_registered(tg_id):
    u = get_user_by_tg_id(tg_id)
    return bool(u and u.get('is_registered') == 1 and u.get('is_banned', 0) == 0)


# ==========================================================
#              УВЕДОМЛЕНИЯ
# ==========================================================

def notify_user(tg_id, text, **kwargs):
    try:
        if tg_id is None:
            return False
        return bool(safe_send_message(tg_id, text, **kwargs))
    except Exception as e:
        logger.warning(f"notify fail {tg_id}: {e}")
        return False


def add_notification(user_id, from_user_id, notif_type, message=""):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO notifications (user_id, from_user_id, type, message) "
                "VALUES (?, ?, ?, ?)",
                (user_id, from_user_id, notif_type, message)
            )
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
            cur = conn.cursor()
            cur.execute('''
                SELECT n.*, COALESCE(u.name, 'Кто-то') as from_name
                FROM notifications n
                LEFT JOIN users u ON n.from_user_id = u.id
                WHERE n.user_id = ? AND n.is_read = 0
                ORDER BY n.created_at DESC
                LIMIT 50
            ''', (user_id,))
            return [dict_from_row(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return []


def mark_notifications_read(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
                (user_id,)
            )
    except Exception as e:
        logger.error(f"Error marking notifications read: {e}")


# ==========================================================
#              ШТРАФЫ
# ==========================================================

def get_fines(tg_id, active_only=True):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return []
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if active_only:
                cur.execute(
                    "SELECT * FROM fines WHERE user_id = ? AND status = 'active' "
                    "ORDER BY created_at DESC", (user_id,))
            else:
                cur.execute(
                    "SELECT * FROM fines WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,))
            return [dict_from_row(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting fines: {e}")
        return []


def is_user_fined(tg_id):
    return len(get_fines(tg_id, active_only=True)) > 0


# ==========================================================
#              ПРЕМИУМ / ЗВЁЗДЫ / ЛОГИ
# ==========================================================

def set_premium(user_id, days):
    try:
        with get_conn() as conn:
            conn.execute('''
                UPDATE users SET
                    is_premium = 1,
                    premium_until = datetime('now', '+' || ? || ' days')
                WHERE id = ?
            ''', (days, user_id))
        return True
    except Exception as e:
        logger.error(f"Error setting premium: {e}")
        return False


def add_stars(user_id, amount, description=""):
    try:
        with get_conn() as conn:
            conn.execute('UPDATE users SET stars = stars + ? WHERE id = ?', (amount, user_id))
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) "
                "VALUES (?, ?, 'admin_gift', ?)",
                (user_id, amount, description)
            )
        return True
    except Exception as e:
        logger.error(f"Error adding stars: {e}")
        return False


def log_admin_action(admin_tg_id, action, target_id=0, details=""):
    try:
        with get_conn() as conn:
            admin_user = get_user_by_tg_id(admin_tg_id)
            conn.execute(
                "INSERT INTO admin_logs (admin_id, action, target_id, details) "
                "VALUES (?, ?, ?, ?)",
                (admin_user['id'] if admin_user else 0, action, target_id, details)
            )
    except Exception as e:
        logger.error(f"log_admin_action error: {e}")


# ==========================================================
#              ИНИЦИАЛИЗАЦИЯ БД
# ==========================================================

def init_db():
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute('''
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
                    looking_for_age_max INTEGER DEFAULT 100,
                    looking_for_gender TEXT DEFAULT 'всех',
                    search_city TEXT,
                    tags TEXT,
                    is_chat_banned INTEGER DEFAULT 0,
                    is_like_banned INTEGER DEFAULT 0,
                    is_dislike_banned INTEGER DEFAULT 0,
                    is_draft_banned INTEGER DEFAULT 0,
                    is_search_banned INTEGER DEFAULT 0,
                    is_visible INTEGER DEFAULT 1,
                    referrer_id INTEGER,
                    referral_count INTEGER DEFAULT 0,
                    referral_rewarded INTEGER DEFAULT 0
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER,
                    target_id INTEGER,
                    reaction TEXT CHECK(reaction IN ('like', 'dislike', 'draft')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, target_id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1_id INTEGER,
                    user2_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    sender_id INTEGER,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES chats(id)
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    from_user_id INTEGER,
                    type TEXT,
                    message TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER,
                    reported_id INTEGER,
                    reason TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
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
            c.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    type TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS premium_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    duration_days INTEGER,
                    amount_stars INTEGER,
                    amount_rub INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT,
                    target_id INTEGER,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS channel_checks (
                    user_id INTEGER PRIMARY KEY,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Индексы для скорости
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_tg ON users(tg_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_reg ON users(is_registered)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reactions_user ON reactions(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reactions_target ON reactions(target_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read)")

        try:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM notifications WHERE created_at < datetime('now', '-30 days')"
                )
        except Exception as e:
            logger.error(f"Cleanup notifications error: {e}")

        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")