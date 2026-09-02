# -*- coding: utf-8 -*-
"""筹码全景报告一键生成 — 输入代码 → 输出完整报告 (明盘+暗盘+反量化+量化警报)

用法:
  python chip_report.py 600844                  # 自动判断市场
  python chip_report.py 000938                  # 深市
  python chip_report.py 600844,000938           # 批量(逗号分隔)
  python chip_report.py 600844 SH               # 显式市场
  python chip_report.py 600844 SH 822834646     # 显式流通股本(股)
  python chip_report.py 600844 --save           # 同时保存报告到 I:\\ob\\量化交易\\

依赖: requests, numpy (暗盘计算需要 Hikyuu)
数据源: 东财 datacenter + emweb + 新浪兜底 + 腾讯行情 + Hikyuu 本地K线
2026-09-01 Free v1.0: 专业版 — 无限次筹码报告。3 个数据 bug 修复已内置。
专业版(付费): 无限次/批量/反量化套路识别/自选池监控/话术帖鉴别 — 见 README.md
"""
import sys, os, re, json, datetime, time
import requests
import numpy as np

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://data.eastmoney.com/"}
SAVE_DIR = r"I:\ob\量化交易"


def get(url, params=None, retry=3):
    for i in range(retry):
        try:
            return requests.get(url, params=params, headers=UA, timeout=12).json()
        except Exception:
            if i == retry - 1:
                return None
            time.sleep(2)


def rows_of(d):
    return ((d or {}).get("result") or {}).get("data") or []


def secid(code, market):
    return ("1." if market == "SH" else "0.") + code


# ==================== 明盘层 ====================
def get_quote(code, market):
    """行情: 东财优先, 腾讯兜底。返回 dict"""
    d = get("https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": secid(code, market), "fields": "f43,f57,f58,f84,f85,f116,f117,f162,f167"}, retry=2)
    data = (d or {}).get("data") or {}
    if data:
        def v(k):
            try:
                return float(data.get(k))
            except (TypeError, ValueError):
                return None
        return {"px": v("f43") / 100 if v("f43") else None,
                "mcap": v("f116") / 1e8 if v("f116") else None,
                "fcap": v("f117") / 1e8 if v("f117") else None,
                "fshares": v("f85"), "src": "eastmoney"}
    # 腾讯兜底/补全 (换手/量比/涨跌幅 只有腾讯有)
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={market.lower()}{code}", timeout=8)
        r.encoding = "gbk"
        p = r.text.split("~")
        if len(p) > 49:
            px = float(p[3]); fcap = float(p[44])
            tx = {"px": px, "chg": p[31], "turnover": p[38], "vol_ratio": p[49],
                  "fcap": fcap, "mcap": float(p[45]), "fshares": fcap * 1e8 / px,
                  "src": "tencent"}
            # 若东财已有价格, 用腾讯补换手/量比/涨跌幅
            d2 = get("https://push2.eastmoney.com/api/qt/stock/get",
                     {"secid": secid(code, market), "fields": "f43,f116,f117,f85"}, retry=1)
            dd = (d2 or {}).get("data") or {}
            if dd:
                def v(k):
                    try:
                        return float(dd.get(k))
                    except (TypeError, ValueError):
                        return None
                if v("f43"):
                    return {"px": v("f43") / 100, "chg": tx["chg"], "turnover": tx["turnover"],
                            "vol_ratio": tx["vol_ratio"], "mcap": v("f116") / 1e8 if v("f116") else tx["mcap"],
                            "fcap": v("f117") / 1e8 if v("f117") else tx["fcap"],
                            "fshares": v("f85") or tx["fshares"], "src": "eastmoney+tencent"}
            return tx
    except Exception:
        pass
    return {}


def get_holder_num(code, market):
    """股东户数 — 主源: 东财F10 gdrs (改名票/新代码也覆盖), 备源: datacenter RPT_HOLDERNUM_DET
    (2026-09 修复: datacenter 报表对改名票(如600844丹化→金煤)只回2019年旧数据, F10 gdrs 数据完整新鲜)
    """
    # ---- 主源: F10 PageAjax gdrs ----
    try:
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={market}{code}"
        d = get(url, retry=2)
        gdrs = (d or {}).get("gdrs") or []
        if gdrs:
            latest = str(gdrs[0].get("END_DATE", ""))[:10]
            try:
                days = (datetime.date.today() - datetime.date.fromisoformat(latest)).days
            except Exception:
                days = 9999
            if days <= 400:
                seq = [{"date": str(r.get("END_DATE", ""))[:10],
                        "num": r.get("HOLDER_TOTAL_NUM"),
                        "ratio": r.get("TOTAL_NUM_RATIO")} for r in gdrs[:8]]
                return {"status": "ok", "seq": seq}
            return {"status": "missing", "latest": latest, "days": days}
    except Exception:
        pass
    # ---- 备源: datacenter RPT_HOLDERNUM_DET ----
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {"reportName": "RPT_HOLDERNUM_DET", "columns": "ALL", "pageSize": "8",
              "sortColumns": "END_DATE", "sortTypes": "-1",
              "filter": f'(SECUCODE="{code}.{market}")', "source": "HSF10", "client": "PC"}
    rows = rows_of(get(url, params))
    if not rows:
        return {"status": "none"}
    latest = str(rows[0].get("END_DATE", ""))[:10]
    try:
        days = (datetime.date.today() - datetime.date.fromisoformat(latest)).days
    except Exception:
        days = 9999
    if days > 400:
        return {"status": "missing", "latest": latest, "days": days}
    seq = [{"date": str(r.get("END_DATE", ""))[:10], "num": r.get("HOLDER_NUM"),
            "ratio": r.get("HOLDER_NUM_RATIO")} for r in rows[:8]]
    return {"status": "ok", "seq": seq}


def get_shareholders(code, market):
    """十大流通股东 + 基金持仓 (重点标出变动)"""
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={market.lower()}{code}"
    d = get(url, retry=2)
    if not d:
        return {"holders": [], "funds": []}
    holders = []
    for g in (d.get("sdltgd") or [])[:10]:
        change = g.get("HOLD_NUM_CHANGE")
        holders.append({"name": g.get("HOLDER_NAME"), "num": g.get("HOLD_NUM"),
                        "change": change, "type": g.get("HOLDER_TYPE")})
    funds = [{"name": g.get("HOLDER_NAME"), "shares": g.get("TOTAL_SHARES"),
              "ratio": g.get("TOTALSHARES_RATIO")} for g in (d.get("jjcg") or [])[:8]]
    return {"holders": holders, "funds": funds}


def get_lhb(code):
    """龙虎榜近60日 (BILLBOARD_NET_AMT 字段)"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "ALL", "pageSize": "20",
              "sortColumns": "TRADE_DATE", "sortTypes": "-1",
              "filter": f'(SECURITY_CODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    out = []
    for r in rows:
        net = r.get("BILLBOARD_NET_AMT")
        try:
            net_s = f"{float(net)/1e4:+.0f}万" if net not in (None, "-") else "N/A"
        except Exception:
            net_s = "N/A"
        out.append({"date": str(r.get("TRADE_DATE", ""))[:10],
                    "explain": r.get("EXPLAIN"), "net": net_s})
    return out


def get_block_trade(code):
    """大宗交易近60日"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL", "pageSize": "10",
              "sortColumns": "TRADE_DATE", "sortTypes": "-1",
              "filter": f'(SECURITY_CODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    out = []
    for r in rows:
        dt = str(r.get("TRADE_DATE", ""))[:10]
        try:
            if (datetime.date.today() - datetime.date.fromisoformat(dt)).days > 400:
                continue
        except Exception:
            pass
        out.append({"date": dt, "price": r.get("DEAL_PRICE"), "amt": r.get("DEAL_AMT"),
                    "premium": r.get("PREMIUM_RATE")})
    return out


def get_rzrq(code):
    """两融"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_RZRQ_LSHJ", "columns": "ALL", "pageSize": "10",
              "sortColumns": "DATE", "sortTypes": "-1",
              "filter": f'(SCODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    if not rows:
        return {"status": "none"}
    return {"status": "ok", "latest": str(rows[0].get("DATE"))[:10], "rzye": rows[0].get("RZYE")}


def get_fundflow(code, market):
    """主力资金流近10日 (东财→新浪兜底)。返回 (list, 合计万)"""
    # 东财
    try:
        d = get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                {"lmt": "10", "klt": "101", "secid": secid(code, market),
                 "fields1": "f1,f2,f3,f7", "fields2": "f51,f52"},
                retry=1)
        ks = (d or {}).get("data", {}).get("klines") or []
        if ks:
            rows = []
            tot = 0
            for k in ks:
                p = k.split(",")
                v = float(p[1]) / 1e4
                tot += v
                rows.append({"date": p[0], "net_wan": v})
            return rows, tot, "eastmoney"
    except Exception:
        pass
    # 新浪兜底
    try:
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"MoneyFlow.ssl_qsfx_zjlrqs?daima={market.lower()}{code}&page=1&num=10")
        txt = requests.get(url, headers=UA, timeout=12).text.strip()
        if txt.startswith("var "):
            txt = txt[txt.index("=") + 1:].strip().rstrip(";")
        data = json.loads(txt)[:10]
        rows = []
        tot = 0
        for d in data:
            net = float(d.get("netamount", 0)) / 1e4
            r0 = float(d.get("r0_net", 0)) / 1e4
            tot += net
            rows.append({"date": d.get("opendate"), "net_wan": net, "super_wan": r0})
        return rows, tot, "sina"
    except Exception as e:
        return [], 0, f"fail:{e}"


# ==================== 暗盘层 (Hikyuu 三角形筹码) ====================
# Hikyuu 可选化 (embeddable python / 未装 hikyuu 时暗盘层降级, 明盘+反量化不受影响)
try:
    import hikyuu.interactive  # 触发 Hikyuu 完整初始化 (数据目录加载)
    from hikyuu import StockManager, Query
    HKU_OK = True
except Exception:
    HKU_OK = False


def _chips_from_kdata(closes, highs, lows, vols, float_shares, cur, k_start, k_end, price_src):
    """三角形筹码模型核心计算 (纯函数, 数据源无关)"""
    n = len(closes)
    if n < 60:
        return {"error": f"K线不足60根 ({n})"}
    float_hands = float_shares / 100.0
    turnover = vols / float_hands * 100.0

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
        chips = chips / total_chips * float_hands

    cum = np.cumsum(chips)
    total = cum[-1] if cum[-1] > 0 else 1
    profit_idx = np.where(price_grid <= cur)[0]
    profit_ratio = cum[profit_idx[-1]] / total * 100 if len(profit_idx) else 0
    avg_cost = (chips * price_grid).sum() / total

    def pctile(p):
        return price_grid[np.searchsorted(cum, p * total)]

    p10, p90 = pctile(0.10), pctile(0.90)
    p15, p85 = pctile(0.15), pctile(0.85)
    peak_idx = int(np.argmax(chips))
    peak_price = price_grid[peak_idx]
    peak_ratio = chips[peak_idx] / total * 100
    idx60 = n - 60 if n >= 60 else 0
    wavg60 = (closes[-60:] * vols[-60:]).sum() / vols[-60:].sum()
    wavg20 = (closes[-20:] * vols[-20:]).sum() / vols[-20:].sum()

    return {"cur": round(cur, 2), "price_src": price_src, "k_start": k_start,
            "k_end": k_end, "n": n,
            "profit_ratio": round(profit_ratio, 1), "avg_cost": round(avg_cost, 2),
            "p10": round(p10, 2), "p90": round(p90, 2),
            "p15": round(p15, 2), "p85": round(p85, 2),
            "peak": round(peak_price, 2), "peak_ratio": round(peak_ratio, 1),
            "turnover60": round(turnover[idx60:].sum()), "turnover120": round(turnover[-120:].sum()),
            "turnover250": round(turnover[-250:].sum()),
            "wavg60": round(wavg60, 2), "wavg20": round(wavg20, 2)}


def _tencent_kline(code, market, days=800):
    """腾讯前复权日K: 返回 (closes, highs, lows, vols, dates) 或 None"""
    try:
        r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                         params={"param": f"{market.lower()}{code},day,,,{days},qfq"}, timeout=15)
        j = r.json()
        k = j["data"][f"{market.lower()}{code}"].get("qfqday") or j["data"][f"{market.lower()}{code}"].get("day")
        if not k or len(k) < 60:
            return None
        closes = np.array([float(x[2]) for x in k], dtype=float)
        highs = np.array([float(x[3]) for x in k], dtype=float)
        lows = np.array([float(x[4]) for x in k], dtype=float)
        vols = np.array([float(x[5]) for x in k], dtype=float)
        dates = [x[0] for x in k]
        return closes, highs, lows, vols, dates
    except Exception:
        return None


def _realtime_price(code, market):
    """腾讯实时价"""
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={market.lower()}{code}", timeout=8)
        r.encoding = "gbk"
        p_ = r.text.split("~")
        if len(p_) > 45 and p_[3]:
            return float(p_[3])
    except Exception:
        pass
    return None


def compute_chips(code, market, float_shares):
    """筹码分布 — hikyuu 优先, 无 hikyuu 自动切腾讯 K 线 (同模型)。返回 dict"""
    # ---- 现价 (腾讯实时, 两数据源共用) ----
    rt = _realtime_price(code, market)

    if HKU_OK:
        try:
            full = f"{market.lower()}{code}"
            sm = StockManager.instance()
            s = sm[full]
            if s is None:
                for st in sm:
                    if st.code == code and st.market == market:
                        s = st
                        break
            if s is None:
                return {"error": f"Hikyuu 无 {full}"}
            k = s.get_kdata(Query(-1000, ktype="DAY"))
            if len(k) < 60:
                return {"error": f"Hikyuu K线不足60根 ({len(k)})"}
            closes = np.array([float(d.close) for d in k], dtype=float)
            highs = np.array([float(d.high) for d in k], dtype=float)
            lows = np.array([float(d.low) for d in k], dtype=float)
            vols = np.array([float(d.volume) for d in k], dtype=float)
            cur = closes[-1]
            k_end = str(k[-1].datetime)[:10]
            k_start = str(k[0].datetime)[:10]
            price_src = "hikyuu"
            if rt and rt > 0 and abs(rt - cur) / cur > 0.005:
                cur = rt
                price_src = f"tencent({k_end}->实时)"
            return _chips_from_kdata(closes, highs, lows, vols, float_shares, cur,
                                     k_start, k_end, price_src)
        except Exception as e:
            # hikyuu 运行异常 → 降级腾讯
            hku_err = str(e)

    # ---- 腾讯 K 线 fallback (无 hikyuu / hikyuu 异常) ----
    tk = _tencent_kline(code, market)
    if tk is None:
        return {"error": "hikyuu 不可用且腾讯 K 线获取失败, 暗盘层无法计算 (明盘+反量化正常)"}
    closes, highs, lows, vols, dates = tk
    cur = closes[-1]
    k_start, k_end = dates[0], dates[-1]
    price_src = "tencent"
    if rt and rt > 0 and abs(rt - cur) / cur > 0.005:
        cur = rt
        price_src = f"tencent({k_end}->实时)"
    return _chips_from_kdata(closes, highs, lows, vols, float_shares, cur,
                             k_start, k_end, price_src)


# ==================== 反量化层 (120日K线) ====================
def anti_quant_scan(code, market):
    """120日前复权K线反量化指标"""
    try:
        r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                         params={"param": f"{market.lower()}{code},day,,,130,qfq"}, timeout=15)
        j = r.json()
        k = j["data"][f"{market.lower()}{code}"].get("qfqday") or j["data"][f"{market.lower()}{code}"].get("day")
    except Exception as e:
        return {"error": str(e)}
    if not k:
        return {"error": "无K线"}
    rows = []
    for item in k[-120:]:
        d, o, c, h, l = item[0], float(item[1]), float(item[2]), float(item[3]), float(item[4])
        amp = (h - l) / o * 100 if o else 0
        rows.append({"d": d, "o": o, "c": c, "amp": amp})
    n = len(rows)
    if n < 20:
        return {"error": f"K线不足 ({n})"}
    amps = [x["amp"] for x in rows]
    gt7 = sum(1 for a in amps if a > 7)
    gt5 = sum(1 for a in amps if a > 5)
    groups = 0
    i = 0
    while i < n - 1:
        if rows[i]["amp"] > 8 and rows[i + 1]["amp"] > 8:
            groups += 1
            i += 2
        else:
            i += 1
    stars = sum(1 for x in rows if x["amp"] > 7 and abs(x["c"] - x["o"]) / (x["amp"] / 100 * x["o"]) < 0.3)
    def chg(days):
        return rows[-1]["c"] / rows[-1 - days]["c"] * 100 - 100 if n > days else None
    return {"n": n, "avg_amp": round(sum(amps) / n, 2), "gt7": gt7, "gt5": gt5,
            "gt7_pct": round(gt7 / n * 100), "groups": groups,
            "stars": stars, "max_amp": round(max(amps), 1),
            "chg10": round(chg(10), 1) if chg(10) is not None else None,
            "chg20": round(chg(20), 1) if chg(20) is not None else None,
            "chg60": round(chg(60), 1) if chg(60) is not None else None}


# ==================== 报告渲染 ====================
def render_report(name, code, market, q, hn, sh, lhb_list, bt_list, rz, ff, ff_tot, chips, aq):
    L = []
    A = L.append
    A("=" * 46)
    A(f"{name} {code}.{market} · 筹码全景报告 · {datetime.date.today()}")
    A("=" * 46)
    # 行情
    px = q.get("px", "-")
    A(f"【行情】现价 {px}" + (f" ({q.get('chg','-')}%)" if q.get("chg") else "")
      + f" | 换手 {q.get('turnover','-')}% | 量比 {q.get('vol_ratio','-')} | 流通市值 {q.get('fcap','-')}亿")
    # 机构动向
    if sh.get("holders"):
        moves = []
        for h in sh["holders"][:6]:
            ch = h.get("change")
            if ch is not None:
                try:
                    cv = float(ch)
                    if cv > 0:
                        moves.append(f"{h['name']} 增持+{cv/1e4:.0f}万股")
                    elif cv < 0:
                        moves.append(f"{h['name']} 减持{cv/1e4:.0f}万股")
                    else:
                        moves.append(f"{h['name']} 不变")
                except Exception:
                    moves.append(f"{h['name']} {ch}")
            else:
                moves.append(h["name"])
        A(f"【机构动向】{'; '.join(moves[:5])}")
    # 主力资金
    if ff:
        max_day = max(ff, key=lambda x: abs(x["net_wan"]))
        A(f"【主力资金】近10日 {ff_tot:+.0f}万 | 单日最大 {max_day['date']} {max_day['net_wan']:+.0f}万")
    # 股东户数
    if hn.get("status") == "ok":
        seq = hn["seq"]
        last = seq[0]
        try:
            ratio = last.get("ratio")
            if ratio is not None and str(ratio) not in ("", "None"):
                rr = float(ratio)
                A(f"【股东户数】最新 {last['date']} {last['num']} (环比 {rr:+.1f}%)")
            else:
                prev = seq[1] if len(seq) > 1 else None
                if prev:
                    rr = (float(last["num"]) / float(prev["num"]) - 1) * 100
                    A(f"【股东户数】最新 {last['date']} {last['num']} (较上期 {rr:+.1f}%)")
                else:
                    A(f"【股东户数】最新 {last['date']} {last['num']}")
        except Exception:
            A(f"【股东户数】最新 {last['date']} {last['num']}")
    elif hn.get("status") == "missing":
        A(f"【股东户数】⚠️ 数据缺失 (东财最新仅 {hn['latest']}, {hn['days']}天前 — 改名票/未披露)")
    else:
        A("【股东户数】无数据")
    # 筹码分布
    if "error" not in chips:
        A(f"【筹码分布】获利盘 {chips['profit_ratio']}% | 平均成本 {chips['avg_cost']} | 90%区间 [{chips['p10']},{chips['p90']}] | 筹码峰 {chips['peak']}")
        A(f"【主力成本】20日 {chips['wavg20']} | 60日 {chips['wavg60']} | 60日换手 {chips['turnover60']}%")
        # 交叉判定
        cur = chips["cur"]
        cross = []
        if cur > chips["peak"]:
            cross.append(f"现价高于筹码峰 {chips['peak']} ({(cur/chips['peak']-1)*100:+.0f}%)")
        else:
            cross.append(f"现价低于筹码峰 {chips['peak']} ({(cur/chips['peak']-1)*100:+.0f}%)")
        if cur > chips["wavg20"]:
            cross.append(f"站上20日成本 {chips['wavg20']}")
        else:
            cross.append(f"低于20日成本 {chips['wavg20']} (短线者浮亏)")
        if chips["profit_ratio"] > 85 and cur > chips["peak"] * 1.3:
            verdict = "高位风险区(获利兑现压力大)"
        elif cur > chips["peak"] and cur > chips["wavg20"]:
            verdict = "突破形态"
        elif chips["profit_ratio"] > 80 and cur < chips["wavg20"]:
            verdict = "派发形态"
        else:
            verdict = "震荡形态"
        A(f"【交叉判定】{'; '.join(cross)} → {verdict}")
    else:
        A(f"【筹码分布】{chips['error']}")
    # 龙虎榜
    if lhb_list:
        recent = [f"{x['date'][5:]} {x['explain']} {x['net']}" for x in lhb_list[:4]]
        A("【龙虎榜】" + " | ".join(recent))
    else:
        A("【龙虎榜】近60日无")
    # 排除项
    ex = []
    if bt_list:
        ex.append(f"大宗 {len(bt_list)}笔(近)")
    else:
        ex.append("大宗无(排除暗仓对倒)")
    ex.append("两融非标的" if rz.get("status") == "none" else f"两融余额{rz.get('rzye')}")
    A(f"【排除项】{' | '.join(ex)}")
    # 反量化
    if "error" not in aq:
        triggers = []
        if aq["gt7_pct"] > 15:
            triggers.append("振幅>7%占比高")
        if aq["groups"] > 3:
            triggers.append("连续异动多")
        if aq["stars"] / max(aq["gt7"], 1) > 0.5:
            triggers.append("长影星密集")
        blind = "盲区修正触发 " + "+".join(triggers) if len(triggers) >= 2 else \
                ("盲区修正触发 " + triggers[0] if triggers else "盲区修正未触发")
        A(f"【反量化】120日均振幅 {aq['avg_amp']}% | >7%天数 {aq['gt7']}/{aq['n']}({aq['gt7_pct']}%) | 连续异动 {aq['groups']}组 | 近10日 {aq['chg10']}% 20日 {aq['chg20']}% 60日 {aq['chg60']}%")
        A(f"         {blind}")
    else:
        A(f"【反量化】{aq['error']}")
    # 量化警报
    A("【量化警报】")
    if "error" not in chips and "error" not in aq:
        A(f"  ⚡ 派发加速: 主力单日净流出 >5亿 + 跌幅 >3% → 立即减仓")
        if chips["profit_ratio"] > 85:
            A(f"  ⚡ 获利兑现: 获利盘 {chips['profit_ratio']}% > 85% → 反弹分批减")
        if cur > chips["peak"] * 1.3:
            A(f"  ⚡ 高位风险: 现价高于筹码峰 30%+ → 不追高")
        A(f"  ⚡ 破位参考: 跌破近期低点(见K线) → 离场; 支撑看筹码密集带上沿")
    else:
        A("  (数据不足, 无法生成)")
    A("-" * 46)
    A("数据来源: 东财/新浪/腾讯/Hikyuu 双口径交叉验证")
    return "\n".join(L)


# ==================== main ====================
def infer_market(code):
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def get_name(code, market):
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={market.lower()}{code}", timeout=8)
        r.encoding = "gbk"
        return r.text.split("~")[1]
    except Exception:
        return code


def run_one(code, market=None, float_shares=None, verbose=True):
    market = market or infer_market(code)
    name = get_name(code, market)
    if verbose:
        print(f"▶ 采集 {name} {code}.{market} ...")
    q = get_quote(code, market)
    if not q.get("fshares") and not q.get("fcap"):
        print(f"  ❌ 行情获取失败 {code}")
        return None
    fshares = float_shares or q.get("fshares") or (q.get("fcap", 0) * 1e8 / q.get("px", 1))
    hn = get_holder_num(code, market)
    sh = get_shareholders(code, market)
    lhb_list = get_lhb(code)
    bt_list = get_block_trade(code)
    rz = get_rzrq(code)
    ff, ff_tot, ff_src = get_fundflow(code, market)
    chips = compute_chips(code, market, fshares)
    aq = anti_quant_scan(code, market)
    report = render_report(name, code, market, q, hn, sh, lhb_list, bt_list, rz, ff, ff_tot, chips, aq)
    return report



if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    save = "--save" in args
    args = [a for a in args if a != "--save"]
    codes_str = args[0]
    market_arg = args[1].upper() if len(args) > 1 and args[1].upper() in ("SH", "SZ", "BJ") else None
    fshares_arg = float(args[2]) if len(args) > 2 and args[2].replace(".", "").isdigit() else None
    codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    for code in codes:
        rep = run_one(code, market_arg, fshares_arg)
        if rep:
            print()
            print(rep)
            print()
            if save:
                os.makedirs(SAVE_DIR, exist_ok=True)
                fp = os.path.join(SAVE_DIR, f"{code}_筹码全景报告_{datetime.date.today()}.txt")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(rep)
                print(f"  💾 已保存: {fp}")
