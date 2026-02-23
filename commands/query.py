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

class QueryBuilder:
    """Builds type-safe SQL queries from validated filters."""
    
    @staticmethod
    def _get_op_sql(filt: Filter) -> Tuple[str, List[Any]]:
        col, op, val = filt.column, filt.op, filt.value
        
        def cast_if_numeric(column_name: str, target_type: str = "REAL") -> str:
            return f"CAST({column_name} AS {target_type})"

        if op == 'is': 
            return (f"{col} = ?", [val])
        
        if op == 'in':
            vals = val.split(',')
            if filt.column_type == 'integer':
                try:
                    casted_vals = [float(v) for v in vals]
                    return (f"{cast_if_numeric(col)} IN ({','.join('?' for _ in casted_vals)})", casted_vals)
                except ValueError:
                    raise ValueError(f"Invalid numeric value for 'in' operator: {val}")
            return (f"{col} IN ({','.join('?' for _ in vals)})", vals)

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

        if filt.column_type == 'integer':
            if op == 'gt':
                return (f"{cast_if_numeric(col)} > ?", [float(val)])
            if op == 'gte':
                return (f"{cast_if_numeric(col)} >= ?", [float(val)])
            if op == 'lt':
                return (f"{cast_if_numeric(col)} < ?", [float(val)])
            if op == 'lte':
                return (f"{cast_if_numeric(col)} <= ?", [float(val)])
            if op == 'between':
                v_start, v_end = val.split(',', 1)
                return (f"{cast_if_numeric(col)} BETWEEN ? AND ?", [float(v_start), float(v_end)])
        
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
                    return None, [], None
        elif config.where_raw:
            # Try to extract table from WHERE clause (simplified)
            # In a real implementation, you might need to specify table explicitly
            tables = schema_manager.get_tables()
            if tables:
                target_table = tables[0]  # Default to first table

        if not target_table:
            return None, [], None

        db_table_name = schema_manager.get_physical_table_name(target_table)

        # Build WHERE clause
        where_clauses = []
        params = []

        # Add filters
        if filters:
            for f in filters:
                try:
                    clause, p = QueryBuilder._get_op_sql(f)
                    where_clauses.append(clause)
                    params.extend(p)
                except Exception:
                    return None, [], None

        # Add raw WHERE clause
        if config.where_raw:
            where_clauses.append(f"({config.where_raw})")

        # Build SELECT clause
        if config.fields:
            # Validate fields
            valid_fields = []
            for field in config.fields:
                if field == '*' or schema_manager.column_exists(target_table, field):
                    valid_fields.append(field)
                else:
                    raise ValueError(f"Invalid field: {field}")
            select_clause = ", ".join(valid_fields)
        else:
            select_clause = "*"

        # Build SQL
        sql = f"SELECT {select_clause} FROM {db_table_name}"
        
        if where_clauses:
            logic = f" {config.logic} ".join(where_clauses)
            sql += f" WHERE {logic}"
        
        # Add ORDER BY
        if config.sort_by:
            if schema_manager.column_exists(target_table, config.sort_by):
                sql += f" ORDER BY {config.sort_by} {config.sort_dir.upper()}"
        
        # Add LIMIT and OFFSET
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

def create_query_cmd(db_path: str, 
                     table_prefix: str = "", 
                     cmd_name: str = None,
                     help_text: str = None) -> click.Command:
    """
    创建一个针对特定数据库的查询命令。
    
    Args:
        db_path: SQLite数据库文件路径
        table_prefix: 表名前缀（将被移除）
        cmd_name: 命令名称（如果为None，则从数据库文件名生成）
        help_text: 命令帮助文本
    
    Returns:
        click.Command 对象，可以直接添加到 CLI
    """
    
    # 生成命令名称
    if cmd_name is None:
        base_name = os.path.basename(db_path)
        cmd_name = os.path.splitext(base_name)[0].replace('-', '_').lower()
    
    # 生成帮助文本
    if help_text is None:
        help_text = f"""
查询 {os.path.basename(db_path)} 数据库。

过滤器格式: table:column:op:value

示例:
  {cmd_name} users:age:gt:25
  {cmd_name} users:name:contains:john --limit 5 --sort-by age --sort-dir desc

操作符说明:
  字符串: is, contains, startswith, endswith, regex, length_is, length_gt, length_lt, in
  数字: is, gt, gte, lt, lte, between, in
  日期: after, before, between, last, next, on
  布尔: is, is_not

选项:
  可以从 stdin 读取过滤器列表（每行一个）
  支持多种输出格式：表格、JSON、NDJSON、纯文本
  可以指定返回字段和排序方式
"""
    
    # 创建 SchemaManager 实例（用于补全）
    schema_manager = SchemaManager(db_path, table_prefix)
    
    # 创建排序字段补全函数
    def sort_by_completer(ctx, param, incomplete):
        if schema_manager.get_tables():
            # 默认使用第一个表的列
            first_table = schema_manager.get_tables()[0]
            return [
                CompletionItem(col) 
                for col in schema_manager.get_columns(first_table)
                if col.startswith(incomplete)
            ]
        return []
    
    # 创建过滤器补全函数
    def filter_completer(ctx, param, incomplete):
        parts = incomplete.split(':', 3)
        num_parts = len(parts)
        
        current_table = parts[0] if num_parts > 0 else ""
        current_column = parts[1] if num_parts > 1 else ""
        current_op = parts[2] if num_parts > 2 else ""
        
        if num_parts == 1:
            # 补全表名
            return [
                CompletionItem(f"{t}:") 
                for t in schema_manager.get_tables() 
                if t.startswith(current_table)
            ]
        
        elif num_parts == 2:
            # 补全列名
            if schema_manager.table_exists(current_table):
                return [
                    CompletionItem(f"{current_table}:{c}:") 
                    for c in schema_manager.get_columns(current_table) 
                    if c.startswith(current_column)
                ]
        
        elif num_parts == 3:
            # 补全操作符
            if (schema_manager.table_exists(current_table) and 
                schema_manager.column_exists(current_table, current_column)):
                simple_type = schema_manager.get_simple_type(current_table, current_column)
                if simple_type in FIELD_TYPES:
                    return [
                        CompletionItem(f"{current_table}:{current_column}:{op}:") 
                        for op in FIELD_TYPES[simple_type]['operators'] 
                        if op.startswith(current_op)
                    ]
        
        return []
    
    @click.command(name=cmd_name, help=help_text, epilog="提示: 使用 --stdin 可以从文件或管道读取多个过滤器")
    @click.argument('filters', nargs=-1, required=False, shell_complete=filter_completer)
    @click.option('--stdin', is_flag=True, help='从标准输入读取查询过滤器（每行一个）')
    @click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), 
                 default='show', help='输出模式：表格/纯文本/JSON/NDJSON')
    @click.option('--field', '-f', multiple=True, help='选择要输出的字段（可多次使用）')
    @click.option('--limit', type=int, default=10, help='最大返回结果数')
    @click.option('--offset', type=int, default=0, help='结果偏移量（用于分页）')
    @click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', 
                 help='组合过滤器的逻辑（AND/OR）')
    @click.option('--sort-by', help='排序字段', shell_complete=sort_by_completer)
    @click.option('--sort-dir', type=click.Choice(['asc', 'desc']), default='desc', 
                 help='排序方向')
    @click.option('--where', help='原始SQL WHERE子句（谨慎使用）')
    @click.option('--verbose', '-v', is_flag=True, help='显示SQL语句')
    @click.option('--list-tables', '-t', is_flag=True, help='列出所有表及其结构')
    @click.option('--count', is_flag=True, help='只返回结果数量')
    def cmd(filters, stdin, output, field, limit, offset, logic, sort_by, sort_dir, 
            where, verbose, list_tables, count):
        """执行查询命令"""
        
        # 检查数据库是否存在
        full_db_path = os.path.expanduser(db_path)
        if not os.path.exists(full_db_path):
            click.secho(f"错误: 数据库文件不存在 - {full_db_path}", fg='red')
            return
        
        # 创建 SchemaManager（实时加载，确保数据最新）
        sm = SchemaManager(full_db_path, table_prefix)
        
        # 列出表模式
        if list_tables:
            tables = sm.get_tables()
            if not tables:
                click.secho("数据库中没有表。", fg='yellow')
                return
            
            click.secho("\n可用的表:", fg='green', bold=True)
            for table in sorted(tables):
                columns = sm.get_columns(table)
                click.echo(f"  {table}:")
                for col in sorted(columns)[:8]:  # 显示前8列
                    col_type = sm.get_simple_type(table, col)
                    click.echo(f"    - {col} ({col_type})")
                if len(columns) > 8:
                    click.echo(f"    ... 还有 {len(columns)-8} 列")
            return
        
        # 解析过滤器
        parsed_filters = []
        
        # 从命令行参数解析
        if filters:
            for filter_str in filters:
                filt = FilterParser.parse(filter_str, sm)
                if filt:
                    parsed_filters.append(filt)
                else:
                    click.secho(f"无效的过滤器: {filter_str}", fg='red')
                    # 显示有效表名
                    if ':' in filter_str:
                        table = filter_str.split(':', 1)[0]
                        if table and not sm.table_exists(table):
                            click.secho(f"  表 '{table}' 不存在。有效表: {', '.join(sm.get_tables())}", fg='yellow')
                    return
        
        # 从stdin解析
        if stdin:
            if not sys.stdin.isatty():
                stdin_data = sys.stdin.read()
                stdin_filters = FilterParser.parse_from_stdin(stdin_data, sm)
                parsed_filters.extend(stdin_filters)
                click.secho(f"从 stdin 读取了 {len(stdin_filters)} 个过滤器", fg='blue', dim=True)
            else:
                click.secho("警告: --stdin 被指定但没有数据从管道传入", fg='yellow')
        
        if not parsed_filters and not where:
            click.secho("错误: 需要提供过滤器或 --where 参数", fg='red')
            return
        
        # 创建查询配置
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
        
        # 构建SQL
        sql, params, table_name = QueryBuilder.build_sql(config, sm)
        
        if not sql:
            click.secho("无法构建SQL查询。", fg='red')
            return
        
        # 显示SQL（如果verbose）
        if verbose:
            click.secho(f"SQL: {sql}", fg='blue', dim=True)
            click.secho(f"参数: {params}", fg='blue', dim=True)
        
        # 执行查询
        conn = None
        try:
            conn = sqlite3.connect(full_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if count:
                # 修改SQL为COUNT查询
                count_sql = re.sub(r'SELECT\s+.*?\s+FROM', 'SELECT COUNT(*) as count FROM', sql, count=1)
                cursor.execute(count_sql, params)
                result = cursor.fetchone()
                click.echo(result['count'])
                return
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            if not results:
                click.secho("没有找到结果。", fg='yellow')
                return
            
            # 格式化输出
            output_text = OutputFormatter.format_results(results, output, list(field))
            if output_text:
                click.echo(output_text)
            
            if output != 'ndjson':  # ndjson 已经是一行一条
                click.secho(f"\n找到 {len(results)} 条结果", fg='green', dim=True)
            
        except sqlite3.Error as e:
            click.secho(f"数据库错误: {e}", fg='red')
            if verbose:
                click.secho(f"SQL: {sql}", fg='red', dim=True)
                click.secho(f"参数: {params}", fg='red', dim=True)
        finally:
            if conn:
                conn.close()
    
    return cmd


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
