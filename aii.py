import requests
import io
import time
import re
import os # Meskipun API Key di-hardcode, 'os' mungkin masih berguna untuk hal lain

# Telegram Bot Library
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, File
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Google Gemini AI Library
import google.generativeai as genai
from PIL import Image # Pillow untuk memproses gambar

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = "7927741258:AAH4ARZUoVJhZiaTqDZCr3SvI5Wrp1naF70" # API Telegram Anda

# =====================================================================================
# --- !!! PENTING: ISI API KEY GEMINI ANDA DI SINI !!! ---
# Ganti string "MASUKKAN_API_KEY_GEMINI_ANDA_YANG_VALID_DISINI" 
# dengan API Key Gemini Anda yang sebenarnya.
# Contoh: GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac"
#
# PERINGATAN: Menyimpan API Key langsung di kode kurang aman jika kode ini akan Anda bagikan
# atau simpan di tempat penyimpanan kode publik (seperti GitHub).
# Untuk penggunaan pribadi di komputer Anda sendiri, ini bisa diterima.

GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # <--- GANTI INI DENGAN API KEY ANDA
# =====================================================================================

# Mengkonfigurasi dan menginisialisasi Model Gemini
gemini_vision_model = None # Inisialisasi di luar try agar variabel selalu ada
try:
    # Pengecekan apakah API Key sudah diisi dengan benar (bukan placeholder, tidak kosong, dan tidak terlalu pendek)
    if (not GOOGLE_GEMINI_API_KEY or
            GOOGLE_GEMINI_API_KEY == "MASUKKAN_API_KEY_GEMINI_ANDA_YANG_VALID_DISINI" or
            len(GOOGLE_GEMINI_API_KEY) < 30): # API Key Gemini biasanya lebih panjang dari 30 karakter

        print("--------------------------------------------------------------------------------")
        print("PERINGATAN: API Key Gemini (GOOGLE_GEMINI_API_KEY) di dalam kode belum diisi")
        print("            dengan benar, masih berupa placeholder, atau terlalu pendek.")
        print("            Harap edit skrip Python ini dan isi API Key Anda yang valid pada")
        print(f"            variabel GOOGLE_GEMINI_API_KEY (di bagian atas skrip).") 
        print("--------------------------------------------------------------------------------")
        # gemini_vision_model akan tetap None (karena diinisialisasi None di atas)
    else:
        # Jika API Key tampak sudah diisi dan memiliki panjang yang wajar, coba konfigurasi
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        # --- PERUBAHAN MODEL DI SINI ---
        gemini_vision_model = genai.GenerativeModel('gemini-1.5-flash-latest') 
        print("Model Gemini (gemini-1.5-flash-latest) berhasil diinisialisasi dengan API Key dari kode.")
except Exception as e:
    print(f"Error saat konfigurasi atau inisialisasi Model Gemini: {e}")
    print("Pastikan:")
    print("1. API Key Gemini yang Anda masukkan di kode sudah benar dan valid.")
    print("2. Layanan Generative Language API (untuk Gemini) sudah aktif di proyek Google Cloud Anda.")
    print("3. Library 'google-generativeai' sudah terinstal dengan benar (`pip install google-generativeai`).")
    # gemini_vision_model akan tetap None jika ada error

# --- Fungsi Analisis Gambar dengan Gemini ---
async def analyze_image_with_gemini(image_bytes: bytes, text_prompt: str):
    if not gemini_vision_model:
        return "Error: Model AI Gemini tidak terinisialisasi. Periksa pesan error saat bot dimulai terkait API Key dan konfigurasi."
    if not image_bytes:
        return "Error: Tidak ada data gambar untuk dianalisis."

    try:
        img = Image.open(io.BytesIO(image_bytes))
        contents = [text_prompt, img]
        # Untuk model Gemini 1.5, pastikan input sesuai. Biasanya list of parts [text, image] masih oke.
        response = await gemini_vision_model.generate_content_async(contents)
        
        if not response.parts: # Atau bisa jadi response.text langsung kosong jika ada masalah
            # Cek feedback untuk detail lebih lanjut jika ada
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"Analisis diblokir oleh AI. Alasan: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
            # Cek jika ada candidate yang kosong atau tidak ada text
            if not response.candidates or not response.candidates[0].content.parts or not response.candidates[0].content.parts[0].text:
                 return "AI tidak memberikan respons teks yang valid. Mungkin karena filter keamanan, gambar tidak jelas, atau API Key bermasalah."

        return response.text # Akses teks bisa sedikit berbeda tergantung struktur respons model baru
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
        "Halo! Saya bot NEZASTORE untuk membantu analisis pasar menggunakan AI.\n"
        "Kirimkan saya screenshot chart yang ingin Anda analisis.\n\n"
        "Anda juga bisa ketik /ai [NAMA_PAIR] sebelum mengirim screenshot untuk memberi label (opsional)."
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
            "Gunakan format /ai [NAMA_PAIR] untuk memberi label pada analisis screenshot Anda."
        )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    photo_file: File = await message.photo[-1].get_file()
    
    image_bytes_io = io.BytesIO()
    await photo_file.download_to_memory(image_bytes_io)
    image_bytes_io.seek(0)
    
    context.user_data['last_image_bytes'] = image_bytes_io.getvalue()

    label = context.user_data.get('market_info_label', "Screenshot")

    await message.reply_text(
        f"Screenshot untuk '{label}' diterima!\n"
        "Pilih jenis analisis yang Anda inginkan:"
    )

    keyboard_new_project = [
        [InlineKeyboardButton("Deskripsi Umum Chart", callback_data="ai_describe_chart")],
        [InlineKeyboardButton("Identifikasi Pola (Teks)", callback_data="ai_identify_pattern")],
        [InlineKeyboardButton("Saran Buy/Sell (Eksperimental)", callback_data="ai_buy_sell_signal")],
        [InlineKeyboardButton("Analisis Metode Kustom (Prompt)", callback_data="ai_custom_prompt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_new_project)
    await message.reply_text("Pilih aksi untuk screenshot ini:", reply_markup=reply_markup)

    if 'market_info_label' in context.user_data:
        del context.user_data['market_info_label']

# --- Callback Query Handlers ---
async def ai_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    image_bytes = context.user_data.get('last_image_bytes')

    if not image_bytes:
        await query.edit_message_text(text="Maaf, saya tidak menemukan gambar untuk dianalisis. Silakan kirim ulang.")
        return

    prompt = ""
    if callback_data == "ai_describe_chart":
        prompt = "Jelaskan secara umum apa yang kamu lihat pada chart trading ini. Fokus pada tren utama, potensi area support/resistance jika terlihat, dan kondisi candlestick terakhir jika signifikan."
        await query.edit_message_text(text="Menganalisis deskripsi umum chart dengan model baru...")
    elif callback_data == "ai_identify_pattern":
        prompt = "Analisis chart trading ini. Apakah kamu melihat pola chart klasik (misalnya, head and shoulders, double top/bottom, triangle, flag, pennant)? Jika ya, sebutkan polanya dan di mana kira-kira kamu melihatnya. Berikan juga level konfirmasi atau target potensial jika pola tersebut valid menurutmu."
        await query.edit_message_text(text="Mengidentifikasi pola chart (respons teks) dengan model baru...")
    elif callback_data == "ai_buy_sell_signal":
        prompt = (
            "PERHATIAN: Ini adalah analisis eksperimental dan BUKAN SARAN FINANSIAL.\n"
            "Berdasarkan chart trading ini, dan dengan menganalisis candlestick terakhir, potensi pola, serta area support/resistance yang mungkin terlihat, apakah ada kecenderungan sinyal 'buy' atau 'sell'? Berikan alasan singkat untuk analisismu. Ingatlah bahwa ini hanya interpretasi visual dari gambar statis."
        )
        await query.edit_message_text(text="Memberikan saran buy/sell (eksperimental) dengan model baru...")
    elif callback_data == "ai_custom_prompt":
        await query.message.reply_text("Silakan ketik prompt spesifik Anda untuk menganalisis gambar yang baru saja dikirim. Awali dengan /promptaisaya [prompt Anda]")
        return

    else:
        await query.edit_message_text(text=f"Pilihan tidak diketahui: {callback_data}")
        return
    
    ai_response = await analyze_image_with_gemini(image_bytes, prompt)
    await query.message.reply_text(f"**Hasil Analisis AI ({callback_data}):**\n\n{ai_response}", parse_mode='Markdown')


async def handle_custom_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    # Hapus 'import inspect' jika tidak digunakan untuk f_lineno
    # import inspect 
    
    if gemini_vision_model is None: # Cek utama apakah model berhasil dimuat
        print("--------------------------------------------------------------------------------")
        print("GAGAL MENJALANKAN BOT: Model Gemini gagal dimuat.")
        print("           Silakan periksa pesan PERINGATAN atau Error di atas terkait")
        print("           konfigurasi API Key Gemini di dalam kode skrip ini (di bagian atas skrip).")
        print("           Pastikan Anda sudah mengganti placeholder dengan API Key yang valid.")
        print("--------------------------------------------------------------------------------")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("label", label_command))
    application.add_handler(CommandHandler("promptaisaya", handle_custom_prompt))

    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(CallbackQueryHandler(ai_analysis_callback))

    print("Bot AI Analisis Screenshot sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
