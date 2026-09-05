import os
import random
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask
from dotenv import load_dotenv
from supabase import create_client

from unixgram import Bot, InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "169"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set")


# ============================================================
# INIT
# ============================================================

bot = Bot(BOT_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

KYIV = ZoneInfo("Europe/Kyiv")

CHECK_URL = "https://unixgram.com/api/account/username/check"

FREE_DAILY = 3
SUB_DAILY = 10

SUB_PRICE = 50
EXTRA_PRICE = 10

SUB_DAYS = 30

MAX_WORKERS = 4


# ============================================================
# RENDER WEB SERVICE
# ============================================================

@app.route("/")
def index():
    return "UnixScan is running", 200


@app.route("/health")
def health():
    return "OK", 200


def run_web():
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# ============================================================
# HELPERS
# ============================================================

def now_kyiv():
    return datetime.now(KYIV)


def today():
    return now_kyiv().date().isoformat()


def edit(call, text, keyboard=None):
    kwargs = {
        "parse_mode": "HTML"
    }

    if keyboard is not None:
        kwargs["reply_markup"] = keyboard

    bot.edit_message_text(
        call.message.chat.id,
        call.message.message_id,
        text,
        **kwargs
    )


def send(chat_id, text, keyboard=None):
    kwargs = {
        "parse_mode": "HTML"
    }

    if keyboard is not None:
        kwargs["reply_markup"] = keyboard

    bot.send_message(
        chat_id,
        text,
        **kwargs
    )


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu(user_id=None):

    rows = [
        [
            InlineKeyboardButton(
                "🔎 Найти ники",
                callback_data="search"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 Подписка",
                callback_data="subscription"
            ),
            InlineKeyboardButton(
                "⭐ Купить запрос",
                callback_data="buy_request"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Моя статистика",
                callback_data="stats"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Как это работает",
                callback_data="how"
            )
        ]
    ]

    if user_id == ADMIN_ID:
        rows.append([
            InlineKeyboardButton(
                "🛠 Админ-панель",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(rows)


def search_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "4 буквы",
                callback_data="len_4"
            ),
            InlineKeyboardButton(
                "5 букв",
                callback_data="len_5"
            )
        ],
        [
            InlineKeyboardButton(
                "6 букв",
                callback_data="len_6"
            ),
            InlineKeyboardButton(
                "7 букв",
                callback_data="len_7"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Назад",
                callback_data="back"
            )
        ]
    ])


def style_menu(length):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌙 Мягкие",
                callback_data=f"style_soft_{length}"
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ Звучные",
                callback_data=f"style_sharp_{length}"
            )
        ],
        [
            InlineKeyboardButton(
                "💠 Редкие",
                callback_data=f"style_rare_{length}"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 Смешанные",
                callback_data=f"style_mixed_{length}"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Назад",
                callback_data="search"
            )
        ]
    ])


def after_search_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Искать ещё",
                callback_data="search"
            )
        ],
        [
            InlineKeyboardButton(
                "💎 Подписка",
                callback_data="subscription"
            ),
            InlineKeyboardButton(
                "⭐ +1 запрос",
                callback_data="buy_request"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="back"
            )
        ]
    ])


def back_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "↩️ Назад",
                callback_data="back"
            )
        ]
    ])


# ============================================================
# DATABASE
# ============================================================

def get_user(user_id, username=None):

    result = (
        supabase
        .table("users")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if result.data:

        user = result.data[0]

        if user.get("request_date") != today():

            supabase.table("users").update({
                "requests_today": 0,
                "request_date": today()
            }).eq(
                "user_id",
                user_id
            ).execute()

            user["requests_today"] = 0
            user["request_date"] = today()

        if username is not None:
            if user.get("username") != username:

                supabase.table("users").update({
                    "username": username
                }).eq(
                    "user_id",
                    user_id
                ).execute()

                user["username"] = username

        return user

    data = {
        "user_id": user_id,
        "username": username or "",
        "requests_today": 0,
        "request_date": today(),
        "extra_requests": 0,
        "subscription_until": None,
        "total_searches": 0,
        "found_nicks": 0
    }

    result = (
        supabase
        .table("users")
        .insert(data)
        .execute()
    )

    return result.data[0]


def update_user(user_id, data):

    return (
        supabase
        .table("users")
        .update(data)
        .eq("user_id", user_id)
        .execute()
    )


# ============================================================
# SUBSCRIPTION
# ============================================================

def subscription_active(user):

    until = user.get("subscription_until")

    if not until:
        return False

    try:

        dt = datetime.fromisoformat(
            until.replace("Z", "+00:00")
        )

        return dt > datetime.now(dt.tzinfo)

    except Exception:

        return False


def subscription_text(user):

    if subscription_active(user):

        until = user.get(
            "subscription_until",
            ""
        )

        return (
            "💎 <b>UnixScan Premium</b>\n\n"
            "✅ Подписка активна\n\n"
            f"📅 До: <b>{until[:10]}</b>\n"
            "🔎 До 10 поисков в день."
        )

    return (
        "💎 <b>UnixScan Premium</b>\n\n"
        "⭐ Цена: <b>50 Stars</b>\n"
        "🔎 <b>10 поисков в день</b>\n"
        "📅 Срок: <b>30 дней</b>\n\n"
        "После оплаты подписка активируется автоматически."
    )


# ============================================================
# LIMITS
# ============================================================

def remaining_requests(user):

    used = int(
        user.get("requests_today", 0)
    )

    extra = int(
        user.get("extra_requests", 0)
    )

    if subscription_active(user):

        normal = max(
            0,
            SUB_DAILY - used
        )

    else:

        normal = max(
            0,
            FREE_DAILY - used
        )

    return normal + extra


def consume_request(user_id):

    user = get_user(user_id)

    used = int(
        user.get("requests_today", 0)
    )

    extra = int(
        user.get("extra_requests", 0)
    )

    if subscription_active(user):

        if used < SUB_DAILY:

            update_user(
                user_id,
                {
                    "requests_today": used + 1
                }
            )

            return True

    else:

        if used < FREE_DAILY:

            update_user(
                user_id,
                {
                    "requests_today": used + 1
                }
            )

            return True

    if extra > 0:

        update_user(
            user_id,
            {
                "extra_requests": extra - 1
            }
        )

        return True

    return False


# ============================================================
# NICK GENERATOR
# ============================================================

CONSONANTS = "bcdfghjklmnpqrstvwxyz"
VOWELS = "aeiou"

GOOD_STARTS = [
    "dr",
    "kr",
    "tr",
    "pr",
    "br",
    "gr",
    "vr",
    "sl",
    "cl",
    "fl",
    "st",
    "sk",
    "sh",
    "ch",
    "th"
]

BAD_PAIRS = {
    "qx",
    "xq",
    "qz",
    "zq",
    "zx",
    "xz",
    "jv",
    "vj",
    "wq",
    "qw",
    "xx",
    "qq",
    "zz",
    "jj"
}

PATTERNS = {

    "soft": [
        "CVCV",
        "CVCVC",
        "CVVC",
        "CVC",
        "CVVCV"
    ],

    "sharp": [
        "CCVC",
        "CVCC",
        "CCVCC",
        "CVCVC",
        "CCVCV"
    ],

    "rare": [
        "CVVC",
        "CCVCV",
        "CVCVC",
        "CVCCV",
        "CCVVC"
    ],

    "mixed": [
        "CVC",
        "CVCV",
        "CVCVC",
        "CVVC",
        "CVVCV",
        "CCVC",
        "CCVCV",
        "CVCCV"
    ]
}


def random_char(kind):

    if kind == "C":
        return random.choice(CONSONANTS)

    return random.choice(VOWELS)


def build_pattern(length, style):

    available = [
        pattern
        for pattern in PATTERNS[style]
        if len(pattern) == length
    ]

    if available:
        return random.choice(available)

    pattern = []

    for i in range(length):

        if i == 0:
            pattern.append("C")

        elif i % 2:
            pattern.append("V")

        else:
            pattern.append("C")

    return "".join(pattern)


def generate_username(length, style):

    pattern = build_pattern(
        length,
        style
    )

    chars = []

    # Иногда используем приятное начало.
    if length >= 5 and random.random() < 0.2:

        start = random.choice(
            GOOD_STARTS
        )

        if len(start) < length:

            chars.extend(start)

            while len(chars) < length:

                if len(chars) % 2:
                    chars.append(
                        random.choice(VOWELS)
                    )
                else:
                    chars.append(
                        random.choice(CONSONANTS)
                    )

            name = "".join(chars)

        else:

            name = "".join(
                random_char(x)
                for x in pattern
            )

    else:

        name = "".join(
            random_char(x)
            for x in pattern
        )

    name = name[:length].lower()

    for pair in BAD_PAIRS:

        if pair in name:
            return generate_username(
                length,
                style
            )

    for i in range(len(name) - 2):

        if (
            name[i]
            == name[i + 1]
            == name[i + 2]
        ):
            return generate_username(
                length,
                style
            )

    return name.capitalize()


def generate_candidates(
    length,
    style,
    count=60
):

    result = set()

    attempts = 0

    while (
        len(result) < count
        and attempts < count * 10
    ):

        attempts += 1

        name = generate_username(
            length,
            style
        )

        if len(name) == length:
            result.add(name)

    return list(result)


# ============================================================
# UNIXGRAM CHECK
# ============================================================

def check_username(username):

    try:

        response = requests.get(
            CHECK_URL,
            params={
                "value": username
            },
            timeout=5
        )

        if response.status_code != 200:
            return username, False

        data = response.json()

        available = (
            data.get("success") is True
            and data.get("data", {}).get("status")
            == "available"
        )

        return username, available

    except Exception as error:

        print(
            "USERNAME CHECK ERROR:",
            username,
            repr(error)
        )

        return username, False


def find_available(
    length,
    style,
    amount=5
):

    candidates = generate_candidates(
        length,
        style,
        60
    )

    available = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                check_username,
                username
            ): username
            for username in candidates
        }

        for future in as_completed(futures):

            username, is_available = (
                future.result()
            )

            if is_available:

                available.append(username)

                if len(available) >= amount:
                    break

    return available


# ============================================================
# SEARCH STATS
# ============================================================

def save_search(
    user_id,
    length,
    style,
    generated,
    available
):

    supabase.table("searches").insert({
        "user_id": user_id,
        "length": length,
        "style": style,
        "generated": generated,
        "available": available
    }).execute()


def update_search_stats(
    user_id,
    found
):

    user = get_user(user_id)

    total_searches = int(
        user.get("total_searches", 0)
    )

    found_nicks = int(
        user.get("found_nicks", 0)
    )

    update_user(
        user_id,
        {
            "total_searches":
                total_searches + 1,

            "found_nicks":
                found_nicks + found
        }
    )


# ============================================================
# PAYMENTS
# ============================================================

def payment_exists(payload):

    result = (
        supabase
        .table("payments")
        .select("id")
        .eq("payload", payload)
        .limit(1)
        .execute()
    )

    return bool(result.data)


def save_payment(
    user_id,
    payload,
    amount
):

    supabase.table("payments").insert({
        "user_id": user_id,
        "payload": payload,
        "amount": amount
    }).execute()


def send_subscription_invoice(
    chat_id
):

    payload = (
        f"sub:{chat_id}:"
        f"{random.randint(100000, 999999)}"
    )

    bot.send_invoice(
        chat_id,
        "💎 UnixScan Premium",
        "10 поисков в день на 30 дней",
        payload=payload,
        amount_stars=SUB_PRICE
    )


def send_extra_invoice(
    chat_id
):

    payload = (
        f"extra:{chat_id}:"
        f"{random.randint(100000, 999999)}"
    )

    bot.send_invoice(
        chat_id,
        "⭐ Дополнительный запрос",
        "Один дополнительный поиск",
        payload=payload,
        amount_stars=EXTRA_PRICE
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    user_id = message.from_user.id

    username = getattr(
        message.from_user,
        "username",
        ""
    )

    get_user(
        user_id,
        username
    )

    text = (
        "🔵 <b>UnixScan</b>\n\n"
        "Красивые и звучные ники для UnixGram.\n\n"
        "🔎 Генерирую варианты по сочетаниям букв\n"
        "⚡ Проверяю их доступность\n"
        "💠 Показываю только свободные\n\n"
        "🎁 Бесплатно: <b>3 поиска в день</b>"
    )

    send(
        message.chat.id,
        text,
        main_menu(user_id)
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler()
def callbacks(call):

    user_id = call.from_user.id
    data = call.data

    # --------------------------------------------------------
    # BACK
    # --------------------------------------------------------

    if data == "back":

        edit(
            call,
            (
                "🔵 <b>UnixScan</b>\n\n"
                "Выбери действие:"
            ),
            main_menu(user_id)
        )

        return

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    if data == "search":

        edit(
            call,
            (
                "🔎 <b>Поиск ников</b>\n\n"
                "Выбери длину:"
            ),
            search_menu()
        )

        return

    # --------------------------------------------------------
    # LENGTH
    # --------------------------------------------------------

    if data.startswith("len_"):

        length = int(
            data.split("_")[1]
        )

        edit(
            call,
            (
                f"🔎 Длина: <b>{length}</b>\n\n"
                "Выбери стиль:"
            ),
            style_menu(length)
        )

        return

    # --------------------------------------------------------
    # STYLE
    # --------------------------------------------------------

    if data.startswith("style_"):

        parts = data.split("_")

        style = parts[1]
        length = int(parts[2])

        if not consume_request(user_id):

            edit(
                call,
                (
                    "🔒 <b>Лимит закончился</b>\n\n"
                    "У тебя больше нет доступных "
                    "поисков.\n\n"
                    "💎 Подписка — <b>50 ⭐</b>\n"
                    "⭐ Дополнительный поиск — <b>10 ⭐</b>"
                ),
                after_search_menu()
            )

            return

        edit(
            call,
            (
                "🔎 <b>Ищу ники...</b>\n\n"
                f"📏 Длина: <b>{length}</b>\n"
                f"🎨 Стиль: <b>{style}</b>\n\n"
                "⏳ Проверяю доступность..."
            )
        )

        try:

            available = find_available(
                length,
                style,
                5
            )

        except Exception as error:

            print(
                "SEARCH ERROR:",
                repr(error)
            )

            edit(
                call,
                (
                    "❌ <b>Ошибка поиска</b>\n\n"
                    "Попробуй ещё раз."
                ),
                after_search_menu()
            )

            return

        save_search(
            user_id,
            length,
            style,
            60,
            len(available)
        )

        update_search_stats(
            user_id,
            len(available)
        )

        if available:

            lines = []

            for nickname in available:

                lines.append(
                    f"💠 <code>{nickname}</code>"
                )

            text = (
                "🔵 <b>Свободные ники</b>\n\n"
                + "\n".join(lines)
                + "\n\n"
                "⚡ Проверено прямо сейчас."
            )

        else:

            text = (
                "🔎 <b>Ничего не найдено</b>\n\n"
                "Свободных вариантов сейчас "
                "не нашлось.\n\n"
                "Попробуй другую длину или стиль."
            )

        edit(
            call,
            text,
            after_search_menu()
        )

        return

    # --------------------------------------------------------
    # SUBSCRIPTION
    # --------------------------------------------------------

    if data == "subscription":

        user = get_user(user_id)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💎 Купить за 50 ⭐",
                    callback_data="buy_subscription"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Назад",
                    callback_data="back"
                )
            ]
        ])

        edit(
            call,
            subscription_text(user),
            keyboard
        )

        return

    # --------------------------------------------------------
    # BUY SUBSCRIPTION
    # --------------------------------------------------------

    if data == "buy_subscription":

        send_subscription_invoice(
            call.message.chat.id
        )

        return

    # --------------------------------------------------------
    # BUY EXTRA
    # --------------------------------------------------------

    if data == "buy_request":

        send_extra_invoice(
            call.message.chat.id
        )

        return

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    if data == "stats":

        user = get_user(user_id)

        if subscription_active(user):
            sub = "💎 Активна"
        else:
            sub = "⚪ Нет"

        left = remaining_requests(user)

        text = (
            "📊 <b>Моя статистика</b>\n\n"
            f"🔎 Всего поисков: "
            f"<b>{user.get('total_searches', 0)}</b>\n"
            f"💠 Найдено ников: "
            f"<b>{user.get('found_nicks', 0)}</b>\n"
            f"⚡ Доступно запросов: "
            f"<b>{left}</b>\n"
            f"💎 Подписка: {sub}"
        )

        edit(
            call,
            text,
            back_menu()
        )

        return

    # --------------------------------------------------------
    # HOW
    # --------------------------------------------------------

    if data == "how":

        text = (
            "ℹ️ <b>Как работает UnixScan</b>\n\n"
            "1️⃣ Выбираешь длину ника.\n\n"
            "2️⃣ Выбираешь стиль сочетания букв.\n\n"
            "3️⃣ UnixScan генерирует варианты.\n\n"
            "4️⃣ Проверяет их через UnixGram.\n\n"
            "5️⃣ Показывает только свободные.\n\n"
            "🎁 Бесплатно — <b>3 поиска в день</b>\n"
            "💎 Premium — <b>10 поисков в день</b>\n"
            "⭐ Дополнительный поиск — <b>10 Stars</b>"
        )

        edit(
            call,
            text,
            back_menu()
        )

        return

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if data == "admin":

        if user_id != ADMIN_ID:
            return

        users_result = (
            supabase
            .table("users")
            .select("*")
            .execute()
        )

        users = users_result.data or []

        payments_result = (
            supabase
            .table("payments")
            .select("*")
            .execute()
        )

        payments = payments_result.data or []

        total_searches = sum(
            int(
                user.get(
                    "total_searches",
                    0
                )
            )
            for user in users
        )

        total_found = sum(
            int(
                user.get(
                    "found_nicks",
                    0
                )
            )
            for user in users
        )

        total_stars = sum(
            int(
                payment.get(
                    "amount",
                    0
                )
            )
            for payment in payments
        )

        text = (
            "🛠 <b>Админ-панель</b>\n\n"
            f"👤 Пользователей: <b>{len(users)}</b>\n"
            f"🔎 Поисков: <b>{total_searches}</b>\n"
            f"💠 Найдено ников: <b>{total_found}</b>\n"
            f"⭐ Получено Stars: <b>{total_stars}</b>\n"
            f"💳 Платежей: <b>{len(payments)}</b>"
        )

        edit(
            call,
            text,
            back_menu()
        )

        return


# ============================================================
# PRE-CHECKOUT
# ============================================================

@bot.pre_checkout_query_handler()
def pre_checkout(query):

    try:

        bot.answer_pre_checkout_query(
            query.id,
            ok=True
        )

    except Exception as error:

        print(
            "PRE-CHECKOUT ERROR:",
            repr(error)
        )


# ============================================================
# SUCCESSFUL PAYMENT
# ============================================================

@bot.message_handler(
    content_types=["successful_payment"]
)
def successful_payment(message):

    try:

        payment = message.successful_payment

        payload = payment.invoice_payload
        amount = payment.total_amount

        user_id = message.from_user.id

        print(
            "PAYMENT:",
            user_id,
            amount,
            payload
        )

        if payment_exists(payload):

            print(
                "Payment already processed:",
                payload
            )

            return

        save_payment(
            user_id,
            payload,
            amount
        )

        user = get_user(user_id)

        # ----------------------------------------------------
        # SUBSCRIPTION
        # ----------------------------------------------------

        if payload.startswith("sub:"):

            current = now_kyiv()

            old_until = user.get(
                "subscription_until"
            )

            if old_until:

                try:

                    old_dt = datetime.fromisoformat(
                        old_until.replace(
                            "Z",
                            "+00:00"
                        )
                    )

                    if old_dt > datetime.now(
                        old_dt.tzinfo
                    ):

                        current = old_dt.astimezone(
                            KYIV
                        )

                except Exception:
                    pass

            until = (
                current
                + timedelta(days=SUB_DAYS)
            )

            update_user(
                user_id,
                {
                    "subscription_until":
                        until.isoformat()
                }
            )

            send(
                message.chat.id,
                (
                    "💎 <b>Подписка активирована!</b>\n\n"
                    "⭐ Оплата: <b>50 Stars</b>\n"
                    "🔎 Лимит: <b>10 поисков в день</b>\n"
                    f"📅 До: <b>{until.date()}</b>"
                ),
                main_menu(user_id)
            )

            return

        # ----------------------------------------------------
        # EXTRA REQUEST
        # ----------------------------------------------------

        if payload.startswith("extra:"):

            extra = int(
                user.get(
                    "extra_requests",
                    0
                )
            )

            update_user(
                user_id,
                {
                    "extra_requests":
                        extra + 1
                }
            )

            send(
                message.chat.id,
                (
                    "⭐ <b>Запрос добавлен!</b>\n\n"
                    "Тебе добавлен ещё "
                    "<b>1 поиск</b>."
                ),
                main_menu(user_id)
            )

    except Exception as error:

        print(
            "PAYMENT ERROR:",
            repr(error)
        )


# ============================================================
# START BOT
# ============================================================

def start_bot():

    print("==============================")
    print("🔵 UnixScan started")
    print("==============================")

    print(
        "Admin ID:",
        ADMIN_ID
    )

    print(
        "Supabase:",
        SUPABASE_URL
    )

    bot.polling()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    start_bot()
