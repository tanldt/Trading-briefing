"""
soxl_method.py — tín hiệu theo phương pháp "Máy in tiền SOXL" (kỷ luật gap down / thủ vốn / free share).

Không thay thế soxl_levels.py / ta_levels.py; file này chỉ tính các thứ investor dùng:
  • bậc gap down −8/−11/−14/−17 (bear: −10/−13/−16/−19) từ giá đóng cửa hôm trước, cỡ lệnh 1/4 của 1/5 vốn
  • gap sống (up/down) chưa fill, gap hôm nay
  • SMA50/SMA200, Bollinger 20 ngày ±2σ/±3σ, MACD 12/26/9 (đường đỏ = signal)
  • cờ: mở cao đóng thấp, nu lô liên tục, chuỗi ngày đỏ, volume
  • mốc ra: nửa ba đỏ (O+C)/2, +5%, luật $10 (~5%)
  • rule engine -> "lời khuyên theo investor" (deterministic). Phần đánh giá riêng của AI do routine Claude viết.

Chạy:
  python soxl_method.py                       -> JSON (SOXL + SOXL.NE)
  python soxl_method.py --md                  -> thêm markdown
  python soxl_method.py --ticker SOXL --capital 50000 --md
  python soxl_method.py --save reports/method -> lưu markdown vào thư mục
  python soxl_method.py --save reports/method --pdf -> kèm PDF
Kiến thức nền: knowledge/soxl-may-in-tien-tong-hop.md
"""
import sys, json, argparse, time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ET = ZoneInfo("America/New_York")
PROFILES = {
    "SOXL":    {"name": "Direxion Daily Semiconductor Bull 3X (NYSE Arca, USD)", "ccy": "USD", "gap_cut": 0.60},
    "SOXL.NE": {"name": "BetaPro 3x Semiconductor Daily Bull (Cboe Canada, CAD)", "ccy": "CAD", "gap_cut": 0.40},
}
LADDER_SIDEWAY = [-8, -11, -14, -17]
LADDER_BEAR = [-10, -13, -16, -19]
SELL_GAP_UP_MIN = 5.0          # gap up ≥5% -> đẩy 1/3 tổng share
TEN_DOLLAR_RULE_PCT = 5.0      # "luật 10 đồng" ≈ 5% khi giá ~200


# ----------------------------------------------------------------------------- data
def fetch(ticker, period="450d", interval="1d", attempts=2, delay=45):
    for i in range(attempts):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False, prepost=False)
            break
        except YFRateLimitError:
            if i + 1 >= attempts:
                raise
            time.sleep(delay)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def session_mode(now_et):
    """pre-market / in-market / after-close / weekend theo giờ New York."""
    if now_et.weekday() >= 5:
        return "weekend"
    t = now_et.time()
    if t < datetime.strptime("09:30", "%H:%M").time():
        return "pre-market"
    if t < datetime.strptime("16:00", "%H:%M").time():
        return "in-market"
    return "after-close"


def today_bar(ticker, daily, today_et):
    """Tách bar hôm nay (đang chạy) khỏi lịch sử đã đóng. Trả (hist, today_dict|None)."""
    if not daily.empty and daily.index[-1].date() == today_et:
        row = daily.iloc[-1]
        hist = daily.iloc[:-1]
        return hist, {"open": float(row["Open"]), "high": float(row["High"]), "low": float(row["Low"]),
                      "last": float(row["Close"]), "volume": float(row["Volume"]), "source": "daily-partial"}
    try:
        intra = fetch(ticker, period="5d", interval="5m", attempts=1)
        if not intra.empty:
            idx = intra.index.tz_convert(ET) if intra.index.tz is not None else intra.index
            mask = idx.date == today_et
            tdf = intra[mask]
            if not tdf.empty:
                return daily, {"open": float(tdf["Open"].iloc[0]), "high": float(tdf["High"].max()),
                               "low": float(tdf["Low"].min()), "last": float(tdf["Close"].iloc[-1]),
                               "volume": float(tdf["Volume"].sum()), "source": "intraday-5m"}
    except Exception:
        pass
    return daily, None


# ----------------------------------------------------------------------------- indicators
def macd(close, fast=12, slow=26, sig=9):
    m = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    s = m.ewm(span=sig, adjust=False).mean()
    return m, s, m - s


def macd_state(close):
    m, s, h = macd(close)
    if len(s) < 6:
        return {}
    slope1 = float(s.iloc[-1] - s.iloc[-2])
    slope4 = float(s.iloc[-4] - s.iloc[-5])
    diff = np.sign((m - s).values)
    cross_days = None
    for k in range(1, min(40, len(diff))):
        if diff[-k] != diff[-k - 1]:
            cross_days = k - 1
            break
    red_dir = "lên" if slope1 > 0 else "xuống"
    rounding = None
    if slope1 > 0 and slope4 > 0 and slope1 < 0.5 * slope4:
        rounding = "tròn đầu trên (đà tăng chậm lại)"
    elif slope1 < 0 and slope4 < 0 and abs(slope1) < 0.5 * abs(slope4):
        rounding = "tròn đầu dưới (đà giảm chậm lại, có thể quay lên)"
    return {
        "macd": round(float(m.iloc[-1]), 3), "signal_red": round(float(s.iloc[-1]), 3),
        "hist": round(float(h.iloc[-1]), 3),
        "blue_vs_red": "trên" if m.iloc[-1] > s.iloc[-1] else "dưới",
        "red_direction": red_dir,
        "above_zero": bool(s.iloc[-1] > 0),
        "last_cross": None if cross_days is None else {
            "days_ago": cross_days, "type": "chéo lên" if diff[-1] > 0 else "chéo xuống"},
        "rounding": rounding,
        "gap_open": abs(float(h.iloc[-1])) > abs(float(h.iloc[-2])),  # "cá sấu há mõm"
    }


def bollinger(close, n=20):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return {"mid": ma, "u2": ma + 2 * sd, "l2": ma - 2 * sd, "u3": ma + 3 * sd, "l3": ma - 3 * sd}


def find_gaps(df, ref_price, max_gaps=6):
    """Gap theo định nghĩa investor: khoảng cách so với ĐÓNG CỬA hôm trước. Sống = chưa bị chạm."""
    ups, downs = [], []
    c, h, l = df["Close"].values, df["High"].values, df["Low"].values
    idx = df.index
    for i in range(1, len(df)):
        pc = c[i - 1]
        if l[i] > pc:      # gap up: không giá nào chạm lại đóng cửa cũ
            alive = not (l[i + 1:] <= pc).any()
            if alive:
                ups.append({"level": round(float(pc), 2), "date": idx[i].date().isoformat(),
                            "size_pct": round(float(l[i] / pc - 1) * 100, 2)})
        elif h[i] < pc:    # gap down
            alive = not (h[i + 1:] >= pc).any()
            if alive:
                downs.append({"level": round(float(pc), 2), "date": idx[i].date().isoformat(),
                              "size_pct": round(float(h[i] / pc - 1) * 100, 2)})
    for g in ups + downs:
        g["dist_pct"] = round((g["level"] / ref_price - 1) * 100, 2)
    ups.sort(key=lambda g: -g["level"])     # gap up gần nhất bên dưới trước
    downs.sort(key=lambda g: g["level"])    # gap down gần nhất bên trên trước
    return {"gap_up_song": ups[:max_gaps], "gap_down_song": downs[:max_gaps]}


def streaks(df):
    o, c, l = df["Open"].values, df["Close"].values, df["Low"].values
    red = 0
    for i in range(len(df) - 1, -1, -1):
        if c[i] < o[i]:
            red += 1
        else:
            break
    newlow = 0
    for i in range(len(df) - 1, 0, -1):
        if l[i] < l[i - 1]:
            newlow += 1
        else:
            break
    return red, newlow


# ----------------------------------------------------------------------------- analysis
def analyze(ticker, capital, now_et):
    prof = PROFILES.get(ticker, {"name": ticker, "ccy": "?", "gap_cut": 0.40})
    out = {"ticker": ticker, "name": prof["name"], "ccy": prof["ccy"], "warnings": []}
    daily = fetch(ticker)
    if daily.empty or len(daily) < 60:
        out["warnings"].append("Không đủ dữ liệu")
        return out

    # cắt tại consolidation/split chưa điều chỉnh (giống các script cũ)
    jumps = daily["Close"].pct_change().abs() > prof["gap_cut"]
    if jumps.any():
        cut = daily.index[jumps][-1]
        out["warnings"].append(f"Gap >{int(prof['gap_cut']*100)}% ngày {cut.date()} — chỉ dùng dữ liệu sau ngày đó")
        daily = daily.loc[cut:]

    hist, today = today_bar(ticker, daily, now_et.date())
    if len(hist) < 30:
        out["warnings"].append("Ít hơn 30 phiên sau khi cắt — SMA/BB kém tin cậy")
    prev = hist.iloc[-1]
    pc, po, ph, pl = (float(prev["Close"]), float(prev["Open"]), float(prev["High"]), float(prev["Low"]))
    prev_date = hist.index[-1].date().isoformat()
    ref = today["last"] if today else pc

    c = hist["Close"]
    sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
    bb = bollinger(c)
    bbv = {k: (round(float(v.iloc[-1]), 2) if not np.isnan(v.iloc[-1]) else None) for k, v in bb.items()}
    ms = macd_state(c)
    red_streak, newlow_streak = streaks(hist)
    vol20 = float(hist["Volume"].tail(20).mean())

    # --- regime ---
    below50 = sma50 is not None and pc < sma50
    below200 = sma200 is not None and pc < sma200
    if sma50 and sma200 and pc > sma50 and pc > sma200 and ms.get("red_direction") == "lên":
        regime = "uptrend"
    elif below50 and (below200 or sma200 is None) and ms.get("red_direction") == "xuống":
        regime = "bear"
    else:
        regime = "consolidation"
    hugging = None
    if bbv["l2"] and pc <= bbv["l2"] * 1.01:
        hugging = "mon men −2σ (không đụng, không average down)"
    elif bbv["u2"] and pc >= bbv["u2"] * 0.99:
        hugging = "mon men +2σ (giữ free share, bán tiền mới khi ra khỏi +2σ→+3σ)"

    # --- ladder & sizing ---
    ladder_pct = LADDER_BEAR if regime == "bear" else LADDER_SIDEWAY
    fifth = capital / 5 if capital else None
    quarter = fifth / 4 if fifth else None
    ladder = []
    for p in ladder_pct:
        lvl = pc * (1 + p / 100)
        row = {"pct": p, "price": round(lvl, 2)}
        if quarter:
            row["budget"] = int(round(quarter))
            row["shares"] = int(quarter // lvl)
        if today:
            row["hit_today"] = bool(today["low"] <= lvl)
        ladder.append(row)

    exits = {
        "half_bar_prev": round((po + pc) / 2, 2),            # nửa ba hôm trước
        "plus5_from_prev_close": round(pc * 1.05, 2),
        "plus10_from_prev_close": round(pc * 1.10, 2),
        "ten_dollar_rule_equiv": round(pc * TEN_DOLLAR_RULE_PCT / 100, 2),
        "thu_von_offset": 0.30 if pc > 150 else (0.10 if pc > 50 else 0.05),
    }

    # --- today ---
    tinfo = None
    if today:
        gap_pct = (today["open"] / pc - 1) * 100
        tinfo = {
            **{k: round(v, 2) for k, v in today.items() if isinstance(v, float)},
            "source": today["source"],
            "gap_open_pct": round(gap_pct, 2),
            "change_pct": round((today["last"] / pc - 1) * 100, 2),
            "gap_down_song_trong_ngay": bool(today["high"] < pc),
            "gap_up_song_trong_ngay": bool(today["low"] > pc),
            "mo_cao_dong_thap": bool(today["last"] < today["open"]),
            "vol_vs_20d_pct": round(today["volume"] / vol20 * 100, 0) if vol20 else None,
            "below_sma50_now": bool(sma50 and today["last"] < sma50),
            "below_l2_now": bool(bbv["l2"] and today["last"] < bbv["l2"]),
        }

    gaps = find_gaps(hist, ref)

    out.update({
        "prev_date": prev_date, "prev_close": round(pc, 2), "prev_open": round(po, 2),
        "prev_high": round(ph, 2), "prev_low": round(pl, 2),
        "prev_bar": "đỏ (mở cao đóng thấp)" if pc < po else "xanh",
        "prev_gap": ("gap down" if ph < float(hist["Close"].iloc[-2]) else
                     "gap up" if pl > float(hist["Close"].iloc[-2]) else "không gap"),
        "sma50": round(sma50, 2) if sma50 else None, "sma200": round(sma200, 2) if sma200 else None,
        "price_vs_sma": {"sma50": "dưới" if below50 else "trên", "sma200": ("dưới" if below200 else "trên") if sma200 else "n/a"},
        "bollinger20": bbv, "hugging": hugging,
        "macd": ms,
        "red_streak": red_streak, "newlow_streak": newlow_streak,
        "prev_vol_vs_20d_pct": round(float(prev["Volume"]) / vol20 * 100, 0) if vol20 else None,
        "regime": regime, "ladder_used": ladder_pct, "ladder": ladder,
        "sizing": {"capital": capital, "one_fifth": round(fifth, 2) if fifth else None,
                   "quarter_of_fifth": round(quarter, 2) if quarter else None},
        "exits": exits, "gaps": gaps, "today": tinfo,
        "high_52w": round(float(daily["High"].max()), 2), "low_52w": round(float(daily["Low"].min()), 2),
        "drawdown_from_high_pct": round((ref / float(daily["High"].max()) - 1) * 100, 1),
    })
    out["advice"] = advise(out)
    return out


# ----------------------------------------------------------------------------- rule engine
def advise(a):
    """Lời khuyên deterministic theo luật investor. Mỗi dòng = một luật áp dụng được."""
    L = []
    t = a.get("today")
    ms = a.get("macd", {})
    ccy = a["ccy"]
    L.append(f"Regime: **{a['regime']}** — giá {a['price_vs_sma']['sma50']} SMA50, {a['price_vs_sma']['sma200']} SMA200; "
             f"MACD đường đỏ đang **{ms.get('red_direction','?')}**"
             + (f", {ms['rounding']}" if ms.get("rounding") else "")
             + (f", {ms['last_cross']['type']} cách {ms['last_cross']['days_ago']} phiên" if ms.get("last_cross") else "") + ".")
    if a.get("hugging"):
        L.append(f"Bollinger: {a['hugging']}.")

    lad = ", ".join(f"{r['pct']}% = {r['price']}" for r in a["ladder"])
    L.append(f"Bậc gap down hôm nay ({'bear' if a['regime']=='bear' else 'sideway'}) từ đóng cửa {a['prev_close']}: {lad} {ccy}. "
             f"Mỗi bậc tối đa 1/4 của 1/5 vốn"
             + (f" ≈ {a['sizing']['quarter_of_fifth']:,.0f} {ccy}" if a['sizing']['quarter_of_fifth'] else "") + ".")

    if t is None:
        L.append("Chưa có bar hôm nay: đặt lệnh sẵn ở các bậc trên trước 9:30 ET. Không mua nếu mở cửa không gap down.")
    else:
        hit = [r for r in a["ladder"] if r.get("hit_today")]
        if t["gap_open_pct"] <= -5:
            if hit:
                L.append(f"HÔM NAY GAP DOWN {t['gap_open_pct']}%: đã chạm bậc {', '.join(str(r['pct'])+'%' for r in hit)} → "
                         f"BỤP theo bậc, thủ vốn ngay khi vượt giá mua +{a['exits']['thu_von_offset']} {ccy} (stop loss, không stop limit).")
            else:
                L.append(f"HÔM NAY GAP DOWN {t['gap_open_pct']}% nhưng chưa tới bậc −{abs(a['ladder'][0]['pct'])}%: chờ, không bắt đáy.")
            if t["below_sma50_now"] and t["below_l2_now"]:
                L.append("Đang dưới SMA50 và dưới −2σ: có gap vẫn bụp nhưng chỉ 'giật tiền' — thủ vốn tức thì, thủ lời theo luật $10 (~5%).")
            if a["red_streak"] >= 2:
                L.append(f"Đây là ngày đỏ thứ {a['red_streak']+1} liên tiếp → được phép bụp mạnh hơn ngày đầu (investor: ngày 1 mua ít, ngày 3 bụp).")
            else:
                L.append("Ngày đầu chợ rớt: mua ít, giữ phần lớn 1/5 cho gap down thứ 2–3.")
        elif t["gap_open_pct"] >= SELL_GAP_UP_MIN:
            L.append(f"HÔM NAY GAP UP {t['gap_open_pct']}%: ĐẨY 1/3 tổng số share tiền mới (giữ free share). "
                     f"Đặt stop lô mua hôm trước ở giá gap ({t['open']}) để lấy nếu quay đầu.")
        else:
            if t["mo_cao_dong_thap"]:
                L.append(f"Không gap down và đang mở cao đóng thấp ({t['open']} → {t['last']}): KHÔNG MUA hôm nay. "
                         f"Đóng dưới nửa ba đỏ hôm trước {a['exits']['half_bar_prev']} → ra tiền mới.")
            else:
                L.append("Không gap: không mua tiền mới; chỉ quản lý lệnh cũ (thủ vốn/thủ lời).")
        if t["below_sma50_now"] and a["price_vs_sma"]["sma50"] == "trên" and t["gap_open_pct"] > -5:
            L.append(f"Đang rớt xuống dưới SMA50 ({a['sma50']}) không gap → RA HẾT tiền mới; nó thường đi tiếp tới −2σ {a['bollinger20']['l2']}.")
        if a["newlow_streak"] >= 2 and t["low"] < a["prev_low"]:
            L.append(f"Nu lô {a['newlow_streak']+1} phiên liên tiếp: không mua khi đang phá low; đặt alert ở low, bật lên rồi mua MARKET và thủ vốn ngay.")
        if t.get("vol_vs_20d_pct") and t["vol_vs_20d_pct"] >= 150:
            L.append(f"Volume {t['vol_vs_20d_pct']:.0f}% trung bình 20 phiên: cao + đóng thấp = còn xuống; cao + đóng cao = đảo chiều/mutual fund vào.")

    if ms.get("red_direction") == "xuống":
        L.append(f"MACD xuống: mọi lô mua đều phải có stop; lời ≈{a['exits']['ten_dollar_rule_equiv']} {ccy} ({TEN_DOLLAR_RULE_PCT}%) thì trailing stop lấy (luật $10). "
                 f"'Xuống 10 lên 5': mốc +5% = {a['exits']['plus5_from_prev_close']} là chỗ ra.")
        L.append("KHÔNG average up khi MACD xuống (= đu đỉnh).")
    else:
        L.append(f"MACD lên: giữ free share 'bò lết'; average up chỉ với lô mới có stop; bán tiền mới khi gap up ≥5% ({a['exits']['plus5_from_prev_close']}) hoặc ra khỏi +2σ {a['bollinger20']['u2']}→+3σ {a['bollinger20']['u3']}.")
        if ms.get("last_cross", {}) and ms["last_cross"]["type"] == "chéo lên" and ms["last_cross"]["days_ago"] <= 3 and a["price_vs_sma"]["sma50"] == "trên":
            L.append("MACD vừa chéo lên và giá trên SMA50 → điểm investor 'o lên 1/5' (vẫn thủ vốn).")

    g = a["gaps"]
    if g["gap_down_song"]:
        n = g["gap_down_song"][0]
        L.append(f"Gap down sống gần nhất phía trên: {n['level']} ({n['date']}, {n['dist_pct']:+.1f}%) — mục tiêu hồi/fill; SOXL 'gap up để đụng gap down'.")
    if g["gap_up_song"]:
        n = g["gap_up_song"][0]
        L.append(f"Gap up sống gần nhất phía dưới: {n['level']} ({n['date']}, {n['dist_pct']:+.1f}%) — vùng có thể bị kéo xuống fill; 'mọi gap đều phải fill'.")
    L.append(f"Từ đỉnh 52 tuần {a['high_52w']} đang {a['drawdown_from_high_pct']}%. Investor: rớt ~27% vào 1/5 được; rớt 40–60% mới vào 1/5 kế; luôn còn 3/5–4/5 cash.")
    return L


# ----------------------------------------------------------------------------- output
def to_markdown(res, now_et, mode):
    md = [f"# Phương pháp SOXL — {now_et.strftime('%Y-%m-%d %H:%M')} ET ({mode})", ""]
    for a in res:
        if "prev_close" not in a:
            md.append(f"## {a['ticker']}\n⚠️ {'; '.join(a['warnings'])}\n")
            continue
        t = a.get("today")
        md.append(f"## {a['ticker']} — {a['name']}")
        if a["warnings"]:
            md.append("⚠️ " + "; ".join(a["warnings"]))
        md.append(f"Đóng cửa {a['prev_date']}: **{a['prev_close']}** ({a['prev_bar']}, {a['prev_gap']}) · "
                  f"SMA50 {a['sma50']} · SMA200 {a['sma200']} · −2σ {a['bollinger20']['l2']} / +2σ {a['bollinger20']['u2']} · "
                  f"−3σ {a['bollinger20']['l3']} / +3σ {a['bollinger20']['u3']} · MACD đỏ {a['macd'].get('red_direction')}")
        if t:
            md.append(f"Hôm nay ({t['source']}): mở {t['open']} (gap {t['gap_open_pct']:+.2f}%) · cao {t['high']} · thấp {t['low']} · "
                      f"hiện {t['last']} ({t['change_pct']:+.2f}%) · vol {t.get('vol_vs_20d_pct')}% TB20")
        md.append("")
        md.append(f"| Bậc | Giá ({a['ccy']}) | Ngân sách | Share | Đã chạm |\n|---|---|---|---|---|")
        for r in a["ladder"]:
            md.append(f"| {r['pct']}% | {r['price']} | {r.get('budget','')} | {r.get('shares','')} | {'✅' if r.get('hit_today') else ''} |")
        e = a["exits"]
        md.append(f"\nMốc ra: nửa ba hôm trước **{e['half_bar_prev']}** · +5% **{e['plus5_from_prev_close']}** · +10% {e['plus10_from_prev_close']} · "
                  f"luật $10 ≈ +{e['ten_dollar_rule_equiv']} {a['ccy']} · thủ vốn = giá mua +{e['thu_von_offset']}")
        g = a["gaps"]
        md.append("\n**Gap sống** — down phía trên: " + (", ".join(f"{x['level']} ({x['dist_pct']:+.0f}%)" for x in g["gap_down_song"]) or "không")
                  + " · up phía dưới: " + (", ".join(f"{x['level']} ({x['dist_pct']:+.0f}%)" for x in g["gap_up_song"]) or "không"))
        md.append("\n**Lời khuyên theo phương pháp investor:**")
        md += [f"- {x}" for x in a["advice"]]
        md.append("")
    md.append("_Phần 'đánh giá riêng của AI' do routine Claude bổ sung dựa trên khối này + knowledge/soxl-may-in-tien-tong-hop.md._")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", action="append", help="SOXL, SOXL.NE (mặc định cả hai)")
    ap.add_argument("--capital", type=float, default=None, help="tổng vốn để tính 1/5 và 1/4 của 1/5")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--save", metavar="DIR", help="lưu markdown vào DIR/method-YYYY-MM-DD-HHMM.md")
    ap.add_argument("--pdf", action="store_true", help="kèm --save: xuất thêm PDF cùng tên (md_to_pdf.py)")
    args = ap.parse_args()

    now_et = datetime.now(ET)
    mode = session_mode(now_et)
    tickers = [t.upper() for t in (args.ticker or ["SOXL", "SOXL.NE"])]
    res = []
    for tk in tickers:
        try:
            res.append(analyze(tk, args.capital, now_et))
        except Exception as exc:
            res.append({"ticker": tk, "warnings": [f"Lỗi {type(exc).__name__}: {exc}"]})

    payload = {"generated_at_et": now_et.isoformat(timespec="minutes"), "session": mode,
               "knowledge": "knowledge/soxl-may-in-tien-tong-hop.md", "results": res}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.md or args.save:
        md = to_markdown(res, now_et, mode)
        if args.md:
            print("\n" + md)
        if args.save:
            import os
            os.makedirs(args.save, exist_ok=True)
            path = os.path.join(args.save, f"method-{now_et.strftime('%Y-%m-%d-%H%M')}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"\nĐã lưu {path}")
            if args.pdf:
                try:
                    from md_to_pdf import md_file_to_pdf
                    print("Đã lưu", md_file_to_pdf(path, title=f"Phương pháp SOXL — {now_et.strftime('%d/%m/%Y %H:%M')} ET"))
                except Exception as exc:
                    print(f"Không tạo được PDF: {exc}")
    return 0 if all("prev_close" in r for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
