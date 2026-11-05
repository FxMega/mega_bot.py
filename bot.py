import os, json, requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta

TD_KEY = os.environ["TWELVEDATA_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

INTERVAL, YF_INTERVAL = "15min", "15m"   # change timeframe here
EMA_N, ATR_N = 13, 14
NEWS_WINDOW = timedelta(minutes=30)       # block signals +/- 30 min around red news
TP1_X, TP2_X, TP3_X, SL_X, BE_X = 1.8, 2.5, 3.0, 1.2, 1.0
STATE_FILE = "state.json"


def tg(msg):
    """Send a push notification via ntfy."""
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Gold Alert", "Priority": "high"}, timeout=15)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"open": None, "last_signal": None}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def market_closed(now):
    wd, h = now.weekday(), now.hour
    return wd == 5 or (wd == 4 and h >= 22) or (wd == 6 and h < 22)


# ---------- data ----------
def get_gold():
    r = requests.get("https://api.twelvedata.com/time_series", params=dict(
        symbol="XAU/USD", interval=INTERVAL, outputsize=120,
        timezone="UTC", apikey=TD_KEY), timeout=20).json()
    if "values" not in r:
        raise RuntimeError(f"Twelve Data error: {r}")
    df = pd.DataFrame(r["values"]).iloc[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")[["open", "high", "low", "close"]].astype(float)
    return df.iloc[:-1]  # drop the still-forming candle


def get_dxy():
    df = yf.download("DX-Y.NYB", interval=YF_INTERVAL, period="5d",
                     progress=False, auto_adjust=True)
    df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.columns = ["open", "high", "low", "close"]
    return df.iloc[:-1]


# ---------- indicators ----------
def ema(s):
    return s.ewm(span=EMA_N, adjust=False).mean()


def atr(df):
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_N, adjust=False).mean()


def crt(g, buy):
    """Candle Range Theory: candle sweeps prior candle's low (high) and closes back inside."""
    for k in (1, 2):
        c1, c2 = g.iloc[-k - 1], g.iloc[-k]
        if buy and c2.low < c1.low and c2.close > c1.low:
            return True
        if not buy and c2.high > c1.high and c2.close < c1.high:
            return True
    return False


def csd(g, buy):
    """Change in State of Delivery: close breaks the open of the latest opposing candle run."""
    d = g.tail(10).reset_index(drop=True)
    opp = (lambda r: r.close < r.open) if buy else (lambda r: r.close > r.open)
    last = d.iloc[-1]
    if opp(last):
        return False
    i = len(d) - 2
    while i >= 0 and not opp(d.iloc[i]):
        i -= 1
    if i < 0:
        return False
    j = i
    while j - 1 >= 0 and opp(d.iloc[j - 1]):
        j -= 1
    level = d.iloc[j].open
    return last.close > level if buy else last.close < level


def red_news(now):
    """High-impact USD news from the Forex Factory weekly feed. Fails closed."""
    try:
        ev = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15).json()
        for e in ev:
            if e.get("impact") == "High" and e.get("country") == "USD":
                t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
                if abs(now - t) <= NEWS_WINDOW:
                    return True, e.get("title", "")
        return False, ""
    except Exception as ex:
        print("News fetch failed, blocking signals:", ex)
        return True, "news feed unavailable"


# ---------- strategy ----------
def check(side, g, d):
    buy = side == "BUY"
    ge, de = ema(g.close), ema(d.close)
    gp, dp = g.close.iloc[-1], d.close.iloc[-1]
    if buy:
        c1 = gp > ge.iloc[-1] and ge.iloc[-1] > ge.iloc[-2]
        c2 = dp < de.iloc[-1] and de.iloc[-1] < de.iloc[-2]
        p = g.high - ge                      # Bulls Power
        c4 = p.iloc[-1] > p.iloc[-2]         # green = rising
    else:
        c1 = gp < ge.iloc[-1] and ge.iloc[-1] < ge.iloc[-2]
        c2 = dp > de.iloc[-1] and de.iloc[-1] > de.iloc[-2]
        p = g.low - ge                       # Bears Power
        c4 = p.iloc[-1] < p.iloc[-2]         # falling = bearish
    c3 = crt(g, buy) or csd(g, buy)
    return c1 and c2 and c3 and c4


def levels(side, entry, a):
    m = 1 if side == "BUY" else -1
    return dict(side=side, entry=entry, atr=a,
                tp1=entry + m * TP1_X * a, tp2=entry + m * TP2_X * a,
                tp3=entry + m * TP3_X * a, sl=entry - m * SL_X * a,
                be=entry + m * BE_X * a, tp1_hit=False, tp2_hit=False)


def fmt(x):
    return f"{x:.2f}"


def track(trade, g, state):
    """Walk candles since last check; send TP/SL/BE alerts."""
    buy = trade["side"] == "BUY"
    for ts, c in g[g.index > pd.Timestamp(trade["last_ts"])].iterrows():
        when = f"{ts:%b %d %H:%M} UTC"
        sl_hit = c.low <= trade["sl"] if buy else c.high >= trade["sl"]

        def reached(level):
            return c.high >= level if buy else c.low <= level

        if sl_hit:  # conservative: SL checked first within a candle
            label = "BE stop (profit locked)" if trade["tp1_hit"] else "STOP LOSS"
            tg(f"{'🟡' if trade['tp1_hit'] else '🔴'} XAU/USD {trade['side']} - {label} hit at {fmt(trade['sl'])}\nCandle: {when}")
            state["open"] = None
            return
        if not trade["tp1_hit"] and reached(trade["tp1"]):
            trade["tp1_hit"] = True
            trade["sl"] = trade["be"]
            tg(f"🟢 XAU/USD {trade['side']} - TP1 hit ({fmt(trade['tp1'])}). Move SL to BE {fmt(trade['be'])}\nCandle: {when}")
        if trade["tp1_hit"] and not trade["tp2_hit"] and reached(trade["tp2"]):
            trade["tp2_hit"] = True
            tg(f"🟢 XAU/USD {trade['side']} - TP2 hit ({fmt(trade['tp2'])})\nCandle: {when}")
        if reached(trade["tp3"]):
            tg(f"🏆 XAU/USD {trade['side']} - TP3 hit ({fmt(trade['tp3'])}). Trade closed.\nCandle: {when}")
            state["open"] = None
            return
        trade["last_ts"] = str(ts)


def main():
    now = datetime.now(timezone.utc)
    if market_closed(now):
        print("Market closed")
        return
    state = load_state()
    g, d = get_gold(), get_dxy()

    if state["open"]:
        track(state["open"], g, state)
        save_state(state)
        if state["open"]:
            return  # one trade at a time

    news, title = red_news(now)
    if news:
        print("Red news window:", title)
        return

    for side in ("BUY", "SELL"):
        if check(side, g, d):
            key = f"{side}@{g.index[-1]}"
            if state["last_signal"] == key:
                return
            entry, a = g.close.iloc[-1], atr(g).iloc[-1]
            t = levels(side, entry, a)
            t["last_ts"] = str(g.index[-1])
            state["open"], state["last_signal"] = t, key
            tg(f"{'🟢' if side == 'BUY' else '🔴'} XAU/USD {side} ({INTERVAL})\n"
               f"Entry: {fmt(entry)}\nSL: {fmt(t['sl'])}\n"
               f"TP1: {fmt(t['tp1'])}\nTP2: {fmt(t['tp2'])}\nTP3: {fmt(t['tp3'])}\n"
               f"After TP1: SL to BE {fmt(t['be'])}\nATR: {fmt(a)}")
            break
    save_state(state)


if __name__ == "__main__":
    main()