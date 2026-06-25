"""
第 1 层 · 采集层（混合策略）
- curl 抓银行官网 HTML
- mmx search query 搜公众号 + 站内活动
- minimax vision describe OCR 用户截图 / PDF
输出：cache/raw_<date>.json
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
from urllib.request import urlopen, Request
from urllib.error import URLError
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
CACHE = ROOT / "cache"
TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = CACHE / f"raw_{TODAY}.json"


def run_mmx_search(query: str, count: int = 10) -> list[dict]:
    """直接调 minimax search API（避开 mmx CLI 的 base_url bug）"""
    try:
        cfg_path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".mmx" / "config.json"
        if not cfg_path.exists():
            cfg_path = Path.home() / ".mmx" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        api_key = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "https://api.minimaxi.com")

        body = json.dumps({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/v1/coding_plan/search",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("organic", [])[:count]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  search '{query}' 失败: {e}", file=sys.stderr)
        return []


def curl_html(url: str, timeout: int = 15) -> str:
    """抓取网页 HTML（带 UA）"""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
        with urlopen(req, timeout=timeout) as resp:
            # 只取前 200KB，足够提取活动列表
            return resp.read(200_000).decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, UnicodeDecodeError) as e:
        print(f"⚠️  curl '{url}' 失败: {e}", file=sys.stderr)
        return ""


def ocr_image(image_path: Path) -> dict:
    """minimax vision 识别单张图片"""
    try:
        # Windows 下 mmx 是 .cmd 文件，subprocess 需要 shell=True
        # 转义反斜杠防止 shell 误解析
        img_path = str(image_path).replace("\\", "/")
        result = subprocess.run(
            f'mmx vision describe --image "{img_path}" '
            f'--prompt "提取图片中的信用卡优惠活动信息：活动标题、适用卡种、银行、商户名、优惠内容（满减/折扣/返现）、起止时间、限城市/门店。以 JSON 格式输出，如果无活动信息则输出空对象。" '
            f'--output json',
            capture_output=True, text=True, timeout=60, shell=True,
            encoding="utf-8", errors="ignore",
        )
        data = json.loads(result.stdout)
        return {
            "source": "vision_ocr",
            "image": str(image_path.name),
            "content": data.get("content", ""),
            "raw": data,
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"⚠️  vision OCR '{image_path}' 失败: {e}", file=sys.stderr)
        return {}


def collect_from_sources() -> list[dict]:
    """按 sources.yml 逐个采集"""
    sources = yaml.safe_load((CONFIG / "sources.yml").read_text(encoding="utf-8"))
    items = []

    # 兼容 sources.yml 顶层是否包了 sources: 字段
    if isinstance(sources, dict) and "sources" in sources:
        sources = sources["sources"]

    for src in sources:
        src_id = src["id"]
        bank = src["bank"]
        name = src["name"]
        stype = src["type"]
        priority = src.get("priority", "low")

        print(f"📥 [{priority}] {bank} · {name}", file=sys.stderr)

        if stype == "search":
            for q in src.get("search_queries", []):
                results = run_mmx_search(q)
                for r in results:
                    items.append({
                        "source_id": src_id,
                        "bank": bank,
                        "channel": "search",
                        "query": q,
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "url": r.get("link", ""),
                        "date": r.get("date", ""),
                    })

        elif stype == "web":
            html = curl_html(src["url"])
            if html:
                # 简单提取：抓 href 和 title 文本块
                links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]{4,80})</a>', html)
                for href, text in links[:30]:
                    if any(kw in text for kw in ["优惠", "活动", "立减", "满减", "积分", "权益", "折扣"]):
                        items.append({
                            "source_id": src_id,
                            "bank": bank,
                            "channel": "web",
                            "title": text.strip(),
                            "snippet": "",
                            "url": href if href.startswith("http") else f"{src['url'].rstrip('/')}/{href.lstrip('/')}",
                        })

        elif stype == "ocr_dir":
            # 遍历目录里所有支持的图片 / PDF
            extensions = src.get("extensions", [])
            for f in sorted(Path(src["path"]).iterdir()):
                if f.suffix.lstrip(".").lower() in extensions and not f.name.startswith("."):
                    ocr = ocr_image(f)
                    if ocr:
                        items.append({
                            "source_id": src_id,
                            "bank": "USER",
                            "channel": "user_upload",
                            "title": f.name,
                            "snippet": ocr.get("content", ""),
                            "url": "",
                            "ocr_raw": ocr.get("raw"),
                        })

    return items


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"🚀 开始采集 · {TODAY}", file=sys.stderr)
    items = collect_from_sources()
    OUTPUT_FILE.write_text(
        json.dumps({"date": TODAY, "count": len(items), "items": items},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 采集完成 · 共 {len(items)} 条原始数据 → {OUTPUT_FILE.name}", file=sys.stderr)


if __name__ == "__main__":
    main()