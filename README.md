# 📺 新闻联播文字稿 · 微信推送 + 历史数据库

每天晚上 8 点（北京时间）自动抓取央视网当天《新闻联播》的文字稿，整理成文本后通过 **PushPlus** 推送到你的微信；同时维护一份 **2012 年至今的历史数据库**（约 5.4 万期、8 万条），供配套安卓 App 下载到本地、离线浏览与搜索。全程运行在 **GitHub Actions** 云端，无需自己的电脑或服务器。

## 🌐 数据源（全年代官方接口）

央视官方文字稿按年代分布在不同域名，本项目的 `cctv_fetcher.py` 自动按日期选择：

| 年代 | 官方接口 | 编码 |
|---|---|---|
| 2009-06 ~ 2010-05 | `news.cctv.com/program/xwlb/` | GBK |
| 2010-05 ~ 2011-04 | `news.cntv.cn/program/xwlb/` | GBK |
| 2011-04 ~ 2016-02 | `cctv.cntv.cn/lm/xinwenlianbo/` | GBK |
| 2016-02 至今 | `tv.cctv.com/lm/xwlb/day/` | UTF-8 |

2016 年前部分详情页已下线，`archive_fetcher.py` 会读取央视官方文字稿的历史存档快照补齐；极少数正文永久丢失的条目会标注"正文已失效，仅存标题"，不造假。

## 🗄️ 历史数据库脚本

```bash
# 全量补齐 2012 至今，按年份打包到 docs/data/years/
python build_history.py --out docs/data --from 2012 --workers 8

# 补抓某几年缺失日期（低并发 + 存档兜底）
python repair_missing.py 2016 2021 2022

# 日常更新：抓当天并合并进当年数据包（GitHub Actions 每天调用）
python update_daily.py

# 公安部新闻动态：抓公安要闻栏目最新条目（Playwright 过反爬）
pip install playwright && python -m playwright install chromium
python mps_fetcher.py --pages 1 --out docs/mps/latest.json
```

产物：`docs/data/years/YYYY.json`（每年一个包）、`docs/data/index.json`（索引）、`docs/data/latest.json`（最新一天）。安卓 App 首次启动下载全部年份包存入本地 SQLite。

## ✨ 特性

- ⏰ **定时推送**：每天 20:00（北京时间）自动运行，打开微信即可阅读
- 📰 **全文文字稿**：抓取当天所有单条新闻的完整正文（非标题摘要），自动去除 `[视频]` 标记
- 🛡️ **稳定可靠**：请求失败自动重试 + 多线程并发抓取；当天文字稿未发布时自动回退最近有数据的一天
- ✂️ **智能分段**：内容过长时自动拆成多条推送，避免微信消息被截断
- 🔧 **零成本**：GitHub Actions 免费额度 + PushPlus 免费额度（每天 200 条），个人使用完全够
- 🧪 **可测试**：支持 `--dry-run` 本地预览、`workflow_dispatch` 云端手动触发

## 🏗️ 工作原理

```
央视网新闻联播列表页  →  解析当天各条新闻链接
        ↓
并发抓取每条详情页正文（#content_area）
        ↓
整理为 Markdown 文本（过长则分段）
        ↓
调用 PushPlus API  →  微信公众号推送到你的微信
```

整个流程由 GitHub Actions 每天定时触发，token 通过 Secrets 加密保存，不会泄露。

## 📱 App 每天更新的运作机制

App 本身**不做抓取**，它只负责展示本地 SQLite 数据库。更新分两条线：

| 环节 | 在哪里 | 做什么 | 触发时机 |
|---|---|---|---|
| ① 云端抓取 | GitHub Actions | `update_daily.py` 抓当天新闻联播 + `mps_fetcher.py` 抓公安部要闻，写入 `docs/` 数据包并 `git commit/push` | 每天 UTC 12:00（北京时间 20:00） |
| ② App 同步 | 手机本地 | 启动时 `SyncTask` 从数据源下载各年份包入库；公安部数据从 `mps/latest.json` 拉取 | 每次打开 App（增量）/ 首次安装（全量） |
| ③ 数据源 | GitHub raw 主源 + 临时站点备源 | App 优先读 `Simbav5/xwlb-wechat-push`，失败自动回退临时站点 | —— |

**关键点**：
- 新闻浏览/搜索**完全离线**（读本地 SQLite），只有同步时才联网。
- 首次安装下载 2012 至今全部数据包（约 117MB）入库，之后每天只增量更新当年数据 + 公安部 10 条。
- 云端 `git push` 成功后，App 下次打开即可拿到最新数据；若某天云端失败，App 显示已有缓存，不会空白。

## 🚓 公安部新闻动态数据源

公安部官网（mps.gov.cn）全站启用了**加速乐 `__jsl_clearance_s` JS cookie 反爬**，普通 HTTP 请求只会拿到 521 挑战页。因此 `mps_fetcher.py` 用 **Playwright 无头浏览器**自动执行 JS 通过校验，再解析「公安要闻」栏目：

- 列表页：`https://www.mps.gov.cn/n2253534/n2253535/index.html`
- 正文提取：`.bTitle p`（标题）、`.banner .time`（日期/来源）、`.wordContent`（正文）
- 过滤无日期的干扰项（如办事指南），只保留有日期的要闻
- 产物：`docs/mps/latest.json`，App 首页「🚓 公安部新闻动态」入口读取此文件

> 该源为**增量快照**（近期约 10 条），非全历史；每天随 GitHub Actions 一起刷新。若公安部改版导致选择器失效，只需调整 `mps_fetcher.py` 的三处 CSS 选择器。

## 🚀 部署步骤（约 5 分钟）

### 第 1 步：获取 PushPlus token

1. 打开 [www.pushplus.plus](https://www.pushplus.plus)，用微信扫码登录
2. 在首页复制你的 **token**（一串 32 位字符）
3. 关注 PushPlus 的微信公众号（否则收不到消息）

> 免费用户每天 200 条额度，本项目每天仅用 1~3 条，完全够用。

### 第 2 步： Fork 本仓库

1. 点击仓库右上角的 **Fork**，把项目 fork 到你自己的 GitHub 账号
2. Fork 完成后，进入你自己仓库的 **Settings → Actions → General**
3. 找到 **Workflow permissions**，选择 **Read and write permissions**（保证 Actions 有权限运行）

### 第 3 步：配置 Secret

1. 在你自己的仓库中，进入 **Settings → Secrets and variables → Actions**
2. 点击 **New repository secret**
3. 名称填写 `PUSHPLUS_TOKEN`，Value 粘贴第 1 步获取的 token，点击 **Add secret**

### 第 4 步：启用并测试

1. 进入仓库的 **Actions** 标签页，左侧点击 **每日新闻联播推送**
2. 如果是第一次进入，点击 **Enable workflow** 启用它
3. 点击右侧 **Run workflow** 手动运行一次：
   - 日期留空 = 推送当天内容
   - 也可填入历史日期（如 `20251117`）测试
4. 运行完成后（约 30 秒~1 分钟），检查微信是否收到推送

✅ 看到微信收到消息，就部署完成了！之后每天 20:00 会自动推送，无需任何操作。

## ⚙️ 配置说明

所有配置均为可选项，通过 GitHub 仓库的 **Variables**（Settings → Secrets and variables → Actions → Variables 标签）添加：

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `PUSH_MAX_CHARS` | `12000` | 单条推送最大字符数，超出自动分段。微信单条过长会被截断，一般不用改 |
| `PUSH_TEMPLATE` | `markdown` | 推送模板：`markdown`（推荐，排版美观）或 `txt`（纯文本） |
| `CCTV_FALLBACK` | `1` | 当天文字稿未发布时是否回退最近有数据的一天。`1` 开启 / `0` 关闭 |

必填的 Secret 只有一个：`PUSHPLUS_TOKEN`。

### ⏰ 修改推送时间

编辑 `.github/workflows/daily.yml` 中的 cron：

```yaml
on:
  schedule:
    - cron: "0 12 * * *"   # UTC 时间；北京时间 = UTC + 8
```

`0 12 * * *` = UTC 12:00 = 北京时间 20:00。例如想改成早上 8 点推送（北京时间），UTC 是 0 点，改为 `0 0 * * *`。

> ⚠️ 注意：GitHub Actions 的定时任务在高峰期可能延迟几分钟到半小时，这是 GitHub 官方已知的限速行为，无法完全避免。若对时间精度要求极高，可考虑改用云服务器 cron。

## 💻 本地运行（可选）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 复制配置模板并填入 token
cp .env.example .env
#   编辑 .env，填入 PUSHPLUS_TOKEN

# 3. 加载环境变量后运行
set -a && source .env && set +a
python main.py

# 只预览不推送（强烈建议首次使用先跑这个）
python main.py --dry-run

# 指定日期测试
python main.py --date 20251117 --dry-run

# 其他参数
python main.py --workers 5      # 并发线程数
python main.py --no-fallback    # 不回退历史日期
```

## 📁 文件结构

```
xwlb-wechat-push/
├── main.py                      # 核心脚本：抓取 / 整理 / 微信推送
├── generate_json.py             # 数据服务：抓取并生成 JSON（供 App 读取）
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── .gitignore
├── .github/
│   └── workflows/
│       └── daily.yml            # 定时配置：每天生成 JSON + 微信推送
├── docs/                        # GitHub Pages 站点根目录（App 数据源）
│   ├── index.json               # 日期索引
│   ├── latest.json              # 最新一天数据
│   └── data/YYYYMMDD.json       # 每日数据
└── README.md                    # 本文档
```

## ❓ 常见问题

**Q：没有收到推送？**
- 确认已关注 PushPlus 微信公众号
- 在 Actions 页面查看运行日志，确认是否成功（绿色 ✓）
- 检查 `PUSHPLUS_TOKEN` Secret 是否填写正确

**Q：推送的文字是空的或只有标题？**
- 央视网文字稿通常在 19:00 后陆续更新，20:00 一般已齐全；若偶尔某条无正文，脚本会自动跳过该条，不影响其他内容

**Q：GitHub Actions 多久没运行会停？**
- GitHub 会在仓库 **60 天无任何活动** 后自动暂停定时任务。本项目每天推送会产生活动记录，一般不会触发；如长期未用后恢复，去 Actions 页面手动 Run 一次即可重新激活

**Q：可以推送给多人吗？**
- 当前推送给自己。如需多人，可升级 PushPlus 群组功能（新建 topic 并在 payload 中加 `topic` 字段）

## 📱 搭配安卓 App 使用

本项目同时为安卓 App 提供数据源。每天定时任务除了微信推送，还会运行 `generate_json.py`，把最近 7 天的数据生成到 `docs/` 目录并提交回仓库。

**开启数据源（让 App 联网同步）：**

1. 进入你的仓库 **Settings → Pages**
2. **Build and deployment → Source** 选择 **Deploy from a branch**
3. 分支选 `main`，目录选 **`/docs`**，保存
4. 等待几分钟后，访问 `https://你的用户名.github.io/xwlb-wechat-push/` 能打开即成功

**在 App 里接入：**

打开安卓 App，**长按顶部红色标题栏**，填入以下任一地址（以 `/` 结尾）：

```
https://raw.githubusercontent.com/你的用户名/xwlb-wechat-push/main/docs/
```

或

```
https://你的用户名.github.io/xwlb-wechat-push/
```

保存后，App 即会优先读取云端最新数据；断网时自动回退到内置示例数据。

> 详见安卓 App 项目：`../news-app/README.md`

## 📄 数据来源与免责声明

文字稿来源于 [央视网《新闻联播》](https://tv.cctv.com/lm/xwlb/)，版权归原作者所有。本项目仅做个人阅读用途的自动化整理与推送，请勿用于商业用途。

---

Made with 🤖 · 每天 20:00 准时送到微信
