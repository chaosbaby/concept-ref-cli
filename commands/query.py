"""
query_db.py - 通用的 SQLite 查询命令工厂模块

可以创建针对不同数据库的查询命令。
"""

from __future__ import annotations

import click
import sqlite3
import os
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional, Callable
from pathlib import Path
from click.shell_completion import CompletionItem

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
    def build_sql(filters: List[Filter], schema_manager: SchemaManager) -> Tuple[Optional[str], List[Any], Optional[str]]:
        if not filters:
            return None, [], None

        target_table = filters[0].table
        for f in filters:
            if f.table != target_table:
                return None, [], None

        db_table_name = schema_manager.get_physical_table_name(target_table)

        where_clauses = []
        params = []

        for f in filters:
            try:
                clause, p = QueryBuilder._get_op_sql(f)
                where_clauses.append(clause)
                params.extend(p)
            except Exception:
                return None, [], None

        if not where_clauses:
            return None, [], None

        sql = f"SELECT * FROM {db_table_name} WHERE {' AND '.join(where_clauses)}"
        return sql, params, db_table_name

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
        # 从数据库文件名生成命令名
        base_name = os.path.basename(db_path)
        cmd_name = os.path.splitext(base_name)[0].replace('-', '_').lower()
    
    # 生成帮助文本
    if help_text is None:
        help_text = f"查询 {os.path.basename(db_path)} 数据库。\n\n格式: table:column:op:value"
    
    # 创建 SchemaManager 实例（用于补全）
    schema_manager = SchemaManager(db_path, table_prefix)
    
    # 创建补全函数
    def create_completer(sm: SchemaManager):
        def completer(ctx, param, incomplete):
            parts = incomplete.split(':', 3)
            num_parts = len(parts)
            
            current_table = parts[0] if num_parts > 0 else ""
            current_column = parts[1] if num_parts > 1 else ""
            current_op = parts[2] if num_parts > 2 else ""
            
            if num_parts == 1:
                # 补全表名
                return [
                    CompletionItem(f"{t}:") 
                    for t in sm.get_tables() 
                    if t.startswith(current_table)
                ]
            
            elif num_parts == 2:
                # 补全列名
                if sm.table_exists(current_table):
                    return [
                        CompletionItem(f"{current_table}:{c}:") 
                        for c in sm.get_columns(current_table) 
                        if c.startswith(current_column)
                    ]
            
            elif num_parts == 3:
                # 补全操作符
                if sm.table_exists(current_table) and sm.column_exists(current_table, current_column):
                    simple_type = sm.get_simple_type(current_table, current_column)
                    if simple_type in FIELD_TYPES:
                        return [
                            CompletionItem(f"{current_table}:{current_column}:{op}:") 
                            for op in FIELD_TYPES[simple_type]['operators'] 
                            if op.startswith(current_op)
                        ]
            
            return []
        return completer
    
    @click.command(name=cmd_name, help=help_text)
    @click.argument('filters', nargs=-1, required=True, 
                   shell_complete=create_completer(schema_manager))
    @click.option('--limit', '-l', default=10, help="返回结果数量限制")
    @click.option('--output', '-o', type=click.Choice(['json', 'table', 'csv']), 
                 default='json', help="输出格式")
    @click.option('--verbose', '-v', is_flag=True, help="显示SQL语句")
    @click.option('--list-tables', '-t', is_flag=True, help="列出所有表")
    def cmd(filters, limit, output, verbose, list_tables):
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
        
        if not parsed_filters:
            click.secho("没有有效的过滤器。", fg='yellow')
            return
        
        # 构建SQL
        sql, params, table_name = QueryBuilder.build_sql(parsed_filters, sm)
        
        if not sql:
            click.secho("无法构建SQL查询。", fg='red')
            return
        
        # 添加LIMIT
        sql += f" LIMIT ?"
        params.append(limit)
        
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
            
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            if not results:
                click.secho("没有找到结果。", fg='yellow')
                return
            
            # 格式化输出
            if output == 'json':
                for row in results:
                    click.echo(json.dumps(dict(row), ensure_ascii=False))
            
            elif output == 'csv':
                if results:
                    # 输出CSV
                    headers = results[0].keys()
                    click.echo(','.join(headers))
                    for row in results:
                        click.echo(','.join(str(v) for v in row))
            
            elif output == 'table':
                if results:
                    headers = results[0].keys()
                    # 计算列宽
                    col_widths = {h: len(h) for h in headers}
                    rows_data = []
                    for row in results:
                        row_dict = dict(row)
                        rows_data.append(row_dict)
                        for h in headers:
                            val = str(row_dict[h])
                            col_widths[h] = max(col_widths[h], len(val))
                    
                    # 打印表头
                    header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
                    click.echo(header_line)
                    click.echo('-' * len(header_line))
                    
                    # 打印行
                    for row_dict in rows_data:
                        row_line = ' | '.join(str(row_dict[h]).ljust(col_widths[h]) for h in headers)
                        click.echo(row_line)
            
            click.secho(f"\n找到 {len(results)} 条结果", fg='green', dim=True)
            
        except sqlite3.Error as e:
            click.secho(f"数据库错误: {e}", fg='red')
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
