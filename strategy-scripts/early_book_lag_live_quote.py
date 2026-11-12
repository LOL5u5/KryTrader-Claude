# krypt-script v1
# name: Early Book-Lag Live-Quote
# description: Buys the side the spot model rates 65%+ over a 40-78c ask in the first ~3 minutes of a window, at once when the quote is a live websocket quote and after two matching ticks when it is not.
#
# Change from "Early Book-Lag Confirmed": the engine now reports where each
# tick's bid/ask came from (ctx quoteSource). The two-tick wait existed only
# to rule out an old quote from Kalshi's market list. When quoteSource is
# "ws" the quote is live, so the entry no longer waits a tick, which is
# where the extra trades come from. A "rest" quote still needs the same quote
# on two consecutive ticks.
#
# The engine also now cancels a "buy at ask" order that has not filled in
# about 20 seconds, so an order placed against a quote that vanished can no
# longer sit there and fill only when price comes back against us.
#
# BACKTEST WARNING: recorded ticks have no quoteSource and are ~95 seconds
# apart, so this script shows ZERO trades in a backtest. That is expected.
# It has never been measured. Run it in paper mode and compare each fill
# price with the ask in the trade reason before trusting it.

MIN_MINS_LEFT = 12.0     # only the opening ~3 minutes of the 15m window
MIN_PROB = 0.65          # model probability required on the side we buy
MIN_ASK = 0.40
MAX_ASK = 0.78
MIN_GAP = 0.10           # modelProb(side) - ask
BIG_GAP = 0.15
MAX_BOOK_SUM = 1.04      # upAsk + downAsk; wider = thin/broken book
CONFIRM_TICKS = 2        # ticks needed when the quote is not a live one
ASK_TOLERANCE = 0.011    # ask may move at most 1c between those ticks
MIN_TICK_GAP_MIN = 0.03  # ticks must be >= ~2s apart (a fresh snapshot)
MAX_TICK_GAP_MIN = 0.50  # ...and <= 30s apart, or the streak restarts
DAILY_STOP_USD = -15.0   # stand down before the $25 rail trips
MAX_OPEN = 5             # coins move together; cap same-window exposure
SIZE = 3
SIZE_BIG = 4


def on_start(state):
    state["wins"] = 0
    state["losses"] = 0
    state["seen"] = {}       # asset -> last qualifying observation


def candidate(ctx):
    # Returns (side, ask, prob, gap) if this tick qualifies, else None.
    mp = ctx.get("modelProb")
    if mp is None:
        return None
    up_ask = ctx.get("upAsk")
    down_ask = ctx.get("downAsk")
    if up_ask is not None and down_ask is not None:
        if up_ask + down_ask > MAX_BOOK_SUM:
            return None

    if mp >= MIN_PROB:
        side, ask, prob, sgn = "up", up_ask, mp, 1.0
    elif 1.0 - mp >= MIN_PROB:
        side, ask, prob, sgn = "down", down_ask, 1.0 - mp, -1.0
    else:
        return None

    if ask is None or ask < MIN_ASK or ask > MAX_ASK:
        return None
    gap = prob - ask
    if gap < MIN_GAP:
        return None

    # Spot must already sit on our side of the strike.
    dz = ctx.get("deltaSignedPct")
    if dz is None or dz * sgn <= 0:
        return None
    return (side, ask, prob, gap)


def decide(ctx):
    if not ctx.get("hasMarket"):
        return None
    asset = ctx.get("asset")
    ticker = ctx.get("ticker")
    ml = ctx.get("minsLeft")
    if asset is None or ticker is None or ml is None:
        return None

    seen = state.get("seen")
    if seen is None:
        seen = {}
        state["seen"] = seen

    if ml < MIN_MINS_LEFT:
        seen.pop(asset, None)
        return None

    cand = candidate(ctx)
    if cand is None:
        seen.pop(asset, None)        # streak broken
        return None
    side, ask, prob, gap = cand

    live_quote = ctx.get("quoteSource") == "ws"
    count = 1
    if not live_quote:
        prev = seen.get(asset)
        if prev is not None and prev.get("ticker") == ticker:
            dt = prev["ml"] - ml
            if dt < MIN_TICK_GAP_MIN:
                return None          # same snapshot as last call; wait
            if (dt <= MAX_TICK_GAP_MIN and prev["side"] == side
                    and abs(prev["ask"] - ask) <= ASK_TOLERANCE):
                count = prev["count"] + 1
        seen[asset] = {"ticker": ticker, "side": side, "ask": ask,
                       "ml": ml, "count": count}
        if count < CONFIRM_TICKS:
            return None

    # Checked only once an entry is otherwise ready.
    pf = ctx.get("portfolio") or {}
    today = pf.get("todayPnlUsd")
    if today is not None and today <= DAILY_STOP_USD:
        return None
    open_count = pf.get("openCount")
    if open_count is not None and open_count >= MAX_OPEN:
        return None

    seen.pop(asset, None)
    size = SIZE_BIG if gap >= BIG_GAP else SIZE
    how = "live quote" if live_quote else "confirmed x%d" % count
    return {
        "side": side,
        "price": "ask",
        "size": size,
        "reason": "lag (%s): model %d vs ask %dc (+%d)" % (
            how, int(round(prob * 100)), int(round(ask * 100)),
            int(round(gap * 100))),
    }


def on_settle(position, state):
    pnl = position.get("pnlUsd") if isinstance(position, dict) else None
    if pnl is None:
        return
    if pnl > 0:
        state["wins"] = state.get("wins", 0) + 1
    elif pnl < 0:
        state["losses"] = state.get("losses", 0) + 1
    log("book-lag record: %d W / %d L" % (state.get("wins", 0),
                                          state.get("losses", 0)))
