import os
import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests
from dotenv import load_dotenv
from flask import Flask
from supabase import create_client, Client
from unixgram import Bot, types

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN обязательна")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Переменные окружения SUPABASE_URL и SUPABASE_KEY обязательны")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
PORT = int(os.getenv("PORT", "10000"))
FREE_DAILY_LIMIT = 3
SUB_DAILY_LIMIT = 10
SUB_PRICE_STARS = 50
EXTRA_PRICE_STARS = 10
SUB_DURATION_DAYS = 30
STARS_CURRENCY = "XTR"
STARS_PROVIDER_TOKEN = ""
SEARCH_LENGTHS = (4, 5, 6, 7)
TARGET_FOUND = 5
MAX_ATTEMPTS = 80
UNIXGRAM_USERNAME_CHECK_URL = "https://unixgram.com/api/account/username/check"
PAYLOAD_SUBSCRIPTION = "sub_month"
PAYLOAD_EXTRA_REQUEST = "extra_request"
VOWELS = "aeiou"
CONSONANTS = "bcdfghjklmnpqrstvwxyz"
BAD_PAIRS = {
    "qq",
    "xx",
    "zz",
    "qx",
    "xq",
    "qz",
    "zq",
    "jq",
    "qj",
    "vw",
    "wv",
    "cx",
    "xc",
}


def _letter_pool(is_vowel_slot: bool) -> str:
    return VOWELS if is_vowel_slot else CONSONANTS


def generate_username(length: int) -> str:
    start_with_vowel = random.choice([True, False])
    result = []
    for i in range(length):
        is_vowel_slot = (i % 2 == 0) == start_with_vowel
        pool = _letter_pool(is_vowel_slot)
        for _ in range(20):
            letter = random.choice(pool)
            if not result:
                result.append(letter)
                break
            prev = result[-1]
            if letter == prev:
                continue
            if prev + letter in BAD_PAIRS:
                continue
            result.append(letter)
            break
        else:
            candidates = [c for c in pool if c != result[-1]] if result else list(pool)
            result.append(random.choice(candidates))
    return "".join(result)


def check_username_available(nick: str, timeout: float = 5.0) -> Optional[bool]:
    try:
        resp = requests.get(
            UNIXGRAM_USERNAME_CHECK_URL, params={"value": nick}, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if not data.get("success"):
        return None
    status = data.get("data", {}).get("status")
    return status == "available"


def find_available_usernames(
    length: int, target_found: int, max_attempts: int, already_tried: set
):
    found = []
    attempts = 0
    tried_this_call = set()
    while attempts < max_attempts and len(found) < target_found:
        nick = generate_username(length)
        if nick in already_tried or nick in tried_this_call:
            continue
        tried_this_call.add(nick)
        attempts += 1
        available = check_username_available(nick)
        if available:
            found.append(nick)
    return (found, attempts, tried_this_call)


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_user(user_id: int, username: Optional[str] = None) -> dict:
    resp = supabase.table("users").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    if rows:
        user = rows[0]
        if username and user.get("username") != username:
            supabase.table("users").update({"username": username}).eq(
                "user_id", user_id
            ).execute()
            user["username"] = username
        return _reset_if_new_day(user)
    new_user = {
        "user_id": user_id,
        "username": username,
        "requests_today": 0,
        "request_date": _today_str(),
        "extra_requests": 0,
        "subscription_until": None,
        "total_searches": 0,
        "found_nicks": 0,
        "created_at": _now_iso(),
    }
    supabase.table("users").insert(new_user).execute()
    return new_user


def _reset_if_new_day(user: dict) -> dict:
    if user.get("request_date") != _today_str():
        supabase.table("users").update(
            {"requests_today": 0, "request_date": _today_str()}
        ).eq("user_id", user["user_id"]).execute()
        user["requests_today"] = 0
        user["request_date"] = _today_str()
    return user


def is_subscribed(user: dict) -> bool:
    until = user.get("subscription_until")
    if not until:
        return False
    try:
        until_dt = datetime.fromisoformat(until)
    except ValueError:
        return False
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=timezone.utc)
    return until_dt > datetime.now(timezone.utc)


def daily_limit_for(user: dict) -> int:
    return SUB_DAILY_LIMIT if is_subscribed(user) else FREE_DAILY_LIMIT


def can_perform_search(user: dict):
    user = _reset_if_new_day(user)
    limit = daily_limit_for(user)
    if user["requests_today"] < limit:
        return (True, "daily")
    if user.get("extra_requests", 0) > 0:
        return (True, "extra")
    return (False, None)


def register_search_usage(user_id: int, source: str, found_count: int):
    resp = supabase.table("users").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    if not rows:
        return
    user = rows[0]
    update = {
        "total_searches": user.get("total_searches", 0) + 1,
        "found_nicks": user.get("found_nicks", 0) + found_count,
    }
    if source == "daily":
        update["requests_today"] = user.get("requests_today", 0) + 1
    elif source == "extra":
        update["extra_requests"] = max(0, user.get("extra_requests", 0) - 1)
    supabase.table("users").update(update).eq("user_id", user_id).execute()


def record_search(
    user_id: int, length: int, style: str, generated: int, available: int
):
    supabase.table("searches").insert(
        {
            "user_id": user_id,
            "length": length,
            "style": style,
            "generated": generated,
            "available": available,
        }
    ).execute()


def record_payment(user_id: int, payload: str, amount: int):
    supabase.table("payments").insert(
        {"user_id": user_id, "payload": payload, "amount": amount}
    ).execute()


def grant_subscription(user_id: int):
    resp = supabase.table("users").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    now = datetime.now(timezone.utc)
    current_until = None
    if rows:
        raw = rows[0].get("subscription_until")
        if raw:
            try:
                parsed = datetime.fromisoformat(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed > now:
                    current_until = parsed
            except ValueError:
                pass
    base = current_until or now
    new_until = base + timedelta(days=SUB_DURATION_DAYS)
    supabase.table("users").update({"subscription_until": new_until.isoformat()}).eq(
        "user_id", user_id
    ).execute()


def grant_extra_request(user_id: int):
    resp = supabase.table("users").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    current = rows[0].get("extra_requests", 0) if rows else 0
    supabase.table("users").update({"extra_requests": current + 1}).eq(
        "user_id", user_id
    ).execute()


def get_user_stats(user_id: int) -> dict:
    resp = supabase.table("users").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    if not rows:
        return {}
    user = _reset_if_new_day(rows[0])
    limit = daily_limit_for(user)
    return {
        "requests_today": user.get("requests_today", 0),
        "daily_limit": limit,
        "remaining_today": max(0, limit - user.get("requests_today", 0)),
        "extra_requests": user.get("extra_requests", 0),
        "total_searches": user.get("total_searches", 0),
        "found_nicks": user.get("found_nicks", 0),
        "is_subscribed": is_subscribed(user),
        "subscription_until": user.get("subscription_until"),
    }


def get_admin_stats() -> dict:
    users_resp = supabase.table("users").select("user_id", count="exact").execute()
    searches_resp = supabase.table("searches").select("id", count="exact").execute()
    payments_resp = supabase.table("payments").select("id", count="exact").execute()
    recent_resp = (
        supabase.table("users")
        .select("user_id, username, total_searches")
        .order("total_searches", desc=True)
        .limit(10)
        .execute()
    )
    return {
        "user_count": users_resp.count or 0,
        "search_count": searches_resp.count or 0,
        "payment_count": payments_resp.count or 0,
        "recent_users": recent_resp.data or [],
    }


def main_menu(chat_id: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔎 Найти ники", callback_data="menu:search"),
        types.InlineKeyboardButton(
            "💎 Подписка / ⭐ Купить запрос", callback_data="menu:buy"
        ),
        types.InlineKeyboardButton("📊 Моя статистика", callback_data="menu:stats"),
        types.InlineKeyboardButton("ℹ️ Как это работает", callback_data="menu:help"),
    )
    if chat_id == ADMIN_ID:
        kb.add(types.InlineKeyboardButton("🛠 Админ-панель", callback_data="menu:admin"))
    return kb


def back_to_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main"))
    return kb


def length_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=len(SEARCH_LENGTHS))
    kb.add(
        *[
            types.InlineKeyboardButton(
                f"{length}", callback_data=f"search:len:{length}"
            )
            for length in SEARCH_LENGTHS
        ]
    )
    kb.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main"))
    return kb


def results_menu(length: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔁 Ещё 5", callback_data=f"search:more:{length}"),
        types.InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main"),
    )
    return kb


def buy_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "💎 Подписка на месяц — 50 ⭐", callback_data="buy:sub"
        ),
        types.InlineKeyboardButton("⭐ Доп. запрос — 10 ⭐", callback_data="buy:extra"),
        types.InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main"),
    )
    return kb


WELCOME_TEXT = "👋 <b>UnixScan</b>\n\nЯ нахожу свободные короткие юзернеймы на Unixgram.\nВыбери, что хочешь сделать:"
HELP_TEXT = "ℹ️ <b>Как это работает</b>\n\n1. Жми «🔎 Найти ники» и выбирай длину ника (4–7 символов).\n2. Бот генерирует произносимые сочетания букв и сразу проверяет их через официальный API Unixgram.\n3. Как только наберётся 5 свободных ников — покажу список. Можно запросить ещё 5 кнопкой «🔁 Ещё 5».\n\n<b>Лимиты:</b>\n• Бесплатно — 3 поиска в день\n• Подписка (50 ⭐/мес) — 10 поисков в день\n• Разовая покупка (10 ⭐) — +1 поиск сверх дневного лимита\n\nСчётчик поисков сбрасывается каждый день по UTC."


def format_stats_text(stats: dict) -> str:
    sub_line = "не активна"
    if stats.get("is_subscribed"):
        sub_line = f"активна до <code>{stats.get('subscription_until')}</code>"
    return f"📊 <b>Моя статистика</b>\n\nПоисков сегодня: <b>{stats['requests_today']}</b> / {stats['daily_limit']}\nОсталось сегодня: <b>{stats['remaining_today']}</b>\nДоп. запросов: <b>{stats['extra_requests']}</b>\nВсего поисков за всё время: <b>{stats['total_searches']}</b>\nВсего найдено ников: <b>{stats['found_nicks']}</b>\nПодписка: {sub_line}"


def format_admin_text(stats: dict) -> str:
    lines = [
        "🛠 <b>Админ-панель</b>\n",
        f"Пользователей: <b>{stats['user_count']}</b>",
        f"Поисков: <b>{stats['search_count']}</b>",
        f"Платежей: <b>{stats['payment_count']}</b>\n",
        "<b>Последние 10 пользователей по активности:</b>",
    ]
    for u in stats["recent_users"]:
        uname = u.get("username") or str(u.get("user_id"))
        lines.append(f"• {uname} — {u.get('total_searches', 0)} поисков")
    return "\n".join(lines)


def format_results_text(length: int, found: list, attempts: int) -> str:
    if not found:
        return f"😕 За {attempts} попыток не удалось найти свободный ник длиной {length}.\nПопробуй ещё раз или выбери другую длину."
    nick_lines = "\n".join((f"• <code>{n}</code>" for n in found))
    return f"✅ Найдено свободных ников (длина {length}, проверено попыток: {attempts}):\n\n{nick_lines}"


bot = Bot(BOT_TOKEN)
app = Flask(__name__)
search_sessions: dict = {}


@app.route("/")
def health():
    return ("OK", 200)


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


@bot.message_handler(commands=["start", "menu"])
def handle_start(message):
    get_or_create_user(message.chat.id, getattr(message.from_user, "username", None))
    bot.send_message(
        message.chat.id,
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu(message.chat.id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:main")
def cb_main_menu(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        WELCOME_TEXT,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=main_menu(call.message.chat.id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:help")
def cb_help(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        HELP_TEXT,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=back_to_menu(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:search")
def cb_search_menu(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "Выбери длину ника:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=length_menu(),
    )


def _run_search(chat_id: int, length: int, message_id: int = None):
    user = get_or_create_user(chat_id)
    can_search, source = can_perform_search(user)
    if not can_search:
        text = "🚫 Лимит поисков на сегодня исчерпан.\nОформи подписку или купи доп. запрос, чтобы продолжить."
        markup = buy_menu()
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        else:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        return
    session = search_sessions.setdefault(chat_id, {"length": length, "tried": set()})
    if session.get("length") != length:
        session = {"length": length, "tried": set()}
        search_sessions[chat_id] = session
    found, attempts, tried_now = find_available_usernames(
        length=length,
        target_found=TARGET_FOUND,
        max_attempts=MAX_ATTEMPTS,
        already_tried=session["tried"],
    )
    session["tried"] |= tried_now
    register_search_usage(chat_id, source, len(found))
    record_search(
        user_id=chat_id,
        length=length,
        style="alternating",
        generated=attempts,
        available=len(found),
    )
    text = format_results_text(length, found, attempts)
    markup = results_menu(length)
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("search:len:"))
def cb_search_length(call):
    bot.answer_callback_query(call.id)
    length = int(call.data.split(":")[-1])
    if length not in SEARCH_LENGTHS:
        return
    _run_search(call.message.chat.id, length, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("search:more:"))
def cb_search_more(call):
    bot.answer_callback_query(call.id)
    length = int(call.data.split(":")[-1])
    _run_search(call.message.chat.id, length, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "menu:stats")
def cb_stats(call):
    bot.answer_callback_query(call.id)
    get_or_create_user(call.message.chat.id)
    stats = get_user_stats(call.message.chat.id)
    bot.edit_message_text(
        format_stats_text(stats),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=back_to_menu(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:buy")
def cb_buy_menu(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"💎 <b>Подписка и доп. запросы</b>\n\n• Подписка на {SUB_DURATION_DAYS} дней — {SUB_PRICE_STARS} ⭐ (10 поисков/день)\n• Разовый доп. запрос — {EXTRA_PRICE_STARS} ⭐ (+1 поиск сверх лимита)",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=buy_menu(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "buy:sub")
def cb_buy_sub(call):
    bot.answer_callback_query(call.id)
    prices = [
        types.LabeledPrice(label="Подписка UnixScan (30 дней)", amount=SUB_PRICE_STARS)
    ]
    bot.send_invoice(
        call.message.chat.id,
        title="Подписка UnixScan",
        description="30 дней повышенного лимита поисков (10 в день).",
        invoice_payload=PAYLOAD_SUBSCRIPTION,
        provider_token=STARS_PROVIDER_TOKEN,
        currency=STARS_CURRENCY,
        prices=prices,
    )


@bot.callback_query_handler(func=lambda call: call.data == "buy:extra")
def cb_buy_extra(call):
    bot.answer_callback_query(call.id)
    prices = [types.LabeledPrice(label="Доп. запрос", amount=EXTRA_PRICE_STARS)]
    bot.send_invoice(
        call.message.chat.id,
        title="Доп. запрос UnixScan",
        description="+1 поиск сверх дневного лимита.",
        invoice_payload=PAYLOAD_EXTRA_REQUEST,
        provider_token=STARS_PROVIDER_TOKEN,
        currency=STARS_CURRENCY,
        prices=prices,
    )


@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)


@bot.message_handler(content_types=["successful_payment"])
def handle_successful_payment(message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    amount = payment.total_amount
    record_payment(message.chat.id, payload, amount)
    if payload == PAYLOAD_SUBSCRIPTION:
        grant_subscription(message.chat.id)
        text = f"✅ Подписка на {SUB_DURATION_DAYS} дней активирована!\nТеперь доступно 10 поисков в день."
    elif payload == PAYLOAD_EXTRA_REQUEST:
        grant_extra_request(message.chat.id)
        text = "✅ Доп. запрос добавлен! Можно использовать сверх дневного лимита."
    else:
        text = "✅ Оплата получена."
    bot.send_message(
        message.chat.id,
        text,
        parse_mode="HTML",
        reply_markup=main_menu(message.chat.id),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:admin")
def cb_admin(call):
    bot.answer_callback_query(call.id)
    if call.message.chat.id != ADMIN_ID:
        return
    stats = get_admin_stats()
    bot.edit_message_text(
        format_admin_text(stats),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=back_to_menu(),
    )


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("UnixScan bot started (polling)...")
    bot.polling(none_stop=True)
