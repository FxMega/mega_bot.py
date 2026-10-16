import requests
import datetime

# === YOUR CONFIG - BUILT IN ===
PHONE = "256788408267"
APIKEY = "6265853"
NTFY_URL = "https://ntfy.sh/gold-ai-ug-788408267"
NTFY_TOPIC = "gold-ai-ug-788408267"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT",
         "AVAXUSDT","DOGEUSDT","DOTUSDT","LINKUSDT","MATICUSDT","SHIBUSDT"]

def send_whatsapp(msg):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(msg)}&apikey={APIKEY}"
        r = requests.get(url, timeout=30)
        print(f"WhatsApp: {r.text}")
        return True
    except Exception as e:
        print(f"WA Error: {e}")
        return False

def send_ntfy(title, msg):
    try:
        requests.post(NTFY_URL, data=msg.encode('utf-8'), headers={"Title": title}, timeout=15)
        print(f"Ntfy sent: {title}")
    except Exception as e:
        print(f"Ntfy Error: {e}")

def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10).json()
        return float(r['price'])
    except:
        return 0

# === MAIN ===
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M EAT")
prices_text = ""
for coin in COINS:
    price = get_price(coin)
    prices_text += f"{coin.replace('USDT','')}: ${price:,.2f}\n"

# ALIVE + SCAN MESSAGE - ALWAYS SENDS
msg = f"""🟢 CRYPTO BOT ALIVE
Time: {now}
Bot is RUNNING 24/7 ✅

Scanning 12 coins:
{prices_text}
Next scan in 15 min.
- FxMega System"""

print(msg)
send_whatsapp(msg)
send_ntfy("CRYPTO ALIVE", msg)

# TODO: Add BUY/SELL logic later - for now sends price snapshot every 15 min
# This proves WhatsApp works. Later we add RSI signals.
