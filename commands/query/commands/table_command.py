"""单个表的查询命令模块"""

import os
import sys
import json
import sqlite3
import re
from typing import List, Optional, Tuple, Any, Dict

import click
from click.shell_completion import CompletionItem

from ..core.schema import SchemaManager
from ..core.filters import FilterParser, Filter
from ..core.builder import QueryBuilder, QueryConfig
from ..core.formatter import OutputFormatter
from ..utils.constants import FIELD_TYPES


def create_table_command(db_path: str, 
                        table_name: str,
                        schema_manager: SchemaManager,
                        help_text: str = None) -> click.Command:
    """
    创建一个针对单个表的查询命令。
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


def _execute_table_query(sm: SchemaManager, 
                        config: QueryConfig, 
                        verbose: bool, 
                        output: str, 
                        count: bool, 
                        db_path: str, 
                        return_results: bool = False, 
                        quiet: bool = False, 
                        line_info: Optional[Tuple[int, str]] = None) -> Optional[List[Dict[str, Any]]]:
    """
    执行单个表查询并返回结果
    
    参数:
        sm: SchemaManager 实例
        config: 查询配置
        verbose: 是否显示SQL语句
        output: 输出模式
        count: 是否只返回计数
        db_path: 数据库路径
        return_results: 是否返回结果列表（而不是直接输出）
        quiet: 安静模式
        line_info: 行信息 (行号, 行内容)
    
    返回:
        如果 return_results 为 True，返回结果列表；否则返回 None
    """
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
            # 将 SELECT 替换为 COUNT(*)
            count_sql = re.sub(r'SELECT\s+.*?\s+FROM', 'SELECT COUNT(*) as count FROM', sql, count=1, flags=re.IGNORECASE)
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
                headers = list(results[0].keys())
                
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
