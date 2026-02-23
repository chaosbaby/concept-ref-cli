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
        parts = filter_str.split(':', 3)
        if len(parts) < 4:
            return None
        
        table, column, op, value = parts
        
        if not schema_manager.table_exists(table):
            return None
        if not schema_manager.column_exists(table, column):
            return None
            
        simple_type = schema_manager.get_simple_type(table, column)
        from ..utils.constants import FIELD_TYPES
        if op not in FIELD_TYPES.get(simple_type, {}).get('operators', []):
            return None

        return Filter(
            table=table, 
            column=column, 
            op=op, 
            value=value, 
            raw=filter_str, 
            column_type=simple_type
        )
    
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
