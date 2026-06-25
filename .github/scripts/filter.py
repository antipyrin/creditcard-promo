"""
第 3 层 · 去重 + 地域 + 时效筛选（纯 Python，零 token）
- 对比 cache/promos_history.json，丢弃 7 天内已推过的
- 按 regions.yml 过滤（默认深圳）
- 时效分桶：今日 / 本周过期 / 高价值 / 全国通用
- 价值分级

输入：cache/extracted_<date>.json
输出：cache/filtered_<date>.json
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
CACHE = ROOT / "cache"
STATE = ROOT / "state"
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_DT = datetime.now()
WEEK_LATER = TODAY_DT + timedelta(days=7)

EXTRACT_FILE = CACHE / f"extracted_{TODAY}.json"
OUT_FILE = CACHE / f"filtered_{TODAY}.json"
HISTORY_FILE = CACHE / "promos_history.json"


def normalize_title(title: str) -> str:
    """标准化标题用于去重"""
    if not title:
        return ""
    return re.sub(r"\s+|[【】\[\]（）()优惠活动]", "", title)[:40]


def load_history() -> set[str]:
    """加载最近 7 天已推送的活动指纹"""
    if not HISTORY_FILE.exists():
        return set()
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    fingerprints = set()
    cutoff = (TODAY_DT - timedelta(days=7)).strftime("%Y-%m-%d")
    for day_entry in history.get("days", []):
        if day_entry.get("date", "") >= cutoff:
            for fp in day_entry.get("fingerprints", []):
                fingerprints.add(fp)
    return fingerprints


def save_history(filtered: dict) -> None:
    """追加今日指纹到历史"""
    if HISTORY_FILE.exists():
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    else:
        history = {"days": []}
    # 清理 30 天前的历史
    cutoff = (TODAY_DT - timedelta(days=30)).strftime("%Y-%m-%d")
    history["days"] = [d for d in history["days"] if d.get("date", "") >= cutoff]
    history["days"].append({
        "date": TODAY,
        "fingerprints": [p["_fp"] for p in filtered.get("all_kept", []) if p.get("_fp")],
    })
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_local_for_region(promo: dict, region: dict) -> bool:
    """判断一条活动是否属于指定城市"""
    if not region:
        return True
    text = " ".join([
        promo.get("merchant", ""),
        promo.get("address", ""),
        promo.get("district", ""),
        promo.get("title", ""),
        promo.get("benefit", ""),
    ]).lower()

    # 行政区
    for d in region.get("districts", []):
        if d.lower() in text:
            return True
    # 地标
    for lm in region.get("landmarks", []):
        if lm.lower() in text:
            return True
    # 交通
    for tr in region.get("transit", []):
        if tr.lower() in text:
            return True
    # 显式地理
    for geo in region.get("explicit_geo", []):
        if geo.lower() in text:
            return True
    return False


def is_national(promo: dict, national: dict) -> bool:
    """判断是否是全国通用"""
    text = " ".join([
        promo.get("title", ""),
        promo.get("benefit", ""),
        promo.get("merchant", ""),
        promo.get("card_name", ""),
    ]).lower()
    # 显式全国/不限地域关键词
    if any(kw in text for kw in ["全国", "线上", "在线", "app", "京东", "天猫",
                                    "12306", "携程", "滴滴", "视频会员",
                                    "爱奇艺", "优酷", "腾讯视频", "网易云"]):
        return True
    # 数字频道
    for ch in national.get("channels", []):
        if ch.lower() in text:
            return True
    return False


def parse_date(s: str) -> datetime | None:
    """解析日期字符串"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 兼容中文日期
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def update_today_flag(promo: dict) -> None:
    """根据 end_date 重新计算 is_today_valid / is_weekly_expiring"""
    end = parse_date(promo.get("end_date", ""))
    if end:
        promo["is_today_valid"] = TODAY_DT <= end
        promo["is_weekly_expiring"] = TODAY_DT <= end <= WEEK_LATER
    # 高价值自动标记
    text = " ".join([promo.get("title", ""), promo.get("benefit", "")])
    if any(kw in text for kw in ["贵宾厅", "vip", "礼宾", "接送", "机场",
                                    "高铁", "酒店", "免费", "加油返", "年费减免",
                                    "fhr", "the hotel"]):
        promo["is_high_value"] = True


def main():
    if not EXTRACT_FILE.exists():
        print(f"❌ 提取文件不存在: {EXTRACT_FILE}", file=sys.stderr)
        sys.exit(1)

    status = yaml.safe_load((STATE / "status.yml").read_text(encoding="utf-8"))
    regions_cfg = yaml.safe_load((CONFIG / "regions.yml").read_text(encoding="utf-8"))

    region_name = status.get("current_region", "shenzhen")
    region = regions_cfg["regions"].get(region_name, {})
    national = regions_cfg["regions"].get("national", {})

    data = json.loads(EXTRACT_FILE.read_text(encoding="utf-8"))
    promos = data.get("promos", [])
    print(f"📦 读取 {len(promos)} 条结构化活动", file=sys.stderr)

    # 0. 更新今日 / 本周过期 / 高价值标记
    for p in promos:
        update_today_flag(p)

    # 0.1 丢弃已过期活动
    before = len(promos)
    promos = [
        p for p in promos
        if not parse_date(p.get("end_date", ""))  # 无 end_date 保留
        or parse_date(p.get("end_date", "")) >= TODAY_DT  # 未过期保留
    ]
    dropped = before - len(promos)
    if dropped:
        print(f"🗑️  丢弃 {dropped} 条已过期活动", file=sys.stderr)

    # 1. 去重（标题指纹）
    seen = set()
    deduped = []
    for p in promos:
        fp = normalize_title(p.get("title", "")) + "|" + p.get("merchant", "")[:20]
        if not fp.strip("|"):
            continue
        p["_fp"] = fp
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(p)

    # 2. 排除 7 天内已推送的
    history_fps = load_history()
    fresh = [p for p in deduped if p["_fp"] not in history_fps]

    # 3. 地域筛选
    local_promos = [p for p in fresh if is_local_for_region(p, region)]
    national_promos = [p for p in fresh if is_national(p, national) and not is_local_for_region(p, region)]

    # 4. 时效分桶
    groups = {"high": [], "today": [], "weekly": [], "national": national_promos}
    for p in local_promos:
        if p.get("is_high_value"):
            groups["high"].append(p)
        elif p.get("is_today_valid"):
            groups["today"].append(p)
        elif p.get("is_weekly_expiring"):
            groups["weekly"].append(p)

    # 5. 按标题排序（保证稳定输出）
    for k in groups:
        groups[k].sort(key=lambda x: (not x.get("is_high_value", False),
                                      x.get("end_date", "z"), x.get("title", "")))

    counts = {
        "high": len(groups["high"]),
        "today": len(groups["today"]),
        "weekly": len(groups["weekly"]),
        "national": len(groups["national"]),
        "total": len(local_promos) + len(national_promos),
    }

    # 输出
    out = {
        "date": TODAY,
        "region": region_name,
        "region_name": region.get("name", region_name),
        "groups": groups,
        "counts": counts,
        "all_kept": local_promos + national_promos,  # 用于写历史
    }
    OUT_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 筛选完成 · {region_name} · 高 {counts['high']} / 今 {counts['today']} / 本周 {counts['weekly']} / 全国 {counts['national']}", file=sys.stderr)

    # 6. 写历史
    save_history(out)


if __name__ == "__main__":
    main()