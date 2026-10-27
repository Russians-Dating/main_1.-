import sqlite3

from telebot import types
from config import BOT_USERNAME, REFERRAL_REWARD_COUNT, REFERRAL_REWARD_DAYS, logger
from database import get_conn, dict_from_row
from keyboards import referral_kb
from utils import safe_send_message, safe_answer_callback, escape_html

import telebot


def get_referral_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


def get_referral_stats(user_id):
    """Возвращает (count, rewarded_days, pending_to_next)"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
            count = cur.fetchone()[0]
            cur.execute("SELECT referral_rewarded FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            rewarded = row[0] if row else 0
        # Сколько уже выдано "пачек" по REFERRAL_REWARD_COUNT
        earned_days = (count // REFERRAL_REWARD_COUNT) * REFERRAL_REWARD_DAYS
        pending = REFERRAL_REWARD_COUNT - (count % REFERRAL_REWARD_COUNT)
        if pending == REFERRAL_REWARD_COUNT and count > 0:
            pending = 0
        return count, earned_days, pending
    except Exception as e:
        logger.error(f"get_referral_stats error: {e}")
        return 0, 0, REFERRAL_REWARD_COUNT


def register_referral(referred_tg_id, referrer_user_id):
    """Сохраняет реферала и начисляет награду при достижении порога.

    Возвращает True, если в этот момент была выдана награда.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Проверяем, что реферер существует
            cur.execute("SELECT id FROM users WHERE id = ?", (referrer_user_id,))
            if not cur.fetchone():
                return False

            # Реферал должен существовать как пользователь (зарегистрирован)
            cur.execute("SELECT id FROM users WHERE tg_id = ?", (referred_tg_id,))
            referred_row = cur.fetchone()
            if not referred_row:
                return False

            # Нельзя быть рефералом самого себя
            if referred_row[0] == referrer_user_id:
                return False

            # Проверяем, что реферал ещё не привязан (идемпотентность)
            cur.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (referred_tg_id,))
            if cur.fetchone():
                return False

            # Записываем реферал
            try:
                cur.execute(
                    "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                    (referrer_user_id, referred_tg_id)
                )
            except sqlite3.IntegrityError:
                # Гонка: реферал уже привязан другой попыткой
                return False

            # Обновляем счётчик у реферера на основе фактического числа рефералов
            cur.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
                (referrer_user_id,)
            )
            new_count = cur.fetchone()[0]
            cur.execute(
                "UPDATE users SET referral_count = ? WHERE id = ?",
                (new_count, referrer_user_id)
            )

            # Сколько наград УЖЕ выдано и сколько должно быть всего
            cur.execute(
                "SELECT referral_rewarded FROM users WHERE id = ?",
                (referrer_user_id,)
            )
            rewarded_now = cur.fetchone()[0] or 0
            reward_due = new_count // REFERRAL_REWARD_COUNT

            reward_given = False
            if reward_due > rewarded_now:
                batches = reward_due - rewarded_now
                total_days = batches * REFERRAL_REWARD_DAYS
                cur.execute('''
                    UPDATE users SET
                        is_premium = 1,
                        premium_until = CASE
                            WHEN premium_until IS NOT NULL AND premium_until > datetime('now')
                                THEN datetime(premium_until, '+' || ? || ' days')
                            ELSE datetime('now', '+' || ? || ' days')
                        END,
                        referral_rewarded = referral_rewarded + ?
                    WHERE id = ?
                ''', (total_days, total_days, batches, referrer_user_id))

                cur.execute('''
                    INSERT INTO transactions (user_id, amount, type, description)
                    VALUES (?, 0, 'premium', ?)
                ''', (referrer_user_id,
                      f'Реферальная награда: +{total_days}д премиума за {new_count} друзей'))

                reward_given = True

        return reward_given

    except Exception as e:
        logger.error(f"register_referral error: {e}")
        return False


def save_pending_referral(temp_data: dict, tg_id, payload) -> None:
    """Из payload 'ref_<id>' сохраняем referrer_id во временные данные
    незавершённой регистрации. Вызывается из /start до регистрации."""
    if not payload or not payload.startswith('ref_'):
        return
    try:
        referrer_id = int(payload.replace('ref_', '', 1))
    except (ValueError, AttributeError):
        return
    if referrer_id <= 0:
        return
    temp_data.setdefault(tg_id, {})['referrer_id'] = referrer_id


def finalize_referral_after_registration(tg_id, referrer_id):
    """Вызывается после успешной регистрации нового пользователя.
    Возвращает True, если была выдана награда рефереру."""
    if not referrer_id:
        return False
    return register_referral(tg_id, referrer_id)


def show_referral_menu(bot, tg_id, user_id):
    link = get_referral_link(user_id)
    count, earned_days, pending = get_referral_stats(user_id)

    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай <b>Premium бесплатно</b>!\n\n"
        f"📊 <b>Твоя статистика:</b>\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"👑 Заработано премиума: <b>{earned_days} дн.</b>\n"
    )

    if pending > 0 and count > 0:
        text += f"⏳ До следующей награды: ещё <b>{pending}</b> чел.\n"
    elif count == 0:
        text += f"⏳ До первой награды: ещё <b>{REFERRAL_REWARD_COUNT}</b> чел.\n"

    text += (
        f"\n💰 <b>Награда:</b> за каждые {REFERRAL_REWARD_COUNT} друзей — "
        f"{REFERRAL_REWARD_DAYS} день Premium!\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>"
    )

    kb = referral_kb(link)
    safe_send_message(tg_id, text, reply_markup=kb, parse_mode='HTML')


def register_referral_handlers(bot_instance):
    """Регистрирует callback-хендлеры."""
    global bot
    bot = bot_instance

    @bot.callback_query_handler(func=lambda c: c.data == 'referral')
    def cb_referral(call):
        from database import get_user_by_tg_id
        u = get_user_by_tg_id(call.from_user.id)
        if not u:
            safe_answer_callback(call.id, "❌ Сначала зарегистрируйся")
            return
        safe_answer_callback(call.id)
        show_referral_menu(bot, call.from_user.id, u['id'])

    @bot.callback_query_handler(func=lambda c: c.data == 'copy_ref')
    def cb_copy_ref(call):
        from database import get_user_by_tg_id
        u = get_user_by_tg_id(call.from_user.id)
        if not u:
            return
        link = get_referral_link(u['id'])
        safe_answer_callback(call.id, f"🔗 Ссылка: {link}", show_alert=True)