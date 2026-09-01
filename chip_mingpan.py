# -*- coding: utf-8 -*-
"""明盘筹码一键采集 — 股东户数/F10(十大流通股东+基金)/龙虎榜/大宗/两融/资金流
数据源: 东财 datacenter+emweb (超时自动重试), 腾讯行情兜底, 新浪资金流兜底
用法: python chip_mingpan.py   (股票列表在 STOCKS 里改)
2026-08-19 三股(688825/300776/000811)实战验证
"""
import json, time, requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://data.eastmoney.com/"}

STOCKS = [
    ("688825", "SH", "长鑫科技"),
    ("300776", "SZ", "帝尔激光"),
    ("000811", "SZ", "冰轮环境"),
]

def get(url, params=None, retry=3):
    for i in range(retry):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=12)
            return r.json()
        except Exception as e:
            if i == retry - 1:
                print(f"  WARN 请求失败({e}): {url[:80]}")
                return None
            time.sleep(2)

def secid(code, market):
    return ("1." if market == "SH" else "0.") + code

def rows_of(d):
    """datacenter 响应容错: result 可能为 null"""
    return ((d or {}).get("result") or {}).get("data") or []

def quote(code, market):
    """东财行情 + 腾讯兜底(东财 push2 整域超时常见)"""
    d = get("https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": secid(code, market), "fields": "f43,f57,f58,f84,f85,f116,f117,f162,f167"}, retry=2)
    data = (d or {}).get("data") or {}
    if data:
        def v(k):
            try:
                return float(data.get(k))
            except (TypeError, ValueError):
                return None
        print(f"  现价:{v('f43')/100 if v('f43') else None} 总市值:{v('f116')/1e8:.1f}亿 流通市值:{v('f117')/1e8:.1f}亿 "
              f"流通股本:{v('f85')/1e8:.2f}亿股 PE(TTM):{v('f162')} PB:{v('f167')}")
    else:
        print("  东财行情超时 -> 腾讯兜底:")
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={market.lower()}{code}", timeout=8)
        r.encoding = "gbk"
        p = r.text.split("~")
        if len(p) > 45:
            print(f"  [腾讯] 现价:{p[3]} 涨跌:{p[31]}% 换手:{p[38]}% 量比:{p[49]} 流通市值:{p[44]}亿 总市值:{p[45]}亿")
            print(f"  [腾讯] 流通股本={float(p[44])*1e8/float(p[3]):.0f}股 (给chip_distribution.py第3参数)")
    except Exception as e:
        print("  腾讯兜底失败:", e)

def holder_num(code, market):
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {"reportName": "RPT_HOLDERNUM_DET", "columns": "ALL", "pageSize": "8",
              "sortColumns": "END_DATE", "sortTypes": "-1",
              "filter": f'(SECUCODE="{code}.{market}")', "source": "HSF10", "client": "PC"}
    rows = rows_of(get(url, params))
    if not rows:
        print("  股东户数: 无数据")
        return
    # 新鲜度校验: 最新记录过旧(>400天) = 数据源缺失(改名票/长期未披露), 提示而非误导
    import datetime
    latest = rows[0].get('END_DATE', '')[:10]
    try:
        days = (datetime.date.today() - datetime.date.fromisoformat(latest)).days
    except Exception:
        days = 9999
    if days > 400:
        print(f"  ⚠️ 股东户数数据缺失: 东财最新记录仅 {latest} ({days}天前) — 改名票/长期未披露, 户数趋势不可用")
        return
    for row in rows[:8]:
        print(f"  {row.get('END_DATE','')[:10]} 户数={row.get('HOLDER_NUM')} 环比={row.get('HOLDER_NUM_RATIO')}% 户均={row.get('AVG_HOLD_NUM')}")

def page_ajax(code, market):
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={market}{code}"
    d = get(url)
    if not d:
        print("  F10: 无数据")
        return
    sdltgd = d.get("sdltgd") or []
    print(f"  十大流通股东({len(sdltgd)}):")
    for i, g in enumerate(sdltgd[:10], 1):
        print(f"    {i}. {g.get('HOLDER_NAME')} 持股{g.get('HOLD_NUM')}股({g.get('HOLD_NUM_RATIO')}%) 变动:{g.get('HOLD_NUM_CHANGE')} 类型:{g.get('HOLDER_TYPE')}")
    jjcg = d.get("jjcg") or []
    print(f"  基金持仓({len(jjcg)}):")
    for g in jjcg[:8]:
        print(f"    {g.get('HOLDER_NAME')} {g.get('TOTAL_SHARES')}股({g.get('TOTALSHARES_RATIO')}%) 市值{g.get('HOLD_VALUE')}万")
    if not jjcg:
        print("    (无)")

def lhb(code):
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "ALL", "pageSize": "20",
              "sortColumns": "TRADE_DATE", "sortTypes": "-1",
              "filter": f'(SECURITY_CODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    if not rows:
        print("  龙虎榜(60日): 无")
        return
    for r in rows:
        net = r.get('BILLBOARD_NET_AMT')
        net_s = f"{float(net)/1e4:+.0f}万" if net not in (None, '-') else "N/A"
        print(f"  {r.get('TRADE_DATE','')[:10]} {r.get('EXPLAIN')} 净买额:{net_s}")

def block_trade(code):
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL", "pageSize": "20",
              "sortColumns": "TRADE_DATE", "sortTypes": "-1",
              "filter": f'(SECURITY_CODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    if not rows:
        print("  大宗交易(60日): 无")
        return
    for r in rows:
        print(f"  {str(r.get('TRADE_DATE'))[:10]} 价{r.get('DEAL_PRICE')} 额{r.get('DEAL_AMT')} 折价率{r.get('PREMIUM_RATE')}%")

def rzrq(code, market):
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_RZRQ_LSHJ", "columns": "ALL", "pageSize": "10",
              "sortColumns": "DATE", "sortTypes": "-1",
              "filter": f'(SCODE="{code}")', "source": "WEB"}
    rows = rows_of(get(url, params))
    if not rows:
        print("  两融: 非两融标的或无数据")
        return
    for r in rows[:6]:
        print(f"  {str(r.get('DATE'))[:10]} 融资余额:{r.get('RZYE')} 融资净买入:{r.get('RZJME')}")

def fflow_em(code, market):
    """东财主力资金流(近10日) — 超时则返回 None 交给新浪兜底"""
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {"lmt": "10", "klt": "101", "secid": secid(code, market),
              "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"}
    for _ in range(3):
        try:
            d = requests.get(url, params=params, headers=UA, timeout=10).json()
            ks = (d or {}).get("data", {}).get("klines") or []
            if ks:
                for k in ks:
                    p = k.split(",")
                    print(f"  {p[0]} 主力净额:{float(p[1])/1e4:.0f}万 超大:{float(p[5])/1e4:+.0f}万 大单:{float(p[4])/1e4:+.0f}万")
                return True
        except Exception:
            time.sleep(2)
    return False

def fflow_sina(code, market):
    """新浪资金流兜底 — ⚠️ page/num 参数无效返回全量历史, 必须只取前N行"""
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"MoneyFlow.ssl_qsfx_zjlrqs?daima={market.lower()}{code}&page=1&num=10")
    try:
        txt = requests.get(url, headers=UA, timeout=12).text.strip()
        if txt.startswith("var "):
            txt = txt[txt.index("=") + 1:].strip().rstrip(";")
        data = json.loads(txt)[:10]
        tot = 0
        for d in data:
            net = float(d.get("netamount", 0)) / 1e4
            r0 = float(d.get("r0_net", 0)) / 1e4
            tot += net
            print(f"  {d.get('opendate')} 净流入:{net:+.0f}万 超大单:{r0:+.0f}万")
        print(f"  近10日合计净流入: {tot:+.0f}万")
    except Exception as e:
        print("  新浪资金流失败:", e)

for code, market, name in STOCKS:
    print("=" * 60)
    print(f"{name} {code}.{market}")
    print("=" * 60)
    print("[行情]")
    quote(code, market)
    print("[股东户数]")
    holder_num(code, market)
    print("[F10 十大流通股东/基金]")
    page_ajax(code, market)
    print("[龙虎榜]")
    lhb(code)
    print("[大宗交易]")
    block_trade(code)
    print("[两融]")
    rzrq(code, market)
    print("[主力资金流 近10日]")
    if not fflow_em(code, market):
        print("  东财超时 -> 新浪兜底:")
        fflow_sina(code, market)
    print()
