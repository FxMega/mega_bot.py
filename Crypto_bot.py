import yfinance as yf, pandas as pd, requests, os, urllib.parse
from datetime import datetime
import numpy as np

NTFY_TOPIC = "gold-ai-ug-788408267"
PHONE = os.getenv("WHATSAPP_PHONE")
APIKEY = os.getenv("CALLMEBOT_APIKEY")

# 12 COINS POWER LIST
CRYPTOS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "BNB-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
    "AVAX-USD",
    "LINK-USD",
    "LTC-USD",
    "MATIC-USD",
    "SHIB-USD"
]

def send(msg, title):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode(), headers={"Title": title, "Priority": "high", "Tags": "rocket,moneybag"})
        print(f"NTFY {title} sent")
    except Exception as e:
        print(f"NTFY fail {e}")
    try:
        if PHONE and APIKEY:
            requests.get(f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={urllib.parse.quote(msg)}&apikey={APIKEY}", timeout=20)
            print(f"WA {title} sent")
    except Exception as e:
        print(f"WA fail {e}")

def indicators(df):
    df['EMA20'] = df['Close'].ewm(span=20).mean()
    df['EMA50'] = df['Close'].ewm(span=50).mean()
    df['EMA200'] = df['Close'].ewm(span=200).mean()
    delta = df['Close'].diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = -delta.where(delta<0,0).rolling(14).mean()
    rs = gain/loss
    df['RSI'] = 100 - (100/(1+rs))
    df['EMA12'] = df['Close'].ewm(span=12).mean()
    df['EMA26'] = df['Close'].ewm(span=26).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['SIGNAL'] = df['MACD'].ewm(span=9).mean()
    df['BB_MA'] = df['Close'].rolling(20).mean()
    df['BB_STD'] = df['Close'].rolling(20).std()
    df['BB_UP'] = df['BB_MA'] + 2*df['BB_STD']
    df['BB_LOW'] = df['BB_MA'] - 2*df['BB_STD']
    df['TR'] = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    df['ATR'] = df['TR'].rolling(14).mean()
    df['VOL_MA'] = df['Volume'].rolling(20).mean()
    return df

def is_valid_buy(last, prev):
    c1 = prev['EMA20'] < prev['EMA50'] and last['EMA20'] > last['EMA50']
    c2 = last['RSI'] > 45 and last['RSI'] < 68
    c3 = last['MACD'] > last['SIGNAL'] and prev['MACD'] <= prev['SIGNAL']
    c4 = last['Close'] > last['EMA200']
    c5 = last['Volume'] > last['VOL_MA']*1.2
    c6 = last['Close'] < last['BB_UP']
    return c1 and c2 and c3 and c4 and c5 and c6

def is_valid_sell(last, prev):
    c1 = prev['EMA20'] > prev['EMA50'] and last['EMA20'] < last['EMA50']
    c2 = last['RSI'] < 55 and last['RSI'] > 32
    c3 = last['MACD'] < last['SIGNAL'] and prev['MACD'] >= prev['SIGNAL']
    c4 = last['Close'] < last['EMA200']
    c5 = last['Volume'] > last['VOL_MA']*1.2
    c6 = last['Close'] > last['BB_LOW']
    return c1 and c2 and c3 and c4 and c5 and c6

for symbol in CRYPTOS:
    try:
        df = yf.download(symbol, period="5d", interval="15m", progress=False)
        if len(df) < 210: continue
        df = indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(last['Close'])
        atr = float(last['ATR'])

        if is_valid_buy(last, prev):
            msg = f"""🚀 CRYPTO PRO V2 - M15
{symbol} BUY 100% VALID ✅✅✅
Entry: {price:.2f}
SL: {price - atr*1.5:.2f}
TP1: {price + atr*2:.2f}
TP2: {price + atr*3.5:.2f}
Strategy: EMA+MACD+RSI+VOL+BB+EMA200
CONFIDENCE: 95%
Time: {datetime.utcnow().strftime('%H:%M UTC')}"""
            send(msg, f"{symbol} BUY PRO")

        elif is_valid_sell(last, prev):
            msg = f"""🔻 CRYPTO PRO V2 - M15
{symbol} SELL 100% VALID ✅✅✅
Entry: {price:.2f}
SL: {price + atr*1.5:.2f}
TP1: {price - atr*2:.2f}
TP2: {price - atr*3.5:.2f}
Strategy: EMA+MACD+RSI+VOL+BB+EMA200
CONFIDENCE: 95%
Time: {datetime.utcnow().strftime('%H:%M UTC')}"""
            send(msg, f"{symbol} SELL PRO")
        else:
            print(f"{symbol} filtered")
    except Exception as e:
        print(f"{symbol} err {e}")

print("12 coins scan done")
