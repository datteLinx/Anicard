from unixgram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from unixgram.api import InputFile
from supabase import create_client
from dotenv import load_dotenv

import os
import random
import time
import io
import tempfile
import urllib.request
import urllib.error

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

TOKEN = os.getenv("UNIXGRAM_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not TOKEN:
    raise RuntimeError("UNIXGRAM_TOKEN не задан")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL не задан")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY не задан")


bot = Bot(TOKEN)

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


ADMINS = {169}

pending_cards = {}

DROP_COOLDOWN = 6 * 60 * 60


# ============================================================
# RARITIES
# ============================================================

RARITIES = {
    "common": {
        "name": "Обычная",
        "chance": 55,
        "points": 10,
        "xp": 10
    },

    "rare": {
        "name": "Редкая",
        "chance": 25,
        "points": 25,
        "xp": 25
    },

    "epic": {
        "name": "Эпическая",
        "chance": 13,
        "points": 50,
        "xp": 50
    },

    "legendary": {
        "name": "Легендарная",
        "chance": 5,
        "points": 100,
        "xp": 100
    },

    "mythic": {
        "name": "Мифическая",
        "chance": 2,
        "points": 250,
        "xp": 250
    }
}


# ============================================================
# HELPERS
# ============================================================

def is_admin(user_id):
    return user_id in ADMINS


def ensure_user(message):
    user_id = message.from_user.id

    username = getattr(
        message.from_user,
        "username",
        ""
    ) or ""

    first_name = getattr(
        message.from_user,
        "first_name",
        ""
    ) or ""

    result = (
        supabase
        .table("users")
        .upsert({
            "user_id": user_id,
            "username": username,
            "first_name": first_name
        })
        .execute()
    )

    return user_id


def ensure_user_id(user_id):
    existing = (
        supabase
        .table("users")
        .select("user_id")
        .eq("user_id", user_id)
        .execute()
    )

    if not existing.data:
        (
            supabase
            .table("users")
            .insert({
                "user_id": user_id,
                "username": "",
                "first_name": "",
                "xp": 0,
                "points": 0,
                "cards_opened": 0,
                "last_drop": 0
            })
            .execute()
        )


def get_user(user_id):
    result = (
        supabase
        .table("users")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


def add_xp(user_id, amount):
    user = get_user(user_id)

    if not user:
        ensure_user_id(user_id)
        user = get_user(user_id)

    new_xp = user["xp"] + amount

    (
        supabase
        .table("users")
        .update({
            "xp": new_xp
        })
        .eq("user_id", user_id)
        .execute()
    )


def add_points(user_id, amount):
    user = get_user(user_id)

    if not user:
        ensure_user_id(user_id)
        user = get_user(user_id)

    new_points = user["points"] + amount

    (
        supabase
        .table("users")
        .update({
            "points": new_points
        })
        .eq("user_id", user_id)
        .execute()
    )


def get_level(xp):
    return xp // 100 + 1


# ============================================================
# INVENTORY
# ============================================================

def add_card_to_inventory(user_id, card_id):

    result = (
        supabase
        .table("inventory")
        .select("amount")
        .eq("user_id", user_id)
        .eq("card_id", card_id)
        .limit(1)
        .execute()
    )

    if result.data:

        amount = result.data[0]["amount"]

        (
            supabase
            .table("inventory")
            .update({
                "amount": amount + 1
            })
            .eq("user_id", user_id)
            .eq("card_id", card_id)
            .execute()
        )

        return True

    (
        supabase
        .table("inventory")
        .insert({
            "user_id": user_id,
            "card_id": card_id,
            "amount": 1
        })
        .execute()
    )

    return False


# ============================================================
# CARDS
# ============================================================

def random_rarity():

    value = random.uniform(0, 100)

    current = 0

    for rarity, data in RARITIES.items():

        current += data["chance"]

        if value <= current:
            return rarity

    return "common"


def get_random_card():

    rarity = random_rarity()

    result = (
        supabase
        .table("cards")
        .select("*")
        .eq("rarity", rarity)
        .execute()
    )

    cards = result.data

    if not cards:

        result = (
            supabase
            .table("cards")
            .select("*")
            .execute()
        )

        cards = result.data

    if not cards:
        return None

    return random.choice(cards)


def get_card(card_id):

    result = (
        supabase
        .table("cards")
        .select("*")
        .eq("id", card_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


# ============================================================
# COOLDOWN
# ============================================================

def can_open(user):

    now = int(time.time())

    last_drop = user["last_drop"] or 0

    return now - last_drop >= DROP_COOLDOWN


def get_remaining_cooldown(user):

    now = int(time.time())

    last_drop = user["last_drop"] or 0

    remaining = DROP_COOLDOWN - (now - last_drop)

    if remaining < 0:
        remaining = 0

    return remaining


def format_time(seconds):

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}ч {minutes}м"

    if minutes > 0:
        return f"{minutes}м {secs}с"

    return f"{secs}с"


def register_drop(user_id):

    now = int(time.time())

    (
        supabase
        .table("users")
        .update({
            "last_drop": now
        })
        .eq("user_id", user_id)
        .execute()
    )


# ============================================================
# STORAGE
# ============================================================

STORAGE_BUCKET = "anicards"


def upload_image(file_bytes, card_id):

    path = f"cards/{card_id}.jpg"

    (
        supabase
        .storage
        .from_(STORAGE_BUCKET)
        .upload(
            path,
            file_bytes,
            {
                "content-type": "image/jpeg",
                "cache-control": "31536000",
                "upsert": "true"
            }
        )
    )

    return path


def get_image_url(path):

    result = (
        supabase
        .storage
        .from_(STORAGE_BUCKET)
        .get_public_url(path)
    )

    return result


def download_image(path):

    data = (
        supabase
        .storage
        .from_(STORAGE_BUCKET)
        .download(path)
    )

    return data


# ============================================================
# PHOTO DOWNLOAD FROM UNIXGRAM
# ============================================================

def get_photo_bytes(message):
    if not message.photo:
        return None

    photo = message.photo[-1]

    if isinstance(photo, dict):
        file_id = photo.get("file_id")
    else:
        file_id = getattr(photo, "file_id", None)

    if not file_id:
        print("PHOTO ERROR: file_id не найден")
        print("PHOTO OBJECT:", repr(photo))
        return None

    print("PHOTO FILE ID:", file_id)

    # file_id в unixgram-py — это уже готовый URL на media.unixgram.com,
    # отдельного get_file/download_file в библиотеке нет
    try:
        req = urllib.request.Request(
            file_id,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        print("PHOTO DOWNLOADED:", len(data), "bytes")
        return data

    except urllib.error.URLError as e:
        print("DOWNLOAD ERROR:", repr(e))
        return None

# ============================================================
# KEYBOARD
# ============================================================

def main_keyboard():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton(
            "🎴 Карточка",
            callback_data="open_card"
        ),
        InlineKeyboardButton(
            "🎒 Инвентарь",
            callback_data="inventory"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "👤 Профиль",
            callback_data="profile"
        ),
        InlineKeyboardButton(
            "🏆 Топ",
            callback_data="top"
        )
    )

    kb.row(
        InlineKeyboardButton(
            "⭐ Поддержать",
            callback_data="donate_menu"
        )
    )

    return kb


# ============================================================
# OPEN CARD
# ============================================================

def open_random_card(chat_id, user_id):

    user = get_user(user_id)

    if not user:
        return

    if not can_open(user):

        remaining = get_remaining_cooldown(user)

        bot.send_message(
            chat_id,
            "⏳ Карточку пока нельзя открыть.\n\n"
            f"Следующая будет доступна через {format_time(remaining)}."
        )

        return

    card = get_random_card()

    if not card:

        bot.send_message(
            chat_id,
            "❌ В базе пока нет карточек."
        )

        return

    register_drop(user_id)

    rarity = RARITIES.get(
        card["rarity"],
        RARITIES["common"]
    )

    duplicate = add_card_to_inventory(
        user_id,
        card["id"]
    )

    add_xp(
        user_id,
        rarity["xp"]
    )

    add_points(
        user_id,
        rarity["points"]
    )

    if duplicate:

        text = (
            "🔁 Дубликат\n\n"
            f"🎴 {card['name']}\n"
            f"📺 {card['anime']}\n"
            f"💎 {rarity['name']}\n\n"
            f"⭐ +{rarity['points']} очков\n"
            f"✨ +{rarity['xp']} XP"
        )

    else:

        text = (
            "🎴 Новая карточка\n\n"
            f"👤 {card['name']}\n"
            f"📺 {card['anime']}\n"
            f"💎 {rarity['name']}\n\n"
            f"⭐ +{rarity['points']} очков\n"
            f"✨ +{rarity['xp']} XP"
        )

        image_path = card["image_path"]

    try:

        image_data = download_image(
            image_path
        )

        photo = InputFile(
            image_data,
            name="card.jpg",
            content_type="image/jpeg"
        )

        bot.send_photo(
            chat_id,
            photo
        )

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "IMAGE ERROR:",
            repr(e)
        )

        bot.send_message(
            chat_id,
            text
        )
# ============================================================
# CALLBACK — CARD
# ============================================================

@bot.callback_query_handler(
    func=lambda q: q.data == "open_card"
)
def callback_open_card(query):

    bot.answer_callback_query(
        query.id
    )

    user_id = query.from_user.id

    user = get_user(
        user_id
    )

    if not user:

        bot.send_message(
            query.message.chat.id,
            "Сначала /start."
        )

        return

    open_random_card(
        query.message.chat.id,
        user_id
    )


# ============================================================
# CALLBACK — INVENTORY
# ============================================================

@bot.callback_query_handler(
    func=lambda q: q.data == "inventory"
)
def callback_inventory(query):

    bot.answer_callback_query(
        query.id
    )

    user_id = query.from_user.id

    result = (
        supabase
        .table("inventory")
        .select(
            "card_id, amount, cards(name, anime, rarity)"
        )
        .eq("user_id", user_id)
        .order("card_id")
        .execute()
    )

    rows = result.data

    if not rows:

        bot.send_message(
            query.message.chat.id,
            "🎒 Инвентарь пуст."
        )

        return

    lines = [
        "🎒 Коллекция",
        ""
    ]

    for row in rows:

        card = row.get("cards")

        if not card:
            continue

        rarity = RARITIES.get(
            card["rarity"],
            RARITIES["common"]
        )

        lines.append(
            f"🎴 {card['name']}\n"
            f"   📺 {card['anime']}\n"
            f"   💎 {rarity['name']} · x{row['amount']}"
        )

    bot.send_message(
        query.message.chat.id,
        "\n".join(lines)
    )


# ============================================================
# CALLBACK — PROFILE
# ============================================================

@bot.callback_query_handler(
    func=lambda q: q.data == "profile"
)
def callback_profile(query):

    bot.answer_callback_query(
        query.id
    )

    user = get_user(
        query.from_user.id
    )

    if not user:

        bot.send_message(
            query.message.chat.id,
            "Сначала /start."
        )

        return

    inventory_result = (
        supabase
        .table("inventory")
        .select("amount")
        .eq(
            "user_id",
            query.from_user.id
        )
        .execute()
    )

    cards_count = sum(
        row["amount"]
        for row in inventory_result.data
    )

    unique_count = len(
        inventory_result.data
    )

    name = (
        user["first_name"]
        or user["username"]
        or str(user["user_id"])
    )

    bot.send_message(
        query.message.chat.id,
        "👤 Профиль\n\n"
        f" {name}\n"
        f" Очки: {user['points']}\n"
        f" XP: {user['xp']}\n"
        f" Уровень: {get_level(user['xp'])}\n"
        f" Карточек: {cards_count}\n"
        f" Уникальных: {unique_count}"
    )


# ============================================================
# CALLBACK — TOP
# ============================================================

@bot.callback_query_handler(
    func=lambda q: q.data == "top"
)
def callback_top(query):

    bot.answer_callback_query(
        query.id
    )

    result = (
        supabase
        .table("users")
        .select("*")
        .order(
            "points",
            desc=True
        )
        .limit(10)
        .execute()
    )

    users = result.data

    if not users:

        bot.send_message(
            query.message.chat.id,
            "🏆 Пока никто не набрал очков."
        )

        return

    lines = [
        "🏆 Топ",
        ""
    ]

    for i, user in enumerate(users):

        name = (
            user["first_name"]
            or user["username"]
            or str(user["user_id"])
        )

        lines.append(
            f"{i + 1}. {name} — "
            f"{user['points']}"
        )

    bot.send_message(
        query.message.chat.id,
        "\n".join(lines)
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    ensure_user(message)

    bot.send_message(
        message.chat.id,
        "🎴 Anicards\n\n"
        "Коллекционируй карточки аниме-персонажей.\n\n"
        "Открывай карточки и собирай коллекцию.\n"
        "За карточки получаешь XP и очки.\n\n"
        "Нажми кнопку ниже.\n\n"
        "Автор: @drowsy",
        reply_markup=main_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    ensure_user(message)

    bot.send_message(
        message.chat.id,
        "🎴 Anicards\n\n"
        "/card — открыть карточку\n"
        "/inventory — коллекция\n"
        "/profile — профиль\n"
        "/top — таблица лидеров\n"
        "/id — узнать свой ID\n"
        "/help — помощь"
    )


# ============================================================
# CARD COMMAND
# ============================================================

@bot.message_handler(
    commands=["card"]
)
def card_command(message):

    user_id = ensure_user(
        message
    )

    open_random_card(
        message.chat.id,
        user_id
    )


# ============================================================
# INVENTORY COMMAND
# ============================================================

@bot.message_handler(
    commands=["inventory"]
)
def inventory(message):

    user_id = ensure_user(
        message
    )

    result = (
        supabase
        .table("inventory")
        .select(
            "card_id, amount, cards(name, anime, rarity)"
        )
        .eq(
            "user_id",
            user_id
        )
        .order("card_id")
        .execute()
    )

    rows = result.data

    if not rows:

        bot.send_message(
            message.chat.id,
            "🎒 Инвентарь пуст.\n\n"
            "Открой первую карточку через /card"
        )

        return

    lines = [
        "🎒 Коллекция",
        ""
    ]

    for row in rows:

        card = row.get("cards")

        if not card:
            continue

        rarity = RARITIES.get(
            card["rarity"],
            RARITIES["common"]
        )

        lines.append(
            f"#{row['card_id']} — {card['name']}\n"
            f"   📺 {card['anime']} · "
            f"{rarity['name']} · "
            f"x{row['amount']}"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines)
    )


# ============================================================
# PROFILE COMMAND
# ============================================================

@bot.message_handler(
    commands=["profile"]
)
def profile(message):

    user_id = ensure_user(
        message
    )

    user = get_user(
        user_id
    )

    inventory_result = (
        supabase
        .table("inventory")
        .select("amount")
        .eq(
            "user_id",
            user_id
        )
        .execute()
    )

    cards_count = sum(
        row["amount"]
        for row in inventory_result.data
    )

    unique_count = len(
        inventory_result.data
    )

    name = (
        user["first_name"]
        or user["username"]
        or str(user_id)
    )

    bot.send_message(
        message.chat.id,
        " Профиль\n\n"
        f" {name}\n"
        f" Очки: {user['points']}\n"
        f" XP: {user['xp']}\n"
        f" Уровень: {get_level(user['xp'])}\n"
        f" Карточек: {cards_count}\n"
        f" Уникальных: {unique_count}"
    )


# ============================================================
# TOP COMMAND
# ============================================================

@bot.message_handler(
    commands=["top"]
)
def top(message):

    ensure_user(
        message
    )

    result = (
        supabase
        .table("users")
        .select("*")
        .order(
            "points",
            desc=True
        )
        .limit(10)
        .execute()
    )

    users = result.data

    if not users:

        bot.send_message(
            message.chat.id,
            "🏆 Пока никто не набрал очков."
        )

        return

    lines = [
        "🏆 Топ",
        ""
    ]

    for i, user in enumerate(users):

        name = (
            user["first_name"]
            or user["username"]
            or str(user["user_id"])
        )

        lines.append(
            f"{i + 1}. {name} — "
            f"{user['points']} ⭐"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines)
    )


# ============================================================
# ID
# ============================================================

@bot.message_handler(
    commands=["id"]
)
def get_id(message):

    bot.send_message(
        message.chat.id,
        f"Твой ID: {message.from_user.id}"
    )


# ============================================================
# ADMIN — ADD CARD
# ============================================================

@bot.message_handler(
    commands=["addcard"]
)
def addcard(message):

    user_id = ensure_user(
        message
    )

    if not is_admin(user_id):

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    if not message.text:
        return

    raw = message.text.replace(
        "/addcard",
        "",
        1
    ).strip()

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) != 4:

        bot.send_message(
            message.chat.id,
            "❌ Формат:\n"
            "/addcard Имя | Аниме | rarity | points"
        )

        return

    name, anime, rarity, points = parts

    if not name or not anime:

        bot.send_message(
            message.chat.id,
            "❌ Имя и аниме не могут быть пустыми."
        )

        return

    if rarity not in RARITIES:

        bot.send_message(
            message.chat.id,
            "❌ Неизвестная редкость.\n\n"
            "common\n"
            "rare\n"
            "epic\n"
            "legendary\n"
            "mythic"
        )

        return

    try:

        points = int(points)

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ Очки должны быть числом."
        )

        return

    pending_cards[user_id] = {
        "name": name,
        "anime": anime,
        "rarity": rarity,
        "points": points
    }

    bot.send_message(
        message.chat.id,
        "📷 Отправь изображение карточки следующим сообщением."
    )


# ============================================================
# ADMIN — PHOTO
# ============================================================

@bot.message_handler(
    content_types=["photo"]
)
def addcard_photo(message):

    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    if user_id not in pending_cards:
        return

    if not message.photo:
        return

    bot.send_message(
        message.chat.id,
        "⏳ Сохраняю изображение..."
    )

    image_bytes = get_photo_bytes(
        message
    )

    if not image_bytes:

        bot.send_message(
            message.chat.id,
            "❌ Не удалось скачать изображение из UnixGram."
        )

        return

    data = pending_cards.pop(
        user_id
    )

    try:

        # Сначала создаём карточку
        result = (
            supabase
            .table("cards")
            .insert({
                "name": data["name"],
                "anime": data["anime"],
                "rarity": data["rarity"],
                "points": data["points"],
                "image_path": "pending"
            })
            .execute()
        )

        card = result.data[0]

        card_id = card["id"]

        # Загружаем САМ файл в Supabase Storage
        image_path = upload_image(
            image_bytes,
            card_id
        )

        # Записываем путь в карточку
        (
            supabase
            .table("cards")
            .update({
                "image_path": image_path
            })
            .eq(
                "id",
                card_id
            )
            .execute()
        )

        bot.send_message(
            message.chat.id,
            "✅ Карточка добавлена!\n\n"
            f"🎴 {data['name']}\n"
            f"📺 {data['anime']}\n"
            f"💎 {RARITIES[data['rarity']]['name']}\n"
            f"⭐ {data['points']} очков"
        )

    except Exception as e:

        print(
            "ADD CARD ERROR:",
            repr(e)
        )

        # Если карточка создалась, но загрузка картинки упала
        try:
            if "card_id" in locals():

                supabase \
                    .table("cards") \
                    .delete() \
                    .eq("id", card_id) \
                    .execute()

        except Exception:
            pass

        bot.send_message(
            message.chat.id,
            "❌ Не удалось сохранить карточку."
        )


# ============================================================
# ADMIN — CARDS
# ============================================================

@bot.message_handler(
    commands=["cards"]
)
def cards_list(message):

    user_id = ensure_user(
        message
    )

    if not is_admin(user_id):

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    result = (
        supabase
        .table("cards")
        .select("*")
        .order("id")
        .execute()
    )

    cards = result.data

    if not cards:

        bot.send_message(
            message.chat.id,
            "Карточек пока нет."
        )

        return

    lines = [
        "🎴 КАРТОЧКИ",
        ""
    ]

    for card in cards:

        rarity = RARITIES.get(
            card["rarity"]
        )

        rarity_name = (
            rarity["name"]
            if rarity
            else card["rarity"]
        )

        lines.append(
            f"#{card['id']} | "
            f"{card['name']} | "
            f"{card['anime']} | "
            f"{rarity_name}"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines)
    )


# ============================================================
# ADMIN — DELETE CARD
# ============================================================

@bot.message_handler(
    commands=["delcard"]
)
def delcard(message):

    user_id = ensure_user(
        message
    )

    if not is_admin(user_id):

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    if not message.text:
        return

    parts = message.text.split()

    if len(parts) != 2:

        bot.send_message(
            message.chat.id,
            "Использование:\n"
            "/delcard ID"
        )

        return

    try:

        card_id = int(parts[1])

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ ID должен быть числом."
        )

        return

    card = get_card(
        card_id
    )

    if not card:

        bot.send_message(
            message.chat.id,
            "❌ Такой карточки нет."
        )

        return

    image_path = card["image_path"]

    # Удаляем картинку из Storage
    try:

        if image_path and image_path != "pending":

            (
                supabase
                .storage
                .from_(STORAGE_BUCKET)
                .remove([
                    image_path
                ])
            )

    except Exception as e:

        print(
            "STORAGE DELETE ERROR:",
            repr(e)
        )

    # Удаляем карточку.
    # inventory удалится каскадно.
    (
        supabase
        .table("cards")
        .delete()
        .eq(
            "id",
            card_id
        )
        .execute()
    )

    bot.send_message(
        message.chat.id,
        f"🗑 Карточка #{card_id} удалена."
    )


# ============================================================
# ADMIN — GIVE CARD
# ============================================================

@bot.message_handler(
    commands=["givecard"]
)
def givecard(message):

    user_id = ensure_user(
        message
    )

    if not is_admin(user_id):

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    if not message.text:
        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.send_message(
            message.chat.id,
            "Использование:\n"
            "/givecard USER_ID CARD_ID"
        )

        return

    try:

        target_id = int(parts[1])
        card_id = int(parts[2])

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ ID должны быть числами."
        )

        return

    card = get_card(
        card_id
    )

    if not card:

        bot.send_message(
            message.chat.id,
            "❌ Карточка не найдена."
        )

        return

    ensure_user_id(
        target_id
    )

    add_card_to_inventory(
        target_id,
        card_id
    )

    bot.send_message(
        message.chat.id,
        f"✅ Пользователю {target_id} "
        f"выдана карточка #{card_id}."
    )


# ============================================================
# ADMIN — GIVE XP
# ============================================================

@bot.message_handler(
    commands=["givexp"]
)
def givexp(message):

    user_id = ensure_user(
        message
    )

    if not is_admin(user_id):

        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )

        return

    if not message.text:
        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.send_message(
            message.chat.id,
            "Использование:\n"
            "/givexp USER_ID AMOUNT"
        )

        return

    try:

        target_id = int(parts[1])
        amount = int(parts[2])

    except ValueError:

        bot.send_message(
            message.chat.id,
            "❌ Используй числа."
        )

        return

    ensure_user_id(
        target_id
    )

    add_xp(
        target_id,
        amount
    )

    add_points(
        target_id,
        amount
    )

    bot.send_message(
        message.chat.id,
        f"✅ Пользователю {target_id} "
        f"выдано {amount} очков."
    )


# ============================================================
# ADMIN — BROADCAST
# ============================================================

@bot.message_handler(
    commands=["broadcast"]
)
def broadcast(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    if not message.text:
        return

    text = message.text.replace(
        "/broadcast",
        "",
        1
    ).strip()

    if not text:

        bot.send_message(
            message.chat.id,
            "Использование:\n"
            "/broadcast Текст рассылки"
        )

        return

    result = (
        supabase
        .table("users")
        .select("user_id")
        .execute()
    )

    users = result.data

    sent = 0
    failed = 0

    for user in users:

        target_id = user["user_id"]

        try:

            bot.send_message(
                target_id,
                text
            )

            sent += 1

        except Exception:

            failed += 1

    bot.send_message(
        message.chat.id,
        "Рассылка завершена.\n\n"
        f"Отправлено: {sent}\n"
        f"Не доставлено: {failed}"
    )


# ============================================================
# ADMIN — STATS
# ============================================================

@bot.message_handler(
    commands=["stats"]
)
def bot_stats(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    users_result = (
        supabase
        .table("users")
        .select("user_id", count="exact")
        .execute()
    )

    cards_result = (
        supabase
        .table("cards")
        .select("id", count="exact")
        .execute()
    )

    inventory_result = (
        supabase
        .table("inventory")
        .select("amount")
        .execute()
    )

    users_data = users_result.data or []
    cards_data = cards_result.data or []
    inventory_data = inventory_result.data or []

    users_count = (
        users_result.count
        if users_result.count is not None
        else len(users_data)
    )

    cards_count = (
        cards_result.count
        if cards_result.count is not None
        else len(cards_data)
    )

    inventory_cards = sum(
        row["amount"]
        for row in inventory_data
    )

    users_all = (
        supabase
        .table("users")
        .select(
            "cards_opened, points, xp"
        )
        .execute()
        .data
    )

    opened = sum(
        row["cards_opened"] or 0
        for row in users_all
    )

    points = sum(
        row["points"] or 0
        for row in users_all
    )

    xp = sum(
        row["xp"] or 0
        for row in users_all
    )

    bot.send_message(
        message.chat.id,
        "СТАТИСТИКА ANICARDS\n\n"
        f"Пользователей: {users_count}\n"
        f"Карточек в базе: {cards_count}\n"
        f"Карточек у пользователей: {inventory_cards}\n"
        f"Открытий: {opened}\n"
        f"Всего очков: {points}\n"
        f"Всего XP: {xp}"
    )

DONATE_AMOUNTS = [10, 50, 100, 250, 500]


def donation_keyboard():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton("⭐ 10", callback_data="donate_10"),
        InlineKeyboardButton("⭐ 50", callback_data="donate_50"),
        InlineKeyboardButton("⭐ 100", callback_data="donate_100")
    )

    kb.row(
        InlineKeyboardButton("⭐ 250", callback_data="donate_250"),
        InlineKeyboardButton("⭐ 500", callback_data="donate_500")
    )

    return kb


@bot.message_handler(commands=["donate"])
def donate(message):
    ensure_user(message)

    bot.send_message(
        message.chat.id,
        "⭐ Поддержать Anicards\n\n"
        "Выбери количество Telegram Stars, которое хочешь отправить:",
        reply_markup=donation_keyboard()
    )


@bot.callback_query_handler(
    func=lambda q: q.data.startswith("donate_")
)
def donation_callback(query):

    try:
        amount = int(query.data.replace("donate_", ""))
    except ValueError:
        bot.answer_callback_query(query.id, "❌ Ошибка.")
        return

    if amount not in DONATE_AMOUNTS:
        bot.answer_callback_query(query.id, "❌ Недопустимая сумма.")
        return

    bot.answer_callback_query(query.id)

    bot.send_invoice(
        query.message.chat.id,
        "Поддержка Anicards",
        f"Донат {amount} Telegram Stars",
        payload=f"donate-{amount}",
        amount_stars=amount
    )


@bot.pre_checkout_query_handler()
def donation_checkout(query):
    # Telegram требует ответить в течение 10 секунд.
    bot.answer_pre_checkout_query(
        query.id,
        ok=True
    )


@bot.message_handler(
    content_types=["successful_payment"]
)
def successful_donation(message):

    payment = message.successful_payment

    payload = getattr(
        payment,
        "invoice_payload",
        ""
    )

    if not payload.startswith("donate-"):
        return

    try:
        amount = int(payload.replace("donate-", ""))
    except ValueError:
        return

    user_id = message.from_user.id

    print(
        f"DONATION: user={user_id}, "
        f"amount={amount} Stars"
    )

    bot.send_message(
        message.chat.id,
        "⭐ Спасибо за поддержку Anicards!\n\n"
        f"Твой донат: {amount} Stars."
    )

@bot.callback_query_handler(
    func=lambda q: q.data == "donate_menu"
)
def donate_menu_callback(query):
    bot.answer_callback_query(query.id)

    bot.send_message(
        query.message.chat.id,
        "⭐ Поддержать Anicards\n\n"
        "Выбери количество Telegram Stars:",
        reply_markup=donation_keyboard()
    )

# ============================================================
# START
# ============================================================

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Anicards OK")

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server started on port {port}")
    server.serve_forever()

if __name__ == "__main__":

    threading.Thread(target=run_health_server, daemon=True).start()

    print("Anicards started!")

    bot.polling()
