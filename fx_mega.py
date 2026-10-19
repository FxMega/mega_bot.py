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

# === SPOT CORRECTION TO MATCH YOUR MT5 ===
GOLD_SPOT_OFFSET = 22.0   # GC=F 4167 -> 4145 spot = -22 (your screenshot)
SILVER_SPOT_OFFSET = 0.35 # SI=F -> spot

PAIRS_FALLBACK = {
    "GOLD": ["XAUUSD=X", "GC=F"],
    "SILVER": ["XAGUSD=X", "SI=F"],
    "BITCOIN": ["BTC-USD"],
    "ETHEREUM": ["ETH-USD"],
    "SOLANA": ["SOL-USD"],
    "BNB": ["BNB-USD"],
    "XRP": ["XRP-USD"],
    "DOGECOIN": ["DOGE-USD"],
    "EURUSD": ["EURUSD=X"],
    "GBPUSD": ["GBPUSD=X"],
    "USDJPY": ["USDJPY=X"]
}
DXY_SYMBOL = "DX-Y.NYB"

def smart_download(name, period, interval):
    tickers = PAIRS_FALLBACK.get(name, [name])
    for sym in tickers:
        try:
            df = yf.download(sym, period=period, interval=interval, auto_adjust=True, progress=False)
            if df is not None and not df.empty and len(df) > 10:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                print(f"{name}: using {sym} OK")
                return df, sym
        except: continue
    return pd.DataFrame(), None

def send(msg, is_buy=True):
    try:
        title = "BUY SIGNAL" if ("BUY" in msg and "SIGNAL" in msg) else "SELL SIGNAL" if ("SELL" in msg and "SIGNAL" in msg) else "BE/TRAIL"
        tag = "moneybag" if "BUY" in title else "money_with_wings" if "SELL" in title else "rocket"
        requests.post(NTFY_URL, data=msg.encode('utf-8'), headers={"Title": f"{title} - {BRAND}","Priority": "high","Tags": tag,"Content-Type": "text/plain; charset=utf-8"}, timeout=10)
        print(f"SENT: {msg[:90]}"); time.sleep(6)
    except Exception as e: print(f"Send: {e}")

def load_trades():
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE,'r') as f: return json.load(f)
        except: return {}
    return {}
def save_trades(tr):
    with open(TRADE_FILE,'w') as f: json.dump(tr,f,indent=2)
def is_weekend(): return datetime.now(timezone.utc).weekday() >=5
def get_red_news():
    blocked=set()
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=10).json()
        now=datetime.now(timezone.utc)
        for ev in r:
            if ev.get("impact")!="High": continue
            try: et=datetime.fromisoformat(ev.get("date").replace("Z","+00:00"))
            except: continue
            if -60 <= (et-now).total_seconds()/60 <=60:
                c=ev.get("country","").strip()
                if c: blocked.add(c)
    except: pass
    return blocked
def f(x):
    try:
        if hasattr(x,'iloc'): return float(x.iloc[0])
        return float(x)
    except: return float(x)
def fmt_price(p):
    try:
        p=float(p)
        if p<0.01: return f"{p:.6f}"
        elif p<1: return f"{p:.5f}"
        elif p<10: return f"{p:.4f}"
        elif p<100: return f"{p:.3f}"
        else: return f"{p:.2f}"
    except: return str(p)
def get_dxy():
    try:
        df = yf.download(DXY_SYMBOL, period="5d", interval="15m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        close=df['Close']; ema=close.ewm(span=13).mean()
        return f(close.iloc[-2]), f(ema.iloc[-2]), f(close.iloc[-2])<f(ema.iloc[-2]), f(close.iloc[-2])>f(ema.iloc[-2]), f(ema.iloc[-2])>f(ema.iloc[-3]), f(ema.iloc[-2])<f(ema.iloc[-3])
    except: return None,None,False,False,False,False

# === 1. BE + TRAIL ===
active=load_trades()
print(f"Active trades: {len(active)}")
for name in PAIRS_FALLBACK.keys():
    if name not in active: continue
    df,sym_used=smart_download(name,"1d","15m")
    if df.empty: continue
    cur=f(df['Close'].iloc[-1])
    # apply spot correction for live trail too
    if sym_used=="GC=F": cur -= GOLD_SPOT_OFFSET
    if sym_used=="SI=F": cur -= SILVER_SPOT_OFFSET
    t=active[name]; side=t['side']; entry=t['entry']; stage=t.get('stage',0)
    tp1=t['tp1']; tp2=t['tp2']; tp3=t['tp3']; tp4=t['tp4']
    hit_tp1=(cur>=tp1) if side=="BUY" else (cur<=tp1)
    hit_tp2=(cur>=tp2) if side=="BUY" else (cur<=tp2)
    hit_tp3=(cur>=tp3) if side=="BUY" else (cur<=tp3)
    hit_tp4=(cur>=tp4) if side=="BUY" else (cur<=tp4)
    if hit_tp4:
        send(f"🏁🎉 {name} TP4 HIT CLOSE ALL {side} {fmt_price(tp4)} at {fmt_price(cur)} {CONTACT} {BRAND}")
        del active[name]; save_trades(active); continue
    if hit_tp3 and stage<3:
        send(f"🔒➡️ {name} TRAIL TP2 TP3 {fmt_price(tp3)} HIT SL {fmt_price(t['sl'])}->{fmt_price(tp2)} {CONTACT} {BRAND}")
        t['sl']=tp2; t['stage']=3; active[name]=t; save_trades(active); continue
    if hit_tp2 and stage<2:
        send(f"🔒➡️ {name} TRAIL TP1 TP2 {fmt_price(tp2)} HIT SL->{fmt_price(tp1)} {CONTACT} {BRAND}")
        t['sl']=tp1; t['stage']=2; active[name]=t; save_trades(active); continue
    if hit_tp1 and stage<1:
        send(f"🔒✨ {name} AUTO BE TP1 {fmt_price(tp1)} HIT MOVE SL TO BE {fmt_price(entry)} {CONTACT} {BRAND}")
        t['sl']=entry; t['stage']=1; active[name]=t; save_trades(active); continue

# === 2. NEW SIGNALS NO-REPAINT ===
blocked=get_red_news()
dxy_cur,dxy_ema,dxy_below,dxy_above,dxy_up,dxy_down=get_dxy()
print(f"DXY {dxy_cur} Blocked:{blocked}")

for name in PAIRS_FALLBACK.keys():
    if name in active: continue
    if name in ["EURUSD","GBPUSD","USDJPY"] and is_weekend(): continue
    if blocked: print(f"{name}: BLOCKED {blocked}"); continue

    df,sym_used=smart_download(name,"5d","15m")
    df_d,_=smart_download(name,"10d","1d")
    if df.empty or df_d.empty or len(df)<100: print(f"{name}: no data"); continue

    close=df['Close']; high=df['High']; low=df['Low']; open_=df['Open']
    cur=f(close.iloc[-2]); cur_live=f(close.iloc[-1])
    
    # === SPOT CORRECTION TO MATCH YOUR MT5 CHART ===
    is_futures=False
    if sym_used=="GC=F":
        cur -= GOLD_SPOT_OFFSET; cur_live -= GOLD_SPOT_OFFSET; is_futures=True
        print(f"{name}: GC=F corrected -{GOLD_SPOT_OFFSET} to match XAUUSDmicro -> {fmt_price(cur)}")
    if sym_used=="SI=F":
        cur -= SILVER_SPOT_OFFSET; cur_live -= SILVER_SPOT_OFFSET; is_futures=True
        print(f"{name}: SI=F corrected -{SILVER_SPOT_OFFSET} to match XAGUSDmicro -> {fmt_price(cur)}")

    hnow=f(high.iloc[-2]); lnow=f(low.iloc[-2])
    if is_futures:
        hnow-= GOLD_SPOT_OFFSET if name=="GOLD" else SILVER_SPOT_OFFSET
        lnow-= GOLD_SPOT_OFFSET if name=="GOLD" else SILVER_SPOT_OFFSET
    open_sig=f(open_.iloc[-2]); h_prev2=f(high.iloc[-3]); l_prev2=f(low.iloc[-3])
    if is_futures:
        off = GOLD_SPOT_OFFSET if name=="GOLD" else SILVER_SPOT_OFFSET
        open_sig-=off; h_prev2-=off; l_prev2-=off

    tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr_raw=f(tr.rolling(14).mean().iloc[-2])
    ema13=close.ewm(span=13).mean()
    ema_now=f(ema13.iloc[-2]); ema_prev=f(ema13.iloc[-3])
    if is_futures:
        off = GOLD_SPOT_OFFSET if name=="GOLD" else SILVER_SPOT_OFFSET
        ema_now-=off; ema_prev-=off

    up=ema_now>ema_prev; down=ema_now<ema_prev
    atr=atr_raw
    if atr<cur*0.005: atr=cur*0.005
    if cur<1.0 and atr<cur*0.01: atr=cur*0.01
    if atr==0: atr=cur*0.01

    pdh=f(df_d['High'].iloc[-2]); pdl=f(df_d['Low'].iloc[-2])
    if is_futures:
        off = GOLD_SPOT_OFFSET if name=="GOLD" else SILVER_SPOT_OFFSET
        pdh-=off; pdl-=off
    crt50=(pdh+pdl)/2
    bull_crt=lnow<pdl and cur>pdl and cur>crt50
    bear_crt=hnow>pdh and cur<pdh and cur<crt50
    body=abs(cur-open_sig); rng=hnow-lnow
    bp=body/rng if rng>0 else 0
    bull_csd=cur>open_sig and bp>0.6 and cur>h_prev2
    bear_csd=cur<open_sig and bp>0.6 and cur<l_prev2
    bulls_now=hnow-ema_now; bulls_prev=h_prev2-ema_prev
    bears_now=lnow-ema_now; bears_prev=l_prev2-ema_prev
    bulls_ok=(bulls_prev<0 and bulls_now>0) or bulls_now>0
    bears_ok=(bears_prev>0 and bears_now<0) or bears_now<0
    base_buy=(bull_crt or bull_csd) and cur>ema_now and up and bulls_ok
    base_sell=(bear_crt or bear_csd) and cur<ema_now and down and bears_ok

    if name=="GOLD":
        if dxy_cur is None: continue
        buy_signal=base_buy and dxy_below and dxy_down
        sell_signal=base_sell and dxy_above and dxy_up
        dxy_msg=f"💵 DXY {fmt_price(dxy_cur)} {'📉 BELOW+DOWN✅' if (dxy_below and dxy_down) else '📈 ABOVE+UP✅' if (dxy_above and dxy_up) else '❌ FAIL'}"
    else:
        buy_signal=base_buy; sell_signal=base_sell; dxy_msg="✨ No DXY needed"

    print(f"{name} {fmt_price(cur)} live {fmt_price(cur_live)} EMA {fmt_price(ema_now)} {'UP' if up else 'DOWN'} Buy:{base_buy} Sell:{base_sell}")

    if buy_signal or sell_signal:
        side="BUY" if buy_signal else "SELL"
        emoji_side="🟢🔥 BUY" if side=="BUY" else "🔴💥 SELL"
        entry=cur
        if side=="BUY":
            sl=entry-1.2*atr; tp1=entry+1.5*atr; tp2=entry+2.0*atr; tp3=entry+2.5*atr; tp4=entry+3.0*atr
        else:
            sl=entry+1.2*atr; tp1=entry-1.5*atr; tp2=entry-2.0*atr; tp3=entry-2.5*atr; tp4=entry-3.0*atr
        active[name]={"side":side,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"stage":0,"time":str(datetime.now(timezone.utc))}
        save_trades(active)
        feed_info = f"(spot corrected from {sym_used} -{GOLD_SPOT_OFFSET if name=='GOLD' else SILVER_SPOT_OFFSET})" if is_futures else f"(using {sym_used})"
        msg=f"""{emoji_side} {name} v10.11 SPOT MATCH ✅ {feed_info}
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY: {fmt_price(entry)} (matches your MT5 {fmt_price(entry)})
🔍 CRT: {'✅ YES' if (bull_crt or bear_crt) else '❌ NO'} | CSD: {'✅ YES' if (bull_csd or bear_csd) else '❌ NO'} 💪 {bp*100:.0f}%
📊 EMA13: {fmt_price(ema_now)} {'📈 UP ✅' if up else '📉 DOWN ✅'}
{dxy_msg}
📏 ATR: {fmt_price(atr)}
🛑 SL: {fmt_price(sl)}
🎯 TP1: {fmt_price(tp1)} -> BE 🛡️
🎯 TP2: {fmt_price(tp2)} -> Trail TP1
🎯 TP3: {fmt_price(tp3)} -> Trail TP2
🎯 TP4: {fmt_price(tp4)} -> CLOSE
⏱️ M15 NO-REPAINT + SPOT MATCH + RedNews ALL
{CONTACT} {BRAND} 🚀"""
        send(msg, is_buy=buy_signal)

print("✅ v10.11 SPOT MATCH - GOLD 4143 not 4167 + 404 FALLBACK FIXED 🎉")