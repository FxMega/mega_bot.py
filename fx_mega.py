import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
import time, json, os
import numpy as np

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND = "FXMEGA UG"
CONTACT = "📞 0700848808"
TRADE_FILE = "active_trades.json"
HISTORY_FILE = "signals_history.json"

PAIRS = {
    "BTC-USD": "BITCOIN", "ETH-USD": "ETHEREUM", "SOL-USD": "SOLANA",
    "BNB-USD": "BNB", "XRP-USD": "XRP", "DOGE-USD": "DOGECOIN",
    "ADA-USD": "CARDANO", "AVAX-USD": "AVALANCHE", "LINK-USD": "CHAINLINK",
    "LTC-USD": "LITECOIN", "DOT-USD": "POLKADOT", "POL-USD": "POLYGON",
    "GC=F": "GOLD", "SI=F": "SILVER",
    "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD", "USDJPY=X": "USDJPY",
    "USDCHF=X": "USDCHF", "AUDUSD=X": "AUDUSD", "USDCAD=X": "USDCAD",
    "NZDUSD=X": "NZDUSD", "EURJPY=X": "EURJPY", "GBPJPY=X": "GBPJPY",
    "EURGBP=X": "EURGBP"
}
DXY_SYMBOL = "DX-Y.NYB"
BINANCE_MAP = {
    "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "SOL-USD": "SOLUSDT",
    "BNB-USD": "BNBUSDT", "XRP-USD": "XRPUSDT", "DOGE-USD": "DOGEUSDT",
    "ADA-USD": "ADAUSDT", "AVAX-USD": "AVAXUSDT", "LINK-USD": "LINKUSDT",
    "LTC-USD": "LTCUSDT", "DOT-USD": "DOTUSDT", "POL-USD": "POLUSDT"
}

def send(msg, title="FXMEGA UG"):
    try:
        requests.post(NTFY_URL, data=msg.encode('utf-8'),
            headers={"Title": title, "Priority": "high", "Tags": "chart", "Content-Type": "text/plain; charset=utf-8"}, timeout=10)
        print(f"✅ SENT: {title}")
        time.sleep(5)
    except Exception as e: print(f"❌ Send error: {e}")

def load_trades():
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}
def save_trades(tr):
    with open(TRADE_FILE, 'w') as f: json.dump(tr, f, indent=2)
def log_signal_history(name, side, entry, sl, tp1, tp2, tp3, tp4, atr, rsi, ob):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: history = json.load(f)
        except: history = []
    history.append({"time": str(datetime.now(timezone.utc)), "pair": name, "side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "atr": atr, "rsi": rsi, "ob": ob})
    history = history[-1500:]
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE,'r') as f: return json.load(f)
        except: return []
    return []

def f(x):
    try:
        if hasattr(x, 'iloc'): return float(x.iloc[0])
        return float(x)
    except: return float(x)
def fmt_price(p, ref):
    if ref < 1: return f"{p:.5f}"
    elif ref < 10: return f"{p:.4f}"
    elif ref < 100: return f"{p:.3f}"
    else: return f"{p:.2f}"

def get_forex_live_yahoo(sym, fallback):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4).json()
        price = float(r['chart']['result'][0]['meta']['regularMarketPrice'])
        if price > 0 and abs(price - fallback)/fallback < 0.015: return price
    except: pass
    return None
def get_live_price(sym, fallback):
    if sym in BINANCE_MAP:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={BINANCE_MAP[sym]}", timeout=3).json()
            price = float(r['price'])
            if price > 0: return price
        except: pass
    if sym in ["GC=F", "SI=F"]:
        try:
            metal = "XAU" if sym == "GC=F" else "XAG"
            r = requests.get(f"https://api.gold-api.com/price/{metal}", timeout=4).json()
            price = float(r['price'])
            if metal == "XAU": price *= 1.003
            if price > 0: return price
        except: pass
    if "=" in sym:
        live = get_forex_live_yahoo(sym, fallback)
        if live: return live
    try:
        live = yf.Ticker(sym).fast_info.get('last_price')
        if live and live > 0: return float(live)
    except: pass
    return fallback

def is_weekend(): return datetime.now(timezone.utc).weekday() >= 5
def get_red_news():
    blocked=set()
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=10).json()
        now=datetime.now(timezone.utc)
        for ev in r:
            if ev.get("impact")!="High": continue
            try: et=datetime.fromisoformat(ev.get("date").replace("Z","+00:00"))
            except: continue
            if -30 <= (et-now).total_seconds()/60 <= 60:
                c=ev.get("country","").strip()
                if c: blocked.add(c)
    except: pass
    return blocked
def get_dxy():
    try:
        df=yf.download(DXY_SYMBOL, period="5d", interval="15m", auto_adjust=True, progress=False)
        if df.empty: df=yf.download("DX=F", period="5d", interval="15m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        close=df['Close']; ema=close.ewm(span=13).mean()
        return f(close.iloc[-1]), f(ema.iloc[-1]), f(close.iloc[-1])<f(ema.iloc[-1]), f(close.iloc[-1])>f(ema.iloc[-1]), f(ema.iloc[-1])>f(ema.iloc[-2]), f(ema.iloc[-1])<f(ema.iloc[-2])
    except: return None,None,False,False,False,False

def get_htf_trend(sym):
    try:
        dfh = yf.download(sym, period="20d", interval="1h", auto_adjust=True, progress=False)
        if dfh.empty or len(dfh) < 200: return 0
        if isinstance(dfh.columns, pd.MultiIndex): dfh.columns=dfh.columns.get_level_values(0)
        close = dfh['Close']
        ema50 = close.ewm(span=50).mean(); ema200 = close.ewm(span=200).mean()
        e50 = f(ema50.iloc[-1]); e200 = f(ema200.iloc[-1])
        if e50 > e200 * 1.0002: return 1
        if e50 < e200 * 0.9998: return -1
        return 0
    except: return 0

def calc_rsi(series, period=14):
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return f(rsi.iloc[-1]), f(rsi.iloc[-2])
    except: return 50,50

def find_order_block(df, side="BUY"):
    try:
        if len(df) < 25: return None, False
        closes = df['Close']; opens = df['Open']; highs = df['High']; lows = df['Low']
        for i in range(len(df)-5, len(df)-20, -1):
            o = f(opens.iloc[i]); c = f(closes.iloc[i])
            if side == "BUY":
                if c < o:
                    next_high = max([f(highs.iloc[j]) for j in range(i+1, i+4)])
                    if next_high > f(highs.iloc[i]) * 1.0003:
                        ob_low = f(lows.iloc[i]); ob_high = f(highs.iloc[i])
                        cur = f(closes.iloc[-1])
                        atr = f((highs-lows).rolling(14).mean().iloc[-1])
                        if abs(cur - ob_low) < 2.5 * atr or cur <= ob_high * 1.001:
                            return ob_low, True
            else:
                if c > o:
                    next_low = min([f(lows.iloc[j]) for j in range(i+1, i+4)])
                    if next_low < f(lows.iloc[i]) * 0.9997:
                        ob_high = f(highs.iloc[i]); ob_low = f(lows.iloc[i])
                        cur = f(closes.iloc[-1])
                        atr = f((highs-lows).rolling(14).mean().iloc[-1])
                        if abs(cur - ob_high) < 2.5 * atr or cur >= ob_low * 0.999:
                            return ob_high, True
        return None, False
    except:
        return None, False

def was_recent_signal(pair_name, hours=2):
    hist = load_history()
    now = datetime.now(timezone.utc)
    for h in reversed(hist[-20:]):
        if h.get('pair') != pair_name: continue
        try:
            t = datetime.fromisoformat(h['time'].replace('Z','+00:00'))
            if (now - t) < timedelta(hours=hours): return True
        except: continue
    return False

# TRAILING & SCAN
active=load_trades()
print(f"🔵 Active: {len(active)} | 🚀 v11.7 FIXED LTC PUMP - BLOCK RSI<35 SELL")

for sym,name in PAIRS.items():
    if name not in active: continue
    if "=" in sym and is_weekend(): continue
    try:
        df=yf.download(sym, period="1d", interval="15m", auto_adjust=True, progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        cur=get_live_price(sym, f(df['Close'].iloc[-1]))
        t=active[name]; side,entry,stage=t['side'],t['entry'],t.get('stage',0)
        tp1,tp2,tp3,tp4=t['tp1'],t['tp2'],t['tp3'],t['tp4']; sl_now=t['sl']
        hit_sl=(cur<=sl_now) if side=="BUY" else (cur>=sl_now)
        if hit_sl:
            send(f"🛑 {name} SL HIT {fmt_price(sl_now,cur)} at {fmt_price(cur,cur)}", f"SL HIT - {name}")
            del active[name]; save_trades(active); continue
        hit_tp1=(cur>=tp1) if side=="BUY" else (cur<=tp1)
        hit_tp2=(cur>=tp2) if side=="BUY" else (cur<=tp2)
        hit_tp3=(cur>=tp3) if side=="BUY" else (cur<=tp3)
        hit_tp4=(cur>=tp4) if side=="BUY" else (cur<=tp4)
        if hit_tp4:
            send(f"🏁 {name} TP4 HIT CLOSE!", f"TP4 HIT - {name}")
            del active[name]; save_trades(active); continue
        if hit_tp3 and stage<3:
            send(f"🔒 {name} TRAIL TO TP2", f"TRAIL TP2 - {name}")
            t['sl']=tp2; t['stage']=3; active[name]=t; save_trades(active); continue
        if hit_tp2 and stage<2:
            send(f"🔒 {name} TRAIL TO TP1", f"TRAIL TP1 - {name}")
            t['sl']=tp1; t['stage']=2; active[name]=t; save_trades(active); continue
        if hit_tp1 and stage<1:
            send(f"🔒 {name} AUTO BE", f"AUTO BE - {name}")
            t['sl']=entry; t['stage']=1; active[name]=t; save_trades(active); continue
    except Exception as e: print(f"Trail {name}: {e}")

blocked=get_red_news()
dxy_cur,dxy_ema,dxy_below,dxy_above,dxy_up,dxy_down=get_dxy()
signals_sent_this_run=0
MAX_SIGNALS_PER_RUN=3

for sym,name in PAIRS.items():
    if name in active: continue
    if signals_sent_this_run>=MAX_SIGNALS_PER_RUN: break
    if "=" in sym and is_weekend(): continue
    if was_recent_signal(name, hours=2):
        print(f"⏳ Cooldown {name}"); continue
    curr="EUR" if "EUR" in name else "GBP" if "GBP" in name else "JPY" if "JPY" in name else "CHF" if "CHF" in name else "AUD" if "AUD" in name else "CAD" if "CAD" in name else "NZD" if "NZD" in name else "USD"
    if curr in blocked or ("USD" in blocked and name in ["GOLD","SILVER","BITCOIN","ETHEREUM","BNB"]): continue
    try:
        df=yf.download(sym, period="5d", interval="15m", auto_adjust=True, progress=False)
        df_d=yf.download(sym, period="10d", interval="1d", auto_adjust=True, progress=False)
        if df.empty or len(df)<100: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if isinstance(df_d.columns, pd.MultiIndex): df_d.columns=df_d.columns.get_level_values(0)
        close,high,low,open_=df['Close'],df['High'],df['Low'],df['Open']
        tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
        atr_raw=f(tr.rolling(14).mean().iloc[-1])
        ema13=close.ewm(span=13).mean()
        ema_now,ema_prev=f(ema13.iloc[-1]),f(ema13.iloc[-2])
        up,down=ema_now>ema_prev,ema_now<ema_prev
        candle_close=f(close.iloc[-1])
        cur=get_live_price(sym,candle_close)
        hnow,lnow=f(high.iloc[-1]),f(low.iloc[-1])
        min_atr=candle_close*0.0015
        atr=atr_raw if atr_raw>=min_atr else min_atr
        htf=get_htf_trend(sym)
        pdh,pdl=f(df_d['High'].iloc[-2]),f(df_d['Low'].iloc[-2])
        crt50=(pdh+pdl)/2
        bull_crt=lnow<pdl and cur>pdl and cur>crt50
        bear_crt=hnow>pdh and cur<pdh and cur<crt50
        body=abs(cur-f(open_.iloc[-1])); rng=hnow-lnow; bp=body/rng if rng>0 else 0
        bull_csd=cur>f(open_.iloc[-1]) and bp>0.6 and cur>f(high.iloc[-2])
        bear_csd=cur<f(open_.iloc[-1]) and bp>0.6 and cur<f(low.iloc[-2])
        bulls_now=hnow-ema_now; bulls_prev=f(high.iloc[-2])-ema_prev
        bears_now=lnow-ema_now; bears_prev=f(low.iloc[-2])-ema_prev
        bulls_ok=(bulls_prev<0 and bulls_now>0) or bulls_now>0
        bears_ok=(bears_prev>0 and bears_now<0) or bears_now<0
        rsi_now,rsi_prev=calc_rsi(close)
        rsi_bull = rsi_now > 50 and rsi_now > rsi_prev
        rsi_bear = rsi_now < 50 and rsi_now < rsi_prev
        ob_price, ob_found_buy = find_order_block(df, "BUY")
        ob_price_s, ob_found_sell = find_order_block(df, "SELL")

        base_buy=(bull_crt or bull_csd) and cur>ema_now and up and bulls_ok
        base_sell=(bear_crt or bear_csd) and cur<ema_now and down and bears_ok
        base_buy = base_buy and rsi_bull
        base_sell = base_sell and rsi_bear

        # ================= v11.7 FIX FOR LTC CASE - CORRECTLY INDENTED =================
        # 1️⃣ RSI Exhaustion filter - BLOCKS YOUR LTC RSI 20.0 SELL THAT PUMPED TO 60.71
        if base_sell and rsi_now < 35:
            print(f"❌ BLOCK SELL {name} - RSI {rsi_now:.1f} OVERSOLD 🚫 - would pump like LTC 58->60.71")
            base_sell = False
        if base_buy and rsi_now > 65:
            print(f"❌ BLOCK BUY {name} - RSI {rsi_now:.1f} OVERBOUGHT 🚫")
            base_buy = False

        # 2️⃣ Require OB for crypto - fixes "No fresh OB" fake signal
        has_any_ob = ob_found_buy or ob_found_sell
        if name in ["LITECOIN","BITCOIN","ETHEREUM","DOGECOIN","XRP","CHAINLINK","SOLANA","BNB","CARDANO","AVALANCHE","POLKADOT","POLYGON"] and not has_any_ob:
            if rsi_now < 40 or rsi_now > 60:
                print(f"❌ BLOCK {name} - No fresh OB + RSI {rsi_now:.1f} = No institutional level ⛔")
                base_sell = False
                base_buy = False
        # ================= END v11.7 FIX =================

        if base_buy and htf==-1:
            print(f"⛔ HTF BLOCK BUY {name} H1 DOWN"); continue
        if base_sell and htf==1:
            print(f"⛔ HTF BLOCK SELL {name} H1 UP"); continue

        if name=="GOLD":
            if dxy_cur is None: continue
            buy_signal=base_buy and dxy_below and dxy_down
            sell_signal=base_sell and dxy_above and dxy_up
        else:
            buy_signal,sell_signal=base_buy,base_sell

        if buy_signal or sell_signal:
            side="BUY" if buy_signal else "SELL"
            emoji_side="🟢🔥 BUY" if side=="BUY" else "🔴💥 SELL"
            if sym in ["GC=F","SI=F"]: sl_mult=1.8
            elif sym in BINANCE_MAP: sl_mult=2.0
            else: sl_mult=1.5
            if side=="BUY":
                sl=cur-sl_mult*atr; tp1=cur+1.5*atr; tp2=cur+2.0*atr; tp3=cur+2.5*atr; tp4=cur+3.0*atr
                zone_low=cur-0.3*atr; zone_high=cur+0.2*atr
                ob_info=f"OB: {fmt_price(ob_price,cur)} ✅" if ob_found_buy else "OB: No fresh OB ❌"
            else:
                sl=cur+sl_mult*atr; tp1=cur-1.5*atr; tp2=cur-2.0*atr; tp3=cur-2.5*atr; tp4=cur-3.0*atr
                zone_low=cur-0.2*atr; zone_high=cur+0.3*atr
                ob_info=f"OB: {fmt_price(ob_price_s,cur)} ✅" if ob_found_sell else "OB: No fresh OB ❌"
            active[name]={"side":side,"entry":cur,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"stage":0,"time":str(datetime.now(timezone.utc))}
            save_trades(active); log_signal_history(name,side,cur,sl,tp1,tp2,tp3,tp4,atr,rsi_now,ob_price if side=="BUY" else ob_price_s)
            source="🟢 BINANCE LIVE" if sym in BINANCE_MAP else "🟡 GOLD-API LIVE" if sym in ["GC=F","SI=F"] else "🔵 YAHOO CHARTS FOREX"
            msg=f"""{emoji_side} {name} v11.7 FIXED ✅
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY ZONE: {fmt_price(zone_low,cur)} - {fmt_price(zone_high,cur)}
👉 NOW {fmt_price(cur,cur)} is BEST (discount) | Valid 30m
📊 RSI: {rsi_now:.1f} {'↑ MOMENTUM' if side=='BUY' else '↓ MOMENTUM'} | {ob_info}
📈 H1 Trend: {'UP' if htf==1 else 'DOWN' if htf==-1 else 'NEUTRAL'} | H1 Filter ON
📏 ATR: {fmt_price(atr,cur)} | 🛑 SL: {fmt_price(sl,cur)} ({sl_mult}x) | 🎯 TP1: {fmt_price(tp1,cur)} | TP2: {fmt_price(tp2,cur)} | TP3: {fmt_price(tp3,cur)} | TP4: {fmt_price(tp4,cur)}
🔍 {source} | BE at TP1 | Trail TP2/TP3 | 2h Cooldown
{CONTACT} {BRAND} 🚀 v11.7 LTC FIX"""
            send(msg, f"{side} - {name} v11.7 RSI+OB {source}")
            signals_sent_this_run+=1
    except Exception as e: print(f"⚠️ Scan {name}: {e}")

print(f"✅ v11.7 DONE - {signals_sent_this_run} signals - FIXED LTC RSI 20 BLOCK")