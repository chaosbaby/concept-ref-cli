"""过滤器解析模块"""

from dataclasses import dataclass
from typing import List, Optional

from .schema import SchemaManager

@dataclass
class Filter:
    """Represents a parsed filter condition."""
    table: str
    column: str
    op: str
    value: str
    raw: str
    column_type: str


class FilterParser:
    """Parses and validates filter strings against a schema."""

    @staticmethod
    def parse(filter_str: str, schema_manager: SchemaManager) -> Optional[Filter]:
        
        # 支持两种格式:
        # 1. table:column:op:value (普通，4部分)
        # 2. table:column:not:op:value (带 not 前缀，5部分)
        parts = filter_str.split(':')
        
        if len(parts) == 4:
            # 格式: table:column:op:value
            table, column, op, value = parts
            
        elif len(parts) == 5:
            # 格式: table:column:not:op:value
            table, column, not_prefix, op, value = parts
            # 检查第三部分是否为 'not'
            if not_prefix == 'not':
                op = f"not:{op}"  # 重新组合成带前缀的操作符
            else:
                return None
        else:
            return None
        
        if not schema_manager.table_exists(table):
            return None
        if not schema_manager.column_exists(table, column):
            return None
            
        simple_type = schema_manager.get_simple_type(table, column)
        
        from ..utils.constants import FIELD_TYPES
        valid_ops = FIELD_TYPES.get(simple_type, {}).get('operators', [])
        
        if op not in valid_ops:
            return None

        filt = Filter(
            table=table, 
            column=column, 
            op=op, 
            value=value, 
            raw=filter_str, 
            column_type=simple_type
        )
        return filt

    @staticmethod
    def parse_from_stdin(stdin_data: str, schema_manager: SchemaManager) -> List[Filter]:
        """Parse filters from stdin (one filter per line)."""
        filters = []
        for line in stdin_data.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):  # Skip comments
                filt = FilterParser.parse(line, schema_manager)
                if filt:
                    filters.append(filt)
        return filters
