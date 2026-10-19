import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timezone
import time, json, os
import numpy as np

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND = "FXMEGA UG"
CONTACT = "0700848808"
TRADE_FILE = "active_trades.json"

# === v10.9 M15 FILTER SETTINGS (DYNAMIC - NO HARDCODE PRICE) ===
ADX_MIN_TREND = 20.0       # M15 ADX <20 = ranging (your 105.54 chart ~12)
ATR_RANGE_MULT_MIN = 0.8   # Range must be >0.8 ATR to be valid
ATR_RANGE_MULT_MAX = 4.0   # Range must be <4 ATR (else trend)
BB_SQUEEZE_PCT = 0.35      # BB width <0.35% = squeeze
RANGE_LOOKBACK = 80        # 80x M15 = 20 hours
USE_MEAN_REVERSION = True  # In ranging, buy low/sell high

PAIRS = {
    "BTC-USD": "BITCOIN",
    "ETH-USD": "ETHEREUM",
    "SOL-USD": "SOLANA",
    "BNB-USD": "BNB",
    "XRP-USD": "XRP",
    "DOGE-USD": "DOGECOIN",
    "GC=F": "GOLD",
    "SI=F": "SILVER",
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY"
}

DXY_SYMBOL = "DX-Y.NYB"

def send(msg, is_buy=True):
    try:
        if "BUY" in msg and "SIGNAL" in msg:
            title = "BUY SIGNAL"
            tag = "moneybag"
        elif "SELL" in msg and "SIGNAL" in msg:
            title = "SELL SIGNAL"
            tag = "money_with_wings"
        else:
            title = "BE/TRAIL ALERT"
            tag = "rocket"
        requests.post(NTFY_URL,
                      data=msg.encode('utf-8'),
                      headers={
                          "Title": f"{title} - {BRAND}",
                          "Priority": "high",
                          "Tags": tag,
                          "Content-Type": "text/plain; charset=utf-8"
                      }, timeout=10)
        print(f"SENT: {msg[:100]}")
        time.sleep(6)
    except Exception as e:
        print(f"Send error: {e}")
        time.sleep(6)

def load_trades():
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_trades(tr):
    with open(TRADE_FILE, 'w') as f: json.dump(tr, f, indent=2)

def is_weekend():
    return datetime.now(timezone.utc).weekday() >= 5

def get_red_news():
    blocked = set()
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10).json()
        now = datetime.now(timezone.utc)
        for ev in r:
            if ev.get("impact") != "High": continue
            try: et = datetime.fromisoformat(ev.get("date").replace("Z", "+00:00"))
            except: continue
            if -30 <= (et - now).total_seconds() / 60 <= 60:
                c = ev.get("country", "").strip()
                if c: blocked.add(c)
    except: pass
    return blocked

def f(x):
    try:
        if hasattr(x, 'iloc'): return float(x.iloc[0])
        return float(x)
    except: return float(x)

def fmt_price(p):
    try:
        p = float(p)
        if p < 0.01: return f"{p:.6f}"
        elif p < 1: return f"{p:.5f}"
        elif p < 10: return f"{p:.4f}"
        elif p < 100: return f"{p:.3f}"
        else: return f"{p:.2f}"
    except: return str(p)

# === v10.9 NEW FUNCTIONS - AUTO DETECT RANGE FOR ANY PAIR ===

def calculate_adx(df, period=14):
    try:
        high = df['High']; low = df['Low']; close = df['Close']
        plus_dm = high.diff()
        minus_dm = low.diff().abs() * -1
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > high.diff()) & (minus_dm > 0), 0.0).abs()
        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.rolling(period).mean()
        return f(adx.iloc[-1])
    except: return 25.0

def calculate_bb_width(df, period=20):
    try:
        close = df['Close']
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + 2*std
        lower = sma - 2*std
        cur = f(close.iloc[-1])
        width = ((f(upper.iloc[-1]) - f(lower.iloc[-1])) / cur * 100) if cur else 0
        return width
    except: return 1.0

def get_auto_range(df):
    """Auto-detect range for whatever pair df is - NO HARDCODE 105.540"""
    try:
        lookback = RANGE_LOOKBACK
        if len(df) < lookback: lookback = len(df)-1
        recent = df.tail(lookback)
        atr = f(pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift()).abs(), (df['Low']-df['Close'].shift()).abs()], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
        if atr == 0: atr = f(recent['Close'].iloc[-1]) * 0.01
        
        raw_high = f(recent['High'].max())
        raw_low = f(recent['Low'].min())
        tolerance = atr * 0.3  # dynamic for any pair
        
        high_touches = 0
        low_touches = 0
        for i in range(len(recent)):
            h = f(recent['High'].iloc[i])
            l = f(recent['Low'].iloc[i])
            if abs(h - raw_high) <= tolerance: high_touches += 1
            if abs(l - raw_low) <= tolerance: low_touches += 1
        
        mid = (raw_high + raw_low) / 2
        range_width = raw_high - raw_low
        range_atr = range_width / atr if atr else 0
        
        is_valid = (high_touches >= 2 and low_touches >= 2 and ATR_RANGE_MULT_MIN <= range_atr <= ATR_RANGE_MULT_MAX)
        
        return {
            "high": raw_high, "low": raw_low, "mid": mid,
            "high_touches": high_touches, "low_touches": low_touches,
            "range_atr": range_atr, "is_valid": is_valid, "atr": atr
        }
    except:
        return {"high":0,"low":0,"mid":0,"high_touches":0,"low_touches":0,"range_atr":0,"is_valid":False,"atr":0}

def is_ranging_market(adx, bb_width, auto_range):
    if adx < ADX_MIN_TREND: return True
    if bb_width < BB_SQUEEZE_PCT: return True
    if auto_range["is_valid"] and auto_range["range_atr"] < 1.8: return True
    return False

def is_bullish_rejection(df):
    try:
        o = f(df['Open'].iloc[-1]); c = f(df['Close'].iloc[-1])
        h = f(df['High'].iloc[-1]); l = f(df['Low'].iloc[-1])
        body = abs(c - o); lower_wick = min(o,c) - l
        return lower_wick > body * 1.5 and c > o
    except: return False

def is_bearish_rejection(df):
    try:
        o = f(df['Open'].iloc[-1]); c = f(df['Close'].iloc[-1])
        h = f(df['High'].iloc[-1]); l = f(df['Low'].iloc[-1])
        body = abs(c - o); upper_wick = h - max(o,c)
        return upper_wick > body * 1.5 and c < o
    except: return False

def get_dxy():
    try:
        df = yf.download(DXY_SYMBOL, period="5d", interval="15m", auto_adjust=True, progress=False)
        if df.empty:
            df = yf.download("DX=F", period="5d", interval="15m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        close = df['Close']
        ema = close.ewm(span=13).mean()
        ema_now = f(ema.iloc[-1])
        ema_prev = f(ema.iloc[-2])
        cur = f(close.iloc[-1])
        return cur, ema_now, cur < ema_now, cur > ema_now, ema_now > ema_prev, ema_now < ema_prev
    except Exception as e:
        print(f"DXY error: {e}")
        return None, None, False, False, False, False

# === 1. AUTO BE + TRAILING (SAME) ===
active = load_trades()
print(f"Active trades: {len(active)}")

for sym, name in PAIRS.items():
    if name not in active: continue
    if "USD=X" in sym and is_weekend(): continue
    try:
        df = yf.download(sym, period="1d", interval="15m", auto_adjust=True, progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        cur = f(df['Close'].iloc[-1])
        t = active[name]
        side = t['side']
        entry = t['entry']
        stage = t.get('stage', 0)
        tp1 = t['tp1']; tp2 = t['tp2']; tp3 = t['tp3']; tp4 = t['tp4']

        hit_tp1 = (cur >= tp1) if side == "BUY" else (cur <= tp1)
        hit_tp2 = (cur >= tp2) if side == "BUY" else (cur <= tp2)
        hit_tp3 = (cur >= tp3) if side == "BUY" else (cur <= tp3)
        hit_tp4 = (cur >= tp4) if side == "BUY" else (cur <= tp4)

        if hit_tp4:
            send(f"""🏁🎉 {name} TP4 HIT - CLOSE ALL! 💰💰💰
{'🟢' if side == 'BUY' else '🔴'} {side} {name}
💵 TP4 {fmt_price(tp4)} HIT at {fmt_price(cur)}
💸 Profit: +{fmt_price(abs(cur-entry))} 🚀
✅ Close remaining 25%
{CONTACT} {BRAND} 🌟""", is_buy=side == "BUY")
            del active[name]; save_trades(active); continue

        if hit_tp3 and stage < 3:
            send(f"""🔒➡️ {name} TRAIL TO TP2 📈
{'🟢' if side == 'BUY' else '🔴'} {side} {name}
🎯 TP3 {fmt_price(tp3)} HIT!
🔄 Move SL {fmt_price(t['sl'])} ➡️ {fmt_price(tp2)}
💰 Lock profit: +{fmt_price(abs(tp2-entry))} 💵
{CONTACT} {BRAND}""", is_buy=side == "BUY")
            t['sl'] = tp2; t['stage'] = 3; active[name] = t; save_trades(active); continue

        if hit_tp2 and stage < 2:
            send(f"""🔒➡️ {name} TRAIL TO TP1 📈🔥
{'🟢' if side == 'BUY' else '🔴'} {side} {name}
🎯 TP2 {fmt_price(tp2)} HIT at {fmt_price(cur)}
🔄 SL -> {fmt_price(tp1)} (TP1)
💰 Locked: +{fmt_price(abs(tp1-entry))} 💵💵
{CONTACT} {BRAND}""", is_buy=side == "BUY")
            t['sl'] = tp1; t['stage'] = 2; active[name] = t; save_trades(active); continue

        if hit_tp1 and stage < 1:
            send(f"""🔒✨ {name} AUTO BE TRIGGERED 🛡️
{'🟢' if side == 'BUY' else '🔴'} {side} {name}
🎯 TP1 {fmt_price(tp1)} HIT at {fmt_price(cur)} ✅✅
👉 ACTION: MOVE SL TO BE {fmt_price(entry)}
😎 Risk free now! No loss 💪
{CONTACT} {BRAND} 🚀""", is_buy=side == "BUY")
            t['sl'] = entry; t['stage'] = 1; active[name] = t; save_trades(active); continue

    except Exception as e:
        print(f"Trail {name}: {e}")

# === 2. NEW SIGNALS SCAN v10.9 WITH AUTO RANGE ===
blocked = get_red_news()
dxy_cur, dxy_ema, dxy_below, dxy_above, dxy_up, dxy_down = get_dxy()
print(f"DXY {dxy_cur} EMA {dxy_ema} Below:{dxy_below} Down:{dxy_down} Above:{dxy_above} Up:{dxy_up}")
print(f"Blocked news: {blocked}")

for sym, name in PAIRS.items():
    if name in active:
        print(f"{name}: in trade skip")
        continue
    if "USD=X" in sym and is_weekend():
        print(f"{name}: weekend closed")
        continue
    curr = "EUR" if "EUR" in name else "GBP" if "GBP" in name else "JPY" if "JPY" in name else "USD"
    if curr in blocked or ("USD" in blocked and name in ["GOLD", "SILVER", "BITCOIN", "ETHEREUM", "BNB"]):
        print(f"{name}: news blocked")
        continue

    try:
        df = yf.download(sym, period="5d", interval="15m", auto_adjust=True, progress=False)
        df_d = yf.download(sym, period="10d", interval="1d", auto_adjust=True, progress=False)
        if df.empty or len(df) < 100: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(df_d.columns, pd.MultiIndex): df_d.columns = df_d.columns.get_level_values(0)

        close = df['Close']; high = df['High']; low = df['Low']; open_ = df['Open']
        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        atr_raw = f(tr.rolling(14).mean().iloc[-1])

        ema13 = close.ewm(span=13).mean()
        ema_now = f(ema13.iloc[-1]); ema_prev = f(ema13.iloc[-2])
        up = ema_now > ema_prev; down = ema_now < ema_prev
        cur = f(close.iloc[-1]); hnow = f(high.iloc[-1]); lnow = f(low.iloc[-1])

        # FIX ATR FOR LOW PRICE
        atr = atr_raw
        min_atr = cur * 0.005
        if atr < min_atr: atr = min_atr
        if cur < 1.0 and atr < cur * 0.01: atr = cur * 0.01
        if atr == 0 or atr is None: atr = cur * 0.01

        # === v10.9 AUTO RANGE + ADX FILTER (DYNAMIC PAIR PRICE) ===
        adx_val = calculate_adx(df)
        bb_width = calculate_bb_width(df)
        auto_range = get_auto_range(df)
        ranging = is_ranging_market(adx_val, bb_width, auto_range)

        print(f"{name} {fmt_price(cur)} ADX:{adx_val:.1f} BB:{bb_width:.2f}% Range:{fmt_price(auto_range['low'])}-{fmt_price(auto_range['high'])} Valid:{auto_range['is_valid']} Ranging:{ranging}")

        # IF RANGING, SKIP TREND SIGNALS
        if ranging and not USE_MEAN_REVERSION:
            print(f"{name}: RANGING detected (ADX {adx_val:.1f} < {ADX_MIN_TREND}) -> SKIP trend")
            continue

        pdh = f(df_d['High'].iloc[-2]); pdl = f(df_d['Low'].iloc[-2]); crt50 = (pdh+pdl)/2
        bull_crt = lnow < pdl and cur > pdl and cur > crt50
        bear_crt = hnow > pdh and cur < pdh and cur < crt50

        body = abs(cur - f(open_.iloc[-1])); rng = hnow - lnow
        bp = body/rng if rng > 0 else 0
        bull_csd = cur > f(open_.iloc[-1]) and bp > 0.6 and cur > f(high.iloc[-2])
        bear_csd = cur < f(open_.iloc[-1]) and bp > 0.6 and cur < f(low.iloc[-2])

        bulls_now = hnow - ema_now; bulls_prev = f(high.iloc[-2]) - ema_prev
        bears_now = lnow - ema_now; bears_prev = f(low.iloc[-2]) - ema_prev
        bulls_ok = (bulls_prev < 0 and bulls_now > 0) or bulls_now > 0
        bears_ok = (bears_prev > 0 and bears_now < 0) or bears_now < 0

        base_buy = (bull_crt or bull_csd) and cur > ema_now and up and bulls_ok
        base_sell = (bear_crt or bear_csd) and cur < ema_now and down and bears_ok

        # === v10.9 LOGIC ===
        buy_signal = False
        sell_signal = False
        signal_type = ""

        if not ranging:
            # TRENDING MODE - your silver 57.305 winners
            if name == "GOLD":
                if dxy_cur is None:
                    print("GOLD skip DXY fail")
                    continue
                buy_signal = base_buy and dxy_below and dxy_down
                sell_signal = base_sell and dxy_above and dxy_up
                dxy_msg = f"💵 DXY {fmt_price(dxy_cur)} {'📉 BELOW+DOWN✅' if (dxy_below and dxy_down) else '📈 ABOVE+UP✅' if (dxy_above and dxy_up) else '❌ FAIL'}"
                signal_type = "TREND+DXY"
            else:
                buy_signal = base_buy
                sell_signal = base_sell
                dxy_msg = "✨ No DXY needed - TREND MODE"
                signal_type = "TREND"
        else:
            # RANGING MODE - mean reversion using auto range of current pair
            if auto_range["is_valid"] and USE_MEAN_REVERSION:
                range_low = auto_range["low"]
                range_high = auto_range["high"]
                range_mid = auto_range["mid"]
                edge = (range_high - range_low) * 0.25

                # BUY at auto low
                if lnow <= range_low + edge and is_bullish_rejection(df):
                    buy_signal = True
                    signal_type = f"RANGE BUY at auto low {fmt_price(range_low)}"
                    dxy_msg = f"📦 RANGING M15 - ADX {adx_val:.1f} | AutoRange {fmt_price(range_low)}-{fmt_price(range_high)} -> mean reversion to mid {fmt_price(range_mid)}"
                # SELL at auto high
                elif hnow >= range_high - edge and is_bearish_rejection(df):
                    sell_signal = True
                    signal_type = f"RANGE SELL at auto high {fmt_price(range_high)}"
                    dxy_msg = f"📦 RANGING M15 - ADX {adx_val:.1f} | AutoRange {fmt_price(range_low)}-{fmt_price(range_high)} -> mean reversion to mid {fmt_price(range_mid)}"
            else:
                print(f"{name}: Ranging but no valid auto range")
                continue

        print(f"{name} {fmt_price(cur)} EMA {fmt_price(ema_now)} {'UP' if up else 'DOWN'} Buy:{base_buy} Sell:{base_sell} ATR:{fmt_price(atr)} Mode:{signal_type}")

        if buy_signal or sell_signal:
            side = "BUY" if buy_signal else "SELL"
            emoji_side = "🟢🔥 BUY" if side == "BUY" else "🔴💥 SELL"
            
            # TP/SL differs for trending vs ranging
            if not ranging:
                # TRENDING TP (like silver 57.735 etc)
                if side == "BUY":
                    sl = cur - 1.2*atr; tp1 = cur + 1.5*atr; tp2 = cur + 2.0*atr; tp3 = cur + 2.5*atr; tp4 = cur + 3.0*atr
                else:
                    sl = cur + 1.2*atr; tp1 = cur - 1.5*atr; tp2 = cur - 2.0*atr; tp3 = cur - 2.5*atr; tp4 = cur - 3.0*atr
            else:
                # RANGING TP - only to mid, smaller
                if side == "BUY":
                    sl = auto_range["low"] - atr*0.5
                    tp1 = auto_range["mid"]
                    tp2 = auto_range["high"] - (auto_range["high"]-auto_range["mid"])*0.3
                    tp3 = auto_range["high"]
                    tp4 = auto_range["high"]
                else:
                    sl = auto_range["high"] + atr*0.5
                    tp1 = auto_range["mid"]
                    tp2 = auto_range["low"] + (auto_range["mid"]-auto_range["low"])*0.3
                    tp3 = auto_range["low"]
                    tp4 = auto_range["low"]

            active[name] = {"side": side, "entry": cur, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "stage": 0, "time": str(datetime.now(timezone.utc))}
            save_trades(active)

            msg = f"""{emoji_side} {name} v10.9 {signal_type} ✅
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY: {fmt_price(cur)}
🔍 CRT: {'✅ YES' if (bull_crt or bear_crt) else '❌ NO'} | CSD: {'✅ YES' if (bull_csd or bear_csd) else '❌ NO'} 💪 {bp*100:.0f}%
📊 EMA13: {fmt_price(ema_now)} {'📈 UP ✅' if up else '📉 DOWN ✅'}
⚡ Power: {(bulls_now if side == 'BUY' else bears_now):.4f} {'🟢' if (bulls_ok or bears_ok) else '🔴'} ✅
📈 ADX: {adx_val:.1f} {'📦 RANGING' if ranging else '🚀 TRENDING'} | BB: {bb_width:.2f}%
📦 AutoRange {fmt_price(auto_range['low'])} - {fmt_price(auto_range['high'])} ({auto_range['high_touches']}/{auto_range['low_touches']} touches) Valid:{auto_range['is_valid']}
{dxy_msg}
📏 ATR: {fmt_price(atr)}

🛑 SL: {fmt_price(sl)}
🎯 TP1: {fmt_price(tp1)} {'-> BE' if not ranging else '-> MID'}
🎯 TP2: {fmt_price(tp2)} {'-> Trail TP1' if not ranging else '-> Range High/Low'}
🎯 TP3: {fmt_price(tp3)}
🎯 TP4: {fmt_price(tp4)}

⏱️ M15 + Auto Range (NO HARDCODE) + 6s ⏳
{CONTACT} {BRAND} 🚀🌟💵"""
            send(msg, is_buy=buy_signal)

    except Exception as e:
        print(f"Scan {name}: {e}")

print("✅ v10.9 M15 AUTO RANGE - DYNAMIC PAIR PRICE, NO 105.540 HARDCODE 🎉🚀💰")