import yfinance as yf
import pandas as pd
import requests, os
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont

PHONE = os.getenv("WHATSAPP_PHONE", "256788408267")
APIKEY = os.getenv("CALLMEBOT_APIKEY", "6265853")
KAMPALA = pytz.timezone('Africa/Kampala')

CRYPTOS = {
    "BTC-USD": {"name": "BITCOIN", "strat": "KING_TREND", "lev": 100, "tp1": 0.02, "tp2": 0.04, "sl": 0.015},
    "ETH-USD": {"name": "ETHEREUM", "strat": "SMART_MONEY", "lev": 75, "tp1": 0.025, "tp2": 0.05, "sl": 0.018},
    "SOL-USD": {"name": "SOLANA", "strat": "BREAKOUT", "lev": 50, "tp1": 0.04, "tp2": 0.08, "sl": 0.025},
    "BNB-USD": {"name": "BNB", "strat": "RANGE_BOUNCE", "lev": 40, "tp1": 0.02, "tp2": 0.035, "sl": 0.015},
    "XRP-USD": {"name": "XRP", "strat": "PUMP_CATCHER", "lev": 30, "tp1": 0.035, "tp2": 0.07, "sl": 0.02},
    "DOGE-USD": {"name": "DOGE", "strat": "MEME_MOMO", "lev": 25, "tp1": 0.05, "tp2": 0.10, "sl": 0.03},
}

def get_data_fixed(sym):
    try:
        # FIXED: Use Ticker.history - more reliable than download
        ticker = yf.Ticker(sym)
        df = ticker.history(period="30d", interval="1h", auto_adjust=True)
        if df.empty:
            print(f"{sym} empty")
            return None
        df = df.dropna()
        if len(df) < 50:
            return None
        # Indicators
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
        last_price = float(df['Close'].iloc[-1])
        print(f"{sym} price OK: {last_price}")
        return df
    except Exception as e:
        print(f"{sym} error {e}")
        return None

def normal_strategy(df, strat):
    last = df.iloc[-1]; prev = df.iloc[-2]; price = float(last['Close']); rsi = float(last['RSI'])
    vol_ok = float(last['Volume']) > float(last['VolAvg20'])*1.05
    
    if strat == "KING_TREND":
        if last['EMA21'] > last['EMA50'] and last['EMA9'] > last['EMA21'] and 38 < rsi < 68:
            return "BUY", price, rsi, "BTC UPTREND CONFIRMED"
        if last['EMA21'] < last['EMA50'] and last['EMA9'] < last['EMA21'] and 32 < rsi < 62:
            return "SELL", price, rsi, "BTC DOWNTREND"
    if strat == "SMART_MONEY":
        if last['EMA21'] > last['EMA50'] and 35 < rsi < 65 and float(prev['RSI']) < 55:
            return "BUY", price, rsi, "ETH PULLBACK BUY"
        if last['EMA21'] < last['EMA50'] and rsi > 50:
            return "SELL", price, rsi, "ETH WEAKNESS"
    if strat == "BREAKOUT":
        if last['Close'] > last['BB_UP']*0.998 and rsi < 76 and vol_ok:
            return "BUY", price, rsi, f"SOL BREAKOUT"
        if last['Close'] < last['BB_LOW']*1.002:
            return "SELL", price, rsi, "SOL BREAKDOWN"
    if strat == "RANGE_BOUNCE":
        if last['Close'] < last['BB_LOW']*1.01 and rsi < 42:
            return "BUY", price, rsi, "BNB OVERSOLD BOUNCE"
        if last['Close'] > last['BB_UP']*0.99 and rsi > 58:
            return "SELL", price, rsi, "BNB OVERBOUGHT FADE"
    if strat == "PUMP_CATCHER":
        if float(last['Volume']) > float(last['VolAvg20'])*1.6 and last['EMA9'] > last['EMA21'] and 50 < rsi < 76:
            return "BUY", price, rsi, f"XRP PUMP"
        if rsi > 75: return "SELL", price, rsi, "XRP PUMP END"
    if strat == "MEME_MOMO":
        if last['EMA9'] > last['EMA21'] and last['EMA21'] > last['EMA50'] and 45 < rsi < 73 and vol_ok:
            return "BUY", price, rsi, "DOGE MOMENTUM"
        if last['EMA9'] < last['EMA21'] and rsi > 58:
            return "SELL", price, rsi, "DOGE FADE"
    return None

def calc_tp_sl(price, signal, cfg):
    price = float(price)
    if signal == "BUY":
        tp1 = price * (1 + cfg['tp1']); tp2 = price * (1 + cfg['tp2']); sl = price * (1 - cfg['sl'])
    else:
        tp1 = price * (1 - cfg['tp1']); tp2 = price * (1 - cfg['tp2']); sl = price * (1 + cfg['sl'])
    return float(tp1), float(tp2), float(sl)

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
    txt_price = f"${price:,.4f}" if price < 10 else f"${price:,.2f}"
    d.text((540,560), f"ENTRY: {txt_price}", font=fm, fill="white", anchor="mm")
    d.rectangle([(80, 650), (1000, 1150)], fill="white")
    d.text((540,700), "TP / SL GOLD CARD", font=fs, fill="black", anchor="mm")
    d.text((540,780), f"TP1: ${tp1:,.4f}" if tp1<10 else f"TP1: ${tp1:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,860), f"TP2: ${tp2:,.4f}" if tp2<10 else f"TP2: ${tp2:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,940), f"SL: ${sl:,.4f}" if sl<10 else f"SL: ${sl:,.2f}", font=fm, fill="#D50000", anchor="mm")
    d.text((540,1030), f"RSI {rsi:.1f} | {reason}", font=fs, fill="black", anchor="mm")
    d.text((540,1250), f"{datetime.now(KAMPALA).strftime('%d %b %H:%M KAMPALA')}", font=fm, fill="white", anchor="mm")
    d.text((540,1330), "CRYPTOMEGA v4.3 FIXED", font=fs, fill="white", anchor="mm")
    path = f"/tmp/{sym.replace('-','')}_card.jpg"; img.save(path, quality=95); return path

def upload_catbox(path):
    try:
        with open(path, 'rb') as f:
            r = requests.post('https://catbox.moe/user/api.php', data={'reqtype':'fileupload'}, files={'fileToUpload': f}, timeout=30)
            if r.status_code == 200 and 'catbox' in r.text:
                url = r.text.strip()
                print(f"CATBOX UPLOADED: {url}")
                return url
    except Exception as e: print(f"Catbox fail {e}")
    # Fallback 0x0.st
    try:
        with open(path, 'rb') as f:
            r = requests.post('https://0x0.st', files={'file': f}, timeout=30)
            if r.status_code == 200: return r.text.strip()
    except: pass
    return None

def send_with_image(caption, image_path):
    url_img = upload_catbox(image_path)
    enc_text = requests.utils.quote(caption)
    if url_img:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}&image={requests.utils.quote(url_img)}"
        print(f"Sending WITH IMAGE: {url_img}")
    else:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={enc_text}&apikey={APIKEY}"
        print("Sending TEXT ONLY - upload failed")
    r = requests.get(url, timeout=30)
    print(f"WA Response: {r.text[:300]}")

print("=== CRYPTOMEGA v4.3 FIXED PRICE ===")
for sym, info in CRYPTOS.items():
    df = get_data_fixed(sym)
    if df is None: continue
    sig = normal_strategy(df, info['strat'])
    if sig:
        signal, price, rsi, reason = sig
        tp1, tp2, sl = calc_tp_sl(price, signal, info)
        # Correct % display for SELL
        if signal == "SELL":
            tp1_pct = f"-{info['tp1']*100:.1f}%"; tp2_pct = f"-{info['tp2']*100:.1f}%"; sl_pct = f"+{info['sl']*100:.1f}%"
        else:
            tp1_pct = f"+{info['tp1']*100:.1f}%"; tp2_pct = f"+{info['tp2']*100:.1f}%"; sl_pct = f"-{info['sl']*100:.1f}%"
        card = create_gold_card(sym, info, signal, price, rsi, reason, tp1, tp2, sl)
        cap = f"💎 {info['name']} {signal} 💎\n{info['strat']}\nENTRY ${price:.2f}\nTP1 ${tp1:.2f} ({tp1_pct})\nTP2 ${tp2:.2f} ({tp2_pct})\nSL ${sl:.2f} ({sl_pct})\nRSI {rsi:.1f}\n{reason}\nLEV x{info['lev']}"
        print(f"✅ {sym} {signal} ENTRY {price} TP1 {tp1} SL {sl}")
        send_with_image(cap, card)
    else:
        last_p = float(df['Close'].iloc[-1]); last_rsi = float(df['RSI'].iloc[-1])
        print(f"{sym} - No signal - Price {last_p:.2f} RSI {last_rsi:.1f}")
