"""
query_db.py - 通用的 SQLite 查询命令工厂模块

可以创建针对不同数据库的查询命令。
"""

from __future__ import annotations

import click
import sqlite3
import os
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional, Callable, Set
from pathlib import Path
from click.shell_completion import CompletionItem
import re

# --- Constants ---

FIELD_TYPES = {
    'string': {
        'operators': ['is', 'contains', 'startswith', 'endswith', 'regex', 'length_is', 'length_gt', 'length_lt', 'in'],
        'value_type': 'string'
    },
    'integer': {
        'operators': ['is', 'gt', 'gte', 'lt', 'lte', 'between', 'in'],
        'value_type': 'number'
    },
    'datetime': {
        'operators': ['after', 'before', 'between', 'last', 'next', 'on'],
        'value_type': 'date'
    },
    'boolean': {
        'operators': ['is', 'is_not'],
        'value_type': 'boolean'
    }
}

# --- Data Classes ---

@dataclass
class Filter:
    """Represents a parsed filter condition."""
    table: str
    column: str
    op: str
    value: str
    raw: str
    column_type: str

@dataclass
class QueryConfig:
    """Configuration for a query."""
    filters: List[Filter] = field(default_factory=list)
    limit: int = 10
    offset: int = 0
    fields: List[str] = field(default_factory=list)
    sort_by: Optional[str] = None
    sort_dir: str = 'desc'
    logic: str = 'AND'
    where_raw: Optional[str] = None

# --- Schema Management ---

class SchemaManager:
    """Inspects and caches the DB schema for a specific database."""
    
    def __init__(self, db_path: str, table_prefix: str = ""):
        self.db_path = os.path.expanduser(db_path)
        self.table_prefix = table_prefix
        self.schema: Dict[str, Dict[str, str]] = {}
        self.physical_tables: Dict[str, str] = {}
        self._load_schema()

    def _load_schema(self):
        """Load schema from the database."""
        if not os.path.exists(self.db_path):
            return
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            for physical_name in tables:
                if physical_name.startswith(self.table_prefix):
                    clean_name = physical_name[len(self.table_prefix):]
                else:
                    clean_name = physical_name
                
                self.physical_tables[clean_name] = physical_name
                self.schema[clean_name] = {}
                
                cursor.execute(f"PRAGMA table_info({physical_name})")
                for col in cursor.fetchall():
                    col_name, col_type = col[1], col[2]
                    self.schema[clean_name][col_name] = col_type
                    
        except sqlite3.Error as e:
            raise RuntimeError(f"Error loading schema from {self.db_path}: {e}")
        finally:
            if conn:
                conn.close()

    def get_simple_type(self, table: str, column: str) -> Optional[str]:
        """Maps SQLite type to a simple type from FIELD_TYPES."""
        if table not in self.schema:
            return None
        if column not in self.schema[table]:
            return None
            
        sql_type = self.schema[table][column].upper()
        if 'INT' in sql_type:
            return 'integer'
        if 'TEXT' in sql_type or 'CHAR' in sql_type or not sql_type:
            return 'string'
        if 'BOOL' in sql_type:
            return 'boolean'
        if 'DATE' in sql_type or 'TIME' in sql_type:
            return 'datetime'
        if 'REAL' in sql_type or 'FLOA' in sql_type or 'DOUB' in sql_type:
            return 'integer'
        return 'string'

    def get_tables(self) -> List[str]:
        return list(self.schema.keys())

    def get_columns(self, table: str) -> List[str]:
        return list(self.schema.get(table, {}).keys())
    
    def get_physical_table_name(self, table: str) -> str:
        return self.physical_tables.get(table, table)
    
    def table_exists(self, table: str) -> bool:
        return table in self.schema
    
    def column_exists(self, table: str, column: str) -> bool:
        return table in self.schema and column in self.schema[table]

# --- Filter Parsing ---

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

# --- Query Building ---
import datetime
import time
import re
from typing import Tuple, List, Any, Optional

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


class QueryBuilder:
    """Builds type-safe SQL queries from validated filters."""
    
    @staticmethod
    def _get_op_sql(filt: Filter) -> Tuple[str, List[Any]]:
        col, op, val = filt.column, filt.op, filt.value
        
        def cast_if_numeric(column_name: str, target_type: str = "REAL") -> str:
            return f"CAST({column_name} AS {target_type})"

        # 处理日期转换 - 只对纯日期格式进行转换
        def process_value(value: str, column_type: str) -> str:
            """根据列类型处理值"""
            if column_type in ['integer', 'real']:
                # 数字类型：检查是否是纯日期格式
                # 如果包含小数点，说明是时间戳，不转换
                if '.' in value:
                    return value
                # 尝试转换日期格式
                converted = convert_date_to_timestamp(value)
                return converted
            return value

        if op == 'is': 
            processed_val = process_value(val, filt.column_type)
            # 对于数字类型，确保转换为合适的类型
            if filt.column_type in ['integer', 'real']:
                try:
                    num_val = float(processed_val)
                    return (f"{cast_if_numeric(col)} = ?", [num_val])
                except ValueError:
                    # 如果转换失败，使用原始字符串
                    return (f"{col} = ?", [processed_val])
            return (f"{col} = ?", [processed_val])
        
        if op == 'in':
            vals = val.split(',')
            processed_vals = [process_value(v, filt.column_type) for v in vals]
            
            if filt.column_type in ['integer', 'real']:
                try:
                    casted_vals = []
                    for v in processed_vals:
                        try:
                            casted_vals.append(float(v))
                        except ValueError:
                            # 如果某个值转换失败，使用原始字符串
                            casted_vals.append(v)
                    return (f"{cast_if_numeric(col)} IN ({','.join('?' for _ in casted_vals)})", casted_vals)
                except Exception:
                    return (f"{col} IN ({','.join('?' for _ in processed_vals)})", processed_vals)
            return (f"{col} IN ({','.join('?' for _ in processed_vals)})", processed_vals)

        if filt.column_type in ['integer', 'real']:
            if op in ['gt', 'gte', 'lt', 'lte']:
                processed_val = process_value(val, filt.column_type)
                try:
                    num_val = float(processed_val)
                    op_map = {
                        'gt': '>', 'gte': '>=', 
                        'lt': '<', 'lte': '<='
                    }
                    return (f"{cast_if_numeric(col)} {op_map[op]} ?", [num_val])
                except ValueError:
                    # 如果转换失败，返回错误信息
                    raise ValueError(f"Invalid numeric value for '{op}' operator: {val} (converted: {processed_val})")
            
            if op == 'between':
                v_start, v_end = val.split(',', 1)
                processed_start = process_value(v_start, filt.column_type)
                processed_end = process_value(v_end, filt.column_type)
                try:
                    return (f"{cast_if_numeric(col)} BETWEEN ? AND ?", [float(processed_start), float(processed_end)])
                except ValueError:
                    raise ValueError(f"Invalid numeric values for 'between' operator: {v_start}, {v_end}")

        # 其他类型的处理保持不变...
        if filt.column_type == 'string':
            if op == 'contains': 
                return (f"{col} LIKE ?", [f"%{val}%"])
            if op == 'startswith': 
                return (f"{col} LIKE ?", [f"{val}%"])
            if op == 'endswith': 
                return (f"{col} LIKE ?", [f"%{val}"])
            if op == 'regex': 
                return (f"{col} REGEXP ?", [val])
            if op == 'length_is': 
                return (f"LENGTH({col}) = ?", [int(val)])
            if op == 'length_gt': 
                return (f"LENGTH({col}) > ?", [int(val)])
            if op == 'length_lt': 
                return (f"LENGTH({col}) < ?", [int(val)])

        if filt.column_type == 'boolean':
            bool_val = 1 if str(val).lower() in ['true', '1', 'yes', 'y', 't'] else 0
            if op == 'is':
                return (f"{col} = ?", [bool_val])
            if op == 'is_not':
                return (f"{col} != ?", [bool_val])
        
        if filt.column_type == 'datetime':
            if op == 'after':
                return (f"{col} > ?", [val])
            if op == 'before':
                return (f"{col} < ?", [val])
            if op == 'on':
                return (f"DATE({col}) = DATE(?)", [val])
            
        raise NotImplementedError(f"Operator '{op}' not implemented for type '{filt.column_type}'")

    @staticmethod
    def build_sql(config: QueryConfig, schema_manager: SchemaManager) -> Tuple[Optional[str], List[Any], Optional[str]]:
        filters = config.filters
        
        if not filters and not config.where_raw:
            return None, [], None

        # Determine target table
        target_table = None
        if filters:
            target_table = filters[0].table
            for f in filters:
                if f.table != target_table:
                    click.secho(f"错误: 查询跨越多表 {f.table} 和 {target_table}", fg='red')
                    return None, [], None
        elif config.where_raw:
            tables = schema_manager.get_tables()
            if tables:
                target_table = tables[0]

        if not target_table:
            click.secho("错误: 无法确定目标表", fg='red')
            return None, [], None

        db_table_name = schema_manager.get_physical_table_name(target_table)

        # Build WHERE clause
        where_clauses = []
        params = []

        if filters:
            for f in filters:
                try:
                    clause, p = QueryBuilder._get_op_sql(f)
                    where_clauses.append(clause)
                    params.extend(p)
                except Exception as e:
                    click.secho(f"错误: 处理过滤器 {f.raw} 时出错: {e}", fg='red')
                    return None, [], None

        if config.where_raw:
            where_clauses.append(f"({config.where_raw})")

        if config.fields:
            valid_fields = []
            for field in config.fields:
                if field == '*' or schema_manager.column_exists(target_table, field):
                    valid_fields.append(field)
                else:
                    click.secho(f"警告: 字段 '{field}' 在表 {target_table} 中不存在，已忽略", fg='yellow')
            if valid_fields:
                select_clause = ", ".join(valid_fields)
            else:
                select_clause = "*"
        else:
            select_clause = "*"

        sql = f"SELECT {select_clause} FROM {db_table_name}"
        
        if where_clauses:
            logic = f" {config.logic} ".join(where_clauses)
            sql += f" WHERE {logic}"
        
        if config.sort_by:
            if schema_manager.column_exists(target_table, config.sort_by):
                sql += f" ORDER BY {config.sort_by} {config.sort_dir.upper()}"
            else:
                click.secho(f"警告: 排序字段 '{config.sort_by}' 不存在，已忽略", fg='yellow')
        
        sql += f" LIMIT ?"
        params.append(config.limit)
        
        if config.offset > 0:
            sql += f" OFFSET ?"
            params.append(config.offset)

        return sql, params, db_table_name


# --- Output Formatting ---

class OutputFormatter:
    """Handles different output formats."""
    
    @staticmethod
    def format_results(results: List[sqlite3.Row], 
                      output_mode: str,
                      fields: List[str] = None) -> str:
        """Format results according to output mode."""
        if not results:
            return ""
        
        if output_mode == 'json':
            # Single JSON array
            return json.dumps([dict(row) for row in results], 
                            ensure_ascii=False, indent=2)
        
        elif output_mode == 'ndjson':
            # Newline-delimited JSON
            lines = []
            for row in results:
                lines.append(json.dumps(dict(row), ensure_ascii=False))
            return '\n'.join(lines)
        
        elif output_mode == 'plain':
            # Plain text (one field per line)
            if fields:
                # Show only specified fields
                lines = []
                for row in results:
                    for field in fields:
                        if field in row.keys():
                            lines.append(str(row[field]))
                return '\n'.join(lines)
            else:
                # Show all fields
                lines = []
                for row in results:
                    lines.append(' '.join(str(v) for v in row))
                return '\n'.join(lines)
        
        elif output_mode == 'show':
            # Pretty table format
            if not results:
                return ""
            
            headers = results[0].keys()
            
            # If fields specified, filter headers
            if fields:
                headers = [h for h in headers if h in fields]
            
            # Calculate column widths
            col_widths = {h: len(h) for h in headers}
            rows_data = []
            
            for row in results:
                row_dict = dict(row)
                rows_data.append(row_dict)
                for h in headers:
                    val = str(row_dict.get(h, ''))
                    col_widths[h] = max(col_widths[h], len(val))
            
            # Build table
            lines = []
            
            # Header
            header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
            lines.append(header_line)
            lines.append('-' * len(header_line))
            
            # Rows
            for row_dict in rows_data:
                row_line = ' | '.join(
                    str(row_dict.get(h, '')).ljust(col_widths[h]) 
                    for h in headers
                )
                lines.append(row_line)
            
            return '\n'.join(lines)
        
        return ""

# --- 命令工厂函数 ---

def create_table_commands(db_path: str, 
                         tables: List[str],
                         table_prefix: str = "", 
                         help_text: str = None) -> List[click.Command]:
    """
    为每个表创建一个独立的查询命令。
    
    参数:
        db_path: 数据库文件路径
        tables: 要创建命令的表名列表
        table_prefix: 表名前缀
        help_text: 帮助文本（会被每个命令继承）
    
    返回:
        命令对象列表
    """
    full_db_path = os.path.expanduser(db_path)
    
    # 创建 SchemaManager 实例
    schema_manager = SchemaManager(full_db_path, table_prefix)
    
    # 验证表是否存在
    available_tables = schema_manager.get_tables()
    commands = []
    
    for table in tables:
        if table not in available_tables:
            click.secho(f"警告: 表 '{table}' 在数据库 {db_path} 中不存在", fg='yellow')
            continue
        
        # 为每个表创建独立的命令
        cmd = _create_single_table_command(
            db_path=full_db_path,
            table_name=table,
            schema_manager=schema_manager,
            help_text=f"{help_text or '查询'} - {table} 表"
        )
        commands.append(cmd)
    
    return commands


def _create_single_table_command(db_path: str, 
                                table_name: str,
                                schema_manager: SchemaManager,
                                help_text: str = None) -> click.Command:
    """
    创建一个针对单个表的查询命令。
    
    参数:
        db_path: 数据库文件路径
        table_name: 表名
        schema_manager: SchemaManager 实例
        help_text: 帮助文本
    """
    # 生成帮助文本
    if help_text is None:
        help_text = f"""
查询 {table_name} 表。

过滤器格式: column:op:value

示例:
  {table_name} term:contains:爱情
  {table_name} freq:gt:100 --limit 5 --sort-by freq --sort-dir desc

特殊功能 - 从标准输入读取过滤器值:
  使用 '-' 作为过滤器值的一部分，可以从标准输入读取实际值。
  每行输入会生成一个独立的查询。

  示例:
    # 为每个词条执行查询
    echo -e "爱情\n友谊\n人生" | {table_name} term:is:-

    # 组合多个过滤器
    echo -e "爱情,100\n友谊,50" | {table_name} term:is:- freq:is:-

操作符说明:
  字符串: is, contains, startswith, endswith, regex, length_is, length_gt, length_lt, in
  数字: is, gt, gte, lt, lte, between, in
  日期: after, before, between, last, next, on
  布尔: is, is_not
"""
    
    # 创建补全函数
    def sort_by_completer(ctx, param, incomplete):
        """补全排序字段"""
        return [
            CompletionItem(col) 
            for col in schema_manager.get_columns(table_name)
            if col.startswith(incomplete)
        ]
    
    def filter_completer(ctx, param, incomplete):
        """补全过滤器"""
        parts = incomplete.split(':', 2)
        num_parts = len(parts)
        
        current_column = parts[0] if num_parts > 0 else ""
        current_op = parts[1] if num_parts > 1 else ""
        
        if num_parts == 1:
            # 补全列名
            return [
                CompletionItem(f"{c}:") 
                for c in schema_manager.get_columns(table_name) 
                if c.startswith(current_column)
            ]
        
        elif num_parts == 2:
            # 补全操作符
            if schema_manager.column_exists(table_name, current_column):
                simple_type = schema_manager.get_simple_type(table_name, current_column)
                if simple_type in FIELD_TYPES:
                    return [
                        CompletionItem(f"{current_column}:{op}:") 
                        for op in FIELD_TYPES[simple_type]['operators'] 
                        if op.startswith(current_op)
                    ]
        
        return []
    
    @click.command(name=table_name, help=help_text, epilog="提示: 在过滤器值中使用 '-' 可以从标准输入读取实际值")
    @click.argument('filters', nargs=-1, required=False, shell_complete=filter_completer)
    @click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), 
                 default='show', help='输出模式：表格/纯文本/JSON/NDJSON')
    @click.option('--field', '-f', multiple=True, help='选择要输出的字段（可多次使用）', shell_complete=sort_by_completer)
    @click.option('--limit', type=int, default=10, help='最大返回结果数')
    @click.option('--offset', type=int, default=0, help='结果偏移量（用于分页）')
    @click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', 
                 help='组合过滤器的逻辑（AND/OR）')
    @click.option('--sort-by', help='排序字段', shell_complete=sort_by_completer)
    @click.option('--sort-dir', type=click.Choice(['asc', 'desc']), default='desc', 
                 help='排序方向')
    @click.option('--where', help='原始SQL WHERE子句（谨慎使用）')
    @click.option('--verbose', '-v', is_flag=True, help='显示SQL语句')
    @click.option('--list-fields', '-l', is_flag=True, help='列出表的字段')
    @click.option('--count', is_flag=True, help='只返回结果数量')
    @click.option('--delimiter', '-d', default=None, help='当一行有多个值时使用的分隔符（默认：逗号）')
    @click.option('--quiet', '-q', is_flag=True, help='安静模式，不显示额外信息')
    @click.option('--separator', '-s', default=None, help='多行输出时的分隔符（默认：空行）')
    def cmd(filters, output, field, limit, offset, logic, sort_by, sort_dir, 
            where, verbose, list_fields, count, delimiter, quiet, separator):
        """执行表查询"""
        
        # 检查数据库是否存在
        if not os.path.exists(db_path):
            click.secho(f"错误: 数据库文件不存在 - {db_path}", fg='red')
            return
        
        # 列出字段
        if list_fields:
            columns = schema_manager.get_columns(table_name)
            if not columns:
                click.secho(f"表 {table_name} 中没有字段。", fg='yellow')
                return
            
            click.secho(f"\n表 {table_name} 的字段:", fg='green', bold=True)
            for col in sorted(columns):
                col_type = schema_manager.get_simple_type(table_name, col)
                click.echo(f"  {col} ({col_type})")
            return
        
        # 检查是否有过滤器
        if not filters and not where:
            click.secho("错误: 需要提供过滤器或 --where 参数", fg='red')
            return
        
        # 解析过滤器模板
        filter_templates = []
        stdin_positions = []  # 记录哪些位置需要从stdin读取值
        
        for i, filter_str in enumerate(filters):
            # 格式是 column:op:value
            parts = filter_str.split(':', 2)
            if len(parts) < 3:
                click.secho(f"无效的过滤器格式: {filter_str} (应为 column:op:value)", fg='red')
                return
            column, op, value = parts
            
            # 验证列是否存在
            if not schema_manager.column_exists(table_name, column):
                click.secho(f"列不存在: {table_name}.{column}", fg='red')
                return
            
            # 检查值是否为 stdin 占位符
            if value == '-':
                stdin_positions.append((i, filter_str, column, op))
            else:
                # 验证操作符是否有效
                simple_type = schema_manager.get_simple_type(table_name, column)
                if op not in FIELD_TYPES.get(simple_type, {}).get('operators', []):
                    click.secho(f"无效的操作符 '{op}' 对于类型 '{simple_type}'", fg='red')
                    return
                filter_templates.append((i, filter_str, column, op, value))
        
        # 如果没有需要从stdin读取的值，直接执行单次查询
        if not stdin_positions:
            parsed_filters = []
            for _, filter_str, column, op, value in filter_templates:
                # 构建完整的过滤器字符串（用于解析）
                full_filter = f"{table_name}:{column}:{op}:{value}"
                filt = FilterParser.parse(full_filter, schema_manager)
                if filt:
                    parsed_filters.append(filt)
            
            if not parsed_filters and not where:
                return
            
            config = QueryConfig(
                filters=parsed_filters,
                limit=limit,
                offset=offset,
                fields=list(field),
                sort_by=sort_by,
                sort_dir=sort_dir,
                logic=logic,
                where_raw=where
            )
            
            _execute_table_query(schema_manager, config, verbose, output, count, db_path, quiet=quiet)
            return
        
        # 需要从stdin读取值
        if sys.stdin.isatty():
            click.secho("错误: 过滤器值使用了 '-' 但没有数据从管道传入", fg='red')
            return
        
        # 读取标准输入的所有行
        stdin_lines = [line.rstrip('\n') for line in sys.stdin if line.strip()]
        
        if not stdin_lines:
            click.secho("警告: 标准输入为空", fg='yellow')
            return
        
        if not quiet:
            click.secho(f"从标准输入读取了 {len(stdin_lines)} 行", fg='blue', dim=True)
        
        # 确定分隔符
        sep = delimiter if delimiter else ','
        
        # 为每一行执行查询
        total_results = 0
        all_results = []
        first_output = True
        
        for line_num, line in enumerate(stdin_lines, 1):
            # 如果一行有多个值，按分隔符拆分
            values = line.split(sep) if sep in line else [line]
            values = [v.strip() for v in values]
            
            # 检查值的数量是否与 stdin 位置匹配
            if len(values) != len(stdin_positions):
                if not quiet:
                    click.secho(f"警告: 第 {line_num} 行有 {len(values)} 个值，但需要 {len(stdin_positions)} 个值", 
                              fg='yellow')
                if len(values) < len(stdin_positions):
                    continue
            
            # 构建这一行的过滤器
            line_filters = []
            
            # 添加固定值的过滤器
            for _, filter_str, column, op, value in filter_templates:
                full_filter = f"{table_name}:{column}:{op}:{value}"
                filt = FilterParser.parse(full_filter, schema_manager)
                if filt:
                    line_filters.append(filt)
            
            # 添加从stdin读取值的过滤器
            for idx, (pos_idx, filter_str, column, op) in enumerate(stdin_positions):
                value = values[idx] if idx < len(values) else values[-1]
                # 构建完整的过滤器字符串
                full_filter = f"{table_name}:{column}:{op}:{value}"
                filt = FilterParser.parse(full_filter, schema_manager)
                if filt:
                    line_filters.append(filt)
            
            if not line_filters:
                continue
            
            config = QueryConfig(
                filters=line_filters,
                limit=limit,
                offset=offset,
                fields=list(field),
                sort_by=sort_by,
                sort_dir=sort_dir,
                logic=logic,
                where_raw=where
            )
            
            # 执行查询
            if output == 'ndjson':
                # NDJSON 模式：收集所有结果
                results = _execute_table_query(schema_manager, config, verbose, output, count, db_path, 
                                              return_results=True, quiet=quiet)
                if results:
                    total_results += len(results)
                    all_results.extend(results)
            else:
                # 其他模式：直接输出，每行结果之间添加分隔符
                if not first_output and separator is not None:
                    # 添加用户指定的分隔符
                    click.echo(separator)
                elif not first_output and output == 'show':
                    # 默认添加空行作为分隔符
                    click.echo()
                
                # 显示行信息（如果不是安静模式）
                if not quiet and len(stdin_lines) > 1:
                    click.secho(f"--- 行 {line_num}: {line} ---", fg='cyan', bold=True)
                
                # 执行查询并直接输出
                _execute_table_query(schema_manager, config, verbose, output, count, db_path, 
                                   return_results=False, quiet=quiet, line_info=(line_num, line))
                
                first_output = False
        
        # 输出所有结果（针对 NDJSON 模式）
        if output == 'ndjson' and all_results:
            for result in all_results:
                click.echo(json.dumps(result, ensure_ascii=False))
        
        # 显示总数（如果不是安静模式）
        if not quiet and total_results > 0:
            click.secho(f"\n总共找到 {total_results} 条结果", fg='green', dim=True)
    
    return cmd


def _execute_table_query(sm, config, verbose, output, count, db_path, 
                        return_results=False, quiet=False, line_info=None):
    """执行单个表查询并返回结果"""
    sql, params, table_name = QueryBuilder.build_sql(config, sm)
    
    if not sql:
        if not return_results:
            click.secho("无法构建SQL查询。", fg='red')
        return None if return_results else None
    
    if verbose and not quiet:
        click.secho(f"SQL: {sql}", fg='blue', dim=True)
        click.secho(f"参数: {params}", fg='blue', dim=True)
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if count:
            count_sql = re.sub(r'SELECT\s+.*?\s+FROM', 'SELECT COUNT(*) as count FROM', sql, count=1)
            cursor.execute(count_sql, params)
            result = cursor.fetchone()
            if return_results:
                return [{'count': result['count']}]
            if not quiet:
                click.echo(result['count'])
            return None
        
        cursor.execute(sql, params)
        results = cursor.fetchall()
        
        if return_results:
            return [dict(row) for row in results]
        
        if not results:
            if not quiet:
                click.secho("没有找到结果。", fg='yellow')
            return None
        
        # 直接输出结果
        if output == 'json':
            # JSON 数组格式
            click.echo(json.dumps([dict(row) for row in results], ensure_ascii=False, indent=2))
        elif output == 'ndjson':
            # NDJSON 格式（每行一个 JSON）
            for row in results:
                click.echo(json.dumps(dict(row), ensure_ascii=False))
        elif output == 'plain':
            # 纯文本格式
            if config.fields:
                # 只输出指定字段
                for row in results:
                    row_dict = dict(row)
                    values = [str(row_dict.get(f, '')) for f in config.fields]
                    click.echo(' '.join(values))
            else:
                # 输出所有字段
                for row in results:
                    click.echo(' '.join(str(v) for v in row))
        else:  # show 模式
            # 表格格式
            if results:
                headers = results[0].keys()
                
                # 如果指定了字段，过滤 headers
                if config.fields:
                    headers = [h for h in headers if h in config.fields]
                
                # 计算列宽
                col_widths = {h: len(h) for h in headers}
                rows_data = []
                
                for row in results:
                    row_dict = dict(row)
                    rows_data.append(row_dict)
                    for h in headers:
                        val = str(row_dict.get(h, ''))
                        col_widths[h] = max(col_widths[h], len(val))
                
                # 打印表头
                header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
                click.echo(header_line)
                click.echo('-' * len(header_line))
                
                # 打印行
                for row_dict in rows_data:
                    row_line = ' | '.join(str(row_dict.get(h, '')).ljust(col_widths[h]) for h in headers)
                    click.echo(row_line)
        
        if not quiet:
            click.secho(f"找到 {len(results)} 条结果", fg='green', dim=True)
        
        return None
        
    except sqlite3.Error as e:
        if not return_results:
            click.secho(f"数据库错误: {e}", fg='red')
            if verbose:
                click.secho(f"SQL: {sql}", fg='red', dim=True)
                click.secho(f"参数: {params}", fg='red', dim=True)
        return None if return_results else None
    finally:
        if conn:
            conn.close()


# 保留原有的 create_query_cmd 函数以便向后兼容
def create_query_cmd(db_path: str, 
                     table_prefix: str = "", 
                     cmd_name: str = None,
                     help_text: str = None) -> click.Command:
    """原有的查询命令创建函数，保持向后兼容"""
    schema_manager = SchemaManager(db_path, table_prefix)
    tables = schema_manager.get_tables()
    
    if not tables:
        @click.command(name=cmd_name, help=help_text or "查询数据库")
        def error_cmd():
            click.secho(f"错误: 数据库 {db_path} 中没有表", fg='red')
        return error_cmd
    
    # 默认使用第一个表
    return _create_single_table_command(
        db_path=db_path,
        table_name=tables[0],
        schema_manager=schema_manager,
        help_text=help_text
    )

# 便捷函数：创建多个数据库命令
def create_commands_from_config(config: Dict[str, Dict[str, str]]) -> List[click.Command]:
    """
    从配置字典创建多个命令。
    
    示例配置:
    {
        'lexicon': {
            'db_path': '~/.lexicon.db',
            'table_prefix': 'source_',
            'help': '查询词典数据库'
        },
        'users': {
            'db_path': '/path/to/users.db',
            'table_prefix': '',
            'help': '查询用户数据库'
        }
    }
    """
    commands = []
    for cmd_name, cmd_config in config.items():
        cmd = create_query_cmd(
            db_path=cmd_config['db_path'],
            table_prefix=cmd_config.get('table_prefix', ''),
            cmd_name=cmd_name,
            help_text=cmd_config.get('help')
        )
        commands.append(cmd)
    return commands
