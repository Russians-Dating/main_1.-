#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, date, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Optional

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=25*1024*1024, backupCount=10, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("dating_bot")

class Config:
    BOT_TOKEN: str = os.environ.get("8953726614:AAFUzzEMAQAhy9LVDXstyXUfL4xbCrDB8as", "")
    DB_PATH: str = os.environ.get("DB_PATH", "dating_platform.db")
    OWNER_IDS: set[int] = {
        int(x) for x in os.environ.get("OWNER_IDS", "").split(",") if x.strip().isdigit()
    }
    MIN_AGE = 18
    MAX_AGE = 100
    MAX_PHOTOS_PER_PROFILE = 5
    MAX_BIO_LENGTH = 700
    MAX_TAGS_PER_PROFILE = 10
    PROFILE_NAME_MAX_LEN = 64
    CITY_MAX_LEN = 64
    DAILY_LIKE_LIMIT_FREE = 30
    DAILY_LIKE_LIMIT_PREMIUM = 150
    DAILY_LIKE_LIMIT_PREMIUM_PLUS = 100_000
    DAILY_PROFILE_VIEW_LIMIT_FREE = 60
    DAILY_PROFILE_VIEW_LIMIT_PREMIUM = 100_000
    INACTIVE_PROFILE_DAYS = 180
    INACTIVE_PROFILE_DELETE_DAYS = 365
    REFERRAL_REWARD_STARS = 15
    DAILY_REWARD_BASE_STARS = 3
    DAILY_REWARD_STREAK_BONUS_CAP = 7
    PREMIUM_PRICE_STARS_MONTHLY = 199
    PREMIUM_PLUS_PRICE_STARS_MONTHLY = 399
    VERIFICATION_VIDEO_MAX_DURATION = 60
    RATE_LIMIT_WINDOW_SECONDS = 10
    RATE_LIMIT_MAX_ACTIONS = 12
    FLOOD_MUTE_SECONDS = 60
    MAX_COMPLAINTS_PER_DAY = 10
    MAX_MESSAGES_PER_MINUTE_CHAT = 20
    CLEANUP_JOB_INTERVAL = 6 * 3600
    SUBSCRIPTION_EXPIRY_JOB_INTERVAL = 3600
    PUNISHMENT_EXPIRY_JOB_INTERVAL = 300

if not Config.BOT_TOKEN:
    log.critical("BOT_TOKEN не задан в переменных окружения")
    sys.exit(1)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def utcnow_iso() -> str:
    return utcnow().isoformat()

class UserStatus(str, Enum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    DELETED = "deleted"
    BANNED = "banned"

class UserRole(str, Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    OWNER = "owner"

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"

class LookingFor(str, Enum):
    MALE = "male"
    FEMALE = "female"
    ANY = "any"

class VerificationStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class PremiumTier(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    PREMIUM_PLUS = "premium_plus"

class PunishmentType(str, Enum):
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"
    SHADOWBAN = "shadowban"

class ComplaintStatus(str, Enum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"

class TransactionType(str, Enum):
    TOPUP = "topup"
    PURCHASE = "purchase"
    REFUND = "refund"
    REWARD = "reward"
    REFERRAL_BONUS = "referral_bonus"

class BotState(str, Enum):
    AWAITING_ADMIN_GIVE_STARS = "awaiting_admin_give_stars"
    AWAITING_ADMIN_RESET_STARS = "awaiting_admin_reset_stars"
    AWAITING_ADMIN_SET_STARS = "awaiting_admin_set_stars"
    AWAITING_ADMIN_GIVE_PREMIUM_DAYS = "awaiting_admin_give_premium_days"
    AWAITING_ADMIN_WARN_REASON = "awaiting_admin_warn_reason"
    NONE = "none"
    REG_GENDER = "reg_gender"
    REG_LOOKING_FOR = "reg_looking_for"
    REG_NAME = "reg_name"
    REG_BIRTHDATE = "reg_birthdate"
    REG_CITY = "reg_city"
    REG_ABOUT = "reg_about"
    REG_PHOTO = "reg_photo"
    REG_TAGS = "reg_tags"
    EDIT_NAME = "edit_name"
    EDIT_ABOUT = "edit_about"
    EDIT_CITY = "edit_city"
    EDIT_PHOTO = "edit_photo"
    EDIT_TAGS = "edit_tags"
    AWAITING_VERIFICATION_VIDEO = "awaiting_verification_video"
    AWAITING_COMPLAINT_REASON = "awaiting_complaint_reason"
    AWAITING_CHAT_MESSAGE = "awaiting_chat_message"
    AWAITING_SEARCH_MIN_AGE = "awaiting_search_min_age"
    AWAITING_SEARCH_MAX_AGE = "awaiting_search_max_age"
    AWAITING_SEARCH_CITY = "awaiting_search_city"
    AWAITING_BROADCAST_CONTENT = "awaiting_broadcast_content"
    AWAITING_ADMIN_SEARCH_ID = "awaiting_admin_search_id"
    AWAITING_MOD_REJECT_REASON = "awaiting_mod_reject_reason"

TAG_CATALOG: list[tuple[str, str]] = [
    ("Музыка", "образ жизни"), ("Кино", "образ жизни"), ("Игры", "образ жизни"),
    ("Путешествия", "образ жизни"), ("Спорт", "образ жизни"), ("Фитнес", "образ жизни"),
    ("Кулинария", "образ жизни"), ("Искусство", "творчество"), ("Фотография", "творчество"),
    ("Чтение", "творчество"), ("Танцы", "творчество"), ("Природа", "активный отдых"),
    ("Походы", "активный отдых"), ("Животные", "образ жизни"), ("Технологии", "карьера"),
    ("Бизнес", "карьера"), ("Наука", "карьера"), ("Мода", "образ жизни"),
    ("Кофе", "образ жизни"), ("Клубы", "образ жизни"), ("Йога", "фитнес"),
    ("Автомобили", "образ жизни"), ("Волонтёрство", "ценности"), ("Духовность", "ценности"),
    ("Веганство", "образ жизни"), ("Языки", "карьера"), ("Аниме", "образ жизни"),
    ("Настольные игры", "образ жизни"), ("Театр", "творчество"), ("Стартапы", "карьера"),
]

CALLBACK_SEP = ":"

class AppError(Exception):
    pass

class ValidationError(AppError):
    pass

class PermissionError_(AppError):
    pass

class NotFoundError(AppError):
    pass

class RateLimitedError(AppError):
    def __init__(self, retry_after: int = 0):
        super().__init__("rate_limited")
        self.retry_after = retry_after

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id             INTEGER PRIMARY KEY,
    public_id           TEXT NOT NULL UNIQUE,
    username            TEXT,
    display_name        TEXT NOT NULL,
    gender              TEXT NOT NULL CHECK (gender IN ('male','female')),
    looking_for         TEXT NOT NULL CHECK (looking_for IN ('male','female','any')),
    birth_date          TEXT NOT NULL,
    city                TEXT,
    about               TEXT,
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','hidden','deleted','banned')),
    role                TEXT NOT NULL DEFAULT 'user'
                            CHECK (role IN ('user','moderator','admin','owner')),
    verification_status TEXT NOT NULL DEFAULT 'none'
                            CHECK (verification_status IN ('none','pending','approved','rejected')),
    premium_tier        TEXT NOT NULL DEFAULT 'free'
                            CHECK (premium_tier IN ('free','premium','premium_plus')),
    premium_until       TEXT,
    balance_stars       INTEGER NOT NULL DEFAULT 0 CHECK (balance_stars >= 0),
    language_code       TEXT NOT NULL DEFAULT 'ru',
    referred_by         INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_active_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_gender_looking ON users(gender, looking_for, status);
CREATE INDEX IF NOT EXISTS idx_users_city ON users(city);
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_at);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS profile_media (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    file_id             TEXT NOT NULL,
    media_type          TEXT NOT NULL CHECK (media_type IN ('photo','video_note')),
    position            INTEGER NOT NULL DEFAULT 0,
    is_verification     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_user ON profile_media(user_id, position);

CREATE TABLE IF NOT EXISTS tags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    category            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_tags (
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tag_id              INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_user_tags_tag ON user_tags(tag_id);

CREATE TABLE IF NOT EXISTS likes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user           INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    to_user             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    is_like             INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE(from_user, to_user)
);
CREATE INDEX IF NOT EXISTS idx_likes_to_user ON likes(to_user, is_like);
CREATE INDEX IF NOT EXISTS idx_likes_from_user ON likes(from_user);

CREATE TABLE IF NOT EXISTS matches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a              INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    user_b              INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at          TEXT NOT NULL,
    is_active           INTEGER NOT NULL DEFAULT 1,
    UNIQUE(user_a, user_b)
);
CREATE INDEX IF NOT EXISTS idx_matches_a ON matches(user_a, is_active);
CREATE INDEX IF NOT EXISTS idx_matches_b ON matches(user_b, is_active);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id            INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    sender_id           INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    content_type        TEXT NOT NULL DEFAULT 'text',
    content             TEXT,
    file_id             TEXT,
    created_at          TEXT NOT NULL,
    is_deleted          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chatmsg_match ON chat_messages(match_id, created_at);

CREATE TABLE IF NOT EXISTS complaints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    target_id           INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    reason              TEXT NOT NULL,
    details             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','reviewing','resolved','dismissed')),
    created_at          TEXT NOT NULL,
    resolved_by         INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    resolved_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status, created_at);
CREATE INDEX IF NOT EXISTS idx_complaints_target ON complaints(target_id);

CREATE TABLE IF NOT EXISTS punishments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    type                TEXT NOT NULL CHECK (type IN ('warn','mute','ban','shadowban')),
    reason              TEXT,
    issued_by           INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    issued_at           TEXT NOT NULL,
    expires_at          TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_punishments_user ON punishments(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_punishments_expiry ON punishments(is_active, expires_at);

CREATE TABLE IF NOT EXISTS verification_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    video_file_id       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','approved','rejected')),
    submitted_at        TEXT NOT NULL,
    reviewed_by         INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at         TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_requests(status, submitted_at);

CREATE TABLE IF NOT EXISTS transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    type                TEXT NOT NULL,
    amount_stars        INTEGER NOT NULL,
    balance_after       INTEGER NOT NULL,
    description         TEXT,
    related_id          TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at);

CREATE TABLE IF NOT EXISTS shop_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sku                 TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    description         TEXT,
    price_stars         INTEGER NOT NULL CHECK (price_stars > 0),
    item_type           TEXT NOT NULL,
    payload             TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS referrals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    referred_id         INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    created_at          TEXT NOT NULL,
    reward_given        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);

CREATE TABLE IF NOT EXISTS daily_rewards (
    user_id             INTEGER PRIMARY KEY,
    last_claim_date     TEXT,
    streak              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_state (
    user_id             INTEGER PRIMARY KEY,
    state               TEXT NOT NULL DEFAULT 'none',
    data                TEXT NOT NULL DEFAULT '{}',
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_filters (
    user_id             INTEGER PRIMARY KEY,
    min_age             INTEGER NOT NULL DEFAULT 18,
    max_age             INTEGER NOT NULL DEFAULT 100,
    city                TEXT,
    verified_only       INTEGER NOT NULL DEFAULT 0,
    tags                TEXT NOT NULL DEFAULT '[]',
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action              TEXT NOT NULL,
    meta                TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action, created_at);

CREATE TABLE IF NOT EXISTS admin_action_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id            INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action              TEXT NOT NULL,
    target_id           INTEGER,
    meta                TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_log_admin ON admin_action_log(admin_id, created_at);

CREATE TABLE IF NOT EXISTS broadcasts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id            INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    content             TEXT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'text',
    file_id             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    total_targets       INTEGER NOT NULL DEFAULT 0,
    sent_count          INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    completed_at        TEXT
);

CREATE TABLE IF NOT EXISTS daily_action_counters (
    user_id             INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    action              TEXT NOT NULL,
    day                 TEXT NOT NULL,
    count               INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, action, day)
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL
);
"""

class Database:
    SCHEMA_VERSION = 1

    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()
        log.info(f"База данных инициализирована: {path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = self._connect()
        return self._local.conn

    def _init_schema(self) -> None:
        bootstrap = self._connect()
        try:
            bootstrap.executescript(SCHEMA_SQL)
            bootstrap.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
            bootstrap.commit()
            log.info("Схема базы данных создана/обновлена")
        except Exception as e:
            log.critical(f"Ошибка инициализации схемы БД: {e}")
            raise
        finally:
            bootstrap.close()

    @contextmanager
    def tx(self):
        with self._write_lock:
            conn = self.conn
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                log.error(f"Откат транзакции: {traceback.format_exc()}")
                raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(sql, params)
        return cur.fetchone()

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        cur = self.conn.execute(sql, params)
        return cur.fetchall()

    def execute_commit(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._write_lock:
            conn = self.conn
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

def _gen_public_id() -> str:
    return "DP-" + str(uuid.uuid4().int)[:6]

def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None

class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, user_id: int) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,)))

    def get_by_public_id(self, public_id: str) -> Optional[dict]:
        return row_to_dict(
            self.db.query_one("SELECT * FROM users WHERE public_id = ?", (public_id.upper(),))
        )

    def exists(self, user_id: int) -> bool:
        return self.db.query_one("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) is not None

    def create(
        self,
        user_id: int,
        username: Optional[str],
        display_name: str,
        gender: str,
        looking_for: str,
        birth_date: str,
        city: Optional[str],
        about: Optional[str],
        referred_by: Optional[int],
        role: str = UserRole.USER.value,
    ) -> dict:
        now = utcnow_iso()
        public_id = _gen_public_id()
        with self.db.tx() as conn:
            while conn.execute(
                "SELECT 1 FROM users WHERE public_id = ?", (public_id,)
            ).fetchone():
                public_id = _gen_public_id()
            conn.execute(
                """INSERT INTO users
                   (user_id, public_id, username, display_name, gender, looking_for,
                    birth_date, city, about, status, role, verification_status,
                    premium_tier, balance_stars, referred_by, created_at, updated_at,
                    last_active_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)""",
                (
                    user_id, public_id, username, display_name, gender, looking_for,
                    birth_date, city, about, UserStatus.ACTIVE.value, role,
                    VerificationStatus.NONE.value, PremiumTier.FREE.value,
                    referred_by, now, now, now,
                ),
            )
            conn.execute(
                "INSERT INTO search_filters(user_id, min_age, max_age, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, Config.MIN_AGE, Config.MAX_AGE, now),
            )
            conn.execute(
                "INSERT OR REPLACE INTO user_state(user_id, state, data, updated_at) VALUES (?,?,?,?)",
                (user_id, BotState.NONE.value, "{}", now),
            )
        log.info(f"Создан новый пользователь: {user_id} (public_id={public_id})")
        return self.get(user_id)

    def update_fields(self, user_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute_commit(
            f"UPDATE users SET {cols} WHERE user_id = ?",
            (*fields.values(), user_id),
        )

    def touch_active(self, user_id: int) -> None:
        self.db.execute_commit(
            "UPDATE users SET last_active_at = ? WHERE user_id = ?",
            (utcnow_iso(), user_id),
        )

    def set_status(self, user_id: int, status: str) -> None:
        self.update_fields(user_id, status=status)
        log.info(f"Статус пользователя {user_id} изменён на {status}")

    def set_role(self, user_id: int, role: str) -> None:
        self.update_fields(user_id, role=role)
        log.info(f"Роль пользователя {user_id} изменена на {role}")

    def adjust_balance(self, conn: sqlite3.Connection, user_id: int, delta: int) -> int:
        row = conn.execute(
            "SELECT balance_stars FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("пользователь не найден")
        new_balance = row["balance_stars"] + delta
        if new_balance < 0:
            raise ValidationError("недостаточно звёзд")
        conn.execute(
            "UPDATE users SET balance_stars = ?, updated_at = ? WHERE user_id = ?",
            (new_balance, utcnow_iso(), user_id),
        )
        return new_balance

    def candidates_for(
        self,
        user_id: int,
        looking_for: str,
        own_gender: str,
        min_age: int,
        max_age: int,
        city: Optional[str],
        verified_only: bool,
        exclude_ids: set[int],
        limit: int = 20,
    ) -> list[dict]:
        today = date.today()
        min_birth = date(today.year - max_age - 1, today.month, today.day).isoformat()
        max_birth = date(today.year - min_age, today.month, today.day).isoformat()

        gender_clause = ""
        params: list[Any] = [user_id]
        if looking_for != LookingFor.ANY.value:
            gender_clause = "AND u.gender = ?"
            params.append(looking_for)

        params.extend([own_gender, min_birth, max_birth])

        city_clause = ""
        if city:
            city_clause = "AND u.city = ?"
            params.append(city)

        verified_clause = ""
        if verified_only:
            verified_clause = "AND u.verification_status = 'approved'"

        exclude_clause = ""
        if exclude_ids:
            placeholders = ",".join("?" for _ in exclude_ids)
            exclude_clause = f"AND u.user_id NOT IN ({placeholders})"
            params.extend(exclude_ids)

        params.append(limit)

        sql = f"""
            SELECT u.* FROM users u
            WHERE u.user_id != ?
              {gender_clause}
              AND u.looking_for IN (?, 'any')
              AND u.birth_date BETWEEN ? AND ?
              {city_clause}
              {verified_clause}
              {exclude_clause}
              AND u.status = 'active'
            ORDER BY u.last_active_at DESC
            LIMIT ?
        """
        return [dict(r) for r in self.db.query_all(sql, tuple(params))]

    def count_active(self) -> int:
        return self.db.query_one(
            "SELECT COUNT(*) c FROM users WHERE status = 'active'"
        )["c"]

    def stats_summary(self) -> dict:
        row = self.db.query_one(
            """SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status='hidden' THEN 1 ELSE 0 END) AS hidden,
                SUM(CASE WHEN status='banned' THEN 1 ELSE 0 END) AS banned,
                SUM(CASE WHEN status='deleted' THEN 1 ELSE 0 END) AS deleted,
                SUM(CASE WHEN verification_status='approved' THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN premium_tier='premium' THEN 1 ELSE 0 END) AS premium,
                SUM(CASE WHEN premium_tier='premium_plus' THEN 1 ELSE 0 END) AS premium_plus
               FROM users"""
        )
        return dict(row)

    def find_inactive_before(self, cutoff_iso: str, statuses: tuple[str, ...]) -> list[dict]:
        placeholders = ",".join("?" for _ in statuses)
        return [
            dict(r)
            for r in self.db.query_all(
                f"SELECT * FROM users WHERE last_active_at < ? AND status IN ({placeholders})",
                (cutoff_iso, *statuses),
            )
        ]

    def list_by_role(self, roles: tuple[str, ...]) -> list[dict]:
        placeholders = ",".join("?" for _ in roles)
        return [
            dict(r)
            for r in self.db.query_all(
                f"SELECT * FROM users WHERE role IN ({placeholders})", roles
            )
        ]

    def list_page(self, offset: int, limit: int, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = self.db.query_all(
                "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(r) for r in rows]

    def all_active_ids(self) -> list[int]:
        return [r["user_id"] for r in self.db.query_all(
            "SELECT user_id FROM users WHERE status IN ('active','hidden')"
        )]

class MediaRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, user_id: int, file_id: str, media_type: str, is_verification: bool = False) -> int:
        with self.db.tx() as conn:
            pos_row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM profile_media "
                "WHERE user_id = ? AND is_verification = 0",
                (user_id,),
            ).fetchone()
            position = pos_row["p"] if not is_verification else 0
            cur = conn.execute(
                """INSERT INTO profile_media
                   (user_id, file_id, media_type, position, is_verification, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, file_id, media_type, position, int(is_verification), utcnow_iso()),
            )
            return cur.lastrowid

    def list_for_user(self, user_id: int, verification: bool = False) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM profile_media WHERE user_id = ? AND is_verification = ? "
                "ORDER BY position ASC",
                (user_id, int(verification)),
            )
        ]

    def count_for_user(self, user_id: int) -> int:
        return self.db.query_one(
            "SELECT COUNT(*) c FROM profile_media WHERE user_id = ? AND is_verification = 0",
            (user_id,),
        )["c"]

    def delete_all_for_user(self, user_id: int, verification: bool = False) -> None:
        self.db.execute_commit(
            "DELETE FROM profile_media WHERE user_id = ? AND is_verification = ?",
            (user_id, int(verification)),
        )

class TagRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure_catalog(self, catalog: list[tuple[str, str]]) -> None:
        with self.db.tx() as conn:
            for name, category in catalog:
                conn.execute(
                    "INSERT OR IGNORE INTO tags(name, category) VALUES (?, ?)",
                    (name, category),
                )
        log.info(f"Каталог тегов обновлён: {len(catalog)} тегов")

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.query_all("SELECT * FROM tags ORDER BY category, name")]

    def get_by_name(self, name: str) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM tags WHERE name = ?", (name,)))

    def for_user(self, user_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT t.* FROM tags t
                   JOIN user_tags ut ON ut.tag_id = t.id
                   WHERE ut.user_id = ? ORDER BY t.category, t.name""",
                (user_id,),
            )
        ]

    def toggle(self, user_id: int, tag_id: int, max_tags: int) -> bool:
        with self.db.tx() as conn:
            existing = conn.execute(
                "SELECT 1 FROM user_tags WHERE user_id = ? AND tag_id = ?",
                (user_id, tag_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM user_tags WHERE user_id = ? AND tag_id = ?",
                    (user_id, tag_id),
                )
                return False
            count = conn.execute(
                "SELECT COUNT(*) c FROM user_tags WHERE user_id = ?", (user_id,)
            ).fetchone()["c"]
            if count >= max_tags:
                raise ValidationError("достигнут максимум тегов")
            conn.execute(
                "INSERT INTO user_tags(user_id, tag_id) VALUES (?, ?)", (user_id, tag_id)
            )
            return True

    def clear_for_user(self, user_id: int) -> None:
        self.db.execute_commit("DELETE FROM user_tags WHERE user_id = ?", (user_id,))

class LikeRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(self, from_user: int, to_user: int, is_like: bool) -> None:
        self.db.execute_commit(
            """INSERT INTO likes(from_user, to_user, is_like, created_at)
               VALUES (?,?,?,?)
               ON CONFLICT(from_user, to_user)
               DO UPDATE SET is_like = excluded.is_like, created_at = excluded.created_at""",
            (from_user, to_user, int(is_like), utcnow_iso()),
        )

    def reciprocal_like_exists(self, conn: sqlite3.Connection, a: int, b: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM likes WHERE from_user = ? AND to_user = ? AND is_like = 1",
            (b, a),
        ).fetchone()
        return row is not None

    def has_interacted(self, from_user: int, to_user: int) -> bool:
        return self.db.query_one(
            "SELECT 1 FROM likes WHERE from_user = ? AND to_user = ?", (from_user, to_user)
        ) is not None

    def already_seen_ids(self, user_id: int) -> set[int]:
        return {
            r["to_user"]
            for r in self.db.query_all(
                "SELECT to_user FROM likes WHERE from_user = ?", (user_id,)
            )
        }

    def likes_received(self, user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT u.* FROM likes l
                   JOIN users u ON u.user_id = l.from_user
                   WHERE l.to_user = ? AND l.is_like = 1 AND u.status = 'active'
                   AND NOT EXISTS (
                       SELECT 1 FROM likes l2 WHERE l2.from_user = ? AND l2.to_user = l.from_user
                   )
                   ORDER BY l.created_at DESC LIMIT ? OFFSET ?""",
                (user_id, user_id, limit, offset),
            )
        ]

    def count_likes_today(self, user_id: int) -> int:
        today = date.today().isoformat()
        return self.db.query_one(
            "SELECT COUNT(*) c FROM likes WHERE from_user = ? AND is_like = 1 AND date(created_at) = ?",
            (user_id, today),
        )["c"]

class MatchRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _ordered(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def create(self, conn: sqlite3.Connection, a: int, b: int) -> int:
        ua, ub = self._ordered(a, b)
        cur = conn.execute(
            """INSERT INTO matches(user_a, user_b, created_at, is_active)
               VALUES (?,?,?,1)
               ON CONFLICT(user_a, user_b) DO UPDATE SET is_active = 1""",
            (ua, ub, utcnow_iso()),
        )
        row = conn.execute(
            "SELECT id FROM matches WHERE user_a = ? AND user_b = ?", (ua, ub)
        ).fetchone()
        log.info(f"Создан мэтч: {a} <-> {b} (id={row['id']})")
        return row["id"]

    def get(self, match_id: int) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM matches WHERE id = ?", (match_id,)))

    def get_between(self, a: int, b: int) -> Optional[dict]:
        ua, ub = self._ordered(a, b)
        return row_to_dict(
            self.db.query_one(
                "SELECT * FROM matches WHERE user_a = ? AND user_b = ?", (ua, ub)
            )
        )

    def list_for_user(self, user_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT m.*,
                          CASE WHEN m.user_a = ? THEN m.user_b ELSE m.user_a END AS other_user_id
                   FROM matches m
                   WHERE (m.user_a = ? OR m.user_b = ?) AND m.is_active = 1
                   ORDER BY m.created_at DESC""",
                (user_id, user_id, user_id),
            )
        ]

    def other_user(self, match: dict, user_id: int) -> int:
        return match["user_b"] if match["user_a"] == user_id else match["user_a"]

    def deactivate(self, match_id: int) -> None:
        self.db.execute_commit("UPDATE matches SET is_active = 0 WHERE id = ?", (match_id,))
        log.info(f"Мэтч деактивирован: {match_id}")

    def is_participant(self, match_id: int, user_id: int) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM matches WHERE id = ? AND (user_a = ? OR user_b = ?) AND is_active = 1",
            (match_id, user_id, user_id),
        )
        return row is not None

class ChatRepository:
    def __init__(self, db: Database):
        self.db = db

    def add_message(
        self, match_id: int, sender_id: int, content: Optional[str],
        content_type: str = "text", file_id: Optional[str] = None,
    ) -> int:
        cur = self.db.execute_commit(
            """INSERT INTO chat_messages(match_id, sender_id, content_type, content, file_id, created_at)
               VALUES (?,?,?,?,?,?)""",
            (match_id, sender_id, content_type, content, file_id, utcnow_iso()),
        )
        return cur.lastrowid

    def recent_messages(self, match_id: int, limit: int = 30) -> list[dict]:
        rows = self.db.query_all(
            """SELECT * FROM chat_messages WHERE match_id = ? AND is_deleted = 0
               ORDER BY created_at DESC LIMIT ?""",
            (match_id, limit),
        )
        return [dict(r) for r in reversed(rows)]

    def count_messages_since(self, match_id: int, sender_id: int, since_iso: str) -> int:
        return self.db.query_one(
            """SELECT COUNT(*) c FROM chat_messages
               WHERE match_id = ? AND sender_id = ? AND created_at >= ?""",
            (match_id, sender_id, since_iso),
        )["c"]

class ComplaintRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, reporter_id: int, target_id: int, reason: str, details: Optional[str]) -> int:
        cur = self.db.execute_commit(
            """INSERT INTO complaints(reporter_id, target_id, reason, details, status, created_at)
               VALUES (?,?,?,?,?,?)""",
            (reporter_id, target_id, reason, details, ComplaintStatus.PENDING.value, utcnow_iso()),
        )
        log.info(f"Создана жалоба: reporter={reporter_id} target={target_id} reason={reason}")
        return cur.lastrowid

    def count_today_by_reporter(self, reporter_id: int) -> int:
        today = date.today().isoformat()
        return self.db.query_one(
            "SELECT COUNT(*) c FROM complaints WHERE reporter_id = ? AND date(created_at) = ?",
            (reporter_id, today),
        )["c"]

    def count_against(self, target_id: int, statuses: tuple[str, ...] = ("pending", "reviewing", "resolved")) -> int:
        placeholders = ",".join("?" for _ in statuses)
        return self.db.query_one(
            f"SELECT COUNT(*) c FROM complaints WHERE target_id = ? AND status IN ({placeholders})",
            (target_id, *statuses),
        )["c"]

    def next_pending(self) -> Optional[dict]:
        return row_to_dict(
            self.db.query_one(
                "SELECT * FROM complaints WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            )
        )

    def get(self, complaint_id: int) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM complaints WHERE id = ?", (complaint_id,)))

    def resolve(self, complaint_id: int, status: str, resolved_by: int) -> None:
        self.db.execute_commit(
            "UPDATE complaints SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_by, utcnow_iso(), complaint_id),
        )
        log.info(f"Жалоба {complaint_id} обработана: статус={status}, модератор={resolved_by}")

    def pending_count(self) -> int:
        return self.db.query_one("SELECT COUNT(*) c FROM complaints WHERE status = 'pending'")["c"]

class PunishmentRepository:
    def __init__(self, db: Database):
        self.db = db

    def issue(
        self, user_id: int, ptype: str, reason: Optional[str], issued_by: Optional[int],
        duration: Optional[timedelta],
    ) -> int:
        expires_at = (utcnow() + duration).isoformat() if duration else None
        cur = self.db.execute_commit(
            """INSERT INTO punishments(user_id, type, reason, issued_by, issued_at, expires_at, is_active)
               VALUES (?,?,?,?,?,?,1)""",
            (user_id, ptype, reason, issued_by, utcnow_iso(), expires_at),
        )
        log.info(f"Выдано наказание: user={user_id} type={ptype} issued_by={issued_by}")
        return cur.lastrowid

    def active_for_user(self, user_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM punishments WHERE user_id = ? AND is_active = 1", (user_id,)
            )
        ]

    def has_active(self, user_id: int, ptype: str) -> bool:
        return self.db.query_one(
            "SELECT 1 FROM punishments WHERE user_id = ? AND type = ? AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (user_id, ptype, utcnow_iso()),
        ) is not None

    def find_expired(self) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM punishments WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at <= ?",
                (utcnow_iso(),),
            )
        ]

    def deactivate(self, punishment_id: int) -> None:
        self.db.execute_commit("UPDATE punishments SET is_active = 0 WHERE id = ?", (punishment_id,))

    def deactivate_all_of_type(self, user_id: int, ptype: str) -> None:
        self.db.execute_commit(
            "UPDATE punishments SET is_active = 0 WHERE user_id = ? AND type = ?",
            (user_id, ptype),
        )
        log.info(f"Наказания типа {ptype} деактивированы для пользователя {user_id}")

    def history_for_user(self, user_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM punishments WHERE user_id = ? ORDER BY issued_at DESC", (user_id,)
            )
        ]

class VerificationRepository:
    def __init__(self, db: Database):
        self.db = db

    def submit(self, user_id: int, video_file_id: str) -> int:
        cur = self.db.execute_commit(
            """INSERT INTO verification_requests(user_id, video_file_id, status, submitted_at)
               VALUES (?,?,?,?)""",
            (user_id, video_file_id, VerificationStatus.PENDING.value, utcnow_iso()),
        )
        log.info(f"Заявка на верификацию: user={user_id}")
        return cur.lastrowid

    def next_pending(self) -> Optional[dict]:
        return row_to_dict(
            self.db.query_one(
                "SELECT * FROM verification_requests WHERE status = 'pending' "
                "ORDER BY submitted_at ASC LIMIT 1"
            )
        )

    def get(self, req_id: int) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM verification_requests WHERE id = ?", (req_id,)))

    def has_pending(self, user_id: int) -> bool:
        return self.db.query_one(
            "SELECT 1 FROM verification_requests WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        ) is not None

    def resolve(self, req_id: int, status: str, reviewed_by: int, notes: Optional[str]) -> None:
        self.db.execute_commit(
            """UPDATE verification_requests
               SET status = ?, reviewed_by = ?, reviewed_at = ?, notes = ? WHERE id = ?""",
            (status, reviewed_by, utcnow_iso(), notes, req_id),
        )
        log.info(f"Заявка на верификацию {req_id}: статус={status}, модератор={reviewed_by}")

    def pending_count(self) -> int:
        return self.db.query_one(
            "SELECT COUNT(*) c FROM verification_requests WHERE status = 'pending'"
        )["c"]

class TransactionRepository:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self, conn: sqlite3.Connection, user_id: int, ttype: str, amount: int,
        balance_after: int, description: str, related_id: Optional[str] = None,
    ) -> int:
        cur = conn.execute(
            """INSERT INTO transactions(user_id, type, amount_stars, balance_after, description, related_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, ttype, amount, balance_after, description, related_id, utcnow_iso()),
        )
        return cur.lastrowid

    def history(self, user_id: int, limit: int = 20) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        ]

class ShopRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure_defaults(self) -> None:
        defaults = [
            ("premium_30d", "Premium — 30 дней", "Безлимитные лайки, просмотр кто лайкнул, расширенные фильтры",
             Config.PREMIUM_PRICE_STARS_MONTHLY, "premium", json.dumps({"duration_days": 30})),
            ("premium_plus_30d", "Premium+ — 30 дней", "Всё из Premium плюс продвижение профиля и приоритетная поддержка",
             Config.PREMIUM_PLUS_PRICE_STARS_MONTHLY, "premium_plus", json.dumps({"duration_days": 30})),
            ("boost_24h", "Продвижение профиля — 24ч", "Ваш профиль будет первым в результатах поиска на 24 часа",
             49, "boost", json.dumps({"duration_hours": 24})),
            ("superlikes_5", "5 Супер-лайков", "Выделитесь с помощью 5 супер-лайков", 29, "superlike_pack",
             json.dumps({"quantity": 5})),
        ]
        with self.db.tx() as conn:
            for sku, name, desc, price, item_type, payload in defaults:
                conn.execute(
                    """INSERT INTO shop_items(sku, name, description, price_stars, item_type, payload, is_active)
                       VALUES (?,?,?,?,?,?,1)
                       ON CONFLICT(sku) DO NOTHING""",
                    (sku, name, desc, price, item_type, payload),
                )
        log.info("Товары магазина по умолчанию добавлены")

    def active_items(self) -> list[dict]:
        return [dict(r) for r in self.db.query_all("SELECT * FROM shop_items WHERE is_active = 1")]

    def get(self, item_id: int) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM shop_items WHERE id = ?", (item_id,)))

    def get_by_sku(self, sku: str) -> Optional[dict]:
        return row_to_dict(self.db.query_one("SELECT * FROM shop_items WHERE sku = ?", (sku,)))

class ReferralRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, conn: sqlite3.Connection, referrer_id: int, referred_id: int) -> int:
        cur = conn.execute(
            "INSERT INTO referrals(referrer_id, referred_id, created_at, reward_given) VALUES (?,?,?,0)",
            (referrer_id, referred_id, utcnow_iso()),
        )
        log.info(f"Реферал: referrer={referrer_id} referred={referred_id}")
        return cur.lastrowid

    def mark_rewarded(self, conn: sqlite3.Connection, referral_id: int) -> None:
        conn.execute("UPDATE referrals SET reward_given = 1 WHERE id = ?", (referral_id,))

    def count_for_referrer(self, referrer_id: int) -> int:
        return self.db.query_one(
            "SELECT COUNT(*) c FROM referrals WHERE referrer_id = ?", (referrer_id,)
        )["c"]

    def get_by_referred(self, referred_id: int) -> Optional[dict]:
        return row_to_dict(
            self.db.query_one("SELECT * FROM referrals WHERE referred_id = ?", (referred_id,))
        )

class DailyRewardRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, user_id: int) -> Optional[dict]:
        return row_to_dict(
            self.db.query_one("SELECT * FROM daily_rewards WHERE user_id = ?", (user_id,))
        )

    def upsert(self, conn: sqlite3.Connection, user_id: int, last_claim_date: str, streak: int) -> None:
        conn.execute(
            """INSERT INTO daily_rewards(user_id, last_claim_date, streak) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET last_claim_date = excluded.last_claim_date,
                                                   streak = excluded.streak""",
            (user_id, last_claim_date, streak),
        )

class StateRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, user_id: int) -> tuple[str, dict]:
        row = self.db.query_one("SELECT state, data FROM user_state WHERE user_id = ?", (user_id,))
        if row is None:
            return BotState.NONE.value, {}
        try:
            data = json.loads(row["data"]) if row["data"] else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return row["state"], data

    def set(self, user_id: int, state: str, data: Optional[dict] = None) -> None:
        payload = json.dumps(data or {})
        self.db.execute_commit(
            """INSERT OR REPLACE INTO user_state(user_id, state, data, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, data = excluded.data,
                                                   updated_at = excluded.updated_at""",
            (user_id, state, payload, utcnow_iso()),
        )

    def clear(self, user_id: int) -> None:
        self.set(user_id, BotState.NONE.value, {})

    def update_data(self, user_id: int, **kwargs) -> dict:
        state, data = self.get(user_id)
        data.update(kwargs)
        self.set(user_id, state, data)
        return data

class SearchFilterRepository:
    def __init__(self, db: Database):
        self.db = db

    def get(self, user_id: int) -> dict:
        row = self.db.query_one("SELECT * FROM search_filters WHERE user_id = ?", (user_id,))
        if row is None:
            return {
                "user_id": user_id, "min_age": Config.MIN_AGE, "max_age": Config.MAX_AGE,
                "city": None, "verified_only": 0, "tags": "[]",
            }
        return dict(row)

    def update(self, user_id: int, **fields) -> None:
        fields["updated_at"] = utcnow_iso()
        existing = self.db.query_one("SELECT 1 FROM search_filters WHERE user_id = ?", (user_id,))
        if existing is None:
            self.db.execute_commit(
                "INSERT INTO search_filters(user_id, min_age, max_age, updated_at) VALUES (?,?,?,?)",
                (user_id, Config.MIN_AGE, Config.MAX_AGE, utcnow_iso()),
            )
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute_commit(
            f"UPDATE search_filters SET {cols} WHERE user_id = ?", (*fields.values(), user_id)
        )

class ActivityLogRepository:
    def __init__(self, db: Database):
        self.db = db

    def log(self, user_id: Optional[int], action: str, meta: Optional[dict] = None) -> None:
        self.db.execute_commit(
            "INSERT INTO activity_log(user_id, action, meta, created_at) VALUES (?,?,?,?)",
            (user_id, action, json.dumps(meta) if meta else None, utcnow_iso()),
        )

    def recent_for_user(self, user_id: int, limit: int = 50) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM activity_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        ]

    def counts_by_action_since(self, since_iso: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.query_all(
                """SELECT action, COUNT(*) c FROM activity_log
                   WHERE created_at >= ? GROUP BY action ORDER BY c DESC""",
                (since_iso,),
            )
        ]

class AdminLogRepository:
    def __init__(self, db: Database):
        self.db = db

    def log(self, admin_id: Optional[int], action: str, target_id: Optional[int], meta: Optional[dict] = None) -> None:
        self.db.execute_commit(
            "INSERT INTO admin_action_log(admin_id, action, target_id, meta, created_at) VALUES (?,?,?,?,?)",
            (admin_id, action, target_id, json.dumps(meta) if meta else None, utcnow_iso()),
        )

    def recent(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.query_all(
            "SELECT * FROM admin_action_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )]

class BroadcastRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, admin_id: int, content: str, content_type: str, file_id: Optional[str], total: int) -> int:
        cur = self.db.execute_commit(
            """INSERT INTO broadcasts(admin_id, content, content_type, file_id, status, total_targets, created_at)
               VALUES (?,?,?,?,'running',?,?)""",
            (admin_id, content, content_type, file_id, total, utcnow_iso()),
        )
        log.info(f"Рассылка создана: admin={admin_id} total={total}")
        return cur.lastrowid

    def update_progress(self, broadcast_id: int, sent: int, failed: int) -> None:
        self.db.execute_commit(
            "UPDATE broadcasts SET sent_count = ?, failed_count = ? WHERE id = ?",
            (sent, failed, broadcast_id),
        )

    def complete(self, broadcast_id: int) -> None:
        self.db.execute_commit(
            "UPDATE broadcasts SET status = 'completed', completed_at = ? WHERE id = ?",
            (utcnow_iso(), broadcast_id),
        )
        log.info(f"Рассылка {broadcast_id} завершена")

class DailyCounterRepository:
    def __init__(self, db: Database):
        self.db = db

    def increment_and_get(self, user_id: int, action: str) -> int:
        today = date.today().isoformat()
        with self.db.tx() as conn:
            conn.execute(
                """INSERT INTO daily_action_counters(user_id, action, day, count) VALUES (?,?,?,1)
                   ON CONFLICT(user_id, action, day) DO UPDATE SET count = count + 1""",
                (user_id, action, today),
            )
            row = conn.execute(
                "SELECT count FROM daily_action_counters WHERE user_id = ? AND action = ? AND day = ?",
                (user_id, action, today),
            ).fetchone()
            return row["count"]

    def get_count(self, user_id: int, action: str) -> int:
        today = date.today().isoformat()
        row = self.db.query_one(
            "SELECT count FROM daily_action_counters WHERE user_id = ? AND action = ? AND day = ?",
            (user_id, action, today),
        )
        return row["count"] if row else 0

@dataclass
class Repos:
    users: UserRepository
    media: MediaRepository
    tags: TagRepository
    likes: LikeRepository
    matches: MatchRepository
    chat: ChatRepository
    complaints: ComplaintRepository
    punishments: PunishmentRepository
    verification: VerificationRepository
    transactions: TransactionRepository
    shop: ShopRepository
    referrals: ReferralRepository
    daily_rewards: DailyRewardRepository
    state: StateRepository
    search_filters: SearchFilterRepository
    activity: ActivityLogRepository
    admin_log: AdminLogRepository
    broadcasts: BroadcastRepository
    daily_counters: DailyCounterRepository

    @classmethod
    def build(cls, db: Database) -> "Repos":
        return cls(
            users=UserRepository(db), media=MediaRepository(db), tags=TagRepository(db),
            likes=LikeRepository(db), matches=MatchRepository(db), chat=ChatRepository(db),
            complaints=ComplaintRepository(db), punishments=PunishmentRepository(db),
            verification=VerificationRepository(db), transactions=TransactionRepository(db),
            shop=ShopRepository(db), referrals=ReferralRepository(db),
            daily_rewards=DailyRewardRepository(db), state=StateRepository(db),
            search_filters=SearchFilterRepository(db), activity=ActivityLogRepository(db),
            admin_log=AdminLogRepository(db), broadcasts=BroadcastRepository(db),
            daily_counters=DailyCounterRepository(db),
        )

def calc_age(birth_date_iso: str) -> int:
    b = date.fromisoformat(birth_date_iso)
    today = date.today()
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))

def validate_birth_date(text: str) -> date:
    text = text.strip()
    parsed: Optional[date] = None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValidationError("Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 15.03.1998).")
    today = date.today()
    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
    if parsed > today:
        raise ValidationError("Дата рождения не может быть в будущем.")
    if age < Config.MIN_AGE:
        raise ValidationError(f"Вам должно быть не менее {Config.MIN_AGE} лет для использования платформы.")
    if age > Config.MAX_AGE:
        raise ValidationError("Пожалуйста, введите корректную дату рождения.")
    return parsed

def validate_name(text: str) -> str:
    text = text.strip()
    if not (1 <= len(text) <= Config.PROFILE_NAME_MAX_LEN):
        raise ValidationError(f"Имя должно содержать от 1 до {Config.PROFILE_NAME_MAX_LEN} символов.")
    if not re.match(r"^[^\d\W][\w \-']*$", text, re.UNICODE):
        raise ValidationError("Имя содержит недопустимые символы.")
    if re.search(r"(https?://|t\.me/|@\w{4,})", text, re.IGNORECASE):
        raise ValidationError("Имя не может содержать ссылки или имена пользователей.")
    return text

def validate_about(text: str) -> str:
    text = text.strip()
    if len(text) > Config.MAX_BIO_LENGTH:
        raise ValidationError(f"Раздел «О себе» должен содержать не более {Config.MAX_BIO_LENGTH} символов.")
    return sanitize_free_text(text)

def validate_city(text: str) -> str:
    text = text.strip()
    if not (1 <= len(text) <= Config.CITY_MAX_LEN):
        raise ValidationError(f"Название города должно содержать от 1 до {Config.CITY_MAX_LEN} символов.")
    return sanitize_free_text(text)

_LINK_RE = re.compile(r"(https?://\S+|t\.me/\S+|www\.\S+)", re.IGNORECASE)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def sanitize_free_text(text: str) -> str:
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _LINK_RE.sub("[ссылка удалена]", text)
    return text.strip()

class RegistrationService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def register(
        self, user_id: int, username: Optional[str], display_name: str, gender: str,
        looking_for: str, birth_date: date, city: Optional[str], about: Optional[str],
        referrer_public_id: Optional[str],
    ) -> dict:
        referred_by = None
        if referrer_public_id:
            referrer = self.repos.users.get_by_public_id(referrer_public_id)
            if referrer and referrer["user_id"] != user_id:
                referred_by = referrer["user_id"]
                log.info(f"Пользователь {user_id} зарегистрирован по реферальной ссылке от {referred_by}")

        role = UserRole.OWNER.value if user_id in Config.OWNER_IDS else UserRole.USER.value
        user = self.repos.users.create(
            user_id=user_id, username=username, display_name=display_name, gender=gender,
            looking_for=looking_for, birth_date=birth_date.isoformat(), city=city, about=about,
            referred_by=referred_by, role=role,
        )
        if referred_by:
            with self._tx_wrapper() as conn:
                ref_id = self.repos.referrals.create(conn, referred_by, user_id)
        self.repos.activity.log(user_id, "registered", {"gender": gender, "looking_for": looking_for})
        log.info(f"Регистрация завершена: user={user_id} role={role}")
        return user

    def _tx_wrapper(self):
        return self.repos.referrals.db.tx()

class ProfileService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def get_full_profile(self, user_id: int) -> Optional[dict]:
        user = self.repos.users.get(user_id)
        if not user:
            return None
        user["age"] = calc_age(user["birth_date"])
        user["photos"] = self.repos.media.list_for_user(user_id)
        user["tags"] = self.repos.tags.for_user(user_id)
        return user

    def update_name(self, user_id: int, name: str) -> None:
        self.repos.users.update_fields(user_id, display_name=validate_name(name))
        log.info(f"Пользователь {user_id} обновил имя")

    def update_about(self, user_id: int, about: str) -> None:
        self.repos.users.update_fields(user_id, about=validate_about(about))
        log.info(f"Пользователь {user_id} обновил «О себе»")

    def update_city(self, user_id: int, city: str) -> None:
        self.repos.users.update_fields(user_id, city=validate_city(city))
        log.info(f"Пользователь {user_id} обновил город")

    def add_photo(self, user_id: int, file_id: str) -> None:
        count = self.repos.media.count_for_user(user_id)
        if count >= Config.MAX_PHOTOS_PER_PROFILE:
            raise ValidationError(f"Можно загрузить не более {Config.MAX_PHOTOS_PER_PROFILE} фото.")
        self.repos.media.add(user_id, file_id, "photo")

    def toggle_tag(self, user_id: int, tag_id: int) -> bool:
        return self.repos.tags.toggle(user_id, tag_id, Config.MAX_TAGS_PER_PROFILE)

    def hide_profile(self, user_id: int) -> None:
        self.repos.users.set_status(user_id, UserStatus.HIDDEN.value)
        self.repos.activity.log(user_id, "profile_hidden")

    def unhide_profile(self, user_id: int) -> None:
        self.repos.users.set_status(user_id, UserStatus.ACTIVE.value)
        self.repos.activity.log(user_id, "profile_unhidden")

    def delete_profile(self, user_id: int) -> None:
        self.repos.users.set_status(user_id, UserStatus.DELETED.value)
        self.repos.activity.log(user_id, "profile_deleted")

    def restore_profile(self, user_id: int) -> None:
        user = self.repos.users.get(user_id)
        if not user or user["status"] != UserStatus.DELETED.value:
            raise ValidationError("Профиль не удалён — нечего восстанавливать.")
        self.repos.users.set_status(user_id, UserStatus.ACTIVE.value)
        self.repos.activity.log(user_id, "profile_restored")

class VerificationService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def submit_video(self, user_id: int, file_id: str) -> None:
        if self.repos.verification.has_pending(user_id):
            raise ValidationError("У вас уже есть ожидающая заявка на верификацию.")
        self.repos.verification.submit(user_id, file_id)
        self.repos.users.update_fields(user_id, verification_status=VerificationStatus.PENDING.value)
        self.repos.activity.log(user_id, "verification_submitted")

    def approve(self, req_id: int, moderator_id: int) -> dict:
        req = self.repos.verification.get(req_id)
        if not req or req["status"] != VerificationStatus.PENDING.value:
            raise NotFoundError("Заявка не найдена или уже обработана.")
        self.repos.verification.resolve(req_id, VerificationStatus.APPROVED.value, moderator_id, None)
        self.repos.users.update_fields(req["user_id"], verification_status=VerificationStatus.APPROVED.value)
        self.repos.admin_log.log(moderator_id, "verification_approved", req["user_id"])
        log.info(f"Верификация одобрена: req={req_id} user={req['user_id']} модератор={moderator_id}")
        return req

    def reject(self, req_id: int, moderator_id: int, reason: str) -> dict:
        req = self.repos.verification.get(req_id)
        if not req or req["status"] != VerificationStatus.PENDING.value:
            raise NotFoundError("Заявка не найдена или уже обработана.")
        self.repos.verification.resolve(req_id, VerificationStatus.REJECTED.value, moderator_id, reason)
        self.repos.users.update_fields(req["user_id"], verification_status=VerificationStatus.REJECTED.value)
        self.repos.admin_log.log(moderator_id, "verification_rejected", req["user_id"], {"reason": reason})
        log.info(f"Верификация отклонена: req={req_id} user={req['user_id']} причина={reason}")
        return req

class MatchService:
    def __init__(self, repos: Repos, db: Database):
        self.repos = repos
        self.db = db

    def daily_like_limit_for(self, user: dict) -> int:
        tier = user["premium_tier"]
        if tier == PremiumTier.PREMIUM_PLUS.value:
            return Config.DAILY_LIKE_LIMIT_PREMIUM_PLUS
        if tier == PremiumTier.PREMIUM.value:
            return Config.DAILY_LIKE_LIMIT_PREMIUM
        return Config.DAILY_LIKE_LIMIT_FREE

    def like(self, from_user_id: int, to_user_id: int) -> Optional[int]:
        if from_user_id == to_user_id:
            raise ValidationError("Нельзя лайкнуть свой собственный профиль.")
        actor = self.repos.users.get(from_user_id)
        if not actor:
            raise NotFoundError("пользователь не найден")

        limit = self.daily_like_limit_for(actor)
        used = self.repos.likes.count_likes_today(from_user_id)
        if used >= limit:
            raise RateLimitedError()

        target = self.repos.users.get(to_user_id)
        if not target or target["status"] != UserStatus.ACTIVE.value:
            raise NotFoundError("Этот профиль больше недоступен.")

        match_id = None
        with self.db.tx() as conn:
            conn.execute(
                """INSERT INTO likes(from_user, to_user, is_like, created_at) VALUES (?,?,1,?)
                   ON CONFLICT(from_user, to_user)
                   DO UPDATE SET is_like = 1, created_at = excluded.created_at""",
                (from_user_id, to_user_id, utcnow_iso()),
            )
            if self.repos.likes.reciprocal_like_exists(conn, from_user_id, to_user_id):
                match_id = self.repos.matches.create(conn, from_user_id, to_user_id)

        self.repos.activity.log(from_user_id, "like", {"target": to_user_id})
        if match_id:
            self.repos.activity.log(from_user_id, "match_created", {"match_id": match_id})
            self.repos.activity.log(to_user_id, "match_created", {"match_id": match_id})
            log.info(f"Взаимный мэтч: {from_user_id} <-> {to_user_id}")
        return match_id

    def dislike(self, from_user_id: int, to_user_id: int) -> None:
        self.repos.likes.record(from_user_id, to_user_id, is_like=False)
        self.repos.activity.log(from_user_id, "dislike", {"target": to_user_id})

    def unmatch(self, user_id: int, match_id: int) -> None:
        if not self.repos.matches.is_participant(match_id, user_id):
            raise PermissionError_("Вы не участвуете в этом мэтче.")
        self.repos.matches.deactivate(match_id)
        self.repos.activity.log(user_id, "unmatch", {"match_id": match_id})

class SearchService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def daily_view_limit_for(self, user: dict) -> int:
        if user["premium_tier"] in (PremiumTier.PREMIUM.value, PremiumTier.PREMIUM_PLUS.value):
            return Config.DAILY_PROFILE_VIEW_LIMIT_PREMIUM
        return Config.DAILY_PROFILE_VIEW_LIMIT_FREE

    def next_candidate(self, user_id: int) -> Optional[dict]:
        user = self.repos.users.get(user_id)
        if not user:
            return None

        viewed_today = self.repos.daily_counters.get_count(user_id, "profile_view")
        limit = self.daily_view_limit_for(user)
        if viewed_today >= limit:
            raise RateLimitedError()

        filters = self.repos.search_filters.get(user_id)
        seen = self.repos.likes.already_seen_ids(user_id)
        seen.add(user_id)

        candidates = self.repos.users.candidates_for(
            user_id=user_id,
            looking_for=user["looking_for"],
            own_gender=user["gender"],
            min_age=filters["min_age"],
            max_age=filters["max_age"],
            city=filters["city"],
            verified_only=bool(filters["verified_only"]),
            exclude_ids=seen,
            limit=5,
        )
        if not candidates:
            return None

        candidate = candidates[0]
        self.repos.daily_counters.increment_and_get(user_id, "profile_view")
        candidate["age"] = calc_age(candidate["birth_date"])
        candidate["photos"] = self.repos.media.list_for_user(candidate["user_id"])
        candidate["tags"] = self.repos.tags.for_user(candidate["user_id"])
        return candidate

class ChatService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def send_message(self, user_id: int, match_id: int, content: Optional[str],
                      content_type: str = "text", file_id: Optional[str] = None) -> dict:
        if not self.repos.matches.is_participant(match_id, user_id):
            raise PermissionError_("Вы не участвуете в этом мэтче.")

        one_minute_ago = (utcnow() - timedelta(minutes=1)).isoformat()
        recent = self.repos.chat.count_messages_since(match_id, user_id, one_minute_ago)
        if recent >= Config.MAX_MESSAGES_PER_MINUTE_CHAT:
            raise RateLimitedError()

        if content:
            content = sanitize_free_text(content)
            if not content:
                raise ValidationError("Сообщение не может быть пустым.")

        match = self.repos.matches.get(match_id)
        other_id = self.repos.matches.other_user(match, user_id)
        if self._is_blocked_by_punishment(user_id):
            raise PermissionError_("Вы временно заблокированы и не можете отправлять сообщения.")

        msg_id = self.repos.chat.add_message(match_id, user_id, content, content_type, file_id)
        self.repos.activity.log(user_id, "chat_message_sent", {"match_id": match_id})
        return {"id": msg_id, "match_id": match_id, "recipient_id": other_id}

    def _is_blocked_by_punishment(self, user_id: int) -> bool:
        return self.repos.punishments.has_active(user_id, PunishmentType.MUTE.value) or \
               self.repos.punishments.has_active(user_id, PunishmentType.BAN.value)

    def history(self, user_id: int, match_id: int) -> list[dict]:
        if not self.repos.matches.is_participant(match_id, user_id):
            raise PermissionError_("Вы не участвуете в этом мэтче.")
        return self.repos.chat.recent_messages(match_id)

class ModerationService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def file_complaint(self, reporter_id: int, target_id: int, reason: str, details: Optional[str]) -> int:
        if reporter_id == target_id:
            raise ValidationError("Нельзя пожаловаться на самого себя.")
        if not self.repos.users.exists(target_id):
            raise NotFoundError("Профиль не найден.")
        count_today = self.repos.complaints.count_today_by_reporter(reporter_id)
        if count_today >= Config.MAX_COMPLAINTS_PER_DAY:
            raise RateLimitedError()
        complaint_id = self.repos.complaints.create(reporter_id, target_id, reason, details)
        self.repos.activity.log(reporter_id, "complaint_filed", {"target": target_id, "reason": reason})
        return complaint_id

    def punish(
        self, target_id: int, ptype: str, reason: Optional[str], issued_by: int,
        duration: Optional[timedelta],
    ) -> int:
        pid = self.repos.punishments.issue(target_id, ptype, reason, issued_by, duration)
        if ptype == PunishmentType.BAN.value:
            self.repos.users.set_status(target_id, UserStatus.BANNED.value)
        self.repos.admin_log.log(issued_by, f"punishment_{ptype}", target_id, {"reason": reason})
        log.info(f"Наказание: target={target_id} type={ptype} issued_by={issued_by}")
        return pid

    def lift_punishment(self, target_id: int, ptype: str, lifted_by: int) -> None:
        self.repos.punishments.deactivate_all_of_type(target_id, ptype)
        if ptype == PunishmentType.BAN.value:
            user = self.repos.users.get(target_id)
            if user and user["status"] == UserStatus.BANNED.value:
                self.repos.users.set_status(target_id, UserStatus.ACTIVE.value)
        self.repos.admin_log.log(lifted_by, f"punishment_lifted_{ptype}", target_id)
        log.info(f"Наказание снято: target={target_id} type={ptype} lifted_by={lifted_by}")

    def is_banned(self, user_id: int) -> bool:
        return self.repos.punishments.has_active(user_id, PunishmentType.BAN.value)

    def is_shadowbanned(self, user_id: int) -> bool:
        return self.repos.punishments.has_active(user_id, PunishmentType.SHADOWBAN.value)

class PaymentService:
    def __init__(self, repos: Repos, db: Database):
        self.repos = repos
        self.db = db

    def credit_stars_topup(self, user_id: int, amount: int, telegram_payment_charge_id: str) -> int:
        if amount <= 0:
            raise ValidationError("Неверная сумма пополнения.")
        with self.db.tx() as conn:
            new_balance = self.repos.users.adjust_balance(conn, user_id, amount)
            self.repos.transactions.record(
                conn, user_id, TransactionType.TOPUP.value, amount, new_balance,
                "Пополнение Telegram Stars", telegram_payment_charge_id,
            )
        self.repos.activity.log(user_id, "stars_topup", {"amount": amount})
        log.info(f"Пополнение: user={user_id} amount={amount}")
        return new_balance

    def purchase_item(self, user_id: int, item_id: int) -> dict:
        item = self.repos.shop.get(item_id)
        if not item or not item["is_active"]:
            raise NotFoundError("Товар недоступен.")
        user = self.repos.users.get(user_id)
        if user["balance_stars"] < item["price_stars"]:
            raise ValidationError("Недостаточно звёзд. Пополните баланс.")

        payload = json.loads(item["payload"] or "{}")
        with self.db.tx() as conn:
            new_balance = self.repos.users.adjust_balance(conn, user_id, -item["price_stars"])
            self.repos.transactions.record(
                conn, user_id, TransactionType.PURCHASE.value, -item["price_stars"], new_balance,
                f"Покупка: {item['name']}", item["sku"],
            )
            if item["item_type"] in (PremiumTier.PREMIUM.value, PremiumTier.PREMIUM_PLUS.value):
                self._activate_premium(conn, user_id, item["item_type"], payload.get("duration_days", 30))
        self.repos.activity.log(user_id, "purchase", {"item": item["sku"]})
        log.info(f"Покупка: user={user_id} item={item['sku']}")
        return item

    def _activate_premium(self, conn: sqlite3.Connection, user_id: int, tier: str, duration_days: int) -> None:
        user = conn.execute("SELECT premium_until, premium_tier FROM users WHERE user_id = ?", (user_id,)).fetchone()
        base = utcnow()
        if user["premium_until"]:
            try:
                current_until = datetime.fromisoformat(user["premium_until"])
                if current_until > base and user["premium_tier"] == tier:
                    base = current_until
            except ValueError:
                pass
        new_until = base + timedelta(days=duration_days)
        conn.execute(
            "UPDATE users SET premium_tier = ?, premium_until = ?, updated_at = ? WHERE user_id = ?",
            (tier, new_until.isoformat(), utcnow_iso(), user_id),
        )
        log.info(f"Premium активирован: user={user_id} tier={tier} until={new_until.isoformat()}")

    def downgrade_expired_premiums(self) -> int:
        rows = self.repos.users.db.query_all(
            "SELECT user_id FROM users WHERE premium_tier != 'free' AND premium_until IS NOT NULL "
            "AND premium_until <= ?",
            (utcnow_iso(),),
        )
        count = 0
        for row in rows:
            self.repos.users.update_fields(row["user_id"], premium_tier=PremiumTier.FREE.value, premium_until=None)
            self.repos.activity.log(row["user_id"], "premium_expired")
            count += 1
        if count:
            log.info(f"Понижен уровень Premium у {count} пользователей")
        return count

class ReferralService:
    def __init__(self, repos: Repos, db: Database):
        self.repos = repos
        self.db = db

    def reward_if_eligible(self, referred_id: int) -> None:
        referral = self.repos.referrals.get_by_referred(referred_id)
        if not referral or referral["reward_given"]:
            return
        with self.db.tx() as conn:
            new_balance = self.repos.users.adjust_balance(conn, referral["referrer_id"], Config.REFERRAL_REWARD_STARS)
            self.repos.transactions.record(
                conn, referral["referrer_id"], TransactionType.REFERRAL_BONUS.value,
                Config.REFERRAL_REWARD_STARS, new_balance, f"Реферальный бонус за пользователя {referred_id}",
            )
            self.repos.referrals.mark_rewarded(conn, referral["id"])
        self.repos.activity.log(referral["referrer_id"], "referral_reward", {"referred": referred_id})
        log.info(f"Реферальный бонус: referrer={referral['referrer_id']} referred={referred_id}")

    def referral_link(self, bot_username: str, user: dict) -> str:
        return f"https://t.me/{bot_username}?start=ref_{user['public_id']}"

    def stats_for(self, user_id: int) -> dict:
        return {"total_referrals": self.repos.referrals.count_for_referrer(user_id)}

class RewardService:
    def __init__(self, repos: Repos, db: Database):
        self.repos = repos
        self.db = db

    def claim_daily(self, user_id: int) -> tuple[int, int]:
        today = date.today()
        record = self.repos.daily_rewards.get(user_id)
        streak = 1
        if record and record["last_claim_date"]:
            last = date.fromisoformat(record["last_claim_date"])
            if last == today:
                raise ValidationError("Вы уже получили ежедневную награду сегодня. Возвращайтесь завтра!")
            streak = record["streak"] + 1 if (today - last).days == 1 else 1

        bonus = min(streak - 1, Config.DAILY_REWARD_STREAK_BONUS_CAP)
        stars = Config.DAILY_REWARD_BASE_STARS + bonus
        with self.db.tx() as conn:
            new_balance = self.repos.users.adjust_balance(conn, user_id, stars)
            self.repos.transactions.record(
                conn, user_id, TransactionType.REWARD.value, stars, new_balance,
                f"Ежедневная награда (серия {streak} дн.)",
            )
            self.repos.daily_rewards.upsert(conn, user_id, today.isoformat(), streak)
        self.repos.activity.log(user_id, "daily_reward_claimed", {"streak": streak, "stars": stars})
        log.info(f"Ежедневная награда: user={user_id} streak={streak} stars={stars}")
        return stars, streak

class StatsService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def platform_overview(self) -> dict:
        summary = self.repos.users.stats_summary()
        summary["pending_verifications"] = self.repos.verification.pending_count()
        summary["pending_complaints"] = self.repos.complaints.pending_count()
        since = (utcnow() - timedelta(days=1)).isoformat()
        summary["activity_last_24h"] = self.repos.activity.counts_by_action_since(since)
        return summary

class CleanupService:
    def __init__(self, repos: Repos):
        self.repos = repos

    def run(self) -> dict:
        hide_cutoff = (utcnow() - timedelta(days=Config.INACTIVE_PROFILE_DAYS)).isoformat()
        delete_cutoff = (utcnow() - timedelta(days=Config.INACTIVE_PROFILE_DELETE_DAYS)).isoformat()

        to_hide = self.repos.users.find_inactive_before(hide_cutoff, (UserStatus.ACTIVE.value,))
        for u in to_hide:
            self.repos.users.set_status(u["user_id"], UserStatus.HIDDEN.value)
            self.repos.activity.log(u["user_id"], "auto_hidden_inactive")

        to_delete = self.repos.users.find_inactive_before(delete_cutoff, (UserStatus.HIDDEN.value,))
        for u in to_delete:
            self.repos.users.set_status(u["user_id"], UserStatus.DELETED.value)
            self.repos.activity.log(u["user_id"], "auto_deleted_inactive")

        log.info(f"Очистка неактивных: скрыто {len(to_hide)}, удалено {len(to_delete)}")
        return {"hidden": len(to_hide), "deleted": len(to_delete)}

@dataclass
class Services:
    repos: Repos
    db: Database
    registration: RegistrationService
    profile: ProfileService
    verification: VerificationService
    match: MatchService
    search: SearchService
    chat: ChatService
    moderation: ModerationService
    payment: PaymentService
    referral: ReferralService
    reward: RewardService
    stats: StatsService
    cleanup: CleanupService

    @classmethod
    def build(cls, db: Database) -> "Services":
        repos = Repos.build(db)
        return cls(
            repos=repos, db=db,
            registration=RegistrationService(repos),
            profile=ProfileService(repos),
            verification=VerificationService(repos),
            match=MatchService(repos, db),
            search=SearchService(repos),
            chat=ChatService(repos),
            moderation=ModerationService(repos),
            payment=PaymentService(repos, db),
            referral=ReferralService(repos, db),
            reward=RewardService(repos, db),
            stats=StatsService(repos),
            cleanup=CleanupService(repos),
        )

class RateLimiter:
    def __init__(self, window_seconds: int, max_actions: int):
        self.window = window_seconds
        self.max_actions = max_actions
        self._events: dict[int, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: int) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(user_id, [])
            cutoff = now - self.window
            while events and events[0] < cutoff:
                events.pop(0)
            if len(events) >= self.max_actions:
                log.debug(f"Rate limit превышен для пользователя {user_id}")
                return False
            events.append(now)
            return True

    def sweep(self) -> None:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            stale = [uid for uid, evs in self._events.items() if not evs or evs[-1] < cutoff]
            for uid in stale:
                del self._events[uid]

class FloodGuard:
    def __init__(self, moderation: ModerationService, threshold: int = 5):
        self.moderation = moderation
        self.threshold = threshold
        self._strikes: dict[int, int] = {}
        self._lock = threading.Lock()

    def strike(self, user_id: int) -> None:
        with self._lock:
            self._strikes[user_id] = self._strikes.get(user_id, 0) + 1
            count = self._strikes[user_id]
        if count >= self.threshold:
            self.moderation.punish(
                user_id, PunishmentType.MUTE.value, "Автоматически: многократное превышение лимита",
                issued_by=None, duration=timedelta(seconds=Config.FLOOD_MUTE_SECONDS),
            )
            log.info(f"Автоматический мут за флуд: user={user_id}")
            with self._lock:
                self._strikes[user_id] = 0

    def reset(self, user_id: int) -> None:
        with self._lock:
            self._strikes.pop(user_id, None)

class KB:
    @staticmethod
    def main_menu(is_moderator: bool, is_admin: bool) -> types.ReplyKeyboardMarkup:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add(types.KeyboardButton("🔍 Поиск"), types.KeyboardButton("👤 Мой профиль"))
        kb.add(types.KeyboardButton("💌 Лайки и мэтчи"), types.KeyboardButton("💬 Чаты"))
        kb.add(types.KeyboardButton("⭐ Premium и магазин"), types.KeyboardButton("🎁 Ежедневная награда"))
        kb.add(types.KeyboardButton("👥 Рефералы"), types.KeyboardButton("⚙️ Настройки"))
        if is_moderator:
            kb.add(types.KeyboardButton("🛡 Панель модератора"))
        if is_admin:
            kb.add(types.KeyboardButton("🛠 Панель админа"))
        return kb

    @staticmethod
    def gender_select(prefix: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("👨 Мужской", callback_data=f"{prefix}{CALLBACK_SEP}male"),
            types.InlineKeyboardButton("👩 Женский", callback_data=f"{prefix}{CALLBACK_SEP}female"),
        )
        return kb

    @staticmethod
    def looking_for_select() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("👨 Мужчин", callback_data=f"reglf{CALLBACK_SEP}male"),
            types.InlineKeyboardButton("👩 Женщин", callback_data=f"reglf{CALLBACK_SEP}female"),
            types.InlineKeyboardButton("💫 Всех", callback_data=f"reglf{CALLBACK_SEP}any"),
        )
        return kb

    @staticmethod
    def photo_done() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Готово", callback_data="regphoto:done"))
        return kb

    @staticmethod
    def tags_select(all_tags: list[dict], selected_ids: set[int], done_cb: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        buttons = []
        for tag in all_tags:
            mark = "✅ " if tag["id"] in selected_ids else ""
            buttons.append(
                types.InlineKeyboardButton(f"{mark}{tag['name']}", callback_data=f"tag{CALLBACK_SEP}{tag['id']}")
            )
        kb.add(*buttons)
        kb.add(types.InlineKeyboardButton("✅ Готово", callback_data=done_cb))
        return kb

    @staticmethod
    def discover_actions(target_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("👎 Мимо", callback_data=f"dislike{CALLBACK_SEP}{target_id}"),
            types.InlineKeyboardButton("⚠️ Жалоба", callback_data=f"reportstart{CALLBACK_SEP}{target_id}"),
            types.InlineKeyboardButton("❤️ Лайк", callback_data=f"like{CALLBACK_SEP}{target_id}"),
        )
        return kb

    @staticmethod
    def match_notification(match_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💬 Сказать привет", callback_data=f"openchat{CALLBACK_SEP}{match_id}"))
        return kb

    @staticmethod
    def profile_menu() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("✏️ Изменить имя", callback_data="editprofile:name"),
            types.InlineKeyboardButton("✏️ Изменить «О себе»", callback_data="editprofile:about"),
        )
        kb.add(
            types.InlineKeyboardButton("✏️ Изменить город", callback_data="editprofile:city"),
            types.InlineKeyboardButton("📷 Фото", callback_data="editprofile:photos"),
        )
        kb.add(
            types.InlineKeyboardButton("🏷 Интересы", callback_data="editprofile:tags"),
            types.InlineKeyboardButton("🎥 Верификация", callback_data="editprofile:verify"),
        )
        kb.add(
            types.InlineKeyboardButton("🙈 Скрыть профиль", callback_data="editprofile:hide"),
            types.InlineKeyboardButton("🗑 Удалить профиль", callback_data="editprofile:delete"),
        )
        return kb

    @staticmethod
    def confirm(action: str, entity_id: Any) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm{CALLBACK_SEP}{action}{CALLBACK_SEP}{entity_id}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="confirm:cancel:0"),
        )
        return kb

    @staticmethod
    def matches_list(matches: list[dict], names: dict[int, str]) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for m in matches:
            other = m["other_user_id"]
            name = names.get(other, f"Пользователь {other}")
            kb.add(types.InlineKeyboardButton(f"💬 {name}", callback_data=f"openchat{CALLBACK_SEP}{m['id']}"))
        return kb

    @staticmethod
    def likes_received_nav(target_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("👎 Мимо", callback_data=f"dislike{CALLBACK_SEP}{target_id}"),
            types.InlineKeyboardButton("❤️ Лайк в ответ", callback_data=f"like{CALLBACK_SEP}{target_id}"),
        )
        return kb

    @staticmethod
    def shop_menu(items: list[dict]) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for item in items:
            kb.add(types.InlineKeyboardButton(
                f"{item['name']} — ⭐{item['price_stars']}",
                callback_data=f"buy{CALLBACK_SEP}{item['id']}",
            ))
        return kb

    @staticmethod
    def moderator_panel() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🎥 Очередь верификации", callback_data="mod:verifqueue"),
            types.InlineKeyboardButton("🚨 Очередь жалоб", callback_data="mod:complaintqueue"),
            types.InlineKeyboardButton("🔎 Поиск по ID", callback_data="mod:searchid"),
        )
        return kb

    @staticmethod
    def verification_review(req_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"vrev{CALLBACK_SEP}approve{CALLBACK_SEP}{req_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"vrev{CALLBACK_SEP}reject{CALLBACK_SEP}{req_id}"),
        )
        return kb

    @staticmethod
    def complaint_review(complaint_id: int, target_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("👁 Профиль", callback_data=f"admviewuser{CALLBACK_SEP}{target_id}"),
            types.InlineKeyboardButton("✅ Отклонить жалобу", callback_data=f"crev{CALLBACK_SEP}dismiss{CALLBACK_SEP}{complaint_id}"),
        )
        kb.add(
            types.InlineKeyboardButton("⚠️ Предупредить", callback_data=f"crev{CALLBACK_SEP}warn{CALLBACK_SEP}{complaint_id}"),
            types.InlineKeyboardButton("🔇 Заглушить на 24ч", callback_data=f"crev{CALLBACK_SEP}mute{CALLBACK_SEP}{complaint_id}"),
        )
        kb.add(types.InlineKeyboardButton("⛔ Забанить", callback_data=f"crev{CALLBACK_SEP}ban{CALLBACK_SEP}{complaint_id}"))
        return kb

    @staticmethod
    def admin_panel() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📊 Статистика платформы", callback_data="adm:stats"),
            types.InlineKeyboardButton("🔎 Поиск по ID", callback_data="adm:searchid"),
            types.InlineKeyboardButton("📢 Рассылка", callback_data="adm:broadcast"),
            types.InlineKeyboardButton("📜 Журнал действий", callback_data="adm:log"),
        )
        return kb

    @staticmethod
    def admin_user_actions(user_id: int, user_role: str, viewer_role: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("⛔ Забанить", callback_data=f"adm{CALLBACK_SEP}ban{CALLBACK_SEP}{user_id}"),
            types.InlineKeyboardButton("♻️ Разбанить", callback_data=f"adm{CALLBACK_SEP}unban{CALLBACK_SEP}{user_id}"),
        )
        kb.add(
            types.InlineKeyboardButton("⚠️ Предупредить", callback_data=f"adm{CALLBACK_SEP}warn{CALLBACK_SEP}{user_id}"),
            types.InlineKeyboardButton("✅ Снять предупреждение", callback_data=f"adm{CALLBACK_SEP}unwarn{CALLBACK_SEP}{user_id}"),
        )
        kb.add(
            types.InlineKeyboardButton("⬆️ Назначить модератором", callback_data=f"adm{CALLBACK_SEP}makemod{CALLBACK_SEP}{user_id}"),
            types.InlineKeyboardButton("⬇️ Снять модератора", callback_data=f"adm{CALLBACK_SEP}unmod{CALLBACK_SEP}{user_id}"),
        )
        if viewer_role in ("admin", "owner"):
            kb.add(
                types.InlineKeyboardButton("👑 Назначить админом", callback_data=f"adm{CALLBACK_SEP}makeadmin{CALLBACK_SEP}{user_id}"),
                types.InlineKeyboardButton("🔽 Снять админа", callback_data=f"adm{CALLBACK_SEP}unadmin{CALLBACK_SEP}{user_id}"),
            )
        if viewer_role == "owner":
            kb.add(
                types.InlineKeyboardButton("💰 Выдать звёзды", callback_data=f"adm{CALLBACK_SEP}givestars{CALLBACK_SEP}{user_id}"),
                types.InlineKeyboardButton("💸 Обнулить звёзды", callback_data=f"adm{CALLBACK_SEP}resetstars{CALLBACK_SEP}{user_id}"),
            )
            kb.add(
                types.InlineKeyboardButton("⭐ Выдать Premium", callback_data=f"adm{CALLBACK_SEP}givepremium{CALLBACK_SEP}{user_id}"),
                types.InlineKeyboardButton("❌ Снять Premium", callback_data=f"adm{CALLBACK_SEP}removepremium{CALLBACK_SEP}{user_id}"),
            )
        return kb

    @staticmethod
    def cancel_inline() -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="generic:cancel"))
        return kb

    @staticmethod
    def remove() -> types.ReplyKeyboardRemove:
        return types.ReplyKeyboardRemove()

bot = telebot.TeleBot(Config.BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=8)
db = Database(Config.DB_PATH)
svc = Services.build(db)
svc.repos.tags.ensure_catalog(TAG_CATALOG)
svc.repos.shop.ensure_defaults()

generic_limiter = RateLimiter(Config.RATE_LIMIT_WINDOW_SECONDS, Config.RATE_LIMIT_MAX_ACTIONS)
flood_guard = FloodGuard(svc.moderation)

_BOT_USERNAME_CACHE: dict[str, str] = {}

def bot_username() -> str:
    if "u" not in _BOT_USERNAME_CACHE:
        _BOT_USERNAME_CACHE["u"] = bot.get_me().username
        log.info(f"Получено имя бота: @{_BOT_USERNAME_CACHE['u']}")
    return _BOT_USERNAME_CACHE["u"]

def safe_answer_callback(call: types.CallbackQuery, text: str = "", show_alert: bool = False) -> None:
    try:
        bot.answer_callback_query(call.id, text=text, show_alert=show_alert)
    except ApiTelegramException as e:
        log.debug(f"Ошибка answer_callback_query для {call.from_user.id}: {e}")

def safe_send(chat_id: int, text: str, **kwargs) -> Optional[types.Message]:
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except ApiTelegramException as e:
        log.warning(f"Ошибка отправки сообщения для {chat_id}: {e}")
        return None

def guarded(handler: Callable) -> Callable:
    def wrapper(update, *args, **kwargs):
        user = getattr(update, "from_user", None)
        user_id = user.id if user else None
        chat_id = None
        if isinstance(update, types.Message):
            chat_id = update.chat.id
        elif isinstance(update, types.CallbackQuery):
            chat_id = update.message.chat.id if update.message else user_id

        try:
            if user_id is not None:
                if not generic_limiter.check(user_id):
                    flood_guard.strike(user_id)
                    if isinstance(update, types.CallbackQuery):
                        safe_answer_callback(update, "⏳ Пожалуйста, помедленнее.", show_alert=True)
                    return
                if svc.moderation.is_banned(user_id):
                    if isinstance(update, types.CallbackQuery):
                        safe_answer_callback(update, "🚫 Ваш аккаунт заблокирован.", show_alert=True)
                    else:
                        safe_send(chat_id, "🚫 Ваш аккаунт заблокирован. Свяжитесь с поддержкой, если считаете это ошибкой.")
                    return
            return handler(update, *args, **kwargs)
        except RateLimitedError:
            msg = "⏳ Вы достигли дневного лимита для этого действия. Приобретите Premium для расширения лимитов или попробуйте завтра."
            if isinstance(update, types.CallbackQuery):
                safe_answer_callback(update, msg, show_alert=True)
            elif chat_id is not None:
                safe_send(chat_id, msg)
        except ValidationError as e:
            msg = f"⚠️ {e}"
            if isinstance(update, types.CallbackQuery):
                safe_answer_callback(update, msg, show_alert=True)
            elif chat_id is not None:
                safe_send(chat_id, msg)
        except PermissionError_ as e:
            msg = f"🚫 {e}"
            if isinstance(update, types.CallbackQuery):
                safe_answer_callback(update, msg, show_alert=True)
            elif chat_id is not None:
                safe_send(chat_id, msg)
        except NotFoundError as e:
            msg = f"❓ {e}"
            if isinstance(update, types.CallbackQuery):
                safe_answer_callback(update, msg, show_alert=True)
            elif chat_id is not None:
                safe_send(chat_id, msg)
        except Exception as e:
            log.error(
                f"Необработанное исключение в обработчике для пользователя {user_id}: "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            if chat_id is not None:
                safe_send(chat_id, "⚠️ Что-то пошло не так. Наша команда уведомлена — попробуйте позже.")

    return wrapper

def require_registered(func: Callable) -> Callable:
    def wrapper(update, *args, **kwargs):
        user_id = update.from_user.id
        chat_id = update.chat.id if isinstance(update, types.Message) else update.message.chat.id
        user = svc.repos.users.get(user_id)
        if not user or user["status"] == UserStatus.DELETED.value:
            safe_send(chat_id, "У вас ещё нет активного профиля. Отправьте /start, чтобы создать его!")
            return
        svc.repos.users.touch_active(user_id)
        return func(update, *args, **kwargs)

    return wrapper

def require_role(*roles: str):
    def decorator(func: Callable) -> Callable:
        def wrapper(update, *args, **kwargs):
            user_id = update.from_user.id
            chat_id = update.chat.id if isinstance(update, types.Message) else update.message.chat.id
            user = svc.repos.users.get(user_id)
            if not user or user["role"] not in roles:
                log.warning(f"Попытка доступа без прав: user={user_id} required_roles={roles}")
                safe_send(chat_id, "🚫 У вас нет доступа к этому разделу.")
                return
            return func(update, *args, **kwargs)

        return wrapper

    return decorator

MOD_ROLES = (UserRole.MODERATOR.value, UserRole.ADMIN.value, UserRole.OWNER.value)
ADMIN_ROLES = (UserRole.ADMIN.value, UserRole.OWNER.value)

def format_profile_card(profile: dict, show_public_id: bool = True) -> str:
    badge = " ✅" if profile["verification_status"] == VerificationStatus.APPROVED.value else ""
    tier = profile["premium_tier"]
    premium_badge = " 💎" if tier == PremiumTier.PREMIUM_PLUS.value else (" ⭐" if tier == PremiumTier.PREMIUM.value else "")
    lines = [f"<b>{profile['display_name']}, {profile['age']}</b>{badge}{premium_badge}"]
    if profile.get("city"):
        lines.append(f"📍 {profile['city']}")
    if show_public_id:
        lines.append(f"🆔 {profile['public_id']}")
    if profile.get("tags"):
        lines.append("🏷 " + ", ".join(t["name"] for t in profile["tags"]))
    if profile.get("about"):
        lines.append("")
        lines.append(profile["about"])
    return "\n".join(lines)

def send_profile_card(chat_id: int, profile: dict, keyboard=None) -> None:
    caption = format_profile_card(profile)
    photos = profile.get("photos") or []
    try:
        if photos:
            if len(photos) == 1:
                bot.send_photo(chat_id, photos[0]["file_id"], caption=caption, reply_markup=keyboard)
            else:
                media = [types.InputMediaPhoto(p["file_id"]) for p in photos]
                media[0].caption = caption
                media[0].parse_mode = "HTML"
                bot.send_media_group(chat_id, media)
                if keyboard is not None:
                    bot.send_message(chat_id, "⬆️ Профиль выше", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, caption, reply_markup=keyboard)
    except ApiTelegramException as e:
        log.warning(f"Ошибка отправки карточки профиля в чат {chat_id}: {e}")
        bot.send_message(chat_id, caption, reply_markup=keyboard)

def notify_match(match_id: int, user_a: int, user_b: int) -> None:
    profile_a = svc.profile.get_full_profile(user_a)
    profile_b = svc.profile.get_full_profile(user_b)
    if profile_a:
        safe_send(
            user_b, f"🎉 Это мэтч с <b>{profile_a['display_name']}</b>!",
            reply_markup=KB.match_notification(match_id),
        )
    if profile_b:
        safe_send(
            user_a, f"🎉 Это мэтч с <b>{profile_b['display_name']}</b>!",
            reply_markup=KB.match_notification(match_id),
        )
    log.info(f"Уведомление о мэтче отправлено: {user_a} <-> {user_b}")

@bot.message_handler(commands=["start"])
@guarded
def handle_start(message: types.Message) -> None:
    user_id = message.from_user.id
    existing = svc.repos.users.get(user_id)
    log.info(f"Команда /start от пользователя {user_id} (существует: {existing is not None})")

    referrer_public_id = None
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_"):
        referrer_public_id = parts[1][4:].strip()

    if existing:
        svc.repos.users.touch_active(user_id)
        if existing["status"] == UserStatus.DELETED.value:
            bot.send_message(
                message.chat.id,
                "С возвращением! Ваш предыдущий профиль был удалён. Хотите восстановить его?",
                reply_markup=KB.confirm("restore_profile", user_id),
            )
            return
        is_mod = existing["role"] in MOD_ROLES
        is_admin = existing["role"] in ADMIN_ROLES
        bot.send_message(
            message.chat.id,
            f"С возвращением, {existing['display_name']}! 👋",
            reply_markup=KB.main_menu(is_mod, is_admin),
        )
        return

    svc.repos.state.set(user_id, BotState.REG_GENDER.value, {"referrer": referrer_public_id})
    bot.send_message(
        message.chat.id,
        "👋 <b>Добро пожаловать на платформу знакомств!</b>\n\n"
        "Давайте создадим ваш профиль. Для начала — ваш пол?",
        reply_markup=KB.gender_select("reggender"),
    )

@bot.message_handler(commands=["help"])
@guarded
def handle_help(message: types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "<b>Доступные команды</b>\n"
        "/start — Создать или вернуться к профилю\n"
        "/profile — Посмотреть свой профиль\n"
        "/discover — Искать анкеты\n"
        "/matches — Ваши мэтчи\n"
        "/shop — Premium и магазин\n"
        "/referral — Ваша реферальная ссылка\n"
        "/cancel — Отменить текущее действие\n\n"
        "Нужна помощь? Используйте кнопку ⚠️ Жалоба на любом профиле, чтобы связаться с модераторами.",
    )

@bot.message_handler(commands=["cancel"])
@guarded
def handle_cancel(message: types.Message) -> None:
    user_id = message.from_user.id
    svc.repos.state.clear(user_id)
    log.info(f"Пользователь {user_id} отменил текущее действие")
    bot.send_message(message.chat.id, "❌ Отменено. Возвращаемся в главное меню.", reply_markup=KB.remove())

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm:restore_profile"))
@guarded
def cb_confirm_restore(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    svc.profile.restore_profile(user_id)
    user = svc.repos.users.get(user_id)
    is_mod = user["role"] in MOD_ROLES
    is_admin = user["role"] in ADMIN_ROLES
    safe_answer_callback(call, "Профиль восстановлен!")
    bot.send_message(call.message.chat.id, "✅ Ваш профиль восстановлен!", reply_markup=KB.main_menu(is_mod, is_admin))

@bot.callback_query_handler(func=lambda c: c.data == "confirm:cancel:0")
@guarded
def cb_confirm_cancel(call: types.CallbackQuery) -> None:
    safe_answer_callback(call, "Отменено.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except ApiTelegramException:
        pass

@bot.callback_query_handler(func=lambda c: c.data == "generic:cancel")
@guarded
def cb_generic_cancel(call: types.CallbackQuery) -> None:
    svc.repos.state.clear(call.from_user.id)
    safe_answer_callback(call, "Отменено.")
    safe_send(call.message.chat.id, "❌ Отменено.")

def _in_state(user_id: int, *states: str) -> bool:
    state, _ = svc.repos.state.get(user_id)
    return state in states

@bot.callback_query_handler(func=lambda c: c.data.startswith("reggender:"))
@guarded
def cb_reg_gender(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    if not _in_state(user_id, BotState.REG_GENDER.value):
        return safe_answer_callback(call)
    gender = call.data.split(CALLBACK_SEP)[1]
    data = svc.repos.state.update_data(user_id, gender=gender)
    svc.repos.state.set(user_id, BotState.REG_LOOKING_FOR.value, data)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Кто вас интересует?", reply_markup=KB.looking_for_select())

@bot.callback_query_handler(func=lambda c: c.data.startswith("reglf:"))
@guarded
def cb_reg_looking_for(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    if not _in_state(user_id, BotState.REG_LOOKING_FOR.value):
        return safe_answer_callback(call)
    looking_for = call.data.split(CALLBACK_SEP)[1]
    data = svc.repos.state.update_data(user_id, looking_for=looking_for)
    svc.repos.state.set(user_id, BotState.REG_NAME.value, data)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Отлично! Какое имя отображать в вашем профиле?")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.REG_NAME.value), content_types=["text"])
@guarded
def msg_reg_name(message: types.Message) -> None:
    user_id = message.from_user.id
    name = validate_name(message.text)
    data = svc.repos.state.update_data(user_id, display_name=name)
    svc.repos.state.set(user_id, BotState.REG_BIRTHDATE.value, data)
    bot.send_message(message.chat.id, "Когда вы родились? (ДД.ММ.ГГГГ)")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.REG_BIRTHDATE.value), content_types=["text"])
@guarded
def msg_reg_birthdate(message: types.Message) -> None:
    user_id = message.from_user.id
    bdate = validate_birth_date(message.text)
    data = svc.repos.state.update_data(user_id, birth_date=bdate.isoformat())
    svc.repos.state.set(user_id, BotState.REG_CITY.value, data)
    bot.send_message(message.chat.id, "В каком вы городе? (Это поможет найти людей поблизости)")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.REG_CITY.value), content_types=["text"])
@guarded
def msg_reg_city(message: types.Message) -> None:
    user_id = message.from_user.id
    city = validate_city(message.text)
    data = svc.repos.state.update_data(user_id, city=city)
    svc.repos.state.set(user_id, BotState.REG_ABOUT.value, data)
    bot.send_message(message.chat.id, "Расскажите немного о себе (или отправьте /skip, чтобы пропустить):")

@bot.message_handler(commands=["skip"])
@guarded
def msg_skip(message: types.Message) -> None:
    user_id = message.from_user.id
    state, data = svc.repos.state.get(user_id)
    if state == BotState.REG_ABOUT.value:
        data["about"] = None
        svc.repos.state.set(user_id, BotState.REG_PHOTO.value, data)
        bot.send_message(message.chat.id, "Теперь отправьте от 1 до 5 фото для профиля. Отправляйте по одному, затем нажмите «Готово».", reply_markup=KB.photo_done())
    elif state == BotState.EDIT_ABOUT.value:
        svc.repos.state.clear(user_id)
        bot.send_message(message.chat.id, "Оставлен прежний текст «О себе».")
    elif state == BotState.AWAITING_COMPLAINT_REASON.value:
        svc.moderation.file_complaint(user_id, data["target_id"], data["reason"], None)
        svc.repos.state.clear(user_id)
        bot.send_message(message.chat.id, "✅ Спасибо, наша команда модерации рассмотрит эту жалобу.")
    else:
        bot.send_message(message.chat.id, "Сейчас нечего пропускать.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.REG_ABOUT.value), content_types=["text"])
@guarded
def msg_reg_about(message: types.Message) -> None:
    user_id = message.from_user.id
    about = validate_about(message.text)
    data = svc.repos.state.update_data(user_id, about=about)
    svc.repos.state.set(user_id, BotState.REG_PHOTO.value, data)
    bot.send_message(
        message.chat.id,
        "📷 Теперь отправьте от 1 до 5 фото для профиля. Отправляйте по одному, затем нажмите «Готово».",
        reply_markup=KB.photo_done(),
    )

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.REG_PHOTO.value, BotState.EDIT_PHOTO.value),
    content_types=["photo"],
)
@guarded
def msg_reg_photo(message: types.Message) -> None:
    user_id = message.from_user.id
    state, data = svc.repos.state.get(user_id)
    file_id = message.photo[-1].file_id

    if state == BotState.EDIT_PHOTO.value:
        svc.profile.add_photo(user_id, file_id)
        count = svc.repos.media.count_for_user(user_id)
        bot.send_message(message.chat.id, f"✅ Фото добавлено ({count}/{Config.MAX_PHOTOS_PER_PROFILE}).", reply_markup=KB.photo_done())
        return

    photos = data.setdefault("photos", [])
    if len(photos) >= Config.MAX_PHOTOS_PER_PROFILE:
        bot.send_message(message.chat.id, f"Вы достигли максимума в {Config.MAX_PHOTOS_PER_PROFILE} фото. Нажмите «Готово».")
        return
    photos.append(file_id)
    svc.repos.state.set(user_id, state, data)
    bot.send_message(
        message.chat.id,
        f"✅ Фото {len(photos)}/{Config.MAX_PHOTOS_PER_PROFILE} добавлено. Отправьте ещё или нажмите «Готово».",
        reply_markup=KB.photo_done(),
    )

@bot.callback_query_handler(func=lambda c: c.data == "regphoto:done")
@guarded
def cb_reg_photo_done(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    state, data = svc.repos.state.get(user_id)

    if state == BotState.EDIT_PHOTO.value:
        svc.repos.state.clear(user_id)
        safe_answer_callback(call, "Готово!")
        bot.send_message(call.message.chat.id, "✅ Фото обновлены.")
        return

    if state != BotState.REG_PHOTO.value:
        return safe_answer_callback(call)

    photos = data.get("photos", [])
    if not photos:
        return safe_answer_callback(call, "Добавьте хотя бы 1 фото.", show_alert=True)

    svc.repos.state.set(user_id, BotState.REG_TAGS.value, data)
    safe_answer_callback(call, "Фото сохранены!")
    all_tags = svc.repos.tags.all()
    bot.send_message(
        call.message.chat.id,
        f"🏷 И напоследок — выберите до {Config.MAX_TAGS_PER_PROFILE} интересов (нажимайте для выбора, затем «Готово»):",
        reply_markup=KB.tags_select(all_tags, set(), "regtags:done"),
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("tag:"))
@guarded
def cb_toggle_tag(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    state, data = svc.repos.state.get(user_id)
    if state not in (BotState.REG_TAGS.value, BotState.EDIT_TAGS.value):
        return safe_answer_callback(call)

    tag_id = int(call.data.split(CALLBACK_SEP)[1])
    selected: set[int] = set(data.get("selected_tags", []))

    if state == BotState.REG_TAGS.value:
        if tag_id in selected:
            selected.discard(tag_id)
        elif len(selected) < Config.MAX_TAGS_PER_PROFILE:
            selected.add(tag_id)
        else:
            return safe_answer_callback(call, "Достигнут максимум тегов.", show_alert=True)
        data["selected_tags"] = list(selected)
        svc.repos.state.set(user_id, state, data)
    else:
        try:
            svc.profile.toggle_tag(user_id, tag_id)
        except ValidationError as e:
            return safe_answer_callback(call, str(e), show_alert=True)

    safe_answer_callback(call)
    current_selected = set(data.get("selected_tags", [])) if state == BotState.REG_TAGS.value else \
        {t["id"] for t in svc.repos.tags.for_user(user_id)}
    done_cb = "regtags:done" if state == BotState.REG_TAGS.value else "edittags:done"
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id,
            reply_markup=KB.tags_select(svc.repos.tags.all(), current_selected, done_cb),
        )
    except ApiTelegramException:
        pass

@bot.callback_query_handler(func=lambda c: c.data == "regtags:done")
@guarded
def cb_reg_tags_done(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    state, data = svc.repos.state.get(user_id)
    if state != BotState.REG_TAGS.value:
        return safe_answer_callback(call)

    bdate = date.fromisoformat(data["birth_date"])
    user = svc.registration.register(
        user_id=user_id,
        username=call.from_user.username,
        display_name=data["display_name"],
        gender=data["gender"],
        looking_for=data["looking_for"],
        birth_date=bdate,
        city=data.get("city"),
        about=data.get("about"),
        referrer_public_id=data.get("referrer"),
    )
    for file_id in data.get("photos", []):
        svc.repos.media.add(user_id, file_id, "photo")
    for tag_id in data.get("selected_tags", []):
        try:
            svc.repos.tags.toggle(user_id, tag_id, Config.MAX_TAGS_PER_PROFILE)
        except ValidationError:
            break

    svc.repos.state.clear(user_id)
    safe_answer_callback(call, "Профиль создан! 🎉")
    is_mod = user["role"] in MOD_ROLES
    is_admin = user["role"] in ADMIN_ROLES
    bot.send_message(
        call.message.chat.id,
        "🎉 <b>Ваш профиль готов!</b>\n\nИспользуйте меню ниже, чтобы начать знакомиться.",
        reply_markup=KB.main_menu(is_mod, is_admin),
    )

@bot.callback_query_handler(func=lambda c: c.data == "edittags:done")
@guarded
def cb_edit_tags_done(call: types.CallbackQuery) -> None:
    svc.repos.state.clear(call.from_user.id)
    safe_answer_callback(call, "Теги обновлены!")
    bot.send_message(call.message.chat.id, "✅ Ваши интересы обновлены.")

@bot.message_handler(func=lambda m: m.text == "👤 Мой профиль")
@guarded
@require_registered
def menu_my_profile(message: types.Message) -> None:
    profile = svc.profile.get_full_profile(message.from_user.id)
    send_profile_card(message.chat.id, profile, keyboard=KB.profile_menu())

@bot.message_handler(commands=["profile"])
@guarded
@require_registered
def cmd_profile(message: types.Message) -> None:
    menu_my_profile(message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("editprofile:"))
@guarded
@require_registered
def cb_edit_profile(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    action = call.data.split(CALLBACK_SEP)[1]
    safe_answer_callback(call)

    if action == "name":
        svc.repos.state.set(user_id, BotState.EDIT_NAME.value)
        bot.send_message(call.message.chat.id, "Введите новое имя:")
    elif action == "about":
        svc.repos.state.set(user_id, BotState.EDIT_ABOUT.value)
        bot.send_message(call.message.chat.id, "Введите новый текст «О себе» (или /skip, чтобы оставить прежний):")
    elif action == "city":
        svc.repos.state.set(user_id, BotState.EDIT_CITY.value)
        bot.send_message(call.message.chat.id, "Введите новый город:")
    elif action == "photos":
        count = svc.repos.media.count_for_user(user_id)
        if count >= Config.MAX_PHOTOS_PER_PROFILE:
            bot.send_message(
                call.message.chat.id,
                f"У вас уже максимум ({Config.MAX_PHOTOS_PER_PROFILE}) фото. Сначала удалите лишние через /myphotos.",
            )
            return
        svc.repos.state.set(user_id, BotState.EDIT_PHOTO.value)
        bot.send_message(call.message.chat.id, "Отправьте новое фото:", reply_markup=KB.photo_done())
    elif action == "tags":
        svc.repos.state.set(user_id, BotState.EDIT_TAGS.value)
        selected = {t["id"] for t in svc.repos.tags.for_user(user_id)}
        bot.send_message(
            call.message.chat.id, "Обновите ваши интересы:",
            reply_markup=KB.tags_select(svc.repos.tags.all(), selected, "edittags:done"),
        )
    elif action == "verify":
        if svc.repos.verification.has_pending(user_id):
            bot.send_message(call.message.chat.id, "У вас уже есть ожидающая заявка на верификацию.")
            return
        svc.repos.state.set(user_id, BotState.AWAITING_VERIFICATION_VIDEO.value)
        bot.send_message(
            call.message.chat.id,
            "🎥 Пожалуйста, отправьте короткий видеокружок (до "
            f"{Config.VERIFICATION_VIDEO_MAX_DURATION}с), на котором вы машете рукой и "
            "называете сегодняшнюю дату, чтобы модератор мог подтвердить, что это действительно вы.",
        )
    elif action == "hide":
        bot.send_message(call.message.chat.id, "Скрыть профиль из поиска? Вы сможете снова сделать его видимым в любое время.",
                          reply_markup=KB.confirm("hide_profile", user_id))
    elif action == "delete":
        bot.send_message(call.message.chat.id, "⚠️ Это удалит ваш профиль. Его можно будет восстановить позже, отправив /start.",
                          reply_markup=KB.confirm("delete_profile", user_id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm:hide_profile"))
@guarded
@require_registered
def cb_confirm_hide(call: types.CallbackQuery) -> None:
    svc.profile.hide_profile(call.from_user.id)
    safe_answer_callback(call, "Профиль скрыт.")
    bot.send_message(call.message.chat.id, "🙈 Ваш профиль теперь скрыт из поиска. Используйте ⚙️ Настройки, чтобы снова сделать его видимым.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm:delete_profile"))
@guarded
@require_registered
def cb_confirm_delete(call: types.CallbackQuery) -> None:
    svc.profile.delete_profile(call.from_user.id)
    safe_answer_callback(call, "Профиль удалён.")
    bot.send_message(call.message.chat.id, "🗑 Ваш профиль удалён. Отправьте /start в любое время, чтобы восстановить его.", reply_markup=KB.remove())

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.EDIT_NAME.value), content_types=["text"])
@guarded
@require_registered
def msg_edit_name(message: types.Message) -> None:
    svc.profile.update_name(message.from_user.id, message.text)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, "✅ Имя обновлено.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.EDIT_ABOUT.value), content_types=["text"])
@guarded
@require_registered
def msg_edit_about(message: types.Message) -> None:
    svc.profile.update_about(message.from_user.id, message.text)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, "✅ Раздел «О себе» обновлён.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.EDIT_CITY.value), content_types=["text"])
@guarded
@require_registered
def msg_edit_city(message: types.Message) -> None:
    svc.profile.update_city(message.from_user.id, message.text)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, "✅ Город обновлён.")

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_VERIFICATION_VIDEO.value),
    content_types=["video_note"],
)
@guarded
@require_registered
def msg_verification_video(message: types.Message) -> None:
    user_id = message.from_user.id
    if message.video_note.duration > Config.VERIFICATION_VIDEO_MAX_DURATION:
        bot.send_message(message.chat.id, f"Видео слишком длинное. Максимум {Config.VERIFICATION_VIDEO_MAX_DURATION}с.")
        return
    svc.verification.submit_video(user_id, message.video_note.file_id)
    svc.repos.state.clear(user_id)
    bot.send_message(message.chat.id, "✅ Отправлено на проверку! Мы уведомим вас, когда модератор проверит видео.")

@bot.message_handler(func=lambda m: m.text == "🔍 Поиск")
@guarded
@require_registered
def menu_discover(message: types.Message) -> None:
    _show_next_candidate(message.chat.id, message.from_user.id)

@bot.message_handler(commands=["discover"])
@guarded
@require_registered
def cmd_discover(message: types.Message) -> None:
    _show_next_candidate(message.chat.id, message.from_user.id)

def _show_next_candidate(chat_id: int, user_id: int) -> None:
    user = svc.repos.users.get(user_id)
    if user and user["verification_status"] != "approved":
        bot.send_message(chat_id, "🔒 Для доступа к поиску необходимо пройти верификацию.\n\nОткройте 👤 Мой профиль → 🎥 Верификация и отправьте видеокружок.")
        return
    candidate = svc.search.next_candidate(user_id)
    if not candidate:
        bot.send_message(
            chat_id,
            "🔎 По вашим фильтрам больше никого нет. Попробуйте расширить поиск в ⚙️ Настройках или заходите позже!",
        )
        return
    send_profile_card(chat_id, candidate, keyboard=KB.discover_actions(candidate["user_id"]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("like:"))
@guarded
@require_registered
def cb_like(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    target_id = int(call.data.split(CALLBACK_SEP)[1])
    match_id = svc.match.like(user_id, target_id)
    safe_answer_callback(call, "❤️ Лайк!")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except ApiTelegramException:
        pass
    if match_id:
        notify_match(match_id, user_id, target_id)
    _show_next_candidate(call.message.chat.id, user_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dislike:"))
@guarded
@require_registered
def cb_dislike(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    target_id = int(call.data.split(CALLBACK_SEP)[1])
    svc.match.dislike(user_id, target_id)
    safe_answer_callback(call)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except ApiTelegramException:
        pass
    _show_next_candidate(call.message.chat.id, user_id)

@bot.message_handler(func=lambda m: m.text == "💌 Лайки и мэтчи")
@guarded
@require_registered
def menu_likes_matches(message: types.Message) -> None:
    user_id = message.from_user.id
    user = svc.repos.users.get(user_id)
    likers = svc.repos.likes.likes_received(user_id, limit=5)

    if user["premium_tier"] == PremiumTier.FREE.value and likers:
        bot.send_message(
            message.chat.id,
            f"💌 Вас лайкнули <b>{len(likers)}+</b> человек! Приобретите Premium, чтобы увидеть кто именно.",
        )
    else:
        for liker in likers:
            liker["age"] = calc_age(liker["birth_date"])
            liker["photos"] = svc.repos.media.list_for_user(liker["user_id"])
            liker["tags"] = svc.repos.tags.for_user(liker["user_id"])
            send_profile_card(message.chat.id, liker, keyboard=KB.likes_received_nav(liker["user_id"]))
        if not likers:
            bot.send_message(message.chat.id, "Пока нет новых лайков. Продолжайте искать, чтобы вас заметили!")

    matches = svc.repos.matches.list_for_user(user_id)
    if matches:
        names = {}
        for m in matches:
            other = svc.repos.users.get(m["other_user_id"])
            names[m["other_user_id"]] = other["display_name"] if other else "Неизвестный"
        bot.send_message(message.chat.id, "💞 <b>Ваши мэтчи:</b>", reply_markup=KB.matches_list(matches, names))

@bot.message_handler(commands=["matches"])
@guarded
@require_registered
def cmd_matches(message: types.Message) -> None:
    menu_likes_matches(message)

@bot.message_handler(func=lambda m: m.text == "💬 Чаты")
@guarded
@require_registered
def menu_chats(message: types.Message) -> None:
    user_id = message.from_user.id
    matches = svc.repos.matches.list_for_user(user_id)
    if not matches:
        bot.send_message(message.chat.id, "У вас пока нет активных чатов. Отправляйтесь в 🔍 Поиск, чтобы найти мэтчи!")
        return
    names = {}
    for m in matches:
        other = svc.repos.users.get(m["other_user_id"])
        names[m["other_user_id"]] = other["display_name"] if other else "Неизвестный"
    bot.send_message(message.chat.id, "💬 <b>Ваши чаты:</b>", reply_markup=KB.matches_list(matches, names))

@bot.callback_query_handler(func=lambda c: c.data.startswith("openchat:"))
@guarded
@require_registered
def cb_open_chat(call: types.CallbackQuery) -> None:
    user_id = call.from_user.id
    match_id = int(call.data.split(CALLBACK_SEP)[1])
    if not svc.repos.matches.is_participant(match_id, user_id):
        return safe_answer_callback(call, "Этот чат больше недоступен.", show_alert=True)

    history = svc.chat.history(user_id, match_id)
    safe_answer_callback(call)
    if history:
        lines = []
        for msg in history[-10:]:
            who = "Вы" if msg["sender_id"] == user_id else "Собеседник"
            content = msg["content"] if msg["content_type"] == "text" else f"[{msg['content_type']}]"
            lines.append(f"<i>{who}:</i> {content}")
        bot.send_message(call.message.chat.id, "\n".join(lines))
    else:
        bot.send_message(call.message.chat.id, "💬 Сообщений пока нет. Скажите привет!")

    svc.repos.state.set(user_id, BotState.AWAITING_CHAT_MESSAGE.value, {"match_id": match_id})
    bot.send_message(call.message.chat.id, "Введите сообщение ниже или /cancel для выхода из режима чата:")

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_CHAT_MESSAGE.value),
    content_types=["text", "photo", "sticker", "voice", "video_note"],
)
@guarded
@require_registered
def msg_chat_send(message: types.Message) -> None:
    user_id = message.from_user.id
    _, data = svc.repos.state.get(user_id)
    match_id = data["match_id"]

    content_type_map = {
        "text": ("text", message.text, None),
        "photo": ("photo", None, message.photo[-1].file_id if message.photo else None),
        "sticker": ("sticker", None, message.sticker.file_id if message.sticker else None),
        "voice": ("voice", None, message.voice.file_id if message.voice else None),
        "video_note": ("video_note", None, message.video_note.file_id if message.video_note else None),
    }
    ctype, content, file_id = content_type_map[message.content_type]

    result = svc.chat.send_message(user_id, match_id, content, ctype, file_id)

    recipient = result["recipient_id"]
    sender = svc.repos.users.get(user_id)
    recipient_in_chat_with_this_match = False
    r_state, r_data = svc.repos.state.get(recipient)
    if r_state == BotState.AWAITING_CHAT_MESSAGE.value and r_data.get("match_id") == match_id:
        recipient_in_chat_with_this_match = True

    prefix = "" if recipient_in_chat_with_this_match else f"💬 <b>{sender['display_name']}</b>: "
    try:
        if ctype == "text":
            safe_send(recipient, f"{prefix}{content}")
        elif ctype == "photo":
            bot.send_photo(recipient, file_id, caption=prefix or None)
        elif ctype == "sticker":
            if prefix:
                safe_send(recipient, prefix)
            bot.send_sticker(recipient, file_id)
        elif ctype == "voice":
            bot.send_voice(recipient, file_id, caption=prefix or None)
        elif ctype == "video_note":
            if prefix:
                safe_send(recipient, prefix)
            bot.send_video_note(recipient, file_id)
    except ApiTelegramException as e:
        log.warning(f"Не удалось доставить сообщение чата получателю {recipient}: {e}")

COMPLAINT_REASONS = ["Фейковый профиль", "Неподобающие фото", "Домогательства", "Несовершеннолетний", "Спам/мошенничество", "Другое"]

@bot.callback_query_handler(func=lambda c: c.data.startswith("reportstart:"))
@guarded
@require_registered
def cb_report_start(call: types.CallbackQuery) -> None:
    target_id = int(call.data.split(CALLBACK_SEP)[1])
    kb = types.InlineKeyboardMarkup(row_width=1)
    for reason in COMPLAINT_REASONS:
        kb.add(types.InlineKeyboardButton(reason, callback_data=f"reportreason{CALLBACK_SEP}{target_id}{CALLBACK_SEP}{reason}"))
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Почему вы жалуетесь на этот профиль?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reportreason:"))
@guarded
@require_registered
def cb_report_reason(call: types.CallbackQuery) -> None:
    _, target_id_str, reason = call.data.split(CALLBACK_SEP, 2)
    target_id = int(target_id_str)
    svc.repos.state.set(
        call.from_user.id, BotState.AWAITING_COMPLAINT_REASON.value,
        {"target_id": target_id, "reason": reason},
    )
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Добавьте подробности (необязательно) или отправьте /skip:")

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_COMPLAINT_REASON.value),
    content_types=["text"],
)
@guarded
@require_registered
def msg_report_details(message: types.Message) -> None:
    user_id = message.from_user.id
    _, data = svc.repos.state.get(user_id)
    details = sanitize_free_text(message.text)
    svc.moderation.file_complaint(user_id, data["target_id"], data["reason"], details or None)
    svc.repos.state.clear(user_id)
    bot.send_message(message.chat.id, "✅ Спасибо, наша команда модерации рассмотрит эту жалобу.")

@bot.message_handler(func=lambda m: m.text == "⭐ Premium и магазин")
@guarded
@require_registered
def menu_shop(message: types.Message) -> None:
    cmd_shop(message)

@bot.message_handler(commands=["shop"])
@guarded
@require_registered
def cmd_shop(message: types.Message) -> None:
    user = svc.repos.users.get(message.from_user.id)
    items = svc.repos.shop.active_items()
    tier_label = {"free": "Бесплатный", "premium": "⭐ Premium", "premium_plus": "💎 Premium+"}[user["premium_tier"]]
    until = f" (до {user['premium_until'][:10]})" if user["premium_until"] else ""
    bot.send_message(
        message.chat.id,
        f"💰 Баланс звёзд: <b>{user['balance_stars']}</b> ⭐\n"
        f"Текущий уровень: <b>{tier_label}</b>{until}\n\n"
        "Выберите товар для покупки за звёзды или /topup для пополнения через Telegram:",
        reply_markup=KB.shop_menu(items),
    )

@bot.message_handler(commands=["topup"])
@guarded
@require_registered
def cmd_topup(message: types.Message) -> None:
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("100 ⭐", callback_data="topup:100"),
        types.InlineKeyboardButton("500 ⭐", callback_data="topup:500"),
        types.InlineKeyboardButton("1000 ⭐", callback_data="topup:1000"),
    )
    bot.send_message(message.chat.id, "Выберите количество Telegram Stars для пополнения баланса:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("topup:"))
@guarded
@require_registered
def cb_topup(call: types.CallbackQuery) -> None:
    amount = int(call.data.split(CALLBACK_SEP)[1])
    safe_answer_callback(call)
    bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"Пополнение на {amount} звёзд",
        description=f"Добавить {amount} звёзд на ваш внутренний баланс.",
        invoice_payload=f"topup:{amount}:{uuid.uuid4().hex}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{amount} звёзд", amount=amount)],
    )

@bot.pre_checkout_query_handler(func=lambda q: True)
def handle_pre_checkout(pre_checkout_query: types.PreCheckoutQuery) -> None:
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except ApiTelegramException as e:
        log.error(f"Ошибка подтверждения pre_checkout: {e}")

@bot.message_handler(content_types=["successful_payment"])
@guarded
@require_registered
def handle_successful_payment(message: types.Message) -> None:
    payload = message.successful_payment.invoice_payload
    amount = message.successful_payment.total_amount
    charge_id = message.successful_payment.telegram_payment_charge_id
    new_balance = svc.payment.credit_stars_topup(message.from_user.id, amount, charge_id)
    bot.send_message(message.chat.id, f"✅ {amount} ⭐ добавлено! Новый баланс: <b>{new_balance}</b> ⭐")

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:"))
@guarded
@require_registered
def cb_buy_item(call: types.CallbackQuery) -> None:
    item_id = int(call.data.split(CALLBACK_SEP)[1])
    item = svc.payment.purchase_item(call.from_user.id, item_id)
    safe_answer_callback(call, "Куплено!")
    bot.send_message(call.message.chat.id, f"✅ Вы приобрели <b>{item['name']}</b>! Приятного использования 🎉")

@bot.message_handler(func=lambda m: m.text == "🎁 Ежедневная награда")
@guarded
@require_registered
def menu_daily_reward(message: types.Message) -> None:
    stars, streak = svc.reward.claim_daily(message.from_user.id)
    bot.send_message(
        message.chat.id,
        f"🎁 Вы получили <b>{stars} ⭐</b>! Текущая серия: <b>{streak} дн.</b>\n"
        "Возвращайтесь завтра, чтобы продолжить серию!",
    )

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
@guarded
@require_registered
def menu_referrals(message: types.Message) -> None:
    cmd_referral(message)

@bot.message_handler(commands=["referral"])
@guarded
@require_registered
def cmd_referral(message: types.Message) -> None:
    user = svc.repos.users.get(message.from_user.id)
    link = svc.referral.referral_link(bot_username(), user)
    stats = svc.referral.stats_for(message.from_user.id)
    bot.send_message(
        message.chat.id,
        f"👥 <b>Приглашайте друзей и получайте звёзды!</b>\n\n"
        f"Вы получаете <b>{Config.REFERRAL_REWARD_STARS} ⭐</b> за каждого друга, "
        "который присоединится по вашей ссылке и пройдёт верификацию.\n\n"
        f"🔗 Ваша ссылка:\n{link}\n\n"
        f"📊 Всего рефералов: <b>{stats['total_referrals']}</b>",
    )

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
@guarded
@require_registered
def menu_settings(message: types.Message) -> None:
    user = svc.repos.users.get(message.from_user.id)
    filters = svc.repos.search_filters.get(message.from_user.id)
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(f"Мин. возраст: {filters['min_age']}", callback_data="setmin:0"),
        types.InlineKeyboardButton(f"Макс. возраст: {filters['max_age']}", callback_data="setmax:0"),
        types.InlineKeyboardButton(f"Город: {filters['city'] or 'Любой'}", callback_data="setcity:0"),
        types.InlineKeyboardButton(
            f"Только верифицированные: {'Да' if filters['verified_only'] else 'Нет'}", callback_data="settoggleverified:0"
        ),
    )
    if user["status"] == UserStatus.HIDDEN.value:
        kb.add(types.InlineKeyboardButton("👁 Сделать профиль видимым", callback_data="unhideprofile:0"))
    bot.send_message(message.chat.id, "⚙️ <b>Настройки</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "unhideprofile:0")
@guarded
@require_registered
def cb_unhide(call: types.CallbackQuery) -> None:
    svc.profile.unhide_profile(call.from_user.id)
    safe_answer_callback(call, "Профиль снова видим!")
    bot.send_message(call.message.chat.id, "👁 Ваш профиль снова отображается в поиске.")

@bot.callback_query_handler(func=lambda c: c.data == "settoggleverified:0")
@guarded
@require_registered
def cb_toggle_verified_filter(call: types.CallbackQuery) -> None:
    filters = svc.repos.search_filters.get(call.from_user.id)
    new_val = 0 if filters["verified_only"] else 1
    svc.repos.search_filters.update(call.from_user.id, verified_only=new_val)
    safe_answer_callback(call, "Обновлено!")
    bot.send_message(call.message.chat.id, f"Фильтр «Только верифицированные»: {'ВКЛ' if new_val else 'ВЫКЛ'}")

@bot.callback_query_handler(func=lambda c: c.data == "setmin:0")
@guarded
@require_registered
def cb_set_min_age(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_SEARCH_MIN_AGE.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, f"Введите минимальный возраст ({Config.MIN_AGE}-{Config.MAX_AGE}):")

@bot.callback_query_handler(func=lambda c: c.data == "setmax:0")
@guarded
@require_registered
def cb_set_max_age(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_SEARCH_MAX_AGE.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, f"Введите максимальный возраст ({Config.MIN_AGE}-{Config.MAX_AGE}):")

@bot.callback_query_handler(func=lambda c: c.data == "setcity:0")
@guarded
@require_registered
def cb_set_city_filter(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_SEARCH_CITY.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Введите город для фильтрации или отправьте «любой», чтобы сбросить:")

def _parse_age_input(text: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise ValidationError("Пожалуйста, введите число.")
    age = int(text)
    if not (Config.MIN_AGE <= age <= Config.MAX_AGE):
        raise ValidationError(f"Возраст должен быть от {Config.MIN_AGE} до {Config.MAX_AGE}.")
    return age

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_SEARCH_MIN_AGE.value), content_types=["text"])
@guarded
@require_registered
def msg_set_min_age(message: types.Message) -> None:
    min_age = _parse_age_input(message.text)
    filters = svc.repos.search_filters.get(message.from_user.id)
    if min_age > filters["max_age"]:
        raise ValidationError("Минимальный возраст не может быть больше максимального.")
    svc.repos.search_filters.update(message.from_user.id, min_age=min_age)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, f"✅ Минимальный возраст установлен: {min_age}.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_SEARCH_MAX_AGE.value), content_types=["text"])
@guarded
@require_registered
def msg_set_max_age(message: types.Message) -> None:
    max_age = _parse_age_input(message.text)
    filters = svc.repos.search_filters.get(message.from_user.id)
    if max_age < filters["min_age"]:
        raise ValidationError("Максимальный возраст не может быть меньше минимального.")
    svc.repos.search_filters.update(message.from_user.id, max_age=max_age)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, f"✅ Максимальный возраст установлен: {max_age}.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_SEARCH_CITY.value), content_types=["text"])
@guarded
@require_registered
def msg_set_city_filter(message: types.Message) -> None:
    text = message.text.strip()
    city = None if text.lower() == "любой" else validate_city(text)
    svc.repos.search_filters.update(message.from_user.id, city=city)
    svc.repos.state.clear(message.from_user.id)
    bot.send_message(message.chat.id, f"✅ Город установлен: {city or 'Любой'}.")

@bot.message_handler(func=lambda m: m.text == "🛡 Панель модератора")
@guarded
@require_registered
@require_role(*MOD_ROLES)
def menu_mod_panel(message: types.Message) -> None:
    pending_v = svc.repos.verification.pending_count()
    pending_c = svc.repos.complaints.pending_count()
    bot.send_message(
        message.chat.id,
        f"🛡 <b>Панель модератора</b>\n\n🎥 Ожидают верификации: {pending_v}\n🚨 Ожидают жалобы: {pending_c}",
        reply_markup=KB.moderator_panel(),
    )

@bot.callback_query_handler(func=lambda c: c.data == "mod:verifqueue")
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_mod_verif_queue(call: types.CallbackQuery) -> None:
    safe_answer_callback(call)
    req = svc.repos.verification.next_pending()
    if not req:
        bot.send_message(call.message.chat.id, "✅ Нет заявок на верификацию.")
        return
    applicant = svc.repos.users.get(req["user_id"])
    caption = (
        f"🎥 Заявка на верификацию #{req['id']}\n"
        f"Заявитель: {applicant['display_name']} ({applicant['public_id']})"
    )
    try:
        bot.send_video_note(call.message.chat.id, req["video_file_id"])
    except ApiTelegramException:
        pass
    bot.send_message(call.message.chat.id, caption, reply_markup=KB.verification_review(req["id"]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("vrev:"))
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_verification_review(call: types.CallbackQuery) -> None:
    _, action, req_id_str = call.data.split(CALLBACK_SEP)
    req_id = int(req_id_str)
    mod_id = call.from_user.id

    if action == "approve":
        req = svc.verification.approve(req_id, mod_id)
        svc.referral.reward_if_eligible(req["user_id"])
        safe_answer_callback(call, "Одобрено!")
        safe_send(req["user_id"], "🎉 Поздравляем! Ваш профиль теперь <b>Верифицирован</b> ✅")
        bot.send_message(call.message.chat.id, "✅ Одобрено.")
    else:
        svc.repos.state.set(mod_id, BotState.AWAITING_MOD_REJECT_REASON.value, {"req_id": req_id})
        safe_answer_callback(call)
        bot.send_message(call.message.chat.id, "Укажите причину отклонения:")

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_MOD_REJECT_REASON.value),
    content_types=["text"],
)
@guarded
@require_registered
@require_role(*MOD_ROLES)
def msg_mod_reject_reason(message: types.Message) -> None:
    mod_id = message.from_user.id
    _, data = svc.repos.state.get(mod_id)
    reason = sanitize_free_text(message.text)
    req = svc.verification.reject(data["req_id"], mod_id, reason)
    svc.repos.state.clear(mod_id)
    safe_send(req["user_id"], f"❌ Ваша заявка на верификацию отклонена.\nПричина: {reason}\n\nВы можете подать новую заявку в любое время.")
    bot.send_message(message.chat.id, "❌ Отклонено.")

@bot.callback_query_handler(func=lambda c: c.data == "mod:complaintqueue")
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_mod_complaint_queue(call: types.CallbackQuery) -> None:
    safe_answer_callback(call)
    complaint = svc.repos.complaints.next_pending()
    if not complaint:
        bot.send_message(call.message.chat.id, "✅ Нет ожидающих жалоб.")
        return
    reporter = svc.repos.users.get(complaint["reporter_id"])
    target = svc.repos.users.get(complaint["target_id"])
    total_against = svc.repos.complaints.count_against(complaint["target_id"])
    bot.send_message(
        call.message.chat.id,
        f"🚨 Жалоба #{complaint['id']}\n"
        f"Отправитель: {reporter['display_name'] if reporter else '?'}\n"
        f"Нарушитель: {target['display_name'] if target else '?'} ({target['public_id'] if target else '?'})\n"
        f"Причина: {complaint['reason']}\n"
        f"Подробности: {complaint['details'] or '-'}\n"
        f"Всего жалоб на пользователя: {total_against}",
        reply_markup=KB.complaint_review(complaint["id"], complaint["target_id"]),
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("crev:"))
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_complaint_review(call: types.CallbackQuery) -> None:
    _, action, complaint_id_str = call.data.split(CALLBACK_SEP)
    complaint_id = int(complaint_id_str)
    mod_id = call.from_user.id
    complaint = svc.repos.complaints.get(complaint_id)
    if not complaint:
        return safe_answer_callback(call, "Жалоба не найдена.", show_alert=True)

    if action == "dismiss":
        svc.repos.complaints.resolve(complaint_id, ComplaintStatus.DISMISSED.value, mod_id)
        safe_answer_callback(call, "Жалоба отклонена.")
        bot.send_message(call.message.chat.id, "✅ Жалоба отклонена.")
        return

    action_map = {
        "warn": (PunishmentType.WARN.value, None),
        "mute": (PunishmentType.MUTE.value, timedelta(hours=24)),
        "ban": (PunishmentType.BAN.value, None),
    }
    ptype, duration = action_map[action]
    svc.moderation.punish(complaint["target_id"], ptype, f"Жалоба #{complaint_id}: {complaint['reason']}", mod_id, duration)
    svc.repos.complaints.resolve(complaint_id, ComplaintStatus.RESOLVED.value, mod_id)
    safe_answer_callback(call, "Меры приняты.")
    action_labels = {"warn": "вынесено предупреждение", "mute": "заглушен", "ban": "забанен"}
    bot.send_message(call.message.chat.id, f"✅ Пользователю {action_labels.get(action, action)}. Жалоба обработана.")
    safe_send(complaint["target_id"], f"⚠️ Модератор принял меры в отношении вашего аккаунта ({ptype}) по результатам рассмотрения жалобы.")

@bot.callback_query_handler(func=lambda c: c.data == "mod:searchid")
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_mod_search_id(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_ADMIN_SEARCH_ID.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Отправьте публичный ID пользователя (например, DP-482913) или Telegram ID:")

@bot.callback_query_handler(func=lambda c: c.data.startswith("admviewuser:"))
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_admin_view_user(call: types.CallbackQuery) -> None:
    target_id = int(call.data.split(CALLBACK_SEP)[1])
    safe_answer_callback(call)
    _send_admin_user_card(call.message.chat.id, target_id, call.from_user.id)

def _send_admin_user_card(chat_id: int, target_id: int, viewer_id: Optional[int] = None) -> None:
    profile = svc.profile.get_full_profile(target_id)
    if not profile:
        bot.send_message(chat_id, "Пользователь не найден.")
        return
    viewer_role = "user"
    if viewer_id:
        viewer = svc.repos.users.get(viewer_id)
        if viewer:
            viewer_role = viewer["role"]
    punishments = svc.repos.punishments.history_for_user(target_id)
    complaints_against = svc.repos.complaints.count_against(target_id)
    roles_map = {"user": "Пользователь", "moderator": "Модератор", "admin": "Админ", "owner": "Владелец"}
    statuses_map = {"active": "Активен", "hidden": "Скрыт", "deleted": "Удалён", "banned": "Забанен"}
    verif_map = {"none": "Нет", "pending": "Ожидает", "approved": "Пройдена", "rejected": "Отклонена"}
    tiers_map = {"free": "Бесплатный", "premium": "Premium", "premium_plus": "Premium+"}
    info = (
        f"{format_profile_card(profile)}\n\n"
        f"Роль: {roles_map.get(profile['role'], profile['role'])} | Статус: {statuses_map.get(profile['status'], profile['status'])}\n"
        f"Верификация: {verif_map.get(profile['verification_status'], profile['verification_status'])} | "
        f"Уровень: {tiers_map.get(profile['premium_tier'], profile['premium_tier'])}\n"
        f"Жалоб получено: {complaints_against} | Наказаний в истории: {len(punishments)}"
    )
    bot.send_message(chat_id, info, reply_markup=KB.admin_user_actions(target_id, profile["role"], viewer_role))

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_SEARCH_ID.value),
    content_types=["text"],
)
@guarded
@require_registered
@require_role(*MOD_ROLES)
def msg_admin_search_id(message: types.Message) -> None:
    svc.repos.state.clear(message.from_user.id)
    query = message.text.strip()
    user = None
    if query.upper().startswith("DP-"):
        user = svc.repos.users.get_by_public_id(query)
    elif query.isdigit():
        user = svc.repos.users.get(int(query))
    if not user:
        bot.send_message(message.chat.id, "Пользователь не найден.")
        return
    _send_admin_user_card(message.chat.id, user["user_id"], message.from_user.id)

@bot.message_handler(func=lambda m: m.text == "🛠 Панель админа")
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def menu_admin_panel(message: types.Message) -> None:
    bot.send_message(message.chat.id, "🛠 <b>Панель администратора</b>", reply_markup=KB.admin_panel())

@bot.callback_query_handler(func=lambda c: c.data == "adm:stats")
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def cb_admin_stats(call: types.CallbackQuery) -> None:
    safe_answer_callback(call)
    s = svc.stats.platform_overview()
    activity_lines = "\n".join(f"  • {a['action']}: {a['c']}" for a in s["activity_last_24h"][:10]) or "  (нет)"
    bot.send_message(
        call.message.chat.id,
        "📊 <b>Статистика платформы</b>\n\n"
        f"Всего пользователей: {s['total']}\n"
        f"Активных: {s['active']} | Скрытых: {s['hidden']} | Забанено: {s['banned']} | Удалено: {s['deleted']}\n"
        f"Верифицировано: {s['verified']}\n"
        f"Premium: {s['premium']} | Premium+: {s['premium_plus']}\n"
        f"Ожидают верификации: {s['pending_verifications']}\n"
        f"Ожидают жалобы: {s['pending_complaints']}\n\n"
        f"<b>Активность (24ч):</b>\n{activity_lines}",
    )

@bot.callback_query_handler(func=lambda c: c.data == "adm:searchid")
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def cb_admin_search_id(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_ADMIN_SEARCH_ID.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Отправьте публичный ID пользователя (например, DP-482913) или Telegram ID:")

@bot.callback_query_handler(func=lambda c: c.data == "adm:log")
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def cb_admin_log(call: types.CallbackQuery) -> None:
    safe_answer_callback(call)
    entries = svc.repos.admin_log.recent(20)
    if not entries:
        bot.send_message(call.message.chat.id, "Действий администраторов пока не зафиксировано.")
        return
    lines = [f"{e['created_at'][:16]} | админ={e['admin_id']} | {e['action']} | цель={e['target_id']}" for e in entries]
    bot.send_message(call.message.chat.id, "📜 <b>Последние действия администраторов:</b>\n\n" + "\n".join(lines))

@bot.callback_query_handler(func=lambda c: c.data == "adm:broadcast")
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def cb_admin_broadcast(call: types.CallbackQuery) -> None:
    svc.repos.state.set(call.from_user.id, BotState.AWAITING_BROADCAST_CONTENT.value)
    safe_answer_callback(call)
    bot.send_message(call.message.chat.id, "Отправьте сообщение для рассылки всем активным пользователям:")

@bot.message_handler(
    func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_BROADCAST_CONTENT.value),
    content_types=["text"],
)
@guarded
@require_registered
@require_role(*ADMIN_ROLES)
def msg_admin_broadcast_content(message: types.Message) -> None:
    admin_id = message.from_user.id
    svc.repos.state.clear(admin_id)
    content = sanitize_free_text(message.text)
    targets = svc.repos.users.all_active_ids()
    broadcast_id = svc.repos.broadcasts.create(admin_id, content, "text", None, len(targets))
    bot.send_message(message.chat.id, f"📢 Выполняется рассылка {len(targets)} пользователям в фоновом режиме...")
    threading.Thread(target=_run_broadcast, args=(broadcast_id, content, targets), daemon=True).start()

def _run_broadcast(broadcast_id: int, content: str, targets: list[int]) -> None:
    sent, failed = 0, 0
    for i, uid in enumerate(targets):
        try:
            bot.send_message(uid, f"📢 <b>Объявление</b>\n\n{content}")
            sent += 1
        except ApiTelegramException:
            failed += 1
        if i % 25 == 0:
            svc.repos.broadcasts.update_progress(broadcast_id, sent, failed)
            time.sleep(0.5)
    svc.repos.broadcasts.update_progress(broadcast_id, sent, failed)
    svc.repos.broadcasts.complete(broadcast_id)
    log.info(f"Рассылка {broadcast_id} завершена: отправлено={sent} ошибок={failed}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:") and c.data.split(CALLBACK_SEP)[1] in
                             ("ban", "unban", "warn", "unwarn", "makeadmin", "unadmin",
                              "givestars", "resetstars", "givepremium", "removepremium"))
@guarded
@require_registered
@require_role(*MOD_ROLES)
def cb_admin_user_action(call: types.CallbackQuery) -> None:
    _, action, target_id_str = call.data.split(CALLBACK_SEP)
    target_id = int(target_id_str)
    admin_id = call.from_user.id
    target = svc.repos.users.get(target_id)
    admin = svc.repos.users.get(admin_id)
    if not target:
        return safe_answer_callback(call, "Пользователь не найден.", show_alert=True)

    if action == "ban":
        if admin["role"] not in ("moderator", "admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.moderation.punish(target_id, PunishmentType.BAN.value, "Забанен администратором", admin_id, None)
        safe_send(target_id, "🚫 Ваш аккаунт заблокирован администратором.")
        safe_answer_callback(call, "Пользователь забанен.")
        bot.send_message(call.message.chat.id, f"✅ Пользователь {target_id} забанен.")

    elif action == "unban":
        if admin["role"] not in ("moderator", "admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.moderation.lift_punishment(target_id, PunishmentType.BAN.value, admin_id)
        safe_send(target_id, "✅ Блокировка вашего аккаунта снята.")
        safe_answer_callback(call, "Пользователь разбанен.")
        bot.send_message(call.message.chat.id, f"✅ Пользователь {target_id} разбанен.")

    elif action == "warn":
        if admin["role"] not in ("moderator", "admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.repos.state.set(admin_id, BotState.AWAITING_ADMIN_WARN_REASON.value, {"target_id": target_id})
        safe_answer_callback(call)
        bot.send_message(call.message.chat.id, "Введите причину предупреждения:")

    elif action == "unwarn":
        if admin["role"] not in ("moderator", "admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.moderation.lift_punishment(target_id, PunishmentType.WARN.value, admin_id)
        safe_send(target_id, "✅ Предупреждение снято администратором.")
        safe_answer_callback(call, "Предупреждение снято.")
        bot.send_message(call.message.chat.id, f"✅ Предупреждение с пользователя {target_id} снято.")

    elif action == "makeadmin":
        if admin["role"] not in ("admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.repos.users.set_role(target_id, UserRole.ADMIN.value)
        svc.repos.admin_log.log(admin_id, "promote_admin", target_id)
        safe_send(target_id, "🎉 Вы повышены до Администратора!")
        safe_answer_callback(call, "Администратор назначен.")
        bot.send_message(call.message.chat.id, f"✅ Пользователь {target_id} назначен администратором.")

    elif action == "unadmin":
        if admin["role"] not in ("admin", "owner"):
            return safe_answer_callback(call, "Недостаточно прав.", show_alert=True)
        svc.repos.users.set_role(target_id, UserRole.USER.value)
        svc.repos.admin_log.log(admin_id, "demote_admin", target_id)
        safe_send(target_id, "Ваша роль администратора снята.")
        safe_answer_callback(call, "Администратор снят.")
        bot.send_message(call.message.chat.id, f"✅ Администратор {target_id} понижен до пользователя.")

    elif action == "givestars":
        if admin["role"] != "owner":
            return safe_answer_callback(call, "Только владелец может выдавать звёзды.", show_alert=True)
        svc.repos.state.set(admin_id, BotState.AWAITING_ADMIN_GIVE_STARS.value, {"target_id": target_id})
        safe_answer_callback(call)
        bot.send_message(call.message.chat.id, f"Введите количество звёзд для выдачи пользователю {target_id}:")

    elif action == "resetstars":
        if admin["role"] != "owner":
            return safe_answer_callback(call, "Только владелец может обнулять звёзды.", show_alert=True)
        with db.tx() as conn:
            current = svc.repos.users.get(target_id)["balance_stars"]
            if current > 0:
                svc.repos.users.adjust_balance(conn, target_id, -current)
                svc.repos.transactions.record(conn, target_id, TransactionType.PURCHASE.value,
                    -current, 0, "Обнуление звёзд администратором", None)
        svc.repos.admin_log.log(admin_id, "reset_stars", target_id)
        safe_send(target_id, "💸 Ваш баланс звёзд был обнулён администратором.")
        safe_answer_callback(call, "Звёзды обнулены.")
        bot.send_message(call.message.chat.id, f"✅ Баланс пользователя {target_id} обнулён.")

    elif action == "givepremium":
        if admin["role"] != "owner":
            return safe_answer_callback(call, "Только владелец может выдавать Premium.", show_alert=True)
        svc.repos.state.set(admin_id, BotState.AWAITING_ADMIN_GIVE_PREMIUM_DAYS.value, {"target_id": target_id})
        safe_answer_callback(call)
        bot.send_message(call.message.chat.id, f"На сколько дней выдать Premium пользователю {target_id}?")

    elif action == "removepremium":
        if admin["role"] != "owner":
            return safe_answer_callback(call, "Только владелец может снимать Premium.", show_alert=True)
        svc.repos.users.update_fields(target_id, premium_tier=PremiumTier.FREE.value, premium_until=None)
        svc.repos.admin_log.log(admin_id, "remove_premium", target_id)
        safe_send(target_id, "❌ Ваш Premium был отключён администратором.")
        safe_answer_callback(call, "Premium снят.")
        bot.send_message(call.message.chat.id, f"✅ Premium снят с пользователя {target_id}.")



@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_WARN_REASON.value), content_types=["text"])
@guarded
@require_registered
@require_role(*MOD_ROLES)
def msg_admin_warn_reason(message: types.Message) -> None:
    admin_id = message.from_user.id
    _, data = svc.repos.state.get(admin_id)
    target_id = data["target_id"]
    reason = sanitize_free_text(message.text)
    svc.moderation.punish(target_id, PunishmentType.WARN.value, reason, admin_id, None)
    svc.repos.state.clear(admin_id)
    safe_send(target_id, f"⚠️ Вам вынесено предупреждение администратором.\nПричина: {reason}")
    bot.send_message(message.chat.id, f"✅ Предупреждение вынесено пользователю {target_id}.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_GIVE_STARS.value), content_types=["text"])
@guarded
@require_registered
@require_role("owner")
def msg_admin_give_stars(message: types.Message) -> None:
    admin_id = message.from_user.id
    _, data = svc.repos.state.get(admin_id)
    target_id = data["target_id"]
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Введите положительное число.")
        return
    with db.tx() as conn:
        new_balance = svc.repos.users.adjust_balance(conn, target_id, amount)
        svc.repos.transactions.record(conn, target_id, TransactionType.TOPUP.value,
            amount, new_balance, "Выдача звёзд администратором", None)
    svc.repos.admin_log.log(admin_id, "give_stars", target_id, {"amount": amount})
    svc.repos.state.clear(admin_id)
    safe_send(target_id, f"💰 Администратор выдал вам {amount} ⭐!")
    bot.send_message(message.chat.id, f"✅ {amount} ⭐ выдано пользователю {target_id}.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_GIVE_PREMIUM_DAYS.value), content_types=["text"])
@guarded
@require_registered
@require_role("owner")
def msg_admin_give_premium(message: types.Message) -> None:
    admin_id = message.from_user.id
    _, data = svc.repos.state.get(admin_id)
    target_id = data["target_id"]
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Введите положительное число дней.")
        return
    new_until = utcnow() + timedelta(days=days)
    svc.repos.users.update_fields(target_id, premium_tier=PremiumTier.PREMIUM.value,
                                   premium_until=new_until.isoformat())
    svc.repos.admin_log.log(admin_id, "give_premium", target_id, {"days": days})
    svc.repos.state.clear(admin_id)
    safe_send(target_id, f"⭐ Вам выдан Premium на {days} дней!")
    bot.send_message(message.chat.id, f"✅ Premium на {days} дн. выдан пользователю {target_id}.")



@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_GIVE_STARS.value), content_types=["text"])
@guarded
@require_registered
@require_role("owner")
def msg_admin_give_stars(message: types.Message) -> None:
    admin_id = message.from_user.id
    _, data = svc.repos.state.get(admin_id)
    target_id = data["target_id"]
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Введите положительное число.")
        return
    with db.tx() as conn:
        new_balance = svc.repos.users.adjust_balance(conn, target_id, amount)
        svc.repos.transactions.record(conn, target_id, "topup", amount, new_balance, "Выдача звёзд владельцем", None)
    svc.repos.state.clear(admin_id)
    safe_send(target_id, f"💰 Владелец выдал вам {amount} ⭐!")
    bot.send_message(message.chat.id, f"✅ {amount} ⭐ выдано пользователю {target_id}.")

@bot.message_handler(func=lambda m: _in_state(m.from_user.id, BotState.AWAITING_ADMIN_GIVE_PREMIUM_DAYS.value), content_types=["text"])
@guarded
@require_registered
@require_role("owner")
def msg_admin_give_premium(message: types.Message) -> None:
    admin_id = message.from_user.id
    _, data = svc.repos.state.get(admin_id)
    target_id = data["target_id"]
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Введите положительное число дней.")
        return
    new_until = utcnow() + timedelta(days=days)
    svc.repos.users.update_fields(target_id, premium_tier="premium", premium_until=new_until.isoformat())
    svc.repos.state.clear(admin_id)
    safe_send(target_id, f"⭐ Вам выдан Premium на {days} дн. владельцем!")
    bot.send_message(message.chat.id, f"✅ Premium на {days} дн. выдан пользователю {target_id}.")

@bot.message_handler(func=lambda m: True, content_types=[
    "text", "photo", "video", "video_note", "voice", "sticker", "document", "audio",
])
@guarded
def fallback_handler(message: types.Message) -> None:
    user = svc.repos.users.get(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "👋 Отправьте /start, чтобы создать профиль!")
        return
    is_mod = user["role"] in MOD_ROLES
    is_admin = user["role"] in ADMIN_ROLES
    bot.send_message(
        message.chat.id,
        "Я не совсем понял. Используйте меню ниже или /help для списка доступных команд.",
        reply_markup=KB.main_menu(is_mod, is_admin),
    )

class BackgroundScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def _run_periodic(self, name: str, interval: float, func: Callable[[], None]) -> None:
        log.info(f"Фоновая задача '{name}' запущена (интервал={interval}с)")
        while not self._stop_event.is_set():
            try:
                func()
            except Exception:
                log.error(f"Фоновая задача '{name}' завершилась с ошибкой:\n{traceback.format_exc()}")
            self._stop_event.wait(interval)
        log.info(f"Фоновая задача '{name}' остановлена")

    def add(self, name: str, interval: float, func: Callable[[], None]) -> None:
        t = threading.Thread(target=self._run_periodic, args=(name, interval, func), daemon=True)
        self._threads.append(t)
        t.start()

    def stop(self) -> None:
        self._stop_event.set()

def job_cleanup_inactive_profiles() -> None:
    log.info("Запуск очистки неактивных профилей")
    result = svc.cleanup.run()
    if result["hidden"] or result["deleted"]:
        log.info(f"Очистка неактивных: скрыто {result['hidden']}, удалено {result['deleted']}")

def job_expire_premiums() -> None:
    count = svc.payment.downgrade_expired_premiums()
    if count:
        log.info(f"Понижен уровень у {count} пользователей с истёкшим Premium")

def job_expire_punishments() -> None:
    expired = svc.repos.punishments.find_expired()
    for p in expired:
        svc.repos.punishments.deactivate(p["id"])
        if p["type"] == PunishmentType.BAN.value:
            user = svc.repos.users.get(p["user_id"])
            if user and user["status"] == UserStatus.BANNED.value:
                svc.repos.users.set_status(p["user_id"], UserStatus.ACTIVE.value)
                safe_send(p["user_id"], "✅ Ваша временная блокировка закончилась. С возвращением!")
    if expired:
        log.info(f"Истекло наказаний: {len(expired)}")

def job_sweep_rate_limiter() -> None:
    generic_limiter.sweep()

scheduler = BackgroundScheduler()

def start_background_jobs() -> None:
    scheduler.add("очистка_неактивных", Config.CLEANUP_JOB_INTERVAL, job_cleanup_inactive_profiles)
    scheduler.add("истечение_premium", Config.SUBSCRIPTION_EXPIRY_JOB_INTERVAL, job_expire_premiums)
    scheduler.add("истечение_наказаний", Config.PUNISHMENT_EXPIRY_JOB_INTERVAL, job_expire_punishments)
    scheduler.add("очистка_rate_limiter", 300, job_sweep_rate_limiter)
    log.info("Фоновые задачи запущены")

def _install_signal_handlers() -> None:
    def _handler(signum, frame):
        log.info(f"Получен сигнал {signum}, корректное завершение...")
        scheduler.stop()
        try:
            bot.stop_polling()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

def main() -> None:
    log.info("Запуск бота платформы знакомств...")
    _install_signal_handlers()
    start_background_jobs()

    try:
        me = bot.get_me()
        log.info(f"Авторизован как @{me.username} (id={me.id})")
    except ApiTelegramException as e:
        log.critical(f"Ошибка авторизации в Telegram: {e}")
        sys.exit(1)

    log.info("Бот начал приём сообщений")
    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True,
                logger_level=logging.WARNING,
            )
        except Exception:
            log.error(f"Опрос упал, перезапуск через 5с:\n{traceback.format_exc()}")
            time.sleep(5)

if __name__ == "__main__":
    main()
