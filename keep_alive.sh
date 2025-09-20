#!/bin/bash

# 保持 GitHub Actions 活跃的脚本
# 每周自动提交一个无关紧要的修改

# 设置工作目录
cd /Users/maqic/tools/deploy-certificate-to-aliyun

# 获取当前时间
current_time=$(date '+%Y-%m-%d %H:%M:%S')

# 在 README.md 文件末尾添加时间戳（如果不存在的话）
if ! grep -q "最后更新" README.md; then
    echo "" >> README.md
    echo "---" >> README.md
    echo "最后更新: $current_time" >> README.md
else
    # 如果存在，则更新时间戳
    sed -i '' "s/最后更新:.*/最后更新: $current_time/" README.md
fi

# 添加所有更改到 git
git add README.md

# 提交更改
git commit -m "chore: 更新最后修改时间 - $current_time"

# 推送到远程仓库
git push origin main

echo "✅ 成功提交并推送更改，时间: $current_time"
