import yfinance as yf, pandas as pd, requests, json, os, time
from datetime import datetime, timezone

NTFY_TOPIC = "gold-ai-ug-788408267"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
BRAND = "FXMEGA UG"
CONTACT = "0700848808"
GOLD_OFF = 24.0   # EXACT MATCH YOUR MT5 4143.98
SILVER_OFF = 0.35
DXY_SYM = "DX-Y.NYB"

PAIRS = {
    "GOLD": ["GC=F"],
    "SILVER": ["SI=F"],
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

def get_red_news():
    blocked=set()
    try:
        r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",timeout=15).json()
        now=datetime.now(timezone.utc)
        for ev in r:
            if ev.get("impact")!="High": continue
            try: et=datetime.fromisoformat(ev.get("date").replace("Z","+00:00"))
            except: continue
            diff=(et-now).total_seconds()/60
            if -60 <= diff <= 60:
                c=ev.get("country","").strip()
                if c:
                    print(f"🔴 RED NEWS FOUND: {c} {ev.get('title','')} at {et} diff {diff:.0f}min -> BLOCK ALL")
                    blocked.add(c)
        if not blocked: print("✅ NO RED NEWS - All pairs allowed")
        else: print(f"⛔ BLOCKED COUNTRIES: {blocked} - SKIP ALL 60min")
    except Exception as e: print(f"News err {e}")
    return blocked

def get_df(name):
    for sym in PAIRS[name]:
        try:
            df=yf.download(sym, period="5d", interval="15m", auto_adjust=True, progress=False)
            if df is not None and not df.empty and len(df)>30:
                if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
                return df, sym
        except: continue
    return pd.DataFrame(), None

def get_dxy():
    try:
        df=yf.download(DXY_SYM, period="5d", interval="15m", auto_adjust=True, progress=False)
        if df is None or df.empty:
            df=yf.download("DX=F", period="5d", interval="15m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        close=df['Close']; ema=close.ewm(span=13).mean()
        cur=float(close.iloc[-2]); ema_now=float(ema.iloc[-2]); ema_prev=float(ema.iloc[-3])
        below=cur<ema_now; above=cur>ema_now; down=ema_now<ema_prev; up=ema_now>ema_prev
        print(f"💵 DXY {cur:.2f} EMA {ema_now:.2f} BELOW={below} ABOVE={above} DOWN={down} UP={up}")
        print(f"   DXY BUY FILTER (GOLD BUY): BELOW={below}+DOWN={down}={below and down}")
        print(f"   DXY SELL FILTER (GOLD SELL): ABOVE={above}+UP={up}={above and up}")
        return cur, ema_now, below, above, down, up
    except: return None,None,False,False,False,False

def send(m, is_buy=True):
    try:
        title = "BUY SIGNAL" if is_buy else "SELL SIGNAL"
        tag = "moneybag" if is_buy else "money_with_wings"
        requests.post(NTFY_URL, data=m.encode('utf-8'),
            headers={"Title": f"{title} - {BRAND}","Priority":"high","Tags":tag,"Content-Type":"text/plain; charset=utf-8"}, timeout=10)
        time.sleep(6)
    except: pass

def ff(x):
    try:
        if hasattr(x,'iloc'): return float(x.iloc[0])
        return float(x)
    except: return float(x)
def fmt(p):
    p=float(p)
    if p<0.01: return f"{p:.6f}"
    elif p<1: return f"{p:.5f}"
    elif p<10: return f"{p:.4f}"
    elif p<100: return f"{p:.3f}"
    else: return f"{p:.2f}"

blocked=get_red_news()
dxy_cur,dxy_ema,dxy_below,dxy_above,dxy_down,dxy_up=get_dxy()

if blocked:
    print("⛔ ALL BLOCKED BY RED NEWS 60min")
else:
    for name in PAIRS.keys():
        df,sym=get_df(name)
        if df.empty: print(f"{name} NO DATA"); continue

        close=df['Close']; high=df['High']; low=df['Low']; op=df['Open']
        cur=ff(close.iloc[-2]); live=ff(close.iloc[-1])
        hnow=ff(high.iloc[-2]); lnow=ff(low.iloc[-2]); o=ff(op.iloc[-2])
        hp=ff(high.iloc[-3]); lp=ff(low.iloc[-3])

        off=GOLD_OFF if name=="GOLD" else SILVER_OFF if name=="SILVER" else 0
        if off>0: cur-=off; live-=off; hnow-=off; lnow-=off; o-=off; hp-=off; lp-=off

        pdh=ff(high.iloc[-97:-1].max()); pdl=ff(low.iloc[-97:-1].min())
        if off>0: pdh-=off; pdl-=off
        mid=(pdh+pdl)/2

        tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
        atr=ff(tr.rolling(14).mean().iloc[-2])
        if atr<cur*0.005: atr=cur*0.005

        ema=close.ewm(span=13).mean()
        ema_now=ff(ema.iloc[-2]); ema_prev=ff(ema.iloc[-3])
        if off>0: ema_now-=off; ema_prev-=off
        up=ema_now>ema_prev; down=ema_now<ema_prev

        bull_crt=lnow<pdl and cur>pdl and cur>mid
        bear_crt=hnow>pdh and cur<pdh and cur<mid
        body=abs(cur-o); rng=hnow-lnow; bp=body/rng if rng>0 else 0
        bull_csd=cur>o and bp>0.6 and cur>hp
        bear_csd=cur<o and bp>0.6 and cur<lp

        bulls_now=hnow-ema_now; bulls_prev=hp-ema_prev
        bears_now=lnow-ema_now; bears_prev=lp-ema_prev
        bulls_red_to_green=bulls_prev<0 and bulls_now>0
        bulls_green=bulls_now>0
        bears_green_to_red=bears_prev>0 and bears_now<0
        bears_red=bears_now<0
        bulls_ok=bulls_red_to_green or bulls_green
        bears_ok=bears_green_to_red or bears_red

        print(f"{name} BullsPower {bulls_now:.2f} PREV {bulls_prev:.2f} -> {'🟢 RED->GREEN' if bulls_red_to_green else '🟢 ALREADY GREEN' if bulls_green else '🔴 STILL RED'} OK={bulls_ok}")
        print(f"{name} BearsPower {bears_now:.2f} PREV {bears_prev:.2f} -> {'🔴 GREEN->RED' if bears_green_to_red else '🔴 ALREADY RED' if bears_red else '🟢 STILL GREEN'} OK={bears_ok}")

        base_buy=(bull_crt or bull_csd) and cur>ema_now and up and bulls_ok
        base_sell=(bear_crt or bear_csd) and cur<ema_now and down and bears_ok

        if name=="GOLD":
            if dxy_cur is None: continue
            buy_final=base_buy and dxy_below and dxy_down
            sell_final=base_sell and dxy_above and dxy_up
        else:
            buy_final=base_buy; sell_final=base_sell

        print(f"{name} ENTRY {fmt(cur)} LIVE {fmt(live)} SPOT -{off} BUY:{buy_final} SELL:{sell_final}")

        if buy_final or sell_final:
            side="BUY" if buy_final else "SELL"
            entry=cur
            if side=="BUY":
                sl=entry-1.2*atr; tp1=entry+1.5*atr; tp2=entry+2.0*atr; tp3=entry+2.5*atr; tp4=entry+3.0*atr
            else:
                sl=entry+1.2*atr; tp1=entry-1.5*atr; tp2=entry-2.0*atr; tp3=entry-2.5*atr; tp4=entry-3.0*atr

            dxy_txt = f"DXY {fmt(dxy_cur)} {'BELOW+DOWN ✅' if dxy_below and dxy_down else 'ABOVE+UP ✅' if dxy_above and dxy_up else ''}"
            bulls_txt = f"{'🟢 RED->GREEN' if bulls_red_to_green else '🟢 GREEN ✅'} BullsPower" if side=="BUY" else f"{'🔴 GREEN->RED' if bears_green_to_red else '🔴 RED ✅'} BearsPower"

            msg=f"""{'🟢🔥 BUY' if side=='BUY' else '🔴💥 SELL'} {name} v10.17 EMOJI + SPOT 24 ✅ ({sym} {'-%.0f spot' % off if off>0 else ''})
⭐⭐⭐ {side} SIGNAL {name} ⭐⭐⭐
💰 ENTRY: {fmt(entry)} LIVE: {fmt(live)} (MT5 MATCH {fmt(entry)} = GC=F -24)
🔍 CRT: {'✅ YES' if (bull_crt or bear_crt) else '❌ NO'} | CSD: {'✅ YES' if (bull_csd or bear_csd) else '❌ NO'} 💪 {bp*100:.0f}%
📊 EMA13: {fmt(ema_now)} {'📈 UP' if up else '📉 DOWN'} | {bulls_txt}
💵 {dxy_txt if name=='GOLD' else 'No DXY needed'}
📏 ATR: {fmt(atr)}
🛑 SL: {fmt(sl)}
🎯 TP1: {fmt(tp1)} -> BE 🔒
🎯 TP2: {fmt(tp2)} -> Trail TP1
🎯 TP3: {fmt(tp3)} -> Trail TP2
🎯 TP4: {fmt(tp4)} -> CLOSE 🏁
⏱️ M15 CLOSED + SPOT {fmt(live)} + 6s
{CONTACT} {BRAND} 🚀"""
            send(msg, is_buy=buy_final)

print("✅ DONE v10.17 EMOJIS RESTORED + GOLD -24 + DXY + BULLS + RED NEWS")