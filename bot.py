import os
import random
import threading
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask
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
    raise RuntimeError("BOT_TOKEN is missing")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL or SUPABASE_KEY is missing")


bot = Bot(BOT_TOKEN)
db = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)


# ============================================================
# HELPERS
# ============================================================

def edit_html(chat_id, message_id, text, reply_markup=None):
    """edit_message_text() signature is (text, chat_id, message_id, reply_markup)
    and has no parse_mode kwarg - unlike send_message()."""
    bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)


# ============================================================
# RENDER
# ============================================================

@app.route("/")
def health():
    return "UnixScan is alive", 200


@app.route("/health")
def health_check():
    return "OK", 200


def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# ============================================================
# CONSTANTS
# ============================================================

FREE_REQUESTS = 3
SUB_REQUESTS = 10

SUB_PRICE = 50
EXTRA_REQUEST_PRICE = 10

USERNAME_CHECK_URL = "https://unixgram.com/api/account/username/check"

STYLES = {
    "mixed": {
        "name": "Смешанные",
        "consonants": [
            "b", "c", "d", "f", "g", "h", "j",
            "k", "l", "m", "n", "p", "r", "s",
            "t", "v", "w", "x", "y", "z"
        ],
        "vowels": [
            "a", "e", "i", "o", "u"
        ]
    }
}


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            "🔎 Найти ники",
            callback_data="find"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "💎 Подписка",
            callback_data="subscription"
        ),
        InlineKeyboardButton(
            "⭐ Купить запрос",
            callback_data="buy_request"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "📊 Моя статистика",
            callback_data="stats"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "ℹ️ Как это работает",
            callback_data="help"
        )
    )

    if ADMIN_ID:
        kb.row(
            InlineKeyboardButton(
                "🛠 Админ-панель",
                callback_data="admin"
            )
        )

    return kb


def back_button():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            "◀️ Назад",
            callback_data="back"
        )
    )

    return kb


def length_menu():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton("4 символа", callback_data="len_4"),
        InlineKeyboardButton("5 символов", callback_data="len_5")
    )

    kb.row(
        InlineKeyboardButton("6 символов", callback_data="len_6"),
        InlineKeyboardButton("7 символов", callback_data="len_7")
    )

    kb.row(
        InlineKeyboardButton(
            "◀️ Назад",
            callback_data="back"
        )
    )

    return kb


def result_menu():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            "🔄 Ещё 5",
            callback_data="find"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "◀️ Главное меню",
            callback_data="back"
        )
    )

    return kb


def admin_menu():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            "📊 Статистика бота",
            callback_data="admin_stats"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "👥 Пользователи",
            callback_data="admin_users"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "◀️ Назад",
            callback_data="back"
        )
    )

    return kb


# ============================================================
# DATABASE
# ============================================================

def get_user(user_id, username=None):
    result = (
        db.table("users")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if result.data:
        user = result.data[0]

        today = datetime.now(timezone.utc).date().isoformat()

        if user.get("request_date") != today:
            db.table("users").update({
                "requests_today": 0,
                "request_date": today
            }).eq("user_id", user_id).execute()

            user["requests_today"] = 0
            user["request_date"] = today

        return user

    data = {
        "user_id": user_id,
        "username": username,
        "requests_today": 0,
        "request_date": datetime.now(timezone.utc).date().isoformat(),
        "extra_requests": 0,
        "subscription_until": None,
        "total_searches": 0,
        "found_nicks": 0
    }

    db.table("users").insert(data).execute()

    return data


def increment_search(user_id, generated, available, length, style):
    user = get_user(user_id)

    db.table("users").update({
        "requests_today": user["requests_today"] + 1,
        "total_searches": user["total_searches"] + 1,
        "found_nicks": user["found_nicks"] + available
    }).eq("user_id", user_id).execute()

    db.table("searches").insert({
        "user_id": user_id,
        "length": length,
        "style": style,
        "generated": generated,
        "available": available
    }).execute()


def add_extra_request(user_id):
    user = get_user(user_id)

    db.table("users").update({
        "extra_requests": user["extra_requests"] + 1
    }).eq("user_id", user_id).execute()


def consume_extra_request(user_id):
    user = get_user(user_id)

    if user["extra_requests"] <= 0:
        return False

    db.table("users").update({
        "extra_requests": user["extra_requests"] - 1
    }).eq("user_id", user_id).execute()

    return True


# ============================================================
# SUBSCRIPTION
# ============================================================

def subscription_active(user):
    until = user.get("subscription_until")

    if not until:
        return False

    try:
        date = datetime.fromisoformat(
            until.replace("Z", "+00:00")
        )

        return date > datetime.now(timezone.utc)

    except Exception:
        return False


def subscription_text(user):
    if not subscription_active(user):
        return "❌ Подписка не активна"

    until = user["subscription_until"]

    return f"✅ Подписка активна\nДо: <code>{until[:10]}</code>"


def can_search(user_id):
    user = get_user(user_id)

    if subscription_active(user):
        if user["requests_today"] < SUB_REQUESTS:
            return True, "subscription"

    if user["requests_today"] < FREE_REQUESTS:
        return True, "free"

    if user["extra_requests"] > 0:
        return True, "extra"

    return False, None


def consume_search(user_id, search_type):
    user = get_user(user_id)

    if search_type == "extra":
        return consume_extra_request(user_id)

    db.table("users").update({
        "requests_today": user["requests_today"] + 1
    }).eq("user_id", user_id).execute()

    return True


# ============================================================
# USERNAME GENERATOR
# ============================================================

def generate_username(length, style):
    config = STYLES[style]

    consonants = config["consonants"]
    vowels = config["vowels"]

    result = ""

    use_consonant = random.choice([True, False])

    while len(result) < length:

        if use_consonant:
            char = random.choice(consonants)
        else:
            char = random.choice(vowels)

        if result and result[-1] == char:
            continue

        result += char

        use_consonant = not use_consonant

    bad_pairs = [
        "qq",
        "xx",
        "zz",
        "jj",
        "ww",
        "yy"
    ]

    if any(pair in result for pair in bad_pairs):
        return generate_username(length, style)

    if result[0] in vowels:
        if length >= 5 and random.random() < 0.5:
            pass

    return result


def check_username(username):
    try:
        response = requests.get(
            USERNAME_CHECK_URL,
            params={"value": username},
            timeout=5
        )

        if response.status_code != 200:
            return False

        data = response.json()

        return (
            data.get("success") is True
            and data.get("data", {}).get("status") == "available"
        )

    except Exception:
        return False


def find_available(length, style, amount=5):
    found = []
    checked = set()

    attempts = 0
    max_attempts = 80

    while len(found) < amount and attempts < max_attempts:
        attempts += 1

        username = generate_username(length, style)

        if username in checked:
            continue

        checked.add(username)

        if check_username(username):
            found.append(username)

    return found, len(checked)


# ============================================================
# TEXTS
# ============================================================

def start_text():
    return (
        "🔵 <b>UnixScan</b>\n\n"
        "Поиск свободных и звучных ников для UnixGram.\n\n"
        "Выбери действие:"
    )


def find_text():
    return (
        "🔎 <b>Поиск ников</b>\n\n"
        "Выбери длину ника:"
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    get_user(
        message.chat.id,
        getattr(message.from_user, "username", None)
        if hasattr(message, "from_user")
        else None
    )

    bot.send_message(
        message.chat.id,
        start_text(),
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# COMMANDS
# ============================================================

@bot.message_handler(commands=["find"])
def command_find(message):
    get_user(message.chat.id)

    bot.send_message(
        message.chat.id,
        find_text(),
        parse_mode="HTML",
        reply_markup=length_menu()
    )


@bot.message_handler(commands=["buy"])
def command_buy(message):
    send_extra_invoice(message.chat.id)


@bot.message_handler(commands=["sub"])
def command_sub(message):
    send_subscription_invoice(message.chat.id)


@bot.message_handler(commands=["stats"])
def command_stats(message):
    show_stats(message.chat.id)


@bot.message_handler(commands=["admin"])
def command_admin(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "❌ Нет доступа."
        )
        return

    bot.send_message(
        message.chat.id,
        "🛠 <b>Админ-панель</b>",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler()
def callback(query):

    user_id = query.message.chat.id
    data = query.data

    bot.answer_callback_query(query.id)

    if data == "back":
        edit_html(
            user_id,
            query.message.message_id,
            start_text(),
            reply_markup=main_menu()
        )
        return

    if data == "find":
        edit_html(
            user_id,
            query.message.message_id,
            find_text(),
            reply_markup=length_menu()
        )
        return

    if data.startswith("len_"):
        length = int(data.split("_")[1])

        perform_search(
            user_id,
            query.message.message_id,
            length,
            "mixed"
        )

        return

    if data == "subscription":
        show_subscription(
            user_id,
            query.message.message_id
        )
        return

    if data == "buy_request":
        send_extra_invoice(user_id)
        return

    if data == "stats":
        show_stats(
            user_id,
            query.message.message_id
        )
        return

    if data == "help":
        text = (
            "ℹ️ <b>Как это работает</b>\n\n"
            "UnixScan генерирует короткие звучные варианты "
            "и проверяет их через UnixGram.\n\n"
            "🆓 Бесплатно — 3 поиска в день.\n"
            "💎 Подписка — 10 поисков в день.\n"
            "⭐ Дополнительный поиск — 10 звёзд."
        )

        edit_html(
            user_id,
            query.message.message_id,
            text,
            reply_markup=back_button()
        )

        return

    if data == "admin":
        if user_id != ADMIN_ID:
            return

        edit_html(
            user_id,
            query.message.message_id,
            "🛠 <b>Админ-панель</b>",
            reply_markup=admin_menu()
        )

        return

    if data == "admin_stats":
        if user_id != ADMIN_ID:
            return

        show_admin_stats(
            user_id,
            query.message.message_id
        )

        return

    if data == "admin_users":
        if user_id != ADMIN_ID:
            return

        show_admin_users(
            user_id,
            query.message.message_id
        )

        return


# ============================================================
# SEARCH
# ============================================================

def perform_search(user_id, message_id, length, style):

    allowed, search_type = can_search(user_id)

    if not allowed:

        text = (
            "🔒 <b>Лимит закончился</b>\n\n"
            "Сегодня бесплатные поиски уже использованы.\n\n"
            "💎 Оформи подписку на 10 поисков в день\n"
            "или ⭐ купи один дополнительный поиск."
        )

        edit_html(
            user_id,
            message_id,
            text,
            reply_markup=main_menu()
        )

        return

    consume_search(user_id, search_type)

    edit_html(
        user_id,
        message_id,
        "🔎 Проверяю свободные ники..."
    )

    found, generated = find_available(
        length,
        style,
        amount=5
    )

    increment_search(
        user_id,
        generated,
        len(found),
        length,
        style
    )

    if found:

        lines = []

        for nick in found:
            lines.append(
                f"@<code>{nick}</code>"
            )

        result = (
            "🔵 <b>Свободные ники</b>\n\n"
            + "\n".join(lines)
            + "\n\n"
            f"Длина: <b>{length}</b>"
        )

    else:

        result = (
            "🔵 <b>UnixScan</b>\n\n"
            "Свободных вариантов не найдено.\n"
            "Попробуй другой стиль или длину."
        )

    edit_html(
        user_id,
        message_id,
        result,
        reply_markup=result_menu()
    )


# ============================================================
# SUBSCRIPTION
# ============================================================

def show_subscription(user_id, message_id=None):

    user = get_user(user_id)

    text = (
        "💎 <b>Подписка UnixScan</b>\n\n"
        "10 поисков каждый день.\n"
        "Без необходимости покупать запросы отдельно.\n\n"
        f"Цена: <b>{SUB_PRICE} ⭐</b>\n\n"
        f"{subscription_text(user)}"
    )

    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            f"💎 Купить за {SUB_PRICE} ⭐",
            callback_data="pay_subscription"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "◀️ Назад",
            callback_data="back"
        )
    )

    if message_id:

        edit_html(
            user_id,
            message_id,
            text,
            reply_markup=kb
        )

    else:

        bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=kb
        )


# ============================================================
# PAYMENTS
# ============================================================

def send_subscription_invoice(user_id):

    payload = f"subscription_{user_id}_{random.randint(100000, 999999)}"

    bot.send_invoice(
        user_id,
        "UnixScan Premium",
        "10 поисков ников каждый день",
        payload=payload,
        amount_stars=SUB_PRICE
    )


def send_extra_invoice(user_id):

    payload = f"extra_{user_id}_{random.randint(100000, 999999)}"

    bot.send_invoice(
        user_id,
        "Дополнительный поиск",
        "Один дополнительный поиск ников",
        payload=payload,
        amount_stars=EXTRA_REQUEST_PRICE
    )


@bot.callback_query_handler()
def payment_buttons(query):

    if query.data == "pay_subscription":

        bot.answer_callback_query(query.id)

        send_subscription_invoice(
            query.message.chat.id
        )


# ============================================================
# PRE CHECKOUT
# ============================================================

@bot.pre_checkout_query_handler()
def checkout(query):
    bot.answer_pre_checkout_query(
        query.id,
        ok=True
    )


# ============================================================
# SUCCESSFUL PAYMENT
# ============================================================

@bot.message_handler(content_types=["successful_payment"])
def successful_payment(message):

    payment = message.successful_payment

    user_id = message.chat.id
    payload = payment.invoice_payload

    if payload.startswith("subscription_"):

        from datetime import timedelta

        until = datetime.now(timezone.utc) + timedelta(days=30)

        db.table("users").update({
            "subscription_until": until.isoformat(),
            "requests_today": 0,
            "request_date": datetime.now(timezone.utc).date().isoformat()
        }).eq("user_id", user_id).execute()

        db.table("payments").insert({
            "user_id": user_id,
            "payload": payload,
            "amount": SUB_PRICE
        }).execute()

        bot.send_message(
            user_id,
            "💎 <b>Подписка активирована!</b>\n\n"
            "Теперь тебе доступно 10 поисков в день.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

    elif payload.startswith("extra_"):

        add_extra_request(user_id)

        db.table("payments").insert({
            "user_id": user_id,
            "payload": payload,
            "amount": EXTRA_REQUEST_PRICE
        }).execute()

        bot.send_message(
            user_id,
            "⭐ <b>Запрос добавлен!</b>\n\n"
            "Ты получил ещё один поиск.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )


# ============================================================
# STATISTICS
# ============================================================

def show_stats(user_id, message_id=None):

    user = get_user(user_id)

    if subscription_active(user):
        limit = SUB_REQUESTS
    else:
        limit = FREE_REQUESTS

    remaining = max(
        0,
        limit - user["requests_today"]
    )

    text = (
        "📊 <b>Моя статистика</b>\n\n"
        f"🔎 Поисков сегодня: "
        f"<b>{user['requests_today']}/{limit}</b>\n"
        f"🟢 Осталось: <b>{remaining}</b>\n"
        f"⭐ Дополнительных запросов: "
        f"<b>{user['extra_requests']}</b>\n\n"
        f"🔍 Всего поисков: "
        f"<b>{user['total_searches']}</b>\n"
        f"💎 Найдено ников: "
        f"<b>{user['found_nicks']}</b>\n\n"
        f"{subscription_text(user)}"
    )

    if message_id:

        edit_html(
            user_id,
            message_id,
            text,
            reply_markup=back_button()
        )

    else:

        bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=back_button()
        )


# ============================================================
# ADMIN
# ============================================================

def show_admin_stats(user_id, message_id):

    users = (
        db.table("users")
        .select("user_id", count="exact")
        .execute()
    )

    searches = (
        db.table("searches")
        .select("id", count="exact")
        .execute()
    )

    payments = (
        db.table("payments")
        .select("id", count="exact")
        .execute()
    )

    users_count = users.count if users.count is not None else 0
    searches_count = searches.count if searches.count is not None else 0
    payments_count = payments.count if payments.count is not None else 0

    text = (
        "📊 <b>Статистика UnixScan</b>\n\n"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"🔎 Поисков: <b>{searches_count}</b>\n"
        f"💳 Платежей: <b>{payments_count}</b>"
    )

    edit_html(
        user_id,
        message_id,
        text,
        reply_markup=back_button()
    )


def show_admin_users(user_id, message_id):

    result = (
        db.table("users")
        .select("user_id,username,total_searches,found_nicks")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    if not result.data:

        text = "👥 Пользователей пока нет."

    else:

        lines = ["👥 <b>Последние пользователи</b>\n"]

        for user in result.data:

            username = user.get("username")

            if username:
                name = f"@{username}"
            else:
                name = str(user["user_id"])

            lines.append(
                f"• {name} — "
                f"{user.get('total_searches', 0)} поисков"
            )

        text = "\n".join(lines)

    edit_html(
        user_id,
        message_id,
        text,
        reply_markup=back_button()
    )


# ============================================================
# FALLBACK
# ============================================================

@bot.message_handler()
def fallback(message):

    bot.send_message(
        message.chat.id,
        start_text(),
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    print("UnixScan started")

    bot.polling()
