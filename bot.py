import os, json, requests
import pandas as pd
import yfinance as yf
from itertools import combinations
from datetime import datetime, timezone, timedelta

TD_KEY = os.environ["TWELVEDATA_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

INTERVAL, YF_INTERVAL = "15min", "15m"   # change timeframe here
EMA_N, ATR_N = 13, 14
NEWS_WINDOW = timedelta(minutes=30)       # block signals +/- 30 min around red news
TP1_X, TP2_X, TP3_X, SL_X, BE_X = 1.8, 2.5, 3.0, 1.2, 1.0
STATE_FILE = "state.json"
FRESH_BARS = 20         # M1 shift must be within the last N M1 candles (covers delayed runs)

# --- entry-quality filters ---
ROOM_BARS = 12          # look back this many M15 candles (12 = 3 hours) for the nearest high/low
ROOM_ATR = 1.5          # need at least this x ATR of free space before that high (buy) / low (sell)
MAX_EXT_ATR = 1.5       # skip if entry is more than this x ATR away from the M15 EMA13

# --- chart pattern settings (M15) ---
PATTERN_BARS = 80       # scan the last 80 M15 candles (20 hours)
PIVOT_ORDER = 3         # a swing point needs 3 lower/higher candles on each side
PAT_TOL = 0.5           # double top/bottom: the two extremes must be within this x ATR
SHOULDER_TOL = 1.0      # head & shoulders: shoulders within this x ATR of each other
HEAD_DEPTH = 0.5        # head must stick out past the shoulders by at least this x ATR
MIN_HEIGHT = 1.0        # pattern height (extreme to neckline) must be at least this x ATR
TRI_TOL = 0.4           # triangle: flat side must be flat within this x ATR


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
    return td_candles("1min", 300)   # ~5 hours of M1, enough to catch up after delays


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
    """M1 MSS / CHoCH after `since` (plain BOS is ignored).
    Buy: M1 closes above the latest confirmed swing high while M1 was making lower highs.
    Sell: M1 closes below the latest confirmed swing low while M1 was making higher lows.
    Returns ("MSS/CHoCH", time of the breaking M1 candle) or None."""
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
            continue                # shift must come after the extreme
        prior = [i for i in swings if i <= j - 3]   # confirmed swings only
        if len(prior) < 2:
            continue                # need 2 swings to know the prior structure
        k = prior[-1]
        if buy:
            level = hi[k]
            broke = cl[j] > level and cl[j - 1] <= level
            shift = level < hi[prior[-2]]      # lower highs before = real shift
        else:
            level = lo[k]
            broke = cl[j] < level and cl[j - 1] >= level
            shift = level > lo[prior[-2]]      # higher lows before = real shift
        if broke and shift:
            return "MSS/CHoCH", w.index[j]
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


# ---------- chart patterns ----------
def pivots(hi, lo):
    """Indexes of confirmed swing highs / swing lows."""
    n, o = len(hi), PIVOT_ORDER
    highs = [i for i in range(o, n - o) if hi[i] == hi[i - o:i + o + 1].max()]
    lows = [i for i in range(o, n - o) if lo[i] == lo[i - o:i + o + 1].min()]
    return highs, lows


def pattern(g, buy):
    """Scans M15 for a completed chart pattern whose neckline/resistance was JUST broken.
    Buy: Inverse Head & Shoulders, Double Bottom, Ascending Triangle (break up).
    Sell: Head & Shoulders, Double Top, Descending Triangle (break down).
    Sells are found by flipping the price series upside down and reusing the buy logic.
    Returns (pattern name, time of the breakout candle) or None."""
    d = g.tail(PATTERN_BARS)
    if not buy:
        d = pd.DataFrame({"open": -d.open, "high": -d.low, "low": -d.high, "close": -d.close}, index=d.index)
    a = atr(g).iloc[-1]
    hi, lo, cl = d.high.values, d.low.values, d.close.values
    n = len(d)
    highs, lows = pivots(hi, lo)
    names = {True: ("Double Bottom", "Inverse Head & Shoulders", "Ascending Triangle"),
             False: ("Double Top", "Head & Shoulders", "Descending Triangle")}[buy]

    def fresh(level, start):
        """First close above `level` after `start`; it must be one of the last 2 candles
        and price must still be above the level (so old breakouts don't count)."""
        for j in range(start + 1, n):
            if cl[j] > level:
                return j if (j >= n - 2 and cl[j:].min() > level) else None
        return None

    # Head & Shoulders (inverse for buys): head clearly lower than two similar shoulders
    for l, h, r in combinations(lows[-6:], 3):
        if h - l < 3 or r - h < 3:
            continue
        if lo[h] >= min(lo[l], lo[r]) - HEAD_DEPTH * a or abs(lo[l] - lo[r]) > SHOULDER_TOL * a:
            continue
        neck = max(hi[l:h + 1].max(), hi[h:r + 1].max())
        if neck - lo[h] < MIN_HEIGHT * a:
            continue
        j = fresh(neck, r)
        if j is not None:
            return names[1], d.index[j]

    # Double Bottom / Double Top: two equal extremes, neckline = the peak between them
    for l1, l2 in combinations(lows[-5:], 2):
        if l2 - l1 < 5 or abs(lo[l1] - lo[l2]) > PAT_TOL * a:
            continue
        neck = hi[l1:l2 + 1].max()
        if neck - max(lo[l1], lo[l2]) < MIN_HEIGHT * a:
            continue
        if lo[l2:].min() < min(lo[l1], lo[l2]) - PAT_TOL * a:
            continue            # price already broke down through the bottom
        j = fresh(neck, l2)
        if j is not None:
            return names[0], d.index[j]

    # Ascending (Descending) Triangle: flat highs (lows) with rising lows (falling highs)
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2, l1, l2 = highs[-2], highs[-1], lows[-2], lows[-1]
        flat = h2 - h1 >= 4 and abs(hi[h1] - hi[h2]) <= TRI_TOL * a
        rising = l2 - l1 >= 4 and lo[l2] - lo[l1] >= 0.3 * a
        if flat and rising and max(h2, l2) - min(h1, l1) >= 10:
            j = fresh(max(hi[h1], hi[h2]), max(h2, l2))
            if j is not None:
                return names[2], d.index[j]
    return None


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


def quality_ok(g, m1, buy):
    """Entry-quality filters, judged at the actual entry price (latest M1 close):
    1. Room: enough free space before the recent high (buy) / low (sell).
       If price is already beyond that level it is a breakout, so there is no wall ahead.
    2. Extension: entry not too far from the M15 EMA13 (don't chase)."""
    a = atr(g).iloc[-1]
    px = m1.close.iloc[-1]
    e = ema(g.close).iloc[-1]
    recent = g.tail(ROOM_BARS)
    if buy:
        wall = recent.high.max()
        room = wall - px
    else:
        wall = recent.low.min()
        room = px - wall
    breakout = room <= 0
    room_ok = breakout or room >= ROOM_ATR * a
    ext = abs(px - e)
    ext_ok = ext <= MAX_EXT_ATR * a
    info = (f"room={'breakout' if breakout else f'{room:.2f}'} (need {ROOM_ATR * a:.2f}) "
            f"ext={ext:.2f} (max {MAX_EXT_ATR * a:.2f})")
    return room_ok, ext_ok, info


def check(side, g, d, m1):
    """Returns (trigger text, signal time) or None.
    The gold EMA13 / DXY EMA13 / Bulls-Bears Power filters must pass first.
    Then ANY of these triggers can fire:
      - CRT + M1 MSS/CHoCH
      - CSD + M1 MSS/CHoCH
      - a chart pattern breakout on M15 (the neckline break is its own confirmation)
    Finally the room and extension filters are applied at the entry price.
    Prints a one-line report of every filter so quiet runs can be explained."""
    buy = side == "BUY"
    t, x, p = trend_ok(g, buy), dxy_ok(d, buy), power_ok(g, buy)
    sweep = crt(g, buy)
    cs = csd(g, buy)
    b_crt = m1_break(m1, sweep, buy) if sweep is not None else None
    b_csd = m1_break(m1, g.index[-1], buy) if cs else None
    pat = pattern(g, buy)
    print(f"{side}: gold_trend={t} dxy={x} power={p} | "
          f"crt_sweep={sweep is not None} crt_mss={bool(b_crt)} csd={cs} csd_mss={bool(b_csd)} | "
          f"pattern={pat[0] if pat else False}")
    if not (t and x and p):
        return None
    tags, times = [], []
    if b_crt:
        tags.append("CRT (M1 MSS/CHoCH)")
        times.append(b_crt[1])
    if b_csd:
        tags.append("CSD (M1 MSS/CHoCH)")
        times.append(b_csd[1])
    if pat:
        tags.append(f"Pattern: {pat[0]}")
        times.append(pat[1])
    if not tags:
        return None
    room_ok, ext_ok, info = quality_ok(g, m1, buy)
    print(f"{side}: trigger found | room_ok={room_ok} ext_ok={ext_ok} | {info}")
    if not (room_ok and ext_ok):
        print(f"{side}: skipped by entry-quality filter")
        return None
    return " + ".join(tags), max(times)


def levels(side, entry, a):
    m = 1 if side == "BUY" else -1
    return dict(side=side, entry=entry, atr=a,
                tp1=entry + m * TP1_X * a, tp2=entry + m * TP2_X * a,
                tp3=entry + m * TP3_X * a, sl=entry - m * SL_X * a,
                be=entry + m * BE_X * a, tp1_hit=False, tp2_hit=False)


def fmt(x):
    return f"{x:.2f}"


def track(trade, m1, state):
    """Walk M1 candles that opened AFTER the entry candle; send TP/SL/BE alerts.
    Nothing from before the entry can count, and hits are timed to the minute."""
    buy = trade["side"] == "BUY"
    new = m1[m1.index > pd.Timestamp(trade["last_ts"])]
    print(f"Tracking {trade['side']} from {trade['entry']:.2f}: {len(new)} new M1 candle(s)")
    for ts, c in new.iterrows():
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
    g, d, m1 = get_gold(), get_dxy(), get_m1()
    print(f"Run {now:%Y-%m-%d %H:%M} UTC | last M15 candle {g.index[-1]:%H:%M} | "
          f"gold close {g.close.iloc[-1]:.2f} | DXY close {d.close.iloc[-1]:.3f}")

    if state["open"]:
        track(state["open"], m1, state)
        save_state(state)
        if state["open"]:
            print(f"Trade open ({state['open']['side']} from {state['open']['entry']:.2f}), tracking only")
            return  # one trade at a time

    news, title = red_news(now)
    if news:
        print("Red news window:", title)
        return
    print("News: clear")

    for side in ("BUY", "SELL"):
        res = check(side, g, d, m1)
        if res:
            trigger, sig_time = res
            key = f"{side}@{sig_time}"
            if state["last_signal"] == key:
                print("Signal already sent for this candle")
                return
            entry, a = m1.close.iloc[-1], atr(g).iloc[-1]
            t = levels(side, entry, a)
            t["last_ts"] = str(m1.index[-1])   # track only M1 candles after this one
            state["open"], state["last_signal"] = t, key
            tg(f"{'🟢' if side == 'BUY' else '🔴'} XAU/USD {side} ({INTERVAL}) - {trigger}\n"
               f"Entry: {fmt(entry)}\nSL: {fmt(t['sl'])}\n"
               f"TP1: {fmt(t['tp1'])}\nTP2: {fmt(t['tp2'])}\nTP3: {fmt(t['tp3'])}\n"
               f"After TP1: SL to BE {fmt(t['be'])}\nATR: {fmt(a)}")
            print(f"SIGNAL SENT: {side} - {trigger}")
            break
    else:
        print("No signal this run")
    save_state(state)


if __name__ == "__main__":
    main()