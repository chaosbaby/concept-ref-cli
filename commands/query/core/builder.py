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
