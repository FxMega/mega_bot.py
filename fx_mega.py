import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timezone
import time
import json
import os

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND = "FXMEGA UG"
CONTACT = "📞 0700848808"
TRADE_FILE = "active_trades.json"
HISTORY_FILE = "signals_history.json"

PAIRS = {
    "BTC-USD": "BITCOIN", "ETH-USD": "ETHEREUM", "SOL-USD": "SOLANA",
    "BNB-USD": "BNB", "XRP-USD": "XRP", "DOGE-USD": "DOGECOIN",
    "GC=F": "GOLD", "SI=F": "SILVER", "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD", "USDJPY=X": "USDJPY"
}
DXY_SYMBOL = "DX-Y.NYB"

def send(msg, title="FXMEGA UG"):
    try:
        requests.post(NTFY_URL, data=msg.encode('utf-8'),
            headers={"Title": title, "Priority": "high", "Tags": "chart", "Content-Type": "text/plain; charset=utf-8"}, timeout=10)
        print(f"SENT: {title}")
        time.sleep(6)
    except Exception as e:
        print(f"Send error: {e}")

def load_trades():
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_trades(tr):
    with open(TRADE_FILE, 'w') as f: json.dump(tr, f, indent=2)

def log_signal_history(name, side, entry, sl, tp1, tp2, tp3, tp4, atr):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: history = json.load(f)
        except: history = []
    history.append({"time": str(datetime.now(timezone.utc)), "pair": name, "side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "atr": atr})
    history = history[-1000:]
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)

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

def get_live_price(sym, fallback):
    try:
        live = yf.Ticker(sym).fast_info.get('last_price')
        if live and live > 0 and abs(live - fallback) / fallback < 0.02:
            return float(live)
    except: pass
    return fallback

# === DAILY REPORT v11.0 ===
def maybe_send_daily_report():
    now_utc = datetime.now(timezone.utc)
    # 22:00 Kampala = 19:00 UTC (EAT is UTC+3)
    if now_utc.hour == 19 and now_utc.minute < 15:
        if not os.path.exists(HISTORY_FILE):
            send("📊 DAILY REPORT v11.0\nNo signals today yet.\nHistory file not found.", "DAILY REPORT - FXMEGA UG")
            return
        try:
            with open(HISTORY_FILE, 'r') as f: history = json.load(f)
        except: history = []
        today_str = now_utc.date().isoformat()
        today_signals = [h for h in history if today_str in h.get('time','')]
        if not today_signals:
            today_signals = history[-10:] # last 10 if none today
        
        total = len(today_signals)
        buys = len([s for s in today_signals if s['side']=='BUY'])
        sells = total - buys
        pairs_count = {}
        for s in today_signals:
            pairs_count[s['pair']] = pairs_count.get(s['pair'], 0) + 1
        
        top_pair = max(pairs_count, key=pairs_count.get) if pairs_count else "None"
        
        msg = f"""📊📈 FXMEGA UG DAILY REPORT v11.0 📉📊
📅 Date: {now_utc.date()} (EAT 22:00)

📈 Total Signals Today: {total}
🟢 BUY: {buys} | 🔴 SELL: {sells}
🏆 Top Pair: {top_pair} ({pairs_count.get(top_pair,0)} signals)
📦 Active Trades Now: {len(load_trades())}

📋 Last Signals:
"""
        for s in today_signals[-5:]:
            msg += f"- {s['time'][11:16]} {s['pair']} {s['side']} @ {fmt_price(s['entry'], s['entry'])}\n"
        
        msg += f"""
⚠️ ATR Bug: FIXED ✅
💰 Live Price: FIXED ✅
📏 Decimals: FIXED ✅

{CONTACT} {BRAND} 🌟🚀
Tomorrow we go harder! 💵💵💵"""
        send(msg, "DAILY REPORT - FXMEGA UG - 22:00 EAT")

# === RUN DAILY REPORT CHECK FIRST ===
maybe_send_daily_report()

# === REST OF YOUR BOT (v10.9 LIVE + ATR FIX) ===
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

active=load_trades()
print(f"Active: {len(active)}")

for sym,name in PAIRS.items():
    if name not in active: continue
    if "USD=X" in sym and is_weekend(): continue
    try:
        df=yf.download(sym, period="1d", interval="15m", auto_adjust=True, progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        cur=get_live_price(sym, f(df['Close'].iloc[-1]))
        t=active[name]; side,entry,stage=t['side'],t['entry'],t.get('stage',0)
        tp1,tp2,tp3,tp4=t['tp1'],t['tp2'],t['tp3'],t['tp4']
        hit_tp1=(cur>=tp1) if side=="BUY" else (cur<=tp1)
        hit_tp2=(cur>=tp2) if side=="BUY" else (cur<=tp2)
        hit_tp3=(cur>=tp3) if side=="BUY" else (cur<=tp3)
        hit_tp4=(cur>=tp4) if side=="BUY" else (cur<=tp4)
        if hit_tp4:
            send(f"🏁 {name} TP4 HIT CLOSE! TP4 {fmt_price(tp4,cur)} at {fmt_price(cur,cur)} Profit +{abs(cur-entry):.4f}", f"TP4 HIT - {name}")
            del active[name]; save_trades(active); continue
        if hit_tp3 and stage<3:
            send(f"🔒 {name} TRAIL TO TP2 TP3 {fmt_price(tp3,cur)} HIT SL->{fmt_price(tp2,cur)}", f"TRAIL TP2 - {name}")
            t['sl']=tp2; t['stage']=3; active[name]=t; save_trades(active); continue
        if hit_tp2 and stage<2:
            send(f"🔒 {name} TRAIL TO TP1 TP2 {fmt_price(tp2,cur)} HIT", f"TRAIL TP1 - {name}")
            t['sl']=tp1; t['stage']=2; active[name]=t; save_trades(active); continue
        if hit_tp1 and stage<1:
            send(f"🔒 {name} AUTO BE TP1 {fmt_price(tp1,cur)} HIT SL->BE {fmt_price(entry,cur)}", f"AUTO BE - {name}")
            t['sl']=entry; t['stage']=1; active[name]=t; save_trades(active); continue
    except Exception as e: print(f"Trail {name}: {e}")

blocked=get_red_news()
dxy_cur,dxy_ema,dxy_below,dxy_above,dxy_up,dxy_down=get_dxy()

for sym,name in PAIRS.items():
    if name in active: continue
    if "USD=X" in sym and is_weekend(): continue
    curr="EUR" if "EUR" in name else "GBP" if "GBP" in name else "JPY" if "JPY" in name else "USD"
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
        base_buy=(bull_crt or bull_csd) and cur>ema_now and up and bulls_ok
        base_sell=(bear_crt or bear_csd) and cur<ema_now and down and bears_ok
        if name=="GOLD":
            if dxy_cur is None: continue
            buy_signal=base_buy and dxy_below and dxy_down
            sell_signal=base_sell and dxy_above and dxy_up
            dxy_msg=f"💵 DXY {dxy_cur:.2f} {'📉 BELOW+DOWN✅' if (dxy_below and dxy_down) else '📈 ABOVE+UP✅' if (dxy_above and dxy_up) else '❌ FAIL'}"
        else:
            buy_signal,sell_signal=base_buy,base_sell
            dxy_msg="✨ No DXY needed"
        if buy_signal or sell_signal:
            side="BUY" if buy_signal else "SELL"
            emoji_side="🟢🔥 BUY" if side=="BUY" else "🔴💥 SELL"
            if side=="BUY": sl=cur-1.2*atr; tp1=cur+1.5*atr; tp2=cur+2.0*atr; tp3=cur+2.5*atr; tp4=cur+3.0*atr
            else: sl=cur+1.2*atr; tp1=cur-1.5*atr; tp2=cur-2.0*atr; tp3=cur-2.5*atr; tp4=cur-3.0*atr
            active[name]={"side":side,"entry":cur,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"stage":0,"time":str(datetime.now(timezone.utc))}
            save_trades(active); log_signal_history(name,side,cur,sl,tp1,tp2,tp3,tp4,atr)
            msg=f"""{emoji_side} {name} v11.0 LIVE ✅
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY (LIVE): {fmt_price(cur,cur)}
🔍 CRT: {'✅ YES' if (bull_crt or bear_crt) else '❌ NO'} | CSD: {'✅ YES' if (bull_csd or bear_csd) else '❌ NO'} 💪 {bp*100:.0f}%
📊 EMA13: {fmt_price(ema_now,cur)} {'📈 UP ✅' if up else '📉 DOWN ✅'}
⚡ Power: {fmt_price((bulls_now if side=='BUY' else bears_now),cur)} {'🟢' if (bulls_ok or bears_ok) else '🔴'} ✅
{dxy_msg}
📏 ATR: {fmt_price(atr,cur)} ({atr/cur*100:.2f}%) | Candle: {fmt_price(candle_close,cur)}

🛑 SL: {fmt_price(sl,cur)} (1.2x)
🎯 TP1: {fmt_price(tp1,cur)} -> BE AUTO 🛡️
🎯 TP2: {fmt_price(tp2,cur)} -> Trail TP1 📈
🎯 TP3: {fmt_price(tp3,cur)} -> Trail TP2 💰
🎯 TP4: {fmt_price(tp4,cur)} -> CLOSE 🎉

⏱️ M15 LIVE + BE/Trail + Report 22:00 EAT
{CONTACT} {BRAND} 🚀🌟💵"""
            send(msg, f"{side} SIGNAL - {name} v11.0")
    except Exception as e: print(f"Scan {name}: {e}")

print("✅ v11.0 FULL - LIVE PRICE + ATR FIX + DAILY REPORT 22:00 EAT 🎉")