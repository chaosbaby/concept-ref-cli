"""命令行接口模块 - 提供命令创建工厂函数"""

from __future__ import annotations

import os
import click
from typing import Dict, List, Optional

from .core.schema import SchemaManager
from .commands.table_command import create_table_command, _execute_table_query
from .core.filters import FilterParser
from .core.builder import QueryConfig, QueryBuilder


def create_table_commands(db_path: str, 
                         tables: List[str],
                         table_prefix: str = "", 
                         help_text: str = None,
                         cache_values: bool = False) -> List[click.Command]:
    """
    为每个表创建一个独立的查询命令。
    
    参数:
        db_path: 数据库文件路径
        tables: 要创建命令的表名列表
        table_prefix: 表名前缀
        help_text: 帮助文本（会被每个命令继承）
        cache_values: 是否缓存字段值以提高补全性能
    
    返回:
        命令对象列表
    """
    full_db_path = os.path.expanduser(db_path)
    
    # 创建 SchemaManager 实例，传入 cache_values 参数
    schema_manager = SchemaManager(full_db_path, table_prefix, cache_values=cache_values)
    
    # 验证表是否存在
    available_tables = schema_manager.get_tables()
    commands = []
    
    for table in tables:
        if table not in available_tables:
            click.secho(f"警告: 表 '{table}' 在数据库 {db_path} 中不存在", fg='yellow')
            continue
        
        # 为每个表创建独立的命令
        cmd = create_table_command(
            db_path=full_db_path,
            table_name=table,
            schema_manager=schema_manager,
            help_text=f"{help_text or '查询'} - {table} 表"
        )
        commands.append(cmd)
    
    return commands

def create_query_cmd(db_path: str, 
                     table_prefix: str = "", 
                     cmd_name: str = None,
                     help_text: str = None) -> click.Command:
    """
    原有的查询命令创建函数，保持向后兼容
    
    参数:
        db_path: 数据库文件路径
        table_prefix: 表名前缀
        cmd_name: 命令名称
        help_text: 帮助文本
    
    返回:
        命令对象
    """
    full_db_path = os.path.expanduser(db_path)
    schema_manager = SchemaManager(full_db_path, table_prefix)
    tables = schema_manager.get_tables()
    
    if not tables:
        @click.command(name=cmd_name, help=help_text or "查询数据库")
        def error_cmd():
            click.secho(f"错误: 数据库 {db_path} 中没有表", fg='red')
        return error_cmd
    
    # 默认使用第一个表
    from .commands.table_command import create_table_command
    return create_table_command(
        db_path=full_db_path,
        table_name=tables[0],
        schema_manager=schema_manager,
        help_text=help_text
    )


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
    
    参数:
        config: 配置字典，键为命令名，值为包含 'db_path'、'table_prefix'、'help' 的字典
    
    返回:
        命令对象列表
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


def create_multi_table_command(db_path: str,
                              tables: List[str],
                              cmd_name: str = "query",
                              table_prefix: str = "",
                              help_text: str = None) -> click.Command:
    """
    创建一个可以查询多个表的命令（通过 --table 参数指定）
    
    参数:
        db_path: 数据库文件路径
        tables: 允许查询的表名列表
        cmd_name: 命令名称
        table_prefix: 表名前缀
        help_text: 帮助文本
    
    返回:
        命令对象
    """
    full_db_path = os.path.expanduser(db_path)
    schema_manager = SchemaManager(full_db_path, table_prefix)
    
    # 验证表是否存在
    available_tables = schema_manager.get_tables()
    valid_tables = [t for t in tables if t in available_tables]
    
    if not valid_tables:
        @click.command(name=cmd_name, help=help_text or "查询数据库")
        def error_cmd():
            click.secho(f"错误: 数据库 {db_path} 中没有可用的表", fg='red')
        return error_cmd
    
    @click.command(name=cmd_name, help=help_text or "查询数据库")
    @click.option('--table', '-t', 
                 type=click.Choice(valid_tables), 
                 required=True,
                 help='要查询的表名')
    @click.argument('filters', nargs=-1, required=False)
    @click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), 
                 default='show', help='输出模式')
    @click.option('--field', '-f', multiple=True, help='选择要输出的字段')
    @click.option('--limit', type=int, default=10, help='最大返回结果数')
    @click.option('--offset', type=int, default=0, help='结果偏移量')
    @click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', 
                 help='组合过滤器的逻辑')
    @click.option('--sort-by', help='排序字段')
    @click.option('--sort-dir', type=click.Choice(['asc', 'desc']), default='desc', 
                 help='排序方向')
    @click.option('--where', help='原始SQL WHERE子句')
    @click.option('--verbose', '-v', is_flag=True, help='显示SQL语句')
    @click.option('--list-fields', '-l', is_flag=True, help='列出表的字段')
    @click.option('--count', is_flag=True, help='只返回结果数量')
    @click.option('--quiet', '-q', is_flag=True, help='安静模式')
    def multi_cmd(table, filters, output, field, limit, offset, logic, sort_by, 
                 sort_dir, where, verbose, list_fields, count, quiet):
        """多表查询命令"""
        
        if not os.path.exists(full_db_path):
            click.secho(f"错误: 数据库文件不存在 - {full_db_path}", fg='red')
            return
        
        # 列出字段
        if list_fields:
            columns = schema_manager.get_columns(table)
            if not columns:
                click.secho(f"表 {table} 中没有字段。", fg='yellow')
                return
            
            click.secho(f"\n表 {table} 的字段:", fg='green', bold=True)
            for col in sorted(columns):
                col_type = schema_manager.get_simple_type(table, col)
                click.echo(f"  {col} ({col_type})")
            return
        
        # 解析过滤器
        parsed_filters = []
        for filter_str in filters:
            parts = filter_str.split(':', 2)
            if len(parts) < 3:
                click.secho(f"无效的过滤器格式: {filter_str}", fg='red')
                return
            column, op, value = parts
            
            full_filter = f"{table}:{column}:{op}:{value}"
            filt = FilterParser.parse(full_filter, schema_manager)
            if filt:
                parsed_filters.append(filt)
        
        if not parsed_filters and not where:
            click.secho("错误: 需要提供过滤器或 --where 参数", fg='red')
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
        
        # 使用 table_command 模块中的执行函数
        from .commands.table_command import _execute_table_query
        _execute_table_query(schema_manager, config, verbose, output, count, 
                           full_db_path, return_results=False, quiet=quiet)
    
    return multi_cmd


# 便捷函数：快速创建单个表的命令
def quick_command(db_path: str, 
                 table: str,
                 cmd_name: str = None,
                 table_prefix: str = "",
                 help_text: str = None) -> click.Command:
    """
    快速创建单个表的查询命令
    
    参数:
        db_path: 数据库文件路径
        table: 表名
        cmd_name: 命令名称（默认使用表名）
        table_prefix: 表名前缀
        help_text: 帮助文本
    
    返回:
        命令对象
    """
    commands = create_table_commands(
        db_path=db_path,
        tables=[table],
        table_prefix=table_prefix,
        help_text=help_text
    )
    
    if commands:
        cmd = commands[0]
        if cmd_name and cmd_name != table:
            # 重命名命令
            cmd.name = cmd_name
        return cmd
    
    # 如果表不存在，返回错误命令
    @click.command(name=cmd_name or table, help=help_text or f"查询 {table} 表")
    def error_cmd():
        click.secho(f"错误: 表 '{table}' 在数据库 {db_path} 中不存在", fg='red')
    
    return error_cmd
