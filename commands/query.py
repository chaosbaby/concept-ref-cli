from __future__ import annotations # Must be the first import

import click
import sqlite3
import os
import re
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from click.shell_completion import CompletionItem

# --- Constants & Configuration ---

DB_PATH = os.path.expanduser("~/.lexicon.db")

FIELD_TYPES = {
    'string': {
        'operators': ['is', 'contains', 'startswith', 'endswith', 'regex', 'length_is', 'length_gt', 'length_lt', 'in'],
        'value_type': 'string'
    },
    'integer': {
        'operators': ['is', 'gt', 'gte', 'lt', 'lte', 'between', 'in'],
        'value_type': 'number'
    },
    'datetime': { # Not yet implemented in QueryBuilder
        'operators': ['after', 'before', 'between', 'last', 'next', 'on'],
        'value_type': 'date'
    },
    'boolean': { # Not yet implemented in QueryBuilder
        'operators': ['is', 'is_not'],
        'value_type': 'boolean'
    }
}

# --- Schema Management ---

class SchemaManager:
    """Inspects and caches the DB schema, and maps it to simplified types."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.schema: Dict[str, Dict[str, str]] = {}
        self._load_schema()

    def _load_schema(self):
        if not os.path.exists(self.db_path):
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'source_%'")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table_name in tables:
            short_name = table_name.replace('source_', '')
            self.schema[short_name] = {}
            cursor.execute(f"PRAGMA table_info({table_name})")
            for col in cursor.fetchall():
                col_name, col_type = col[1], col[2]
                self.schema[short_name][col_name] = col_type
        conn.close()

    def get_simple_type(self, table: str, column: str) -> Optional[str]:
        """Maps SQLite type to a simple type from FIELD_TYPES."""
        sql_type = self.schema.get(table, {}).get(column, '').upper()
        if 'INT' in sql_type:
            return 'integer'
        if 'TEXT' in sql_type or 'CHAR' in sql_type or not sql_type: # Default to string for fts5
            return 'string'
        # Add more mappings for REAL, BLOB, etc. if needed
        return 'string' # Fallback

    def get_tables(self) -> List[str]:
        return list(self.schema.keys())

    def get_columns(self, table: str) -> List[str]:
        return list(self.schema.get(table, {}).keys())

# --- Parsing and Query Building ---

@dataclass
class Filter:
    table: str
    column: str
    op: str
    value: str
    raw: str
    column_type: str

class FilterParser:
    """Parses and validates filter strings against the schema."""
    
    @staticmethod
    def parse(filter_str: str, schema_manager: SchemaManager) -> Optional[Filter]:
        parts = filter_str.split(':', 3)
        if len(parts) < 4:
            click.secho(f"Invalid filter format: '{filter_str}'. Expected `table:column:op:value`.", fg='red')
            return None
        
        table, column, op, value = parts
        
        # Validation
        if table not in schema_manager.schema:
            click.secho(f"Invalid table '{table}' in filter '{filter_str}'. Valid tables: {list(schema_manager.schema.keys())}", fg='red')
            return None
        if column not in schema_manager.schema[table]:
            click.secho(f"Invalid column '{column}' for table '{table}'. Valid columns: {list(schema_manager.schema[table].keys())}", fg='red')
            return None
            
        simple_type = schema_manager.get_simple_type(table, column)
        if op not in FIELD_TYPES.get(simple_type, {}).get('operators', []):
            allowed_ops = FIELD_TYPES.get(simple_type, {}).get('operators', [])
            click.secho(f"Invalid operator '{op}' for column '{column}' (type: {simple_type}). Allowed: {allowed_ops}", fg='red')
            return None

        return Filter(table=table, column=column, op=op, value=value, raw=filter_str, column_type=simple_type)

class QueryBuilder:
    """Builds a type-safe SQL query from a list of validated filters."""

    @staticmethod
    def _get_op_sql(filt: 'Filter') -> Tuple[str, List[Any]]:
        col, op, val = filt.column, filt.op, filt.value
        
        # Helper for casting if needed
        def cast_if_numeric(column_name: str, target_type: str) -> str:
            # For FTS5 tables, all columns are text, so we often need to cast.
            # A more advanced schema manager could know which tables are virtual.
            return f"CAST({column_name} AS {target_type})"

        # Operators that apply to both string and numeric types
        if op == 'is': return (f"{col} = ?", [val])
        if op == 'in':
            vals = val.split(',')
            if filt.column_type == 'integer':
                try:
                    casted_vals = [float(v) for v in vals]
                    return (f"{cast_if_numeric(col, 'REAL')} IN ({','.join('?' for _ in casted_vals)})", casted_vals)
                except ValueError:
                    raise ValueError(f"Invalid numeric value for 'in' operator on integer column '{col}': {val}")
            return (f"{col} IN ({','.join('?' for _ in vals)})", vals)

        # String-specific operators
        if filt.column_type == 'string':
            if op == 'contains': return (f"{col} LIKE ?", [f"%{val}%"])
            if op == 'startswith': return (f"{col} LIKE ?", [f"{val}%"])
            if op == 'endswith': return (f"{col} LIKE ?", [f"%{val}"])
            if op == 'regex': return (f"{col} REGEXP ?", [val])
            if op == 'length_is': return (f"LENGTH({col}) = ?", [int(val)])
            if op == 'length_gt': return (f"LENGTH({col}) > ?", [int(val)])
            if op == 'length_lt': return (f"LENGTH({col}) < ?", [int(val)])

        # Numeric-specific operators
        if filt.column_type == 'integer':
            if op in ['gt', 'gte', 'lt', 'lte']:
                 op_map = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
                 return (f"{cast_if_numeric(col, 'REAL')} {op_map[op]} ?", [float(val)])
            if op == 'between': 
                v_start, v_end = val.split(',', 1)
                return (f"{cast_if_numeric(col, 'REAL')} BETWEEN ? AND ?", [float(v_start), float(v_end)])
            
        raise NotImplementedError(f"Operator '{op}' is defined for type '{filt.column_type}' but not implemented in QueryBuilder or applied to incorrect type.")

    @staticmethod
    def build_sql(filters: list['Filter']) -> Optional[Tuple[str, List[Any], str]]:
        if not filters:
            return None

        target_table = filters[0].table
        db_table_name = f"source_{target_table}"

        where_clauses = []
        params = []

        for f in filters:
            if f.table != target_table:
                click.secho(f"Error: Cross-table queries are not supported. All filters must be for table '{target_table}'.", fg='red')
                return None
            try:
                clause, p = QueryBuilder._get_op_sql(f)
                where_clauses.append(clause)
                params.extend(p)
            except Exception as e:
                click.secho(f"Error processing filter '{f.raw}': {e}", fg='red')
                return None

        if not where_clauses:
            return None

        sql = f"SELECT * FROM {db_table_name} WHERE {' AND '.join(where_clauses)}"
        return sql, params, db_table_name

# --- Shell Completion ---

def query_filters_completer(ctx, param, incomplete):
    schema_manager = SchemaManager(DB_PATH)
    
    parts = incomplete.split(':', 3)
    num_parts = len(parts)
    
    current_table = parts[0] if num_parts > 0 else ""
    current_column = parts[1] if num_parts > 1 else ""
    current_op = parts[2] if num_parts > 2 else ""
    
    # Context: Table name
    if num_parts == 1:
        return [CompletionItem(f"{t}:") for t in schema_manager.get_tables() if t.startswith(current_table)]
    
    # Context: Column name
    elif num_parts == 2:
        if current_table in schema_manager.schema:
            return [CompletionItem(f"{current_table}:{c}:") for c in schema_manager.get_columns(current_table) if c.startswith(current_column)]
    
    # Context: Operator name
    elif num_parts == 3:
        if current_table in schema_manager.schema and current_column in schema_manager.schema[current_table]:
            simple_type = schema_manager.get_simple_type(current_table, current_column)
            if simple_type in FIELD_TYPES:
                return [CompletionItem(f"{current_table}:{current_column}:{op}:") for op in FIELD_TYPES[simple_type]['operators'] if op.startswith(current_op)]
    
    return []


@click.command('query')
@click.argument('filters', nargs=-1, required=True, shell_complete=query_filters_completer)
@click.option('--limit', default=10, help="Number of results to return.")
def query_cmd(filters, limit):
    """
    Run a structured query using `table:column:op:value` syntax.
    
    Examples:
    
    lxc query dict:freq:gt:10000 dict:tag:is:n
    
    lxc query ids:char:in:a,b,c,d
    """
    if not os.path.exists(DB_PATH):
        click.secho(f"Database not found at {DB_PATH}. Please run `lxc init`.", fg='red')
        return

    schema_manager = SchemaManager(DB_PATH)
    parsed_filters = [f for f in [FilterParser.parse(s, schema_manager) for s in filters] if f]
    
    if not parsed_filters or len(parsed_filters) != len(filters):
        click.secho("Aborting due to invalid filters.", fg='yellow')
        return

    result = QueryBuilder.build_sql(parsed_filters)
    if not result:
        return
    sql, params, table_name = result
        
    sql += f" LIMIT ?"
    params.append(limit)

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        click.secho(f"SQL: {sql}", fg='yellow', dim=True)
        click.secho(f"Params: {params}", fg='yellow', dim=True)

        cursor.execute(sql, params)
        results = cursor.fetchall()
        
        if not results:
            click.secho("No results found.", fg='yellow')
            return
            
        for row in results:
            # A simple, consistent output format
            click.echo(json.dumps(dict(row), ensure_ascii=False))

    except sqlite3.OperationalError as e:
        click.secho(f"Database Error: {e}", fg='red')
    finally:
        if 'conn' in locals():
            conn.close()