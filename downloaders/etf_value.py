"""ETF 参考净值快照、正式净值与费率摘要。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re

import requests

from analysis.etf_value import number, value_metrics
from downloaders.eastmoney import EastmoneyClient, to_secid

HK_TIME = timezone(timedelta(hours=8))
FIELDS = "f2,f5,f6,f12,f13,f14,f31,f32,f124,f297,f402,f441"
MORGAN_FEE_URL = "https://www.cifm.com/fund/560530/fee/202409/t20240906_179620.html"


def parse_market(row):
    code = f"{'SH' if str(row.get('f13')) == '1' else 'SZ'}.{row.get('f12')}"
    timestamp = number(row.get("f124"), True)
    try:
        quote_time = datetime.fromtimestamp(timestamp, HK_TIME).isoformat(timespec="seconds") if timestamp else None
    except (OverflowError, OSError, ValueError):
        quote_time = None
    date = str(row.get("f297", ""))
    market_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 and date.isdigit() else None
    result = {"code": code, "name": row.get("f14"), "price": number(row.get("f2"), True),
              "iopv": number(row.get("f441"), True), "bid": number(row.get("f31"), True),
              "ask": number(row.get("f32"), True), "volume_lots": number(row.get("f5")),
              "turnover": number(row.get("f6")), "quote_time": quote_time,
              "market_date": market_date, "iopv_time": None,
              "provider_discount_pct": number(row.get("f402")),
              "market_source": "东方财富 ETF 市场",
              "market_source_url": "https://quote.eastmoney.com/center/gridlist.html#fund_etf"}
    result.update(value_metrics(result))
    return result


def fetch_value_snapshot(items):
    requested = {code: name for code, name in items}
    rows = {code: {"code": code, "name": name} for code, name in items}
    client = EastmoneyClient(timeout=8)
    params = {"secids": ",".join(to_secid(code) for code in requested),
              "fields": FIELDS, "fltt": 2, "invt": 2}
    try:
        payload = None
        last_error = None
        for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
            for attempt in range(2):
                try:
                    payload = client._get(f"https://{host}/api/qt/ulist.np/get", params)
                    if not (payload.get("data") or {}).get("diff"):
                        raise RuntimeError("ETF 参考净值接口无数据")
                    break
                except Exception as error:
                    last_error = error
                    client._switch_proxy_mode()
            if payload and (payload.get("data") or {}).get("diff"):
                break
        if not payload or not (payload.get("data") or {}).get("diff"):
            raise RuntimeError(f"ETF 参考净值获取失败：{type(last_error).__name__}")
        for raw in payload["data"]["diff"]:
            item = parse_market(raw)
            if item["code"] in requested:
                rows[item["code"]] = item
    finally:
        client._session.close()
    return rows


def _session():
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"})
    return session


def parse_fee_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    values = {}
    for titles, key in [(("管理费率", "管理费"), "management_fee_pct"),
                        (("托管费率", "托管费"), "custody_fee_pct")]:
        heading = soup.find(lambda tag: tag.name in ("th", "td") and tag.get_text(strip=True) in titles)
        sibling = heading.find_next_sibling("td") if heading else None
        match = re.search(r"([\d.]+)\s*%", sibling.get_text()) if sibling else None
        values[key] = number(match.group(1)) if match else None
    return values


def fetch_fund_reference(code, should_stop=lambda: False):
    bare = code.split(".")[1]
    result = {"code": code, "nav": None, "nav_date": None}
    if should_stop():
        return result
    with _session() as session:
        url = "https://api.fund.eastmoney.com/f10/lsjz"
        try:
            for attempt in range(2):
                try:
                    response = session.get(url, params={"fundCode": bare, "pageIndex": 1, "pageSize": 1}, timeout=8)
                    break
                except requests.RequestException:
                    if attempt or should_stop():
                        raise
                    session.trust_env = True
            response.raise_for_status()
            rows = (response.json().get("Data") or {}).get("LSJZList") or []
            if rows:
                result.update(nav=number(rows[0].get("DWJZ"), True), nav_date=rows[0].get("FSRQ"),
                              nav_source_url=f"https://fundf10.eastmoney.com/jjjz_{bare}.html")
        except Exception as error:
            result["nav_error"] = type(error).__name__
        fee_url = f"https://fundf10.eastmoney.com/jbgk_{bare}.html"
        if should_stop():
            return result
        try:
            response = session.get(fee_url, timeout=8)
            response.raise_for_status()
            response.encoding = "utf-8"
            result.update(parse_fee_html(response.text), fee_source_url=fee_url,
                          fee_verified=False, fee_note="东财基金概况，未逐只核对基金公司公告")
        except Exception as error:
            result["fee_error"] = type(error).__name__
        if code == "SH.560530":
            try:
                response = session.get(MORGAN_FEE_URL, timeout=8)
                response.raise_for_status()
                response.encoding = "utf-8"
                official = parse_fee_html(response.text)
                if all(value is not None for value in official.values()):
                    result.update(official, fee_source_url=MORGAN_FEE_URL, fee_verified=True,
                                  fee_verified_at=datetime.now(HK_TIME).isoformat(timespec="seconds"),
                                  fee_note="摩根基金官网费率页")
            except requests.RequestException:
                pass
    return result


def fetch_fund_references(items, should_stop=lambda: False):
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {row["code"]: row for row in pool.map(
            lambda code: fetch_fund_reference(code, should_stop), [code for code, _ in items])}
