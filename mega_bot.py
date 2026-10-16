import os, json, asyncio, datetime, pytz, requests, websockets, pandas as pd, random

KAMPALA_TZ = pytz.timezone('Africa/Kampala')
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "256700848808")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "gold-ai-ug-788408267")

# 520-PROOF WS
DERIV_WS_LIST = [
    "wss://ws.deriv.com/websockets/v3?app_id=1089",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
    "wss://ws.deriv.com/websockets/v3?app_id=37302"
]

SYMBOLS_VOL = ["R_10","R_25","R_50","R_75","R_100","VOLATILITY_10_INDEX","VOLATILITY_25_INDEX","VOLATILITY_50_INDEX","VOLATILITY_75_INDEX","VOLATILITY_100_INDEX"]
HISTORY_FILE = "signals_history.json"

def fmt(sym, p):
    try:
        p=float(p); s=sym.upper()
        if "JPY" in s: return f"{p:.3f}"
        if "XAU" in s or "GOLD" in s: return f"{p:.2f}"
        if "XAG" in s or "SILVER" in s: return f"{p:.3f}"
        if "EUR" in s or "GBP" in s: return f"{p:.5f}"
        return f"{p:.2f}"
    except: return str(p)

def send_whatsapp(text):
    if not CALLMEBOT_APIKEY: return
    try:
        phone=WHATSAPP_PHONE.replace("+","").replace(" ","")
        url=f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={requests.utils.quote(text)}&apikey={CALLMEBOT_APIKEY}"
        requests.get(url, timeout=15)
    except: pass

def send_ntfy(title, body):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{title}\n{body}".encode('utf-8'), headers={"Title": title, "Priority": "high"}, timeout=10)
    except: pass

def send_all(title, body):
    full=f"{title}\n{body}\n\nFXMEGA UG • 0700848808"
    print(full); send_whatsapp(full); send_ntfy(title, body)
    try:
        hist=[]
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE,'r') as f: hist=json.load(f)
        hist.append({"title":title,"body":body,"time":datetime.datetime.now().isoformat()})
        with open(HISTORY_FILE,'w') as f: json.dump(hist[-100:], f, indent=2)
    except: pass

def add_signal(sym): print(f"Signal {sym}")
def rsi_calc(s,p=14):
    delta=s.diff(); gain=(delta.where(delta>0,0)).ewm(span=p).mean(); loss=(-delta.where(delta<0,0)).ewm(span=p).mean(); rs=gain/loss; return 100-(100/(1+rs))

async def get_candles(sym, gran=60):
    random.shuffle(DERIV_WS_LIST)
    for WS in DERIV_WS_LIST:
        try:
            async with websockets.connect(WS, ping_interval=20, extra_headers={"Origin": "https://app.deriv.com", "User-Agent": "Mozilla/5.0"}, open_timeout=20) as ws:
                await ws.send(json.dumps({"ticks_history": sym, "count": 200, "end": "latest", "granularity": gran, "style": "candles"}))
                data=json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if "candles" in data and len(data["candles"])>50:
                    print(f"{sym} OK")
                    return pd.DataFrame(data["candles"])
        except Exception as e:
            print(f"WS {sym} fail {str(e)[:60]}")
            await asyncio.sleep(0.5)
            continue
    return pd.DataFrame()

async def analyze_vol(sym):
    df=await get_candles(sym,60)
    if df.empty or len(df)<60: print(f"{sym} no data"); return
    df['close']=pd.to_numeric(df['close']); df['high']=pd.to_numeric(df['high']); df['low']=pd.to_numeric(df['low'])
    ema50=df['close'].ewm(span=50).mean(); ema_flat=abs(ema50.iloc[-1]-ema50.iloc[-10])<(df['close'].iloc[-1]*0.001) if len(ema50)>10 else True
    recent=df.iloc[-120:]; rh=recent['high'].max(); rl=recent['low'].min(); rs=rh-rl
    if rs==0: return
    price=float(df['close'].iloc[-1]); r=float(rsi_calc(df['close']).iloc[-1]); pos=((price-rl)/rs*100)
    if pos<20 and r<35 and ema_flat:
        sl=rl-(rs*0.2); tp=rl+(rs*0.8)
        send_all(f"🔵 FX MEGA UG - {sym} BUY", f"🎯 ENTRY: {fmt(sym,price)} | Low: {fmt(sym,rl)} High: {fmt(sym,rh)}\n🔴 SL: {fmt(sym,sl)} | ✅ TP: {fmt(sym,tp)} | RSI:{r:.1f}\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
    if pos>80 and r>65 and ema_flat:
        sl=rh+(rs*0.2); tp=rh-(rs*0.8)
        send_all(f"🔴 FX MEGA UG - {sym} SELL", f"🎯 ENTRY: {fmt(sym,price)} | High: {fmt(sym,rh)} Low: {fmt(sym,rl)}\n🔴 SL: {fmt(sym,sl)} | ✅ TP: {fmt(sym,tp)} | RSI:{r:.1f}\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
    await asyncio.sleep(0.8)

async def analyze_gold():
    try:
        import yfinance as yf
        df=yf.download("GC=F", period="2d", interval="15m", progress=False)
        if df.empty: return
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        df.columns=[c.lower() for c in df.columns]
        price=float(df['close'].iloc[-1]); e20=float(df['close'].ewm(span=20).mean().iloc[-1]); e50=float(df['close'].ewm(span=50).mean().iloc[-1]); r=float(rsi_calc(df['close']).iloc[-1]); a=float((df['high']-df['low']).rolling(14).mean().iloc[-1])
        lh=float(df['high'].iloc[-20:-1].max()); ll=float(df['low'].iloc[-20:-1].min()); up=price>e20>e50; down=price<e20<e50
        if up and price>lh and 55<r<75:
            sl=price-(a*1.5); tp1=price+(a*2); tp2=price+(a*3.5)
            send_all(f"🔵 FX MEGA UG - GOLD BUY", f"🎯 ENTRY: {fmt('GOLD',price)} | 🔴 SL: {fmt('GOLD',sl)}\n✅ TP1: {fmt('GOLD',tp1)} | TP2: {fmt('GOLD',tp2)}\n📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
        if down and price<ll and 30<r<55:
            sl=price+(a*1.5); tp1=price-(a*2); tp2=price-(a*3.5)
            send_all(f"🔴 FX MEGA UG - GOLD SELL", f"🎯 ENTRY: {fmt('GOLD',price)} | 🔴 SL: {fmt('GOLD',sl)}\n✅ TP1: {fmt('GOLD',tp1)} | TP2: {fmt('GOLD',tp2)}\n📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
        print("Gold checked OK")
    except Exception as e: print(f"Gold err {e}")

# ==== SILVER ADDED BACK ====
async def analyze_silver():
    try:
        import yfinance as yf
        df=yf.download("SI=F", period="2d", interval="15m", progress=False)
        if df.empty: 
            print("Silver no data")
            return
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        df.columns=[c.lower() for c in df.columns]
        price=float(df['close'].iloc[-1]); e20=float(df['close'].ewm(span=20).mean().iloc[-1]); e50=float(df['close'].ewm(span=50).mean().iloc[-1]); r=float(rsi_calc(df['close']).iloc[-1]); a=float((df['high']-df['low']).rolling(14).mean().iloc[-1])
        lh=float(df['high'].iloc[-20:-1].max()); ll=float(df['low'].iloc[-20:-1].min()); up=price>e20>e50; down=price<e20<e50
        if up and price>lh and 55<r<75:
            sl=price-(a*1.5); tp1=price+(a*2); tp2=price+(a*3.5)
            send_all(f"🔵 FX MEGA UG - SILVER BUY", f"🎯 ENTRY: {fmt('SILVER',price)} | 🔴 SL: {fmt('SILVER',sl)}\n✅ TP1: {fmt('SILVER',tp1)} | TP2: {fmt('SILVER',tp2)}\n📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n🥈 Silver breakout\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
        if down and price<ll and 30<r<55:
            sl=price+(a*1.5); tp1=price-(a*2); tp2=price-(a*3.5)
            send_all(f"🔴 FX MEGA UG - SILVER SELL", f"🎯 ENTRY: {fmt('SILVER',price)} | 🔴 SL: {fmt('SILVER',sl)}\n✅ TP1: {fmt('SILVER',tp1)} | TP2: {fmt('SILVER',tp2)}\n📊 EMA20:{e20:.1f} EMA50:{e50:.1f} RSI:{r:.1f}\n🥈 Silver breakdown\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m/%Y')}")
        print("Silver checked OK")
    except Exception as e: print(f"Silver err {e}")

async def main():
    print(f"FXMEGA UG V5.6 WITH SILVER - {datetime.datetime.now(KAMPALA_TZ)}")
    print(f"DUAL: WhatsApp + ntfy.sh/{NTFY_TOPIC}")
    await analyze_gold()
    await analyze_silver()
    for s in SYMBOLS_VOL:
        try: await analyze_vol(s)
        except: pass
    print("Done - GOLD + SILVER + VOLS sent to BOTH!")

if __name__=="__main__": asyncio.run(main())
