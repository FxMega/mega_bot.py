import yfinance as yf
import requests, os, pytz, time
from datetime import datetime

PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
KAMPALA = pytz.timezone('Africa/Kampala')

# ========== FILTERS ==========
def get_btc_flash_block():
    try:
        btc = yf.Ticker("BTC-USD").history(period="1d", interval="1h", auto_adjust=True)
        last = float(btc['Close'].iloc[-1])
        ago = float(btc['Close'].iloc[-4])
        chg = (last - ago) / ago * 100
        if abs(chg) > 5:
            return True, f"BTC FLASH {chg:+.1f}% in 4h"
        return False, "CLEAR"
    except:
        return False, "CLEAR"

def get_red_news_block():
    try:
        now = datetime.now(KAMPALA)
        if now.weekday() == 2 and 21 <= now.hour < 23:
            return True, "RED NEWS: FOMC 21:00-23:00 EAT"
        return False, "CLEAR"
    except:
        return False, "CLEAR"

# ========== ASSETS WITH OWN STRATEGY NAME ==========
ASSETS = {
    "BTC-USD": {"name": "BITCOIN", "type": "btc", "lev": 100, "tp1": 0.006, "tp2": 0.012, "sl": 0.004},
    "ETH-USD": {"name": "ETHEREUM", "type": "eth", "lev": 75, "tp1": 0.007, "tp2": 0.014, "sl": 0.005},
    "SOL-USD": {"name": "SOLANA", "type": "sol", "lev": 50, "tp1": 0.009, "tp2": 0.018, "sl": 0.006},
    "GC=F": {"name": "GOLD", "type": "gold", "lev": 30, "tp1": 0.004, "tp2": 0.008, "sl": 0.003},
    "SI=F": {"name": "SILVER", "type": "silver", "lev": 25, "tp1": 0.006, "tp2": 0.012, "sl": 0.005},
}

def get_data(sym):
    df = yf.Ticker(sym).history(period="7d", interval="15m", auto_adjust=True)
    if df.empty or len(df) < 70:
        return None
    df['EMA9'] = df['Close'].ewm(9).mean()
    df['EMA20'] = df['Close'].ewm(20).mean()
    df['EMA21'] = df['Close'].ewm(21).mean()
    df['EMA50'] = df['Close'].ewm(50).mean()
    df['EMA200'] = df['Close'].ewm(200).mean()
    d = df['Close'].diff()
    g = (d.where(d > 0, 0)).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + g/l))
    df['VOL_AVG'] = df['Volume'].rolling(20).mean()
    df['BB_MID'] = df['Close'].rolling(20).mean()
    df['BB_STD'] = df['Close'].rolling(20).std()
    df['BB_UP'] = df['BB_MID'] + df['BB_STD']*2
    df['BB_LOW'] = df['BB_MID'] - df['BB_STD']*2
    # MACD for ETH
    df['EMA12'] = df['Close'].ewm(12).mean()
    df['EMA26'] = df['Close'].ewm(26).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_SIG'] = df['MACD'].ewm(9).mean()
    return df

# ========== BTC BEST: EMA50 + EMA200 Trend + Pullback (BTC respects big EMAs, institutional) ==========
def btc_strategy(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    price, rsi = float(last['Close']), float(last['RSI'])
    # Only trade when above 200 EMA (bull market) or below for shorts
    if float(last['Close']) > float(last['EMA200']) and float(last['EMA50']) > float(last['EMA200']):
        # Pullback to EMA50 then bounce with volume
        if float(prev['Close']) < float(prev['EMA50']) and float(last['Close']) > float(last['EMA50']) and 50 < rsi < 68 and float(last['Volume']) > float(last['VOL_AVG'])*1.2:
            return "BUY", price, rsi, "BTC BEST: EMA50 Pullback + 200 Trend + Vol"
    if float(last['Close']) < float(last['EMA200']) and float(last['EMA50']) < float(last['EMA200']):
        if float(prev['Close']) > float(prev['EMA50']) and float(last['Close']) < float(last['EMA50']) and 32 < rsi < 50 and float(last['Volume']) > float(last['VOL_AVG'])*1.2:
            return "SELL", price, rsi, "BTC BEST: EMA50 Rejection + 200 Downtrend"
    return None

# ========== ETH BEST: EMA20 + MACD Cross + RSI 50 Level (ETH is trend follower) ==========
def eth_strategy(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    price, rsi = float(last['Close']), float(last['RSI'])
    macd, macd_sig = float(last['MACD']), float(last['MACD_SIG'])
    macd_prev, sig_prev = float(prev['MACD']), float(prev['MACD_SIG'])
    # Bull: MACD crosses up + price above EMA20 + RSI above 50
    if macd_prev < sig_prev and macd > macd_sig and float(last['Close']) > float(last['EMA20']) and rsi > 52 and rsi < 68:
        return "BUY", price, rsi, "ETH BEST: MACD Cross + EMA20 Trend"
    if macd_prev > sig_prev and macd < macd_sig and float(last['Close']) < float(last['EMA20']) and rsi < 48 and rsi > 32:
        return "SELL", price, rsi, "ETH BEST: MACD Cross Down + EMA20"
    return None

# ========== SOL BEST: BB Squeeze + EMA9 Breakout + Huge Volume (SOL is explosive) ==========
def sol_strategy(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    price, rsi = float(last['Close']), float(last['RSI'])
    # Bollinger squeeze breakout with extreme volume - SOL specialty
    if float(last['Close']) > float(last['BB_UP']) and float(last['Close']) > float(last['EMA9']) and float(last['Volume']) > float(last['VOL_AVG'])*1.5 and 55 < rsi < 75:
        return "BUY", price, rsi, f"SOL BEST: BB Breakout + Vol {float(last['Volume'])/float(last['VOL_AVG']):.1f}x"
    if float(last['Close']) < float(last['BB_LOW']) and float(last['Close']) < float(last['EMA9']) and float(last['Volume']) > float(last['VOL_AVG'])*1.5 and 25 < rsi < 45:
        return "SELL", price, rsi, f"SOL BEST: BB Breakdown + Vol {float(last['Volume'])/float(last['VOL_AVG']):.1f}x"
    return None

def gold_strategy(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    price, rsi = float(last['Close']), float(last['RSI'])
    if float(last['Close']) > float(last['EMA50']) and float(last['EMA21']) > float(last['EMA50']):
        if float(prev['Close']) < float(prev['EMA21']) and float(last['Close']) > float(last['EMA21']) and 45 < rsi < 65:
            return "BUY", price, rsi, "GOLD BEST: EMA21 Pullback Bounce"
    if float(last['Close']) < float(last['EMA50']) and float(last['EMA21']) < float(last['EMA50']):
        if float(prev['Close']) > float(prev['EMA21']) and float(last['Close']) < float(last['EMA21']) and 35 < rsi < 55:
            return "SELL", price, rsi, "GOLD BEST: EMA21 Pullback Drop"
    return None

def silver_strategy(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    if float(last['Close']) > float(last['BB_UP']) and float(last['Close']) > float(last['EMA21']) and 50 < rsi < 70 and float(last['Volume']) > float(last['VOL_AVG'])*1.3:
        return "BUY", price, rsi, f"SILVER BEST: BB Breakout Vol {float(last['Volume'])/float(last['VOL_AVG']):.1f}x"
    if float(last['Close']) < float(last['BB_LOW']) and float(last['Close']) < float(last['EMA21']) and 30 < rsi < 50 and float(last['Volume']) > float(last['VOL_AVG'])*1.3:
        return "SELL", price, rsi, f"SILVER BEST: BB Breakdown Vol {float(last['Volume'])/float(last['VOL_AVG']):.1f}x"
    return None

# ===== MAIN =====
print("=== FXMEGA UG SCALPING v8 EACH COIN BEST STRATEGY ===")
btc_block, btc_r = get_btc_flash_block()
news_block, news_r = get_red_news_block()
print(f"BTC: {btc_r} | NEWS: {news_r}")

if btc_block or news_block:
    reason = btc_r if btc_block else news_r
    txt = f"FXMEGA UG SCALPING\n⛔ BLOCKED\n{reason}\nNo scalps - Paused"
    requests.get(f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(txt)}&apikey={APIKEY}", timeout=15)
    time.sleep(5)
    exit(0)

for sym, cfg in ASSETS.items():
    df = get_data(sym)
    if df is None:
        print(f"{sym} no data")
        continue

    if cfg['type'] == 'btc':
        res = btc_strategy(df)
    elif cfg['type'] == 'eth':
        res = eth_strategy(df)
    elif cfg['type'] == 'sol':
        res = sol_strategy(df)
    elif cfg['type'] == 'gold':
        res = gold_strategy(df)
    else:
        res = silver_strategy(df)

    price_now = float(df['Close'].iloc[-1])
    print(f"{cfg['name']} ${price_now:.2f} -> {res[0] if res else 'WAIT'} | {cfg['type']}")

    if res:
        sig, price, rsi, reason = res
        if sig == "BUY":
            tp1 = price * (1 + cfg['tp1'])
            tp2 = price * (1 + cfg['tp2'])
            sl = price * (1 - cfg['sl'])
        else:
            tp1 = price * (1 - cfg['tp1'])
            tp2 = price * (1 - cfg['tp2'])
            sl = price * (1 + cfg['sl'])

        txt = f"FXMEGA UG SCALPING\n⚡ {cfg['name']} {sig} 15M\n{reason}\nENTRY {price:.2f}\nTP1 {tp1:.2f} (+{cfg['tp1']*100:.1f}%)\nTP2 {tp2:.2f}\nSL {sl:.2f}\nRSI {rsi:.1f} LEV x{cfg['lev']}"
        requests.get(f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(txt)}&apikey={APIKEY}", timeout=15)
        time.sleep(5)
