import os
import threading
from flask import Flask

from unixgram import Bot
from openai import OpenAI


# ============================================================
# CONFIG
# ============================================================

UNIXGRAM_TOKEN = os.getenv("UNIXGRAM_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")

if not UNIXGRAM_TOKEN:
    raise RuntimeError("Не задан UNIXGRAM_TOKEN")

if not HF_TOKEN:
    raise RuntimeError("Не задан HF_TOKEN")


# ============================================================
# UNIXGRAM
# ============================================================

bot = Bot(UNIXGRAM_TOKEN)


# ============================================================
# AI
# ============================================================

ai = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN
)

MODEL = "openai/gpt-oss-120b:cerebras"


# История диалогов
# user_id -> список сообщений
histories = {}

MAX_HISTORY = 20


# ============================================================
# FLASK ДЛЯ RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def index():
    return "aniAI is running"


@app.route("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id

    histories[user_id] = []

    bot.send_message(
        message.chat.id,
        "Привет! Я aniAI.\n\n"
        "Я использую gpt-oss-120b.\n"
        "Просто напиши мне сообщение."
    )


# ============================================================
# CLEAR
# ============================================================

@bot.message_handler(commands=["clear"])
def clear(message):
    user_id = message.chat.id

    histories[user_id] = []

    bot.send_message(
        message.chat.id,
        "Контекст диалога очищен."
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Команды aniAI:\n\n"
        "/start — начать диалог\n"
        "/clear — очистить контекст\n"
        "/help — помощь\n\n"
        "Просто отправь сообщение, чтобы поговорить с ИИ."
    )


# ============================================================
# AI CHAT
# ============================================================

@bot.message_handler()
def ai_chat(message):

    user_id = message.chat.id
    text = message.text if hasattr(message, "text") else None

    if not text:
        return

    text = text.strip()

    if not text:
        return

    # Создаём историю
    if user_id not in histories:
        histories[user_id] = []

    history = histories[user_id]

    # Добавляем сообщение пользователя
    history.append({
        "role": "user",
        "content": text
    })

    # Ограничиваем историю
    history = history[-MAX_HISTORY:]
    histories[user_id] = history

    try:

        response = ai.chat.completions.create(
            model=MODEL,
            messages=history,
            temperature=0.7,
            max_tokens=1500
        )

        answer = response.choices[0].message.content

        if not answer:
            answer = "ИИ не вернул ответ."

        # Сохраняем ответ ИИ
        history.append({
            "role": "assistant",
            "content": answer
        })

        histories[user_id] = history[-MAX_HISTORY:]

        bot.send_message(
            message.chat.id,
            answer
        )

    except Exception as e:

        print("AI ERROR:", repr(e))

        bot.send_message(
            message.chat.id,
            "Произошла ошибка при обращении к ИИ."
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # Flask запускается отдельно,
    # чтобы Render видел открытый порт
    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    print("aniAI запущен")

    # UnixGram polling
    bot.polling()
