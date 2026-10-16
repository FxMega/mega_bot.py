import yfinance as yf
import pandas as pd
import requests
import pytz
import os
from datetime import datetime
import json
import ta
import re

# ===== CONFIG - FROM GITHUB SECRETS =====
PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
EAT = pytz.timezone('Africa/Kampala')

# ===== SEND FUNCTION - CALLMEBOT =====
def send_whatsapp(message):
    try:
        full_message = f"{message}\n\n---\nFXMEGA UG • 0700848808"
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(full_message)}&apikey={APIKEY}"
        r = requests.get(url, timeout=30)
        print(f"WHATSAPP SENT: {r.text} | Status: {r.status_code}")
        return True
    except Exception as e:
        print(f"WHATSAPP FAIL: {e}")
        return False

def get_indicators(df):
    df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=20)
    df['EMA50'] = ta.trend.ema_indicator(df['Close'], window=50)
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
    df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
    df['High20'] = df['High'].rolling(20).max()
    df['Low20'] = df['Low'].rolling(20).min()
    return df

def analyze_pair(symbol, name, tf):
    try:
        interval = "15m" if tf == "SCALP" else "1h"
        period = "5d" if tf == "SCALP" else "1mo"
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = get_indicators(df)
        last = df.iloc[-1]
        price = float(last['Close'])
        rsi = float(last['RSI'])
        ema20 = float(last['EMA20'])
        ema50 = float(last['EMA50'])
        atr = float(last['ATR'])

        signal = None
        reason = ""

        if price > ema20 > ema50 and 55 < rsi < 75 and price >= last['High20'] * 0.999:
            signal = "BUY"
            reason = f"Trend Bullish • Price above EMA20/50 • RSI {rsi:.1f} • Breakout"
        elif price < ema20 < ema50 and 25 < rsi < 45 and price <= last['Low20'] * 1.001:
            signal = "SELL"
            reason = f"Trend Bearish • Price below EMA20/50 • RSI {rsi:.1f} • Breakdown"

        if signal:
            sl = price - (atr * 1.5) if signal == "BUY" else price + (atr * 1.5)
            tp = price + (atr * 3) if signal == "BUY" else price - (atr * 3)
            icon = "🟢" if signal == "BUY" else "🔴"
            msg = f"""{icon} {signal} {name} ({tf})

Symbol: {symbol}
Price: {price:.2f}
TF: {tf}

Entry: {price:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Reason: {reason}
RSI: {rsi:.1f}
EMA20: {ema20:.2f} | EMA50: {ema50:.2f}

Time: {datetime.now(EAT).strftime('%Y-%m-%d %H:%M EAT')}"""
            return {"msg": msg, "entry": price, "tp": tp, "sl": sl, "direction": signal}
        return None
    except Exception as e:
        print(f"Error {name}: {e}")
        return None

def check_tp_hits():
    if not os.path.exists("signals_history.json"):
        return
    try:
        with open("signals_history.json", "r") as f:
            history = json.load(f)
        active = [s for s in history if s.get("status") == "ACTIVE"]
        if not active:
            return
        for sig_data in history:
            if sig_data.get("status") != "ACTIVE":
                continue
            symbol = sig_data["symbol"]
            name = sig_data["name"]
            entry = float(sig_data["entry"])
            tp = float(sig_data["tp"])
            sl = float(sig_data["sl"])
            direction = sig_data["direction"]
            try:
                data = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
                if data.empty:
                    continue
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                current_price = float(data['Close'].iloc[-1])
                high = float(data['High'].max())
                low = float(data['Low'].min())
                hit = None
                if direction == "BUY":
                    if high >= tp:
                        hit = f"🎯 TP HIT! {name} BUY {entry:.2f} -> {tp:.2f} 💰 Profit!"
                    elif low <= sl:
                        hit = f"❌ SL HIT! {name} BUY {entry:.2f} -> {sl:.2f}"
                elif direction == "SELL":
                    if low <= tp:
                        hit = f"🎯 TP HIT! {name} SELL {entry:.2f} -> {tp:.2f} 💰 Profit!"
                    elif high >= sl:
                        hit = f"❌ SL HIT! {name} SELL {entry:.2f} -> {sl:.2f}"
                if hit:
                    send_whatsapp(hit)
                    sig_data["status"] = "CLOSED"
            except Exception as e:
                print(f"Check {name} error: {e}")
                continue
        with open("signals_history.json", "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"TP Check error: {e}")

def main():
    print("FXMEGA UG V4.6 FULL - CallMeBot Edition Running...")
    check_tp_hits()
    pairs = [
        ("GC=F", "GOLD"),
        ("SI=F", "SILVER"),
        ("BTC-USD", "BTCUSD"),
        ("EURUSD=X", "EURUSD"),
        ("GBPUSD=X", "GBPUSD"),
        ("USDJPY=X", "USDJPY"),
    ]
    found_signals = []
    for symbol, name in pairs:
        # Check both SCALP and SWING
        for tf in ["SCALP", "SWING"]:
            result = analyze_pair(symbol, name, tf)
            if result:
                if isinstance(result, dict):
                    sig_msg = result.get("msg", str(result))
                    entry = result.get("entry", 0)
                    tp = result.get("tp", 0)
                    sl = result.get("sl", 0)
                    direction = result.get("direction", "BUY")
                else:
                    sig_msg = result
                    entry = tp = sl = 0
                    direction = "SELL" if "SELL" in sig_msg else "BUY"
                    try:
                        m1 = re.search(r"Entry: ([\d\.]+)", sig_msg)
                        m2 = re.search(r"TP: ([\d\.]+)", sig_msg)
                        m3 = re.search(r"SL: ([\d\.]+)", sig_msg)
                        if m1: entry = float(m1.group(1))
                        if m2: tp = float(m2.group(1))
                        if m3: sl = float(m3.group(1))
                    except:
                        pass
                found_signals.append(sig_msg)
                send_whatsapp(sig_msg)
                try:
                    hist = []
                    if os.path.exists("signals_history.json"):
                        with open("signals_history.json", "r") as f:
                            hist = json.load(f)
                    if entry and tp and sl:
                        hist.append({"symbol": symbol, "name": name, "entry": entry, "tp": tp, "sl": sl, "direction": direction, "time": datetime.now(EAT).isoformat(), "status": "ACTIVE"})
                        with open("signals_history.json", "w") as f:
                            json.dump(hist, f, indent=2)
                except Exception as e:
                    print(f"Save hist error: {e}")
    if not found_signals:
        print("No signals this run - Bot is monitoring...")

def daily_report():
    msg = f"""📊 DAILY REPORT - {datetime.now(EAT).strftime('%d %B %Y')}

Today's Summary:
Checked: GOLD, SILVER, BTC, EURUSD, GBPUSD, USDJPY
Bot Status: Active ✅
Time: {datetime.now(EAT).strftime('%H:%M EAT')}"""
    send_whatsapp(msg)

def weekly_report():
    msg = f"""📈 WEEKLY REPORT - Week Ending {datetime.now(EAT).strftime('%d %B %Y')}

Bot Status: Active All Week ✅
FXMEGA UG - Professional Signals"""
    send_whatsapp(msg)

if __name__ == "__main__":
    now = datetime.now(EAT)
    if now.hour == 22:
        if now.weekday() == 6:
            weekly_report()
        daily_report()
    else:
        main()
