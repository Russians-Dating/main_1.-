import threading
import time

import telebot
from telebot import types

from config import TOKEN, ADMIN_IDS, BASHKIR_CITIES, logger, CHANNEL_ID, CHANNEL_URL, BOT_USERNAME
from database import (
    init_db, get_conn, get_user_by_tg_id, get_user_by_id,
    get_user_id_by_tg, is_admin, get_admin_level, update_last_active,
    is_registered, get_unread_notifications, mark_notifications_read,
    add_notification, get_fines, is_user_fined, log_admin_action,
    set_premium, dict_from_row   # ← добавили
)
from keyboards import (
    gender_kb, tags_kb, subscription_kb, main_menu_kb, profile_kb,
    edit_profile_kb, profile_card_kb, search_settings_kb, gender_search_kb,
    cities_kb, donate_kb, fine_kb, PREMIUM_PLANS
)
import utils
from utils import (
    safe_send_message, safe_send_photo, safe_answer_callback,
    escape_html, user_mention 
)

# Импортируем и регистрируем handlers
from handlers import referral as ref_module
from handlers import admin as admin_module

# --- Создаём бота ---
bot = telebot.TeleBot(TOKEN, parse_mode=None)
utils.bot = bot  # для utils

# --- Глобальные состояния ---
user_states = {}
temp_data = {}
user_tags = {}
states_lock = threading.RLock()

# --- Инициализация БД ---
init_db()


# ==========================================================
#              ОБЩИЕ УТИЛИТЫ
# ==========================================================

def check_subscription(tg_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, tg_id)
        return member.status in ('member', 'administrator', 'creator')
    except Exception as e:
        logger.warning(f"sub check fail {tg_id}: {e}")
        return True


def require_subscription(tg_id):
    if check_subscription(tg_id):
        return True
    safe_send_message(
        tg_id,
        "📢 Для использования бота подпишись на наш канал:",
        reply_markup=subscription_kb()
    )
    return False


def notify_user(tg_id, text, **kwargs):
    try:
        if tg_id is None:
            return False
        return bool(safe_send_message(tg_id, text, **kwargs))
    except Exception as e:
        logger.warning(f"notify fail {tg_id}: {e}")
        return False


# ==========================================================
#              /start и РЕГИСТРАЦИЯ
# ==========================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    tg_id = message.from_user.id
    if tg_id < 0 or getattr(message.from_user, 'is_bot', False):
        return

    # Обработка реферальной ссылки — сохраняем временно
    args = message.text.split()
    pending_referrer = None
    if len(args) > 1 and args[1].startswith('ref_'):
        ref_module.save_pending_referral(temp_data, tg_id, args[1])
        pending_referrer = temp_data.get(tg_id, {}).get('referrer_id')

    if not require_subscription(tg_id):
        return

    if is_registered(tg_id):
        show_main_menu(tg_id)
        return

    with states_lock:
        temp_data[tg_id] = {}
        if pending_referrer:
            temp_data[tg_id]['referrer_id'] = pending_referrer
        user_tags[tg_id] = []
        user_states[tg_id] = {'state': 'waiting_gender'}

    safe_send_message(
        tg_id,
        "👋 <b>Привет!</b>\n\nДавай создадим твою анкету.\n\nВыбери свой пол:",
        reply_markup=gender_kb(),
        parse_mode='HTML'
    )


@bot.callback_query_handler(func=lambda c: c.data == "check_subscription")
def cb_check_subscription(call):
    tg_id = call.from_user.id
    if check_subscription(tg_id):
        safe_answer_callback(call.id, "✅ Спасибо!")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        cmd_start(call.message)
    else:
        safe_answer_callback(call.id, "❌ Ты ещё не подписан", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith('gender_'))
def process_gender(call):
    tg_id = call.from_user.id
    with states_lock:
        if user_states.get(tg_id, {}).get('state') != 'waiting_gender':
            safe_answer_callback(call.id, "❌ Не сейчас")
            return
    gender = 'мужской' if call.data == 'gender_male' else 'женский'
    with states_lock:
        temp_data.setdefault(tg_id, {})['gender'] = gender
        user_states[tg_id] = {'state': 'waiting_name'}
    safe_answer_callback(call.id)
    safe_send_message(tg_id, "📝 Как тебя зовут? (от 2 до 50 символов)")


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_name')
def process_name(message):
    tg_id = message.from_user.id
    name = (message.text or "").strip()
    if not (2 <= len(name) <= 50):
        safe_send_message(tg_id, "❌ Имя от 2 до 50 символов.")
        return
    with states_lock:
        temp_data.setdefault(tg_id, {})['name'] = name
        user_states[tg_id] = {'state': 'waiting_age'}
    safe_send_message(tg_id, "📅 Сколько тебе лет? (14–100)")


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_age')
def process_age(message):
    tg_id = message.from_user.id
    try:
        age = int((message.text or "").strip())
    except ValueError:
        safe_send_message(tg_id, "❌ Введи число.")
        return
    if not (14 <= age <= 100):
        safe_send_message(tg_id, "❌ Возраст 14–100.")
        return
    with states_lock:
        temp_data.setdefault(tg_id, {})['age'] = age
        user_states[tg_id] = {'state': 'waiting_city'}
    cities = ", ".join(BASHKIR_CITIES)
    safe_send_message(
        tg_id,
        f"🏙️ Города Башкортостана:\n{cities}\n\n🌆 Напиши свой город:"
    )


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_city')
def process_city(message):
    import re
    tg_id = message.from_user.id
    city = (message.text or "").strip()
    if not re.match(r'^[А-ЯЁ][а-яё\- ]+$', city):
        safe_send_message(tg_id, "❌ С большой буквы, только русские. Пример: Уфа")
        return
    if city not in BASHKIR_CITIES:
        safe_send_message(tg_id, "❌ Город не найден. Доступны:\n" + ", ".join(BASHKIR_CITIES))
        return
    with states_lock:
        temp_data.setdefault(tg_id, {})['city'] = city
        user_states[tg_id] = {'state': 'waiting_tags'}
        user_tags[tg_id] = []
    safe_send_message(
        tg_id,
        "🏷️ Выбери свои интересы:",
        reply_markup=tags_kb([])
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith('tag_') and c.data != 'tag_')
def process_tag(call):
    tg_id = call.from_user.id
    tag = call.data.split('_', 1)[1]
    with states_lock:
        if user_states.get(tg_id, {}).get('state') != 'waiting_tags':
            safe_answer_callback(call.id, "❌ Не сейчас")
            return
        selected = user_tags.setdefault(tg_id, [])
        if tag in selected:
            selected.remove(tag)
        else:
            if len(selected) >= 10:
                safe_answer_callback(call.id, "❌ Максимум 10 тегов")
                return
            selected.append(tag)
        current = list(selected)
    safe_answer_callback(call.id, f"✅ {tag}")
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🏷️ Выбери свои интересы:",
            reply_markup=tags_kb(current)
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "tags_done")
def tags_done(call):
    tg_id = call.from_user.id
    with states_lock:
        if user_states.get(tg_id, {}).get('state') != 'waiting_tags':
            safe_answer_callback(call.id, "❌ Не сейчас")
            return
        temp_data.setdefault(tg_id, {})['tags'] = ','.join(user_tags.get(tg_id, []))
        user_states[tg_id] = {'state': 'waiting_about'}
        user_tags.pop(tg_id, None)
    safe_answer_callback(call.id)
    safe_send_message(
        tg_id,
        "📝 Расскажи о себе (1–2 предложения, до 500 символов):"
    )


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_about')
def process_about(message):
    tg_id = message.from_user.id
    about = (message.text or "").strip()
    if len(about) > 500:
        safe_send_message(tg_id, "❌ Максимум 500 символов.")
        return
    with states_lock:
        temp_data.setdefault(tg_id, {})['about'] = about
        user_states[tg_id] = {'state': 'waiting_photo'}
    safe_send_message(tg_id, "📸 Пришли фото (или /skip):")


@bot.message_handler(content_types=['photo'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def process_photo(message):
    tg_id = message.from_user.id
    if not message.photo:
        safe_send_message(tg_id, "❌ Не вижу фото. Или /skip")
        return
    with states_lock:
        temp_data.setdefault(tg_id, {})['photo_file_id'] = message.photo[-1].file_id
    finish_registration(tg_id)


@bot.message_handler(commands=['skip'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'waiting_photo')
def skip_photo(message):
    tg_id = message.from_user.id
    with states_lock:
        temp_data.setdefault(tg_id, {})['photo_file_id'] = None
    finish_registration(tg_id)


def finish_registration(tg_id):
    with states_lock:
        data = dict(temp_data.get(tg_id, {}))
        referrer_id = data.pop('referrer_id', None)
    for f in ('name', 'age', 'city', 'gender'):
        if not data.get(f):
            with states_lock:
                temp_data.pop(tg_id, None)
                user_states.pop(tg_id, None)
            safe_send_message(tg_id, "❌ Ошибка. /start")
            return

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute('''
                    UPDATE users SET name=?, age=?, city=?, about=?, photo_file_id=?,
                        is_registered=1, gender=?, tags=?, last_active=CURRENT_TIMESTAMP
                    WHERE tg_id = ?
                ''', (data['name'], data['age'], data['city'], data.get('about', ''),
                      data.get('photo_file_id'), data['gender'], data.get('tags', ''), tg_id))
            else:
                cur.execute('''
                    INSERT INTO users (tg_id, name, age, city, about, photo_file_id,
                        is_registered, gender, tags,
                        looking_for_age_min, looking_for_age_max, looking_for_gender)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 14, 100, 'всех')
                ''', (tg_id, data['name'], data['age'], data['city'],
                      data.get('about', ''), data.get('photo_file_id'),
                      data['gender'], data.get('tags', '')))
    except Exception as e:
        logger.error(f"finish_registration: {e}")
        safe_send_message(tg_id, "❌ Ошибка сохранения.")
        return

    with states_lock:
        temp_data.pop(tg_id, None)
        user_states.pop(tg_id, None)

    # Финализируем реферала, если он был приведён по ссылке
    if referrer_id:
        try:
            reward_given = ref_module.finalize_referral_after_registration(tg_id, referrer_id)
            if reward_given:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT tg_id FROM users WHERE id = ?", (referrer_id,))
                    r = cur.fetchone()
                    if r:
                        safe_send_message(
                            r[0],
                            f"🎉 <b>Поздравляем!</b>\n\nДостигнут порог рефералов — "
                            f"начислен бонусный Premium 👑",
                            parse_mode='HTML'
                        )
        except Exception as e:
            logger.error(f"referral finalize error: {e}")

    safe_send_message(tg_id, "✅ <b>Профиль создан!</b>", parse_mode='HTML')
    show_profile(tg_id)


# ==========================================================
#              ПРОФИЛЬ / МЕНЮ
# ==========================================================

def show_profile(tg_id, chat_id=None):
    chat_id = chat_id or tg_id
    user = get_user_by_tg_id(tg_id)
    if not user:
        safe_send_message(chat_id, "❌ Сначала /start")
        return
    tags_list = user.get('tags', '').split(',') if user.get('tags') else []
    tags_text = ", ".join(tags_list) if tags_list else "Не указаны"
    referral_link = ref_module.get_referral_link(user['id'])

    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: #{user['id']:05d}\n"
        f"👤 Имя: {escape_html(user['name'])}\n"
        f"🎂 Возраст: {user['age']}\n"
        f"🏙️ Город: {user['city']}\n"
        f"⚥ Пол: {user.get('gender') or '—'}\n"
        f"🏷️ Интересы: {escape_html(tags_text)}\n"
        f"📝 О себе: {escape_html(user.get('about') or '—')}\n\n"
        f"💰 Баланс: {user.get('stars', 0)} ⭐\n"
        f"👑 Премиум: {'Да' if user.get('is_premium') else 'Нет'}\n"
        f"✅ Верификация: {'Да' if user.get('verified') else 'Нет'}\n"
        f"🎁 Приглашено друзей: {user.get('referral_count', 0)}"
    )
    sent = None
    if user.get('photo_file_id'):
        sent = safe_send_photo(chat_id, photo=user['photo_file_id'],
                               caption=text, reply_markup=profile_kb(referral_link),
                               parse_mode='HTML')
    if not sent:
        safe_send_message(chat_id, text, reply_markup=profile_kb(referral_link),
                          parse_mode='HTML')


def show_main_menu(tg_id):
    if not is_registered(tg_id):
        safe_send_message(tg_id, "❌ Сначала /start")
        return
    if is_user_fined(tg_id):
        show_fine_notification(tg_id)
        return
    notif_count = len(get_unread_notifications(tg_id))
    text = "📋 <b>Главное меню</b>"
    if notif_count > 0:
        text += f"\n\n🔔 Новых уведомлений: {notif_count}"
    safe_send_message(
        tg_id, text,
        reply_markup=main_menu_kb(is_admin(tg_id), notif_count),
        parse_mode='HTML'
    )


def show_search_settings(tg_id):
    user = get_user_by_tg_id(tg_id)
    if not user:
        return
    text = (
        f"⚙️ <b>Настройки поиска</b>\n\n"
        f"🎂 Возраст: {user.get('looking_for_age_min', 14)}–{user.get('looking_for_age_max', 100)}\n"
        f"⚥ Пол: {user.get('looking_for_gender', 'всех')}\n"
        f"🏙️ Город: {user.get('search_city') or 'Все города'}"
    )
    safe_send_message(tg_id, text, reply_markup=search_settings_kb(), parse_mode='HTML')


def edit_profile(tg_id, chat_id=None):
    chat_id = chat_id or tg_id
    safe_send_message(chat_id, "📝 Что изменить?", reply_markup=edit_profile_kb())


# ==========================================================
#              ПОИСК И РЕАКЦИИ
# ==========================================================

def send_next_profile(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        safe_send_message(tg_id, "❌ /start")
        return
    if is_user_fined(tg_id):
        show_fine_notification(tg_id)
        return
    user = get_user_by_id(user_id)
    if not user or user.get('is_search_banned') == 1:
        safe_send_message(tg_id, "❌ Поиск заблокирован.")
        return

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            a_min = user.get('looking_for_age_min') or 14
            a_max = user.get('looking_for_age_max') or 100
            g = user.get('looking_for_gender') or 'всех'
            city = user.get('search_city')
            q = '''SELECT u.* FROM users u
                   LEFT JOIN reactions r ON u.id = r.target_id AND r.user_id = ?
                   WHERE u.id != ? AND u.is_registered = 1 AND u.is_banned = 0
                   AND u.is_visible = 1 AND u.age BETWEEN ? AND ?'''
            params = [user_id, user_id, a_min, a_max]
            if g != 'всех':
                q += " AND u.gender = ?"
                params.append(g)
            if city:
                q += " AND u.city = ?"
                params.append(city)
            q += " AND r.reaction IS NULL ORDER BY RANDOM() LIMIT 1"
            cur.execute(q, params)
            target = dict_from_row_safe(cur.fetchone())
    except Exception as e:
        logger.error(f"send_next_profile: {e}")
        safe_send_message(tg_id, "❌ Ошибка поиска.")
        return

    if not target:
        safe_send_message(tg_id, "😔 Анкеты закончились.\n/menu — меню")
        return

    tags_list = target.get('tags', '').split(',') if target.get('tags') else []
    tags_text = "🏷️ " + ", ".join(tags_list) if tags_list else ""

    text = (
        f"🆔 ID: #{target['id']:05d}\n"
        f"👤 Имя: {escape_html(target['name'])}\n"
        f"🎂 Возраст: {target['age']}\n"
        f"🏙️ Город: {target['city']}\n"
        f"{tags_text}\n"
        f"📝 {escape_html(target.get('about') or 'Не указано')}"
    )
    sent = None
    if target.get('photo_file_id'):
        sent = safe_send_photo(tg_id, photo=target['photo_file_id'], caption=text,
                               reply_markup=profile_card_kb(target['id']), parse_mode='HTML')
    if not sent:
        safe_send_message(tg_id, text, reply_markup=profile_card_kb(target['id']),
                          parse_mode='HTML')


def dict_from_row_safe(row):
    from database import dict_from_row
    return dict_from_row(row)


# ==========================================================
#              ШТРАФЫ
# ==========================================================

def show_fine_notification(tg_id):
    user = get_user_by_tg_id(tg_id)
    if not user:
        return
    fines = get_fines(tg_id)
    if not fines:
        return
    total = sum(f['amount'] for f in fines)
    text = "🚨 <b>Вас оштрафовали!</b>\n\n"
    for f in fines:
        text += f"Причина: {escape_html(f.get('reason', ''))}\n"
        text += f"Сумма: {f.get('amount', 0)} ⭐\n\n"
    text += (
        "⚡ Последствия:\n❌ Лайки\n❌ Дизлайки\n❌ Черновики\n❌ Поиск\n\n"
        f"💰 Баланс: {user.get('stars', 0)} ⭐\n"
        f"Не хватает: {max(0, total - user.get('stars', 0))} ⭐"
    )
    safe_send_message(tg_id, text, reply_markup=fine_kb(total), parse_mode='HTML')


@bot.callback_query_handler(func=lambda c: c.data.startswith('fine_pay_'))
def cb_fine_pay(call):
    tg_id = call.from_user.id
    try:
        amount = int(call.data.split('_')[2])
    except (ValueError, IndexError):
        safe_answer_callback(call.id, "❌ Ошибка")
        return
    user = get_user_by_tg_id(tg_id)
    if not user:
        return
    if user.get('stars', 0) < amount:
        safe_answer_callback(call.id, "❌ Недостаточно ⭐", show_alert=True)
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET stars = stars - ? WHERE id = ?", (amount, user['id']))
        cur.execute("UPDATE fines SET status='paid', paid_at=CURRENT_TIMESTAMP "
                    "WHERE user_id = ? AND status='active'", (user['id'],))
        cur.execute(
            "INSERT INTO transactions (user_id, amount, type, description) "
            "VALUES (?, ?, 'fine', 'Оплата штрафа')", (user['id'], -amount))
    safe_answer_callback(call.id, "✅ Штраф оплачен!")
    safe_send_message(tg_id, "✅ Штраф оплачен! Доступ восстановлен.")
    show_main_menu(tg_id)


@bot.callback_query_handler(func=lambda c: c.data == 'fine_appeal')
def cb_fine_appeal(call):
    for a in ADMIN_IDS:
        safe_send_message(a, f"⚠️ Пользователь {call.from_user.id} обжалует штраф.")
    safe_answer_callback(call.id, "✅ Отправлено")
    safe_send_message(call.from_user.id, "✅ Заявка отправлена.")


# ==========================================================
#              ДОНАТ
# ==========================================================

def show_donate_menu(tg_id):
    user = get_user_by_tg_id(tg_id)
    if not user:
        safe_send_message(tg_id, "❌ /start")
        return
    text = (
        f"💎 <b>Донат меню</b>\n\n"
        f"💰 Баланс: {user.get('stars', 0)} ⭐\n"
        f"👑 Премиум: {'Да' if user.get('is_premium') else 'Нет'}\n\n"
        f"Выбери тариф:"
    )
    safe_send_message(tg_id, text, reply_markup=donate_kb(), parse_mode='HTML')


@bot.callback_query_handler(func=lambda c: c.data.startswith('donate_') and c.data != 'donate_')
def cb_donate(call):
    tg_id = call.from_user.id
    try:
        plan_id = int(call.data.split('_')[1])
    except (ValueError, IndexError):
        return
    plan = PREMIUM_PLANS.get(plan_id)
    if not plan:
        safe_answer_callback(call.id, "❌ Тариф не найден")
        return
    user = get_user_by_tg_id(tg_id)
    if not user:
        return
    if user.get('stars', 0) < plan['stars']:
        safe_answer_callback(call.id, f"❌ Нужно {plan['stars']}⭐, у тебя {user.get('stars', 0)}",
                             show_alert=True)
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET stars = stars - ? WHERE id = ?", (plan['stars'], user['id']))
        if user.get('is_premium') and user.get('premium_until'):
            cur.execute('''
                UPDATE users SET premium_until = datetime(premium_until, '+' || ? || ' days')
                WHERE id = ?
            ''', (plan['days'], user['id']))
        else:
            cur.execute('''
                UPDATE users SET is_premium = 1,
                    premium_until = datetime('now', '+' || ? || ' days')
                WHERE id = ?
            ''', (plan['days'], user['id']))
        cur.execute('''
            INSERT INTO premium_purchases (user_id, duration_days, amount_stars, amount_rub)
            VALUES (?, ?, ?, ?)
        ''', (user['id'], plan['days'], plan['stars'], plan['rub']))
        cur.execute('''
            INSERT INTO transactions (user_id, amount, type, description)
            VALUES (?, ?, 'premium', ?)
        ''', (user['id'], -plan['stars'], f"Премиум {plan['name']}"))
    safe_answer_callback(call.id, f"✅ Премиум {plan['name']} активирован!")
    safe_send_message(tg_id, f"🎉 Premium на {plan['name']} активирован!")
    show_donate_menu(tg_id)


# ==========================================================
#              РЕДАКТИРОВАНИЕ ПРОФИЛЯ
# ==========================================================

@bot.callback_query_handler(func=lambda c: c.data in
                           ('edit_name', 'edit_age', 'edit_city', 'edit_about', 'edit_photo'))
def cb_edit_field(call):
    tg_id = call.from_user.id
    field = call.data.split('_', 1)[1]
    prompts = {
        'name': "Введи новое имя (2–50):",
        'age': "Введи новый возраст (14–100):",
        'city': "Введи новый город:",
        'about': "Новое описание (до 500):",
        'photo': "Пришли новое фото (/cancel — отмена):",
    }
    with states_lock:
        user_states[tg_id] = {'state': f'edit_{field}'}
    safe_answer_callback(call.id)
    safe_send_message(tg_id, prompts[field])


@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    tg_id = message.from_user.id
    with states_lock:
        user_states.pop(tg_id, None)
    safe_send_message(tg_id, "❌ Отменено. /menu")
    show_main_menu(tg_id)


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state', '').startswith('edit_'))
def process_edit_text(message):
    tg_id = message.from_user.id
    state = user_states.get(tg_id, {}).get('state', '')
    field = state.replace('edit_', '')
    text = (message.text or "").strip()

    if field == 'name':
        if not (2 <= len(text) <= 50):
            safe_send_message(tg_id, "❌ 2–50 символов.")
            return
        db_field, value = 'name', text
    elif field == 'age':
        try:
            value = int(text)
        except ValueError:
            safe_send_message(tg_id, "❌ Введи число.")
            return
        if not (14 <= value <= 100):
            safe_send_message(tg_id, "❌ 14–100.")
            return
        db_field = 'age'
    elif field == 'city':
        if text not in BASHKIR_CITIES:
            safe_send_message(tg_id, "❌ Город не найден.")
            return
        db_field, value = 'city', text
    elif field == 'about':
        if len(text) > 500:
            safe_send_message(tg_id, "❌ Максимум 500.")
            return
        db_field, value = 'about', text
    else:
        return

    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {db_field} = ? WHERE tg_id = ?", (value, tg_id))
    with states_lock:
        user_states.pop(tg_id, None)
    safe_send_message(tg_id, f"✅ Обновлено!")
    show_profile(tg_id)


@bot.message_handler(content_types=['photo'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'edit_photo')
def process_edit_photo(message):
    tg_id = message.from_user.id
    if not message.photo:
        return
    file_id = message.photo[-1].file_id
    with get_conn() as conn:
        conn.execute("UPDATE users SET photo_file_id = ? WHERE tg_id = ?", (file_id, tg_id))
    with states_lock:
        user_states.pop(tg_id, None)
    safe_send_message(tg_id, "✅ Фото обновлено!")
    show_profile(tg_id)


@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') in ('set_age_min', 'set_age_max'))
def process_set_age(message):
    tg_id = message.from_user.id
    state = user_states.get(tg_id, {}).get('state')
    try:
        val = int((message.text or "").strip())
    except ValueError:
        safe_send_message(tg_id, "❌ Введи число.")
        return
    if not (14 <= val <= 100):
        safe_send_message(tg_id, "❌ 14–100.")
        return
    if state == 'set_age_min':
        with get_conn() as conn:
            conn.execute("UPDATE users SET looking_for_age_min = ? WHERE tg_id = ?", (val, tg_id))
        with states_lock:
            user_states[tg_id] = {'state': 'set_age_max'}
        safe_send_message(tg_id, "Теперь максимальный возраст (14–100):")
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT looking_for_age_min FROM users WHERE tg_id = ?", (tg_id,))
        row = cur.fetchone()
        if row and val < row[0]:
            safe_send_message(tg_id, f"❌ Минимум {row[0]}")
            return
        conn.execute("UPDATE users SET looking_for_age_max = ? WHERE tg_id = ?", (val, tg_id))
    with states_lock:
        user_states.pop(tg_id, None)
    safe_send_message(tg_id, "✅ Обновлено.")
    show_search_settings(tg_id)


# ==========================================================
#              ЛАЙКИ / ЧАТЫ / УВЕДОМЛЕНИЯ
# ==========================================================

def show_matches(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute('''SELECT u.* FROM users u
                       JOIN reactions r ON u.id = r.user_id
                       WHERE r.target_id = ? AND r.reaction = 'like' ''', (user_id,))
        matches = [dict_from_row(r) for r in cur.fetchall()]
    if not matches:
        safe_send_message(tg_id, "😔 Пока нет лайков.")
        return
    text = "💕 <b>Тебе понравились:</b>\n\n"
    for m in matches:
        text += f"👤 {escape_html(m['name'])}, {m['age']} — #{m['id']:05d}\n"
    safe_send_message(tg_id, text, parse_mode='HTML')


def show_chats(tg_id):
    user_id = get_user_id_by_tg(tg_id)
    if not user_id:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM chats WHERE user1_id = ? OR user2_id = ?",
                    (user_id, user_id))
        chats = [dict_from_row(r) for r in cur.fetchall()]
    if not chats:
        safe_send_message(tg_id, "💭 У тебя пока нет чатов.")
        return
    text = "💬 <b>Твои чаты:</b>\n\n"
    for ch in chats:
        other_id = ch['user2_id'] if ch['user1_id'] == user_id else ch['user1_id']
        other = get_user_by_id(other_id)
        if other:
            text += f"👤 {escape_html(other['name'])} — #{other_id:05d}\n"
    safe_send_message(tg_id, text, parse_mode='HTML')


def show_notifications(tg_id):
    notifs = get_unread_notifications(tg_id)
    if not notifs:
        safe_send_message(tg_id, "📬 Нет новых уведомлений.")
        return
    lines = []
    for n in notifs:
        from_name = escape_html((n.get('from_name') or "Кто-то").strip() or "Кто-то")
        ntype = n.get('type')
        msg = escape_html((n.get('message') or "").strip())
        if ntype == 'like':
            lines.append(f"❤️ {from_name} лайкнул(а) тебя!")
        elif ntype == 'mutual_like':
            lines.append(f"💕 Взаимный лайк с {from_name}!")
        elif ntype == 'message':
            lines.append(f"💬 {from_name}: {msg}" if msg else f"💬 от {from_name}")
        else:
            lines.append(f"❔ {from_name}: {msg}" if msg else f"❔ от {from_name}")
    mark_notifications_read(tg_id)
    safe_send_message(tg_id, "📬 <b>Уведомления:</b>\n\n" + "\n\n".join(lines),
                      parse_mode='HTML')


# ==========================================================
#              УНИВЕРСАЛЬНЫЙ CALLBACK
# ==========================================================

# ВАЖНО: сначала регистрируем referral- и admin-хендлеры,
# потому что ниже идёт catch-all хендлер func=lambda c: True.
# telebot использует ПЕРВЫЙ совпавший хендлер в порядке регистрации.
# Если catch-all зарегистрируется раньше — все кнопки админки
# и рефералки будут перехвачены им и ответят "Неизвестное действие".
ref_module.register_referral_handlers(bot)
admin_module.register_admin_handlers(bot, user_states, states_lock)


@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    tg_id = call.from_user.id
    if tg_id < 0 or not call.message:
        return
    data = call.data or ""

    u = get_user_by_tg_id(tg_id)
    if u and u.get('is_banned') == 1 and not is_admin(tg_id):
        safe_answer_callback(call.id, "🚫 Вы забанены", show_alert=True)
        return

    # Простые действия
    simple = {
        'menu': lambda: show_main_menu(tg_id),
        'search': lambda: send_next_profile(tg_id),
        'profile': lambda: show_profile(tg_id),
        'edit': lambda: edit_profile(tg_id),
        'matches': lambda: show_matches(tg_id),
        'chats': lambda: show_chats(tg_id),
        'notifications': lambda: show_notifications(tg_id),
        'donate': lambda: show_donate_menu(tg_id),
        'search_settings': lambda: show_search_settings(tg_id),
    }
    if data in simple:
        safe_answer_callback(call.id)
        try:
            simple[data]()
        except Exception as e:
            logger.error(f"callback {data}: {e}")
        return

    if data == 'reset_search':
        safe_answer_callback(call.id)
        with get_conn() as conn:
            conn.execute('''UPDATE users SET looking_for_age_min=14, looking_for_age_max=100,
                            looking_for_gender='всех', search_city=NULL WHERE tg_id = ?''', (tg_id,))
        safe_send_message(tg_id, "✅ Настройки сброшены.")
        show_search_settings(tg_id)
        return

    if data == 'set_age':
        safe_answer_callback(call.id)
        with states_lock:
            user_states[tg_id] = {'state': 'set_age_min'}
        safe_send_message(tg_id, "Введи минимальный возраст (14–100):")
        return

    if data == 'set_gender':
        safe_answer_callback(call.id)
        safe_send_message(tg_id, "Кого искать?", reply_markup=gender_search_kb())
        return

    if data.startswith('sg_'):
        safe_answer_callback(call.id)
        mapping = {'sg_male': 'мужской', 'sg_female': 'женский', 'sg_all': 'всех'}
        gender = mapping.get(data)
        if gender:
            with get_conn() as conn:
                conn.execute("UPDATE users SET looking_for_gender = ? WHERE tg_id = ?",
                             (gender, tg_id))
            safe_send_message(tg_id, f"✅ Пол: {gender}")
            show_search_settings(tg_id)
        return

    if data == 'set_city':
        safe_answer_callback(call.id)
        safe_send_message(tg_id, "Выбери город:", reply_markup=cities_kb())
        return

    if data.startswith('sc_'):
        safe_answer_callback(call.id)
        city = data[3:]
        with get_conn() as conn:
            if city == 'all':
                conn.execute("UPDATE users SET search_city = NULL WHERE tg_id = ?", (tg_id,))
                safe_send_message(tg_id, "✅ Все города")
            else:
                conn.execute("UPDATE users SET search_city = ? WHERE tg_id = ?", (city, tg_id))
                safe_send_message(tg_id, f"✅ {city}")
        show_search_settings(tg_id)
        return

    if data.startswith('report_'):
        try:
            target_id = int(data.split('_', 1)[1])
        except (ValueError, IndexError):
            return
        with states_lock:
            user_states[tg_id] = {'state': 'report_reason', 'target_id': target_id}
        safe_answer_callback(call.id)
        safe_send_message(tg_id, "⚠️ Напиши причину жалобы (мин. 3 символа):")
        return

    if data.startswith(('like_', 'dislike_', 'draft_')):
        handle_reaction(call, data)
        return

    safe_answer_callback(call.id, "❓ Неизвестное действие")


def handle_reaction(call, data):
    tg_id = call.from_user.id
    if not is_registered(tg_id):
        safe_answer_callback(call.id, "❌ Сначала /start")
        return
    if is_user_fined(tg_id):
        safe_answer_callback(call.id, "❌ Есть неоплаченный штраф", show_alert=True)
        return
    try:
        action, tid_str = data.split('_', 1)
        target_id = int(tid_str)
    except (ValueError, IndexError):
        safe_answer_callback(call.id, "❌ Ошибка")
        return
    user_id = get_user_id_by_tg(tg_id)
    if not user_id or user_id == target_id:
        safe_answer_callback(call.id, "❌ Нельзя")
        return

    is_new = False
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM reactions WHERE user_id = ? AND target_id = ?",
                    (user_id, target_id))
        if cur.fetchone():
            cur.execute("UPDATE reactions SET reaction = ? WHERE user_id = ? AND target_id = ?",
                        (action, user_id, target_id))
        else:
            cur.execute("INSERT INTO reactions (user_id, target_id, reaction) VALUES (?, ?, ?)",
                        (user_id, target_id, action))
            is_new = True

    safe_answer_callback(call.id, "✅ Учтено!")

    if action == 'like' and is_new:
        target = get_user_by_id(target_id)
        sender = get_user_by_id(user_id)
        if target and sender:
            sender_name = escape_html((sender.get('name') or '').strip() or f"ID {user_id}")
            if call.from_user.username:
                user_link = f'<a href="https://t.me/{call.from_user.username}">@{call.from_user.username}</a>'
            else:
                user_link = f'<a href="tg://user?id={tg_id}">{sender_name}</a>'
            add_notification(target_id, user_id, 'like', f"{sender_name} лайкнул(а) тебя!")
            notify_user(
                target['tg_id'],
                f'❤️ <b>{sender_name}</b> лайкнул(а) тебя!\nЮзер: {user_link}',
                parse_mode='HTML'
            )
            # Взаимный лайк
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM reactions WHERE user_id = ? AND target_id = ? AND reaction = 'like'",
                            (target_id, user_id))
                if cur.fetchone():
                    u1, u2 = sorted([user_id, target_id])
                    conn.execute("INSERT OR IGNORE INTO chats (user1_id, user2_id) VALUES (?, ?)",
                                 (u1, u2))
                    t_name = escape_html((target.get('name') or '').strip() or f"ID {target_id}")
                    add_notification(user_id, target_id, 'mutual_like', f"Взаимный лайк с {t_name}!")
                    add_notification(target_id, user_id, 'mutual_like', f"Взаимный лайк с {sender_name}!")
                    notify_user(user_id, f'💕 Взаимный лайк с <b>{t_name}</b>!',
                                parse_mode='HTML')
                    notify_user(target['tg_id'], f'💕 Взаимный лайк с <b>{sender_name}</b>!',
                                parse_mode='HTML')

    try:
        send_next_profile(tg_id)
    except Exception as e:
        logger.error(f"next profile: {e}")


# ==========================================================
#              ПРОЧИЕ КОМАНДЫ
# ==========================================================

@bot.message_handler(content_types=['text'],
                     func=lambda m: m.from_user.id > 0 and
                     user_states.get(m.from_user.id, {}).get('state') == 'report_reason')
def process_report_reason(message):
    tg_id = message.from_user.id
    with states_lock:
        st = user_states.get(tg_id, {})
        target_id = st.get('target_id')
        user_states.pop(tg_id, None)
    reason = (message.text or "").strip()
    if len(reason) < 3:
        safe_send_message(tg_id, "❌ Слишком короткая причина.")
        return
    if not target_id:
        return
    reporter_id = get_user_id_by_tg(tg_id)
    if not reporter_id:
        return
    with get_conn() as conn:
        conn.execute("INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)",
                     (reporter_id, target_id, reason))
    safe_send_message(tg_id, "✅ Жалоба отправлена.")
    for a in ADMIN_IDS:
        safe_send_message(a, f"⚠️ Новая жалоба от {tg_id} на ID {target_id}\nПричина: {reason}")


@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    show_profile(message.from_user.id)


@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    show_main_menu(message.from_user.id)


# ==========================================================
#              ЗАПУСК
# ==========================================================

if __name__ == '__main__':
    try:
        bot.remove_webhook()
    except Exception:
        pass
    logger.info("🚀 Бот запущен...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20, long_polling_timeout=25)
        except Exception as e:
            logger.error(f"polling error: {e}")
            time.sleep(5)