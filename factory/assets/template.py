import click
import json
import sqlite3
import os
import sys
import re
from datetime import datetime

try:
    import zhconv
except ImportError:
    zhconv = None

# Standard DB path
DB_PATH = os.path.expanduser("~/.{{ tool_id }}.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def format_output(row, mode, fields=None):
    """Unified output formatter supporting projection and modes."""
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    
    if mode == 'json':
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'stream':
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        click.echo(" ".join([str(v) for v in data.values()]))
    else: # 'view' or default
        if 'pk' in data and 'desc' in data:
            click.secho(f"【{data['pk']}】", fg='cyan', nl=False)
            click.echo(f" {data['desc']}")
        else:
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))

def get_input_stream(query, stdin_flag):
    """Handle both argument query and stdin stream."""
    if query == '-' or stdin_flag:
        for line in sys.stdin:
            yield line.strip()
    elif query:
        yield query

@click.group()
def cli():
    """{{ description }}"""
    pass

@cli.command()
@click.argument('query', required=False)
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['view', 'json', 'plain', 'stream']), default='view')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--limit', default=20, help='Max results')
def search(query, stdin, output, field, limit):
    """Search with standardized input/output."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Auto-detect stream mode if in pipe
    if is_headless() and output == 'view':
        output = 'stream'
        
    for q in get_input_stream(query, stdin):
        if not q: continue
        # Generic search on pk (Primary Key)
        cursor.execute("SELECT * FROM entries WHERE pk MATCH ? LIMIT ?", (f"{q}*", limit))
        rows = cursor.fetchall()
        for row in rows:
            format_output(row, output, field)
            
    conn.close()

@cli.command()
@click.argument('query')
def complete(query):
    """Fast completion for shell tab. (Target < 50ms)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pk FROM completion_table WHERE pk LIKE ? ORDER BY rank DESC LIMIT 10", (f"{query}%",))
    for row in cursor:
        click.echo(row['pk'])
    conn.close()

@cli.command()
@click.option('--data', required=True)
def init(data):
    """Initialize with FTS5 and completion index."""
    # To be customized
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("CREATE VIRTUAL TABLE entries USING fts5(pk, desc, tags, val)")
    
    # Fast completion index
    cursor.execute("DROP TABLE IF EXISTS completion_table")
    cursor.execute("CREATE TABLE completion_table (pk TEXT PRIMARY KEY, rank INTEGER)")
    cursor.execute("CREATE INDEX idx_comp_pk ON completion_table(pk)")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    cli()
