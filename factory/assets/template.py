import click
import json
import sqlite3
import os
import sys
import re
from pathlib import Path

# Standard DB path
DB_PATH = os.path.expanduser("~/.{{ tool_id }}.db")
CONFIG_PATH = os.path.expanduser("~/.{{ tool_id }}.json")

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        return {"output": "show", "limit": 10}

    @staticmethod
    def save(config):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)

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
        pk = data.get('pk') or list(data.values())[0]
        desc = data.get('desc') or " | ".join([str(v) for k,v in data.items() if k != 'pk'])
        click.secho(f"【{pk}】", fg='cyan', nl=False)
        click.echo(f" {desc}")

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
def features():
    """Display supported features and capabilities."""
    manifest_path = os.path.join(os.path.dirname(__file__), 'features-manifest.json')
    # In practice, the factory can bake this or the CLI can look for it.
    click.secho(f"\n🚀 {{ tool_id }} Feature Matrix\n", fg='cyan', bold=True)
    # Placeholder for dynamic display logic
    click.echo(" [Dynamic Feature Matrix Implementation]")

@cli.command()
@click.argument('query', required=False)
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['view', 'json', 'plain', 'stream']), help='Output mode')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--limit', type=int)
def search(query, stdin, output, field, limit):
    """Search with standardized input/output."""
    cfg = ConfigManager.load()
    output = output or cfg.get('output', 'view')
    limit = limit or cfg.get('limit', 20)
    
    conn = get_db()
    cursor = conn.cursor()
    
    if is_headless() and output == 'view':
        output = 'stream'
        
    for q in get_input_stream(query, stdin):
        if not q: continue
        cursor.execute("SELECT * FROM entries WHERE pk MATCH ? LIMIT ?", (f"{q}*", limit))
        rows = cursor.fetchall()
        for row in rows:
            format_output(row, output, field)
            
    conn.close()

@cli.command()
@click.argument('query')
def complete(query):
    """Fast prefix completion for shell tab. (Target < 50ms)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pk FROM completion_table WHERE pk LIKE ? ORDER BY rank DESC LIMIT 15", (f"{query}%",))
    for row in cursor:
        click.echo(row['pk'])
    conn.close()

@cli.command()
@click.option('--count', default=1)
def pick(count):
    """Randomly pick items for inspiration."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entries ORDER BY RANDOM() LIMIT ?", (count,))
    for row in cursor:
        format_output(row, 'view')
    conn.close()

@cli.command()
@click.option('--data', required=True)
def init(data):
    """Initialize with FTS5 and completion index."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("CREATE VIRTUAL TABLE entries USING fts5(pk, desc, tags, val)")
    
    cursor.execute("DROP TABLE IF EXISTS completion_table")
    cursor.execute("CREATE TABLE completion_table (pk TEXT PRIMARY KEY, rank INTEGER)")
    cursor.execute("CREATE INDEX idx_comp_pk ON completion_table(pk, rank DESC)")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    cli()
