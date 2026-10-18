import yfinance as yf
import time
import requests
from datetime import datetime, timezone
import pandas as pd

# NTFY UNLIMITED - NO LIMITS EVER
NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND_NAME = "FXMEGA UG"
CONTACT_NUMBER = "0700848808"

TRADING_PAIRS_CONFIG = {
    "BTC-USD": {"pair_display_name": "BITCOIN","rsi_buy_threshold": 32,"rsi_sell_threshold": 68,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "BITCOIN uses EMA 20/50 trend filter. BUY only when EMA20 is above EMA50 indicating uptrend AND RSI is below 32 oversold. SELL only when EMA20 is below EMA50 indicating downtrend AND RSI is above 68 overbought."},
    "ETH-USD": {"pair_display_name": "ETHEREUM","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "ETHEREUM RSI 30/70 wider because ETH is more volatile. EMA20/50 for trend."},
    "SOL-USD": {"pair_display_name": "SOLANA","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 9,"ema_slow_period": 21,"currency_affected_by_news": "USD","full_strategy_explanation": "SOLANA fast EMA 9/21 to catch quick moves, RSI 35/65 tight to scalp fast."},
    "BNB-USD": {"pair_display_name": "BNB","rsi_buy_threshold": 38,"rsi_sell_threshold": 62,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "BNB low volatility uses narrow RSI 38/62 to catch small moves, EMA 20/50."},
    "XRP-USD": {"pair_display_name": "XRP","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","full_strategy_explanation": "XRP respects big trend, EMA 50/200, only trades with big trend direction + RSI 30/70."},
    "DOGE-USD": {"pair_display_name": "DOGECOIN","rsi_buy_threshold": 25,"rsi_sell_threshold": 75,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "DOGECOIN meme coin only trade extremes. BUY RSI<25 SELL RSI>75. Ignores EMA."},
    "GC=F": {"pair_display_name": "GOLD","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","full_strategy_explanation": "GOLD EMA 50/200. BUY only if price above EMA200 + RSI<35 dip. SELL only if price below EMA50 + RSI>65."},
    "SI=F": {"pair_display_name": "SILVER","rsi_buy_threshold": 40,"rsi_sell_threshold": 60,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "SILVER choppy RSI 40/60 wider, EMA 20/50 to avoid false breakouts."},
    "EURUSD=X": {"pair_display_name": "EURUSD","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "EUR","full_strategy_explanation": "EURUSD low volatility EMA 50/200 big trend filter + RSI 30/70."},
    "GBPUSD=X": {"pair_display_name": "GBPUSD","rsi_buy_threshold": 32,"rsi_sell_threshold": 68,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "GBP","full_strategy_explanation": "GBPUSD more volatile than EURUSD EMA 20/50 faster RSI 32/68."},
    "USDJPY=X": {"pair_display_name": "USDJPY","rsi_buy_threshold": 25,"rsi_sell_threshold": 75,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "JPY","full_strategy_explanation": "USDJPY trends strongly only trade extremes RSI 25/75 + EMA 50/200."},
}

def get_red_news_blocked_currencies():
    blocked = set()
    try:
        print("Starting RED NEWS check...")
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
                if c:
                    blocked.add(c)
                    print(f"RED NEWS: {c} - {ev.get('title')} in {diff:.0f}min")
    except Exception as e:
        print(f"RED NEWS check failed: {e}")
    return blocked

def calculate_rsi_and_ema_indicators(df, fast, slow):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:,0]
    close = pd.Series(close).dropna()
    diff = close.diff()
    gains = diff.where(diff>0,0).rolling(14).mean()
    losses = -diff.where(diff<0,0).rolling(14).mean()
    rs = gains/losses
    rsi = 100 - (100/(1+rs))
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    def safe_last(s):
        if isinstance(s, pd.DataFrame): v=s.iloc[-1,0]
        else: v=s.iloc[-1]
        if isinstance(v, pd.Series): v=v.iloc[0]
        return float(v)
    return safe_last(rsi), safe_last(ema_fast), safe_last(ema_slow), safe_last(close)

def send_alert_message(msg):
    try:
        r = requests.post(
            NTFY_URL,
            data=msg.encode('utf-8'),
            headers={"Title": "FXMEGA UG SIGNAL","Priority": "high","Tags": "moneybag,chart_with_upwards_trend"},
            timeout=10
        )
        print(f"SENT SUCCESSFULLY to ntfy {NTFY_TOPIC}: {msg[:120]}... Resp: {r.text[:80]}")
    except Exception as e:
        print(f"FAILED ntfy: {e}")

print("=================================================================")
print(f"{BRAND_NAME} v6 NTFY UNLIMITED - STARTING RUN")
print("=================================================================")
blocked_now = get_red_news_blocked_currencies()
print(f"Blocked: {blocked_now if blocked_now else 'None'}")
for sym, cfg in TRADING_PAIRS_CONFIG.items():
    curr = cfg["currency_affected_by_news"]
    name = cfg["pair_display_name"]
    if curr in blocked_now: print(f"{name} SKIPPED RED NEWS {curr}"); continue
    if "USD" in blocked_now and name in ["GOLD","SILVER","BITCOIN","ETHEREUM","BNB"]: print(f"{name} SKIPPED USD RED NEWS"); continue
    try:
        print(f"\n--- ANALYZING {name} ({sym}) ---")
        df = yf.download(sym, period="5d", interval="15m", progress=False, auto_adjust=True)
        if df.empty or len(df)<60: print(f"{name} NO DATA"); continue
        rsi, ef, es, price = calculate_rsi_and_ema_indicators(df, cfg["ema_fast_period"], cfg["ema_slow_period"])
        print(f"{name} CURRENT: Price={price:.2f} RSI={rsi:.1f} EMA{cfg['ema_fast_period']}={ef:.2f} EMA{cfg['ema_slow_period']}={es:.2f}")
        buy=False; sell=False; reason=""
        if name in ["DOGECOIN","USDJPY"]:
            if rsi < cfg["rsi_buy_threshold"]: buy=True; reason=f"EXTREME OVERSOLD RSI {rsi:.1f} < {cfg['rsi_buy_threshold']}"
            elif rsi > cfg["rsi_sell_threshold"]: sell=True; reason=f"EXTREME OVERBOUGHT RSI {rsi:.1f} > {cfg['rsi_sell_threshold']}"
        elif name=="GOLD":
            if rsi < cfg["rsi_buy_threshold"] and price>es: buy=True; reason=f"GOLD UPTREND Price {price:.2f}>EMA200 {es:.2f} RSI {rsi:.1f}"
            elif rsi > cfg["rsi_sell_threshold"] and price<ef: sell=True; reason=f"GOLD DOWNTREND Price {price:.2f}<EMA50 {ef:.2f} RSI {rsi:.1f}"
        else:
            if rsi < cfg["rsi_buy_threshold"] and ef>es: buy=True; reason=f"UPTREND EMA{cfg['ema_fast_period']} {ef:.2f}>EMA{cfg['ema_slow_period']} {es:.2f} RSI {rsi:.1f}"
            elif rsi > cfg["rsi_sell_threshold"] and ef<es: sell=True; reason=f"DOWNTREND EMA{cfg['ema_fast_period']} {ef:.2f}<EMA{cfg['ema_slow_period']} {es:.2f} RSI {rsi:.1f}"
        entry=price
        if buy:
            if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"]: sl=entry*0.975; tp1=entry*1.015; tp2=entry*1.03; tp3=entry*1.06
            elif name in ["GOLD","SILVER"]: sl=entry*0.992; tp1=entry*1.005; tp2=entry*1.01; tp3=entry*1.015
            else: sl=entry*0.995; tp1=entry*1.003; tp2=entry*1.006; tp3=entry*1.009
            msg=f"{BRAND_NAME}\n{name} BUY SIGNAL\nENTRY: {entry:.2f}\nTP1 {tp1:.2f}\nTP2 {tp2:.2f}\nTP3 {tp3:.2f}\nSL {sl:.2f}\nRSI {rsi:.1f}\nREASON: {reason}\nRED NEWS: Safe\n{CONTACT_NUMBER}"
            send_alert_message(msg); time.sleep(6)
        elif sell:
            if name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"]: sl=entry*1.025; tp1=entry*0.985; tp2=entry*0.97; tp3=entry*0.94
            elif name in ["GOLD","SILVER"]: sl=entry*1.008; tp1=entry*0.995; tp2=entry*0.99; tp3=entry*0.985
            else: sl=entry*1.005; tp1=entry*0.997; tp2=entry*0.994; tp3=entry*0.991
            msg=f"{BRAND_NAME}\n{name} SELL SIGNAL\nENTRY: {entry:.2f}\nTP1 {tp1:.2f}\nTP2 {tp2:.2f}\nTP3 {tp3:.2f}\nSL {sl:.2f}\nRSI {rsi:.1f}\nREASON: {reason}\nRED NEWS: Safe\n{CONTACT_NUMBER}"
            send_alert_message(msg); time.sleep(6)
        else: print(f"{name} -> WAIT RSI {rsi:.1f}")
    except Exception as e: print(f"Error {name}: {e}")
    print("Waiting 1 sec..."); time.sleep(1)
print("=================================================================")
print("FXMEGA UG v6 NTFY UNLIMITED - Completed successfully")
print("=================================================================")