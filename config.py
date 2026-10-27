import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _env(key, default=None, required=False):
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"❌ Переменная окружения {key} не задана в .env")
    return value


TOKEN = _env("BOT_TOKEN", required=True)
DB_NAME = _env("DB_NAME", "lovebot.db")
ADMIN_IDS = [int(x) for x in _env("ADMIN_IDS", "").split(",") if x.strip()]
CHANNEL_ID = _env("CHANNEL_ID", "@tavejr7")
CHANNEL_URL = _env("CHANNEL_URL", "https://t.me/tavejr7")
BOT_USERNAME = _env("BOT_USERNAME", "Ywggg17bot")

# Реферальная система
REFERRAL_REWARD_COUNT = int(_env("REFERRAL_REWARD_COUNT", "10"))  # сколько друзей
REFERRAL_REWARD_DAYS = int(_env("REFERRAL_REWARD_DAYS", "1"))     # дней премиума

if not ADMIN_IDS:
    logger.warning("⚠️ ADMIN_IDS пустой — админ-панель недоступна")

logger.info(f"Конфиг: DB={DB_NAME}, ADMINS={ADMIN_IDS}, CHANNEL={CHANNEL_ID}")

BASHKIR_CITIES = [
    "Уфа", "Агидель", "Баймак", "Белебей", "Белорецк",
    "Бирск", "Благовещенск", "Давлеканово", "Дюртюли",
    "Ишимбай", "Кумертау", "Межгорье", "Мелеуз",
    "Нефтекамск", "Октябрьский", "Салават", "Сибай",
    "Стерлитамак", "Туймазы", "Учалы", "Янаул"
]