"""
第 5 层 · 推送层
- PushPlus 主通道（国内微信）
- Server酱备用通道
- HTML 报告 URL 用 jsDelivr CDN
- 增强：上传 HTML 到 minimax + 让 minimax 读 HTML 生成精炼摘要（节省 token）

⚠️ 关于 minimax file upload：
  - 正确端点是 POST /v1/files/upload + purpose=retrieval
  - mmx CLI 自带的 file upload 用错了端点（/v1/files）会 404
  - 本文件用 Python 直接调 minimax API 绕过 CLI bug
  - 注意：minimax file storage 不提供公开 URL，仅供 minimax 内部 API 引用
    因此 HTML 报告的公开访问仍用 jsDelivr CDN

输入：daily-promos/<date>.html, cache/filtered_<date>.json
环境变量：
  - PUSHPLUS_TOKEN
  - SCT_SENDKEY (备用)
  - GITHUB_REPOSITORY  (自动)
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
DAILY = ROOT / "daily-promos"
TODAY = datetime.now().strftime("%Y-%m-%d")

FILTERED = CACHE / f"filtered_{TODAY}.json"
HTML_FILE = DAILY / f"{TODAY}.html"


def _load_dotenv() -> None:
    """
    从 .env 加载环境变量（仅当环境变量未设置时）
    .env 已加入 .gitignore，永远不会被 commit
    极简实现，避免依赖 python-dotenv
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 仅当环境变量未设置时才覆盖
        os.environ.setdefault(key, value)


_load_dotenv()  # 脚本启动时自动加载 .env

# ──────────────────────────────────────────────
# minimax 直接 API 调用（绕过 mmx CLI 的 endpoint bug）
# ──────────────────────────────────────────────

def _load_mmx_config() -> tuple[str, str]:
    """从 ~/.mmx/config.json 读 API key 和 base_url"""
    cfg_path = Path.home() / ".mmx" / "config.json"
    if not cfg_path.exists():
        # Windows 兼容
        cfg_path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".mmx" / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cfg.get("api_key", ""), cfg.get("base_url", "https://api.minimaxi.com")
    except Exception as e:
        print(f"⚠️  读 minimax 配置失败: {e}", file=sys.stderr)
        return "", "https://api.minimaxi.com"


def mmx_upload_file(file_path: Path, purpose: str = "retrieval") -> str | None:
    """
    上传文件到 minimax（用正确端点 /v1/files/upload）
    返回 file_id，失败返回 None
    """
    api_key, base_url = _load_mmx_config()
    if not api_key or not file_path.exists():
        return None
    try:
        # 用 curl multipart/form-data 上传（Python urllib 拼 multipart 较繁琐）
        result = subprocess.run([
            "curl", "-sS", "-X", "POST",
            f"{base_url}/v1/files/upload",
            "-H", f"Authorization: Bearer {api_key}",
            "-F", f"file=@{file_path}",
            "-F", f"purpose={purpose}",
        ], capture_output=True, text=True, timeout=60,
           encoding="utf-8", errors="ignore")
        if result.returncode != 0:
            print(f"⚠️  mmx file upload curl 失败: {result.stderr[:200]}", file=sys.stderr)
            return None
        data = json.loads(result.stdout)
        if data.get("base_resp", {}).get("status_code") == 0:
            file_id = data.get("file", {}).get("file_id")
            print(f"✅ 已上传到 minimax · file_id={file_id}", file=sys.stderr)
            return str(file_id)
        print(f"⚠️  mmx file upload 业务失败: {result.stdout[:200]}", file=sys.stderr)
        return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"⚠️  mmx file upload 异常: {e}", file=sys.stderr)
        return None


def mmx_chat_with_file(file_id: str, prompt: str, max_tokens: int = 1024) -> str:
    """
    让 minimax 读取已上传的文件 + 回答问题
    用 Anthropic Messages API + document content block
    """
    api_key, base_url = _load_mmx_config()
    if not api_key:
        return ""
    try:
        body = json.dumps({
            "model": "MiniMax-M3",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "file", "file_id": file_id}},
                    {"type": "text", "text": prompt},
                ],
            }],
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
        if isinstance(content, list):
            for c in content:
                if c.get("type") == "text":
                    return c.get("text", "")
        return ""
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  mmx chat with file 异常: {e}", file=sys.stderr)
        return ""


def maybe_generate_ai_summary(filtered: dict) -> str | None:
    """
    可选增强：上传 HTML 到 minimax + 让它读 HTML 生成更精炼的推送摘要
    失败时优雅降级到本地 build_summary
    """
    if not HTML_FILE.exists():
        return None

    region = filtered.get("region_name", "深圳")
    counts = filtered.get("counts", {})

    # 策略 A（首选）：上传 HTML，让 minimax 读文件 + 生成摘要
    file_id = mmx_upload_file(HTML_FILE, purpose="retrieval")

    # 策略 B（更稳）：直接读取 HTML 文本内容（含结构化数据 + 活动列表），
    # 作为系统 prompt + 用户消息直接发给 minimax，避开 document 解析不稳定问题
    try:
        html_text = HTML_FILE.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️  读 HTML 失败: {e}", file=sys.stderr)
        html_text = ""

    prompt = f"""你是「信用卡优惠日报」的精炼推送助手。下面是今天生成的 HTML 日报全文（{region}地区，共 {counts.get('total', 0)} 条活动）。

⚠️ 严格要求：
1. **只能基于 HTML 中的真实活动**，不要虚构、不要补充任何 HTML 里没有的银行/商户/活动
2. summary-bar 顶部数字就是权威：📍 {region} · 今日 {counts.get('today', 0)} 条 / 本周过期 {counts.get('weekly', 0)} 条 / 高价值 {counts.get('high', 0)} 条（直接用这些数字，不要自己数）
3. 每个分组只列 HTML 里实际有内容的，最多 3 条，标注【银行】商户｜优惠
4. 文末加：⚙️ 想暂停推送：在 GitHub Issue 评论 @promo 暂停
5. 只输出 Markdown 文本，不要 HTML、不要代码块包装、不要任何解释

HTML 日报全文：
```html
{html_text[:12000]}
```
"""
    api_key, base_url = _load_mmx_config()
    if not api_key:
        return None
    try:
        body = json.dumps({
            "model": "MiniMax-M3",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
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
        if isinstance(content, list):
            for c in content:
                if c.get("type") == "text":
                    summary = c.get("text", "")
                    if summary:
                        print(f"✅ minimax AI 摘要生成成功（{len(summary)} 字符，{'file_id' if file_id else 'no-file'}={file_id or 'N/A'}）", file=sys.stderr)
                        return summary
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  minimax AI 摘要失败: {e}", file=sys.stderr)
    return None


def get_repo() -> str:
    """从环境变量读 GitHub 仓库名"""
    return os.environ.get("GITHUB_REPOSITORY", "antipyrin/creditcard-promo")


def build_html_url(repo: str) -> str:
    """生成 jsDelivr CDN URL（私有仓库不能访问，需要公开）"""
    return f"https://cdn.jsdelivr.net/gh/{repo}@main/daily-promos/{TODAY}.html"


def build_raw_url(repo: str) -> str:
    """备用 raw.githubusercontent.com"""
    return f"https://raw.githubusercontent.com/{repo}/main/daily-promos/{TODAY}.html"


def build_summary(filtered: dict) -> str:
    """生成推送的纯文本摘要"""
    region = filtered.get("region_name", "深圳")
    counts = filtered.get("counts", {})
    groups = filtered.get("groups", {})

    lines = [f"📍 {region} · 今日 {counts.get('today', 0)} 条 / 本周过期 {counts.get('weekly', 0)} 条 / 高价值 {counts.get('high', 0)} 条"]

    if groups.get("high"):
        lines.append("\n🌟 高价值：")
        for p in groups["high"][:3]:
            lines.append(f"  · {p.get('title', '')} · {p.get('benefit', '')}")

    if groups.get("today"):
        lines.append("\n🔥 今日可用：")
        for p in groups["today"][:5]:
            lines.append(f"  · 【{p.get('bank', '')}】{p.get('title', '')} · {p.get('merchant', '')} · {p.get('benefit', '')}")

    if groups.get("weekly"):
        lines.append("\n⏰ 本周过期：")
        for p in groups["weekly"][:3]:
            lines.append(f"  · ⚠️ {p.get('end_date', '')} 截止 · {p.get('title', '')}")

    return "\n".join(lines)


def push_pushplus(token: str, title: str, content: str, html_url: str) -> bool:
    """备用通道：推送到 PushPlus（仅当飞书不可用时启用）"""
    full_content = f"""{content}

━━━━━━━━━━━━━━━━━━━━
📱 完整精美卡片：{html_url}"""

    try:
        result = subprocess.run([
            "curl", "-sS", "-X", "POST",
            "https://www.pushplus.plus/send",
            "-d", f"token={token}",
            "-d", f"title={title}",
            "--data-urlencode", f"content={full_content}",
            "-d", "template=html",
        ], capture_output=True, text=True, timeout=15,
           encoding="utf-8", errors="ignore")
        if result.returncode == 0:
            print(f"✅ PushPlus 推送完成 · {title}", file=sys.stderr)
            return True
        print(f"⚠️  PushPlus 推送失败: {result.stderr}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("⚠️  PushPlus 推送超时", file=sys.stderr)
        return False


def push_feishu(webhook_url: str, card: dict) -> bool:
    """主通道：推送到飞书自定义机器人（卡片消息）"""
    try:
        body = json.dumps(card, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"⚠️  飞书响应非 JSON: {raw[:200]}", file=sys.stderr)
            return False
        # 飞书 webhook 返回 {"code":0, "msg":"success"} 或 {"StatusCode":0,...}
        code = data.get("code", data.get("StatusCode"))
        if code == 0:
            print(f"✅ 飞书推送成功", file=sys.stderr)
            return True
        print(f"⚠️  飞书推送业务失败: code={code}, msg={data.get('msg') or data.get('StatusMessage')}", file=sys.stderr)
        return False
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"⚠️  飞书推送网络失败: {e}", file=sys.stderr)
        return False


def build_feishu_card(filtered: dict, html_url: str, repo: str) -> dict:
    """
    构造飞书卡片消息（interactive 类型）
    支持颜色模板、按钮、Markdown 文本块
    """
    region = filtered.get("region_name", "深圳")
    counts = filtered.get("counts", {})
    groups = filtered.get("groups", {})

    # 选颜色：空=灰，高价值=红，今日有=橙，普通=蓝
    total = counts.get("total", 0)
    if total == 0:
        template = "grey"
    elif counts.get("high", 0) > 0:
        template = "red"
    elif counts.get("today", 0) > 0:
        template = "orange"
    else:
        template = "blue"

    elements = []

    # 顶部 summary
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"📍 **{region}** · 今日 {counts.get('today', 0)} 条 "
                f"/ 本周过期 {counts.get('weekly', 0)} 条 "
                f"/ 高价值 {counts.get('high', 0)} 条"
            ),
        },
    })
    elements.append({"tag": "hr"})

    def _promo_line(promo: dict, emoji: str = "•") -> str:
        """格式化为飞书 Markdown 文本"""
        bank = promo.get("bank", "")
        title = promo.get("title", "")
        merchant = promo.get("merchant", "")
        benefit = promo.get("benefit", "")
        end_date = promo.get("end_date", "")
        # 注意：f-string 不能包含 **，会被解析为幂运算
        # 用 chr(42) 占位再拼接，或拆成多个 f-string
        bopen, bclose = "**", "**"
        line = f"{emoji} {bopen}【{bank}】{title}{bclose}"
        if merchant:
            line += f"\n   📍 {merchant}"
        if benefit:
            line += f" · {benefit}"
        if end_date:
            line += f"\n   ⏰ 截止 {end_date}"
        return line

    # 各分组
    if groups.get("high"):
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**🌟 高价值（别错过）**"}})
        for p in groups["high"][:3]:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _promo_line(p)}})
        elements.append({"tag": "hr"})

    if groups.get("today"):
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**🔥 今日可用 · 深圳本地**"}})
        for p in groups["today"][:5]:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _promo_line(p)}})
        elements.append({"tag": "hr"})

    if groups.get("weekly"):
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**⏰ 本周过期**"}})
        for p in groups["weekly"][:3]:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _promo_line(p, "⚠️")}})
        elements.append({"tag": "hr"})

    if groups.get("national"):
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**🌐 全国通用**"}})
        for p in groups["national"][:3]:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _promo_line(p)}})
        elements.append({"tag": "hr"})

    if total == 0:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"📭 今天没找到适合 {region} 的活动，明天再来看～"},
        })
        elements.append({"tag": "hr"})

    # 操作按钮
    actions = []
    if html_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📱 查看完整精美卡片"},
            "url": html_url,
            "type": "primary",
        })
    actions.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "⚙️ 控制推送（暂停/换城市）"},
        "url": f"https://github.com/{repo}/issues/new",
        "type": "default",
    })
    elements.append({"tag": "action", "actions": actions})

    # 备注
    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": "🤖 由 minimax 自动采集 · 数据来源各银行官方渠道"},
        ],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"💳 信用卡优惠日报 · {TODAY}"},
                "template": template,
            },
            "elements": elements,
        },
    }


def main():
    if not FILTERED.exists():
        print(f"❌ 筛选文件不存在: {FILTERED}", file=sys.stderr)
        sys.exit(1)

    filtered = json.loads(FILTERED.read_text(encoding="utf-8"))

    # 生成 AI 摘要（用于本地拼接或日志，非飞书卡片必须）
    summary = maybe_generate_ai_summary(filtered)
    if not summary:
        summary = build_summary(filtered)
        print("ℹ️  使用本地拼接摘要", file=sys.stderr)

    repo = get_repo()
    html_url = build_html_url(repo)
    raw_url = build_raw_url(repo)

    title = f"💳 信用卡优惠日报 {TODAY} · {filtered.get('region_name', '深圳')}"

    # 主通道：飞书 webhook
    feishu_webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if feishu_webhook:
        card = build_feishu_card(filtered, html_url, repo)
        if not push_feishu(feishu_webhook, card):
            # 飞书失败，尝试 PushPlus 兜底
            pushplus_token = os.environ.get("PUSHPLUS_TOKEN", "")
            if pushplus_token:
                print("⚠️  飞书失败，尝试 PushPlus 备用", file=sys.stderr)
                push_pushplus(pushplus_token, title, summary, html_url)
    else:
        print("⚠️  FEISHU_WEBHOOK_URL 未配置", file=sys.stderr)
        # 兜底用 PushPlus（如果还配了）
        pushplus_token = os.environ.get("PUSHPLUS_TOKEN", "")
        if pushplus_token:
            push_pushplus(pushplus_token, title, summary, html_url)


if __name__ == "__main__":
    main()