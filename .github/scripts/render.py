"""
第 4 层 · HTML 报告生成（Jinja2 模板渲染）
- 读取 filtered_<date>.json
- 用 Jinja2 渲染 daily-card.html.j2 和 daily-report.md.j2
- 落盘到 daily-promos/<date>.html 和 .md

输入：cache/filtered_<date>.json
输出：daily-promos/<date>.html, daily-promos/<date>.md
"""
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("❌ 缺少 jinja2，请先 pip install jinja2", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
CACHE = ROOT / "cache"
OUT_DIR = ROOT / "daily-promos"
TODAY = datetime.now().strftime("%Y-%m-%d")
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()]

IN_FILE = CACHE / f"filtered_{TODAY}.json"
HTML_OUT = OUT_DIR / f"{TODAY}.html"
MD_OUT = OUT_DIR / f"{TODAY}.md"


def main():
    if not IN_FILE.exists():
        print(f"❌ 筛选文件不存在: {IN_FILE}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data = json.loads(IN_FILE.read_text(encoding="utf-8"))
    # 注入 Jinja2 不能直接读取的字段
    data["weekday"] = WEEKDAY_CN

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # HTML
    html_tpl = env.get_template("daily-card.html.j2")
    HTML_OUT.write_text(html_tpl.render(**data), encoding="utf-8")
    print(f"✅ HTML 报告 → {HTML_OUT.relative_to(ROOT)}", file=sys.stderr)

    # Markdown
    md_tpl = env.get_template("daily-report.md.j2")
    MD_OUT.write_text(md_tpl.render(**data), encoding="utf-8")
    print(f"✅ Markdown 报告 → {MD_OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()