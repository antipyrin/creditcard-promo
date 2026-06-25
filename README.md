# 💳 信用卡优惠日报自动化

每天 07:30 自动采集**中国银行长城信用卡**、**广发 VISA 鼎极无限卡**、**平安银行标准万事达金卡**三张卡的官方优惠信息，按地域（默认深圳）和时效筛选后，通过**飞书**推送到你手机。

完全云端运行，**电脑可以一直关机**。

## ✨ 功能特性

- 🌐 **全渠道采集**：银行官网、公众号、卡组织（VISA/Mastercard/银联）、用户截图 OCR
- 📍 **地域筛选**：默认深圳，可一键切换广州
- ⏰ **时效分桶**：今日可用 / 本周过期 / 高价值 / 全国通用
- 💎 **缓存去重**：7 天内已推送的活动不再重复
- 🎨 **飞书卡片**：彩色卡片 + 按钮 + Markdown + 分组
- 🔌 **GitHub Issue 反向控制**：`@promo 暂停/恢复/切换地区`
- 🤖 **minimax 全栈**：search / vision OCR / text chat / file upload 全部用自家能力
- 💰 **零成本**：GitHub Actions + 飞书机器人 webhook + jsDelivr CDN

## 🛠️ 技术栈

| 层 | 工具 | 用途 |
|---|---|---|
| 调度 | GitHub Actions cron | 云端定时 |
| AI 引擎 | `mmx text chat --model MiniMax-M3` | 结构化提取 + AI 摘要 |
| 搜索 | minimax search API (`/v1/coding_plan/search`) | 银行官网 + 公众号 |
| OCR | `mmx vision describe` | 银行海报 / APP 截图 / PDF |
| 数据处理 | Python + Jinja2 + PyYAML | 去重 / 筛选 / 模板渲染 |
| **推送** | **飞书 webhook（卡片消息）** | 主推送通道 |
| 报告托管 | jsDelivr CDN + GitHub 仓库 | HTML 卡片链接 |
| 反向控制 | GitHub Issue 评论 | 暂停/恢复/切换地区 |

## 📁 目录结构

```
creditcard-promo/
├── .github/
│   ├── workflows/
│   │   ├── daily-promo.yml        # 主推送工作流（每天 07:30）
│   │   └── command-handler.yml    # 微信端指令接收
│   └── scripts/
│       ├── collect.py             # 第 1 层：采集
│       ├── extract.py             # 第 2 层：结构化提取
│       ├── filter.py              # 第 3 层：去重 + 筛选
│       ├── render.py              # 第 4 层：HTML 渲染
│       ├── notify.py              # 第 5 层：推送
│       └── handle_command.py      # 指令处理
├── config/
│   ├── cards.yml                  # 三张卡的卡种配置
│   ├── sources.yml                # 信息源 URL / 公众号清单
│   └── regions.yml                # 深圳 + 广州关键词库
├── templates/
│   ├── daily-card.html.j2         # 精美 HTML 卡片模板
│   └── daily-report.md.j2         # Markdown 存档模板
├── state/
│   └── status.yml                 # 推送开关 + 当前地区
├── cache/
│   ├── raw_<date>.json            # 当日原始采集数据
│   ├── extracted_<date>.json      # 结构化提取结果
│   ├── filtered_<date>.json       # 筛选后数据
│   └── promos_history.json        # 7 天去重历史
├── screenshots/                   # 用户上传截图（OCR 用）
├── pdfs/                          # 用户上传 PDF（OCR 用）
├── daily-promos/                  # 历史日报存档
│   ├── 2026-06-25.html
│   ├── 2026-06-25.md
│   └── ...
├── .env.example                   # 环境变量样例
└── README.md
```

## 🚀 快速开始

### 1. 准备账号和密钥

| 项 | 用途 | 获取 |
|---|---|---|
| GitHub 账号 | 仓库托管 + Actions 调度 | github.com 注册 |
| minimax API Key | AI 调用 | `~/.mmx/config.json` 里的 `api_key` |
| **飞书 Webhook URL** | **主推送通道** | 见下方飞书设置 |
| PushPlus Token（可选） | 备用通道 | pushplus.plus 关注公众号拿 token |

### 2. 创建飞书推送通道

1. 飞书 App → 消息 → 右上角 "+" → 创建群
2. 自己创建一个**只有你自己的群**（或拉一个好友都行）
3. 进入群 → 右上角 "..." → 设置 → 群机器人 → 添加机器人 → **自定义机器人**
4. 设置机器人名字（如"信用卡日报"）
5. 复制 **webhook URL**（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx`）

### 3. 创建 GitHub 仓库

```bash
cd creditcard-promo
git init
git add .
git commit -m "feat: 初始化信用卡优惠日报工作流"
git branch -M main
git remote add origin https://github.com/<你的用户名>/creditcard-promo.git
git push -u origin main
```

> ⚠️ **重要**：仓库必须设为**公开**，否则 jsDelivr CDN 无法访问 HTML 报告。如果对隐私敏感，可考虑用 GitHub Pages 替代 jsDelivr。

### 4. 配置 GitHub Secrets

仓库 Settings → Secrets and variables → Actions → New repository secret：

| Name | Value | 必填 |
|---|---|---|
| `MMX_API_KEY` | minimax API Key | ✅ |
| `FEISHU_WEBHOOK_URL` | 飞书机器人 webhook URL | ✅ |
| `PUSHPLUS_TOKEN` | PushPlus Token（飞书失败的兜底） | 可选 |
| `SCT_SENDKEY` | Server酱 SendKey（备用） | 可选 |

### 5. 第一次试跑

仓库 Actions 标签 → 选 `每日信用卡优惠推送` → Run workflow → 等 1-2 分钟

### 6. 接入指令控制

新建一个 Issue（标题随意），在评论里输入：

```
@promo 查看状态
```

bot 会自动回复。

支持的指令：

| 指令 | 作用 |
|---|---|
| `@promo 暂停` | 停止推送 |
| `@promo 恢复` | 恢复推送 |
| `@promo 切换深圳` | 改推深圳 |
| `@promo 切换广州` | 改推广州 |
| `@promo 立即推送` | 立刻跑一次 |
| `@promo 查看状态` | 看当前配置 |

## 📲 飞书推送效果

每天 07:30 自动收到一条飞书卡片消息，类似这样：

```
┌─────────────────────────────────────────┐
│  💳 信用卡优惠日报 · 2026-06-25（周四）    │
├─────────────────────────────────────────┤
│  📍 深圳 · 今日 3 条 / 本周过期 0 条       │
│  / 高价值 0 条                          │
├─────────────────────────────────────────┤
│  🔥 今日可用 · 深圳本地                   │
│  • 【银联】云闪付商超节满60减25元         │
│     📍 深圳指定商超 · 每日6-22点          │
│  • 【银联】云闪付无感加油9折最高减20元    │
│     📍 深圳指定加油站 · 月限 4 次         │
│  • 【平安银行】潮汕大目牛肉火锅           │
│     📍 潮汕大目牛肉火锅城 · 周三抢满200立减100 │
├─────────────────────────────────────────┤
│  🌐 全国通用                             │
│  • 【平安银行】车主卡权益                 │
│  • 【银联】蘑菇街满30减8元                │
├─────────────────────────────────────────┤
│  [📱 查看完整精美卡片] [⚙️ 控制推送]       │
├─────────────────────────────────────────┤
│  🤖 由 minimax 自动采集                   │
└─────────────────────────────────────────┘
```

## 🧪 本地测试

```bash
# 1. 安装依赖
pip install jinja2 pyyaml requests

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实密钥

# 3. 跑全流程（本地无 minimax CLI 也行，collect 会失败但其他层可验证）
python .github/scripts/collect.py
python .github/scripts/extract.py
python .github/scripts/filter.py
python .github/scripts/render.py
python .github/scripts/notify.py

# 4. 查看生成的报告
# 浏览器打开 daily-promos/2026-06-25.html
```

## 📊 Token 消耗与成本

每天约消耗 **55K input + 13K output tokens**（MiniMax-M3 国内价格）。

| 项 | 单日消耗 | 月度估算 |
|---|---|---|
| Token | ~70K | ~2.1M |
| 费用（minimax 国内） | < ¥0.05 | **< ¥1** |

GitHub Actions 私有仓库免费额度 2000 分钟/月，本项目每天约 5 分钟，**完全在免费额度内**。

PushPlus 免费版每天 5 条推送，**够用**。

## 🔧 自定义配置

### 改默认地区

编辑 `state/status.yml`：

```yaml
current_region: shenzhen   # 改成 guangzhou 或 both
```

### 改推送时间

编辑 `state/status.yml` 和 `.github/workflows/daily-promo.yml` 的 cron：

```yaml
# 北京时间 08:00 = UTC 00:00
- cron: '0 0 * * *'
```

### 改关键词库

编辑 `config/regions.yml`，在对应 region 下加 districts / landmarks / transit。

### 加新银行/卡

编辑 `config/cards.yml` 和 `config/sources.yml`。

## 📈 调优建议

运行 7 天后，根据命中率调整：

- **噪音多**（推送很多用不上的）：收窄 `regions.yml` 关键词
- **漏报**（错过重要活动）：扩展 `sources.yml` 加新源
- **OCR 不准**：手动把截图放大清晰后再上传

## 📜 许可证

MIT