#!/bin/bash

# 保持 GitHub Actions 活跃的脚本（Mac 本地定时任务）
# 每周自动提交一个无关紧要的修改；运行前会检查配置是否正确

set -e

# 使用脚本所在目录为仓库根目录（便于在任意位置克隆仓库）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ---------- 配置检查 ----------
check_config() {
  local ok=1

  if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "❌ 配置错误: 当前目录不是 Git 仓库 ($REPO_ROOT)"
    return 1
  fi

  if ! git remote get-url origin &>/dev/null; then
    echo "❌ 配置错误: 未配置 remote origin"
    return 1
  fi

  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [[ "$branch" != "main" ]]; then
    echo "❌ 配置错误: 当前分支是 '$branch'，请切换到 main"
    return 1
  fi

  if [[ ! -f "README.md" ]]; then
    echo "❌ 配置错误: README.md 不存在"
    return 1
  fi

  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    echo "⚠️  提示: 工作区或暂存区有未提交更改，将只提交 README 时间戳"
  fi

  echo "✅ 配置检查通过 (仓库: $REPO_ROOT, 分支: main)"
  return 0
}

if ! check_config; then
  echo "请修正上述配置后重试。"
  exit 1
fi

# ---------- 更新 README 时间戳并提交 ----------
current_time=$(date '+%Y-%m-%d %H:%M:%S')

if ! grep -q "最后更新" README.md; then
  echo "" >> README.md
  echo "---" >> README.md
  echo "最后更新: $current_time" >> README.md
else
  sed -i '' "s/最后更新:.*/最后更新: $current_time/" README.md
fi

git add README.md

if git diff --staged --quiet; then
  echo "✅ 无变更，跳过提交 (时间: $current_time)"
  exit 0
fi

git commit -m "chore: 更新最后修改时间 - $current_time"
git push origin main

echo "✅ 成功提交并推送，时间: $current_time"
