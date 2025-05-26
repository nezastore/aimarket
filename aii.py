import requests
import io
import time
import re
import os # Untuk mengambil API Key dari environment variable (lebih aman)

# Telegram Bot Library
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, File
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Google Gemini AI Library
import google.generativeai as genai
from PIL import Image # Pillow untuk memproses gambar

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = "7927741258:AAH4ARZUoVJhZiaTqDZCr3SvI5Wrp1naF70" # API Telegram Anda

# KONFIGURASI GEMINI API KEY:
# Cara 1: Langsung di kode (kurang aman, JANGAN lakukan ini di kode publik)
GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # GANTI DENGAN API KEY ANDA YANG VALID
genai.configure(api_key=AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac)

# Cara 2: Menggunakan environment variable (lebih aman)
# Anda perlu mengatur environment variable bernama GOOGLE_GEMINI_API_KEY dengan nilai API Key Anda.
try:
    GOOGLE_GEMINI_API_KEY = os.getenv("AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac")
    if not GOOGLE_GEMINI_API_KEY:
        print("PERINGATAN: Environment variable GOOGLE_GEMINI_API_KEY belum di-set.")
        # Fallback jika ingin tetap mencoba dengan string dari file (JANGAN lakukan di produksi)
        # GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # GANTI DENGAN API KEY ANDA
    genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
    # Inisialisasi model (hanya untuk vision)
    gemini_vision_model = genai.GenerativeModel('gemini-pro-vision')
    print("Model Gemini Pro Vision berhasil diinisialisasi.")
except Exception as e:
    print(f"Error konfigurasi Gemini API: {e}. Pastikan API Key valid dan library terinstal.")
    gemini_vision_model = None


# --- Fungsi Analisis Gambar dengan Gemini ---
async def analyze_image_with_gemini(image_bytes: bytes, text_prompt: str):
    if not gemini_vision_model:
        return "Error: Model AI Gemini tidak terinisialisasi. Periksa API Key dan konfigurasi."
    if not image_bytes:
        return "Error: Tidak ada data gambar untuk dianalisis."

    try:
        # Persiapkan konten gambar untuk API
        img = Image.open(io.BytesIO(image_bytes))
        
        # Model 'gemini-pro-vision' menerima list dari [text, image] atau [text, image, text, ...]
        contents = [text_prompt, img]
        
        response = await gemini_vision_model.generate_content_async(contents) # Gunakan async
        
        # Hati-hati dengan safety ratings, bisa menyebabkan tidak ada 'text'
        if not response.parts:
             # Cek apakah diblokir karena safety atau alasan lain
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"Analisis diblokir oleh AI. Alasan: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
            return "AI tidak memberikan respons teks. Mungkin karena filter keamanan atau gambar tidak jelas."

        return response.text
    except Exception as e:
        return f"Terjadi kesalahan saat berkomunikasi dengan AI Gemini: {str(e)}"

# --- Fungsi Deteksi Tipe Pasar (Sederhana) ---
def detect_market_and_normalize_symbol(user_symbol):
    user_symbol = user_symbol.upper().replace("/", "").replace(" ", "")
    if user_symbol:
        return {'type': 'manual', 'display_name': user_symbol, 'symbols': {'user_input': user_symbol}}
    return None

# --- Handler Bot Telegram ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Saya bot untuk membantu analisis pasar menggunakan AI.\n"
        "Kirimkan saya screenshot chart yang ingin Anda analisis.\n\n"
        "Anda juga bisa ketik /label [NAMA_PAIR] sebelum mengirim screenshot untuk memberi label (opsional)."
    )

async def label_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        user_symbol = context.args[0]
        market_info = detect_market_and_normalize_symbol(user_symbol)
        if market_info:
            context.user_data['market_info_label'] = market_info['display_name']
            await update.message.reply_text(
                f"Baik, analisis berikutnya akan diberi label '{market_info['display_name']}'.\n"
                "Sekarang, silakan kirim screenshot chart Anda."
            )
        else:
            await update.message.reply_text("Label tidak valid. Cukup kirim screenshot chart Anda.")
    else:
        await update.message.reply_text(
            "Gunakan format /label [NAMA_PAIR] untuk memberi label pada analisis screenshot Anda."
        )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    photo_file: File = await message.photo[-1].get_file()
    
    image_bytes_io = io.BytesIO()
    await photo_file.download_to_memory(image_bytes_io)
    image_bytes_io.seek(0) # Penting untuk reset pointer setelah download
    
    context.user_data['last_image_bytes'] = image_bytes_io.getvalue() # Simpan byte gambar

    label = context.user_data.get('market_info_label', "Screenshot")

    await message.reply_text(
        f"Screenshot untuk '{label}' diterima!\n"
        "Pilih jenis analisis yang Anda inginkan:"
    )

    keyboard_new_project = [
        [InlineKeyboardButton("Deskripsi Umum Chart", callback_data="ai_describe_chart")],
        [InlineKeyboardButton("Identifikasi Pola (Teks)", callback_data="ai_identify_pattern")],
        [InlineKeyboardButton("Saran Buy/Sell (Eksperimental)", callback_data="ai_buy_sell_signal")],
        [InlineKeyboardButton("Analisis Metode Kustom (Prompt)", callback_data="ai_custom_prompt")], # Untuk input prompt sendiri
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_new_project)
    await message.reply_text("Pilih aksi untuk screenshot ini:", reply_markup=reply_markup)

    # Reset label setelah digunakan
    if 'market_info_label' in context.user_data:
        del context.user_data['market_info_label']

# --- Callback Query Handlers ---
async def ai_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer() # Selalu jawab callback query

    callback_data = query.data
    image_bytes = context.user_data.get('last_image_bytes')

    if not image_bytes:
        await query.edit_message_text(text="Maaf, saya tidak menemukan gambar untuk dianalisis. Silakan kirim ulang.")
        return

    prompt = ""
    if callback_data == "ai_describe_chart":
        prompt = "Jelaskan secara umum apa yang kamu lihat pada chart trading ini. Fokus pada tren utama, potensi area support/resistance jika terlihat, dan kondisi candlestick terakhir jika signifikan."
        await query.edit_message_text(text="Menganalisis deskripsi umum chart...")
    elif callback_data == "ai_identify_pattern":
        prompt = "Analisis chart trading ini. Apakah kamu melihat pola chart klasik (misalnya, head and shoulders, double top/bottom, triangle, flag, pennant)? Jika ya, sebutkan polanya dan di mana kira-kira kamu melihatnya. Berikan juga level konfirmasi atau target potensial jika pola tersebut valid menurutmu."
        await query.edit_message_text(text="Mengidentifikasi pola chart (respons teks)...")
    elif callback_data == "ai_buy_sell_signal":
        prompt = (
            "PERHATIAN: Ini adalah analisis eksperimental dan BUKAN SARAN FINANSIAL.\n"
            "Berdasarkan chart trading ini, dan dengan menganalisis candlestick terakhir, potensi pola, serta area support/resistance yang mungkin terlihat, apakah ada kecenderungan sinyal 'buy' atau 'sell'? Berikan alasan singkat untuk analisismu. Ingatlah bahwa ini hanya interpretasi visual dari gambar statis."
        )
        await query.edit_message_text(text="Memberikan saran buy/sell (eksperimental)...")
    elif callback_data == "ai_custom_prompt":
        # Untuk prompt kustom, Anda bisa meminta pengguna mengirim prompt tambahan,
        # atau memiliki beberapa prompt yang sudah ditentukan sebelumnya.
        # Untuk saat ini, kita gunakan prompt generik lagi.
        # Nanti bisa dikembangkan jadi state conversation untuk meminta prompt dari user.
        await query.message.reply_text("Silakan ketik prompt spesifik Anda untuk menganalisis gambar yang baru saja dikirim. Awali dengan /promptaisaya [prompt Anda]")
        return # Tidak langsung menganalisis, tunggu input prompt dari user

    else:
        await query.edit_message_text(text=f"Pilihan tidak diketahui: {callback_data}")
        return
    
    # Lakukan analisis AI
    ai_response = await analyze_image_with_gemini(image_bytes, prompt)
    
    # Kirim hasil sebagai pesan baru agar tidak terpotong jika terlalu panjang untuk edit_message_text
    await query.message.reply_text(f"**Hasil Analisis AI ({callback_data}):**\n\n{ai_response}", parse_mode='Markdown')


async def handle_custom_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani prompt kustom dari pengguna setelah tombol 'Analisis Metode Kustom' ditekan."""
    if not context.args:
        await update.message.reply_text("Format salah. Gunakan: /promptaisaya [prompt Anda]")
        return

    custom_prompt = " ".join(context.args)
    image_bytes = context.user_data.get('last_image_bytes')

    if not image_bytes:
        await update.message.reply_text("Maaf, saya tidak menemukan gambar untuk dianalisis dengan prompt kustom ini. Silakan kirim ulang gambar terlebih dahulu, lalu pilih opsi kustom.")
        return

    await update.message.reply_text(f"Menganalisis gambar dengan prompt kustom Anda: '{custom_prompt[:50]}...'")
    
    ai_response = await analyze_image_with_gemini(image_bytes, custom_prompt)
    await update.message.reply_text(f"**Hasil Analisis AI (Prompt Kustom):**\n\n{ai_response}", parse_mode='Markdown')


# --- Main Function ---
def main():
    if not GOOGLE_GEMINI_API_KEY or gemini_vision_model is None:
        print("GAGAL MENJALANKAN BOT: API Key Gemini tidak terkonfigurasi atau model gagal dimuat.")
        print("Pastikan environment variable GOOGLE_GEMINI_API_KEY sudah di-set dengan benar.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("label", label_command))
    application.add_handler(CommandHandler("promptaisaya", handle_custom_prompt)) # Untuk menangani prompt kustom

    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CallbackQueryHandler(ai_analysis_callback)) # Menangani semua callback dari tombol AI

    print("Bot AI Analisis Screenshot sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
