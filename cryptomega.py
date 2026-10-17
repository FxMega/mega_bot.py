import yfinance as yf
import requests
import os
import pytz
from datetime import datetime
from bs4 import BeautifulSoup

PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
KAMPALA = pytz.timezone('Africa/Kampala')

# ========== RED NEWS FILTER v5.2 ==========
def get_red_news_block():
    try:
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_eat = datetime.now(KAMPALA)
        blocked = []

        # 1. FOREX FACTORY RED + CRYPTO KILLERS
        try:
            j_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            jr = requests.get(j_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if jr.status_code == 200:
                events = jr.json()
                for ev in events:
                    if ev.get('impact') != 'High':
                        continue
                    curr = ev.get('country','')
                    title = ev.get('title','').upper()
                    KILLERS = ['CPI','FOMC','FED','NFP','NON-FARM','INTEREST','GDP','PPI','UNEMPLOYMENT','POWELL','ETF','SEC','BLACKROCK','APPROVAL']
                    if curr in ['USD','ALL'] or any(k in title for k in KILLERS):
                        try:
                            ev_date = datetime.strptime(ev.get('date'), '%m-%d-%Y').date()
                            if abs((ev_date - now_utc.date()).days) <= 1:
                                blocked.append(f"RED {curr} {ev.get('title')} @ {ev.get('time')}")
                        except:
                            continue
        except Exception as e:
            print(f"Forex API error: {e}")

        # 2. FOMC 2026 DATES - FULL DAY BLOCK
        FOMC_2026 = ["2026-01-28","2026-03-18","2026-05-06","2026-06-17","2026-07-29","2026-09-16","2026-11-04","2026-12-09"]
        if now_eat.strftime("%Y-%m-%d") in FOMC_2026:
            blocked.append(f"FOMC DAY {now_eat.strftime('%Y-%m-%d')}")

        # 3. NFP FIRST FRIDAY 14-16 EAT
        if now_eat.weekday() == 4 and 1 <= now_eat.day <= 7 and 14 <= now_eat.hour <= 16:
            blocked.append("NFP FRIDAY 15:30 EAT")

        # 4. BTC FLASH >5% in 4h
        try:
            btc = yf.Ticker("BTC-USD").history(period="1d", interval="1h", auto_adjust=True)
            if not btc.empty and len(btc) >= 5:
                chg = (btc['Close'].iloc[-1] - btc['Close'].iloc[-4]) / btc['Close'].iloc[-4] * 100
                if abs(chg) > 5:
                    blocked.append(f"BTC {chg:+.1f}% in 4h - News Vol")
        except:
            pass

        if blocked:
            return True, " | ".join(blocked[:3])
        return False, "CLEAR"
    except Exception as e:
        print(f"News filter error fail open: {e}")
        return False, ""

CRYPTOS = {
    "BTC-USD": {"name": "BITCOIN", "lev": 100, "tp1": 0.02, "tp2": 0.04, "sl": 0.015},
    "ETH-USD": {"name": "ETHEREUM", "lev": 75, "tp1": 0.025, "tp2": 0.05, "sl": 0.018},
    "SOL-USD": {"name": "SOLANA", "lev": 50, "tp1": 0.04, "tp2": 0.08, "sl": 0.025},
    "BNB-USD": {"name": "BNB", "lev": 40, "tp1": 0.018, "tp2": 0.032, "sl": 0.012},
    "XRP-USD": {"name": "XRP", "lev": 30, "tp1": 0.035, "tp2": 0.07, "sl": 0.02},
    "DOGE-USD": {"name": "DOGE", "lev": 25, "tp1": 0.05, "tp2": 0.10, "sl": 0.03},
}

def get_data(sym):
    df = yf.Ticker(sym).history(period="30d", interval="1h", auto_adjust=True)
    if df.empty or len(df) < 60:
        return None
    df['EMA9'] = df['Close'].ewm(span=9).mean()
    df['EMA21'] = df['Close'].ewm(span=21).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()
    d = df['Close'].diff()
    g = (d.where(d > 0, 0)).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + g/l))
    df['EMA12'] = df['Close'].ewm(span=12).mean()
    df['EMA26'] = df['Close'].ewm(span=26).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_SIG'] = df['MACD'].ewm(span=9).mean()
    return df

def strategy_BTC(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e9, e21, e50 = float(last['EMA9']), float(last['EMA21']), float(last['EMA50'])
    if e21 > e50 and e9 > e21 and 35 < rsi < 65:
        return "BUY", price, rsi, "EMA50 Uptrend"
    if e21 < e50 and e9 < e21 and 35 < rsi < 65:
        return "SELL", price, rsi, "EMA50 Downtrend"
    return None

def strategy_ETH(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e9, e21 = float(last['EMA9']), float(last['EMA21'])
    macd, sig = float(last['MACD']), float(last['MACD_SIG'])
    if e9 > e21 and macd > sig and 38 < rsi < 68:
        return "BUY", price, rsi, "MACD Bullish Cross"
    if e9 < e21 and macd < sig and 32 < rsi < 62:
        return "SELL", price, rsi, "MACD Bearish Cross"
    return None

def strategy_SOL(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e9, e21, e50 = float(last['EMA9']), float(last['EMA21']), float(last['EMA50'])
    if e9 > e21 and price > e50 and 45 < rsi < 75:
        return "BUY", price, rsi, "Momentum Breakout"
    if e9 < e21 and price < e50 and 25 < rsi < 55:
        return "SELL", price, rsi, "Momentum Breakdown"
    return None

def strategy_BNB(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e9, e21, e50 = float(last['EMA9']), float(last['EMA21']), float(last['EMA50'])
    if e9 > e21 and e21 > e50 and 48 < rsi < 62:
        return "BUY", price, rsi, "Low Vol Trend Up"
    if e9 < e21 and e21 < e50 and 38 < rsi < 52:
        return "SELL", price, rsi, "Low Vol Trend Down"
    return None

def strategy_XRP(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e21 = float(last['EMA21'])
    if rsi < 38 and price > e21:
        return "BUY", price, rsi, "Oversold Bounce"
    if rsi > 62 and price < e21:
        return "SELL", price, rsi, "Overbought Fade"
    return None

def strategy_DOGE(df):
    last = df.iloc[-1]
    price, rsi = float(last['Close']), float(last['RSI'])
    e9, e21 = float(last['EMA9']), float(last['EMA21'])
    if rsi < 35 and e9 > e21:
        return "BUY", price, rsi, "Meme Oversold"
    if rsi > 65 and e9 < e21:
        return "SELL", price, rsi, "Meme Overbought"
    return None

STRATEGIES = {
    "BTC-USD": strategy_BTC,
    "ETH-USD": strategy_ETH,
    "SOL-USD": strategy_SOL,
    "BNB-USD": strategy_BNB,
    "XRP-USD": strategy_XRP,
    "DOGE-USD": strategy_DOGE,
}

# ===== MAIN =====
print("=== CRYPTOMEGA v5.2 PER-COIN + RED NEWS FILTER ===")
is_blocked, reason = get_red_news_block()
print(f"NEWS CHECK: {'BLOCKED - '+reason if is_blocked else 'CLEAR'}")

if is_blocked:
    txt = f"⛔ RED NEWS BLOCK\n{reason}\nNo trades - Paused"
    url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(txt)}&apikey={APIKEY}"
    requests.get(url, timeout=15)
    print("Paused due to red news")
    exit(0)

for sym, cfg in CRYPTOS.items():
    df = get_data(sym)
    if df is None:
        print(f"{sym} No data")
        continue
    res = STRATEGIES[sym](df)
    price_now = float(df['Close'].iloc[-1])
    rsi_now = float(df['RSI'].iloc[-1])
    print(f"{sym} ${price_now:.4f} RSI {rsi_now:.1f} -> {res[0] if res else 'NO SIGNAL'}")
    if res:
        signal, price, rsi, reason_r = res
        if signal == "BUY":
            tp1 = price * (1 + cfg['tp1'])
            tp2 = price * (1 + cfg['tp2'])
            sl = price * (1 - cfg['sl'])
        else:
            tp1 = price * (1 - cfg['tp1'])
            tp2 = price * (1 - cfg['tp2'])
            sl = price * (1 + cfg['sl'])
        def fmt(p):
            return f"{p:.4f}" if p < 1 else f"{p:.2f}"
        text = f"{cfg['name']} {signal}\n{reason_r}\nENTRY {fmt(price)}\nTP1 {fmt(tp1)}\nTP2 {fmt(tp2)}\nSL {fmt(sl)}\nRSI {rsi:.1f}\nLEV x{cfg['lev']}"
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(text)}&apikey={APIKEY}"
        r = requests.get(url, timeout=15)
        print(f"SENT {sym}: {r.text[:120]}")
