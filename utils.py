import html
from datetime import datetime
from config import logger
import telebot

bot = None  # устанавливается в main.py


def safe_send_message(chat_id, text, **kwargs):
    try:
        if chat_id is None:
            return None
        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):
            return None
        if chat_id == 0:
            return None
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.warning(f"send_message to {chat_id} failed: {e}")
        return None


def safe_send_photo(chat_id, photo, caption="", **kwargs):
    try:
        if chat_id is None or not photo:
            return None
        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):
            return None
        if chat_id == 0:
            return None
        return bot.send_photo(chat_id, photo=photo, caption=caption, **kwargs)
    except Exception as e:
        logger.warning(f"send_photo to {chat_id} failed: {e}")
        try:
            return bot.send_message(chat_id, caption or "📷 [фото недоступно]", **kwargs)
        except Exception:
            return None


def safe_answer_callback(call_id, text=None, show_alert=False):
    try:
        bot.answer_callback_query(call_id, text=text, show_alert=show_alert)
    except Exception:
        pass


def safe_edit_message(chat_id, message_id, text=None, reply_markup=None):
    try:
        bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=reply_markup
        )
    except Exception:
        pass


def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def escape_html(text):
    return html.escape(str(text)) if text else ""


def user_mention(user):
    """Возвращает HTML-упоминание пользователя."""
    name = escape_html(user.get('name') or f"ID {user['id']}")
    tg_id = user.get('tg_id')
    if not tg_id:
        return name
    return f'<a href="tg://user?id={tg_id}">{name}</a>'