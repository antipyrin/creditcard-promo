"""
第 2 层 · 结构化提取（mmx text chat --model MiniMax-M3）
- 一次性送入所有原始数据（400K context 吃得下）
- 输出结构化 JSON 数组，每条含银行/卡种/商户/优惠/时间等字段
输入：cache/raw_<date>.json
输出：cache/extracted_<date>.json
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
TODAY = datetime.now().strftime("%Y-%m-%d")
RAW_FILE = CACHE / f"raw_{TODAY}.json"
OUT_FILE = CACHE / f"extracted_{TODAY}.json"

SYSTEM_PROMPT = """你是信用卡优惠结构化提取助手。
你的任务：从输入的网页搜索结果 / OCR 文本中，提取所有"信用卡优惠活动"，输出严格 JSON 数组。

每条活动的字段：
{
  "title": "活动标题",
  "bank": "银行名（中国银行/广发银行/平安银行/银联/VISA/Mastercard）",
  "card_name": "适用卡种（如 VISA 鼎极无限、长城信用卡、万事达金卡；未知则填'信用卡通用'）",
  "card_org": "卡组织（银联/Visa/Mastercard/不限）",
  "merchant": "商户名称",
  "address": "商户地址（无则空字符串）",
  "district": "行政区（深圳的福田/南山/等；广州的天河/越秀/等；全国则'全国'）",
  "benefit": "优惠内容（如'满100减30'、'5折'、'免费2次'）",
  "start_date": "开始日期（YYYY-MM-DD，无则空字符串）",
  "end_date": "结束日期（YYYY-MM-DD，无则空字符串）",
  "is_today_valid": true/false（今天是否能用）,
  "is_weekly_expiring": true/false（是否本周过期）,
  "is_high_value": true/false（是否机场贵宾厅/接送/酒店/加油返现≥5%/免费权益等硬权益）,
  "source_url": "原文链接（无则空字符串）",
  "source_channel": "来源渠道（search/web/ocr）"
}

要求：
1. 只输出 JSON 数组，不要任何解释、Markdown 包装
2. 与信用卡优惠无关的内容（开户流程、还款说明、积分规则等）一律不提取
3. 提取不到明确活动信息的条目丢弃
4. end_date 必须严格 YYYY-MM-DD 格式
5. is_today_valid 默认为 true（除非明确是过期或预告）

今天是 """ + datetime.now().strftime("%Y-%m-%d") + "。"


def call_mmx(system: str, user_msg: str, max_tokens: int = 8192) -> str:
    """直接调 minimax Messages API（避开 mmx shell 长度限制）"""
    try:
        cfg_path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".mmx" / "config.json"
        if not cfg_path.exists():
            cfg_path = Path.home() / ".mmx" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        api_key = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "https://api.minimaxi.com")

        body = json.dumps({
            "model": "MiniMax-M3",
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
            "max_tokens": max_tokens,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url}/anthropic/v1/messages",
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("content", [])
        if isinstance(content, list) and content:
            return content[0].get("text", "")
        return data.get("text", "")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  minimax API 调用异常: {e}", file=sys.stderr)
        return ""


def extract_promos(raw_items: list[dict]) -> list[dict]:
    """批量结构化提取"""
    if not raw_items:
        return []

    # 把所有原始条目拼成一段文本
    lines = []
    for i, item in enumerate(raw_items, 1):
        lines.append(f"[{i}] 银行={item.get('bank','')} 标题={item.get('title','')}")
        if item.get("snippet"):
            lines.append(f"   摘要={item['snippet'][:500]}")
        if item.get("url"):
            lines.append(f"   链接={item['url']}")
    user_msg = "\n".join(lines)

    print(f"📤 调用 minimax 提取 {len(raw_items)} 条原始数据...", file=sys.stderr)
    response = call_mmx(SYSTEM_PROMPT, user_msg)

    if not response:
        return []

    # 尝试解析 JSON 数组
    # 兼容 minimax 偶尔返回 ```json 包装
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        promos = json.loads(cleaned)
        if isinstance(promos, dict) and "promos" in promos:
            promos = promos["promos"]
        if not isinstance(promos, list):
            print(f"⚠️  返回非数组: {type(promos)}", file=sys.stderr)
            return []
        # 字段补全
        for p in promos:
            p.setdefault("title", "")
            p.setdefault("bank", "")
            p.setdefault("card_name", "信用卡通用")
            p.setdefault("card_org", "不限")
            p.setdefault("merchant", "")
            p.setdefault("address", "")
            p.setdefault("district", "")
            p.setdefault("benefit", "")
            p.setdefault("start_date", "")
            p.setdefault("end_date", "")
            p.setdefault("is_today_valid", True)
            p.setdefault("is_weekly_expiring", False)
            p.setdefault("is_high_value", False)
            p.setdefault("source_url", "")
            p.setdefault("source_channel", "search")
        return promos
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON 解析失败: {e}", file=sys.stderr)
        print(f"   原始返回（前 500 字符）: {cleaned[:500]}", file=sys.stderr)
        return []


import re  # 用在 cleaned 预处理


def main():
    if not RAW_FILE.exists():
        print(f"❌ 原始数据不存在: {RAW_FILE}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    items = raw.get("items", [])
    print(f"📦 读取原始数据 {len(items)} 条", file=sys.stderr)

    promos = extract_promos(items)
    OUT_FILE.write_text(
        json.dumps({"date": TODAY, "count": len(promos), "promos": promos},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 提取完成 · {len(promos)} 条结构化活动 → {OUT_FILE.name}", file=sys.stderr)


if __name__ == "__main__":
    main()