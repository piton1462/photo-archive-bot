import os
import sqlite3
import logging
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    ConversationHandler, filters
)

logging.basicConfig(level=logging.INFO)
WAITING = 1

GROUP_CHAT_ID = os.environ["ARCHIVE_CHAT_ID"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

def init_db():
    conn = sqlite3.connect("/tmp/photos.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id TEXT,
            lat REAL,
            lon REAL,
            address TEXT,
            archived_message_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def reverse_geocode(lat, lon):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ru"},
            headers={"User-Agent": "PhotoBot/1.0 (sniki1462@gmail.com)"},
            timeout=5
        )
        return r.json().get("display_name", f"{lat}, {lon}") if r.ok else f"{lat}, {lon}"
    except:
        return f"{lat}, {lon}"

async def start(update: Update, context):
    kb = [[KeyboardButton("📍 Отправить геопозицию", request_location=True)]]
    await update.message.reply_text(
        "Нажмите кнопку, чтобы отправить геопозицию, затем — фото.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
    )
    return WAITING

async def handle_input(update: Update, context):
    ud = context.user_data
    if update.message.location:
        lat, lon = update.message.location.latitude, update.message.location.longitude
        ud.update({"lat": lat, "lon": lon, "address": reverse_geocode(lat, lon)})
        await update.message.reply_text(f"📍 Адрес:\n{ud['address']}\nТеперь отправьте фото.")
        return WAITING
    elif update.message.photo:
        if "address" not in ud:
            await update.message.reply_text("Сначала отправьте геопозицию!")
            return WAITING
        photo = update.message.photo[-1]
        file_id = photo.file_id
        addr = ud["address"]
        user_id = update.effective_user.id
        msg = await context.bot.send_photo(GROUP_CHAT_ID, file_id, caption=f"📍 {addr}\n👤 {user_id}")
        conn = sqlite3.connect("/tmp/photos.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO photos (user_id, file_id, lat, lon, address, archived_message_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, file_id, ud["lat"], ud["lon"], addr, msg.message_id)
        )
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Сохранено!")
        ud.clear()
        return WAITING
    else:
        await update.message.reply_text("Отправьте геопозицию или фото.")
        return WAITING

async def gallery(update: Update, context):
    conn = sqlite3.connect("/tmp/photos.db")
    c = conn.cursor()
    c.execute("SELECT file_id, address FROM photos ORDER BY timestamp DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Архив пуст.")
        return
    for fid, addr in rows:
        try:
            await update.message.reply_photo(fid, caption=f"📍 {addr}")
        except:
            await update.message.reply_text(f"❌ Недоступно: {addr}")

async def search(update: Update, context):
    if not context.args:
        await update.message.reply_text("Используйте: /search <адрес>")
        return
    q = " ".join(context.args).lower()
    conn = sqlite3.connect("/tmp/photos.db")
    c = conn.cursor()
    c.execute("SELECT file_id, address FROM photos WHERE LOWER(address) LIKE ?", (f"%{q}%",))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Ничего не найдено.")
        return
    for fid, addr in rows:
        try:
            await update.message.reply_photo(fid, caption=f"📍 {addr}")
        except:
            await update.message.reply_text(f"Фото утеряно: {addr}")

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={WAITING: [MessageHandler(filters.LOCATION | filters.PHOTO, handle_input)]},
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("gallery", gallery))
    app.add_handler(CommandHandler("search", search))
    app.run_polling()

if __name__ == "__main__":
    main()
