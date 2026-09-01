# a-stock-chips · A-Share Chip Intelligence (Free Edition)

> **Institutional-grade chip/chip-position intelligence for retail investors**
> See where the big money's cost basis sits, who's buying, who's trapped — verifiable inference from public data.

---

## What is this?

A Python toolkit that reconstructs an **institutional view of the chip structure** (筹码分布) for China A-shares, using only public data:

| Capability | Description |
|---|---|
| **Visible chips (明盘)** | Shareholder count trends / top-10 circulating shareholders / Dragon-Tiger list (龙虎榜) / block trades / margin trading / main capital flows |
| **Hidden chips (暗盘)** | Hikyuu triangle-distribution model: profit-taking ratio / average cost / 90% cost band / chip peak / institutional cost zone / 250-day turnover |
| **Cross-validation** | Current price vs chip peak vs 20-day cost → breakout / distribution / high-risk zone patterns |

Everything is **fact + probability**, never a buy/sell signal. Every number is traceable to a public source.

## Quick Start

```bash
pip install requests numpy
# Hidden-chip model requires Hikyuu: pip install hikyuu  (https://github.com/fasiondog/hikyuu)

python chip_report.py 600844          # single stock (market auto-detected)
python chip_report.py 600844,000938   # batch (Pro feature)
python chip_report.py 600844 --save   # save report to file
```

Sample report (see `examples/example_report.txt`):

```
==============================================
Jinmei Tech 600844.SH · Chip Panorama · 2026-09-01
==============================================
[Quote] px 4.12 | turnover 15.99% | vol-ratio 1.39 | float cap 3.39B CNY
[Institutions] HK Central Clearing +7.77M shares; Chang'an Trust -117.61M
[Main capital] 10d +165.65M | max single day 8/25 +138.90M
[Chip dist.] profit-taking 93.4% | avg cost 3.31 | chip peak 3.43
[Verdict] price ABOVE chip peak (+20%); above 20d cost → high-risk zone
[Alerts] profit-taking >85% → trim on bounces
----------------------------------------------
Sources: EastMoney/Sina/Tencent/Hikyuu dual-channel cross-check
```

## Free vs Pro

| Feature | Free | Pro |
|---|---|---|
| Chip panorama report | ⚠️ 1/day, 1 stock | ✅ unlimited + batch |
| Hidden-chip model | ✅ (in report) | ✅ full |
| **Anti-quant pattern detection** (T1–T11) | ❌ | ✅ |
| **Watchlist monitor** (EOD auto-reports + alerts) | ❌ | ✅ |
| **Suspicious-pick-article forensics** (4-step protocol) | ❌ | ✅ |
| Volume-efficiency / limit-up sentiment / unlock-risk alerts | ❌ | ✅ |

> 💎 **Upgrade to Pro**: unlock anti-quant pattern detection (11 quant harvesting patterns), watchlist monitoring, unlimited batch reports. Contact the author for a license key.
>
> 🔥 **First-month promo: 9.9 CNY (regular 199/month) — first 20 users only.** DM the author to claim.

## Data Sources & Reliability

- **Multi-source failover**: EastMoney push2 (rate-limited) → Tencent → Sina fallback chain, with built-in retry
- **Freshness validation**: shareholder-count record older than 400 days is flagged as missing source (renamed stocks), never silently wrong
- **Real-time price recheck**: Hikyuu K-lines may lag; Tencent realtime price re-computes profit-taking ratios
- **Known limits**: BSE history gaps degrade to simplified analysis; non-margin stocks skip margin sections

## ⚠️ Disclaimer

All data comes from public channels (EastMoney / Sina Finance / Tencent Finance / exchange disclosures) and is provided **for research only — not investment advice**. Markets are risky; invest with care. Redistribution or resale of tool output is prohibited.

## License

MIT — free edition is fully open source. Use, modify, distribute freely (keep the disclaimer).

---

*Made for A-share retail investors · anti-quant · chip analysis*
