import requests, json, os, datetime

# === YOUR CONFIG ===
PHONE = "256788408267"
APIKEY = "6265853"
NTFY_URL = "https://ntfy.sh/gold-ai-ug-788408267"
TRADES_FILE = "crypto_trades.json"

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT",
         "AVAXUSDT","DOGEUSDT","DOTUSDT","LINKUSDT","LTCUSDT","TRXUSDT"]

def send_whatsapp(msg):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={requests.utils.quote(msg)}&apikey={APIKEY}"
        requests.get(url, timeout=30)
        print(f"WA sent")
    except Exception as e:
        print(e)

def send_ntfy(title, msg):
    try:
        requests.post(NTFY_URL, data=msg.encode('utf-8'), headers={"Title": title}, timeout=10)
    except: pass

def get_price(symbol):
    try:
        return float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=10).json()['price'])
    except: return 0

def get_klines(symbol):
    try:
        data = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=15m&limit=100", timeout=10).json()
        return [float(x[4]) for x in data]
    except: return []

def ema(data, p):
    if len(data)<p: return 0
    k=2/(p+1); e=sum(data[:p])/p
    for pr in data[p:]: e=pr*k+e*(1-k)
    return e

def rsi(data, p=14):
    if len(data)<p+1: return 50
    gains=[max(data[i]-data[i-1],0) for i in range(1,len(data))]
    losses=[max(data[i-1]-data[i],0) for i in range(1,len(data))]
    ag=sum(gains[-p:])/p; al=sum(losses[-p:])/p
    if al==0: return 70
    return 100-(100/(1+ag/al))

def load_trades():
    if os.path.exists(TRADES_FILE):
        try: return json.load(open(TRADES_FILE))
        except: return {}
    return {}

def save_trades(trades):
    json.dump(trades, open(TRADES_FILE,'w'), indent=2)

# === MAIN ===
now = datetime.datetime.now().strftime("%H:%M %d/%m")
trades = load_trades()
print(f"Loaded {len(trades)} open trades")

# 1. CHECK TP/SL FOR OPEN TRADES
for coin in list(trades.keys()):
    price = get_price(coin)
    if price==0: continue
    t = trades[coin]
    entry = t['entry']; tp=t['tp']; sl=t['sl']; side=t['side']

    hit_tp = (side=="BUY" and price>=tp) or (side=="SELL" and price<=tp)
    hit_sl = (side=="BUY" and price<=sl) or (side=="SELL" and price>=sl)

    if hit_tp or hit_sl:
        result = "TP HIT ✅ PROFIT" if hit_tp else "SL HIT ❌ LOSS"
        pnl = ((price-entry)/entry*100) if side=="BUY" else ((entry-price)/entry*100)
        msg = f"""{"🟢" if hit_tp else "🔴"} CRYPTO - {coin.replace('USDT','')} {result}
Side: {side}
Entry: ${entry:,.2f}
Close: ${price:,.2f}
P/L: {pnl:.2f}%
Time: {now}
FxMega Auto-Track"""
        send_whatsapp(msg)
        send_ntfy(f"{coin} {result}", msg)
        del trades[coin]
        print(f"Closed {coin} - {result}")

save_trades(trades)

# 2. SCAN FOR NEW SIGNALS (only if no open trade for that coin)
new_signals=0
for coin in COINS:
    if coin in trades: continue # already in trade, skip
    closes = get_klines(coin)
    if len(closes)<30: continue
    price=closes[-1]; e9=ema(closes,9); e21=ema(closes,21); r=rsi(closes)
    name=coin.replace("USDT","")
    signal=None

    if e9>e21 and 45<r<70 and closes[-1]>closes[-2]:
        sl=price*0.985; tp=price*1.03; conf=int(60+(r-45))
        signal = f"🟢 CRYPTO - {name} BUY\nPrice: ${price:,.2f}\nRSI: {r:.1f}\nSL: ${sl:,.2f}\nTP: ${tp:,.2f}\nConf: {conf}%\n{now}\nFxMega"
        trades[coin]={"side":"BUY","entry":price,"sl":sl,"tp":tp,"time":now}

    elif e9<e21 and 30<r<55 and closes[-1]<closes[-2]:
        sl=price*1.015; tp=price*0.97; conf=int(60+(55-r))
        signal = f"🔴 CRYPTO - {name} SELL\nPrice: ${price:,.2f}\nRSI: {r:.1f}\nSL: ${sl:,.2f}\nTP: ${tp:,.2f}\nConf: {conf}%\n{now}\nFxMega"
        trades[coin]={"side":"SELL","entry":price,"sl":sl,"tp":tp,"time":now}

    if signal:
        new_signals+=1
        send_whatsapp(signal)
        send_ntfy(f"{name} {trades[coin]['side']}", signal)

save_trades(trades)

if new_signals==0 and len(trades)==0 and datetime.datetime.now().minute < 16:
    send_whatsapp(f"⏳ CRYPTO SCAN {now}\n12 coins - No signal\n{len(trades)} open trades\nBot active ✅")
