# krypt-script v1
# name: Model-Confirmed Favorite v5
# description: v4 plus two extra entry tiers that are never combined (VWAP band up to 1.0% when RSI is calm; RSI above 72 only when spot is 0.30%+ past the strike), sized inside the daily loss limit and held to settlement.
#
# v5 changes (replayed on the recorded ticks, 2026-10-18 to 2026-11-11, HYPE
# off; thresholds were chosen on this same data, so treat it as in-sample):
#   - VWAP band widened from 0.5% to 1.0%: the trades between 0.5% and 1.0%
#     behaved like the rest of v4 in both the early and the late part of the data
#   - RSI above 72 is allowed only when spot is at least 0.30% past the strike
#     (twice the normal distance). Stretched RSI with spot only just past the
#     strike is where the losses were, and stays excluded
#   - the two are never combined: RSI above 72 together with price more than
#     0.5% past VWAP lost 8 of 81 in the replay, so each relaxation applies
#     only when the other measure is inside its v4 limit
#   - the ask cap stays at 96c: 97c entries replayed at about +1.6c a contract
#     with 2 losses in 176, too thin to be worth a 97c loss
#   - exposure also reads portfolio.openCostUsd, which the engine now refreshes
#     after every order inside a tick
#
# Tested and rejected because they added losing trades: model below 95%,
# spot closer than 0.15%, no momentum filter, no VWAP floor, HYPE.

def on_start(state):
    state["exp_ct"] = None
    state["exp_usd"] = 0.0

def on_settle(position, state):
    n = position.get("contracts") or 0
    c = position.get("avgEntryCents")
    if c is None:
        c = position.get("costCents")
    if c is None:
        return None
    left = (state.get("exp_usd") or 0.0) - n * (c / 100.0 + 0.01)
    state["exp_usd"] = left if left > 0.0 else 0.0
    return None

def decide(ctx):
    MF_MIN = 0.95        # model win probability required on the side we buy
    ASK_MIN = 0.85
    ASK_MAX = 0.9649     # rounds to 96c or less
    ML_MIN = 2.0
    ML_MAX = 14.0
    MAX_SPREAD = 0.03
    DS_MIN = 0.0015      # spot at least 0.15% past the strike on our side
    DS_STRETCH = 0.0030  # distance required when RSI is above RSI_MAX
    MOM_MIN = 0.03       # ema1-vs-sma5 percent, in our direction
    VWAP_MIN = 0.0       # price-vs-1h-VWAP percent, in our direction
    VWAP_MAX = 1.0       # only when RSI is not stretched
    VWAP_TIGHT = 0.5     # the v4 band; required when RSI is above RSI_MAX
    RSI_MAX = 72.0       # RSI measured in our direction (100 - RSI for down)
    SKIP = ("HYPE",)
    SIZE = 20
    MIN_SIZE = 3
    MAX_OPEN = 3
    DAY_BUDGET = 24.0    # keep the worst case above the $25 daily auto-disable
    BAL_FRAC = 0.25      # max share of balance in one order (live only)

    if not ctx.get("hasMarket"):
        return None
    ml = ctx.get("minsLeft")
    mp = ctx.get("modelProb")
    if ml is None or mp is None:
        return None
    if ctx.get("asset") in SKIP:
        return None
    if ml < ML_MIN or ml > ML_MAX:
        return None

    side = "up" if mp >= 0.5 else "down"
    sgn = 1.0 if side == "up" else -1.0
    mf = mp if side == "up" else 1.0 - mp
    if mf < MF_MIN:
        return None

    dsp = ctx.get("deltaSignedPct")
    if dsp is None or dsp * sgn < DS_MIN:
        return None

    mom = ctx.get("ema1VsSma5Pct")
    if mom is None or mom * sgn <= MOM_MIN:
        return None

    vw = ctx.get("priceVsVwapPct")
    if vw is None or vw * sgn <= VWAP_MIN or vw * sgn > VWAP_MAX:
        return None

    rsi = ctx.get("rsi")
    if rsi is None:
        return None
    rsi_side = rsi if side == "up" else 100.0 - rsi
    tier = "A"
    if rsi_side > RSI_MAX:
        # stretched RSI: only with spot far past the strike AND not also
        # stretched above the 1h VWAP (both at once is where v5 lost)
        if dsp * sgn < DS_STRETCH or vw * sgn > VWAP_TIGHT:
            return None
        tier = "B"
    elif vw * sgn > VWAP_TIGHT:
        tier = "C"

    ask = ctx.get("upAsk") if side == "up" else ctx.get("downAsk")
    if ask is None or ask < ASK_MIN or ask > ASK_MAX:
        return None
    yb = ctx.get("yesBid")
    ya = ctx.get("yesAsk")
    if yb is None or ya is None:
        return None
    bid = yb if side == "up" else 1.0 - ya
    if ask - bid > MAX_SPREAD:
        return None

    # money already committed in this 15-minute window
    ct = ctx.get("closeTime")
    if ct != state.get("exp_ct"):
        state["exp_ct"] = ct
        state["exp_usd"] = 0.0
    exposure = state.get("exp_usd") or 0.0

    pnl = 0.0
    bal = None
    pf = ctx.get("portfolio")
    if pf is not None:
        if (pf.get("openCount") or 0) >= MAX_OPEN:
            return None
        p = pf.get("todayPnlUsd")
        if p is not None:
            pnl = p
        bal = pf.get("balanceUsd")
        oc = pf.get("openCostUsd")
        if oc is not None and oc > exposure:
            exposure = oc

    per_contract = ask + 0.01          # full loss plus fee, per contract
    size = SIZE
    budget = DAY_BUDGET + pnl - exposure
    size = min(size, int(budget / per_contract))
    if bal is not None and bal > 0:
        size = min(size, int(bal * BAL_FRAC / per_contract))
    if size < MIN_SIZE:
        return None

    state["exp_usd"] = exposure + size * per_contract
    return {"side": side, "price": "ask", "size": size,
            "reason": "%s model %d%% ask %dc rsi %d" % (
                tier, int(mf * 100), int(round(ask * 100)), int(rsi_side))}
