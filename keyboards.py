from telebot import types
from config import BASHKIR_CITIES

TAGS_LIST = [
    'Музыка', 'Спорт', 'Кино', 'Книги', 'Путешествия', 'Игры',
    'Фотография', 'Рисование', 'Танцы', 'Готовка', 'Йога', 'Программирование'
]

PREMIUM_PLANS = {
    1: {"name": "1 день", "stars": 9, "days": 1, "rub": 9},
    2: {"name": "1 неделя", "stars": 49, "days": 7, "rub": 49},
    4: {"name": "3 месяца", "stars": 199, "days": 90, "rub": 199},
    5: {"name": "6 месяцев", "stars": 349, "days": 180, "rub": 349},
    6: {"name": "12 месяцев", "stars": 599, "days": 365, "rub": 599},
}


# ---------- РЕГИСТРАЦИЯ ----------

def gender_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👨 Мужской", callback_data="gender_male"),
        types.InlineKeyboardButton("👩 Женский", callback_data="gender_female"),
    )
    return kb


def tags_kb(selected=None):
    selected = selected or []
    kb = types.InlineKeyboardMarkup(row_width=3)
    for tag in TAGS_LIST:
        label = f"✅ {tag}" if tag in selected else tag
        kb.add(types.InlineKeyboardButton(label, callback_data=f"tag_{tag}"))
    kb.add(types.InlineKeyboardButton("✅ Готово", callback_data="tags_done"))
    return kb


def subscription_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📢 Подписаться", url="https://t.me/tavejr7"))
    kb.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription"))
    return kb


# ---------- ГЛАВНОЕ МЕНЮ ----------

def main_menu_kb(is_admin=False, notif_count=0):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Искать анкеты", callback_data="search"),
        types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
    )
    kb.add(
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit"),
        types.InlineKeyboardButton("⚙️ Настройки поиска", callback_data="search_settings"),
    )
    kb.add(
        types.InlineKeyboardButton("💕 Мои лайки", callback_data="matches"),
        types.InlineKeyboardButton("💬 Мои чаты", callback_data="chats"),
    )
    kb.add(
        types.InlineKeyboardButton(f"📬 Уведомления ({notif_count})", callback_data="notifications"),
        types.InlineKeyboardButton("💎 Донат", callback_data="donate"),
    )
    kb.add(types.InlineKeyboardButton("🎁 Реферальная программа", callback_data="referral"))
    if is_admin:
        kb.add(types.InlineKeyboardButton("🔐 Админ-панель", callback_data="admin"))
    return kb


# ---------- ПРОФИЛЬ ----------

def profile_kb(referral_link):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔗 Моя реферальная ссылка", url=referral_link),
        types.InlineKeyboardButton("🎁 Реферальная программа", callback_data="referral"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit"),
        types.InlineKeyboardButton("💎 Донат", callback_data="donate"),
        types.InlineKeyboardButton("📋 Меню", callback_data="menu"),
    )
    return kb


def edit_profile_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("✏️ Имя", callback_data="edit_name"),
        types.InlineKeyboardButton("✏️ Возраст", callback_data="edit_age"),
        types.InlineKeyboardButton("✏️ Город", callback_data="edit_city"),
        types.InlineKeyboardButton("✏️ О себе", callback_data="edit_about"),
        types.InlineKeyboardButton("📸 Фото", callback_data="edit_photo"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="menu"),
    )
    return kb


# ---------- ПОИСК ----------

def profile_card_kb(target_id):
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{target_id}"),
        types.InlineKeyboardButton("👎 Дизлайк", callback_data=f"dislike_{target_id}"),
        types.InlineKeyboardButton("📝 В черновики", callback_data=f"draft_{target_id}"),
    )
    kb.add(
        types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_{target_id}"),
        types.InlineKeyboardButton("📋 Меню", callback_data="menu"),
    )
    return kb


def search_settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🎂 Изменить возраст", callback_data="set_age"),
        types.InlineKeyboardButton("⚥ Изменить пол", callback_data="set_gender"),
        types.InlineKeyboardButton("🏙️ Изменить город", callback_data="set_city"),
        types.InlineKeyboardButton("🔄 Сбросить", callback_data="reset_search"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="menu"),
    )
    return kb


def gender_search_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("👨 Мужской", callback_data="sg_male"),
        types.InlineKeyboardButton("👩 Женский", callback_data="sg_female"),
        types.InlineKeyboardButton("👥 Все", callback_data="sg_all"),
    )
    return kb


def cities_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in BASHKIR_CITIES:
        kb.add(types.InlineKeyboardButton(c, callback_data=f"sc_{c}"))
    kb.add(types.InlineKeyboardButton("🌍 Все города", callback_data="sc_all"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="search_settings"))
    return kb


# ---------- ДОНАТ ----------

def donate_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for pid, plan in PREMIUM_PLANS.items():
        btn = f"{plan['name']} — {plan['stars']}⭐ / {plan['rub']}₽"
        kb.add(types.InlineKeyboardButton(btn, callback_data=f"donate_{pid}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
    return kb


# ---------- ШТРАФЫ ----------

def fine_kb(total_fine):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💳 Оплатить штраф", callback_data=f"fine_pay_{total_fine}"),
        types.InlineKeyboardButton("💰 Пополнить", callback_data="donate"),
    )
    kb.add(types.InlineKeyboardButton("❌ Обжаловать", callback_data="fine_appeal"))
    return kb


# ---------- РЕФЕРАЛЬНАЯ СИСТЕМА ⭐ ----------

def referral_kb(referral_link):
    """
    referral_link — полная реферальная ссылка вида https://t.me/bot_name?start=ref_X
    """
    kb = types.InlineKeyboardMarkup(row_width=1)
    # Кнопка "Поделиться" использует ту же ссылку (Telegram сам корректно обработает)
    kb.add(types.InlineKeyboardButton("📤 Поделиться", url=referral_link))
    kb.add(types.InlineKeyboardButton("🔗 Скопировать ссылку", callback_data="copy_ref"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
    return kb


# ---------- АДМИН-ПАНЕЛЬ ----------

def admin_menu_kb(level=2):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
    )
    kb.add(
        types.InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_reports"),
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
    )
    if level >= 2:
        kb.add(
            types.InlineKeyboardButton("🔍 Поиск юзера", callback_data="admin_find"),
            types.InlineKeyboardButton("🎁 Выдать премиум", callback_data="admin_premium"),
        )
    if level >= 3:
        kb.add(
            types.InlineKeyboardButton("👑 Управление админами", callback_data="admin_admins"),
        )
    kb.add(types.InlineKeyboardButton("📋 Меню", callback_data="menu"))
    return kb


def admin_user_card_kb(target_id, is_banned):
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_banned:
        kb.add(types.InlineKeyboardButton("✅ Разбанить", callback_data=f"adm_unban_{target_id}"))
    else:
        kb.add(types.InlineKeyboardButton("🚫 Забанить", callback_data=f"adm_bonly_{target_id}"))
    kb.add(
        types.InlineKeyboardButton("⚠️ Штраф", callback_data=f"adm_fine_{target_id}"),
        types.InlineKeyboardButton("💰 Звёзды", callback_data=f"adm_stars_{target_id}"),
    )
    kb.add(
        types.InlineKeyboardButton("👑 Премиум", callback_data=f"adm_giveprem_{target_id}"),
        types.InlineKeyboardButton("✅ Верификация", callback_data=f"adm_verify_{target_id}"),
    )
    kb.add(types.InlineKeyboardButton("🔙 К жалобам", callback_data="admin_reports"))
    return kb


def report_action_kb(reported_id, report_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🚫 Забанить", callback_data=f"adm_ban_{reported_id}_{report_id}"),
        types.InlineKeyboardButton("✅ Отклонить", callback_data=f"adm_rej_{report_id}"),
    )
    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data=f"adm_view_{reported_id}"))
    return kb


def reports_nav_kb(page, total_pages):
    kb = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm_rep_page_{page-1}"))
    buttons.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        buttons.append(types.InlineKeyboardButton("➡️", callback_data=f"adm_rep_page_{page+1}"))
    kb.add(*buttons)
    return kb


def premium_duration_kb(target_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for pid, plan in PREMIUM_PLANS.items():
        kb.add(types.InlineKeyboardButton(
            f"{plan['name']} ({plan['days']}д)",
            callback_data=f"adm_prem_{target_id}_{plan['days']}"
        ))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"adm_view_{target_id}"))
    return kb