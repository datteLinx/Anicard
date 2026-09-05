import os
import random
import string
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
# SERVICES
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
# HTTP SERVER FOR RENDER
# ============================================================

@app.route("/")
def health():
    return "UnixScan is running", 200


@app.route("/health")
def health_check():
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
# KEYBOARDS
# ============================================================

def main_menu(user_id=None):

    rows = [
        [
            InlineKeyboardButton("🔎 Найти ники", callback_data="search")
        ],
        [
            InlineKeyboardButton("💎 Подписка", callback_data="subscription"),
            InlineKeyboardButton("⭐ Купить запрос", callback_data="buy_request")
        ],
        [
            InlineKeyboardButton("📊 Моя статистика", callback_data="stats")
        ],
        [
            InlineKeyboardButton("ℹ️ Как это работает", callback_data="how")
        ]
    ]

    if user_id == ADMIN_ID:
        rows.append([
            InlineKeyboardButton("🛠 Админ-панель", callback_data="admin")
        ])

    return InlineKeyboardMarkup(rows)


def search_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("4 буквы", callback_data="len_4"),
            InlineKeyboardButton("5 букв", callback_data="len_5")
        ],
        [
            InlineKeyboardButton("6 букв", callback_data="len_6"),
            InlineKeyboardButton("7 букв", callback_data="len_7")
        ],
        [
            InlineKeyboardButton("↩️ Назад", callback_data="back")
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
            InlineKeyboardButton("↩️ Назад", callback_data="search")
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


# ============================================================
# DATABASE
# ============================================================

def today():
    return datetime.now(KYIV).date().isoformat()


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
                "user_id", user_id
            ).execute()

            user["requests_today"] = 0
            user["request_date"] = today()

        if username is not None and user.get("username") != username:
            supabase.table("users").update({
                "username": username
            }).eq(
                "user_id", user_id
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

    if not subscription_active(user):
        return (
            "💎 <b>Подписка UnixScan</b>\n\n"
            "⭐ Цена: <b>50 Stars</b>\n"
            "🔎 Лимит: <b>10 поисков в день</b>\n"
            "📅 Срок: <b>30 дней</b>\n\n"
            "После оплаты подписка активируется автоматически."
        )

    until = user.get("subscription_until", "")

    return (
        "💎 <b>Подписка уже активна</b>\n\n"
        f"📅 До: <code>{until[:10]}</code>\n"
        "🔎 Доступно до 10 поисков в день."
    )


# ============================================================
# REQUEST LIMITS
# ============================================================

def remaining_requests(user):

    used = int(user.get("requests_today", 0))
    extra = int(user.get("extra_requests", 0))

    if subscription_active(user):
        normal_left = max(0, SUB_DAILY - used)
    else:
        normal_left = max(0, FREE_DAILY - used)

    return normal_left + extra


def consume_request(user_id):

    user = get_user(user_id)

    used = int(user.get("requests_today", 0))
    extra = int(user.get("extra_requests", 0))

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
# USERNAME GENERATOR
# ============================================================

CONSONANTS = "bcdfghjklmnpqrstvwxyz"
VOWELS = "aeiou"

# Более приятные сочетания.
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
    "zx",
    "jv",
    "vj",
    "wq",
    "qw",
    "xx",
    "qq",
    "zz",
    "jj"
}


def random_char(kind):

    if kind == "C":
        return random.choice(CONSONANTS)

    return random.choice(VOWELS)


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


def build_pattern(length, style):

    patterns = [
        p for p in PATTERNS[style]
        if len(p) == length
    ]

    if patterns:
        return random.choice(patterns)

    # Если для конкретной длины шаблонов нет —
    # строим автоматически.
    pattern = []

    for i in range(length):

        if i == 0:
            pattern.append("C")

        elif i % 2 == 1:
            pattern.append("V")

        else:
            pattern.append("C")

    return "".join(pattern)


def generate_username(length, style):

    pattern = build_pattern(length, style)

    chars = []

    for i, kind in enumerate(pattern):

        if i == 0 and length >= 5 and random.random() < 0.18:

            start = random.choice(GOOD_STARTS)

            if len(start) <= length:
                chars.extend(start)

                remaining = length - len(chars)

                for j in range(remaining):
                    next_kind = "V" if j % 2 == 0 else "C"
                    chars.append(random_char(next_kind))

                break

        chars.append(random_char(kind))

    name = "".join(chars)[:length].lower()

    # Убираем неприятные сочетания.
    for pair in BAD_PAIRS:

        if pair in name:
            return generate_username(length, style)

    # Не допускаем три одинаковых подряд.
    for i in range(len(name) - 2):

        if (
            name[i]
            == name[i + 1]
            == name[i + 2]
        ):
            return generate_username(length, style)

    return name.capitalize()


def generate_candidates(length, style, count=50):

    result = set()

    attempts = 0

    while len(result) < count and attempts < count * 10:

        attempts += 1

        name = generate_username(
            length,
            style
        )

        if len(name) != length:
            continue

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

    except Exception:

        return username, False


def find_available(length, style, amount=5):

    candidates = generate_candidates(
        length,
        style,
        60
    )

    available = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                check_username,
                username
            )
            for username in candidates
        ]

        for future in as_completed(futures):

            username, free = future.result()

            if free:

                available.append(username)

                if len(available) >= amount:
                    break

    return available


# ============================================================
# SEARCH HISTORY
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

    update_user(
        user_id,
        {
            "total_searches":
                int(user.get("total_searches", 0)) + 1,

            "found_nicks":
                int(user.get("found_nicks", 0)) + found
        }
    )


# ============================================================
# PAYMENT
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


# ============================================================
# SEND INVOICE
# ============================================================

def send_subscription_invoice(chat_id):

    payload = f"sub:{chat_id}:{random.randint(100000, 999999)}"

    bot.send_invoice(
        chat_id,
        "💎 UnixScan Premium",
        "10 поисков ников в день на 30 дней",
        payload=payload,
        amount_stars=SUB_PRICE
    )


def send_extra_invoice(chat_id):

    payload = f"extra:{chat_id}:{random.randint(100000, 999999)}"

    bot.send_invoice(
        chat_id,
        "⭐ Дополнительный запрос",
        "Один дополнительный поиск ников",
        payload=payload,
        amount_stars=EXTRA_PRICE
    )


# ============================================================
# /START
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

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=main_menu(user_id)
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler()
def callbacks(call):

    user_id = call.from_user.id

    # --------------------------------------------------------
    # BACK
    # --------------------------------------------------------

    if call.data == "back":

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            (
                "🔵 <b>UnixScan</b>\n\n"
                "Выбери действие:"
            ),
            reply_markup=main_menu(user_id)
        )

        return

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    if call.data == "search":

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            (
                "🔎 <b>Поиск ников</b>\n\n"
                "Выбери длину:"
            ),
            reply_markup=search_menu()
        )

        return

    # --------------------------------------------------------
    # LENGTH
    # --------------------------------------------------------

    if call.data.startswith("len_"):

        length = int(
            call.data.split("_")[1]
        )

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            (
                f"🔎 Длина: <b>{length}</b>\n\n"
                "Какой стиль ищем?"
            ),
            reply_markup=style_menu(length)
        )

        return

    # --------------------------------------------------------
    # STYLE
    # --------------------------------------------------------

    if call.data.startswith("style_"):

        parts = call.data.split("_")

        style = parts[1]
        length = int(parts[2])

        user = get_user(user_id)

        if not consume_request(user_id):

            bot.edit_message_text(
                call.message.chat.id,
                call.message.message_id,
                (
                    "🔒 <b>Лимит закончился</b>\n\n"
                    "У тебя больше нет доступных поисков.\n\n"
                    "💎 Подписка — 50 ⭐\n"
                    "⭐ Дополнительный поиск — 10 ⭐"
                ),
                reply_markup=after_search_menu()
            )

            return

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            (
                "🔎 <b>Ищу ники...</b>\n\n"
                f"📏 Длина: {length}\n"
                f"🎨 Стиль: {style}\n\n"
                "⏳ Проверяю доступность..."
            )
        )

        try:

            available = find_available(
                length,
                style,
                amount=5
            )

        except Exception as e:

            print(
                "SEARCH ERROR:",
                repr(e)
            )

            bot.edit_message_text(
                call.message.chat.id,
                call.message.message_id,
                (
                    "❌ Не удалось выполнить поиск.\n\n"
                    "Попробуй ещё раз."
                ),
                reply_markup=after_search_menu()
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

        if not available:

            text = (
                "🔎 <b>Результат</b>\n\n"
                "К сожалению, свободных вариантов "
                "не найдено.\n\n"
                "Попробуй другой стиль или длину."
            )

        else:

            lines = [
                f"💠 <code>{name}</code>"
                for name in available
            ]

            text = (
                "🔵 <b>Свободные ники</b>\n\n"
                + "\n".join(lines)
                + "\n\n"
                "⚡ Ники проверены прямо сейчас."
            )

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            text,
            reply_markup=after_search_menu()
        )

        return

    # --------------------------------------------------------
    # SUBSCRIPTION
    # --------------------------------------------------------

    if call.data == "subscription":

        user = get_user(user_id)

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            subscription_text(user),
            reply_markup=InlineKeyboardMarkup([
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
        )

        return

    # --------------------------------------------------------
    # BUY SUB
    # --------------------------------------------------------

    if call.data == "buy_subscription":

        send_subscription_invoice(
            call.message.chat.id
        )

        return

    # --------------------------------------------------------
    # BUY REQUEST
    # --------------------------------------------------------

    if call.data == "buy_request":

        send_extra_invoice(
            call.message.chat.id
        )

        return

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    if call.data == "stats":

        user = get_user(user_id)

        if subscription_active(user):

            sub_status = "💎 Активна"

        else:

            sub_status = "⚪ Нет"

        left = remaining_requests(user)

        text = (
            "📊 <b>Моя статистика</b>\n\n"
            f"🔎 Всего поисков: "
            f"<b>{user.get('total_searches', 0)}</b>\n"
            f"💠 Найдено ников: "
            f"<b>{user.get('found_nicks', 0)}</b>\n"
            f"⚡ Доступно запросов: "
            f"<b>{left}</b>\n"
            f"💎 Подписка: {sub_status}"
        )

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "↩️ Назад",
                        callback_data="back"
                    )
                ]
            ])
        )

        return

    # --------------------------------------------------------
    # HOW
    # --------------------------------------------------------

    if call.data == "how":

        text = (
            "ℹ️ <b>Как работает UnixScan</b>\n\n"
            "1️⃣ Ты выбираешь длину ника.\n\n"
            "2️⃣ Выбираешь стиль сочетания букв.\n\n"
            "3️⃣ UnixScan генерирует десятки "
            "вариантов.\n\n"
            "4️⃣ Каждый вариант проверяется через "
            "UnixGram.\n\n"
            "5️⃣ Ты получаешь только свободные ники.\n\n"
            "🎁 Бесплатно — 3 поиска в день.\n"
            "💎 Premium — 10 поисков в день.\n"
            "⭐ Можно докупать отдельные запросы."
        )

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "↩️ Назад",
                        callback_data="back"
                    )
                ]
            ])
        )

        return

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if call.data == "admin":

        if user_id != ADMIN_ID:
            return

        result = (
            supabase
            .table("users")
            .select("*")
            .execute()
        )

        users = result.data or []

        total_users = len(users)

        total_searches = sum(
            int(x.get("total_searches", 0))
            for x in users
        )

        total_found = sum(
            int(x.get("found_nicks", 0))
            for x in users
        )

        payments = (
            supabase
            .table("payments")
            .select("*")
            .execute()
        )

        payments_data = payments.data or []

        stars = sum(
            int(x.get("amount", 0))
            for x in payments_data
        )

        text = (
            "🛠 <b>Админ-панель</b>\n\n"
            f"👤 Пользователей: <b>{total_users}</b>\n"
            f"🔎 Поисков: <b>{total_searches}</b>\n"
            f"💠 Найдено ников: <b>{total_found}</b>\n"
            f"⭐ Получено Stars: <b>{stars}</b>\n"
            f"💳 Платежей: <b>{len(payments_data)}</b>"
        )

        bot.edit_message_text(
            call.message.chat.id,
            call.message.message_id,
            text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "↩️ Назад",
                        callback_data="back"
                    )
                ]
            ])
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

    except Exception as e:

        print(
            "PRECHECKOUT ERROR:",
            repr(e)
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
            f"PAYMENT: user={user_id}, "
            f"amount={amount}, "
            f"payload={payload}"
        )

        # Защита от повторной обработки.
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

            current = datetime.now(KYIV)

            until_raw = user.get(
                "subscription_until"
            )

            if until_raw:

                try:

                    old_until = datetime.fromisoformat(
                        until_raw.replace(
                            "Z",
                            "+00:00"
                        )
                    )

                    if old_until > current:

                        current = old_until.astimezone(
                            KYIV
                        )

                except Exception:
                    pass

            until = current + timedelta(
                days=SUB_DAYS
            )

            update_user(
                user_id,
                {
                    "subscription_until":
                        until.isoformat()
                }
            )

            bot.send_message(
                message.chat.id,
                (
                    "💎 <b>Подписка активирована!</b>\n\n"
                    "⭐ Оплата: <b>50 Stars</b>\n"
                    "🔎 Лимит: <b>10 поисков в день</b>\n"
                    f"📅 До: <b>{until.date()}</b>\n\n"
                    "Теперь можешь искать больше ников."
                ),
                reply_markup=main_menu(user_id)
            )

            return

        # ----------------------------------------------------
        # EXTRA REQUEST
        # ----------------------------------------------------

        if payload.startswith("extra:"):

            extra = int(
                user.get("extra_requests", 0)
            )

            update_user(
                user_id,
                {
                    "extra_requests": extra + 1
                }
            )

            bot.send_message(
                message.chat.id,
                (
                    "⭐ <b>Запрос добавлен!</b>\n\n"
                    "Тебе добавлен ещё <b>1 поиск</b>.\n\n"
                    "Можешь использовать его прямо сейчас."
                ),
                reply_markup=main_menu(user_id)
            )

            return

    except Exception as e:

        print(
            "PAYMENT ERROR:",
            repr(e)
        )


# ============================================================
# ERROR LOGGING
# ============================================================

def start_bot():

    print("===================================")
    print("🔵 UnixScan starting...")
    print("===================================")

    print(
        "Admin:",
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
