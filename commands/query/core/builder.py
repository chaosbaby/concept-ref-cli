"""SQL 查询构建模块"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any
import click

from .filters import Filter
from .schema import SchemaManager
from ..utils.date_converter import convert_date_to_timestamp


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


class QueryBuilder:
    """Builds type-safe SQL queries from validated filters."""
    @staticmethod
    def _get_op_sql(filt: Filter) -> Tuple[str, List[Any]]:
        col, op, val = filt.column, filt.op, filt.value
        
        # 检查是否是 NOT 操作符
        is_not = False
        actual_op = op
        
        if op.startswith('not:'):
            is_not = True
            actual_op = op[4:]  # 去掉 'not:' 前缀
        
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

        # 根据实际操作符生成 SQL
        if actual_op == 'is': 
            processed_val = process_value(val, filt.column_type)
            # 对于数字类型，确保转换为合适的类型
            if filt.column_type in ['integer', 'real']:
                try:
                    num_val = float(processed_val)
                    sql = f"{cast_if_numeric(col)} {'!=' if is_not else '='} ?"
                    return (sql, [num_val])
                except ValueError:
                    # 如果转换失败，使用原始字符串
                    sql = f"{col} {'!=' if is_not else '='} ?"
                    return (sql, [processed_val])
            sql = f"{col} {'!=' if is_not else '='} ?"
            return (sql, [processed_val])
        
        if actual_op == 'in':
            vals = val.split(',')
            processed_vals = [process_value(v, filt.column_type) for v in vals]
            
            if filt.column_type in ['integer', 'real']:
                try:
                    casted_vals = []
                    for v in processed_vals:
                        try:
                            casted_vals.append(float(v))
                        except ValueError:
                            casted_vals.append(v)
                    not_prefix = "NOT " if is_not else ""
                    return (f"{cast_if_numeric(col)} {not_prefix}IN ({','.join('?' for _ in casted_vals)})", casted_vals)
                except Exception:
                    not_prefix = "NOT " if is_not else ""
                    return (f"{col} {not_prefix}IN ({','.join('?' for _ in processed_vals)})", processed_vals)
            not_prefix = "NOT " if is_not else ""
            return (f"{col} {not_prefix}IN ({','.join('?' for _ in processed_vals)})", processed_vals)

        if filt.column_type in ['integer', 'real']:
            if actual_op in ['gt', 'gte', 'lt', 'lte']:
                processed_val = process_value(val, filt.column_type)
                try:
                    num_val = float(processed_val)
                    op_map = {
                        'gt': '>', 'gte': '>=', 
                        'lt': '<', 'lte': '<='
                    }
                    sql_op = op_map[actual_op]
                    if is_not:
                        # 对于比较操作符，NOT > 相当于 <=，等等
                        not_map = {
                            '>': '<=',
                            '>=': '<',
                            '<': '>=',
                            '<=': '>'
                        }
                        sql_op = not_map[sql_op]
                    return (f"{cast_if_numeric(col)} {sql_op} ?", [num_val])
                except ValueError:
                    # 如果转换失败，返回错误信息
                    raise ValueError(f"Invalid numeric value for '{op}' operator: {val} (converted: {processed_val})")
            
            if actual_op == 'between':
                v_start, v_end = val.split(',', 1)
                processed_start = process_value(v_start, filt.column_type)
                processed_end = process_value(v_end, filt.column_type)
                try:
                    if is_not:
                        # NOT BETWEEN 转换为 (col < ? OR col > ?)
                        return (f"({cast_if_numeric(col)} < ? OR {cast_if_numeric(col)} > ?)", 
                            [float(processed_start), float(processed_end)])
                    else:
                        return (f"{cast_if_numeric(col)} BETWEEN ? AND ?", 
                            [float(processed_start), float(processed_end)])
                except ValueError:
                    raise ValueError(f"Invalid numeric values for 'between' operator: {v_start}, {v_end}")

        # 字符串类型的处理 - 重点修复这里
        if filt.column_type == 'string':
            if actual_op == 'contains':
                if is_not:
                    # NOT LIKE 使用 NOT LIKE
                    return (f"{col} NOT LIKE ?", [f"%{val}%"])
                else:
                    return (f"{col} LIKE ?", [f"%{val}%"])
            
            if actual_op == 'startswith':
                if is_not:
                    return (f"{col} NOT LIKE ?", [f"{val}%"])
                else:
                    return (f"{col} LIKE ?", [f"{val}%"])
            
            if actual_op == 'endswith':
                if is_not:
                    return (f"{col} NOT LIKE ?", [f"%{val}"])
                else:
                    return (f"{col} LIKE ?", [f"%{val}"])
            
            if actual_op == 'regex':
                if is_not:
                    # SQLite 没有直接的 NOT REGEXP，需要组合
                    return (f"NOT ({col} REGEXP ?)", [val])
                else:
                    return (f"{col} REGEXP ?", [val])
            
            if actual_op == 'length_is':
                op_symbol = '!=' if is_not else '='
                return (f"LENGTH({col}) {op_symbol} ?", [int(val)])
            
            if actual_op == 'length_gt':
                if is_not:
                    return (f"LENGTH({col}) <= ?", [int(val)])
                else:
                    return (f"LENGTH({col}) > ?", [int(val)])
            
            if actual_op == 'length_lt':
                if is_not:
                    return (f"LENGTH({col}) >= ?", [int(val)])
                else:
                    return (f"LENGTH({col}) < ?", [int(val)])

        if filt.column_type == 'boolean':
            bool_val = 1 if str(val).lower() in ['true', '1', 'yes', 'y', 't'] else 0
            if actual_op == 'is':
                if is_not:
                    return (f"{col} != ?", [bool_val])
                return (f"{col} = ?", [bool_val])
            if actual_op == 'is_not':  # 已经包含 NOT
                return (f"{col} != ?", [bool_val])
    
            
        if filt.column_type == 'datetime':
            if actual_op == 'after':
                op_symbol = '<=' if is_not else '>'
                return (f"{col} {op_symbol} ?", [val])
            if actual_op == 'before':
                op_symbol = '>=' if is_not else '<'
                return (f"{col} {op_symbol} ?", [val])
            if actual_op == 'on':
                if is_not:
                    return (f"DATE({col}) != DATE(?)", [val])
                return (f"DATE({col}) = DATE(?)", [val])
            if actual_op == 'between':
                v_start, v_end = val.split(',', 1)
                if is_not:
                    return (f"(DATE({col}) < DATE(?) OR DATE({col}) > DATE(?))", [v_start, v_end])
                return (f"DATE({col}) BETWEEN DATE(?) AND DATE(?)", [v_start, v_end])
                
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
