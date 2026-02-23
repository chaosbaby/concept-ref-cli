"""日期转换工具模块"""

import datetime
import time
import re
from typing import Optional


def convert_date_to_timestamp(date_str: str) -> str:
    """
    将日期字符串转换为 Unix 时间戳。
    支持的格式: 
      - YYYY-MM-DD (2026-01-01)
      - YYYYMMDD (20260101)
      - YYYY- (2026-) -> 自动补全为 YYYY-01-01
      - YYYY (2026) -> 自动补全为 YYYY-01-01
    如果输入不是日期格式，原样返回。
    """
    if not isinstance(date_str, str):
        return date_str
    
    date_str = date_str.strip()
    
    # 处理 YYYY- 格式 (如 2026-)
    if re.match(r'^\d{4}-$', date_str):
        # 补全为 YYYY-01-01
        date_str = f"{date_str}01-01"
    
    # 处理 YYYY 格式 (如 2026)
    elif re.match(r'^\d{4}$', date_str):
        # 补全为 YYYY-01-01
        date_str = f"{date_str}-01-01"
    
    # 处理 YYYY-MM 格式 (如 2026-01)
    elif re.match(r'^\d{4}-\d{2}$', date_str):
        # 补全为 YYYY-MM-01
        date_str = f"{date_str}-01"
    
    # 严格匹配：必须是纯日期格式
    date_patterns = [
        (r'^\d{4}-\d{2}-\d{2}$', '%Y-%m-%d'),  # 2026-01-01
        (r'^\d{4}\d{2}\d{2}$', '%Y%m%d'),      # 20260101
    ]
    
    for pattern, fmt in date_patterns:
        if re.match(pattern, date_str):
            try:
                dt = datetime.datetime.strptime(date_str, fmt)
                # 设置为当天 00:00:00
                timestamp = int(time.mktime(dt.timetuple()))
                return str(timestamp)
            except ValueError:
                # 解析失败，返回原值
                pass
    
    # 不是日期格式，原样返回
    return date_str


def is_date_string(value: str) -> bool:
    """检查字符串是否为日期格式"""
    date_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',  # 2026-01-01
        r'^\d{4}\d{2}\d{2}$',    # 20260101
        r'^\d{4}-$',             # 2026-
        r'^\d{4}$',              # 2026
        r'^\d{4}-\d{2}$',        # 2026-01
    ]
    return any(re.match(pattern, value) for pattern in date_patterns)
