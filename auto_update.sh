#!/bin/bash
# 每日新闻数据一键更新 + 发布（供 WorkBuddy 定时任务调用）
# 抓取新闻联播与公安部要闻 → 同步到站点 → 重新发布 → 验证
set -u
BASE=/workspace/xwlb-wechat-push
SITE=/workspace/release-site
SITE_SCRIPTS=/root/.codebuddy/skills/sites/scripts
LOG=$BASE/auto_update.log
UA="Mozilla/5.0"

echo "===== $(date '+%F %T %Z') 每日更新开始 =====" | tee -a "$LOG"

# 1) 抓取并更新数据（含公安部，可能耗时数分钟）
cd "$BASE" || exit 1
python3.11 daily_bundle.py 2>&1 | tee -a "$LOG"

# 2) 重新发布站点
echo "--- 重新发布站点 ---" | tee -a "$LOG"
cd "$SITE_SCRIPTS" || exit 1
PUB=$(node publish.js --dir "$SITE" --language static 2>&1)
echo "$PUB" | tee -a "$LOG"

# 3) 验证公网最新日期
echo "--- 验证公网数据 ---" | tee -a "$LOG"
sleep 2
LATEST=$(curl -sS -m 20 -A "$UA" "https://a52fea9258524190f.app.workbuddy.host/data/latest.json?sharecode=H5W4NT5AIL" \
  | python3.11 -c "import sys,json; d=json.load(sys.stdin); print(d.get('date'), d.get('count'))" 2>/dev/null)
echo "公网最新: $LATEST" | tee -a "$LOG"
echo "===== $(date '+%F %T %Z') 每日更新结束 =====" | tee -a "$LOG"
