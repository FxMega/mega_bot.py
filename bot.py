import os, json, requests
import numpy as np
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

# --- chart pattern settings ---
# (name, candles to scan, breakout must be within the last N candles of that timeframe)
PATTERN_TFS = [("M15", 80, 2), ("M5", 80, 4), ("M1", 100, 15)]
PIVOT_ORDER = 4         # a swing point needs 4 lower/higher candles on each side
PAT_TOL = 0.35          # double/triple top-bottom: extremes must be within this x ATR
SHOULDER_TOL = 0.6      # head & shoulders: shoulders within this x ATR of each other
HEAD_DEPTH = 1.0        # head must stick out past the shoulders by at least this x ATR
MIN_HEIGHT = 2.0        # pattern height must be at least this x ATR
TRI_TOL = 0.3           # flat side of a triangle / rectangle must be flat within this x ATR
FLAG_POLE_ATR = 3.0     # a flag's pole must be at least this x ATR tall
SLOPE_MIN = 0.8         # triangle / wedge lines must move at least this x ATR between their two points
SEEN_KEEP = 60          # remember this many sent triggers so none is alerted twice

# --- learning memory ---
MIN_SAMPLES = 5         # a setup needs this many closed results before memory judges its win rate
SKIP_BELOW = 0.35       # skip a setup whose (smoothed) win rate is below this
PROVEN_ABOVE = 0.60     # label a setup "proven" at or above this win rate
LOSS_STREAK = 3         # skip a setup after this many losses in a row (latest results)
MEMORY_WINDOW = 30      # only the latest N results of a setup count (markets change)
JOURNAL_KEEP = 400      # trade results kept in state.json
MAX_SHADOW = 6          # skipped signals still followed on paper so the bot keeps learning
NOTIFY_SKIPS = True     # send a quiet ntfy message when memory skips a signal


def tg(msg, priority="high"):
    """Send a push notification via ntfy."""
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Gold Alert", "Priority": priority}, timeout=15)


def load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("open", None)
    s.setdefault("seen", [])
    s.setdefault("journal", [])   # every closed trade: setup, session, win/loss
    s.setdefault("shadow", [])    # skipped signals followed on paper
    return s


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
    return td_candles("1min", 480)   # 8 hours of M1: also builds the M5 chart, no extra API call


def to_m5(m1):
    """Build M5 candles from M1. Only complete 5-minute buckets are kept."""
    r = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    cnt = m1.close.resample("5min").count()
    return r[cnt == 5].dropna()


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
    """Indexes of confirmed swing highs / swing lows (one pivot per tied plateau)."""
    n, o = len(hi), PIVOT_ORDER
    highs = [i for i in range(o, n - o)
             if hi[i] > hi[i - o:i].max() and hi[i] >= hi[i + 1:i + o + 1].max()]
    lows = [i for i in range(o, n - o)
            if lo[i] < lo[i - o:i].min() and lo[i] <= lo[i + 1:i + o + 1].min()]
    return highs, lows


def pattern(df, buy, bars, fresh_bars):
    """Scans one timeframe for a completed pattern that has JUST broken out.
    Buy patterns (break up): Inverse Head & Shoulders, Triple Bottom, Double Bottom,
      Rectangle, Ascending Triangle, Symmetrical Triangle, Falling Wedge, Bull Flag.
    Sell patterns (break down): Head & Shoulders, Triple Top, Double Top, Rectangle,
      Descending Triangle, Symmetrical Triangle, Rising Wedge, Bear Flag.
    Sells are found by flipping the price series upside down and reusing the buy logic.
    Returns (pattern name, time of the breakout candle) or None."""
    if len(df) < 30:
        return None
    a = atr(df).iloc[-1]
    d = df.tail(bars)
    if not buy:
        d = pd.DataFrame({"open": -d.open, "high": -d.low, "low": -d.high, "close": -d.close}, index=d.index)
    hi, lo, cl = d.high.values, d.low.values, d.close.values
    n = len(d)
    x = np.arange(n)
    highs, lows = pivots(hi, lo)
    nm = {True: ("Inverse Head & Shoulders", "Triple Bottom", "Double Bottom", "Rectangle (break up)",
                 "Ascending Triangle", "Symmetrical Triangle (break up)", "Falling Wedge", "Bull Flag"),
          False: ("Head & Shoulders", "Triple Top", "Double Top", "Rectangle (break down)",
                  "Descending Triangle", "Symmetrical Triangle (break down)", "Rising Wedge", "Bear Flag")}[buy]

    def flat(v):
        return np.full(n, v)

    def fresh(level, start):
        """First close above `level` (an array) after `start`. It must be among the last
        `fresh_bars` candles and price must still be above the level, so old breakouts don't count."""
        for j in range(start + 1, n):
            if cl[j] > level[j]:
                ok = j >= n - fresh_bars and bool((cl[j:] > level[j:]).all())
                return j if ok else None
        return None

    # 1. Head & Shoulders (inverse for buys): head clearly lower than two similar shoulders
    for l, h, r in combinations(lows[-6:], 3):
        if h - l < 3 or r - h < 3:
            continue
        if lo[h] >= min(lo[l], lo[r]) - HEAD_DEPTH * a or abs(lo[l] - lo[r]) > SHOULDER_TOL * a:
            continue
        neck = max(hi[l:h + 1].max(), hi[h:r + 1].max())
        if neck - lo[h] < MIN_HEIGHT * a:
            continue
        j = fresh(flat(neck), r)
        if j is not None:
            return nm[0], d.index[j]

    # 2. Triple Bottom / Triple Top
    for l1, l2, l3 in combinations(lows[-6:], 3):
        if l2 - l1 < 4 or l3 - l2 < 4:
            continue
        v = (lo[l1], lo[l2], lo[l3])
        if max(v) - min(v) > PAT_TOL * a:
            continue
        neck = hi[l1:l3 + 1].max()
        if neck - max(v) < MIN_HEIGHT * a or lo[l3:].min() < min(v) - PAT_TOL * a:
            continue
        j = fresh(flat(neck), l3)
        if j is not None:
            return nm[1], d.index[j]

    # 3. Bull Flag (Bear Flag): sharp pole up, then a drifting pullback, then a break above it
    for p1 in highs[-4:]:
        if p1 < 5 or n - p1 > 30:
            continue
        s0 = max(0, p1 - 12)
        p0 = s0 + int(lo[s0:p1 + 1].argmin())
        rise = hi[p1] - lo[p0]
        if rise < FLAG_POLE_ATR * a:
            continue
        qs = [q for q in highs if q - p1 >= 4 and hi[q] <= hi[p1]]
        if not qs or lo[p1:].min() < hi[p1] - 0.5 * rise:
            continue            # no pullback high, or the pullback retraced more than half the pole
        q = qs[-1]
        upper = hi[p1] + ((hi[q] - hi[p1]) / (q - p1)) * (x - p1)
        j = fresh(upper, q)
        if j is not None:
            return nm[7], d.index[j]

    # 4-7. Two-line patterns built from the last 2 swing highs and the last 2 swing lows
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2, l1, l2 = highs[-2], highs[-1], lows[-2], lows[-1]
        if h2 - h1 >= 4 and l2 - l1 >= 4 and max(h2, l2) - min(h1, l1) >= 10:
            top_slope = (hi[h2] - hi[h1]) / (h2 - h1)
            bot_slope = (lo[l2] - lo[l1]) / (l2 - l1)
            upper = hi[h1] + top_slope * (x - h1)
            lower = lo[l1] + bot_slope * (x - l1)
            xa, xb = min(h1, l1), max(h2, l2)
            w0, w1 = upper[xa] - lower[xa], upper[xb] - lower[xb]
            converging = 0 < w1 < 0.8 * w0
            top_flat = abs(hi[h1] - hi[h2]) <= TRI_TOL * a
            bot_flat = abs(lo[l1] - lo[l2]) <= TRI_TOL * a
            start = xb
            found = None
            if top_flat and bot_flat and upper[xb] - lower[xb] >= MIN_HEIGHT * a:
                found = (nm[3], flat(max(hi[h1], hi[h2])))
            elif top_flat and lo[l2] - lo[l1] >= SLOPE_MIN * a:
                found = (nm[4], flat(max(hi[h1], hi[h2])))
            elif converging and hi[h1] - hi[h2] >= SLOPE_MIN * a and lo[l2] - lo[l1] >= SLOPE_MIN * a:
                found = (nm[5], upper)
            elif converging and hi[h1] - hi[h2] >= SLOPE_MIN * a and top_slope < bot_slope < 0:
                found = (nm[6], upper)
            if found:
                j = fresh(found[1], start)
                if j is not None:
                    return found[0], d.index[j]

    # 8. Double Bottom / Double Top: two equal extremes, neckline = the peak between them
    for l1, l2 in combinations(lows[-5:], 2):
        if l2 - l1 < 5 or abs(lo[l1] - lo[l2]) > PAT_TOL * a:
            continue
        neck = hi[l1:l2 + 1].max()
        if neck - max(lo[l1], lo[l2]) < MIN_HEIGHT * a:
            continue
        if lo[l2:].min() < min(lo[l1], lo[l2]) - PAT_TOL * a:
            continue            # price already broke down through the bottom
        j = fresh(flat(neck), l2)
        if j is not None:
            return nm[2], d.index[j]

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


def check(side, g, d, m1, m5):
    """Returns a list of (trigger text, trigger time) or None.
    The gold EMA13 / DXY EMA13 / Bulls-Bears Power filters (M15) must pass first.
    Then ANY of these triggers can fire:
      - CRT + M1 MSS/CHoCH
      - CSD + M1 MSS/CHoCH
      - a chart pattern breakout on M15, M5 or M1
    Finally the room and extension filters are applied at the entry price.
    Prints a one-line report of every filter so quiet runs can be explained."""
    buy = side == "BUY"
    t, x, p = trend_ok(g, buy), dxy_ok(d, buy), power_ok(g, buy)
    sweep = crt(g, buy)
    cs = csd(g, buy)
    b_crt = m1_break(m1, sweep, buy) if sweep is not None else None
    b_csd = m1_break(m1, g.index[-1], buy) if cs else None
    frames = {"M15": g, "M5": m5, "M1": m1}
    pats = {}
    for tf, bars, fb in PATTERN_TFS:
        r = pattern(frames[tf], buy, bars, fb)
        if r:
            pats[tf] = r
    print(f"{side}: gold_trend={t} dxy={x} power={p} | "
          f"crt_sweep={sweep is not None} crt_mss={bool(b_crt)} csd={cs} csd_mss={bool(b_csd)} | "
          f"patterns={ {tf: r[0] for tf, r in pats.items()} or False }")
    if not (t and x and p):
        return None
    trig = []
    if b_crt:
        trig.append(("CRT (M1 MSS/CHoCH)", b_crt[1]))
    if b_csd:
        trig.append(("CSD (M1 MSS/CHoCH)", b_csd[1]))
    for tf, (name, ts) in pats.items():
        trig.append((f"Pattern: {name} ({tf})", ts))
    if not trig:
        return None
    room_ok, ext_ok, info = quality_ok(g, m1, buy)
    print(f"{side}: trigger found | room_ok={room_ok} ext_ok={ext_ok} | {info}")
    if not (room_ok and ext_ok):
        print(f"{side}: skipped by entry-quality filter")
        return None
    return trig


def levels(side, entry, a):
    m = 1 if side == "BUY" else -1
    return dict(side=side, entry=entry, atr=a,
                tp1=entry + m * TP1_X * a, tp2=entry + m * TP2_X * a,
                tp3=entry + m * TP3_X * a, sl=entry - m * SL_X * a,
                be=entry + m * BE_X * a, tp1_hit=False, tp2_hit=False)


def fmt(x):
    return f"{x:.2f}"


# ---------- learning memory ----------
def session_of(ts):
    h = ts.hour
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 17:
        return "NewYork"
    if 17 <= h < 22:
        return "LateNY"
    return "Asia"


def results_for(journal, side, kind, session=None):
    """Win/loss history (oldest to newest) of one setup, optionally within one session."""
    r = [j["win"] for j in journal
         if j["side"] == side and kind in j.get("kinds", []) and (session is None or j.get("session") == session)]
    return r[-MEMORY_WINDOW:]


def judge(journal, side, kind, session):
    """Memory's verdict on one trigger: ("skip" | "proven" | "ok" | "new", short text).
    Looks at this setup in the current session first, then at the setup overall."""
    for sess in (session, None):
        r = results_for(journal, side, kind, sess)
        label = f"{sum(r)}/{len(r)} won" + (f" in {sess}" if sess else "")
        if len(r) >= LOSS_STREAK and not any(r[-LOSS_STREAK:]):
            return "skip", f"{LOSS_STREAK} losses in a row ({label})"
        if len(r) >= MIN_SAMPLES:
            rate = (sum(r) + 2) / (len(r) + 4)        # smoothed so tiny samples don't swing it
            if rate < SKIP_BELOW:
                return "skip", f"weak record ({label})"
            if rate >= PROVEN_ABOVE:
                return "proven", label
            return "ok", label
    return "new", "no history yet"


def record(state, trade, out, shadow):
    """Store a closed trade (real or paper) in the journal."""
    state["journal"].append(dict(time=trade.get("time", ""), side=trade["side"],
                                 kinds=trade.get("kinds", []), session=trade.get("session", ""),
                                 win=bool(out["win"]), stage=out["stage"], shadow=shadow))
    state["journal"] = state["journal"][-JOURNAL_KEEP:]
    print(f"Journal: {trade['side']} {out['stage']} ({'win' if out['win'] else 'loss'})"
          f"{' [paper]' if shadow else ''} setups={trade.get('kinds', [])}")


def print_memory(journal):
    stats = {}
    for j in journal:
        for k in j.get("kinds", []):
            key = f"{j['side']}|{k}"
            w, n = stats.get(key, (0, 0))
            stats[key] = (w + int(j["win"]), n + 1)
    for key, (w, n) in sorted(stats.items(), key=lambda kv: -kv[1][1])[:8]:
        print(f"Memory {key}: {w}/{n} won")


def new_trade(side, entry, a, now, m1, kinds):
    t = levels(side, entry, a)
    t.update(last_ts=str(m1.index[-1]),    # track only M1 candles after this one
             time=str(now), kinds=kinds, session=session_of(now))
    return t


def track(trade, m1, notify=True):
    """Walk M1 candles that opened AFTER the entry candle.
    Real trades send TP/SL/BE alerts; paper trades run silently.
    Returns {"win": bool, "stage": "SL"|"BE"|"TP3"} when the trade closes, else None.
    A trade counts as a win once TP1 was reached."""
    buy = trade["side"] == "BUY"
    say = tg if notify else (lambda *a, **k: None)
    new = m1[m1.index > pd.Timestamp(trade["last_ts"])]
    for ts, c in new.iterrows():
        when = f"{ts:%b %d %H:%M} UTC"
        sl_hit = c.low <= trade["sl"] if buy else c.high >= trade["sl"]

        def reached(level):
            return c.high >= level if buy else c.low <= level

        if sl_hit:  # conservative: SL checked first within a candle
            label = "BE stop (profit locked)" if trade["tp1_hit"] else "STOP LOSS"
            say(f"{'🟡' if trade['tp1_hit'] else '🔴'} XAU/USD {trade['side']} - {label} hit at {fmt(trade['sl'])}. Trade closed.\nCandle: {when}")
            return {"win": trade["tp1_hit"], "stage": "BE" if trade["tp1_hit"] else "SL"}
        if not trade["tp1_hit"] and reached(trade["tp1"]):
            trade["tp1_hit"] = True
            trade["sl"] = trade["be"]
            say(f"🟢 XAU/USD {trade['side']} - TP1 hit ({fmt(trade['tp1'])}). Move SL to BE {fmt(trade['be'])}\nCandle: {when}")
        if trade["tp1_hit"] and not trade["tp2_hit"] and reached(trade["tp2"]):
            trade["tp2_hit"] = True
            say(f"🟢 XAU/USD {trade['side']} - TP2 hit ({fmt(trade['tp2'])})\nCandle: {when}")
        if reached(trade["tp3"]):
            say(f"🏆 XAU/USD {trade['side']} - TP3 hit ({fmt(trade['tp3'])}). Trade closed.\nCandle: {when}")
            return {"win": True, "stage": "TP3"}
        trade["last_ts"] = str(ts)
    return None


def main():
    now = datetime.now(timezone.utc)
    if market_closed(now):
        print("Market closed")
        return
    state = load_state()
    g, d, m1 = get_gold(), get_dxy(), get_m1()
    m5 = to_m5(m1)
    print(f"Run {now:%Y-%m-%d %H:%M} UTC | last M15 candle {g.index[-1]:%H:%M} | "
          f"gold close {g.close.iloc[-1]:.2f} | DXY close {d.close.iloc[-1]:.3f}")

    # paper trades (signals memory skipped) are followed silently so the bot learns from them too
    still = []
    for sh in state["shadow"]:
        out = track(sh, m1, notify=False)
        if out:
            record(state, sh, out, shadow=True)
        else:
            still.append(sh)
    state["shadow"] = still

    if state["open"]:
        out = track(state["open"], m1, notify=True)
        print(f"Tracking {state['open']['side']} from {state['open']['entry']:.2f}")
        if out:
            record(state, state["open"], out, shadow=False)
            state["open"] = None
        save_state(state)
        if state["open"]:
            print("Trade open, tracking only")
            return  # one trade at a time

    print_memory(state["journal"])
    news, title = red_news(now)
    if news:
        print("Red news window:", title)
        save_state(state)
        return
    print("News: clear")

    sess = session_of(now)
    for side in ("BUY", "SELL"):
        res = check(side, g, d, m1, m5)
        if not res:
            continue
        keys = [f"{side}|{tag}|{ts}" for tag, ts in res]
        fresh = [tag for (tag, ts), k in zip(res, keys) if k not in state["seen"]]
        state["seen"] = (state["seen"] + keys)[-SEEN_KEEP:]
        if not fresh:
            print(f"{side}: triggers already alerted, skipping")
            continue

        verdicts = {tag: judge(state["journal"], side, tag, sess) for tag in fresh}
        allowed = [t for t in fresh if verdicts[t][0] != "skip"]
        skipped = [t for t in fresh if verdicts[t][0] == "skip"]
        entry, a = m1.close.iloc[-1], atr(g).iloc[-1]

        if not allowed:
            why = "; ".join(f"{t}: {verdicts[t][1]}" for t in skipped)
            print(f"{side}: SKIPPED by memory - {why}")
            if len(state["shadow"]) < MAX_SHADOW:
                state["shadow"].append(new_trade(side, entry, a, now, m1, fresh))
                print("Following it on paper to keep learning")
            if NOTIFY_SKIPS:
                tg(f"🧠 Skipped {side} - memory says: {why}", priority="low")
            continue

        t = new_trade(side, entry, a, now, m1, fresh)
        state["open"] = t
        mem = []
        for tag in allowed:
            v, label = verdicts[tag]
            mem.append(f"{'⭐ ' if v == 'proven' else ''}{tag}: {label}")
        for tag in skipped:
            mem.append(f"(ignored: {tag} - {verdicts[tag][1]})")
        tg(f"{'🟢' if side == 'BUY' else '🔴'} XAU/USD {side} ({INTERVAL}) - {' + '.join(allowed)}\n"
           f"Entry: {fmt(entry)}\nSL: {fmt(t['sl'])}\n"
           f"TP1: {fmt(t['tp1'])}\nTP2: {fmt(t['tp2'])}\nTP3: {fmt(t['tp3'])}\n"
           f"After TP1: SL to BE {fmt(t['be'])}\nATR: {fmt(a)}\n"
           f"Memory: " + " | ".join(mem))
        print(f"SIGNAL SENT: {side} - {' + '.join(allowed)}")
        break
    else:
        print("No signal this run")
    save_state(state)


if __name__ == "__main__":
    main()