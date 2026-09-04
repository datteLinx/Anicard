from unixgram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time

# ============================================================
# CONFIG
# ============================================================

TOKEN = "3116357841:9twhoSbV5tqEmHgp5zmc4LgqmsDeTnJJ"

# ID администраторов Anicards
ADMINS = {
    123456789,
}

# Сколько раз в сутки можно открыть карточку
DAILY_DROPS = 3

# Редкости
RARITIES = {
    "common": {
        "name": "Обычная",
        "chance": 55,
        "points": 10,
        "xp": 10,
    },
    "rare": {
        "name": "Редкая",
        "chance": 25,
        "points": 25,
        "xp": 25,
    },
    "epic": {
        "name": "Эпическая",
        "chance": 13,
        "points": 50,
        "xp": 50,
    },
    "legendary": {
        "name": "Легендарная",
        "chance": 5,
        "points": 100,
        "xp": 100,
    },
    "mythic": {
        "name": "Мифическая",
        "chance": 2,
        "points": 250,
        "xp": 250,
    },
}

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect("anicards.db", check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            xp INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            cards_opened INTEGER DEFAULT 0,
            last_drop INTEGER DEFAULT 0
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            anime TEXT NOT NULL,
            rarity TEXT NOT NULL,
            points INTEGER NOT NULL,
            image_url TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL,
            amount INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id)
        )
    """)

    db.commit()


init_db()


# ============================================================
# USERS
# ============================================================

def ensure_user(message):
    user_id = message.from_user.id

    username = getattr(message.from_user, "username", "") or ""
    first_name = getattr(message.from_user, "first_name", "") or ""

    db.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (user_id, username, first_name))

    db.commit()

    return user_id


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()


def add_xp(user_id, amount):
    db.execute(
        "UPDATE users SET xp = xp + ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()


def add_points(user_id, amount):
    db.execute(
        "UPDATE users SET points = points + ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()


def get_level(xp):
    # Каждые 100 XP = новый уровень
    return xp // 100 + 1


# ============================================================
# INVENTORY
# ============================================================

def add_card_to_inventory(user_id, card_id):
    existing = db.execute("""
        SELECT amount
        FROM inventory
        WHERE user_id = ? AND card_id = ?
    """, (user_id, card_id)).fetchone()

    if existing:
        db.execute("""
            UPDATE inventory
            SET amount = amount + 1
            WHERE user_id = ? AND card_id = ?
        """, (user_id, card_id))
        duplicate = True
    else:
        db.execute("""
            INSERT INTO inventory (user_id, card_id, amount)
            VALUES (?, ?, 1)
        """, (user_id, card_id))
        duplicate = False

    db.commit()
    return duplicate


# ============================================================
# RARITY
# ============================================================

def random_rarity():
    value = random.uniform(0, 100)

    current = 0

    for rarity, data in RARITIES.items():
        current += data["chance"]

        if value <= current:
            return rarity

    return "common"


# ============================================================
# CARDS
# ============================================================

def get_random_card():
    rarity = random_rarity()

    cards = db.execute("""
        SELECT *
        FROM cards
        WHERE rarity = ?
    """, (rarity,)).fetchall()

    # Если карточек такой редкости ещё нет,
    # берём любую существующую
    if not cards:
        cards = db.execute("""
            SELECT *
            FROM cards
        """).fetchall()

    if not cards:
        return None

    return random.choice(cards)


def get_card(card_id):
    return db.execute(
        "SELECT * FROM cards WHERE id = ?",
        (card_id,)
    ).fetchone()


# ============================================================
# LIMIT
# ============================================================

def can_open(user):
    now = int(time.time())

    if now - user["last_drop"] >= 86400:
        return True

    return user["cards_opened"] < DAILY_DROPS


def register_drop(user_id):
    now = int(time.time())
    user = get_user(user_id)

    if now - user["last_drop"] >= 86400:
        db.execute("""
            UPDATE users
            SET cards_opened = 1,
                last_drop = ?
            WHERE user_id = ?
        """, (now, user_id))
    else:
        db.execute("""
            UPDATE users
            SET cards_opened = cards_opened + 1
            WHERE user_id = ?
        """, (user_id,))

    db.commit()


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton("🎴 Карточка", callback_data="open_card"),
        InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory")
    )

    kb.row(
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("🏆 Топ", callback_data="top")
    )

    return kb


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = ensure_user(message)

    bot.send_message(
        message.chat.id,
        "🎴 <b>Anicards</b>\n\n"
        "Коллекционируй карточки аниме-персонажей.\n\n"
        "🎴 Открывай карточки\n"
        "🎒 Собирай коллекцию\n"
        "⭐ Получай XP и очки\n"
        "🏆 Попадай в таблицу лидеров\n\n"
        "Нажми кнопку ниже.",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    ensure_user(message)

    bot.send_message(
        message.chat.id,
        "🎴 <b>Anicards</b>\n\n"
        "/card — открыть карточку\n"
        "/inventory — твоя коллекция\n"
        "/profile — твой профиль\n"
        "/top — таблица лидеров\n"
        "/help — помощь",
        parse_mode="HTML"
    )


# ============================================================
# OPEN CARD
# ============================================================

@bot.message_handler(commands=["card"])
def open_card(message):
    user_id = ensure_user(message)
    user = get_user(user_id)

    if not can_open(user):
        bot.send_message(
            message.chat.id,
            "⏳ Ты уже открыл все карточки на сегодня.\n"
            "Попробуй завтра."
        )
        return

    card = get_random_card()

    if not card:
        bot.send_message(
            message.chat.id,
            "❌ В базе пока нет карточек."
        )
        return

    register_drop(user_id)

    rarity = RARITIES[card["rarity"]]

    duplicate = add_card_to_inventory(
        user_id,
        card["id"]
    )

    add_xp(user_id, rarity["xp"])
    add_points(user_id, rarity["points"])

    if duplicate:
        text = (
            "🔁 <b>Дубликат!</b>\n\n"
            f"🎴 <b>{card['name']}</b>\n"
            f"📺 {card['anime']}\n"
            f"💎 {rarity['name']}\n\n"
            f"⭐ +{rarity['points']} очков\n"
            f"✨ +{rarity['xp']} XP"
        )
    else:
        text = (
            "🎴 <b>НОВАЯ КАРТОЧКА!</b>\n\n"
            f"👤 <b>{card['name']}</b>\n"
            f"📺 {card['anime']}\n"
            f"💎 Редкость: <b>{rarity['name']}</b>\n"
            f"⭐ Очки: <b>{rarity['points']}</b>\n"
            f"✨ XP: <b>+{rarity['xp']}</b>"
        )

    bot.send_photo(
        message.chat.id,
        card["image_url"],
        caption=text,
        parse_mode="HTML"
    )


# ============================================================
# INVENTORY
# ============================================================

@bot.message_handler(commands=["inventory"])
def inventory(message):
    user_id = ensure_user(message)

    rows = db.execute("""
        SELECT
            cards.id,
            cards.name,
            cards.anime,
            cards.rarity,
            cards.points,
            inventory.amount
        FROM inventory
        JOIN cards ON cards.id = inventory.card_id
        WHERE inventory.user_id = ?
        ORDER BY cards.rarity DESC, cards.id
    """, (user_id,)).fetchall()

    if not rows:
        bot.send_message(
            message.chat.id,
            "🎒 <b>Инвентарь пуст.</b>\n\n"
            "Открой первую карточку через /card",
            parse_mode="HTML"
        )
        return

    lines = [
        "🎒 <b>ТВОЯ КОЛЛЕКЦИЯ</b>",
        ""
    ]

    for card in rows:
        rarity = RARITIES[card["rarity"]]

        lines.append(
            f"#{card['id']} — <b>{card['name']}</b>\n"
            f"   📺 {card['anime']} · "
            f"{rarity['name']} · x{card['amount']}"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ============================================================
# PROFILE
# ============================================================

@bot.message_handler(commands=["profile"])
def profile(message):
    user_id = ensure_user(message)
    user = get_user(user_id)

    level = get_level(user["xp"])

    cards_count = db.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM inventory
        WHERE user_id = ?
    """, (user_id,)).fetchone()[0]

    unique_count = db.execute("""
        SELECT COUNT(*)
        FROM inventory
        WHERE user_id = ?
    """, (user_id,)).fetchone()[0]

    name = user["first_name"] or user["username"] or str(user_id)

    bot.send_message(
        message.chat.id,
        "👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 {name}\n"
        f"⭐ Очки: <b>{user['points']}</b>\n"
        f"✨ XP: <b>{user['xp']}</b>\n"
        f"🏅 Уровень: <b>{level}</b>\n"
        f"🎴 Карточек: <b>{cards_count}</b>\n"
        f"📚 Уникальных: <b>{unique_count}</b>",
        parse_mode="HTML"
    )


# ============================================================
# LEADERBOARD
# ============================================================

@bot.message_handler(commands=["top"])
def top(message):
    ensure_user(message)

    users = db.execute("""
        SELECT *
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """).fetchall()

    if not users:
        bot.send_message(
            message.chat.id,
            "🏆 Пока никто не набрал очков."
        )
        return

    lines = ["🏆 <b>ТОП ANICARDS</b>", ""]

    medals = ["🥇", "🥈", "🥉"]

    for index, user in enumerate(users):
        medal = medals[index] if index < 3 else f"{index + 1}."

        name = (
            user["first_name"]
            or user["username"]
            or str(user["user_id"])
        )

        lines.append(
            f"{medal} <b>{name}</b> — "
            f"{user['points']} ⭐"
        )

    bot.send_message(
        message.chat.id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda q: q.data == "open_card"
)
def callback_open_card(query):
    bot.answer_callback_query(query.id)

    # Создаём объект, похожий на обычный message,
    # поэтому здесь проще просто отправить подсказку.
    bot.send_message(
        query.message.chat.id,
        "🎴 Используй /card"
    )


@bot.callback_query_handler(
    func=lambda q: q.data == "inventory"
)
def callback_inventory(query):
    bot.answer_callback_query(query.id)

    user_id = query.from_user.id

    rows = db.execute("""
        SELECT
            cards.name,
            cards.anime,
            cards.rarity,
            inventory.amount
        FROM inventory
        JOIN cards ON cards.id = inventory.card_id
        WHERE inventory.user_id = ?
    """, (user_id,)).fetchall()

    if not rows:
        bot.send_message(
            query.message.chat.id,
            "🎒 Инвентарь пуст."
        )
        return

    text = "🎒 <b>ИНВЕНТАРЬ</b>\n\n"

    for card in rows:
        text += (
            f"🎴 {card['name']} — "
            f"{RARITIES[card['rarity']]['name']} "
            f"x{card['amount']}\n"
        )

    bot.send_message(
        query.message.chat.id,
        text,
        parse_mode="HTML"
    )


@bot.callback_query_handler(
    func=lambda q: q.data == "profile"
)
def callback_profile(query):
    bot.answer_callback_query(query.id)

    user = get_user(query.from_user.id)

    if not user:
        bot.send_message(
            query.message.chat.id,
            "Используй /start"
        )
        return

    bot.send_message(
        query.message.chat.id,
        f"👤 <b>Профиль</b>\n\n"
        f"⭐ Очки: {user['points']}\n"
        f"✨ XP: {user['xp']}\n"
        f"🏅 Уровень: {get_level(user['xp'])}",
        parse_mode="HTML"
    )


@bot.callback_query_handler(
    func=lambda q: q.data == "top"
)
def callback_top(query):
    bot.answer_callback_query(query.id)

    users = db.execute("""
        SELECT *
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """).fetchall()

    text = "🏆 <b>ТОП</b>\n\n"

    for i, user in enumerate(users):
        name = (
            user["first_name"]
            or user["username"]
            or str(user["user_id"])
        )

        text += (
            f"{i + 1}. {name} — "
            f"{user['points']} ⭐\n"
        )

    bot.send_message(
        query.message.chat.id,
        text,
        parse_mode="HTML"
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return user_id in ADMINS


@bot.message_handler(commands=["addcard"])
def addcard(message):
    user_id = ensure_user(message)

    if not is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )
        return

    # Формат:
    # /addcard Имя | Аниме | rarity | points | image_url

    raw = message.text.replace("/addcard", "", 1).strip()

    parts = [x.strip() for x in raw.split("|")]

    if len(parts) != 5:
        bot.send_message(
            message.chat.id,
            "❌ Формат:\n\n"
            "/addcard Имя | Аниме | rarity | points | image_url\n\n"
            "Редкости:\n"
            "common\n"
            "rare\n"
            "epic\n"
            "legendary\n"
            "mythic"
        )
        return

    name, anime, rarity, points, image_url = parts

    if rarity not in RARITIES:
        bot.send_message(
            message.chat.id,
            "❌ Неизвестная редкость."
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

    cur = db.execute("""
        INSERT INTO cards
        (name, anime, rarity, points, image_url)
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        anime,
        rarity,
        points,
        image_url
    ))

    db.commit()

    card_id = cur.lastrowid

    bot.send_message(
        message.chat.id,
        "✅ <b>Карточка добавлена!</b>\n\n"
        f"ID: <b>#{card_id}</b>\n"
        f"👤 {name}\n"
        f"📺 {anime}\n"
        f"💎 {RARITIES[rarity]['name']}\n"
        f"⭐ {points}",
        parse_mode="HTML"
    )


# ============================================================
# ADMIN CARD LIST
# ============================================================

@bot.message_handler(commands=["cards"])
def cards_list(message):
    user_id = ensure_user(message)

    if not is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )
        return

    cards = db.execute("""
        SELECT *
        FROM cards
        ORDER BY id
    """).fetchall()

    if not cards:
        bot.send_message(
            message.chat.id,
            "Карточек пока нет."
        )
        return

    text = "🎴 <b>КАРТОЧКИ</b>\n\n"

    for card in cards:
        text += (
            f"#{card['id']} | "
            f"{card['name']} | "
            f"{card['anime']} | "
            f"{RARITIES[card['rarity']]['name']}\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="HTML"
    )


# ============================================================
# ADMIN DELETE
# ============================================================

@bot.message_handler(commands=["delcard"])
def delcard(message):
    user_id = ensure_user(message)

    if not is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )
        return

    parts = message.text.split()

    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "Использование:\n/delcard ID"
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

    card = get_card(card_id)

    if not card:
        bot.send_message(
            message.chat.id,
            "❌ Такой карточки нет."
        )
        return

    db.execute(
        "DELETE FROM cards WHERE id = ?",
        (card_id,)
    )

    db.execute(
        "DELETE FROM inventory WHERE card_id = ?",
        (card_id,)
    )

    db.commit()

    bot.send_message(
        message.chat.id,
        f"🗑 Карточка #{card_id} удалена."
    )


# ============================================================
# ADMIN GIVE CARD
# ============================================================

@bot.message_handler(commands=["givecard"])
def givecard(message):
    user_id = ensure_user(message)

    if not is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )
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

    card = get_card(card_id)

    if not card:
        bot.send_message(
            message.chat.id,
            "❌ Карточка не найдена."
        )
        return

    if not get_user(target_id):
        db.execute("""
            INSERT INTO users (user_id)
            VALUES (?)
        """, (target_id,))
        db.commit()

    add_card_to_inventory(
        target_id,
        card_id
    )

    bot.send_message(
        message.chat.id,
        f"✅ Пользователю <b>{target_id}</b> "
        f"выдана карточка #{card_id}.",
        parse_mode="HTML"
    )


# ============================================================
# ADMIN XP
# ============================================================

@bot.message_handler(commands=["id"])
def get_id(message):
    bot.send_message(
        message.chat.id,
        f"Твой ID: {message.from_user.id}"
    )

@bot.message_handler(commands=["givexp"])
def givexp(message):
    user_id = ensure_user(message)

    if not is_admin(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ Нет доступа."
        )
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

    if not get_user(target_id):
        db.execute(
            "INSERT INTO users (user_id) VALUES (?)",
            (target_id,)
        )
        db.commit()

    add_xp(target_id, amount)

    bot.send_message(
        message.chat.id,
        f"✅ Выдано <b>{amount} XP</b> "
        f"пользователю {target_id}.",
        parse_mode="HTML"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    print("Anicards started!")
    bot.polling()
