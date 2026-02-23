"""
query_db - 通用的 SQLite 查询命令工厂模块

可以创建针对不同数据库的查询命令。
"""

from __future__ import annotations

from .cli import (
    create_table_commands,
    create_query_cmd,
    create_commands_from_config,
    quick_command
)

__version__ = "1.0.0"
__all__ = [
    "create_table_commands",
    "create_query_cmd", 
    "create_commands_from_config",
    "quick_command"
]
