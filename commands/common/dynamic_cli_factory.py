import click
import sqlite3
import os
from datetime import datetime

class RangeParser:
    """Parse numeric ranges like '2', '1-', '1-5', '-20', '10,20'."""
    @staticmethod
    def to_sql(col_name, range_str):
        if not range_str: return None, []
        range_str = str(range_str).strip()
        
        if ',' in range_str:
            parts = range_str.split(',')
            start, end = parts[0].strip(), parts[1].strip()
            if start and end:
                try: return f"CAST({col_name} AS REAL) BETWEEN ? AND ?", [float(start), float(end)]
                except ValueError: return None, []
        if '-' in range_str:
            parts = range_str.split('-')
            start, end = parts[0].strip(), parts[1].strip()
            if start and end:
                try: return f"CAST({col_name} AS REAL) BETWEEN ? AND ?", [float(start), float(end)]
                except ValueError: return None, []
            elif start:
                try: return f"CAST({col_name} AS REAL) >= ?", [float(start)]
                except ValueError: return None, []
            elif end:
                try: return f"CAST({col_name} AS REAL) <= ?", [float(end)]
                except ValueError: return None, []
        try:
            return f"{col_name} = ?", [float(range_str)]
        except ValueError:
            return f"{col_name} LIKE ?", [f'%{range_str}%']

class DynamicOptions:
    """Introspects DB schema and generates Click options dynamically."""
    def __init__(self, db_path, table_name):
        self.db_path = db_path
        self.table_name = table_name
        self.numeric_types = ['INT', 'INTEGER', 'REAL', 'FLOAT', 'DOUBLE']
        # More specific exclusion list per table might be needed
        self.excluded_fields = ['id', 'file_mtime', 'session_id', 'content'] 

    def get_schema(self):
        if not os.path.exists(self.db_path): return []
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({self.table_name})")
        schema = cursor.fetchall()
        conn.close()
        return schema

    def generate_options(self):
        options = []
        for col in self.get_schema():
            col_name, col_type = col[1], col[2].upper()
            if col_name in self.excluded_fields: continue
            
            param_name = col_name.replace('_', '-')
            help_text = f"Filter by {col_name}."
            if any(t in col_type for t in self.numeric_types):
                options.append(click.Option([f'--{param_name}'], help=help_text + " (e.g., 1-5, 10,20)", type=str))
            else:
                options.append(click.Option([f'--{param_name}'], help=help_text + " (text)", type=str))
        return options

    def add_to_command(self, command):
        for option in self.generate_options():
            command.params.append(option)
        return command

def format_dynamic_output(row, mode, fields=None):
    """Generic formatter for dynamic commands."""
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    
    if mode in ['json', 'ndjson']:
        # Convert timestamp to ISO format for JSON
        for k, v in data.items():
            if 'time' in k and isinstance(v, (int, float)):
                data[k] = datetime.fromtimestamp(v).isoformat()
        click.echo(click.style(f"Not implemented yet", fg='red'))
    elif mode == 'plain':
        click.echo(" | ".join([str(data.get(k, '')) for k in (fields or data.keys())]))
    else: # show
        for key, value in data.items():
            if 'time' in key and isinstance(value, (int, float)):
                value = datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M')
            click.secho(f"{key}: ", fg='cyan', nl=False)
            click.echo(str(value))
        click.echo("-" * 20)

def create_table_search_command(db_path, table_name, fts_table=None):
    """
    Factory to create a Click search command for a specific database table.
    """
    @click.command(name=table_name, help=f"Search and filter records in the {table_name} table.")
    @click.argument('query', required=False)
    @click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), default='show', help='Output mode.')
    @click.option('--field', '-f', multiple=True, help='Select specific fields for output.')
    @click.option('--limit', type=int, default=10, help='Maximum number of results.')
    @click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', help='Logic to combine filters.')
    @click.pass_context
    def dynamic_search_cmd(ctx, query, output, field, limit, logic, **kwargs):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        where_clauses, params = [], []
        
        # FTS search if query and fts_table are provided
        if query and fts_table:
            # This part is complex; assumes a join key. For now, simple FTS.
            # Example: find session_ids from FTS, then filter sessions table.
            # This needs a more robust implementation based on actual schema relationships.
            click.secho(f"Note: FTS query on '{query}' is not fully implemented in this generic factory yet.", dim=True)

        processed_kwargs = {k.replace('-', '_'): v for k, v in kwargs.items()}
        for key, value in processed_kwargs.items():
            if value is not None:
                c, p = RangeParser.to_sql(key, value)
                if c: where_clauses.append(c); params.extend(p)

        sql = f"SELECT * FROM {table_name}"
        if where_clauses:
            # Correctly join the clauses with the specified logic operator
            conditions = f" {logic} ".join(where_clauses)
            sql += f" WHERE {conditions}"
        
        sql += " ORDER BY create_time DESC LIMIT ?"
        params.append(limit)
        
        try:
            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
            if not results:
                click.secho(f"No results found in {table_name}.", fg='yellow')
                return
            for row in results:
                format_dynamic_output(row, output, field)
        except sqlite3.OperationalError as e:
            click.secho(f"DB Error: {e}\nQuery: {sql}\nParams: {params}", fg='red')
        conn.close()

    # Add dynamic options to the newly created command
    DynamicOptions(db_path, table_name).add_to_command(dynamic_search_cmd)
    return dynamic_search_cmd
