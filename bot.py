import os
import logging
import requests
import psycopg2
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    ConversationHandler, filters
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
WAITING = 1

# Получаем токен и URL базы из переменных окружения
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

def init_db():
    """Создаёт таблицу, если её нет"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            file_id TEXT,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def reverse_geocode(lat, lon):
    """Преобразует координаты в адрес на русском языке"""
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "accept-language": "ru"
            },
            headers={"User-Agent": "PhotoBot/1.0 (sniki1462@gmail.com)"},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("display_name", f"{lat}, {lon}")
        return f"{lat}, {lon}"
    except Exception as e:
        return f"{lat}, {lon} (ошибка геокодирования)"

async def start(update: Update, context):
    """Начало диалога"""
    kb = [[KeyboardButton("📍 Отправить геопозицию", request_location=True)]]
    await update.message.reply_text(
        "Привет! Нажмите кнопку, чтобы отправить геопозицию, затем — фото.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
    )
    return WAITING

async def handle_input(update: Update, context):
    """Обработка геопозиции и фото"""
    user_data = context.user_data

    # Обработка геопозиции
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        address = reverse_geocode(lat, lon)
        user_data.update({"lat": lat, "lon": lon, "address": address})
        await update.message.reply_text(f"📍 Адрес:\n{address}\nТеперь отправьте фото.")
        return WAITING

    # Обработка фото
    elif update.message.photo:
        if "address" not in user_data:
            await update.message.reply_text("Сначала отправьте геопозицию!")
            return WAITING

        photo = update.message.photo[-1]
        file_id = photo.file_id
        address = user_data["address"]
        user_id = update.effective_user.id

        # Сохраняем в PostgreSQL
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO photos (user_id, file_id, lat, lon, address) VALUES (%s, %s, %s, %s, %s)",
            (user_id, file_id, user_data["lat"], user_data["lon"], address)
        )
        conn.commit()
        cur.close()
        conn.close()

        await update.message.reply_text("✅ Фото сохранено!")
        user_data.clear()
        return WAITING

    else:
        await update.message.reply_text("Пожалуйста, отправьте геопозицию или фото.")
        return WAITING

async def gallery(update: Update, context):
    """Показывает последние 10 фото"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT file_id, address FROM photos ORDER BY timestamp DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text("Архив пуст.")
        return

    for file_id, address in rows:
        try:
            await update.message.reply_photo(photo=file_id, caption=f"📍 {address}")
        except Exception:
            await update.message.reply_text(f"❌ Фото недоступно: {address}")

async def search(update: Update, context):
    """Поиск по адресу"""
    if not context.args:
        await update.message.reply_text("Используйте: /search <часть адреса>")
        return

    query = " ".join(context.args).lower()
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT file_id, address FROM photos WHERE LOWER(address) LIKE %s", (f"%{query}%",))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text("Ничего не найдено.")
        return

    for file_id, address in rows:
        try:
            await update.message.reply_photo(photo=file_id, caption=f"📍 {address}")
        except Exception:
            await update.message.reply_text(f"Фото утеряно: {address}")

def main():
    """Запуск бота"""
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={WAITING: [MessageHandler(filters.LOCATION | filters.PHOTO, handle_input)]},
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("gallery", gallery))
    app.add_handler(CommandHandler("search", search))

    app.run_polling()

if __name__ == "__main__":
    main()
