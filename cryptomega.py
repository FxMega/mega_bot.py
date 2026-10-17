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

def get_data(sym):
    try:
        df = yf.download(sym, period="60d", interval="1h", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        df['EMA9'] = df['Close'].ewm(span=9).mean()
        df['EMA21'] = df['Close'].ewm(span=21).mean()
        df['EMA50'] = df['Close'].ewm(span=50).mean()
        df['EMA200'] = df['Close'].ewm(span=200).mean()
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

def best_strategy(df, strat):
    last = df.iloc[-1]; prev = df.iloc[-2]; price = last['Close']; rsi = last['RSI']
    if strat == "KING_TREND":
        if last['EMA50'] > last['EMA200'] and last['EMA9'] > last['EMA21'] and prev['EMA9'] <= prev['EMA21'] and 45 < rsi < 65:
            return "BUY", price, rsi, "BTC UPTREND + EMA9 CROSS"
        if last['EMA50'] < last['EMA200'] and last['EMA9'] < last['EMA21'] and prev['EMA9'] >= prev['EMA21'] and 35 < rsi < 55:
            return "SELL", price, rsi, "BTC DOWNTREND"
    if strat == "SMART_MONEY":
        if last['EMA21'] > last['EMA50'] and last['Close'] > last['SMA20'] and 40 < rsi < 60 and prev['RSI'] < 40:
            return "BUY", price, rsi, "ETH PULLBACK BOUNCE"
        if last['EMA21'] < last['EMA50'] and last['Close'] < last['SMA20'] and 40 < rsi < 70:
            return "SELL", price, rsi, "ETH WEAKNESS"
    if strat == "BREAKOUT":
        if last['Close'] > last['BB_UP'] and last['Volume'] > last['VolAvg20']*1.8 and rsi < 75:
            return "BUY", price, rsi, f"SOL BREAKOUT {last['Volume']/last['VolAvg20']:.1f}x VOL"
        if last['Close'] < last['BB_LOW'] and last['Volume'] > last['VolAvg20']*1.5:
            return "SELL", price, rsi, "SOL BREAKDOWN"
    if strat == "RANGE_BOUNCE":
        if last['Close'] < last['BB_LOW'] and rsi < 35: return "BUY", price, rsi, "BNB BB BOUNCE"
        if last['Close'] > last['BB_UP'] and rsi > 65: return "SELL", price, rsi, "BNB BB FADE"
    if strat == "PUMP_CATCHER":
        if last['Volume'] > last['VolAvg20']*2.5 and rsi > 55 and last['EMA9'] > last['EMA21']:
            return "BUY", price, rsi, f"XRP PUMP {last['Volume']/last['VolAvg20']:.1f}x"
        if last['RSI'] > 78: return "SELL", price, rsi, "XRP EXHAUSTED"
    if strat == "MEME_MOMO":
        if last['EMA9'] > last['EMA21'] and last['EMA21'] > last['EMA50'] and last['Volume'] > last['VolAvg20']*1.5 and 50 < rsi < 70:
            return "BUY", price, rsi, "DOGE MOMENTUM"
        if last['EMA9'] < last['EMA21'] and rsi > 65: return "SELL", price, rsi, "DOGE HYPE FADE"
    return None

def calc_tp_sl(price, signal, cfg):
    if signal == "BUY":
        tp1 = price * (1 + cfg['tp1']); tp2 = price * (1 + cfg['tp2']); sl = price * (1 - cfg['sl'])
    else:
        tp1 = price * (1 - cfg['tp1']); tp2 = price * (1 - cfg['tp2']); sl = price * (1 + cfg['sl'])
    return tp1, tp2, sl

def create_gold_card(sym, info, signal, price, rsi, reason, tp1, tp2, sl):
    is_buy = signal == "BUY"; color = "#00C853" if is_buy else "#D50000"
    img = Image.new('RGB', (1080, 1500), color)
    d = ImageDraw.Draw(img)
    try:
        fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 80); fm = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
        fl = ImageFont.truetype("DejaVuSans-Bold.ttf", 140); fs = ImageFont.truetype("DejaVuSans-Bold.ttf", 35)
    except: fb = fm = fl = fs = ImageFont.load_default()
    d.text((540,100), info['name'], font=fb, fill="white", anchor="mm")
    d.text((540,180), f"{sym} | {info['strat']} | LEV x{info['lev']}", font=fs, fill="white", anchor="mm")
    d.text((540,380), signal, font=fl, fill="white", anchor="mm")
    price_txt = f"${price:,.5f}" if price < 1 else f"${price:,.2f}"
    d.text((540,580), f"ENTRY: {price_txt}", font=fm, fill="white", anchor="mm")
    d.rectangle([(80, 680), (1000, 1150)], fill="white")
    d.text((540,730), "TAKE PROFIT / STOP LOSS", font=fs, fill="black", anchor="mm")
    d.text((540,800), f"TP1: ${tp1:,.5f}" if tp1 < 1 else f"TP1: ${tp1:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,880), f"TP2: ${tp2:,.5f}" if tp2 < 1 else f"TP2: ${tp2:,.2f}", font=fm, fill="#00C853", anchor="mm")
    d.text((540,960), f"SL: ${sl:,.5f}" if sl < 1 else f"SL: ${sl:,.2f}", font=fm, fill="#D50000", anchor="mm")
    d.text((540,1040), f"RSI: {rsi:.1f} | {reason}", font=fs, fill="black", anchor="mm")
    d.text((540,1250), f"{datetime.now(KAMPALA).strftime('%d %b %H:%M KAMPALA')}", font=fm, fill="white", anchor="mm")
    d.text((540,1320), "CRYPTOMEGA v4 | IMAGE API", font=fs, fill="white", anchor="mm")
    path = f"/tmp/{sym}_card.jpg"; img.save(path, quality=95); return path

# === NEW: CALLMEBOT IMAGE API ===
def upload_image_get_url(image_path):
    """Upload to 0x0.st (free, no key) and return public URL"""
    try:
        with open(image_path, 'rb') as f:
            r = requests.post('https://0x0.st', files={'file': f}, timeout=30)
            if r.status_code == 200:
                url = r.text.strip()
                print(f"Image uploaded: {url}")
                return url
    except Exception as e:
        print(f"Upload failed: {e}")
    return None

def send_whatsapp_with_image(caption, image_path):
    public_url = upload_image_get_url(image_path)
    if public_url:
        # CallMeBot image param
        encoded_text = requests.utils.quote(caption)
        encoded_img = requests.utils.quote(public_url)
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={encoded_text}&apikey={APIKEY}&image={encoded_img}"
        try:
            r = requests.get(url, timeout=30)
            print(f"Send with image: {r.text} | Status {r.status_code}")
            return True
        except Exception as e:
            print(f"Send image failed: {e}")
            # Fallback to text only
            url2 = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={encoded_text}&apikey={APIKEY}"
            requests.get(url2, timeout=20)
            return False
    else:
        # Fallback text
        encoded_text = requests.utils.quote(caption)
        url2 = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={encoded_text}&apikey={APIKEY}"
        requests.get(url2, timeout=20)
        return False

print("=== CRYPTOMEGA v4 IMAGE API ===")
for sym, info in CRYPTOS.items():
    df = get_data(sym)
    if df is None or len(df) < 100: continue
    sig = best_strategy(df, info['strat'])
    if sig:
        signal, price, rsi, reason = sig
        tp1, tp2, sl = calc_tp_sl(price, signal, info)
        card_path = create_gold_card(sym, info, signal, price, rsi, reason, tp1, tp2, sl)
        cap = f"💎 {info['name']} {signal} 💎\nENTRY ${price:.4f}\nTP1 ${tp1:.4f}\nTP2 ${tp2:.4f}\nSL ${sl:.4f}\nRSI {rsi:.1f}\n{reason}\nLEV x{info['lev']}"
        print(f"Sending {sym} with IMAGE...")
        send_whatsapp_with_image(cap, card_path)
    else:
        print(f"{sym} - No signal")
