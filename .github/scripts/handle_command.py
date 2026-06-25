"""
指令处理 · 解析 GitHub Issue 评论里的 @promo 命令并修改 state/status.yml
支持：
  @promo 暂停         → enabled: false
  @promo 恢复         → enabled: true
  @promo 切换广州     → current_region: guangzhou
  @promo 切换深圳     → current_region: shenzhen
  @promo 立即推送     → 触发 daily-promo.yml（占位）

环境变量：
  - COMMENT_BODY: GitHub Issue 评论内容
  - GITHUB_REPOSITORY: 仓库名
  - GITHUB_TOKEN: 用于给 Issue 回复
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ 缺少 pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state" / "status.yml"
COMMENT = os.environ.get("COMMENT_BODY", "")


def load_status() -> dict:
    return yaml.safe_load(STATE.read_text(encoding="utf-8"))


def save_status(status: dict) -> None:
    STATE.write_text(
        yaml.dump(status, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def reply_to_issue(msg: str) -> None:
    """给 Issue 评论（占位）"""
    print(f"💬 自动回复: {msg}", file=sys.stderr)


def trigger_workflow() -> None:
    """触发 daily-promo.yml（占位）"""
    print("🚀 触发 daily-promo.yml（占位）", file=sys.stderr)


def handle_command(body: str) -> None:
    """解析指令"""
    if "@promo" not in body.lower():
        return

    status = load_status()
    lower = body.lower()

    if "暂停" in body:
        status["enabled"] = False
        save_status(status)
        reply_to_issue("✅ 已暂停推送。\n恢复方式：评论 `@promo 恢复`")

    elif "恢复" in body:
        status["enabled"] = True
        save_status(status)
        reply_to_issue("✅ 已恢复推送。下次推送时间见 state/status.yml")

    elif "切换广州" in body or "切到广州" in body or "广州" in body:
        status["current_region"] = "guangzhou"
        save_status(status)
        reply_to_issue("✅ 已切换到 **广州**。下次推送生效")

    elif "切换深圳" in body or "切到深圳" in body or "深圳" in body:
        status["current_region"] = "shenzhen"
        save_status(status)
        reply_to_issue("✅ 已切换到 **深圳**。下次推送生效")

    elif "立即推送" in body or "现在推送" in body:
        trigger_workflow()
        reply_to_issue("🚀 已触发立即推送，请等待约 1-2 分钟")

    elif "状态" in body or "查看" in body:
        reply_to_issue(
            f"📊 当前状态：\n"
            f"- 推送：{'✅ 开启' if status.get('enabled') else '⏸️ 暂停'}\n"
            f"- 地区：{status.get('current_region')}\n"
            f"- 时间：{status.get('push_time')}"
        )
    else:
        reply_to_issue(
            "❓ 未识别的指令。支持的指令：\n"
            "- `@promo 暂停` / `@promo 恢复`\n"
            "- `@promo 切换广州` / `@promo 切换深圳`\n"
            "- `@promo 立即推送`\n"
            "- `@promo 查看状态`"
        )


def main():
    if not COMMENT:
        print("❌ COMMENT_BODY 环境变量为空", file=sys.stderr)
        sys.exit(1)

    print(f"📥 收到指令: {COMMENT[:100]}", file=sys.stderr)
    handle_command(COMMENT)
    print("✅ 指令处理完成", file=sys.stderr)


if __name__ == "__main__":
    main()