import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timezone
import time, json, os

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND = "FXMEGA UG"
CONTACT = "0700848808"
TRADE_FILE = "active_trades.json"

# === FIXED FEED: SPOT not FUTURES ===
PAIRS = {
    "BTC-USD": "BITCOIN",
    "ETH-USD": "ETHEREUM",
    "SOL-USD": "SOLANA",
    "BNB-USD": "BNB",
    "XRP-USD": "XRP",
    "DOGE-USD": "DOGECOIN",
    "XAUUSD=X": "GOLD",   # was GC=F -> now matches your 4143 chart
    "XAGUSD=X": "SILVER", # was SI=F
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY"
}
DXY_SYMBOL = "DX-Y.NYB"

def send(msg, is_buy=True):
    try:
        if "BUY" in msg and "SIGNAL" in msg:
            title = "BUY SIGNAL"; tag = "moneybag"
        elif "SELL" in msg and "SIGNAL" in msg:
            title = "SELL SIGNAL"; tag = "money_with_wings"
        else:
            title = "BE/TRAIL ALERT"; tag = "rocket"
        requests.post(NTFY_URL, data=msg.encode('utf-8'),
                      headers={"Title": f"{title} - {BRAND}","Priority": "high","Tags": tag,"Content-Type": "text/plain; charset=utf-8"}, timeout=10)
        print(f"SENT: {msg[:100]}")
        time.sleep(6)
    except Exception as e:
        print(f"Send error: {e}"); time.sleep(6)

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
            if -60 <= (et - now).total_seconds() / 60 <= 60:
                c = ev.get("country", "").strip()
                if c: blocked.add(c)
                print(f"RED NEWS BLOCK: {c} {ev.get('title','')} diff {(et-now).total_seconds()/60:.0f}min")
    except Exception as e:
        print(f"News error: {e}")
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

def get_dxy():
    try:
        df = yf.download(DXY_SYMBOL, period="5d", interval="15m", auto_adjust=True, progress=False)
        if df.empty:
            df = yf.download("DX=F", period="5d", interval="15m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        close = df['Close']; ema = close.ewm(span=13).mean()
        ema_now = f(ema.iloc[-2]); ema_prev = f(ema.iloc[-3]); cur = f(close.iloc[-2])
        return cur, ema_now, cur < ema_now, cur > ema_now, ema_now > ema_prev, ema_now < ema_prev
    except Exception as e:
        print(f"DXY error: {e}")
        return None, None, False, False, False, False

# === 1. AUTO BE + TRAILING (use live price) ===
active = load_trades()
print(f"Active trades: {len(active)}")
for sym, name in PAIRS.items():
    if name not in active: continue
    if "USD=X" in sym and is_weekend(): continue
    try:
        df = yf.download(sym, period="1d", interval="15m", auto_adjust=True, progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        cur = f(df['Close'].iloc[-1]) # live for trail
        t = active[name]; side = t['side']; entry = t['entry']; stage = t.get('stage', 0)
        tp1 = t['tp1']; tp2 = t['tp2']; tp3 = t['tp3']; tp4 = t['tp4']
        hit_tp1 = (cur >= tp1) if side == "BUY" else (cur <= tp1)
        hit_tp2 = (cur >= tp2) if side == "BUY" else (cur <= tp2)
        hit_tp3 = (cur >= tp3) if side == "BUY" else (cur <= tp3)
        hit_tp4 = (cur >= tp4) if side == "BUY" else (cur <= tp4)
        if hit_tp4:
            send(f"🏁🎉 {name} TP4 HIT - CLOSE ALL! {side} {fmt_price(tp4)} at {fmt_price(cur)} {CONTACT} {BRAND}", is_buy=side=="BUY")
            del active[name]; save_trades(active); continue
        if hit_tp3 and stage < 3:
            send(f"🔒➡️ {name} TRAIL TO TP2 TP3 {fmt_price(tp3)} HIT! Move SL {fmt_price(t['sl'])} ➡️ {fmt_price(tp2)} {CONTACT} {BRAND}", is_buy=side=="BUY")
            t['sl']=tp2; t['stage']=3; active[name]=t; save_trades(active); continue
        if hit_tp2 and stage < 2:
            send(f"🔒➡️ {name} TRAIL TO TP1 TP2 {fmt_price(tp2)} HIT at {fmt_price(cur)} SL->{fmt_price(tp1)} {CONTACT} {BRAND}", is_buy=side=="BUY")
            t['sl']=tp1; t['stage']=2; active[name]=t; save_trades(active); continue
        if hit_tp1 and stage < 1:
            send(f"🔒✨ {name} AUTO BE TRIGGERED TP1 {fmt_price(tp1)} HIT at {fmt_price(cur)} MOVE SL TO BE {fmt_price(entry)} {CONTACT} {BRAND}", is_buy=side=="BUY")
            t['sl']=entry; t['stage']=1; active[name]=t; save_trades(active); continue
    except Exception as e:
        print(f"Trail {name}: {e}")

# === 2. NEW SIGNALS - NO REPAINT ===
blocked = get_red_news()
dxy_cur, dxy_ema, dxy_below, dxy_above, dxy_up, dxy_down = get_dxy()
print(f"DXY {dxy_cur} EMA {dxy_ema} Below:{dxy_below} Down:{dxy_down} Above:{dxy_above} Up:{dxy_up}")
print(f"Blocked news: {blocked}")

for sym, name in PAIRS.items():
    if name in active:
        print(f"{name}: in trade skip"); continue
    if "USD=X" in sym and is_weekend():
        print(f"{name}: weekend closed"); continue
    if blocked:
        print(f"{name}: BLOCKED by RED NEWS {blocked} 60min - SKIP ALL"); continue

    try:
        df = yf.download(sym, period="5d", interval="15m", auto_adjust=True, progress=False)
        df_d = yf.download(sym, period="10d", interval="1d", auto_adjust=True, progress=False)
        if df.empty or len(df) < 100: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(df_d.columns, pd.MultiIndex): df_d.columns = df_d.columns.get_level_values(0)

        close = df['Close']; high = df['High']; low = df['Low']; open_ = df['Open']

        # NO REPAINT: use CLOSED candle [-2]
        cur = f(close.iloc[-2])
        cur_live = f(close.iloc[-1])
        hnow = f(high.iloc[-2])
        lnow = f(low.iloc[-2])
        open_sig = f(open_.iloc[-2])
        h_prev2 = f(high.iloc[-3])
        l_prev2 = f(low.iloc[-3])

        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
        atr_raw = f(tr.rolling(14).mean().iloc[-2])

        ema13 = close.ewm(span=13).mean()
        ema_now = f(ema13.iloc[-2]); ema_prev = f(ema13.iloc[-3])
        up = ema_now > ema_prev; down = ema_now < ema_prev

        atr = atr_raw
        min_atr = cur * 0.005
        if atr < min_atr: atr = min_atr
        if cur < 1.0 and atr < cur * 0.01: atr = cur * 0.01
        if atr == 0 or atr is None: atr = cur * 0.01

        pdh = f(df_d['High'].iloc[-2]); pdl = f(df_d['Low'].iloc[-2]); crt50 = (pdh+pdl)/2
        bull_crt = lnow < pdl and cur > pdl and cur > crt50
        bear_crt = hnow > pdh and cur < pdh and cur < crt50

        body = abs(cur - open_sig); rng = hnow - lnow
        bp = body/rng if rng > 0 else 0
        bull_csd = cur > open_sig and bp > 0.6 and cur > h_prev2
        bear_csd = cur < open_sig and bp > 0.6 and cur < l_prev2

        bulls_now = hnow - ema_now; bulls_prev = h_prev2 - ema_prev
        bears_now = lnow - ema_now; bears_prev = l_prev2 - ema_prev
        bulls_ok = (bulls_prev < 0 and bulls_now > 0) or bulls_now > 0
        bears_ok = (bears_prev > 0 and bears_now < 0) or bears_now < 0

        base_buy = (bull_crt or bull_csd) and cur > ema_now and up and bulls_ok
        base_sell = (bear_crt or bear_csd) and cur < ema_now and down and bears_ok

        if name == "GOLD":
            if dxy_cur is None: print("GOLD skip DXY fail"); continue
            buy_signal = base_buy and dxy_below and dxy_down
            sell_signal = base_sell and dxy_above and dxy_up
            dxy_msg = f"💵 DXY {fmt_price(dxy_cur)} {'📉 BELOW+DOWN✅' if (dxy_below and dxy_down) else '📈 ABOVE+UP✅' if (dxy_above and dxy_up) else '❌ FAIL'}"
        else:
            buy_signal = base_buy; sell_signal = base_sell; dxy_msg = "✨ No DXY needed"

        print(f"{name} {fmt_price(cur)} (live {fmt_price(cur_live)}) EMA {fmt_price(ema_now)} {'UP' if up else 'DOWN'} Buy:{base_buy} Sell:{base_sell} ATR:{fmt_price(atr)}")

        if buy_signal or sell_signal:
            side = "BUY" if buy_signal else "SELL"
            emoji_side = "🟢🔥 BUY" if side == "BUY" else "🔴💥 SELL"
            entry = cur  # entry = closed candle price = matches MT5
            if side == "BUY":
                sl = entry - 1.2*atr; tp1 = entry + 1.5*atr; tp2 = entry + 2.0*atr; tp3 = entry + 2.5*atr; tp4 = entry + 3.0*atr
            else:
                sl = entry + 1.2*atr; tp1 = entry - 1.5*atr; tp2 = entry - 2.0*atr; tp3 = entry - 2.5*atr; tp4 = entry - 3.0*atr

            active[name] = {"side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "stage": 0, "time": str(datetime.now(timezone.utc))}
            save_trades(active)

            msg = f"""{emoji_side} {name} v10.10 FIXED FEED {'+DXY 💵' if name == 'GOLD' else ''} ✅
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY: {fmt_price(entry)} (closed M15 matches MT5)
🔍 CRT: {'✅ YES' if (bull_crt or bear_crt) else '❌ NO'} | CSD: {'✅ YES' if (bull_csd or bear_csd) else '❌ NO'} 💪 {bp*100:.0f}%
📊 EMA13: {fmt_price(ema_now)} {'📈 UP ✅' if up else '📉 DOWN ✅'}
⚡ Power: {(bulls_now if side == 'BUY' else bears_now):.4f} {'🟢' if (bulls_ok or bears_ok) else '🔴'} ✅
{dxy_msg}
📏 ATR: {fmt_price(atr)}

🛑 SL: {fmt_price(sl)} (1.2x ATR)
🎯 TP1: {fmt_price(tp1)} (1.5x) -> 🔒 BE AUTO 🛡️
🎯 TP2: {fmt_price(tp2)} (2.0x) -> 🔒 Trail TP1 📈
🎯 TP3: {fmt_price(tp3)} (2.5x) -> 🔒 Trail TP2 💰
🎯 TP4: {fmt_price(tp4)} (3.0x) -> 🏁 CLOSE 🎉

⏱️ M15 CLOSED + Spot Feed + RedNews ALL + 6s ⏳
{CONTACT} {BRAND} 🚀🌟💵"""
            send(msg, is_buy=buy_signal)

    except Exception as e:
        print(f"Scan {name}: {e}")

print("✅ v10.10 FIXED FEED - SPOT XAUUSD + NO REPAINT + RED NEWS ALL + MATCHES MT5 CHART 🎉🚀💰")