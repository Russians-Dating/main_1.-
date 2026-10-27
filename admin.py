import time
from telebot import types
from config import ADMIN_IDS, logger, BASHKIR_CITIES
from database import (
    get_conn, dict_from_row, get_user_by_tg_id, get_user_by_id,
    get_user_id_by_tg, is_admin, get_admin_level, log_admin_action,
    notify_user
)
from keyboards import (
    admin_menu_kb, admin_user_card_kb, report_action_kb,
    reports_nav_kb, premium_duration_kb
)
from utils import safe_send_message, safe_send_photo, safe_answer_callback, escape_html

user_states = {}  # будет установлено через register_handlers


def register_admin_handlers(bot, states, states_lock):
    global user_states
    user_states = states

    # ---------- Команды ----------

    @bot.message_handler(commands=['admin'])
    def cmd_admin(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            safe_send_message(tg_id, "❌ У вас нет прав администратора.")
            return
        level = get_admin_level(tg_id)
        safe_send_message(
            tg_id,
            f"🔐 <b>Админ-панель</b> (Уровень {level})\n\n"
            f"💡 <b>Команды:</b>\n"
            f"/ban &lt;tg_id&gt; — забанить\n"
            f"/unban &lt;tg_id&gt; — разбанить\n"
            f"/broadcast &lt;текст&gt; — рассылка",
            reply_markup=admin_menu_kb(level),
            parse_mode='HTML'
        )

    @bot.message_handler(commands=['ban'])
    def cmd_ban(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            safe_send_message(tg_id, "❌ Нет прав.")
            return
        args = message.text.split()
        if len(args) < 2:
            safe_send_message(tg_id, "Использование: /ban <tg_id>")
            return
        try:
            target_tg = int(args[1])
        except ValueError:
            safe_send_message(tg_id, "❌ tg_id должен быть числом.")
            return
        target = get_user_by_tg_id(target_tg)
        if not target:
            safe_send_message(tg_id, "❌ Пользователь не найден.")
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (target_tg,))
        log_admin_action(tg_id, 'ban', target['id'], f'/ban {target_tg}')
        notify_user(target_tg, "🚫 Вы были забанены администрацией.")
        safe_send_message(tg_id, f"✅ {target['name']} забанен.")

    @bot.message_handler(commands=['unban'])
    def cmd_unban(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            safe_send_message(tg_id, "❌ Нет прав.")
            return
        args = message.text.split()
        if len(args) < 2:
            safe_send_message(tg_id, "Использование: /unban <tg_id>")
            return
        try:
            target_tg = int(args[1])
        except ValueError:
            safe_send_message(tg_id, "❌ tg_id должен быть числом.")
            return
        target = get_user_by_tg_id(target_tg)
        if not target:
            safe_send_message(tg_id, "❌ Пользователь не найден.")
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_banned = 0 WHERE tg_id = ?", (target_tg,))
        log_admin_action(tg_id, 'unban', target['id'], f'/unban {target_tg}')
        notify_user(target_tg, "✅ Вы разбанены.")
        safe_send_message(tg_id, f"✅ {target['name']} разбанен.")

    @bot.message_handler(commands=['broadcast'])
    def cmd_broadcast(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            safe_send_message(tg_id, "❌ Нет прав.")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            safe_send_message(tg_id, "📢 Использование: /broadcast <текст>")
            return
        broadcast_to_all(bot, tg_id, args[1].strip())

    # ---------- Callback-и ----------

    @bot.callback_query_handler(func=lambda c: c.data == 'admin')
    def cb_admin(call):
        tg_id = call.from_user.id
        if not is_admin(tg_id):
            safe_answer_callback(call.id, "❌ Нет прав")
            return
        safe_answer_callback(call.id)
        level = get_admin_level(tg_id)
        safe_send_message(
            tg_id,
            f"🔐 <b>Админ-панель</b> (Уровень {level})",
            reply_markup=admin_menu_kb(level),
            parse_mode='HTML'
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_stats')
    def cb_admin_stats(call):
        if not is_admin(call.from_user.id):
            safe_answer_callback(call.id, "❌ Нет прав")
            return
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users")
                total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM users WHERE is_registered = 1")
                registered = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
                banned = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
                premium = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM reactions WHERE reaction = 'like'")
                likes = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
                pending = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM referrals")
                referrals = cur.fetchone()[0]
            text = (
                f"📊 <b>Статистика</b>\n\n"
                f"👥 Всего: <b>{total}</b>\n"
                f"✅ Зарегистрировано: <b>{registered}</b>\n"
                f"👑 Premium: <b>{premium}</b>\n"
                f"🚫 Забанено: <b>{banned}</b>\n"
                f"❤️ Лайков: <b>{likes}</b>\n"
                f"⚠️ Жалоб в ожидании: <b>{pending}</b>\n"
                f"🎁 Рефералов: <b>{referrals}</b>"
            )
            safe_answer_callback(call.id)
            safe_send_message(call.from_user.id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"admin_stats error: {e}")
            safe_answer_callback(call.id, "❌ Ошибка")

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_users')
    def cb_admin_users(call):
        if not is_admin(call.from_user.id):
            safe_answer_callback(call.id, "❌ Нет прав")
            return
        safe_answer_callback(call.id)
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, tg_id, name, age, city, is_banned "
                    "FROM users ORDER BY id DESC LIMIT 20"
                )
                rows = cur.fetchall()
        except Exception as e:
            logger.error(f"admin_users error: {e}")
            return
        if not rows:
            safe_send_message(call.from_user.id, "Нет пользователей.")
            return
        for r in rows:
            status = "🚫" if r['is_banned'] else "✅"
            text = f"{status} <b>{escape_html(r['name'])}</b>, {r['age']} — {r['city']}\nID: #{r['id']:05d} | tg: <code>{r['tg_id']}</code>"
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("👤 Открыть", callback_data=f"adm_view_{r['id']}"))
            safe_send_message(call.from_user.id, text, reply_markup=kb, parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_reports')
    def cb_admin_reports(call):
        tg_id = call.from_user.id
        if not is_admin(tg_id):
            safe_answer_callback(call.id, "❌ Нет прав")
            return
        logger.info(f"cb_admin_reports called by {tg_id}")
        safe_answer_callback(call.id)
        try:
            show_admin_reports(bot, tg_id, page=0)
        except Exception as e:
            logger.error(f"show_admin_reports failed: {e}")
            safe_send_message(tg_id, f"❌ Ошибка при загрузке жалоб: {e}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_rep_page_'))
    def cb_adm_rep_page(call):
        if not is_admin(call.from_user.id):
            return
        try:
            page = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            page = 0
        safe_answer_callback(call.id)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        show_admin_reports(bot, call.from_user.id, page=page)

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_rej_'))
    def cb_adm_rej(call):
        if not is_admin(call.from_user.id):
            return
        try:
            report_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute("UPDATE reports SET status = 'rejected' WHERE id = ?", (report_id,))
        log_admin_action(call.from_user.id, 'report_reject', report_id, '')
        safe_answer_callback(call.id, "✅ Жалоба отклонена")
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=(call.message.text or "") + "\n\n✅ ОТКЛОНЕНА"
            )
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_ban_'))
    def cb_adm_ban(call):
        if not is_admin(call.from_user.id):
            return
        parts = call.data.split('_')
        try:
            target_id = int(parts[2])
            report_id = int(parts[3]) if len(parts) > 3 else None
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (target_id,))
            if report_id:
                conn.execute("UPDATE reports SET status = 'resolved' WHERE id = ?", (report_id,))
        log_admin_action(call.from_user.id, 'ban', target_id, f'Жалоба #{report_id}')
        target = get_user_by_id(target_id)
        if target:
            notify_user(target['tg_id'], "🚫 Вы были забанены администрацией.")
        safe_answer_callback(call.id, "🚫 Забанен", show_alert=True)
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=(call.message.text or "") + "\n\n🚫 ЗАБАНЕН"
            )
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_view_'))
    def cb_adm_view(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        safe_answer_callback(call.id)
        show_admin_user_card(bot, call.from_user.id, target_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_bonly_'))
    def cb_adm_bonly(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (target_id,))
        log_admin_action(call.from_user.id, 'ban', target_id, 'Ручной бан')
        target = get_user_by_id(target_id)
        if target:
            notify_user(target['tg_id'], "🚫 Вы были забанены администрацией.")
        safe_answer_callback(call.id, "🚫 Забанен", show_alert=True)
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        show_admin_user_card(bot, call.from_user.id, target_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_unban_'))
    def cb_adm_unban(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (target_id,))
        log_admin_action(call.from_user.id, 'unban', target_id, '')
        target = get_user_by_id(target_id)
        if target:
            notify_user(target['tg_id'], "✅ Вы разбанены администрацией.")
        safe_answer_callback(call.id, "✅ Разбанен", show_alert=True)
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        show_admin_user_card(bot, call.from_user.id, target_id)

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_broadcast')
    def cb_admin_broadcast(call):
        if not is_admin(call.from_user.id):
            return
        with states_lock:
            user_states[call.from_user.id] = {'state': 'broadcast_text'}
        safe_answer_callback(call.id)
        safe_send_message(
            call.from_user.id,
            "📢 Отправь текст для рассылки следующим сообщением.\nДля отмены: /cancel"
        )

    # ---------- Штраф / Звёзды / Премиум ----------

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_stars_'))
    def cb_adm_stars(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with states_lock:
            user_states[call.from_user.id] = {'state': 'adm_stars_amount', 'target_id': target_id}
        safe_answer_callback(call.id)
        safe_send_message(call.from_user.id, "💰 Сколько звёзд выдать? (можно отрицательное)")

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_fine_'))
    def cb_adm_fine(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with states_lock:
            user_states[call.from_user.id] = {'state': 'adm_fine_amount', 'target_id': target_id}
        safe_answer_callback(call.id)
        safe_send_message(call.from_user.id, "⚠️ Введи сумму штрафа в ⭐:")

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_verify_'))
    def cb_adm_verify(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (target_id,))
        log_admin_action(call.from_user.id, 'verify', target_id, '')
        safe_answer_callback(call.id, "✅ Верифицирован", show_alert=True)
        target = get_user_by_id(target_id)
        if target:
            notify_user(target['tg_id'], "✅ Ваш профиль верифицирован!")
        show_admin_user_card(bot, call.from_user.id, target_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_giveprem_'))
    def cb_adm_giveprem(call):
        if not is_admin(call.from_user.id):
            return
        try:
            target_id = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            return
        safe_answer_callback(call.id)
        safe_send_message(
            call.from_user.id,
            "👑 Выбери длительность Premium:",
            reply_markup=premium_duration_kb(target_id)
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith('adm_prem_'))
    def cb_adm_premium_days(call):
        if not is_admin(call.from_user.id):
            return
        try:
            parts = call.data.split('_')
            target_id = int(parts[2])
            days = int(parts[3])
        except (ValueError, IndexError):
            return
        with get_conn() as conn:
            conn.execute('''
                UPDATE users SET
                    is_premium = 1,
                    premium_until = CASE
                        WHEN premium_until IS NOT NULL AND premium_until > datetime('now')
                            THEN datetime(premium_until, '+' || ? || ' days')
                        ELSE datetime('now', '+' || ? || ' days')
                    END
                WHERE id = ?
            ''', (days, days, target_id))
        log_admin_action(call.from_user.id, 'premium', target_id, f'+{days}д')
        target = get_user_by_id(target_id)
        if target:
            notify_user(target['tg_id'], f"👑 Вам выдан Premium на {days} дн.!")
        safe_answer_callback(call.id, f"✅ +{days} дней Premium", show_alert=True)
        with states_lock:
            user_states.pop(call.from_user.id, None)
        show_admin_user_card(bot, call.from_user.id, target_id)

    # ---------- Поиск юзера / Выдать премиум / Управление админами ----------

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_find')
    def cb_admin_find(call):
        if not is_admin(call.from_user.id):
            return
        safe_answer_callback(call.id)
        with states_lock:
            user_states[call.from_user.id] = {'state': 'adm_find_user'}
        safe_send_message(
            call.from_user.id,
            "🔍 Введи Telegram ID пользователя для поиска:"
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_premium')
    def cb_admin_premium(call):
        if not is_admin(call.from_user.id):
            return
        safe_answer_callback(call.id)
        with states_lock:
            user_states[call.from_user.id] = {'state': 'adm_give_premium'}
        safe_send_message(
            call.from_user.id,
            "👑 Введи Telegram ID пользователя, которому выдать Premium:"
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'admin_admins')
    def cb_admin_admins(call):
        if get_admin_level(call.from_user.id) < 2:
            safe_answer_callback(call.id, "⛔ Недостаточно прав", show_alert=True)
            return
        safe_answer_callback(call.id)
        show_admins_list(bot, call.from_user.id)

    # ---------- Текстовые состояния ----------

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'broadcast_text')
    def process_broadcast_text(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            with states_lock:
                user_states.pop(tg_id, None)
            return
        text = (message.text or "").strip()
        if not text:
            safe_send_message(tg_id, "❌ Пустой текст. Или /cancel")
            return
        with states_lock:
            user_states.pop(tg_id, None)
        broadcast_to_all(bot, tg_id, text)

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'adm_stars_amount')
    def process_adm_stars(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            return
        with states_lock:
            st = user_states.get(tg_id, {})
            target_id = st.get('target_id')
        try:
            amount = int((message.text or "").strip())
        except ValueError:
            safe_send_message(tg_id, "❌ Введи число.")
            return
        if not target_id:
            with states_lock:
                user_states.pop(tg_id, None)
            return
        with get_conn() as conn:
            conn.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (amount, target_id))
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) "
                "VALUES (?, ?, 'admin_gift', ?)",
                (target_id, amount, f'Админ: {amount}⭐')
            )
        log_admin_action(tg_id, 'stars', target_id, f'{amount}')
        with states_lock:
            user_states.pop(tg_id, None)
        target = get_user_by_id(target_id)
        if target:
            if amount > 0:
                notify_user(target['tg_id'], f"🎁 Вам начислено {amount} ⭐!")
            elif amount < 0:
                notify_user(target['tg_id'], f"⚠️ Списано {abs(amount)} ⭐.")
        safe_send_message(tg_id, f"✅ Баланс изменён на {amount} ⭐.")
        show_admin_user_card(bot, tg_id, target_id)

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'adm_fine_amount')
    def process_adm_fine_amount(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            return
        with states_lock:
            target_id = user_states.get(tg_id, {}).get('target_id')
        try:
            amount = int((message.text or "").strip())
        except ValueError:
            safe_send_message(tg_id, "❌ Введи число.")
            return
        if amount <= 0:
            safe_send_message(tg_id, "❌ Сумма > 0.")
            return
        with states_lock:
            user_states[tg_id] = {'state': 'adm_fine_reason', 'target_id': target_id, 'amount': amount}
        safe_send_message(tg_id, "📝 Укажи причину штрафа:")

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'adm_fine_reason')
    def process_adm_fine_reason(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            return
        with states_lock:
            st = user_states.get(tg_id, {})
            target_id = st.get('target_id')
            amount = st.get('amount')
        reason = (message.text or "").strip()
        if not reason:
            safe_send_message(tg_id, "❌ Причина не может быть пустой.")
            return
        admin_user = get_user_by_tg_id(tg_id)
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO fines (user_id, admin_id, amount, reason) VALUES (?, ?, ?, ?)",
                (target_id, admin_user['id'] if admin_user else 0, amount, reason)
            )
        log_admin_action(tg_id, 'fine', target_id, f'{amount}⭐: {reason}')
        with states_lock:
            user_states.pop(tg_id, None)
        target = get_user_by_id(target_id)
        if target:
            notify_user(
                target['tg_id'],
                f"🚨 Вам выписан штраф {amount} ⭐\nПричина: {reason}\nДля оплаты: /menu"
            )
        safe_send_message(tg_id, f"✅ Штраф {amount} ⭐ выписан.")
        show_admin_user_card(bot, tg_id, target_id)

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'adm_find_user')
    def process_adm_find_user(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            with states_lock:
                user_states.pop(tg_id, None)
            return
        raw = (message.text or "").strip().lstrip('@')
        with states_lock:
            user_states.pop(tg_id, None)
        try:
            target_tg = int(raw)
        except ValueError:
            safe_send_message(tg_id, "❌ Введи числовой Telegram ID.")
            return
        target = get_user_by_tg_id(target_tg)
        if not target:
            safe_send_message(tg_id, f"❌ Пользователь с tg_id <code>{target_tg}</code> не найден.")
            return
        show_admin_user_card(bot, tg_id, target['id'])

    @bot.message_handler(content_types=['text'],
                         func=lambda m: m.from_user.id > 0 and
                         user_states.get(m.from_user.id, {}).get('state') == 'adm_give_premium')
    def process_adm_give_premium(message):
        tg_id = message.from_user.id
        if not is_admin(tg_id):
            with states_lock:
                user_states.pop(tg_id, None)
            return
        raw = (message.text or "").strip().lstrip('@')
        try:
            target_tg = int(raw)
        except ValueError:
            safe_send_message(tg_id, "❌ Введи числовой Telegram ID.")
            return
        target = get_user_by_tg_id(target_tg)
        if not target:
            safe_send_message(tg_id, f"❌ Пользователь с tg_id <code>{target_tg}</code> не найден.")
            return
        with states_lock:
            user_states[tg_id] = {'state': 'adm_give_premium_days', 'target_id': target['id']}
        safe_send_message(
            tg_id,
            "👑 Выбери длительность Premium:",
            reply_markup=premium_duration_kb(target['id'])
        )


# ---------- Вспомогательные функции ----------

def show_admins_list(bot, admin_tg_id):
    try:
        with get_conn() as conn:
            cur = conn.execute('''
                SELECT id, tg_id, name, is_admin
                FROM users
                WHERE is_admin >= 1
                ORDER BY is_admin DESC, name ASC
            ''')
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"show_admins_list error: {e}")
        safe_send_message(admin_tg_id, "❌ Ошибка получения списка админов.")
        return

    if not rows:
        safe_send_message(admin_tg_id, "ℹ️ Администраторов не найдено.")
        return

    lines = ["👑 <b>Список администраторов:</b>\n"]
    for r in rows:
        role = "Гл. админ" if r['is_admin'] >= 2 else "Админ"
        lines.append(
            f"🆔 <code>{r['tg_id']}</code> — {escape_html(r['name'] or '?')} "
            f"({role}, ID:{r['id']})"
        )
    safe_send_message(admin_tg_id, "\n".join(lines), parse_mode='HTML')

def show_admin_reports(bot, tg_id, page=0, per_page=5):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
            total = cur.fetchone()[0]
            if total == 0:
                safe_send_message(tg_id, "✅ Жалоб в ожидании нет.")
                return
            offset = page * per_page
            cur.execute('''
                SELECT r.*,
                       u1.name as reporter_name, u1.tg_id as reporter_tg,
                       u2.name as reported_name, u2.tg_id as reported_tg
                FROM reports r
                LEFT JOIN users u1 ON r.reporter_id = u1.id
                LEFT JOIN users u2 ON r.reported_id = u2.id
                WHERE r.status = 'pending'
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?
            ''', (per_page, offset))
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"show_admin_reports error: {e}")
        return

    if not rows:
        safe_send_message(tg_id, "✅ Больше жалоб нет.")
        return

    total_pages = (total + per_page - 1) // per_page

    for r in rows:
        text = (
            f"⚠️ <b>Жалоба #{r['id']}</b>\n\n"
            f"👤 От: {escape_html(r.get('reporter_name') or '?')} (tg:{r.get('reporter_tg')})\n"
            f"🎯 На: {escape_html(r.get('reported_name') or '?')} "
            f"(ID:{r['reported_id']}, tg:{r.get('reported_tg')})\n"
            f"📝 Причина: {escape_html(r['reason'])}\n"
            f"📅 {r['created_at']}"
        )
        safe_send_message(
            tg_id, text,
            reply_markup=report_action_kb(r['reported_id'], r['id']),
            parse_mode='HTML'
        )

    safe_send_message(
        tg_id,
        f"📄 Страница {page+1} из {total_pages}",
        reply_markup=reports_nav_kb(page, total_pages)
    )


def show_admin_user_card(bot, admin_tg_id, target_id):
    target = get_user_by_id(target_id)
    if not target:
        safe_send_message(admin_tg_id, "❌ Пользователь не найден.")
        return

    tags_list = target.get('tags', '').split(',') if target.get('tags') else []
    tags_text = ", ".join(tags_list) if tags_list else "—"

    text = (
        f"👤 <b>Карточка пользователя</b>\n\n"
        f"🆔 ID: #{target['id']:05d}\n"
        f"🆔 TG: <code>{target['tg_id']}</code>\n"
        f"👤 Имя: {escape_html(target['name'])}\n"
        f"🎂 Возраст: {target['age']}\n"
        f"🏙️ Город: {target['city']}\n"
        f"⚥ Пол: {target.get('gender') or '—'}\n"
        f"🏷️ Интересы: {escape_html(tags_text)}\n"
        f"📝 О себе: {escape_html(target.get('about') or '—')}\n\n"
        f"💰 Баланс: {target.get('stars', 0)} ⭐\n"
        f"👑 Премиум: {'Да' if target.get('is_premium') else 'Нет'}\n"
        f"🚫 Бан: {'ДА' if target.get('is_banned') else 'нет'}\n"
        f"✅ Верификация: {'Да' if target.get('verified') else 'Нет'}\n"
        f"🎁 Рефералов: {target.get('referral_count', 0)}"
    )

    kb = admin_user_card_kb(target_id, target.get('is_banned'))

    sent = None
    if target.get('photo_file_id'):
        sent = safe_send_photo(admin_tg_id, photo=target['photo_file_id'],
                               caption=text, reply_markup=kb, parse_mode='HTML')
    if not sent:
        safe_send_message(admin_tg_id, text, reply_markup=kb, parse_mode='HTML')


def broadcast_to_all(bot, admin_tg_id, text):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT tg_id FROM users WHERE is_banned = 0 AND is_registered = 1")
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"broadcast fetch error: {e}")
        safe_send_message(admin_tg_id, "❌ Ошибка получения списка.")
        return

    total = len(rows)
    if total == 0:
        safe_send_message(admin_tg_id, "❌ Нет получателей.")
        return

    safe_send_message(admin_tg_id, f"📢 Рассылка для {total} чел...")
    sent, failed = 0, 0
    for row in rows:
        try:
            if bot.send_message(row['tg_id'], text):
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(0.05)

    safe_send_message(
        admin_tg_id,
        f"✅ Готово!\n📤 Отправлено: {sent}\n❌ Ошибок: {failed}\n👥 Всего: {total}"
    )
    log_admin_action(admin_tg_id, 'broadcast', 0,
                     f'{text[:80]} (sent={sent}, fail={failed})')