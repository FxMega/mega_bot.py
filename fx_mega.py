# 🚀 FXMEGA v13.1 FINAL - 💰 Universal Bot 💰 + 🚦 GITHUB 15 MINS
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import time, threading
import json

# 🔐 MT5 CONFIG
MT5_LOGIN = 133559628
MT5_SERVER = "Exness-MT5Real9"
MT5_PASSWORD = "247256Was@"
LOT_SIZE = 0.01

ATR_MULT_SL = 1.5
ATR_MULT_TP2 = 2.0

FOREX_PAIRS = ["EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","EURGBP","EURJPY","GBPJPY","AUDJPY","EURCHF","GBPCHF","CADJPY","AUDCAD","AUDCHF","EURAUD","GBPAUD","GBPCAD","NZDCAD","EURCAD","EURNZD"]
METALS = ["XAUUSD","XAGUSD","XAUEUR"]
CRYPTO = ["BTCUSD","ETHUSD","LINKUSD","SOLUSD","XRPUSD","LTCUSD","DOGEUSD"]
ALL_PAIRS = list(set(FOREX_PAIRS + METALS + CRYPTO))
POC_CACHE = {}
GITHUB_SIGNALS = {}

def init_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("❌ MT5 fail", mt5.last_error())
        return False
    print("✅ MT5 Connected! 🚀")
    return True

def get_data(symbol, tf, n=100):
    rates = mt5.copy_rates(symbol, tf, 0, n)
    if rates is None or len(rates) < 50: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def ema(df, p=13): return df['close'].ewm(span=p).mean()
def atr(df, p=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([hl,hc,lc], axis=1).max(axis=1)
    return tr.rolling(p).mean()
def bulls_power(df, p=13): return df['high'] - ema(df,p)
def is_uptrend(df): return ema(df,13).iloc[-1] > df['close'].ewm(span=50).mean().iloc[-1]
def is_downtrend(df): return ema(df,13).iloc[-1] < df['close'].ewm(span=50).mean().iloc[-1]

def get_poc_levels(symbol, force_update=False):
    global POC_CACHE
    daily = get_data(symbol, mt5.TIMEFRAME_D1, 5)
    if daily is None: return POC_CACHE.get(symbol)
    y = daily.iloc[-2]
    y_date = y['time'].date()
    if not force_update and symbol in POC_CACHE and POC_CACHE[symbol]['date'] == y_date:
        return POC_CACHE[symbol]
    H, L, C = y['high'], y['low'], y['close']
    Range = H - L
    POC = (H + L + C) / 3
    VAH = POC + (Range * 0.15)
    VAL = POC - (Range * 0.15)
    new_levels = {"POC":POC,"VAH":VAH,"VAL":VAL,"Range":Range,"date":y_date}
    POC_CACHE[symbol] = new_levels
    print(f"🆕 [POC UPDATED] {symbol} 📅 {y_date} 🎯 POC:{POC:.5f} 🔝 VAH:{VAH:.5f} 🔻 VAL:{VAL:.5f}")
    return new_levels

def daily_poc_updater():
    while True:
        now = datetime.now()
        if now.hour == 0 and now.minute == 5:
            print("⏰ === DAILY POC UPDATE ALL PAIRS 🌍 ===")
            for sym in ALL_PAIRS:
                get_poc_levels(sym, force_update=True)
                time.sleep(0.2)
            time.sleep(70)
        time.sleep(30)

def dxy_filter(for_buy=True):
    dxy = get_data("DXY", mt5.TIMEFRAME_M30, 100) or get_data("USDX", mt5.TIMEFRAME_M30, 100)
    if dxy is None: return True
    e = ema(dxy,13)
    below = dxy.iloc[-1]['close'] < e.iloc[-1]
    down = e.iloc[-1] < e.iloc[-5]
    return (below and down) if for_buy else (not below and not down)

def check_buy(symbol):
    df = get_data(symbol, mt5.TIMEFRAME_M30, 100)
    if df is None: return False, None
    poc = get_poc_levels(symbol)
    if poc is None: return False, None
    price = df.iloc[-1]['close']
    e13 = ema(df,13).iloc[-1]
    bp = bulls_power(df,13)
    if price < e13: return False, None
    if not is_uptrend(df): return False, None
    if not (bp.iloc[-2] < 0 and bp.iloc[-1] > 0 or bp.iloc[-1] > 0): return False, None
    if df.iloc[-1]['close'] <= df.iloc[-1]['open']: return False, None
    if price > poc["VAH"]: return False, None
    if "XAU" in symbol and not dxy_filter(True): return False, None
    if price <= poc["POC"] + poc["Range"]*0.05:
        return True, {"atr":atr(df,14).iloc[-1],"poc":poc,"price":price}
    return False, None

def check_sell(symbol):
    df = get_data(symbol, mt5.TIMEFRAME_M30, 100)
    if df is None: return False, None
    poc = get_poc_levels(symbol)
    if poc is None: return False, None
    price = df.iloc[-1]['close']
    e13 = ema(df,13).iloc[-1]
    bp = bulls_power(df,13)
    if price > e13: return False, None
    if not is_downtrend(df): return False, None
    if not (bp.iloc[-1] < 0): return False, None
    if df.iloc[-1]['close'] >= df.iloc[-1]['open']: return False, None
    if price < poc["VAL"]: return False, None
    if price >= poc["POC"] - poc["Range"]*0.05:
        return True, {"atr":atr(df,14).iloc[-1],"poc":poc,"price":price}
    return False, None

def execute(symbol, direction, info):
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if direction=="BUY" else tick.bid
    sl = price - info["atr"]*ATR_MULT_SL if direction=="BUY" else price + info["atr"]*ATR_MULT_SL
    tp = price + info["atr"]*ATR_MULT_TP2 if direction=="BUY" else price - info["atr"]*ATR_MULT_TP2
    emoji = "🟢🟢🟢 BUY" if direction=="BUY" else "🔴🔴🔴 SELL"
    req = {"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":LOT_SIZE,"type":mt5.ORDER_TYPE_BUY if direction=="BUY" else mt5.ORDER_TYPE_SELL,"price":price,"sl":sl,"tp":tp,"deviation":20,"magic":13100,"comment":f"FXMEGA {direction}","type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(req)
    print(f"{emoji} {symbol} 💰 Lot:{LOT_SIZE} SL:{sl:.5f} TP:{tp:.5f} 🎯 POC:{info['poc']['POC']:.2f}")
    return res, price, sl, tp

def save_github_signals():
    try:
        def map_symbol(sym):
            m = {"XAUUSD":"GOLD","XAGUSD":"SILVER","BTCUSD":"BTC","ETHUSD":"ETH","LINKUSD":"LINK","SOLUSD":"SOL","XRPUSD":"XRP","LTCUSD":"LTC","DOGEUSD":"DOGE"}
            return m.get(sym, sym)
        signals_data = {
            "updated": datetime.now().isoformat(),
            "source": "FxMega mega_bot.py v13.1 15min",
            "github_url": "https://raw.githubusercontent.com/FxMega/mega_bot.py/main/signals.json",
            "signals": {}
        }
        for sym in ALL_PAIRS:
            app_sym = map_symbol(sym)
            if sym in GITHUB_SIGNALS and GITHUB_SIGNALS[sym]["type"] != "WAIT":
                signals_data["signals"][app_sym] = GITHUB_SIGNALS[sym]
            else:
                if app_sym not in signals_data["signals"]:
                    signals_data["signals"][app_sym] = {"type": "WAIT", "time": datetime.now().strftime("%H:%M:%S")}
        with open("signals.json", "w") as f:
            json.dump(signals_data, f, indent=2)
        print(f"📤 [GITHUB] signals.json updated - {len(signals_data['signals'])} pairs - {datetime.now()}")
    except Exception as e:
        print(f"❌ GitHub save error: {e}")

def run():
    if not init_mt5(): return
    for sym in ALL_PAIRS: mt5.symbol_select(sym, True)
    for sym in ALL_PAIRS: get_poc_levels(sym, True)
    threading.Thread(target=daily_poc_updater, daemon=True).start()
    print(f"🚀 FXMEGA v13.1 FINAL + GITHUB 15 MINS Running - {len(ALL_PAIRS)} pairs 🌍 | POC auto-updates 00:05 ⏰ | M30 ⏳ | Lot 0.01 💵 | Writing signals.json every 15 mins")
    save_github_signals()
    while True:
        for sym in ALL_PAIRS:
            ok, info = check_buy(sym)
            if ok: 
                res, price, sl, tp = execute(sym, "BUY", info)
                GITHUB_SIGNALS[sym] = {
                    "type": "BUY",
                    "entry": float(price),
                    "sl": float(sl),
                    "be": float(price + info["atr"]*0.5),
                    "tp1": float(price + info["atr"]*1.0),
                    "tp2": float(tp),
                    "tp3": float(price + info["atr"]*3.0),
                    "score": "7/8",
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "poc": float(info["poc"]["POC"]),
                    "timer": "15:00"
                }
            else:
                ok, info = check_sell(sym)
                if ok: 
                    res, price, sl, tp = execute(sym, "SELL", info)
                    GITHUB_SIGNALS[sym] = {
                        "type": "SELL",
                        "entry": float(price),
                        "sl": float(sl),
                        "be": float(price - info["atr"]*0.5),
                        "tp1": float(price - info["atr"]*1.0),
                        "tp2": float(tp),
                        "tp3": float(price - info["atr"]*3.0),
                        "score": "7/8",
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "poc": float(info["poc"]["POC"]),
                        "timer": "15:00"
                    }
                else:
                    if sym not in GITHUB_SIGNALS:
                        GITHUB_SIGNALS[sym] = {"type": "WAIT", "time": datetime.now().strftime("%H:%M:%S")}
        save_github_signals()
        print(f"⏳ Cycle done {datetime.now()} - signals.json updated for FxMega app - Waiting 15 mins ☕ - time.sleep(900) added as you requested")
        time.sleep(900)  # ✅ 15 MINS AS YOU REQUESTED - ADDED HERE

if __name__ == "__main__":
    run()