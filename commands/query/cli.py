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
                     tables: List[str] = None,
                     cmd_name: str = "query",
                     help_text: str = None,
                     cache_values: bool = False) -> click.Group:
    """
    创建一个查询命令组，每个表作为子命令
    
    参数:
        db_path: 数据库文件路径
        table_prefix: 表名前缀
        tables: 要创建子命令的表名列表，如果为None或空列表则使用所有实体表
        cmd_name: 命令组名称
        help_text: 命令组帮助文本
        cache_values: 是否缓存字段值以提高补全性能
    
    返回:
        click.Group 命令组对象
    """
    full_db_path = os.path.expanduser(db_path)
    schema_manager = SchemaManager(full_db_path, table_prefix, cache_values=cache_values)
    
    # 获取所有可用的表
    available_tables = schema_manager.get_tables()
    
    if not available_tables:
        @click.group(name=cmd_name, help=help_text or f"查询数据库 {db_path}")
        def error_group():
            """错误提示组"""
            pass
        
        @error_group.command(name="list")
        def list_cmd():
            """列出可用表"""
            click.secho(f"错误: 数据库 {db_path} 中没有表", fg='red')
        
        return error_group
    
    # 确定要创建命令的表列表
    target_tables = []
    if tables:
        # 使用指定的表，检查是否存在
        for table in tables:
            if table in available_tables:
                target_tables.append(table)
            else:
                click.secho(f"警告: 表 '{table}' 在数据库 {db_path} 中不存在，已忽略", fg='yellow')
    else:
        # 使用所有实体表（排除系统表）
        target_tables = [t for t in available_tables if not t.startswith('sqlite_')]
    
    if not target_tables:
        # 如果没有有效的表，返回带错误提示的组
        @click.group(name=cmd_name, help=help_text or f"查询数据库 {db_path}")
        def empty_group():
            """空命令组"""
            pass
        
        @empty_group.command(name="list")
        def list_cmd():
            """列出可用表"""
            if tables:
                click.secho(f"错误: 指定的表都不存在于数据库 {db_path} 中", fg='red')
            else:
                click.secho(f"错误: 数据库 {db_path} 中没有可用的实体表", fg='red')
        
        return empty_group
    
    # 创建命令组
    @click.group(name=cmd_name, help=help_text or f"查询数据库 {db_path} 中的表")
    @click.pass_context
    def query_group(ctx):
        """数据库查询命令组"""
        # 可以在这里添加全局配置
        ctx.ensure_object(dict)
        ctx.obj['db_path'] = full_db_path
        ctx.obj['table_prefix'] = table_prefix
        ctx.obj['schema_manager'] = schema_manager
    
    # 为每个表创建子命令
    from .commands.table_command import create_table_command
    
    for table in target_tables:
        # 创建表的查询命令
        table_cmd = create_table_command(
            db_path=full_db_path,
            table_name=table,
            schema_manager=schema_manager,
            help_text=f"查询 {table} 表"
        )
        
        # 将命令添加到组中
        query_group.add_command(table_cmd, name=table)
    
    # 添加一个额外的命令来列出所有可用表
    @query_group.command(name="list")
    def list_tables():
        """列出所有可用的表"""
        click.secho(f"\n数据库: {db_path}", fg='cyan', bold=True)
        click.secho(f"表名前缀: '{table_prefix}'\n", fg='cyan')
        
        click.secho("可用的表:", fg='green', bold=True)
        for i, table in enumerate(available_tables, 1):
            if table in target_tables:
                click.secho(f"  {i:2d}. {table} (可用)", fg='white')
            else:
                click.secho(f"  {i:2d}. {table} (系统表)", fg='bright_black')
    
    return query_group

# def create_query_cmd(db_path: str, 
#                      table_prefix: str = "", 
#                      cmd_name: str = None,
#                      help_text: str = None) -> click.Command:
#     """
#     原有的查询命令创建函数，保持向后兼容
#
#     参数:
#         db_path: 数据库文件路径
#         table_prefix: 表名前缀
#         cmd_name: 命令名称
#         help_text: 帮助文本
#
#     返回:
#         命令对象
#     """
#     full_db_path = os.path.expanduser(db_path)
#     schema_manager = SchemaManager(full_db_path, table_prefix)
#     tables = schema_manager.get_tables()
#
#     if not tables:
#         @click.command(name=cmd_name, help=help_text or "查询数据库")
#         def error_cmd():
#             click.secho(f"错误: 数据库 {db_path} 中没有表", fg='red')
#         return error_cmd
#
#     # 默认使用第一个表
#     from .commands.table_command import create_table_command
#     return create_table_command(
#         db_path=full_db_path,
#         table_name=tables[0],
#         schema_manager=schema_manager,
#         help_text=help_text
#     )



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
