import requests
import io
import time
import re
import os

# Telegram Bot Library
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, File
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Google Gemini AI Library
import google.generativeai as genai
from PIL import Image

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = "7927741258:AAH4ARZUoVJhZiaTqDZCr3SvI5Wrp1naF70" # Ganti dengan Token Bot Anda

# =====================================================================================
# --- !!! PENTING: ISI API KEY GEMINI ANDA DI SINI !!! ---
# Ganti string "MASUKKAN_API_KEY_GEMINI_ANDA_YANG_VALID_DISINI" 
# dengan API Key Gemini Anda yang sebenarnya.
# Contoh: GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac"
GOOGLE_GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # <--- GANTI INI
# =====================================================================================

# Prompt Default untuk Analisis Otomatis Screenshot
DEFAULT_ANALYSIS_PROMPT = (
    "Anda adalah seorang analis teknikal pasar keuangan.  Analisis ini bersifat Profesional dan Tingkat kecerdasan Program.\n\n"
    "Analisis screenshot chart trading berikut ini secara detail. Fokus pada elemen-elemen berikut jika terlihat dengan jelas di gambar:\n"
    "1. Perkiraan Harga Saat Ini: (jika ada skala harga yang jelas dan mudah dibaca).\n"
    "2. Tren Utama: (Contoh: Naik, Turun, Sideways/Konsolidasi).\n"
    "3. Pola Candlestick/Chart Signifikan: (Contoh: Doji di Puncak/Lembah, Engulfing, Hammer, Shooting Star, Head and Shoulders, Double Top/Bottom, Triangle, Flag, Wedge, Channel).\n"
    "4. Kondisi Indikator Teknikal Utama (jika terlihat jelas): (Contoh: RSI (Oversold <30, Overbought >70, Divergence), MACD (Golden/Death Cross, Divergence, Posisi Histogram), Moving Averages (Posisi harga terhadap MA, Golden/Death Cross MA), Bollinger Bands (Harga menyentuh upper/lower band, Squeeze)).\n"
    "5. Level Support dan Resistance Kunci: (Identifikasi beberapa level S&R penting yang terlihat).\n\n"
    "6. Gunakan strategi Pola 7 Candle & Teknik 7 Naga.\n"
    "Berdasarkan semua observasi di atas, berikan:\n"
    "A. **Saran Trading Keseluruhan:** (BUY, SELL, atau NETRAL/WAIT)\n"
    "B. **Alasan Utama (poin-poin):** (Berikan minimal 2-3 alasan utama untuk saran trading Anda, merujuk pada observasi dari poin 1-5 di atas).\n"
    "C. **Potensi Level Penting (jika teridentifikasi dari chart):**\n"
    "   - Target Profit (TP) potensial: [jika ada]\n"
    "   - Stop Loss (SL) potensial: [jika ada]\n\n"
    "Struktur jawaban Anda sebaiknya jelas, terperinci, dan menggunakan poin-poin atau heading untuk setiap bagian. Ingat, ini adalah Trading forex maka usahakan semaksimal mungkin untuk analisa."
)

# Mengkonfigurasi dan menginisialisasi Model Gemini
gemini_vision_model = None
try:
    if (not GOOGLE_GEMINI_API_KEY or
            GOOGLE_GEMINI_API_KEY == "MASUKKAN_API_KEY_GEMINI_ANDA_YANG_VALID_DISINI" or
            len(GOOGLE_GEMINI_API_KEY) < 30):
        print("--------------------------------------------------------------------------------")
        print("PERINGATAN: API Key Gemini (GOOGLE_GEMINI_API_KEY) di dalam kode belum diisi")
        print("            dengan benar, masih berupa placeholder, kosong, atau terlalu pendek.")
        print("            Harap edit skrip Python ini dan isi API Key Anda yang valid pada")
        print(f"            variabel GOOGLE_GEMINI_API_KEY (di bagian atas skrip).")
        print("--------------------------------------------------------------------------------")
    else:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        gemini_vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Model Gemini (gemini-1.5-flash-latest) berhasil diinisialisasi.")
except Exception as e:
    print(f"Error saat konfigurasi atau inisialisasi Model Gemini: {e}")
    print("Pastikan API Key valid, layanan Gemini API aktif, dan library 'google-generativeai' terinstal.")

# --- Fungsi Analisis Gambar dengan Gemini ---
async def analyze_image_with_gemini(image_bytes: bytes, text_prompt: str):
    if not gemini_vision_model:
        return "Error: Model AI tidak terinisialisasi. Periksa pesan error saat bot dimulai."
    if not image_bytes:
        return "Error: Tidak ada data gambar untuk dianalisis."
    try:
        img = Image.open(io.BytesIO(image_bytes))
        contents = [text_prompt, img]
        response = await gemini_vision_model.generate_content_async(contents)
        if not response.parts:
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                return f"Analisis diblokir: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
            if not response.candidates or not hasattr(response.candidates[0], 'content') or not response.candidates[0].content.parts or not hasattr(response.candidates[0].content.parts[0], 'text'):
                return "AI tidak memberikan respons teks yang valid."
        return response.text
    except Exception as e:
        return f"Kesalahan komunikasi dengan AI : {str(e)}"

# --- Handler Bot Telegram ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✨ Halo! Saya BotNeza Analis Pasar Finansial v2.0 ✨\n\n"
        "➡️ **Cara Penggunaan:**\n"
        "1. Kirimkan saya screenshot chart trading Anda.\n"
        "   Bot akan otomatis memberikan analisis pasar mendalam (saran Buy/Sell, alasan, dll.).\n"
        "2. (Opsional) Gunakan `/label NAMA_PAIR` *sebelum* mengirim gambar untuk memberi label pada analisis.\n"
        "3. (Opsional) Setelah mengirim screenshot, gunakan `/ai PROMPT_KUSTOM_ANDA` untuk bertanya hal spesifik terkait screenshot tersebut.\n\n"
        "Pastikan screenshot chart Anda jelas. Mari mulai!"
    )

async def label_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        user_symbol = " ".join(context.args) # Memungkinkan label dengan spasi
        context.user_data['market_info_label'] = user_symbol
        await update.message.reply_text(
            f"🏷️ Label '{user_symbol}' disiapkan.\n"
            "Sekarang, silakan kirim screenshot chart Anda."
        )
    else:
        await update.message.reply_text(
            "Gunakan format /label [NAMA_PAIR_ATAU_LABEL_ANDA] (contoh: /label EURUSD Timeframe H1)."
        )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    photo_file: File = await message.photo[-1].get_file()
    
    image_bytes_io = io.BytesIO()
    await photo_file.download_to_memory(image_bytes_io)
    image_bytes_io.seek(0)
    
    # Simpan byte gambar untuk digunakan oleh perintah /ai nanti
    context.user_data['last_image_bytes'] = image_bytes_io.getvalue()

    label = context.user_data.get('market_info_label', "Screenshot")
    
    processing_message = await message.reply_text(
        f"🖼️ Screenshot untuk '{label}' diterima!\n"
        f"⏳ Menganalisis secara otomatis dengan AI ... Mohon tunggu sebentar."
    )

    ai_response = await analyze_image_with_gemini(image_bytes_io.getvalue(), DEFAULT_ANALYSIS_PROMPT)
    
    try: # Hapus pesan "Menganalisis..."
        await processing_message.delete()
    except Exception:
        pass

    await message.reply_text(f"**🤖 Hasil Analisis Otomatis untuk '{label}'**:\n\n{ai_response}", parse_mode='Markdown')

    # Reset label setelah digunakan untuk analisis otomatis
    if 'market_info_label' in context.user_data:
        del context.user_data['market_info_label']

async def ai_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani perintah /ai untuk prompt kustom terhadap gambar terakhir."""
    if not context.args:
        await update.message.reply_text("⚠️ Format salah. Gunakan: /ai [prompt kustom Anda]\nContoh: /ai apakah ada pola bearish divergence di RSI?")
        return

    custom_prompt = " ".join(context.args)
    image_bytes = context.user_data.get('last_image_bytes')

    if not image_bytes:
        await update.message.reply_text("⚠️ Maaf, saya tidak menemukan screenshot sebelumnya untuk dianalisis dengan prompt kustom ini. Silakan kirim screenshot terlebih dahulu.")
        return
    
    label = context.user_data.get('market_info_label', "Screenshot Terakhir")
    temp_message = await update.message.reply_text(f"⏳ Menganalisis '{label}' dengan prompt kustom Anda: '{custom_prompt[:70]}...' Mohon tunggu.")
    
    ai_response = await analyze_image_with_gemini(image_bytes, custom_prompt)

    try:
        await temp_message.delete()
    except Exception:
        pass
        
    await update.message.reply_text(f"**🤖 Hasil Analisis AI (Prompt Kustom Anda untuk '{label}'):**\n\n{ai_response}", parse_mode='Markdown')

# --- Main Function ---
def main():
    if gemini_vision_model is None:
        print("--------------------------------------------------------------------------------")
        print("GAGAL MENJALANKAN BOT: Model AI gagal dimuat.")
        print("           Silakan periksa pesan PERINGATAN atau Error di atas terkait")
        print("           konfigurasi API Key di dalam kode skrip ini (di bagian atas skrip).")
        print("           Pastikan Anda sudah mengganti placeholder dengan API Key yang valid.")
        print("--------------------------------------------------------------------------------")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("label", label_command))
    application.add_handler(CommandHandler("ai", ai_command_handler)) # Perintah baru /ai

    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    # CallbackQueryHandler sudah tidak diperlukan karena tidak ada inline button lagi dari handle_image

    print("🚀 Bot AI Analisis Screenshot v2.0 (Mode Otomatis) sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
