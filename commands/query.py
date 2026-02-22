class QueryBuilder:
    """Builds a type-safe SQL query from a list of validated filters."""

    @staticmethod
    def _get_op_sql(filt: Filter) -> Tuple[str, List[Any]]:
        col, op, val = filt.column, filt.op, filt.value
        
        # String operators
        if op == 'is': return (f"{col} = ?", [val])
        if op == 'contains': return (f"{col} LIKE ?", [f"%{val}%"])
        if op == 'startswith': return (f"{col} LIKE ?", [f"{val}%"])
        if op == 'endswith': return (f"{col} LIKE ?", [f"%{val}%"])
        if op == 'regex': return (f"{col} REGEXP ?", [val]) # Note: Requires user-defined REGEXP function in SQLite
        if op == 'length_is': return (f"LENGTH({col}) = ?", [int(val)])
        if op == 'length_gt': return (f"LENGTH({col}) > ?", [int(val)])
        if op == 'length_lt': return (f"LENGTH({col}) < ?", [int(val)])

        # Numeric operators
        # No CAST needed if we trust the schema, but FTS5 tables store everything as text.
        # So we CAST to be safe, especially for virtual tables.
        if op in ['gt', 'gte', 'lt', 'lte']:
             op_map = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
             return (f"CAST({col} AS REAL) {op_map[op]} ?", [float(val)])
        if op == 'between': 
            v_start, v_end = val.split(',', 1)
            return (f"CAST({col} AS REAL) BETWEEN ? AND ?", [float(v_start), float(v_end)])
        if op == 'in':
            vals = val.split(',')
            return (f"{col} IN ({','.join('?' for _ in vals)})", vals)
            
        raise NotImplementedError(f"Operator '{op}' is defined but not implemented in QueryBuilder.")

    @staticmethod
    def build_sql(filters: list[Filter]) -> Optional[Tuple[str, List[Any], str]]:
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
                return None # Abort on error

        if not where_clauses:
            return None

        sql = f"SELECT * FROM {db_table_name} WHERE {' AND '.join(where_clauses)}"
        return sql, params, db_table_name

# --- Shell Completion ---

def query_filters_completer(ctx, param, incomplete):
    schema_manager = SchemaManager(DB_PATH) # Initialize for completion context
    
    # Determine which part of the filter string we are completing
    parts = incomplete.split(':', 3) # Max 3 splits: table, column, op, value
    num_parts = len(parts)
    
    current_table = None
    current_column = None
    current_op = None

    # Try to infer context from the incomplete string itself
    if num_parts > 0 and parts[0]: current_table = parts[0]
    if num_parts > 1 and parts[1]: current_column = parts[1]
    if num_parts > 2 and parts[2]: current_op = parts[2]
    
    suggestions = []

    # Context: Table name
    if num_parts == 1 and not current_table: # Just started typing `lxc query <TAB>`
        return [t for t in schema_manager.get_tables()]
    elif num_parts == 1: # `lxc query di<TAB>`
        return [t for t in schema_manager.get_tables() if t.startswith(current_table)]
    
    # Context: Column name
    elif num_parts == 2: # `lxc query dict:<TAB>` or `lxc query dict:f<TAB>`
        if current_table and current_table in schema_manager.schema:
            suggestions.extend([f"{current_table}:{c}" for c in schema_manager.get_columns(current_table) if c.startswith(current_column or '')])
            return suggestions
    
    # Context: Operator name
    elif num_parts == 3: # `lxc query dict:freq:<TAB>` or `lxc query dict:freq:g<TAB>`
        if current_table and current_column and current_table in schema_manager.schema and current_column in schema_manager.schema[current_table]:
            simple_type = schema_manager.get_simple_type(current_table, current_column)
            if simple_type in FIELD_TYPES:
                suggestions.extend([f"{current_table}:{current_column}:{op}" for op in FIELD_TYPES[simple_type]['operators'] if op.startswith(current_op or '')])
                return suggestions
    
    # Context: Value (e.g., `lxc query dict:tag:is:<TAB>`)
    # This is more complex and depends on the operator and column.
    # For now, no generic value completion, but could be added for known enum-like columns.
    
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
