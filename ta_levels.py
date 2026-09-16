"""
ta_levels.py — tính các mức kỹ thuật cho ETF đòn bẩy niêm yết Canada.
Chạy: python ta_levels.py HNU.TO            -> JSON ra stdout
      python ta_levels.py SOXL.NE --md      -> thêm bảng markdown
      python ta_levels.py                   -> mặc định SOXL.NE
Yêu cầu: pip install yfinance pandas
"""
import sys, json, time
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ---- profile theo ticker: refs = mã tham chiếu, gap = ngưỡng nghi consolidation ----
PROFILES = {
    "SOXL.NE": {
        "name": "BetaPro 3x Semiconductor Daily Bull (Cboe Canada, CAD)",
        "leverage": "3x",
        "refs": {"SOXL": "SOXL", "SOXX": "SOXX", "CADUSD": "CADUSD=X"},
        "gap": 0.40,
    },
    "HNU.TO": {
        "name": "BetaPro Natural Gas Leveraged Daily Bull 2x (TSX, CAD)",
        "leverage": "2x",
        # NG=F = Henry Hub front month; BOIL = 2x nat gas Mỹ; UNG = 1x
        "refs": {"NG_futures": "NG=F", "BOIL": "BOIL", "UNG": "UNG", "CADUSD": "CADUSD=X"},
        # nat gas có thể +-15%/ngày -> 2x = 30%; đặt ngưỡng cao hơn để không cắt nhầm
        "gap": 0.45,
    },
}
LOOKBACK_DAYS = 200


def fetch(ticker, days=LOOKBACK_DAYS, max_attempts=1, retry_delay=60):
    for attempt in range(max_attempts):
        try:
            df = yf.download(ticker, period=f"{days}d", interval="1d",
                             auto_adjust=True, progress=False)
            break
        except YFRateLimitError:
            if attempt + 1 >= max_attempts:
                raise
            time.sleep(retry_delay)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def rsi(close, n=14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def atr(df, n=14):
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def swings(df, w=3, n=3):
    highs, lows = [], []
    h, l = df["High"], df["Low"]
    for i in range(w, len(df) - w):
        if h.iloc[i] == h.iloc[i - w:i + w + 1].max():
            highs.append(round(float(h.iloc[i]), 2))
        if l.iloc[i] == l.iloc[i - w:i + w + 1].min():
            lows.append(round(float(l.iloc[i]), 2))
    return highs[-n:], lows[-n:]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ticker = args[0].upper() if args else "SOXL.NE"
    prof = PROFILES.get(ticker, {"name": ticker, "leverage": "?", "refs": {"CADUSD": "CADUSD=X"}, "gap": 0.40})

    out = {"ticker": ticker, "name": prof["name"], "leverage": prof["leverage"],
           "generated_at": datetime.now().isoformat(timespec="minutes"), "warnings": []}
    try:
        df = fetch(ticker, max_attempts=2, retry_delay=60)
    except Exception as exc:
        out["warnings"].append("Yahoo Finance tạm giới hạn truy cập sau 2 lần thử"
                               if isinstance(exc, YFRateLimitError)
                               else f"Không tải được dữ liệu chính {ticker}")
        out["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1
    if df.empty or len(df) < 60:
        out["warnings"].append(f"KHÔNG đủ dữ liệu {ticker} từ yfinance")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    last_date = df.index[-1].date()
    if (datetime.now().date() - last_date) > timedelta(days=4):
        out["warnings"].append(f"Dữ liệu cũ: bar cuối {last_date}")

    gaps = (df["Close"].pct_change().abs() > prof["gap"])
    if gaps.any():
        cut = df.index[gaps][-1]
        out["warnings"].append(
            f"Gap >{int(prof['gap']*100)}% ngày {cut.date()} (consolidation?) — chỉ dùng dữ liệu từ sau ngày đó")
        df = df.loc[cut:]
        if len(df) < 60:
            out["warnings"].append("Sau khi cắt gap còn <60 phiên — EMA50/RSI kém tin cậy")

    if df["Volume"].iloc[-1] < 0.3 * df["Volume"].tail(20).mean():
        out["warnings"].append("Volume phiên cuối rất thấp")

    c = df["Close"]
    last, prev = df.iloc[-1], df.iloc[-2]
    ema = {n: round(float(c.ewm(span=n, adjust=False).mean().iloc[-1]), 2) for n in (9, 21, 50)}
    r = round(float(rsi(c).iloc[-1]), 1)
    a = float(atr(df).iloc[-1])
    slope20 = round(float((c.iloc[-1] / c.iloc[-21] - 1) * 100), 2) if len(c) > 21 else None

    H, L, C = float(last["High"]), float(last["Low"]), float(last["Close"])
    PP = (H + L + C) / 3
    piv = {k: round(v, 2) for k, v in {
        "PP": PP, "R1": 2 * PP - L, "S1": 2 * PP - H,
        "R2": PP + (H - L), "S2": PP - (H - L)}.items()}
    sh, sl = swings(df)

    out.update({
        "last_date": last_date.isoformat(),
        "bars_used": int(len(df)),
        "close": round(C, 2),
        "change_pct": round((C / float(prev["Close"]) - 1) * 100, 2),
        "prev_high": round(H, 2), "prev_low": round(L, 2),
        "ema": ema,
        "price_vs_ema": {f"ema{n}": "trên" if C > v else "dưới" for n, v in ema.items()},
        "rsi14": r,
        "atr14": round(a, 2), "atr_pct": round(a / C * 100, 2),
        "expected_range_today": [round(C - a, 2), round(C + a, 2)],
        "slope_20d_pct": slope20,
        "pivots": piv,
        "high_20d": round(float(df["High"].tail(20).max()), 2),
        "low_20d": round(float(df["Low"].tail(20).min()), 2),
        "high_50d": round(float(df["High"].tail(50).max()), 2),
        "low_50d": round(float(df["Low"].tail(50).min()), 2),
        "swing_highs": sh, "swing_lows": sl,
    })

    refs = {}
    for name, t in prof["refs"].items():
        try:
            rd = fetch(t, 10, max_attempts=1)
            refs[name] = {"symbol": t,
                          "close": round(float(rd["Close"].iloc[-1]), 4),
                          "change_pct": round(float(rd["Close"].pct_change().iloc[-1] * 100), 2),
                          "date": rd.index[-1].date().isoformat()}
        except Exception as e:
            out["warnings"].append(f"Không lấy được {t}: {e}")
    out["refs"] = refs

    print(json.dumps(out, ensure_ascii=False, indent=2))

    if "--md" in sys.argv:
        print(f"\n**{ticker}** — {prof['name']}\n\n| Mức | Giá (CAD) |\n|---|---|")
        for k in ("R2", "R1", "PP", "S1", "S2"):
            print(f"| {k} | {piv[k]} |")
        for n, v in ema.items():
            print(f"| EMA{n} | {v} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
