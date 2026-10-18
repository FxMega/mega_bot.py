import yfinance as yf
import time
import requests
from datetime import datetime, timezone
import pandas as pd

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND_NAME = "FXMEGA UG"
CONTACT_NUMBER = "0700848808"

TRADING_PAIRS_CONFIG = {
    "BTC-USD": {"pair_display_name": "BITCOIN","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "ETH-USD": {"pair_display_name": "ETHEREUM","rsi_buy_threshold": 32,"rsi_sell_threshold": 68,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "SOL-USD": {"pair_display_name": "SOLANA","rsi_buy_threshold": 38,"rsi_sell_threshold": 62,"ema_fast_period": 9,"ema_slow_period": 21,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "BNB-USD": {"pair_display_name": "BNB","rsi_buy_threshold": 42,"rsi_sell_threshold": 78,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","timeframe": "1h","is_forex": False},
    "XRP-USD": {"pair_display_name": "XRP","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "DOGE-USD": {"pair_display_name": "DOGECOIN","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "GC=F": {"pair_display_name": "GOLD","rsi_buy_threshold": 40,"rsi_sell_threshold": 60,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "SI=F": {"pair_display_name": "SILVER","rsi_buy_threshold": 42,"rsi_sell_threshold": 58,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","timeframe": "15m","is_forex": False},
    "EURUSD=X": {"pair_display_name": "EURUSD","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "EUR","timeframe": "15m","is_forex": True},
    "GBPUSD=X": {"pair_display_name": "GBPUSD","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "GBP","timeframe": "15m","is_forex": True},
    "USDJPY=X": {"pair_display_name": "USDJPY","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "JPY","timeframe": "15m","is_forex": True},
}

def is_weekend_forex_closed():
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Mon ... 5=Sat 6=Sun
    return weekday >= 5  # Sat or Sun

def get_red_news_blocked_currencies():
    blocked = set()
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, timeout=10)
        data = r.json()
        now = datetime.now(timezone.utc)
        for ev in data:
            if ev.get("impact") != "High": continue
            try: et = datetime.fromisoformat(ev.get("date").replace("Z", "+00:00"))
            except: continue
            diff = (et - now).total_seconds()/60
            if -30 <= diff <= 60:
                c = ev.get("country","").strip()
                if c: blocked.add(c)
    except: pass
    return blocked

def calculate_rsi_and_ema_indicators(df, fast, slow):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df['Close']
    if isinstance(close, pd.DataFrame): close = close.iloc[:,0]
    close = pd.Series(close).dropna()
    diff = close.diff()
    gains = diff.where(diff>0,0).rolling(14).mean()
    losses = -diff.where(diff<0,0).rolling(14).mean()
    rs = gains/losses
    rsi = 100 - (100/(1+rs))
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    recent_low = close.tail(20).min()
    recent_high = close.tail(20).max()
    def safe_last(s):
        if isinstance(s, pd.DataFrame): v=s.iloc[-1,0]
        else: v=s.iloc[-1]
        if isinstance(v, pd.Series): v=v.iloc[0]
        return float(v)
    return safe_last(rsi), safe_last(ema_fast), safe_last(ema_slow), safe_last(close), float(recent_low), float(recent_high)

def send_alert_message(msg, is_buy=True, is_heartbeat=False):
    try:
        if is_heartbeat: title = "HEARTBEAT - NO SIGNAL"; tags = "zzz"
        else: title = "BUY SIGNAL" if is_buy else "SELL SIGNAL"; tags = "moneybag" if is_buy else "money_with_wings"
        requests.post(NTFY_URL, data=msg.encode('utf-8'), headers={"Title": f"{title} - {BRAND_NAME}","Priority": "default" if is_heartbeat else "high","Tags": tags}, timeout=10)
        print(f"SENT: {msg[:100]}")
    except Exception as e: print(f"FAILED: {e}")

print(f"{BRAND_NAME} v8.4 WEEKEND AWARE STARTING")
weekend_closed = is_weekend_forex_closed()
print(f"Is Weekend? {weekend_closed} - Forex will be skipped if True")
blocked_now = get_red_news_blocked_currencies()
print(f"Blocked: {blocked_now if blocked_now else 'None'}")

signals_found = 0
status_lines = []

for sym, cfg in TRADING_PAIRS_CONFIG.items():
    curr = cfg["currency_affected_by_news"]; name = cfg["pair_display_name"]; tf = cfg["timeframe"]; is_fx = cfg["is_forex"]
    
    # WEEKEND FOREX CLOSED LOGIC
    if is_fx and weekend_closed:
        print(f"{name}: WEEKEND CLOSED - SKIP")
        status_lines.append(f"{name}: WEEKEND CLOSED")
        continue
    
    if curr in blocked_now: status_lines.append(f"{name}: BLOCKED {curr}"); continue
    if "USD" in blocked_now and name in ["GOLD","SILVER","BITCOIN","ETHEREUM","BNB"]: status_lines.append(f"{name}: BLOCKED USD"); continue
    try:
        period = "10d" if tf=="1h" else "5d"
        df = yf.download(sym, period=period, interval=tf, progress=False, auto_adjust=True)
        if df.empty or len(df)<60: status_lines.append(f"{name}: NO DATA"); continue
        rsi, ef, es, price, r_low, r_high = calculate_rsi_and_ema_indicators(df, cfg["ema_fast_period"], cfg["ema_slow_period"])
        print(f"{name} ({tf}) Price={price:.2f} RSI={rsi:.1f} Low={r_low:.2f} High={r_high:.2f}")
        
        # FLAT DATA FILTER - Market closed fake data
        if r_low == r_high or abs(r_high - r_low) < 0.0001:
            print(f"{name}: FLAT DATA Low==High -> SKIP (market closed)")
            status_lines.append(f"{name}: FLAT DATA - SKIP")
            continue
        
        status_lines.append(f"{name} {price:.2f} RSI {rsi:.1f}")
        
        near_support = price <= r_low * 1.015
        near_resistance = price >= r_high * 0.985
        extreme_oversold = rsi < 20
        extreme_overbought = rsi > 80
        
        buy=False; sell=False; reason=""
        
        if extreme_oversold and not is_fx:
            buy=True; reason=f"EXTREME OVERSOLD {rsi:.1f} <20 - REVERSAL"
        elif extreme_overbought and not is_fx:
            sell=True; reason=f"EXTREME OVERBOUGHT {rsi:.1f} >80 - REVERSAL"
        elif name == "BNB":
            if rsi < cfg["rsi_buy_threshold"] and ef>es and not near_resistance:
                buy=True; reason=f"UPTREND RSI {rsi:.1f} < {cfg['rsi_buy_threshold']}"
            elif rsi > cfg["rsi_sell_threshold"] and ef<es and not near_support:
                sell=True; reason=f"DOWNTREND RSI {rsi:.1f} > {cfg['rsi_sell_threshold']}"
        elif name in ["DOGECOIN","USDJPY"]:
            if rsi < cfg["rsi_buy_threshold"] and not near_resistance: buy=True; reason=f"OVERSOLD {rsi:.1f}"
            elif rsi > cfg["rsi_sell_threshold"] and not near_support: sell=True; reason=f"OVERBOUGHT {rsi:.1f}"
        elif name=="GOLD":
            if rsi < cfg["rsi_buy_threshold"] and price>es and not near_resistance: buy=True; reason=f"UPTREND RSI {rsi:.1f}"
            elif rsi > cfg["rsi_sell_threshold"] and price<ef and not near_support: sell=True; reason=f"DOWNTREND RSI {rsi:.1f}"
        else:
            if rsi < cfg["rsi_buy_threshold"] and ef>es and not near_resistance: buy=True; reason=f"UPTREND RSI {rsi:.1f}"
            elif rsi > cfg["rsi_sell_threshold"] and ef<es and not near_support: sell=True; reason=f"DOWNTREND RSI {rsi:.1f}"
        
        entry=price
        if buy:
            sl=entry*0.975 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*0.992 if name in ["GOLD","SILVER"] else entry*0.995
            tp1=entry*1.015 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*1.005 if name in ["GOLD","SILVER"] else entry*1.003
            tp2=entry*1.03 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*1.01 if name in ["GOLD","SILVER"] else entry*1.006
            tp3=entry*1.06 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*1.015 if name in ["GOLD","SILVER"] else entry*1.009
            msg = f"""BUY {name} SIGNAL
ENTRY: {entry:.2f}
TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}
SL: {sl:.2f}
RSI: {rsi:.1f} - {reason}
Timeframe: {tf}
{CONTACT_NUMBER} {BRAND_NAME}"""
            send_alert_message(msg, is_buy=True); signals_found+=1; time.sleep(4)
        elif sell:
            sl=entry*1.025 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*1.008 if name in ["GOLD","SILVER"] else entry*1.005
            tp1=entry*0.985 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*0.995 if name in ["GOLD","SILVER"] else entry*0.997
            tp2=entry*0.97 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*0.99 if name in ["GOLD","SILVER"] else entry*0.994
            tp3=entry*0.94 if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"] else entry*0.985 if name in ["GOLD","SILVER"] else entry*0.991
            msg = f"""SELL {name} SIGNAL
ENTRY: {entry:.2f}
TP1: {tp1:.2f} TP2: {tp2:.2f} TP3: {tp3:.2f}
SL: {sl:.2f}
RSI: {rsi:.1f} - {reason}
Timeframe: {tf}
{CONTACT_NUMBER} {BRAND_NAME}"""
            send_alert_message(msg, is_buy=False); signals_found+=1; time.sleep(4)
    except Exception as e: print(f"Error {name}: {e}")
    time.sleep(1)

if signals_found == 0:
    summary = "\n".join(status_lines[:11])
    note = "Forex CLOSED Weekend" if weekend_closed else "Market Open"
    heartbeat_msg = f"""NO SIGNAL - All WAIT
{summary}
{note}
Next check in 1hr
{CONTACT_NUMBER} {BRAND_NAME}"""
    send_alert_message(heartbeat_msg, is_heartbeat=True)
else:
    print(f"Done - {signals_found} signals sent")
print("v8.4 Completed")