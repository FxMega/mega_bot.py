import yfinance as yf
import pandas as pd
import requests, os
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import pytz

PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
KAMPALA = pytz.timezone('Africa/Kampala')

CRYPTOS = {
    "BTC-USD": {"name": "BITCOIN", "lev": 100, "tp1": 0.02, "tp2": 0.04, "sl": 0.015},
    "ETH-USD": {"name": "ETHEREUM", "lev": 75, "tp1": 0.025, "tp2": 0.05, "sl": 0.018},
    "SOL-USD": {"name": "SOLANA", "lev": 50, "tp1": 0.04, "tp2": 0.08, "sl": 0.025},
    "BNB-USD": {"name": "BNB", "lev": 40, "tp1": 0.02, "tp2": 0.035, "sl": 0.015},
    "XRP-USD": {"name": "XRP", "lev": 30, "tp1": 0.035, "tp2": 0.07, "sl": 0.02},
    "DOGE-USD": {"name": "DOGE", "lev": 25, "tp1": 0.05, "tp2": 0.10, "sl": 0.03},
}

def get_data(sym):
    df = yf.Ticker(sym).history(period="30d", interval="1h", auto_adjust=True)
    if df.empty or len(df) < 50: return None
    df['EMA9'] = df['Close'].ewm(span=9).mean()
    df['EMA21'] = df['Close'].ewm(span=21).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()
    df['VolAvg20'] = df['Volume'].rolling(20).mean()
    d = df['Close'].diff()
    g = (d.where(d > 0, 0)).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + g/l))
    df['BB'] = df['Close'].rolling(20).mean()
    return df

def get_signal(df):
    last = df.iloc[-1]
    price = float(last['Close'])
    rsi = float(last['RSI'])
    e9 = float(last['EMA9'])
    e21 = float(last['EMA21'])
    e50 = float(last['EMA50'])
    if e21 > e50 and e9 > e21 and 30 < rsi < 70:
        return "BUY", price, rsi
    if e21 < e50 and e9 < e21 and 30 < rsi < 70:
        return "SELL", price, rsi
    return None

def make_card(name, signal, price, tp1, tp2, sl, rsi):
    color = "#00C853" if signal=="BUY" else "#FF1744"
    img = Image.new('RGB', (1080, 1350), color)
    d = ImageDraw.Draw(img)
    try:
        b = ImageFont.truetype("DejaVuSans-Bold.ttf", 70)
        m = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 130)
        s = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
    except:
        b=m=big=s=ImageFont.load_default()
    d.text((540, 90), name, font=b, fill="white", anchor="mm")
    d.text((540, 350), signal, font=big, fill="white", anchor="mm")
    d.text((540, 500), f"${price:,.2f}", font=m, fill="white", anchor="mm")
    d.rectangle([(70, 600), (1010, 1050)], fill="white")
    d.text((540, 650), f"TP1 ${tp1:,.2f}", font=m, fill="#00C853", anchor="mm")
    d.text((540, 750), f"TP2 ${tp2:,.2f}", font=m, fill="#00C853", anchor="mm")
    d.text((540, 850), f"SL ${sl:,.2f}", font=m, fill="#D50000", anchor="mm")
    d.text((540, 950), f"RSI {rsi:.1f}", font=s, fill="black", anchor="mm")
    d.text((540, 1180), datetime.now(KAMPALA).strftime('%d %b %H:%M KAMPALA'), font=m, fill="white", anchor="mm")
    path = f"/tmp/{name}_card.jpg"
    img.save(path, quality=90)
    return path

def upload(path):
    # Try file.io first - works in GitHub
    try:
        with open(path, 'rb') as f:
            r = requests.post('https://file.io', files={'file': f}, timeout=15)
            if r.status_code == 200:
                url = r.json().get('link')
                if url:
                    print(f"UPLOAD OK file.io: {url}")
                    return url
    except Exception as e:
        print(f"file.io fail {e}")
    try:
        with open(path, 'rb') as f:
            r = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=15)
            if r.status_code == 200:
                url = r.json()['data']['url']
                print(f"UPLOAD OK tmpfiles: {url}")
                return url
    except Exception as e:
        print(f"tmpfiles fail {e}")
    return None

print("=== CRYPTOMEGA v4.5 CLEAN ===")
for sym, cfg in CRYPTOS.items():
    df = get_data(sym)
    if df is None:
        print(f"{sym} no data")
        continue
    sig = get_signal(df)
    real_price = float(df['Close'].iloc[-1])
    print(f"{sym} real price {real_price:.2f} RSI {float(df['RSI'].iloc[-1]):.1f}")
    if sig:
        signal, price, rsi = sig
        # CORRECT TP/SL MATH
        if signal == "BUY":
            tp1 = price * (1 + cfg['tp1'])
            tp2 = price * (1 + cfg['tp2'])
            sl = price * (1 - cfg['sl'])
        else:
            tp1 = price * (1 - cfg['tp1'])
            tp2 = price * (1 - cfg['tp2'])
            sl = price * (1 + cfg['sl'])
        print(f"--> {sym} {signal} ENTRY {price:.2f} TP1 {tp1:.2f} SL {sl:.2f}")
        card = make_card(cfg['name'], signal, price, tp1, tp2, sl, rsi)
        img_url = upload(card)
        caption = f"{cfg['name']} {signal}\nENTRY {price:.2f}\nTP1 {tp1:.2f}\nTP2 {tp2:.2f}\nSL {sl:.2f}\nRSI {rsi:.1f}\nLEV x{cfg['lev']}"
        enc_text = requests.utils.quote(caption)
        if img_url:
            enc_img = requests.utils.quote(img_url)
            url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}&image={enc_img}"
            print(f"SEND WITH IMAGE {img_url}")
        else:
            url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}"
            print("SEND TEXT ONLY")
        requests.get(url, timeout=20)
    else:
        print(f"{sym} No signal")
