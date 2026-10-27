# repositories.py
"""Бизнес-логика работы с БД: пользователи, уведомления, штрафы, премиум."""
from config import ADMIN_IDS, logger
from database import get_conn, dict_from_row


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