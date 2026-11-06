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
FRESH_BARS = 20         # M1 break must be within the last N M1 candles (covers delayed runs)


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
def td_candles(interval, size):
    r = requests.get("https://api.twelvedata.com/time_series", params=dict(
        symbol="XAU/USD", interval=interval, outputsize=size,
        timezone="UTC", apikey=TD_KEY), timeout=20).json()
    if "values" not in r:
        raise RuntimeError(f"Twelve Data error: {r}")
    df = pd.DataFrame(r["values"]).iloc[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")[["open", "high", "low", "close"]].astype(float)
    return df.iloc[:-1]  # drop the still-forming candle


def get_gold():
    return td_candles(INTERVAL, 120)


def get_m1():
    return td_candles("1min", 150)


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
    """Candle Range Theory: candle sweeps prior candle's low (high) and closes back inside.
    Returns the open time of the sweep candle, or None."""
    for k in (1, 2):
        c1, c2 = g.iloc[-k - 1], g.iloc[-k]
        if buy and c2.low < c1.low and c2.close > c1.low:
            return g.index[-k]
        if not buy and c2.high > c1.high and c2.close < c1.high:
            return g.index[-k]
    return None


def m1_break(m1, since, buy):
    """Bullish/bearish BOS or CHoCH on M1 after the M15 sweep candle opened.
    Returns (label, time of the breaking M1 candle) or None."""
    w = m1[m1.index >= since]
    n = len(w)
    if n < 8:
        return None
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    if buy:
        swings = [i for i in range(2, n - 2) if hi[i] == hi[i - 2:i + 3].max()]
        ext = int(lo.argmin())      # the sweep low
    else:
        swings = [i for i in range(2, n - 2) if lo[i] == lo[i - 2:i + 3].min()]
        ext = int(hi.argmax())      # the sweep high
    for j in range(max(3, n - FRESH_BARS), n):
        if j <= ext:
            continue                # break must come after the sweep extreme
        prior = [i for i in swings if i <= j - 3]   # confirmed swings only
        if not prior:
            continue
        k = prior[-1]
        if buy:
            level = hi[k]
            broke = cl[j] > level and cl[j - 1] <= level
            was_down = len(prior) > 1 and level < hi[prior[-2]]   # lower highs before = CHoCH
        else:
            level = lo[k]
            broke = cl[j] < level and cl[j - 1] >= level
            was_down = len(prior) > 1 and level > lo[prior[-2]]   # higher lows before = CHoCH
        if broke:
            return ("CHoCH" if was_down else "BOS"), w.index[j]
    return None


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
def trend_ok(df, buy):
    """Gold: price above EMA13 and EMA sloping up (SELL: the opposite)."""
    e = ema(df.close)
    if buy:
        return df.close.iloc[-1] > e.iloc[-1] and e.iloc[-1] > e.iloc[-2]
    return df.close.iloc[-1] < e.iloc[-1] and e.iloc[-1] < e.iloc[-2]


def dxy_ok(df, buy):
    """Gold BUY needs DXY below EMA13 and sloping down (SELL is the opposite)."""
    e = ema(df.close)
    if buy:
        return df.close.iloc[-1] < e.iloc[-1] and e.iloc[-1] < e.iloc[-2]
    return df.close.iloc[-1] > e.iloc[-1] and e.iloc[-1] > e.iloc[-2]


def power_ok(g, buy):
    """Bulls Power (buy) above zero, or rising 2 bars in a row. Bears Power mirrored for sell."""
    e = ema(g.close)
    if buy:
        p = g.high - e
        return p.iloc[-1] > 0 or (p.iloc[-1] > p.iloc[-2] > p.iloc[-3])
    p = g.low - e
    return p.iloc[-1] < 0 or (p.iloc[-1] < p.iloc[-2] < p.iloc[-3])


def check(side, g, d, m1):
    """Returns (trigger text, signal time) or None.
    CRT only counts when an M1 BOS/CHoCH confirms it. CSD works as before."""
    buy = side == "BUY"
    if not (trend_ok(g, buy) and dxy_ok(d, buy) and power_ok(g, buy)):
        return None
    tags, when = [], g.index[-1]
    sweep = crt(g, buy)
    if sweep is not None:
        b = m1_break(m1, sweep, buy)
        if b:
            tags.append(f"CRT + M1 {b[0]}")
            when = b[1]
    if csd(g, buy):
        tags.append("CSD")
    if not tags:
        return None
    return " + ".join(tags), when


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
            tg(f"{'🟡' if trade['tp1_hit'] else '🔴'} XAU/USD {trade['side']} - {label} hit at {fmt(trade['sl'])}. Trade closed.\nCandle: {when}")
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

    m1 = get_m1()
    for side in ("BUY", "SELL"):
        res = check(side, g, d, m1)
        if res:
            trigger, sig_time = res
            key = f"{side}@{sig_time}"
            if state["last_signal"] == key:
                return
            entry, a = m1.close.iloc[-1], atr(g).iloc[-1]
            t = levels(side, entry, a)
            t["last_ts"] = str(g.index[-1])
            state["open"], state["last_signal"] = t, key
            tg(f"{'🟢' if side == 'BUY' else '🔴'} XAU/USD {side} ({INTERVAL}) - {trigger}\n"
               f"Entry: {fmt(entry)}\nSL: {fmt(t['sl'])}\n"
               f"TP1: {fmt(t['tp1'])}\nTP2: {fmt(t['tp2'])}\nTP3: {fmt(t['tp3'])}\n"
               f"After TP1: SL to BE {fmt(t['be'])}\nATR: {fmt(a)}")
            break
    save_state(state)


if __name__ == "__main__":
    main()