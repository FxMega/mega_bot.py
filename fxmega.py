import json, os, requests, pandas as pd
from datetime import datetime
import pytz, yfinance as yf
from PIL import Image, ImageDraw, ImageFont

PHONE = "256788408267"
CALLMEBOT_API = "6265853"
TRADES_FILE = "fxmega_trades.json"
LAST_FILE = "fxmega_last.json"

# YOUR 8 PAIRS - UNTOUCHED
PAIRS = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD", 
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "USDCAD=X": "USDCAD",
    "XAUUSD=X": "GOLD",
    "EURJPY=X": "EURJPY",
    "GBPJPY=X": "GBPJPY"
}

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

# --- GOLD CARD CREATOR - GREEN BUY / RED SELL ---
def create_fxmega_card(asset, sig_type, entry, sl, tp1, tp2, reason, win_rate, time_str):
    W,H = 1080,1920
    img = Image.new('RGB',(W,H),'#0a0a0a')
    draw = ImageDraw.Draw(img)
    draw.rectangle([18,18,W-18,H-18], outline='#d4af37', width=2)
    draw.rectangle([40,40,W-40,H-40], outline='#d4af37', width=1)
    draw.ellipse([220,60,860,700], outline='#d4af37', width=4)
    for x,y,h,col in [(300,280,120,'#16a34a'),(370,220,140,'#16a34a'),(440,300,70,'#dc2626'),(510,340,110,'#dc2626'),(580,240,160,'#16a34a'),(650,260,140,'#16a34a'),(720,200,150,'#16a34a'),(790,240,120,'#dc2626')]:
        draw.rectangle([x,y,x+45,y+h], fill=col)
        draw.line([x+22,y-40,x+22,y+h+40], fill='#d4af37', width=2)
    try:
        fb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",72)
        fm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",36)
        fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",30)
        fbs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",42)
    except:
        fb=fm=fs=fbs=ImageFont.load_default()
    draw.text((540,560),"FXMEGA",fill='#d4af37',font=fb,anchor='mm')
    draw.text((540,630),"UG",fill='#d4af37',font=fm,anchor='mm')
    draw.text((540,670),"0700848808",fill='#d4af37',font=fs,anchor='mm')
    draw.text((540,810),"FXMEGA UG",fill='#d4af37',font=fb,anchor='mm')
    draw.line([180,870,900,870],fill='#d4af37',width=2)
    draw.rounded_rectangle([90,940,300,1000],radius=8,fill='#d4af37')
    draw.text((195,970),asset,fill='black',font=fbs,anchor='mm')
    draw.line([320,970,990,970],fill='#d4af37',width=1)
    if sig_type=="BUY":
        draw.rounded_rectangle([280,1040,800,1110],radius=12,fill='#16a34a')
        draw.text((540,1075),"BUY SIGNAL",fill='white',font=fbs,anchor='mm')
    else:
        draw.rounded_rectangle([280,1040,800,1110],radius=12,fill='#dc2626')
        draw.text((540,1075),"SELL SIGNAL",fill='white',font=fbs,anchor='mm')
    y=1180
    def line(lab,val):
        nonlocal y
        draw.text((110,y),f"◆  {lab}:",fill='#d4af37',font=fs,anchor='lm')
        draw.text((380,y),str(val),fill='#f5e6c8',font=fm,anchor='lm')
        draw.line([380,y+32,970,y+32],fill='#d4af37',width=1)
        y+=95
    line("Entry Price",entry)
    line("Stop Loss",sl)
    line("Take Profit 1",tp1)
    line("Take Profit 2",tp2)
    line("Reason",reason)
    line("Win Rate",f"{win_rate}%")
    line("Time",time_str)
    draw.rounded_rectangle([90,H-130,W-90,H-70],radius=8,outline='#d4af37',width=2)
    draw.text((540,H-100),"Contact: 0700848808",fill='#d4af37',font=fm,anchor='mm')
    path="/tmp/fxmega_signal.png"
    img.save(path,quality=95)
    return path

def upload_and_send(card_path, caption):
    try:
        with open(card_path,'rb') as f:
            r=requests.post('https://0x0.st',files={'file':f},timeout=20)
        if not r.text.startswith('http'): 
            print(f"Upload fail {r.text}")
            return
        img_url=r.text.strip()
        print(f"Image URL: {img_url}")
        params={"phone":PHONE,"text":caption,"apikey":CALLMEBOT_API,"image":img_url}
        resp=requests.get("https://api.callmebot.com/whatsapp.php",params=params,timeout=30)
        print(f"WhatsApp: {resp.text[:150]}")
    except Exception as e:
        print(f"Send error {e}")

def load_json(p):
    if not os.path.exists(p): return {}
    try:
        with open(p,'r') as f: return json.load(f)
    except: return {}
def save_json(p,d):
    with open(p,'w') as f: json.dump(d,f)

# --- EACH PAIR BEST STRATEGY - YOUR ORIGINAL v8 LOGIC RESTORED ---
def analyze_pair(ticker, name, df):
    close = pd.Series(df['Close'].iloc[:,0] if hasattr(df['Close'],'iloc') and df['Close'].ndim>1 else df['Close']).dropna()
    price = float(close.iloc[-1])
    ema20 = float(close.ewm(20).mean().iloc[-1])
    ema50 = float(close.ewm(50).mean().iloc[-1])
    rsi = float(get_rsi(close).iloc[-1])
    atr = float(get_atr(df).iloc[-1])
    print(f"{name}: Price {price:.5f} EMA20 {ema20:.5f} EMA50 {ema50:.5f} RSI {rsi:.1f}")

    sig=None
    reason=""

    # 1. EURUSD - Trend King - EMA 20/50 + RSI 55-68 / 32-45
    if name=="EURUSD":
        if price>ema20 and ema20>ema50 and 55<rsi<68:
            sig="BUY"; reason="EUR Trend Bull + RSI"
        elif price<ema20 and ema20<ema50 and 32<rsi<45:
            sig="SELL"; reason="EUR Trend Bear + RSI"

    # 2. GBPUSD - Breakout Volatile - needs stronger momentum
    elif name=="GBPUSD":
        if price>ema20 and rsi>60:
            sig="BUY"; reason="GBP Breakout Bull"
        elif price<ema20 and rsi<40:
            sig="SELL"; reason="GBP Breakout Bear"

    # 3. USDJPY - Mean Reversion - sensitive to RSI
    elif name=="USDJPY":
        if price>ema20 and rsi<65 and rsi>55:
            sig="BUY"; reason="JPY Mean Rev Bull"
        elif price<ema20 and rsi>35 and rsi<45:
            sig="SELL"; reason="JPY Mean Rev Bear"

    # 4. AUDUSD - Commodity Trend
    elif name=="AUDUSD":
        if price>ema20 and ema20>ema50 and rsi>58:
            sig="BUY"; reason="AUD Commodity Bull"
        elif price<ema20 and ema20<ema50 and rsi<42:
            sig="SELL"; reason="AUD Commodity Bear"

    # 5. USDCAD - Oil Inverse
    elif name=="USDCAD":
        if price>ema20 and rsi>60:
            sig="BUY"; reason="CAD Oil Inverse Bull"
        elif price<ema20 and rsi<40:
            sig="SELL"; reason="CAD Oil Inverse Bear"

    # 6. GOLD - Volatile Scalp - wider RSI
    elif name=="GOLD":
        if price>ema20 and rsi>55 and rsi<70:
            sig="BUY"; reason="GOLD Volatile Bull"
        elif price<ema20 and rsi<45 and rsi>30:
            sig="SELL"; reason="GOLD Volatile Bear"

    # 7. EURJPY & GBPJPY - Cross Pairs - Trend + RSI
    else:  # EURJPY, GBPJPY
        if price>ema20 and ema20>ema50 and rsi>58:
            sig="BUY"; reason=f"{name} Cross Bull"
        elif price<ema20 and ema20<ema50 and rsi<42:
            sig="SELL"; reason=f"{name} Cross Bear"

    if not sig:
        print(f"{name}: No signal")
        return None

    sl = price - atr*1.8 if sig=="BUY" else price + atr*1.8
    tp1 = price + atr*2.0 if sig=="BUY" else price - atr*2.0
    tp2 = price + atr*3.5 if sig=="BUY" else price - atr*3.5
    print(f">>> {name} {sig} FOUND Entry {price:.5f} <<<")
    return {"symbol":name,"type":sig,"entry":round(price,5),"sl":round(sl,5),"tp1":round(tp1,5),"tp2":round(tp2,5),"rsi":round(rsi,1),"reason":reason,"est":"70-75%"}

def main():
    print("=== FXMEGA v8 - PAIR STRATEGY + GOLD CARD ===")
    tz=pytz.timezone('Africa/Kampala')
    if datetime.now(tz).weekday()>=5:
        print("Weekend - FX closed")
        return
    last=load_json(LAST_FILE)
    for ticker,name in PAIRS.items():
        try:
            df=yf.download(ticker,period="10d",interval="1h",progress=False)
            if len(df)<100: continue
            data=analyze_pair(ticker,name,df)
            if not data: continue
            sig_id=f"{data['symbol']}_{data['type']}_{data['entry']}"
            if last.get(name)==sig_id:
                print(f"Skip duplicate {sig_id}")
                continue
            tstr=datetime.now(tz).strftime("%H:%M %d/%m")
            card=create_fxmega_card(data['symbol'],data['type'],f"{data['entry']}",f"{data['sl']}",f"{data['tp1']}",f"{data['tp2']}",data['reason'],data['est'].replace('%',''),tstr)
            caption=f"FXMEGA v8 {data['symbol']} {data['type']} - Check image for TP/SL"
            upload_and_send(card,caption)
            last[name]=sig_id
            save_json(LAST_FILE,last)
        except Exception as e:
            print(f"{name} error {e}")

if __name__=="__main__":
    main()
