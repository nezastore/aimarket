import requests
import pandas as pd
import pandas_ta as ta
import io
import mplfinance as mpf
import time
import re # Regular expressions for symbol detection
import math # For math.isclose()

# Telegram Bot Library
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- Konfigurasi ---
TELEGRAM_BOT_TOKEN = "7927741258:AAH4ARZUoVJhZiaTqDZCr3SvI5Wrp1naF70" # API Telegram Anda
ALPHA_VANTAGE_API_KEY = "8DC4AP9DS0UVQDDM" # API ALPHA_VANTAGE Anda
GEMINI_API_KEY = "AIzaSyCpYrPfiG0hiccKOkGowU8rfFDYWxarnac" # API Gemini Anda (Catatan: Ini terlihat seperti Google API Key)

# --- Timeframe Mapping ---
TIMEFRAME_MAP = {
    "1 Jam": {'alphavantage_ohlcv_config': {'function': 'FX_INTRADAY', 'interval': '60min', 'outputsize': 'compact'}, 'limit': 100},
    # "4 Jam": {'alphavantage_ohlcv_config': None, 'limit': 200}, # Alpha Vantage tidak ada 4h intraday untuk Kripto/Forex intraday
    "1 Hari": {'alphavantage_ohlcv_config': {'function': 'FX_DAILY', 'outputsize': 'compact'}, 'limit': 200},
    "1 Minggu": {'alphavantage_ohlcv_config': {'function': 'FX_WEEKLY', 'outputsize': 'compact'}, 'limit': 200},
    "1 Bulan": {'alphavantage_ohlcv_config': {'function': 'FX_MONTHLY', 'outputsize': 'compact'}, 'limit': 200},
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
    
    # 1. Kripto (umumnya diakhiri USD/USDT/BUSD)
    if re.match(r'^[A-Z]{2,5}(USDT|USD|BUSD)$', user_symbol):
        base_currency = user_symbol[:-3] if user_symbol.endswith(('USD', 'BUSD')) else user_symbol[:-4]
        quote_currency = user_symbol[-3:] if user_symbol.endswith(('USD', 'BUSD')) else user_symbol[-4:]
        
        return {
            'type': 'crypto',
            'display_name': user_symbol,
            'symbols': {
                'av_from': base_currency, 
                'av_to': quote_currency.replace('USDT', 'USD'), # AV sering pakai USD bukan USDT untuk OHLCV
                'gemini_symbol': user_symbol.lower() # Simbol untuk Gemini (lowercase)
            },
            'price_source': 'gemini' # <-- PENTING: Kembali menggunakan Gemini untuk harga spot kripto
        }
    
    # 2. Forex (pasangan 6 huruf, 3 huruf untuk setiap mata uang)
    if re.match(r'^[A-Z]{6}$', user_symbol):
        from_currency = user_symbol[:3]
        to_currency = user_symbol[3:]
        return {
            'type': 'forex',
            'display_name': f"{from_currency}/{to_currency}",
            'symbols': {'av_from': from_currency, 'av_to': to_currency},
            'price_source': 'alphavantage_spot'
        }
    
    # 3. Komoditas (XAUUSD, XAGUSD) - Alpha Vantage treats as Forex
    if user_symbol in ['XAUUSD', 'XAGUSD']:
        return {
            'type': 'commodity',
            'display_name': user_symbol,
            'symbols': {'av_from': user_symbol[:3], 'av_to': user_symbol[3:]},
            'price_source': 'alphavantage_spot'
        }
    
    return None 

# --- Fungsi Pengambilan Data OHLCV (Alpha Vantage saja, sama seperti sebelumnya) ---
async def get_ohlcv_data(market_info, timeframe_display_name):
    ohlcv_data_config = TIMEFRAME_MAP[timeframe_display_name]
    limit = ohlcv_data_config['limit']
    df = None
    error_message = None

    wait_for_alphavantage_rate_limit()

    av_symbol_map = market_info['symbols']
    from_currency = av_symbol_map['av_from']
    to_currency = av_symbol_map['av_to']
    av_config = ohlcv_data_config['alphavantage_ohlcv_config']

    if not av_config:
        error_message = f"Timeframe '{timeframe_display_name}' tidak didukung Alpha Vantage untuk {market_info['type']}."
        return None, error_message
    
    function = av_config['function']
    outputsize = av_config['outputsize']
    
    if market_info['type'] == 'crypto':
        if function == 'FX_INTRADAY': function = 'CRYPTO_INTRADAY'
        elif function == 'FX_DAILY': function = 'DIGITAL_CURRENCY_DAILY'
        elif function == 'FX_WEEKLY': function = 'DIGITAL_CURRENCY_WEEKLY'
        elif function == 'FX_MONTHLY': function = 'DIGITAL_CURRENCY_MONTHLY'

    url_params = f"function={function}&symbol={from_currency}&market={to_currency}&outputsize={outputsize}&apikey={ALPHA_VANTAGE_API_KEY}"
    if 'interval' in av_config:
        url_params += f"&interval={av_config['interval']}"
        key_data = f"Time Series FX ({av_config['interval']})" if market_info['type'] != 'crypto' else f"Time Series Crypto ({av_config['interval']})"
    else:
        if market_info['type'] == 'crypto':
            key_data = "Time Series (Digital Currency Daily)" if function == 'DIGITAL_CURRENCY_DAILY' else \
                       "Time Series (Digital Currency Weekly)" if function == 'DIGITAL_CURRENCY_WEEKLY' else \
                       "Time Series (Digital Currency Monthly)"
            # Parameter untuk crypto daily/weekly/monthly berbeda, tidak menggunakan 'market' tapi 'symbol' dan 'market' (USD)
            # url_params = f"function={function}&symbol={from_currency}&market={to_currency}&outputsize={outputsize}&apikey={ALPHA_VANTage_API_KEY}" # Ini sudah benar di atas
        else:
            key_data = {
                'FX_DAILY': "Time Series FX (Daily)",
                'FX_WEEKLY': "Time Series FX (Weekly)",
                'FX_MONTHLY': "Time Series FX (Monthly)"
            }.get(function)
            url_params = f"function={function}&from_symbol={from_currency}&to_symbol={to_currency}&outputsize={outputsize}&apikey={ALPHA_VANTAGE_API_KEY}"
    
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
            error_message = f"Tidak ada data OHLCV dari Alpha Vantage untuk {market_info['display_name']} ({timeframe_display_name}). Simbol/timeframe mungkin tidak valid atau tidak ada data. Respons: {data}"
            return None, error_message
        
        raw_ohlcv = data[key_data]
        if not raw_ohlcv:
            error_message = f"Tidak ada data OHLCV dari Alpha Vantage untuk {market_info['display_name']} pada {timeframe_display_name}."
            return None, error_message

        df = pd.DataFrame.from_dict(raw_ohlcv, orient='index', dtype=float)
        df.index = pd.to_datetime(df.index)
        
        if market_info['type'] == 'crypto':
            # Crypto data from Alpha Vantage uses different keys, sometimes with 'a.' and 'b.' prefixes
            rename_map = {}
            # Check common crypto naming conventions from AV
            # Example key: '1a. open (USD)' or '1. open'
            # We need to find the actual keys present in the first row of data
            sample_keys = list(raw_ohlcv[list(raw_ohlcv.keys())[0]].keys())

            open_key = next((k for k in sample_keys if 'open' in k.lower()), None)
            high_key = next((k for k in sample_keys if 'high' in k.lower()), None)
            low_key = next((k for k in sample_keys if 'low' in k.lower()), None)
            close_key = next((k for k in sample_keys if 'close' in k.lower()), None)
            volume_key = next((k for k in sample_keys if 'volume' in k.lower() and 'market cap' not in k.lower()), None) # exclude volume_marketcap if simple volume exists

            if open_key: rename_map[open_key] = 'Open'
            if high_key: rename_map[high_key] = 'High'
            if low_key: rename_map[low_key] = 'Low'
            if close_key: rename_map[close_key] = 'Close'
            if volume_key: rename_map[volume_key] = 'Volume'
            
            df = df.rename(columns=rename_map)

            # Ensure essential columns exist
            for col in ['Open', 'High', 'Low', 'Close']:
                if col not in df.columns:
                    error_message = f"Kolom esensial '{col}' tidak ditemukan dalam data OHLCV kripto."
                    return None, error_message
            if 'Volume' not in df.columns:
                df['Volume'] = 0 # Default to 0 if no volume key was found
            
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        else: 
            df = df.rename(columns={
                '1. open': 'Open', '2. high': 'High', '3. low': 'Low', '4. close': 'Close', '5. volume': 'Volume'
            })
            if 'Volume' not in df.columns: # Handle cases where volume might be missing for Forex
                 df['Volume'] = 0
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
        df = df.iloc[::-1] # Sort from oldest to newest

    except requests.exceptions.RequestException as e:
        error_message = f"Error jaringan saat mengambil OHLCV Alpha Vantage ({market_info['display_name']}): {e}"
    except Exception as e:
        error_message = f"Error pemrosesan data OHLCV Alpha Vantage ({market_info['display_name']}): {e}. Data: {data if 'data' in locals() else 'Tidak ada data'}"
    
    return df, error_message

# --- Fungsi Pengambilan Harga Terkini (Mengembalikan Gemini untuk Kripto) ---
async def get_current_price(market_info):
    price = None
    error_message = None

    if market_info['price_source'] == 'gemini': # Jika sumber harga adalah Gemini
        gemini_symbol = market_info['symbols']['gemini'] 
        url = f"https://api.gemini.com/v2/ticker/{gemini_symbol}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            price = float(data['close'])
        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil harga Gemini ({gemini_symbol}): {e}. Pastikan simbol kripto valid di Gemini."
        except KeyError:
            error_message = f"Simbol '{gemini_symbol}' tidak ditemukan atau respons Gemini tidak terduga. (Coba simbol kripto lain seperti BTCUSD)."
        
    elif market_info['price_source'] == 'alphavantage_spot': # Jika sumber harga adalah Alpha Vantage
        wait_for_alphavantage_rate_limit()
        av_symbol_map = market_info['symbols']
        from_currency = av_symbol_map['av_from']
        to_currency = av_symbol_map['av_to']

        if market_info['type'] in ['forex', 'commodity']:
            url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={from_currency}&to_currency={to_currency}&apikey={ALPHA_VANTAGE_API_KEY}"
        # elif market_info['type'] == 'crypto': # Crypto spot price now from Gemini
        #     url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={from_currency}{to_currency}&apikey={ALPHA_VANTAGE_API_KEY}"
            
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if market_info['type'] in ['forex', 'commodity'] and "Realtime Currency Exchange Rate" in data:
                price = float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
            # elif market_info['type'] == 'crypto' and "Global Quote" in data and data['Global Quote']:
            #     price = float(data['Global Quote']['05. price'])
            else:
                error_message = f"Alpha Vantage error saat mengambil harga {market_info['display_name']}: {data.get('Error Message', 'Tidak ada data atau respons tidak terduga.')}"
            
        except requests.exceptions.RequestException as e:
            error_message = f"Error jaringan saat mengambil harga Alpha Vantage ({market_info['display_name']}): {e}"
        except KeyError:
            error_message = f"Pasangan '{market_info['display_name']}' tidak ditemukan atau respons Alpha Vantage tidak terduga."
            
    return price, error_message

# --- Fungsi Perhitungan Indikator (Sama seperti sebelumnya) ---
def calculate_indicators(df):
    if df is None or df.empty:
        return None, None, None, None, None # Added None for df return
    df.ta.rsi(append=True)
    df.ta.macd(append=True)
    
    # Check if columns were created and have enough non-NA values
    if 'RSI_14' not in df.columns or 'MACD_12_26_9' not in df.columns or \
       'MACDH_12_26_9' not in df.columns or 'MACDS_12_26_9' not in df.columns:
        print("Kolom indikator tidak berhasil dibuat.")
        return None, None, None, None, df # Return df as is

    if len(df) < 26 or df['RSI_14'].iloc[25:].isnull().all() or df['MACD_12_26_9'].iloc[25:].isnull().all(): 
        print(f"Data tidak cukup untuk kalkulasi indikator setelah dropna atau dari awal. Panjang df: {len(df)}")
        return None, None, None, None, df 

    latest_rsi = df['RSI_14'].iloc[-1]
    latest_macd = df['MACD_12_26_9'].iloc[-1]
    latest_macd_h = df['MACDH_12_26_9'].iloc[-1]
    latest_macd_s = df['MACDS_12_26_9'].iloc[-1]
    return latest_rsi, latest_macd, latest_macd_h, latest_macd_s, df # Return df

# --- Fungsi Saran Buy/Sell dengan Alasan Spesifik untuk Candle Terakhir (Sama seperti sebelumnya) ---
def get_buy_sell_suggestion_with_reasons(df, rsi, macd, macd_h, macd_s):
    suggestion = "Netral"
    reasons = []

    # Ensure indicators are not None
    if rsi is None or macd is None or macd_h is None or macd_s is None:
        reasons.append("Indikator tidak dapat dihitung dengan benar.")
        return suggestion, reasons
    
    # Check for sufficient data for previous MACD values
    prev_macd = None
    prev_macd_s = None
    if len(df) >= 2: # Need at least two rows to get iloc[-2]
        # Also check if the required MACD columns exist and are not all NaN
        if 'MACD_12_26_9' in df.columns and 'MACDS_12_26_9' in df.columns:
            if not pd.isna(df['MACD_12_26_9'].iloc[-2]) and not pd.isna(df['MACDS_12_26_9'].iloc[-2]):
                prev_macd = df['MACD_12_26_9'].iloc[-2]
                prev_macd_s = df['MACDS_12_26_9'].iloc[-2]

    if rsi < 30:
        suggestion = "Potensi Beli"
        reasons.append("RSI di bawah 30 (oversold) pada candle terakhir.")
    elif rsi > 70:
        suggestion = "Potensi Jual"
        reasons.append("RSI di atas 70 (overbought) pada candle terakhir.")
    
    if prev_macd is not None and prev_macd_s is not None: # Check if previous values were successfully retrieved
        # Golden Cross
        if prev_macd < prev_macd_s and macd >= macd_s: 
            if "Beli" not in suggestion: 
                suggestion = "Beli Kuat" if "Potensi Beli" in suggestion else "Beli"
            else: # If already "Potensi Beli", upgrade to "Beli Kuat"
                suggestion = "Beli Kuat"
            reasons.append("Garis MACD baru saja memotong Garis Sinyal ke atas (sinyal bullish).")
        # Death Cross
        elif prev_macd > prev_macd_s and macd <= macd_s: 
            if "Jual" not in suggestion: 
                suggestion = "Jual Kuat" if "Potensi Jual" in suggestion else "Jual"
            else: # If already "Potensi Jual", upgrade to "Jual Kuat"
                suggestion = "Jual Kuat"
            reasons.append("Garis MACD baru saja memotong Garis Sinyal ke bawah (sinyal bearish).")
    
    # Histogram MACD logic
    if len(df) >= 2 and 'MACDH_12_26_9' in df.columns:
        prev_macd_h = df['MACDH_12_26_9'].iloc[-2]
        if not pd.isna(prev_macd_h) and not pd.isna(macd_h): # Ensure current and previous histogram values are not NaN
            # Increasing bullish momentum
            if macd_h > 0 and macd_h > prev_macd_h:
                if "Beli" not in suggestion and "Netral" in suggestion: # Add only if neutral or no strong signal yet
                    suggestion = "Potensi Beli"
                reasons.append("Histogram MACD positif dan menunjukkan momentum kenaikan.")
            # Increasing bearish momentum
            elif macd_h < 0 and macd_h < prev_macd_h:
                if "Jual" not in suggestion and "Netral" in suggestion: # Add only if neutral or no strong signal yet
                    suggestion = "Potensi Jual"
                reasons.append("Histogram MACD negatif dan menunjukkan momentum penurunan.")

    if not reasons:
        reasons.append("Pasar saat ini netral berdasarkan indikator RSI dan MACD pada candle terakhir.")

    return suggestion, reasons

# --- Fungsi Plotting Grafik dengan Sinyal (Sama seperti sebelumnya) ---
def plot_candlestick_with_signals(df, symbol_display_name, timeframe_display, suggestion, reasons):
    mc = mpf.make_marketcolors(up='green', down='red', wick='inherit', edge='inherit', volume='in', ohlc='i')
    s = mpf.make_mpf_style(base_mpf_style='yahoo', marketcolors=mc, gridcolor='gray', facecolor='#1a1a1a', figcolor='black', edgecolor='inherit')

    # Ensure indicator columns exist before trying to plot them
    apds = []
    if 'MACD_12_26_9' in df.columns:
        apds.append(mpf.make_addplot(df['MACD_12_26_9'], panel=2, color='white', title='MACD'))
    if 'MACDS_12_26_9' in df.columns:
        apds.append(mpf.make_addplot(df['MACDS_12_26_9'], panel=2, color='orange'))
    if 'MACDH_12_26_9' in df.columns:
        apds.append(mpf.make_addplot(df['MACDH_12_26_9'], type='bar', panel=2, color='lightblue', alpha=0.7))
    if 'RSI_14' in df.columns:
        apds.append(mpf.make_addplot(df['RSI_14'], panel=3, color='purple', title='RSI', ylim=(0,100)))
        apds.append(mpf.make_addplot(pd.Series([30]*len(df), index=df.index), panel=3, color='gray', linestyle='--', alpha=0.5)) # Oversold line
        apds.append(mpf.make_addplot(pd.Series([70]*len(df), index=df.index), panel=3, color='gray', linestyle='--', alpha=0.5)) # Overbought line
    else: # If RSI is not available, don't plot RSI panel elements
        pass


    last_idx = df.index[-1]
    last_low = df['Low'].iloc[-1]
    last_high = df['High'].iloc[-1]

    marker_offset_factor = 0.05 
    marker_offset = (last_high - last_low) * marker_offset_factor if (last_high - last_low) > 0 else last_low * 0.01 # Avoid zero offset

    marker_size = 300 

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
                         figscale=1.5,
                         panel_ratios=(4,1,1,1) if ('RSI_14' in df.columns and 'MACD_12_26_9' in df.columns) else (6,1,2) if 'MACD_12_26_9' in df.columns else (8,2), # Adjust ratios if RSI is missing
                         figsize=(12, 8)
                        )

    # Add suggestion and reasons to the chart
    # Ensure axes[0] exists (it should for the main price panel)
    if axes and len(axes) > 0:
        axes[0].text(0.01, 0.99, f"Saran: {suggestion}", transform=axes[0].transAxes, fontsize=12, va='top', ha='left', color='white', bbox=dict(facecolor='black', alpha=0.5))
        reasons_text = "Alasan:\n" + "\n".join([f"- {r}" for r in reasons])
        axes[0].text(0.01, 0.90, reasons_text, transform=axes[0].transAxes, fontsize=9, va='top', ha='left', color='white', wrap=True, bbox=dict(facecolor='black', alpha=0.5))


    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    buf.seek(0)
    
    return buf

# --- Handler Bot Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Halo! Saya bot analisis pasar finansial. "
        "Ketik /analyze [SIMBOL] (contoh: /analyze XAUUSD atau /analyze BTCUSD) untuk analisis."
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
    
    context.user_data['market_info'] = market_info
    context.user_data['original_user_symbol'] = user_symbol # Store original symbol for re-analysis
    
    keyboard = []
    for tf_display_name, tf_data in TIMEFRAME_MAP.items():
        if tf_data['alphavantage_ohlcv_config'] is None: 
            continue 
        keyboard.append(InlineKeyboardButton(tf_display_name, callback_data=f"analyze_tf_{tf_display_name}"))
    
    # --- PERUBAHAN DI SINI (Menu Timeframe) ---
    # Mengatur setiap tombol agar berada di barisnya sendiri
    arranged_keyboard = [[button] for button in keyboard] 
    # --- AKHIR PERUBAHAN ---

    reply_markup = InlineKeyboardMarkup(arranged_keyboard)

    await update.message.reply_text(
        f"Memilih {market_info['display_name']}. Pilih timeframe:",
        reply_markup=reply_markup
    )

async def process_analysis_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Extract timeframe from callback_data like "analyze_tf_1 Hari"
    try:
        timeframe_display_name = query.data.split('analyze_tf_')[-1]
    except IndexError:
        await query.edit_message_text("Error: Callback data timeframe tidak valid.")
        return
        
    market_info = context.user_data.get('market_info') 
    
    if not market_info:
        await query.edit_message_text("Terjadi kesalahan. Silakan mulai ulang dengan /analyze [SIMBOL].")
        return

    # Inform user that analysis is starting, replacing the button menu
    await query.edit_message_text(f"Menganalisis {market_info['display_name']} pada timeframe {timeframe_display_name}...")

    current_price, price_error = await get_current_price(market_info)
    if current_price is None:
        await query.edit_message_text(f"Maaf, tidak dapat mengambil harga terkini untuk {market_info['display_name']}. {price_error or 'Silakan coba lagi.'}")
        return

    ohlcv_df, ohlcv_error = await get_ohlcv_data(market_info, timeframe_display_name)
    if ohlcv_df is None or ohlcv_df.empty:
        await query.edit_message_text(f"Maaf, tidak dapat mengambil data historis untuk {market_info['display_name']} ({timeframe_display_name}). {ohlcv_error or 'Silakan coba lagi.'}")
        return
    
    # Minimal data check before calculating indicators
    if len(ohlcv_df) < 26: # MACD typically needs 26 periods
        await query.edit_message_text(f"Maaf, data historis yang tersedia ({len(ohlcv_df)} candle) tidak cukup untuk menghitung indikator (butuh minimal 26 candle).")
        return

    rsi, macd, macd_h, macd_s, ohlcv_df_updated = calculate_indicators(ohlcv_df.copy()) # Pass a copy to avoid modifying original df in context
    
    if rsi is None or macd is None: # Check if indicators were successfully calculated
        await query.edit_message_text(f"Maaf, indikator tidak dapat dihitung dengan data yang tersedia untuk {market_info['display_name']}. Pastikan ada cukup data historis yang valid.")
        return
    
    suggestion, reasons = get_buy_sell_suggestion_with_reasons(ohlcv_df_updated, rsi, macd, macd_h, macd_s)

    try:
        plot_buffer = plot_candlestick_with_signals(ohlcv_df_updated, market_info['display_name'], timeframe_display_name, suggestion, reasons)
        
        # Determine price formatting based on market type and value
        if market_info['type'] in ['forex', 'commodity']:
            if current_price < 10: # For pairs like XAU/USD or EUR/USD which might have many decimals if price is low, e.g. under $10
                price_format = ",.5f" 
            else: 
                price_format = ",.2f"
        else: # Crypto
            if current_price < 0.01:
                price_format = ",.8f" # For very low-priced cryptos
            elif current_price < 1:
                price_format = ",.5f"
            else:
                price_format = ",.2f"
        
        caption = (
            f"**Analisis Pasar: {market_info['display_name']} ({timeframe_display_name})**\n"
            f"💰 Harga Terkini: `${current_price:{price_format}}`\n"
            f"📊 RSI (14): `{rsi:.2f}`\n"
            f"📈 MACD (12,26,9): `{macd:.4f}` (Sinyal: `{macd_s:.4f}`, Hist: `{macd_h:.4f}`)\n"
            f"\n"
            f"**Kesimpulan: {suggestion.upper()}**\n"
            f"Alasan: {', '.join(reasons) if reasons else 'Tidak ada sinyal kuat.'}\n"
            f"*(Analisis ini murni berdasarkan indikator teknikal RSI & MACD pada candle terakhir, bukan saran finansial.)*"
        )
        
        # Delete the "Menganalisis..." message BEFORE sending the photo with new buttons
        # This avoids the old message briefly reappearing if send_photo is slow
        try:
            await query.delete_message()
        except Exception as e:
            print(f"Gagal menghapus pesan sementara: {e}")


        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=plot_buffer,
            caption=caption,
            parse_mode='Markdown'
        )
        # Message for new buttons will be sent after the photo

        # Prepare TradingView symbol
        tradingview_symbol = ""
        av_s = market_info['symbols']
        if market_info['type'] == 'crypto':
            # Gemini symbols are like 'btcusd', AV uses FROM:BTC, TO:USD. TradingView often uses BTCUSD or BTCUSDT.
            # Assuming gemini_symbol is more aligned with TradingView for crypto.
            tv_base = av_s.get('av_from', '') 
            tv_quote = av_s.get('av_to', '').replace('USD', 'USDT') # Prefer USDT for TV if base was USD
            if 'USDT' not in tv_base and 'USD' not in tv_base : # e.g. BTC from BTCUSD
                 tradingview_symbol = f"{tv_base}{tv_quote}"
            else: # if av_from already contains quote e.g. BTCUSDT
                 tradingview_symbol = tv_base

        elif market_info['type'] in ['forex', 'commodity']:
            tradingview_symbol = f"FX_IDC:{av_s['av_from']}{av_s['av_to']}"
        
        # --- PERUBAHAN DI SINI (Menu Fitur) ---
        feature_keyboard = [
            [InlineKeyboardButton("Lihat Grafik (TradingView)", url=f"https://www.tradingview.com/chart/?symbol={tradingview_symbol}")],
            [InlineKeyboardButton("Pasang Alert (Segera Hadir)", callback_data="feature_alert_placeholder")], # Added placeholder for non-functional button
            [InlineKeyboardButton("Apa itu RSI?", callback_data="explain_rsi")],
            [InlineKeyboardButton("Apa itu MACD?", callback_data="explain_macd")],
            [InlineKeyboardButton("Analisis Ulang Simbol Ini", callback_data=f"reanalyze_market__{context.user_data.get('original_user_symbol', '')}")]
        ]
        # --- AKHIR PERUBAHAN ---
        feature_reply_markup = InlineKeyboardMarkup(feature_keyboard)

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Pilihan lebih lanjut:",
            reply_markup=feature_reply_markup
        )

    except Exception as e:
        print(f"Error saat membuat atau mengirim grafik: {e}")
        # If query.delete_message() succeeded, edit_message_text will fail.
        # So, send a new message for the error.
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Terjadi kesalahan saat membuat atau mengirim grafik: {e}"
        )

async def explain_rsi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "**RSI (Relative Strength Index)** adalah osilator momentum yang mengukur kecepatan dan perubahan pergerakan harga. "
        "RSI berosilasi antara 0 dan 100. Umumnya, RSI di atas 70 menunjukkan kondisi *overbought* (jenuh beli, potensi pembalikan turun), "
        "sementara di bawah 30 menunjukkan kondisi *oversold* (jenuh jual, potensi pembalikan naik)."
    )
    await query.message.reply_text(text, parse_mode='Markdown')

async def explain_macd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "**MACD (Moving Average Convergence Divergence)** adalah indikator momentum *trend-following* yang menunjukkan hubungan "
        "antara dua rata-rata bergerak harga (EMA 12 dan EMA 26). Garis MACD adalah selisih kedua EMA tersebut. "
        "Garis Sinyal adalah EMA 9 dari Garis MACD. Histogram MACD adalah selisih antara Garis MACD dan Garis Sinyal.\n\n"
        "Sinyal utama:\n"
        "- *Golden Cross*: Garis MACD memotong Garis Sinyal ke atas (sinyal bullish).\n"
        "- *Death Cross*: Garis MACD memotong Garis Sinyal ke bawah (sinyal bearish).\n"
        "- *Divergence*: Ketidaksesuaian antara pergerakan harga dan MACD."
    )
    await query.message.reply_text(text, parse_mode='Markdown')

async def reanalyze_market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    # Extract original symbol from callback data "reanalyze_market__SYMBOL"
    try:
        original_symbol = query.data.split('__')[-1]
        if not original_symbol: # Handle cases where symbol might be empty
            await query.message.reply_text("Tidak dapat menemukan simbol untuk dianalisis ulang. Silakan coba /analyze lagi.")
            return
    except (IndexError, AttributeError):
        await query.message.reply_text("Format callback reanalisis tidak valid.")
        return

    # Simulate a new /analyze command
    # We need to create a mock Update object that analyze_command expects, or pass args directly
    # For simplicity, let's reuse the existing message if possible, or create a new one.
    
    # Option 1: Directly call analyze_command with faked update and context.args
    # This is cleaner if analyze_command doesn't rely too much on specific message properties not available here.
    # Create a new Update object for the call, ensuring it has a message attribute
    # Note: This is a simplified way to reinvoke. Depending on what `analyze_command` uses from `update.message`,
    # you might need to populate more fields or ensure `query.message` is suitable.
    
    # Delete the message with "Pilihan Lebih Lanjut" buttons
    try:
        await query.delete_message()
    except Exception as e:
        print(f"Gagal menghapus pesan sebelum reanalisis: {e}")

    # Send a message as if user typed /analyze SYMBOL
    # This is more robust as it correctly sets up the context for analyze_command
    new_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"/analyze {original_symbol}"
    )

    # Create a new Update object based on this new message
    new_update = Update(update_id=update.update_id + 1, message=new_message) # update_id should be unique

    context.args = [original_symbol] # Set context.args as analyze_command expects
    await analyze_command(new_update, context)


async def feature_alert_placeholder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Placeholder for the 'Pasang Alert' feature."""
    query = update.callback_query
    await query.answer("Fitur 'Pasang Alert' segera hadir!", show_alert=True)


# --- Main Function untuk Menjalankan Bot ---
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("analyze", analyze_command)) 
    
    # Handler for timeframe selection
    application.add_handler(CallbackQueryHandler(process_analysis_callback_query, pattern='^analyze_tf_'))
    
    # Handlers for explanations
    application.add_handler(CallbackQueryHandler(explain_rsi_callback, pattern='^explain_rsi$'))
    application.add_handler(CallbackQueryHandler(explain_macd_callback, pattern='^explain_macd$'))
    
    # Handler for re-analyzing symbol
    application.add_handler(CallbackQueryHandler(reanalyze_market_callback, pattern='^reanalyze_market__'))

    # Handler for placeholder alert button
    application.add_handler(CallbackQueryHandler(feature_alert_placeholder_callback, pattern='^feature_alert_placeholder$'))


    print("Bot sedang berjalan...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
