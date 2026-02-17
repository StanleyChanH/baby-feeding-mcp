#!/bin/bash
# 启动宝宝抚养记录 MCP Server 并连接到小智AI

cd "$(dirname "$0")"

# 加载 .env 文件中的环境变量
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 检查 MCP_ENDPOINT 是否设置
if [ -z "$MCP_ENDPOINT" ]; then
    echo "错误: 请在 .env 文件中设置 MCP_ENDPOINT"
    exit 1
fi

echo "启动 Baby Feeding MCP Server..."
echo "连接到: $MCP_ENDPOINT"
echo "按 Ctrl+C 停止"
echo ""

python mcp_pipe.py server.py
