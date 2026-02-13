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

# Standard DB path using a hidden file in home directory
DB_PATH = os.path.expanduser("~/.{{ tool_id }}.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_headless():
    """Check if the output should be pure data (pipe-friendly)."""
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def log(msg, fg=None, bold=False):
    """Unified logging that respects headless mode."""
    if not is_headless():
        click.secho(msg, fg=fg, bold=bold, err=True)

def echo_data(data):
    """Standardized data output (JSON for pipes, formatted for TTY)."""
    if is_headless():
        if isinstance(data, (dict, list)):
            click.echo(json.dumps(data, ensure_ascii=False))
        else:
            click.echo(data)
    else:
        if isinstance(data, (dict, list)):
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            click.echo(data)

@click.group()
def cli():
    """{{ description }}"""
    # Auto-init check
    if not os.path.exists(DB_PATH) and len(sys.argv) > 1 and sys.argv[1] not in ['init', 'completion']:
        log("ℹ️  Database not found. Initializing...", fg='cyan')
        ctx = click.get_current_context()
        # Note: In real usage, this might need a default data path or fail gracefully
        pass

@cli.command()
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']))
def completion(shell):
    """Generate shell completion script."""
    cmd = f"eval \"$(_\{{ tool_name.upper() \}}_COMPLETE={shell}_source {{ tool_name }})\""
    click.echo(f"# Add this to your shell config:")
    click.echo(cmd)

def handle_search(cursor, query, is_json, strict):
    if zhconv:
        query = zhconv.convert(query, 'zh-hans')
        
    pattern = query if strict else f"%{query}%"
    
    # Generic search logic (to be customized in generated scripts)
    cursor.execute("SELECT * FROM entries WHERE title LIKE ? OR content LIKE ? LIMIT 20", (pattern, pattern))
    rows = cursor.fetchall()
    
    results = [dict(r) for r in rows]
    
    if is_json or is_headless():
        for res in results:
            echo_data(res)
    else:
        if not results:
            log("No results found.", fg='yellow')
        for r in results:
            click.echo(f"【{r.get('title', 'N/A')}】 {r.get('content', '')[:100]}...")

@cli.command()
@click.argument('query', required=False)
@click.option('--json', 'is_json', is_flag=True, help='Output as JSON')
@click.option('--strict', is_flag=True, help='Exact match')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def search(query, is_json, strict, stream):
    """Search for terms or content."""
    conn = get_db()
    cursor = conn.cursor()
    
    if stream:
        for line in sys.stdin:
            q = line.strip()
            if q: handle_search(cursor, q, is_json, strict)
    elif query:
        handle_search(cursor, query, is_json, strict)
    else:
        log("Usage: {{ tool_name }} search [QUERY]", fg='yellow')
    conn.close()

@cli.command()
@click.option('--limit', default=20, help='Max items to stream')
@click.option('--offset', default=0, help='Skip items')
@click.option('--filter', 'filter_query', help='Optional filter SQL clause')
def stream(limit, offset, filter_query):
    """Stream raw data as NDJSON (Ideal for pipes)."""
    conn = get_db()
    cursor = conn.cursor()
    
    sql = "SELECT * FROM entries"
    if filter_query:
        sql += f" WHERE {filter_query}"
    sql += " LIMIT ? OFFSET ?"
    
    cursor.execute(sql, (limit, offset))
    for row in cursor:
        echo_data(dict(row))
    conn.close()

@cli.command()
@click.option('--data', 'data_path', required=True, help='Source data path')
@click.option('--clear', is_flag=True, help='Clear existing data')
def init(data_path, clear):
    """Initialize the database with high-performance import."""
    if clear and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = WAL")

    log("🏗️  Creating tables...", fg='cyan')
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("""
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            tags TEXT,
            metadata TEXT,
            fingerprint TEXT UNIQUE
        )
    """)
    cursor.execute("CREATE INDEX idx_title ON entries(title)")
    
    log(f"📥 Importing data from {data_path}...", fg='cyan')
    # Custom import logic to be implemented per dataset
    
    conn.commit()
    conn.close()
    log("✅ Initialization complete!", fg='green', bold=True)

@cli.command()
def doctor():
    """Check database health and statistics."""
    if not os.path.exists(DB_PATH):
        log("❌ Database file missing.", fg='red')
        return

    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT count(*) FROM entries")
        count = cursor.fetchone()[0]
        size = os.path.getsize(DB_PATH) / (1024 * 1024)
        
        log(f"📊 Database Stats:")
        log(f"  - Path: {DB_PATH}")
        log(f"  - Size: {size:.2f} MB")
        log(f"  - Total Entries: {count}")
        
        # Check for FTS5 if applicable
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'")
        has_fts = cursor.fetchone() is not None
        log(f"  - Full-Text Search: {'Enabled' if has_fts else 'Disabled'}")
        
    except Exception as e:
        log(f"❌ Error during check: {e}", fg='red')
    finally:
        conn.close()

if __name__ == '__main__':
    cli()
