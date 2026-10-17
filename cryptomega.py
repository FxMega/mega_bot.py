import yfinance as yf
import pandas as pd
import requests, os
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont

PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
KAMPALA = pytz.timezone('Africa/Kampala')
TEST_MODE = False  # NORMAL SIGNALS NOW!

CRYPTOS = {
    "BTC-USD": {"name": "BITCOIN", "strat": "KING_TREND", "lev": 100, "tp1": 0.02, "tp2": 0.04, "sl": 0.015},
    "ETH-USD": {"name": "ETHEREUM", "strat": "SMART_MONEY", "lev": 75, "tp1": 0.025, "tp2": 0.05, "sl": 0.018},
    "SOL-USD": {"name": "SOLANA", "strat": "BREAKOUT", "lev": 50, "tp1": 0.04, "tp2": 0.08, "sl": 0.025},
    "BNB-USD": {"name": "BNB", "strat": "RANGE_BOUNCE", "lev": 40, "tp1": 0.02, "tp2": 0.035, "sl": 0.015},
    "XRP-USD": {"name": "XRP", "strat": "PUMP_CATCHER", "lev": 30, "tp1": 0.035, "tp2": 0.07, "sl": 0.02},
    "DOGE-USD": {"name": "DOGE", "strat": "MEME_MOMO", "lev": 25, "tp1": 0.05, "tp2": 0.10, "sl": 0.03},
}

def get_data(sym):
    try:
        df = yf.download(sym, period="30d", interval="1h", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 50: return None
        df['EMA9'] = df['Close'].ewm(span=9).mean()
        df['EMA21'] = df['Close'].ewm(span=21).mean()
        df['EMA50'] = df['Close'].ewm(span=50).mean()
        df['VolAvg20'] = df['Volume'].rolling(20).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['STD20'] = df['Close'].rolling(20).std()
        df['BB_UP'] = df['SMA20'] + 2*df['STD20']
        df['BB_LOW'] = df['SMA20'] - 2*df['STD20']
        return df
    except: return None

def normal_strategy(df, strat):
    last = df.iloc[-1]; prev = df.iloc[-2]; price = last['Close']; rsi = last['RSI']
    vol_ok = last['Volume'] > last['VolAvg20']*1.1
    
    # BTC - Trend + Pullback
    if strat == "KING_TREND":
        if last['EMA21'] > last['EMA50'] and last['EMA9'] > last['EMA21'] and 38 < rsi < 68 and last['Close'] > last['SMA20']:
            return "BUY", price, rsi, "BTC UPTREND CONFIRMED"
        if last['EMA21'] < last['EMA50'] and last['EMA9'] < last['EMA21'] and 32 < rsi < 62:
            return "SELL", price, rsi, "BTC DOWNTREND"

    # ETH - Smart Money
    if strat == "SMART_MONEY":
        if last['EMA21'] > last['EMA50'] and 35 < rsi < 65 and prev['RSI'] < 55 and last['Close'] > last['EMA9']:
            return "BUY", price, rsi, "ETH PULLBACK BUY"
        if last['EMA21'] < last['EMA50'] and rsi > 55:
            return "SELL", price, rsi, "ETH WEAKNESS"

    # SOL - Breakout needs volume
    if strat == "BREAKOUT":
        if last['Close'] > last['BB_UP']*0.998 and rsi < 75 and vol_ok:
            return "BUY", price, rsi, f"SOL BREAKOUT VOL {last['Volume']/last['VolAvg20']:.1f}x"
        if last['Close'] < last['BB_LOW']*1.002 and rsi > 25:
            return "SELL", price, rsi, "SOL BREAKDOWN"

    # BNB - Range
    if strat == "RANGE_BOUNCE":
        if last['Close'] < last['BB_LOW']*1.01 and rsi < 40:
            return "BUY", price, rsi, "BNB OVERSOLD BOUNCE"
        if last['Close'] > last['BB_UP']*0.99 and rsi > 60:
            return "SELL", price, rsi, "BNB OVERBOUGHT FADE"

    # XRP - Pump
    if strat == "PUMP_CATCHER":
        if last['Volume'] > last['VolAvg20']*1.8 and last['EMA9'] > last['EMA21'] and 50 < rsi < 75:
            return "BUY", price, rsi, f"XRP PUMP {last['Volume']/last['VolAvg20']:.1f}x"
        if rsi > 75:
            return "SELL", price, rsi, "XRP PUMP END"

    # DOGE - Momentum
    if strat == "MEME_MOMO":
        if last['EMA9'] > last['EMA21'] and last['EMA21'] > last['EMA50'] and 45 < rsi < 72 and vol_ok:
            return "BUY", price, rsi, "DOGE MOMENTUM"
        if last['EMA9'] < last['EMA21'] and rsi > 60:
            return "SELL", price, rsi, "DOGE FADE"
    return None

def calc_tp_sl(price, signal, cfg):
    if signal == "BUY":
        return price*(1+cfg['tp1']), price*(1+cfg['tp2']), price*(1-cfg['sl'])
    else:
        return price*(1-cfg['tp1']), price*(1-cfg['tp2']), price*(1+cfg['sl'])

def create_gold_card(sym, info, signal, price, rsi, reason, tp1, tp2, sl):
    is_buy = signal == "BUY"; color = "#00C853" if is_buy else "#D50000"
    img = Image.new('RGB', (1080, 1500), color)
    d = ImageDraw.Draw(img)
    try:
        fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 75); fm = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
        fl = ImageFont.truetype("DejaVuSans-Bold.ttf", 140); fs = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
    except: fb = fm = fl = fs = ImageFont.load_default()
    d.text((540,100), info['name'], font=fb, fill="white", anchor="mm")
    d.text((540,170), f"{sym} | {info['strat']} | LEV x{info['lev']}", font=fs, fill="white", anchor="mm")
    d.text((540,380), signal, font=fl, fill="white", anchor="mm")
    d.text((540,560), f"ENTRY: ${price:,.4f}" if price < 10 else f"ENTRY: ${price:,.2f}", font=fm, fill="white", anchor="mm")
    d.rectangle([(80, 650), (1000, 1150)], fill="white")
    d.text((540,700), "TP / SL GOLD CARD", font=fs, fill="black", anchor="mm")
    d.text((540,780), f"TP1: ${tp1:,.4f}" if tp1<10 else f"TP1: ${tp1:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,860), f"TP2: ${tp2:,.4f}" if tp2<10 else f"TP2: ${tp2:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,940), f"SL: ${sl:,.4f}" if sl<10 else f"SL: ${sl:,.2f}", font=fm, fill="#D50000", anchor="mm")
    d.text((540,1030), f"RSI {rsi:.1f} | {reason}", font=fs, fill="black", anchor="mm")
    d.text((540,1250), f"{datetime.now(KAMPALA).strftime('%d %b %H:%M KAMPALA')}", font=fm, fill="white", anchor="mm")
    d.text((540,1330), "CRYPTOMEGA v4.2 NORMAL", font=fs, fill="white", anchor="mm")
    path = f"/tmp/{sym.replace('-','')}_card.jpg"; img.save(path, quality=95); return path

def upload_image_get_url(path):
    try:
        with open(path, 'rb') as f:
            r = requests.post('https://0x0.st', files={'file': f}, timeout=30)
            if r.status_code == 200: return r.text.strip()
    except: pass
    return None

def send_with_image(caption, image_path):
    url_img = upload_image_get_url(image_path)
    enc_text = requests.utils.quote(caption)
    if url_img:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}&image={requests.utils.quote(url_img)}"
    else:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}"
    requests.get(url, timeout=30)

print("=== CRYPTOMEGA v4.2 NORMAL SIGNALS ===")
for sym, info in CRYPTOS.items():
    df = get_data(sym)
    if df is None: continue
    sig = normal_strategy(df, info['strat'])
    if sig:
        signal, price, rsi, reason = sig
        tp1, tp2, sl = calc_tp_sl(price, signal, info)
        card = create_gold_card(sym, info, signal, price, rsi, reason, tp1, tp2, sl)
        cap = f"💎 {info['name']} {signal} 💎\n{info['strat']}\nENTRY ${price:.4f}\nTP1 ${tp1:.4f} (+{info['tp1']*100:.1f}%)\nTP2 ${tp2:.4f} (+{info['tp2']*100:.1f}%)\nSL ${sl:.4f}\nRSI {rsi:.1f}\n{reason}\nLEV x{info['lev']}"
        print(f"✅ {sym} {signal} - {reason}")
        send_with_image(cap, card)
    else:
        print(f"{sym} - No signal today (RSI {df.iloc[-1]['RSI']:.1f})")
