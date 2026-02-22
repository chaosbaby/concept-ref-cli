import click
import sqlite3
import os
import json
import sys
from datetime import datetime

def get_input_stream(query, stdin_flag):
    """Handle both argument query and stdin stream."""
    if query == '-' or stdin_flag:
        # Check if there is data on stdin
        if not sys.stdin.isatty():
            for line in sys.stdin:
                yield line.strip()
    elif query:
        yield query

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
            # Try exact match for numbers first
            val = float(range_str)
            return f"{col_name} = ?", [val]
        except ValueError:
            # Fallback to LIKE for strings
            return f"{col_name} LIKE ?", [f'%{range_str}%']

class DynamicOptions:
    """Introspects DB schema and generates Click options with shell completion."""
    def __init__(self, db_path, table_name, completer_factory=None):
        self.db_path = db_path
        self.table_name = table_name
        self.numeric_types = ['INT', 'INTEGER', 'REAL', 'FLOAT', 'DOUBLE']
        self.text_types = ['TEXT', 'VARCHAR', 'CHAR']
        self.excluded_fields = [] 
        self._schema_cache = None
        self.completer_factory = completer_factory

    def get_schema(self):
        if self._schema_cache:
            return self._schema_cache
        if not os.path.exists(self.db_path): return []
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({self.table_name})")
        schema = cursor.fetchall()
        conn.close()
        self._schema_cache = schema
        return schema
    
    def get_column_names(self):
        return [col[1] for col in self.get_schema()]

    def get_primary_text_column(self):
        """Heuristic to find the best column for a generic text query."""
        schema = self.get_schema()
        # Prefer specific names
        for name_guess in ['term', 'name', 'title', 'char', 'id']:
            for col in schema:
                if col[1] == name_guess:
                    return name_guess
        # Fallback to first text-like column
        for col in schema:
            if any(t in col[2].upper() for t in self.text_types):
                return col[1]
        return None

    def generate_options(self):
        options = []
        for col in self.get_schema():
            col_name, col_type = col[1], col[2].upper()
            if col_name in self.excluded_fields: continue
            
            param_name = col_name.replace('_', '-')
            help_text = f"Filter by {col_name}."
            is_numeric = any(t in col_type for t in self.numeric_types)
            
            completer = None
            if not is_numeric and self.completer_factory:
                completer = self.completer_factory(col_name)

            if is_numeric:
                options.append(click.Option([f'--{param_name}'], help=help_text + " (e.g., 1-5, 10,20)", type=str))
            else:
                options.append(click.Option([f'--{param_name}'], help=help_text + " (text)", type=str, shell_complete=completer))
        return options

    def add_to_command(self, command):
        for option in self.generate_options():
            command.params.append(option)
        return command

def format_dynamic_output(row, mode, all_fields):
    """Generic formatter for dynamic commands with schema padding."""
    data = {field: row.get(field) for field in all_fields}

    if mode == 'json':
        for k, v in data.items():
            if 'time' in k and isinstance(v, (int, float)):
                data[k] = datetime.fromtimestamp(v).isoformat() if v else None
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    elif mode == 'ndjson':
        for k, v in data.items():
            if 'time' in k and isinstance(v, (int, float)):
                data[k] = datetime.fromtimestamp(v).isoformat() if v else None
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        click.echo(" | ".join([str(data.get(k, '')) for k in all_fields]))
    else: # show
        for key in all_fields:
            value = data.get(key)
            if 'time' in key and isinstance(value, (int, float)):
                value = datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M') if value else 'N/A'
            click.secho(f"{key}: ", fg='cyan', nl=False)
            click.echo(str(value if value is not None else 'N/A'))
        click.echo("-" * 20)

def create_table_search_command(db_path, table_name, fts_table=None):
    """
    Factory to create a Click search command for a specific database table,
    with dynamic filtering, sorting, and schema-aware output with shell completion.
    """
    
    # --- Shell Completion Factories ---
    def make_value_completer(column_name):
        def completer(ctx, param, incomplete):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                query = f"SELECT DISTINCT {column_name} FROM {table_name} WHERE {column_name} LIKE ? LIMIT 100"
                cursor.execute(query, (f'{incomplete}%',))
                values = [row[0] for row in cursor.fetchall() if row[0] is not None]
                return values
            except Exception:
                return []
            finally:
                if 'conn' in locals() and conn: conn.close()
        return completer

    option_generator = DynamicOptions(db_path, table_name, completer_factory=make_value_completer)
    valid_columns = option_generator.get_column_names()
    primary_text_col = option_generator.get_primary_text_column()

    def sort_by_completer(ctx, param, incomplete):
        return [c for c in valid_columns if c.startswith(incomplete)]

    # --- Command Definition ---
    query_help = f"Query string to search in '{primary_text_col}'." if primary_text_col else "Query string (no primary text column found)."
    
    @click.command(name=table_name, help=f"Search and filter records in the {table_name} table.")
    @click.argument('query', required=False)
    @click.option('--stdin', is_flag=True, help='Read query from stdin.')
    @click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), default='show', help='Output mode.')
    @click.option('--field', '-f', multiple=True, help='Select specific fields for output.')
    @click.option('--limit', type=int, default=10, help='Maximum number of results.')
    @click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', help='Logic to combine filters.')
    @click.option('--sort-by', help='Column to sort by.', shell_complete=sort_by_completer)
    @click.option('--sort-dir', type=click.Choice(['asc', 'desc']), default='desc', help='Sort direction.')
    @click.option('--where', help='RAW SQL where clause. Use with caution.')
    @click.pass_context
    def dynamic_search_cmd(ctx, query, stdin, output, field, limit, logic, sort_by, sort_dir, where, **kwargs):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # --- Determine Input Source and Target ---
        stdin_target_key = None
        processed_kwargs = {k.replace('-', '_'): v for k, v in kwargs.items()}

        for key, value in processed_kwargs.items():
            if value == '-':
                stdin_target_key = key
                break
        
        if not stdin_target_key and (query == '-' or stdin):
            stdin_target_key = primary_text_col

        # --- Prepare Input Items from the Determined Source ---
        input_items = []
        if stdin_target_key and not sys.stdin.isatty():
            # Read from stdin ONCE to avoid consuming the generator
            input_items = [line.strip() for line in sys.stdin if line.strip()]
        elif query:
            input_items = [query]
        
        # --- Prepare Base Filters (non-stdin) ---
        base_where_clauses, base_params = [], []
        for key, value in processed_kwargs.items():
            if value is not None and key != stdin_target_key:
                c, p = RangeParser.to_sql(key, value)
                if c: base_where_clauses.append(c); base_params.extend(p)
        if where:
            base_where_clauses.append(f"({where})")

        # --- Finalize Execution Plan ---
        fields_to_select = ", ".join(field) if field else "*"
        all_output_fields = list(field) if field else valid_columns
        
        # If no items from stdin/query, but other filters exist, run the query once without a query item.
        if not input_items and (base_where_clauses or where):
            input_items = [None]
        # If no input and no filters, run for a general full-table query (respecting limit).
        elif not input_items and not query and not stdin:
             input_items = [None]

        # --- Main Query Loop ---
        for q_item in input_items:
            where_clauses = list(base_where_clauses)
            params = list(base_params)

            # Apply the query item (from stdin or arg) to its target column
            if q_item and stdin_target_key:
                c, p = RangeParser.to_sql(stdin_target_key, q_item)
                if c: where_clauses.append(c); params.extend(p)
            
            sql = f"SELECT {fields_to_select} FROM {table_name}"
            if where_clauses:
                conditions = f" {logic} ".join(where_clauses)
                sql += f" WHERE {conditions}"
            
            # Add sorting
            if sort_by:
                if sort_by in valid_columns:
                    sql += f" ORDER BY {sort_by} {sort_dir.upper()}"
                else:
                    click.secho(f"Error: Invalid sort column '{sort_by}'.", fg='red')
                    continue 
            elif 'freq' in valid_columns:
                 sql += " ORDER BY CAST(freq AS INTEGER) DESC"
            elif 'rank' in valid_columns:
                 sql += " ORDER BY CAST(rank AS INTEGER) DESC"
            elif 'create_time' in valid_columns:
                sql += " ORDER BY create_time DESC"

            sql += " LIMIT ?"
            params.append(limit)
            
            try:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                results = [dict(row) for row in cursor.fetchall()]
                if not results:
                    continue
                
                for row in results:
                    format_dynamic_output(row, output, all_output_fields)
            except sqlite3.OperationalError as e:
                click.secho(f"DB Error: {e}\nQuery: {sql}\nParams: {params}", fg='red')
        
        conn.close()

    option_generator.add_to_command(dynamic_search_cmd)
    return dynamic_search_cmd
