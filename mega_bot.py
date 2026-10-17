import json, os, requests, pandas as pd
from datetime import datetime
import pytz, yfinance as yf

PHONE = "256788408267"
CALLMEBOT_API = "YOUR_KEY_HERE"  # <--- PUT YOUR REAL KEY
LAST_FILE = "mega_last_signal.json"

PAIRS = {
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "GBPJPY": "GBPJPY=X",
    "US30": "^DJI",
    "NAS100": "^IXIC",
    "BTCUSD": "BTC-USD"
}

def is_weekend():
    tz = pytz.timezone('Africa/Kampala')
    return datetime.now(tz).weekday() >= 5

def get_rsi(s, p=14):
    d = s.diff()
    gain = d.where(d>0,0).rolling(p).mean()
    loss = -d.where(d<0,0).rolling(p).mean()
    return 100 - (100/(1+gain/loss.replace(0,0.0001)))

def get_atr(df, p=14):
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([hl,hc,lc], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def send(msg):
    try:
        url = "https://api.callmebot.com/whatsapp.php"
        requests.get(url, params={"phone":PHONE,"text":msg,"apikey":CALLMEBOT_API}, timeout=25)
        print(f"Sent signal")
    except Exception as e:
        print(e)

def load_last():
    if not os.path.exists(LAST_FILE): return {}
    try:
        with open(LAST_FILE,'r') as f: return json.load(f)
    except: return {}
def save_last(d):
    with open(LAST_FILE,'w') as f: json.dump(d,f)

def analyze(name, ticker, gold_cache):
    df = yf.download(ticker, period="10d", interval="1h", progress=False)
    if df.empty or len(df) < 100: return None
    close = df['Close'].iloc[:,0] if isinstance(df.columns, pd.MultiIndex) else df['Close']
    close = pd.Series(close).dropna()
    
    # Clean columns for ATR
    if isinstance(df.columns, pd.MultiIndex):
        df_c = pd.DataFrame()
        df_c['High'] = df['High'].iloc[:,0]
        df_c['Low'] = df['Low'].iloc[:,0]
        df_c['Close'] = df['Close'].iloc[:,0]
    else:
        df_c = df

    price = float(close.iloc[-1])
    ema20 = float(close.ewm(20).mean().iloc[-1])
    ema50 = float(close.ewm(50).mean().iloc[-1])
    ema200 = float(close.ewm(200).mean().iloc[-1])
    rsi = float(get_rsi(close).iloc[-1])
    atr = float(get_atr(df_c).iloc[-1]) if not pd.isna(get_atr(df_c).iloc[-1]) else price*0.005

    sig = None
    # --- PAIR SPECIFIC BEST STRATEGY ---
    if name == "GOLD":
        if price < ema20 and ema20 < ema50 and 30 < rsi < 44:
            sig = "SELL"
        elif price > ema20 and ema20 > ema50 and 56 < rsi < 70:
            sig = "BUY"
    elif name == "SILVER":
        gold_ema = float(gold_cache.ewm(20).mean().iloc[-1])
        gold_down = float(gold_cache.iloc[-1]) < gold_ema
        gold_up = not gold_down
        if price < ema20 and gold_down and 25 < rsi < 45:
            sig = "SELL"
        elif price > ema20 and gold_up and 55 < rsi < 75:
            sig = "BUY"
    elif name in ["EURUSD","GBPUSD"]:
        if price < ema50 < ema200 and rsi < 46:
            sig = "SELL"
        elif price > ema50 > ema200 and rsi > 54:
            sig = "BUY"
    elif name in ["USDJPY","GBPJPY"]:
        if price < ema20 and ema20 < ema50 and rsi < 42:
            sig = "SELL"
        elif price > ema20 and ema20 > ema50 and rsi > 58:
            sig = "BUY"
    else: # US30, NAS100, BTCUSD
        if price < ema20 and rsi > 68:
            sig = "SELL"
        elif price > ema20 and ema50 < ema20 and 52 < rsi < 68:
            sig = "BUY"

    if not sig: return None

    # SL/TP2 based on pair volatility
    if name in ["GOLD","SILVER"]:
        sl = price + atr*1.5 if sig=="SELL" else price - atr*1.5
        tp1 = price - atr*1.8 if sig=="SELL" else price + atr*1.8
        tp2 = price - atr*3.2 if sig=="SELL" else price + atr*3.2
    else:
        sl = price*1.0025 if sig=="SELL" else price*0.9975
        tp1 = price*0.9985 if sig=="SELL" else price*1.0015
        tp2 = price*0.997 if sig=="SELL" else price*1.003
        if "JPY" in name:
            sl = price*1.003 if sig=="SELL" else price*0.997
            tp1 = price*0.998 if sig=="SELL" else price*1.002
            tp2 = price*0.996 if sig=="SELL" else price*1.004

    prec = 3 if name in ["GOLD","SILVER","US30","NAS100"] else 5
    if name == "BTCUSD": prec = 2

    reason = "Silver EMA + Gold DOWN" if name=="SILVER" and sig=="SELL" else f"{name} {'EMA Trend' if name in ['GOLD','EURUSD','GBPUSD'] else 'Trend Pullback' if 'JPY' in name else 'Momentum'}"

    return {
        "symbol":name,"type":sig,
        "entry":round(price,prec),"sl":round(sl,prec),
        "tp1":round(tp1,prec),"tp2":round(tp2,prec),
        "rsi":round(rsi,1),"reason":reason,"est":"68-75%"
    }

def main():
    if is_weekend():
        print("Weekend - Forex closed")
        return

    g = yf.download("GC=F", period="10d", interval="1h", progress=False)
    gold_cache = pd.Series((g['Close'].iloc[:,0] if isinstance(g.columns, pd.MultiIndex) else g['Close']).dropna())

    last = load_last()
    tz = pytz.timezone('Africa/Kampala')
    tstr = datetime.now(tz).strftime("%H:%M %d/%m")

    for name, ticker in PAIRS.items():
        data = analyze(name, ticker, gold_cache)
        if not data: continue

        sig_id = f"{data['symbol']}_{data['type']}_{data['entry']}"
        if last.get(name) == sig_id:
            print(f"Duplicate blocked {sig_id}")
            continue

        icon = "🔴" if data['type']=="SELL" else "🟢"
        msg = f"""{icon} FX MEGA UG - {data['symbol']} {data['type']} - Gold Corr
🎯 ENTRY: {data['entry']}
🔴 SL: {data['sl']}
✅ TP1: {data['tp1']}
✅ TP2: {data['tp2']}
📊 {data['reason']} | RSI:{data['rsi']} | Est {data['est']}
🕒 {tstr}
FXMEGA UG • 0700848808"""

        send(msg)
        last[name] = sig_id
        save_last(last)
        print(f"SENT {sig_id}")

if __name__ == "__main__":
    main()
