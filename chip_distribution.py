# -*- coding: utf-8 -*-
"""暗盘筹码分布计算 — 三角形分布模型
用法: python chip_distribution.py <code> [market] [float_shares]  (market默认自动: 6/9→SH, 其余→SZ; float_shares=流通股本/股, 可选, 缺省查stkfinance→东财quote)
例:   python chip_distribution.py 688520 SH
      python chip_distribution.py 300258 SZ 569891488   # stkfinance无记录时手动传
"""
输出: 获利盘比例/平均成本/90%成本区间/筹码峰/价格带分布表
import sys, sqlite3
import numpy as np

def get_code():
    if len(sys.argv) >= 2:
        code = sys.argv[1]
        market = sys.argv[2].upper() if len(sys.argv) >= 3 else ("SH" if code.startswith(("6", "9")) else "SZ")
        return market, code
    # 默认示例
    return "SH", "688520"

market, code = get_code()
full = f"{market.lower()}{code}"

print("=" * 60)
print(f"暗盘筹码分布 {full} (三角形分布模型)")
print("=" * 60)

from hikyuu.interactive import *
from hikyuu import Query
sm = StockManager.instance()
s = sm[full]
if s is None:
    for st in sm:
        if st.code == code and st.market == market:
            s = st
            break
if s is None:
    raise ValueError(f"Hikyuu 无 {full}")

k = s.get_kdata(Query(-1000, ktype="DAY"))
print(f"K线: {len(k)}根  {k[0].datetime} ~ {k[-1].datetime}")
closes = np.array([float(d.close) for d in k], dtype=float)
highs = np.array([float(d.high) for d in k], dtype=float)
lows = np.array([float(d.low) for d in k], dtype=float)
vols = np.array([float(d.volume) for d in k], dtype=float)  # 手
n = len(closes)

# 流通股本(股) — 优先级: argv[3] > stkfinance > 东财quote f85
float_shares = float(sys.argv[3]) if len(sys.argv) >= 4 else None
if not float_shares:
    conn = sqlite3.connect("c:/stock/stock.db")
    row = conn.execute("""
        SELECT sf.liutongguben FROM stkfinance sf
        JOIN Stock st ON sf.stockid = st.stockid
        WHERE st.code=? AND sf.liutongguben > 0
        ORDER BY sf.updated_date DESC LIMIT 1
    """, (code,)).fetchone()
    conn.close()
    float_shares = float(row[0]) if row else None
if not float_shares:
    # 降级: 东财 quote API (f85=流通股本/股) — stkfinance 常缺个股记录(2026-08-12 300258实测)
    try:
        import requests
        mkt = 0 if code.startswith(("0", "3")) else 1
        r = requests.get("https://push2.eastmoney.com/api/qt/stock/get",
                         params={"secid": f"{mkt}.{code}", "fields": "f85"},
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}, timeout=10)
        f85 = r.json().get("data", {}).get("f85")
        if f85:
            float_shares = float(f85)
    except Exception as e:
        print(f"WARN: 东财quote取流通股本失败: {e}")
if not float_shares:
    print("WARN: 无法获取流通股本 — 手动传: python chip_distribution.py <code> <market> <float_shares>")
    sys.exit(1)
float_hands = float_shares / 100.0
print(f"流通股本: {float_shares/1e8:.2f}亿股 ({float_hands/1e4:.0f}万手)")

turnover = vols / float_hands * 100.0  # 换手率%

# ===== 筹码分布: 三角形权重分配 =====
lo_all, hi_all = lows.min(), highs.max()
price_grid = np.linspace(lo_all * 0.95, hi_all * 1.05, 300)
chips = np.zeros_like(price_grid)

for i in range(n):
    mid = (highs[i] + lows[i]) / 2
    hi_i, lo_i = highs[i], lows[i]
    if hi_i <= lo_i:
        continue
    mask = (price_grid >= lo_i) & (price_grid <= hi_i)
    idx = np.where(mask)[0]
    if len(idx) < 1:
        continue
    w = np.zeros(len(idx))
    for j, gi in enumerate(idx):
        p = price_grid[gi]
        if p <= mid:
            w[j] = (p - lo_i) / (mid - lo_i) if mid > lo_i else 1.0
        else:
            w[j] = (hi_i - p) / (hi_i - mid) if hi_i > mid else 1.0
    w = np.clip(w, 0, 1)
    wsum = w.sum()
    if wsum <= 0:
        continue
    chips[idx] += w / wsum * vols[i]

total_chips = chips.sum()
if total_chips > 0:
    chips = chips / total_chips * float_hands  # 归一化到流通盘(手)

# ===== 关键指标 =====
cur = closes[-1]
# 实时价核对 (Hikyuu K线可能滞后; 用腾讯实时价重算获利盘 — 陷阱见 anti-quant SKILL.md)
try:
    import requests
    r = requests.get(f"https://qt.gtimg.cn/q={market.lower()}{code}", timeout=8)
    r.encoding = "gbk"
    p_ = r.text.split("~")
    if len(p_) > 45:
        rt = float(p_[3])
        if rt > 0 and abs(rt - cur) / cur > 0.005:
            print(f"⚠️ Hikyuu收盘 {cur:.2f} ({str(k[-1].datetime)[:10]}) vs 腾讯实时 {rt:.2f} — 以实时价重算获利盘")
            cur = rt
except Exception:
    pass
cum = np.cumsum(chips)
total = cum[-1] if cum[-1] > 0 else 1

profit_idx = np.where(price_grid <= cur)[0]
profit_ratio = cum[profit_idx[-1]] / total * 100 if len(profit_idx) else 0
avg_cost = (chips * price_grid).sum() / total

def pctile(p):
    return price_grid[np.searchsorted(cum, p * total)]

p10, p90 = pctile(0.10), pctile(0.90)
p15, p85 = pctile(0.15), pctile(0.85)
peak_idx = np.argmax(chips)
peak_price = price_grid[peak_idx]
peak_ratio = chips[peak_idx] / total * 100

idx60 = n - 60 if n >= 60 else 0
wavg60 = (closes[-60:] * vols[-60:]).sum() / vols[-60:].sum()
wavg20 = (closes[-20:] * vols[-20:]).sum() / vols[-20:].sum()

print()
print(f"现价: {cur:.2f}")
print(f"获利盘比例: {profit_ratio:.1f}%   (上方套牢: {100-profit_ratio:.1f}%)")
print(f"平均成本: {avg_cost:.2f}  (现价 vs 平均成本: {cur/avg_cost*100-100:+.1f}%)")
print(f"90%筹码区间: [{p10:.2f}, {p90:.2f}]  宽度{(p90-p10)/p10*100:.0f}%")
print(f"70%筹码区间: [{p15:.2f}, {p85:.2f}]")
print(f"筹码峰价格: {peak_price:.2f} (占比 {peak_ratio:.1f}%)")
print(f"60日换手: {turnover[idx60:].sum():.0f}%  120日: {turnover[-120:].sum():.0f}%  250日: {turnover[-250:].sum():.0f}%")
print(f"60日加权均价: {wavg60:.2f}  20日加权均价: {wavg20:.2f}")

print()
print("价格带筹码分布 (每档2元):")
lo_band = int(lo_all // 2 * 2)
for b in range(lo_band, int(hi_all) + 2, 2):
    m = (price_grid >= b) & (price_grid < b + 2)
    ratio = chips[m].sum() / total * 100
    if ratio > 0.3:
        mark = " ◀现价" if b <= cur < b + 2 else ""
        print(f"  {b:4d}-{b+2:3d}元: {ratio:5.1f}%{mark}")

print()
print("DONE")
