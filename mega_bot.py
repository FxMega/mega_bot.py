import os
import json
import asyncio
import datetime
import pytz
import requests
import websockets
import pandas as pd

# ================= FXMEGA UG V5.3 LATEST - DUAL SEND =================
# FIXED: ENTRY/SL/TP same bug + Sends to WhatsApp + ntfy.sh at same time
# Topic: gold-ai-ug-788408267 | Phone: 0700848808

KAMPALA_TZ = pytz.timezone('Africa/Kampala')
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "256700848808")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "gold-ai-ug-788408267")

DERIV_WS_LIST = [
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089"
]

SYMBOLS_VOL = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "VOLATILITY_10_INDEX", "VOLATILITY_25_INDEX", 
    "VOLATILITY_50_INDEX", "VOLATILITY_75_INDEX", "VOLATILITY_100_INDEX"
]

HISTORY_FILE = "signals_history.json"

# ========== FIX: PRICE FORMATTER (SOLVES 1.13/1.13/1.13 BUG) ==========
def fmt(sym, p):
    try:
        p = float(p)
        s = sym.upper()
        if "JPY" in s:
            return f"{p:.3f}"
        if "XAU" in s or "GOLD" in s:
            return f"{p:.2f}"
        if "XAG" in s:
            return f"{p:.3f}"
        if "EUR" in s or "GBP" in s or "USD" in s:
            return f"{p:.5f}"
        return f"{p:.2f}"
    except:
        return str(p)

def send_whatsapp(text):
    if not CALLMEBOT_APIKEY:
        print("No CALLMEBOT_APIKEY - skipping WhatsApp")
        return
    try:
        phone = WHATSAPP_PHONE.replace("+", "").replace(" ", "")
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={requests.utils.quote(text)}&apikey={CALLMEBOT_APIKEY}"
        r = requests.get(url, timeout=15)
        print(f"WhatsApp Sent: {r.status_code}")
    except Exception as e:
        print(f"WhatsApp Error: {e}")

def send_ntfy(title, body):
    try:
        url = f"https://ntfy.sh/{NTFY_TOPIC}"
        data = f"{title}\n{body}"
        headers = {
            "Title": title,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend,money_bar,gold"
        }
        r = requests.post(url, data=data.encode('utf-8'), headers=headers, timeout=10)
        print(f"ntfy Sent: {r.status_code} to {NTFY_TOPIC}")
    except Exception as e:
        print(f"ntfy Error: {e}")

def send_all(title, body):
    """SENDS TO BOTH WHATSAPP + NTFY AT SAME TIME"""
    full = f"{title}\n{body}\n\nFXMEGA UG • 0700848808"
    print(full)
    send_whatsapp(full)  # 1. WhatsApp
    send_ntfy(title, body)  # 2. ntfy app
    # Save history for TP tracker
    try:
        hist = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                hist = json.load(f)
        hist.append({
            "title": title, 
            "body": body, 
            "time": datetime.datetime.now().isoformat()
        })
        with open(HISTORY_FILE, 'w') as f:
            json.dump(hist[-100:], f, indent=2)
    except Exception as e:
        print(f"History error: {e}")

def add_signal(sym):
    print(f"Signal logged: {sym}")

def rsi_calc(s, p=14):
    delta = s.diff()
    gain = (delta.where(delta > 0, 0)).ewm(span=p).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=p).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

async def get_candles(sym, gran=60):
    for WS in DERIV_WS_LIST:
        try:
            async with websockets.connect(WS, ping_interval=20) as ws:
                req = {
                    "ticks_history": sym,
                    "adjust_start_time": 1,
                    "count": 200,
                    "end": "latest",
                    "granularity": gran,
                    "style": "candles"
                }
                await ws.send(json.dumps(req))
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(resp)
                if "candles" in data:
                    return pd.DataFrame(data["candles"])
        except Exception as e:
            print(f"WS {sym} error: {e}")
            continue
    return pd.DataFrame()

async def analyze_vol(sym):
    df = await get_candles(sym, gran=60)
    if df.empty or len(df) < 60:
        print(f"{sym} no data")
        return
    try:
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        ema50 = df['close'].ewm(span=50).mean()
        ema_flat = abs(ema50.iloc[-1] - ema50.iloc[-10]) < (df['close'].iloc[-1] * 0.001) if len(ema50) > 10 else True
        recent = df.iloc[-120:]
        rh = recent['high'].max()
        rl = recent['low'].min()
        rs = rh - rl
        if rs == 0:
            return
        price = float(df['close'].iloc[-1])
        r = float(rsi_calc(df['close']).iloc[-1])
        pos = ((price - rl) / rs * 100) if rs > 0 else 50

        if pos < 20 and r < 35 and ema_flat:
            add_signal(sym)
            sl = rl - (rs * 0.2)
            tp = rl + (rs * 0.8)
            send_all(
                f"🔵 FX MEGA UG - {sym} BUY",
                f"🎯 ENTRY: {fmt(sym,price)} | Low: {fmt(sym,rl)} High: {fmt(sym,rh)}\n"
                f"🔴 SL: {fmt(sym,sl)} | ✅ TP: {fmt(sym,tp)} | RSI:{r:.1f} Pos:{pos:.1f}\n"
                f"⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}"
            )

        if pos > 80 and r > 65 and ema_flat:
            add_signal(sym)
            sl = rh + (rs * 0.2)
            tp = rh - (rs * 0.8)
            send_all(
                f"🔴 FX MEGA UG - {sym} SELL",
                f"🎯 ENTRY: {fmt(sym,price)} | High: {fmt(sym,rh)} Low: {fmt(sym,rl)}\n"
                f"🔴 SL: {fmt(sym,sl)} | ✅ TP: {fmt(sym,tp)} | RSI:{r:.1f} Pos:{pos:.1f}\n"
                f"⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}"
            )
    except Exception as e:
        print(f"Analyze {sym} error: {e}")

async def analyze_gold():
    try:
        import yfinance as yf
        df = yf.download("GC=F", period="2d", interval="15m", progress=False)
        if df.empty:
            print("Gold no data")
            return
        # Fix yfinance columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        
        price = float(df['close'].iloc[-1])
        e20 = float(df['close'].ewm(span=20).mean().iloc[-1])
        e50 = float(df['close'].ewm(span=50).mean().iloc[-1])
        r = float(rsi_calc(df['close']).iloc[-1])
        a = float((df['high'] - df['low']).rolling(14).mean().iloc[-1])
        last_high = float(df['high'].iloc[-20:-1].max())
        last_low = float(df['low'].iloc[-20:-1].min())
        is_up = price > e20 > e50
        is_down = price < e20 < e50

        if is_up and price > last_high and 55 < r < 75:
            add_signal("GOLD")
            sl = price - (a * 1.5)
            tp1 = price + (a * 2)
            tp2 = price + (a * 3.5)
            send_all(
                f"🔵 FX MEGA UG - GOLD BUY",
                f"🎯 ENTRY: {fmt('GOLD',price)} | 🔴 SL: {fmt('GOLD',sl)}\n"
                f"✅ TP1: {fmt('GOLD',tp1)} | TP2: {fmt('GOLD',tp2)}\n"
                f"📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n"
                f"⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}"
            )

        if is_down and price < last_low and 30 < r < 55:
            add_signal("GOLD")
            sl = price + (a * 1.5)
            tp1 = price - (a * 2)
            tp2 = price - (a * 3.5)
            send_all(
                f"🔴 FX MEGA UG - GOLD SELL",
                f"🎯 ENTRY: {fmt('GOLD',price)} | 🔴 SL: {fmt('GOLD',sl)}\n"
                f"✅ TP1: {fmt('GOLD',tp1)} | TP2: {fmt('GOLD',tp2)}\n"
                f"📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n"
                f"⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}"
            )
        print("Gold checked OK")
    except Exception as e:
        print(f"Gold error: {e}")

async def main():
    print(f"FXMEGA UG V5.3 LATEST Starting - {datetime.datetime.now(KAMPALA_TZ)}")
    print(f"DUAL SEND: WhatsApp {WHATSAPP_PHONE} + ntfy.sh/{NTFY_TOPIC}")
    await analyze_gold()
    for sym in SYMBOLS_VOL:
        try:
            await analyze_vol(sym)
        except Exception as e:
            print(e)
    print("FXMEGA UG Done - Signals sent to BOTH apps!")

if __name__ == "__main__":
    asyncio.run(main())
