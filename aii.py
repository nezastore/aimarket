import requests
import pandas as pd
import pandas_ta as ta
import io
import mplfinance as mpf
import time
import re # Regular expressions for symbol detection

# Telegram Bot Library
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = "7927741258:AAH4ARZUoVJhZiaTqDZCr3SvI5Wrp1naF70" # API Telegram Anda
ALPHA_VANTAGE_API_KEY = "8DC4AP9DS0UVQDDM" # API ALPHA_VANTAGE Anda
GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # API Gemini Anda (Catatan: Ini terlihat seperti Google API Key)

# --- Timeframe Mapping ---
TIMEFRAME_MAP = {
    "1 Jam": {'binance_interval': '1h', 'alphavantage_ohlcv_config': {'function': 'FX_INTRADAY', 'interval': '60min', 'outputsize': 'compact'}, 'limit': 100},
    "4 Jam": {'binance_interval': '4h', 'alphavantage_ohlcv_config': None, 'limit': 200}, # Alpha Vantage tidak ada 4h intraday
    "1 Hari": {'binance_interval': '1d', 'alphavantage_ohlcv_config': {'function': 'FX_DAILY', 'outputsize': 'compact'}, 'limit': 200},
    "1 Minggu": {'binance_interval': '1w', 'alphavantage_ohlcv_config': {'function': 'FX_WEEKLY', 'outputsize': 'compact'}, 'limit': 200},
    "1 Bulan": {'binance_interval': '1M', 'alphavantage_ohlcv_config': {'function': 'FX_MONTHLY', 'outputsize': 'compact'}, 'limit': 200},
}

# --- Global Rate Limit Tracker for Alpha Vantage ---
LAST_AV_CALL_TIME = 0
AV_CALL_INTERVAL = 15 # Seconds (to respect 5 calls/minute limit)

def wait_for_alphavantage_rate_limit():
    global LAST_AV_CALL_TIME
    current_time = time.time()
    elapsed = current_time - LAST_AV_CALL_TIME
    if elapsed < AV_CALL_INTERVAL:
        wait_time = AV_CALL_INTERVAL - elapsed
        print(f"Alpha Vantage rate limit: Waiting for {wait_time:.2f} seconds...")
        time.sleep(wait_time)
    LAST_AV_CALL_TIME = time.time()

# --- Fungsi Deteksi Tipe Pasar & Normalisasi Simbol ---
def detect_market_and_normalize_symbol(user_symbol):
    user_symbol = user_symbol.upper().replace("/", "").replace(" ", "") # Bersihkan input
    
    # Prioritas deteksi:
    # 1. Kripto (umumnya diakhiri USDT/USD/BUSD)
    # Ini akan mencoba Binance dan Gemini.
    if re.match(r'^[A-Z]{2,5}(USDT|USD|BUSD)$', user_symbol):
        binance_symbol = user_symbol.replace('USD', 'USDT') # Default ke USDT untuk Binance
        gemini_symbol = user_symbol.lower() # Gemini biasanya lowercase
        return {
            'type': 'crypto',
            'display_name': user_symbol,
            'symbols': {'binance': binance_symbol, 'gemini': gemini_symbol}
        }
    
    # 2. Forex (pasangan 6 huruf, 3 huruf untuk setiap mata uang)
    if re.match(r'^[A-Z]{6}$', user_symbol):
        from_currency = user_symbol[:3]
        to_currency = user_symbol[3:]
        return {
            'type': 'forex',
            'display_name': f"{from_currency}/{to_currency}",
            'symbols': {'av_from': from_currency, 'av_to': to_currency}
        }
    
    # 3. Komoditas/Saham (misal XAUUSD untuk Gold, atau simbol saham) - lewat Alpha Vantage
    # XAUUSD, XAGUSD adalah komoditas populer di pasar Forex/Logam Mulia.
    if user_symbol in ['XAUUSD', 'XAGUSD']:
         return {
            'type': 'commodity',
            'display_name': user_symbol,
            'symbols': {'av_from': user_symbol[:3], 'av_to': user_symbol[3:]} # AV treat XAUUSD as forex
        }

    # Jika tidak terdeteksi oleh pola di atas, kita bisa coba asumsikan itu mungkin simbol saham
    # dan coba Alpha Vantage GLOBAL_QUOTE/TIME_SERIES_DAILY
    # Namun untuk bot ini, kita akan fokus pada Forex/Kripto/Komoditas yang lebih umum.
    # Jika Anda ingin mendukung saham, logika ini perlu diperluas dan membutuhkan endpoint AV yang berbeda.
    return None # Simbol tidak dikenal atau tidak didukung

# --- Fungsi Pengambilan Data OHLCV ---
async def get_ohlcv_data(market_info, timeframe_display_name):
    ohlcv_data_config = TIMEFRAME_MAP[timeframe_display_name]
    limit = ohlcv_data_config['limit']
    df = None
    error_message = None

    if market_info['type'] == 'crypto':
        symbol_binance = market_info['symbols']['binance']
        interval_binance = ohlcv_data_config['binance_interval']
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol_binance}&interval={interval_binance}&limit={limit}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            raw_data = response.json()
            if not raw_data: # Jika tidak ada data
                error_message = f"Tidak ada data OHLCV dari Binance untuk {symbol_binance} pada {interval_binance}. Simbol mungkin tidak valid."
                return None, error_message
            
            df = pd.DataFrame(raw_data, columns=[
                'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 
                'Close time', 'Quote asset volume', 'Number of trades', 
                'Taker buy base asset volume', 'Taker buy quote asset volume', 'Ignore'
            ])
            df['Open time'] = pd.to_datetime(df['Open time'], unit='ms')
            df = df.set_index('Open time')
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil OHLCV Binance ({symbol_binance}): {e}"
        except Exception as e:
            error_message = f"Error pemrosesan data OHLCV Binance ({symbol_binance}): {e}"
    
    elif market_info['type'] in ['forex', 'commodity']: # Alpha Vantage digunakan untuk Forex/Komoditas
        wait_for_alphavantage_rate_limit() # Tunggu rate limit
        av_symbol_map = market_info['symbols']
        from_currency = av_symbol_map['av_from']
        to_currency = av_symbol_map['av_to']
        av_config = ohlcv_data_config['alphavantage_ohlcv_config']

        if not av_config:
            error_message = f"Timeframe '{timeframe_display_name}' tidak didukung Alpha Vantage untuk {market_info['type']}."
            return None, error_message
        
        function = av_config['function']
        outputsize = av_config['outputsize']
        
        url_params = f"function={function}&from_symbol={from_currency}&to_symbol={to_currency}&outputsize={outputsize}&apikey={ALPHA_VANTAGE_API_KEY}"
        if 'interval' in av_config: # Untuk intraday
            url_params += f"&interval={av_config['interval']}"
            key_data = f"Time Series FX ({av_config['interval']})"
        else: # Untuk daily, weekly, monthly
            key_data = {
                'FX_DAILY': "Time Series FX (Daily)",
                'FX_WEEKLY': "Time Series FX (Weekly)",
                'FX_MONTHLY': "Time Series FX (Monthly)"
            }.get(function)
        
        url = f"https://www.alphavantage.co/query?{url_params}"

        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                error_message = f"Alpha Vantage Error ({market_info['display_name']}): {data['Error Message']}"
                if "5 calls per minute" in data["Error Message"]:
                    error_message += "\n(Batas panggilan API tercapai. Mohon tunggu sejenak sebelum mencoba lagi.)"
                return None, error_message
            if key_data not in data:
                error_message = f"Tidak ada data OHLCV dari Alpha Vantage untuk {market_info['display_name']} ({timeframe_display_name}). Simbol/timeframe mungkin tidak valid."
                return None, error_message
            
            raw_ohlcv = data[key_data]
            if not raw_ohlcv: # Jika tidak ada data
                error_message = f"Tidak ada data OHLCV dari Alpha Vantage untuk {market_info['display_name']} pada {timeframe_display_name}."
                return None, error_message

            df = pd.DataFrame.from_dict(raw_ohlcv, orient='index', dtype=float)
            df.index = pd.to_datetime(df.index)
            df = df.rename(columns={
                '1. open': 'Open', '2. high': 'High', '3. low': 'Low', '4. close': 'Close', '5. volume': 'Volume'
            })
            df = df.iloc[::-1] # Balik urutan agar terbaru di bawah
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil OHLCV Alpha Vantage ({market_info['display_name']}): {e}"
        except Exception as e:
            error_message = f"Error pemrosesan data OHLCV Alpha Vantage ({market_info['display_name']}): {e}"
    
    return df, error_message

# --- Fungsi Pengambilan Harga Terkini ---
async def get_current_price(market_info):
    price = None
    error_message = None

    if market_info['type'] == 'crypto':
        gemini_symbol = market_info['symbols']['gemini']
        # Gemini public API tidak memerlukan API Key di header untuk endpoint publik seperti /v2/ticker
        # Jika endpoint di masa depan memerlukan autentikasi, Anda perlu menambahkan header:
        # headers = {'X-GEMINI-APIKEY': GEMINI_API_KEY}
        # response = requests.get(url, headers=headers)
        url = f"https://api.gemini.com/v2/ticker/{gemini_symbol}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            price = float(data['close'])
        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil harga Gemini ({gemini_symbol}): {e}"
        except KeyError:
            error_message = f"Simbol '{gemini_symbol}' tidak ditemukan atau respons Gemini tidak terduga. (Coba simbol kripto lain seperti BTCUSD)."
        
    elif market_info['type'] in ['forex', 'commodity']:
        wait_for_alphavantage_rate_limit() # Tunggu rate limit
        av_symbol_map = market_info['symbols']
        from_currency = av_symbol_map['av_from']
        to_currency = av_symbol_map['av_to']
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={from_currency}&to_currency={to_currency}&apikey={ALPHA_VANTAGE_API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if "Realtime Currency Exchange Rate" in data:
                price = float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
            else:
                error_message = f"Alpha Vantage error saat mengambil harga {market_info['display_name']}: {data.get('Error Message', 'Unknown error')}"
            
        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil harga Alpha Vantage ({market_info['display_name']}): {e}"
        except KeyError:
            error_message = f"Pasangan mata uang '{market_info['display_name']}' tidak ditemukan atau respons Alpha Vantage tidak terduga."
            
    return price, error_message

# --- Fungsi Perhitungan Indikator (Sama seperti sebelumnya) ---
def calculate_indicators(df):
    if df is None or df.empty:
        return None, None, None, None
    df.ta.rsi(append=True)
    df.ta.macd(append=True)
    
    # Pastikan ada cukup data untuk indikator (misal MACD butuh setidaknya 26 candle)
    if len(df) < 26: 
        return None, None, None, None 

    latest_rsi = df['RSI_14'].iloc[-1]
    latest_macd = df['MACD_12_26_9'].iloc[-1]
    latest_macd_h = df['MACDH_12_26_9'].iloc[-1]
    latest_macd_s = df['MACDS_12_26_9'].iloc[-1]
    return latest_rsi, latest_macd, latest_macd_h, latest_macd_s

# --- Fungsi Saran Buy/Sell dengan Alasan Spesifik untuk Candle Terakhir ---
def get_buy_sell_suggestion_with_reasons(df, rsi, macd, macd_h, macd_s):
    suggestion = "Netral"
    reasons = []

    # Get previous MACD values for crossover detection
    prev_macd = None
    prev_macd_s = None
    if len(df) >= 2:
        prev_macd = df['MACD_12_26_9'].iloc[-2]
        prev_macd_s = df['MACDS_12_26_9'].iloc[-2]

    # Check for strong RSI signals
    if rsi < 30:
        suggestion = "Potensi Beli"
        reasons.append("RSI di bawah 30 (oversold) pada candle terakhir.")
    elif rsi > 70:
        suggestion = "Potensi Jual"
        reasons.append("RSI di atas 70 (overbought) pada candle terakhir.")
    
    # MACD Logic (Crossover strategy)
    if prev_macd is not None and prev_macd_s is not None:
        # Bullish Crossover (MACD crosses ABOVE signal line)
        # Check for actual cross (was below, now at or above) and not just floating around the line
        if prev_macd < prev_macd_s and macd >= macd_s: # and not math.isclose(prev_macd, prev_macd_s):
            if "Beli" not in suggestion: # Prioritaskan sinyal buy kuat
                suggestion = "Beli Kuat" if "Potensi Beli" in suggestion else "Beli"
            reasons.append("Garis MACD baru saja memotong Garis Sinyal ke atas (sinyal bullish).")
        # Bearish Crossover (MACD crosses BELOW signal line)
        elif prev_macd > prev_macd_s and macd <= macd_s: # and not math.isclose(prev_macd, prev_macd_s):
            if "Jual" not in suggestion: # Prioritaskan sinyal sell kuat
                suggestion = "Jual Kuat" if "Potensi Jual" in suggestion else "Jual"
            reasons.append("Garis MACD baru saja memotong Garis Sinyal ke bawah (sinyal bearish).")
    
    # MACD Histogram momentum
    # Check if histogram is turning positive or negative, or increasing/decreasing
    if len(df) >= 2:
        prev_macd_h = df['MACDH_12_26_9'].iloc[-2]
        if macd_h > 0 and macd_h > prev_macd_h: # Histogram positif dan meningkat
            if "Beli" not in suggestion and "Netral" in suggestion:
                suggestion = "Potensi Beli"
                reasons.append("Histogram MACD positif dan menunjukkan momentum kenaikan.")
        elif macd_h < 0 and macd_h < prev_macd_h: # Histogram negatif dan menurun
            if "Jual" not in suggestion and "Netral" in suggestion:
                suggestion = "Potensi Jual"
                reasons.append("Histogram MACD negatif dan menunjukkan momentum penurunan.")

    # Jika belum ada alasan kuat, berikan alasan netral
    if not reasons:
        reasons.append("Pasar saat ini netral berdasarkan indikator RSI dan MACD pada candle terakhir.")

    return suggestion, reasons

# --- Fungsi Plotting Grafik dengan Sinyal ---
def plot_candlestick_with_signals(df, symbol_display_name, timeframe_display, suggestion, reasons):
    mc = mpf.make_marketcolors(up='green', down='red', wick='inherit', edge='inherit', volume='in', ohlc='i')
    s = mpf.make_mpf_style(base_mpf_style='yahoo', marketcolors=mc, gridcolor='gray', facecolor='#1a1a1a', figcolor='black', edgecolor='inherit')

    apds = [
        mpf.make_addplot(df['MACD_12_26_9'], panel=2, color='white', title='MACD'),
        mpf.make_addplot(df['MACDS_12_26_9'], panel=2, color='orange'),
        mpf.make_addplot(df['MACDH_12_26_9'], type='bar', panel=2, color='lightblue', alpha=0.7),
        mpf.make_addplot(df['RSI_14'], panel=3, color='purple', title='RSI', ylim=(0,100)),
        mpf.make_addplot(pd.Series([30]*len(df), index=df.index), panel=3, color='gray', linestyle='--', alpha=0.5), # Oversold line
        mpf.make_addplot(pd.Series([70]*len(df), index=df.index), panel=3, color='gray', linestyle='--', alpha=0.5), # Overbought line
    ]

    # Menandai sinyal buy/sell pada candle terakhir
    last_idx = df.index[-1]
    last_open = df['Open'].iloc[-1]
    last_close = df['Close'].iloc[-1]
    last_high = df['High'].iloc[-1]
    last_low = df['Low'].iloc[-1]

    # Posisi marker relatif terhadap candle
    marker_offset_factor = 0.05 # 5% dari tinggi candle
    marker_offset = (last_high - last_low) * marker_offset_factor 

    marker_size = 300 # Ukuran marker

    # Adjust marker position based on candle direction
    # Place buy marker slightly below the low, sell marker slightly above the high
    buy_marker_pos = last_low - marker_offset
    sell_marker_pos = last_high + marker_offset

    if "Beli" in suggestion:
        apds.append(mpf.make_addplot(pd.Series([buy_marker_pos], index=[last_idx]), type='scatter', marker='^', markersize=marker_size, color='green', panel=0))
    elif "Jual" in suggestion:
        apds.append(mpf.make_addplot(pd.Series([sell_marker_pos], index=[last_idx]), type='scatter', marker='v', markersize=marker_size, color='red', panel=0))

    fig, axes = mpf.plot(df,
                         type='candle',
                         style=s,
                         title=f"{symbol_display_name} ({timeframe_display}) Candlestick Chart",
                         ylabel='Price',
                         volume=True,
                         ylabel_lower='Volume',
                         addplot=apds,
                         returnfig=True,
                         figscale=1.5, # Skala gambar
                         panel_ratios=(4,1,1,1), # Ratio for price, volume, MACD, RSI panels
                         figsize=(12, 8) # Ukuran gambar lebih besar
                        )

    # Tambahkan teks saran di grafik
    axes[0].text(0.01, 0.99, f"Saran: {suggestion}", transform=axes[0].transAxes, fontsize=12, va='top', ha='left', color='white')
    # Use '\n' to break long reasons into multiple lines if needed.
    reasons_text = "Alasan: " + "\n".join(reasons)
    axes[0].text(0.01, 0.95, reasons_text, transform=axes[0].transAxes, fontsize=10, va='top', ha='left', color='white', wrap=True)


    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150) # Tingkatkan DPI untuk kejernihan
    buf.seek(0)
    
    return buf

# --- Handler Bot Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Saya bot analisis pasar finansial. "
        "Ketik /analyze [SIMBOL] (contoh: /analyze XAUUSD atau /analyze AUDUSD) untuk analisis."
    )

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Mohon sertakan simbol market (contoh: /analyze XAUUSD atau /analyze BTCUSD).")
        return

    user_symbol = context.args[0]
    market_info = detect_market_and_normalize_symbol(user_symbol)

    if not market_info:
        await update.message.reply_text(
            f"Simbol '{user_symbol}' tidak dikenali atau tidak didukung oleh sumber data gratis kami. "
            f"Coba simbol umum seperti EURUSD, XAUUSD, BTCUSD, atau ETHUSD."
        )
        return
    
    # Simpan market_info dan original_user_symbol untuk digunakan nanti
    context.user_data['market_info'] = market_info
    context.user_data['original_user_symbol'] = user_symbol
    
    # Buat tombol timeframe berdasarkan ketersediaan API untuk tipe market
    keyboard = []
    for tf_display_name, tf_data in TIMEFRAME_MAP.items():
        # Alpha Vantage (untuk Forex/Commodity) tidak punya 4h intraday
        if market_info['type'] in ['forex', 'commodity'] and tf_data['alphavantage_ohlcv_config'] is None:
            continue
        keyboard.append(InlineKeyboardButton(tf_display_name, callback_data=f"analyze_tf_{tf_display_name}"))
    
    # Susun tombol, misal 2 per baris
    arranged_keyboard = [keyboard[i:i + 2] for i in range(0, len(keyboard), 2)]
    reply_markup = InlineKeyboardMarkup(arranged_keyboard)

    await update.message.reply_text(
        f"Memilih {market_info['display_name']}. Pilih timeframe:",
        reply_markup=reply_markup
    )

async def process_analysis_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    timeframe_display_name = query.data.split('_')[-1]
    market_info = context.user_data.get('market_info') # Ambil info market yang sudah disimpan
    
    if not market_info:
        await query.edit_message_text("Terjadi kesalahan. Silakan mulai ulang dengan /analyze [SIMBOL].")
        return

    await query.edit_message_text(f"Menganalisis {market_info['display_name']} pada timeframe {timeframe_display_name}...")

    # --- Proses Analisis ---
    current_price, price_error = await get_current_price(market_info)
    if current_price is None:
        await query.edit_message_text(f"Maaf, tidak dapat mengambil harga terkini untuk {market_info['display_name']}. {price_error or ''}")
        return

    ohlcv_df, ohlcv_error = await get_ohlcv_data(market_info, timeframe_display_name)
    if ohlcv_df is None or ohlcv_df.empty:
        await query.edit_message_text(f"Maaf, tidak dapat mengambil data historis untuk {market_info['display_name']} ({timeframe_display_name}). {ohlcv_error or ''}")
        return
    
    # Pastikan data cukup untuk menghitung indikator (misal MACD butuh setidaknya 26 candle)
    if len(ohlcv_df) < 26: 
        await query.edit_message_text(f"Maaf, data historis yang tersedia ({len(ohlcv_df)} candle) tidak cukup untuk menghitung indikator (butuh minimal 26 candle).")
        return

    rsi, macd, macd_h, macd_s = calculate_indicators(ohlcv_df)
    if rsi is None: # Ini bisa terjadi jika data tidak cukup setelah pemotongan NaN oleh pandas_ta
        await query.edit_message_text(f"Maaf, indikator tidak dapat dihitung dengan data yang tersedia untuk {market_info['display_name']}. Pastikan ada cukup data historis.")
        return
    
    # Dapatkan saran dan alasan untuk candle terakhir
    suggestion, reasons = get_buy_sell_suggestion_with_reasons(ohlcv_df, rsi, macd, macd_h, macd_s)

    # --- Buat Grafik dan Kirim ---
    try:
        plot_buffer = plot_candlestick_with_signals(ohlcv_df, market_info['display_name'], timeframe_display_name, suggestion, reasons)
        
        # Penentuan jumlah desimal untuk harga
        # Untuk Forex/Komoditas, gunakan lebih banyak desimal (4-6), untuk Kripto (2)
        if market_info['type'] in ['forex', 'commodity']:
            # Coba deteksi presisi berdasarkan harga. Emas bisa 2 desimal, Forex 4-5.
            if current_price < 100: # Misal EURUSD
                price_format = ",.5f"
            else: # Misal XAUUSD
                price_format = ",.2f"
        else: # Crypto
            price_format = ",.2f"
        
        caption = (
            f"**Analisis Pasar: {market_info['display_name']} ({timeframe_display_name})**\n"
            f"💰 Harga Terkini: `${current_price:{price_format}}`\n"
            f"📊 RSI: `{rsi:.2f}`\n"
            f"📈 MACD: `{macd:.4f}` (Sinyal: `{macd_s:.4f}`, Hist: `{macd_h:.4f}`)\n"
            f"\n"
            f"**Kesimpulan: {suggestion.upper()}**\n"
            f"Alasan: {', '.join(reasons) if reasons else 'Tidak ada sinyal kuat.'}\n"
            f"*(Analisis ini murni berdasarkan indikator teknikal RSI & MACD pada candle terakhir, bukan saran finansial.)*"
        )
        
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=plot_buffer,
            caption=caption,
            parse_mode='Markdown'
        )
        await query.delete_message()

        # --- Tambahkan Tombol Fitur Tambahan ---
        # Buat URL TradingView dinamis
        tradingview_symbol = ""
        if market_info['type'] == 'crypto':
            tradingview_symbol = f"BINANCE:{market_info['symbols']['binance']}"
        elif market_info['type'] == 'forex':
            tradingview_symbol = f"FX_IDC:{market_info['symbols']['av_from']}{market_info['symbols']['av_to']}"
        elif market_info['type'] == 'commodity':
            # Untuk komoditas seperti XAUUSD, TradingView pakai format FX_IDC
            tradingview_symbol = f"FX_IDC:{market_info['symbols']['av_from']}{market_info['symbols']['av_to']}"


        feature_keyboard = [
            [InlineKeyboardButton("Lihat Grafik (TradingView)", url=f"https://www.tradingview.com/chart/?symbol={tradingview_symbol}"),
             InlineKeyboardButton("Pasang Alert (Segera Hadir)", callback_data="feature_alert")],
            [InlineKeyboardButton("Apa itu RSI?", callback_data="explain_rsi"),
             InlineKeyboardButton("Apa itu MACD?", callback_data="explain_macd")],
            [InlineKeyboardButton("Analisis Ulang Simbol Ini", callback_data=f"reanalyze_market__{context.user_data['original_user_symbol']}")] 
        ]
        feature_reply_markup = InlineKeyboardMarkup(feature_keyboard)

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Pilihan lebih lanjut:",
            reply_markup=feature_reply_markup
        )

    except Exception as e:
        print(f"Error saat membuat atau mengirim grafik: {e}")
        await query.edit_message_text(f"Terjadi kesalahan saat membuat atau mengirim grafik: {e}")

async def explain_rsi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "**RSI (Relative Strength Index)** adalah osilator momentum yang mengukur kecepatan dan perubahan pergerakan harga. "
        "RSI berosilasi antara 0 dan 100. Umumnya, RSI di atas 70 menunjukkan kondisi *overbought* (potensi pembalikan turun), "
        "sementara di bawah 30 menunjukkan kondisi *oversold* (potensi pembalikan naik)."
    )
    await query.message.reply_text(text, parse_mode='Markdown')

async def explain_macd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "**MACD (Moving Average Convergence Divergence)** adalah indikator momentum *trend-following* yang menunjukkan hubungan "
        "antara dua rata-rata bergerak harga. Sinyal utama adalah *crossover* garis MACD di atas atau di bawah garis sinyal, "
        "serta divergence antara MACD dan harga."
    )
    await query.message.reply_text(text, parse_mode='Markdown')

async def reanalyze_market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    original_symbol = query.data.split('__')[-1] # Ambil simbol asli dari callback data

    # Simulasikan kembali command /analyze dengan simbol yang sama
    # Ini akan memicu alur pemilihan timeframe lagi
    temp_update = Update(update_id=query.update_id) # Buat update dummy
    temp_update.message = query.message # Gunakan message dari query
    temp_update.message.text = f"/analyze {original_symbol}" # Set teks pesan
    context.args = [original_symbol] # Set args untuk analyze_command

    await analyze_command(temp_update, context)

# --- Main Function untuk Menjalankan Bot ---
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("analyze", analyze_command)) 
    
    # Callback Handlers
    application.add_handler(CallbackQueryHandler(process_analysis_callback_query, pattern='^analyze_tf_'))
    application.add_handler(CallbackQueryHandler(explain_rsi_callback, pattern='^explain_rsi$'))
    application.add_handler(CallbackQueryHandler(explain_macd_callback, pattern='^explain_macd$'))
    application.add_handler(CallbackQueryHandler(reanalyze_market_callback, pattern='^reanalyze_market__'))

    print("Bot sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()