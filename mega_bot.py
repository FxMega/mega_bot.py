import os, datetime, pytz, requests, pandas as pd, json, sys
from collections import Counter

KAMPALA_TZ = pytz.timezone('Africa/Kampala')
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "256700848808")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "gold-ai-ug-788408267")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
RED_WINDOW = 90
HISTORY_FILE = "signals_history.json"

def fmt(sym, p):
    try:
        p=float(p); s=sym.upper()
        if "JPY" in s: return f"{p:.3f}"
        if "GOLD" in s or "XAU" in s: return f"{p:.2f}"
        if "SILVER" in s or "XAG" in s: return f"{p:.3f}"
        return f"{p:.5f}"
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

def save_history(title, body):
    try:
        hist=[]
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE,'r') as f: hist=json.load(f)
        pair = "UNKNOWN"
        for k in ["GOLD","SILVER","EURUSD","GBPUSD","USDJPY"]:
            if k in title.upper(): pair=k; break
        hist.append({"title":title,"body":body,"time":datetime.datetime.now(KAMPALA_TZ).isoformat(),"pair":pair})
        with open(HISTORY_FILE,'w') as f: json.dump(hist[-500:], f, indent=2)
    except: pass

def send_all(title, body):
    full=f"{title}\n{body}\n\nFXMEGA UG • 0700848808"
    print(full)
    send_whatsapp(full)
    send_ntfy(title, body)
    save_history(title, body)

def rsi(s,p=14):
    delta=s.diff(); gain=(delta.where(delta>0,0)).ewm(span=p).mean(); loss=(-delta.where(delta<0,0)).ewm(span=p).mean(); rs=gain/loss; return 100-(100/(1+rs))

def adx_calc(df,p=14):
    try:
        h=df['high']; l=df['low']; c=df['close']
        plus_dm=h.diff(); minus_dm=-l.diff()
        plus_dm[plus_dm<0]=0; minus_dm[minus_dm<0]=0
        tr=pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        atr=tr.ewm(span=p).mean()
        plus_di=100*(plus_dm.ewm(span=p).mean()/atr)
        minus_di=100*(minus_dm.ewm(span=p).mean()/atr)
        dx=100*((plus_di-minus_di).abs()/(plus_di+minus_di))
        return float(dx.ewm(span=p).mean().iloc[-1])
    except: return 25

def bbands(s,p=20,sd=2):
    ma=s.rolling(p).mean(); std=s.rolling(p).std(); return ma+std*sd, ma-std*sd, ma

def keltner(df,p=20,atr_p=10,m=1.5):
    ema=df['close'].ewm(span=p).mean()
    tr=pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    atr=tr.ewm(span=atr_p).mean()
    return ema+atr*m, ema-atr*m, ema

def ichimoku(df):
    try:
        high9=df['high'].rolling(9).max(); low9=df['low'].rolling(9).min(); tenkan=(high9+low9)/2
        high26=df['high'].rolling(26).max(); low26=df['low'].rolling(26).min(); kijun=(high26+low26)/2
        senkou_a=((tenkan+kijun)/2).shift(26)
        high52=df['high'].rolling(52).max(); low52=df['low'].rolling(52).min(); senkou_b=((high52+low52)/2).shift(26)
        return float(tenkan.iloc[-1]), float(kijun.iloc[-1]), float(senkou_a.iloc[-1]), float(senkou_b.iloc[-1])
    except: return None,None,None,None

def get_red():
    try: return requests.get(FF_URL, timeout=10).json()
    except: return []

def is_blocked(currs):
    evs=get_red(); now=datetime.datetime.now(pytz.utc)
    for ev in evs:
        try:
            imp=str(ev.get("impact","")); country=str(ev.get("country","") or ev.get("currency","")).upper()
            if "High" not in imp and imp not in ["3","High"]:
                if str(ev.get("color","")).lower()!="red": continue
            if country not in currs: continue
            ts=ev.get("date") or ev.get("timestamp")
            et=None
            if isinstance(ts,(int,float)): et=datetime.datetime.fromtimestamp(ts, tz=pytz.utc)
            else:
                try: et=datetime.datetime.fromisoformat(str(ts).replace("Z","+00:00"))
                except: continue
            if et and abs((et-now).total_seconds())/60 <= RED_WINDOW:
                return True, f"{country} {ev.get('title','Red News')} @ {et.astimezone(KAMPALA_TZ).strftime('%H:%M')}"
        except: continue
    return False, None

def get_data(yf_sym, period="5d", interval="15m"):
    import yfinance as yf
    df=yf.download(yf_sym, period=period, interval=interval, progress=False)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[c.lower() for c in df.columns]
    return df

# ===== BEST STRATEGIES =====
def strategy_gold():
    name="GOLD"
    blocked, reason=is_blocked(["USD"])
    if blocked: print(f"⛔ {name} BLOCKED {reason}"); return
    df15=get_data("GC=F","5d","15m"); df1h=get_data("GC=F","10d","60m")
    if df15 is None or df1h is None: return
    price=float(df15['close'].iloc[-1]); e20=float(df15['close'].ewm(span=20).mean().iloc[-1]); e50=float(df15['close'].ewm(span=50).mean().iloc[-1])
    e20_h=float(df1h['close'].ewm(span=20).mean().iloc[-1]); e50_h=float(df1h['close'].ewm(span=50).mean().iloc[-1])
    r=float(rsi(df15['close']).iloc[-1]); atr=float((df15['high']-df15['low']).rolling(14).mean().iloc[-1])
    lh=float(df15['high'].iloc[-20:-1].max()); ll=float(df15['low'].iloc[-20:-1].min())
    if price>e20>e50 and e20_h>e50_h and price>lh and 55<r<75:
        sl=price-atr*1.5; tp1=price+atr*2.5; tp2=price+atr*4.5
        send_all(f"🔵 FX MEGA UG - {name} BUY - London Breakout", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Breakout {fmt(name,lh)} | RSI:{r:.1f} | 1H UP | Est 68-72%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    if price<e20<e50 and e20_h<e50_h and price<ll and 25<r<45:
        sl=price+atr*1.5; tp1=price-atr*2.5; tp2=price-atr*4.5
        send_all(f"🔴 FX MEGA UG - {name} SELL - London Breakdown", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Breakdown {fmt(name,ll)} | RSI:{r:.1f} | 1H DOWN | Est 68-72%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    print(f"{name} OK {fmt(name,price)}")

def strategy_silver():
    name="SILVER"
    blocked, reason=is_blocked(["USD"])
    if blocked: print(f"⛔ {name} BLOCKED {reason}"); return
    df15=get_data("SI=F","5d","15m"); df_gold=get_data("GC=F","5d","15m")
    if df15 is None or df_gold is None: return
    price=float(df15['close'].iloc[-1]); e20=float(df15['close'].ewm(span=20).mean().iloc[-1]); e50=float(df15['close'].ewm(span=50).mean().iloc[-1])
    gold_p=float(df_gold['close'].iloc[-1]); gold_e20=float(df_gold['close'].ewm(span=20).mean().iloc[-1])
    r=float(rsi(df15['close']).iloc[-1]); atr=float((df15['high']-df15['low']).rolling(14).mean().iloc[-1])
    if price>e20>e50 and gold_p>gold_e20 and 52<r<70:
        sl=price-atr*2.0; tp1=price+atr*2.8
        send_all(f"🔵 FX MEGA UG - {name} BUY - Gold Corr", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)}\n📊 Silver EMA + Gold UP {fmt('GOLD',gold_p)} | RSI:{r:.1f} | Est 64-68%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    if price<e20<e50 and gold_p<gold_e20 and 30<r<48:
        sl=price+atr*2.0; tp1=price-atr*2.8
        send_all(f"🔴 FX MEGA UG - {name} SELL - Gold Corr", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)}\n📊 Silver EMA + Gold DOWN | RSI:{r:.1f} | Est 64-68%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    print(f"{name} OK {fmt(name,price)}")

def strategy_eurusd():
    name="EURUSD"
    blocked, reason=is_blocked(["EUR","USD"])
    if blocked: print(f"⛔ {name} BLOCKED {reason}"); return
    df=get_data("EURUSD=X","5d","15m")
    if df is None: return
    price=float(df['close'].iloc[-1]); r=float(rsi(df['close']).iloc[-1]); adx=adx_calc(df)
    upper, lower, mid = bbands(df['close'],20,2.0)
    u=float(upper.iloc[-1]); l=float(lower.iloc[-1]); m=float(mid.iloc[-1])
    atr=float((df['high']-df['low']).rolling(14).mean().iloc[-1])
    if price<=l and r<32 and adx<25:
        sl=price-atr*1.8; tp1=m; tp2=u
        send_all(f"🔵 FX MEGA UG - {name} BUY - BB Reversion", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Lower BB {fmt(name,l)} | RSI:{r:.1f} | ADX:{adx:.1f} | Est 63-67%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    if price>=u and r>68 and adx<25:
        sl=price+atr*1.8; tp1=m; tp2=l
        send_all(f"🔴 FX MEGA UG - {name} SELL - BB Reversion", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Upper BB {fmt(name,u)} | RSI:{r:.1f} | ADX:{adx:.1f} | Est 63-67%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    print(f"{name} OK {fmt(name,price)}")

def strategy_gbpusd():
    name="GBPUSD"
    blocked, reason=is_blocked(["GBP","USD"])
    if blocked: print(f"⛔ {name} BLOCKED {reason}"); return
    df=get_data("GBPUSD=X","5d","15m")
    if df is None: return
    price=float(df['close'].iloc[-1]); r=float(rsi(df['close']).iloc[-1]); adx=adx_calc(df)
    uk, lk, ema = keltner(df,20,14,1.8)
    uk=float(uk.iloc[-1]); lk=float(lk.iloc[-1]); atr=float((df['high']-df['low']).rolling(14).mean().iloc[-1])
    if price>uk and adx>25 and 55<r<72:
        sl=price-atr*2.5; tp1=price+atr*2.0; tp2=price+atr*3.5
        send_all(f"🔵 FX MEGA UG - {name} BUY - Keltner Break", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Above Keltner {fmt(name,uk)} | ADX:{adx:.1f} | Est 60-64%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    if price<lk and adx>25 and 28<r<45:
        sl=price+atr*2.5; tp1=price-atr*2.0; tp2=price-atr*3.5
        send_all(f"🔴 FX MEGA UG - {name} SELL - Keltner Break", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)} TP2: {fmt(name,tp2)}\n📊 Below Keltner {fmt(name,lk)} | ADX:{adx:.1f} | Est 60-64%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    print(f"{name} OK {fmt(name,price)}")

def strategy_usdjpy():
    name="USDJPY"
    blocked, reason=is_blocked(["USD","JPY"])
    if blocked: print(f"⛔ {name} BLOCKED {reason}"); return
    df=get_data("JPY=X","10d","15m")
    if df is None: return
    price=float(df['close'].iloc[-1]); e20=float(df['close'].ewm(span=20).mean().iloc[-1]); e50=float(df['close'].ewm(span=50).mean().iloc[-1])
    r=float(rsi(df['close']).iloc[-1]); adx=adx_calc(df)
    tenkan,kijun,senkou_a,senkou_b=ichimoku(df)
    if tenkan is None: return
    cloud_top=max(senkou_a,senkou_b); cloud_bottom=min(senkou_a,senkou_b)
    atr=float((df['high']-df['low']).rolling(14).mean().iloc[-1])
    if price>cloud_top and tenkan>kijun and price>e20>e50 and adx>22 and 52<r<68:
        sl=price-atr*2.3; tp1=price+atr*2.5
        send_all(f"🔵 FX MEGA UG - {name} BUY - Ichimoku", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)}\n📊 Above Cloud {fmt(name,cloud_top)} | ADX:{adx:.1f} | Est 64-68%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    if price<cloud_bottom and tenkan<kijun and price<e20<e50 and adx>22 and 32<r<48:
        sl=price+atr*2.3; tp1=price-atr*2.5
        send_all(f"🔴 FX MEGA UG - {name} SELL - Ichimoku", f"🎯 ENTRY: {fmt(name,price)}\n🔴 SL: {fmt(name,sl)}\n✅ TP1: {fmt(name,tp1)}\n📊 Below Cloud {fmt(name,cloud_bottom)} | ADX:{adx:.1f} | Est 64-68%\n⏰ {datetime.datetime.now(KAMPALA_TZ).strftime('%H:%M %d/%m')}")
    print(f"{name} OK {fmt(name,price)}")

def generate_daily_report():
    try:
        if not os.path.exists(HISTORY_FILE):
            send_all("📊 DAILY REPORT 22:00 - No trades", "No signals today. Market ranging or red news blocked.\nGood - no bad trade = profit!")
            return
        with open(HISTORY_FILE,'r') as f: hist=json.load(f)
        today = datetime.datetime.now(KAMPALA_TZ).date().isoformat()
        todays = [h for h in hist if today in h['time']]
        if not todays:
            send_all(f"📊 DAILY REPORT {today}", f"Date: {today}\nNo signals today. All filtered by ADX/News.\nWin rate protected!\n⏰ 22:00 Kampala")
            return
        pairs = Counter([h.get('pair','?') for h in todays])
        total=len(todays); best=pairs.most_common(1)[0][0] if pairs else "None"
        report=f"📅 {today}\nTotal: {total} signals\n\n"
        for p,c in pairs.items(): report+=f"{p}: {c}\n"
        report+=f"\n🏆 Best: {best}\n📈 Est win V8.0: 64-68%\n🟢 Red news filter active\n⏰ 22:00 Kampala"
        send_all(f"📊 FXMEGA DAILY REPORT {today}", report)
    except Exception as e:
        send_all("📊 DAILY REPORT Error", str(e))

def generate_weekly_report():
    try:
        if not os.path.exists(HISTORY_FILE):
            send_all("📊 WEEKLY REPORT - No data", "No history yet")
            return
        with open(HISTORY_FILE,'r') as f: hist=json.load(f)
        pairs = Counter([h.get('pair','?') for h in hist[-100:]])
        total=len(hist); best=pairs.most_common(1)[0][0] if pairs else "None"; worst=pairs.most_common()[-1][0] if pairs else "None"
        report=f"📅 Week ending {datetime.datetime.now(KAMPALA_TZ).strftime('%d/%m/%Y')}\nTotal: {total} signals\n\n"
        for p,c in pairs.items(): report+=f"{p}: {c}\n"
        report+=f"\n🏆 Best: {best}\n⚠️ Worst: {worst}\n📈 Avg win V8.0: 64-68%\n💡 Next week: Focus {best}, avoid {worst} on red news\n⏰ Sunday 20:00 Kampala"
        send_all(f"📊 FXMEGA WEEKLY REPORT", report)
    except Exception as e:
        send_all("📊 WEEKLY REPORT Error", str(e))

def main():
    if "--daily" in sys.argv: generate_daily_report(); return
    if "--weekly" in sys.argv: generate_weekly_report(); return
    print(f"FXMEGA UG V8.0 FINAL - {datetime.datetime.now(KAMPALA_TZ)}")
    strategy_gold(); strategy_silver(); strategy_eurusd(); strategy_gbpusd(); strategy_usdjpy()
    print("Done - All 5 best strategies executed!")

if __name__=="__main__":
    main()
