import click
import json
import sqlite3
import os
import sys
import re

# Standard DB path
DB_PATH = os.path.expanduser("~/.lexicon.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def log(msg, fg=None, bold=False):
    if not is_headless():
        click.secho(msg, fg=fg, bold=bold, err=True)

def format_output(row, mode, fields=None):
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    
    if mode == 'json':
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'stream':
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        click.echo(" ".join([str(v) for v in data.values()]))
    else: # 'view'
        click.secho(f"【{data.get('pk', '')}】", fg='cyan', nl=False)
        click.echo(f" {data.get('desc', '')} (Rank: {data.get('val', 0)})")

def get_input_stream(query, stdin_flag):
    if query == '-' or stdin_flag:
        for line in sys.stdin:
            yield line.strip()
    elif query:
        yield query

@click.group()
def cli():
    """Lexicon Engine: Unified access to words, characters, and semantic components."""
    pass

@cli.command()
@click.option('--sources-dir', default='sources/lexicon', help='Directory containing raw txt files')
@click.option('--clear', is_flag=True, help='Clear existing database')
def init(sources_dir, clear):
    """Initialize the lexicon database with FTS5 and Virtual Columns."""
    if clear and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = WAL")

    log("🏗️  Creating FTS5 tables...", fg='cyan')
    
    # Unified Search Table (FTS5)
    # pk: word/char, desc: components/semantic, tags: word-tag/semantic-code, val: freq
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("CREATE VIRTUAL TABLE entries USING fts5(pk, desc, tags, val, source UNINDEXED)")
    
    # Completion Table
    cursor.execute("DROP TABLE IF EXISTS completion_table")
    cursor.execute("CREATE TABLE completion_table (pk TEXT PRIMARY KEY, rank INTEGER)")
    cursor.execute("CREATE INDEX idx_comp_pk ON completion_table(pk)")

    # --- Load Jieba Dict ---
    jieba_path = os.path.join(sources_dir, 'jieba_dict.txt')
    if os.path.exists(jieba_path):
        log(f"📥 Loading dictionary...", fg='cyan')
        batch = []
        comp_batch = []
        with open(jieba_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        term = parts[0]
                        freq = parts[1]
                        tag = parts[2] if len(parts) > 2 else ""
                        batch.append((term, "", tag, freq, "dict"))
                        comp_batch.append((term, int(freq)))
                    except (ValueError, IndexError): continue
                if len(batch) >= 5000:
                    cursor.executemany("INSERT INTO entries (pk, desc, tags, val, source) VALUES (?, ?, ?, ?, ?)", batch)
                    cursor.executemany("INSERT OR IGNORE INTO completion_table (pk, rank) VALUES (?, ?)", comp_batch)
                    batch, comp_batch = [], []
        if batch:
            cursor.executemany("INSERT INTO entries (pk, desc, tags, val, source) VALUES (?, ?, ?, ?, ?)", batch)
            cursor.executemany("INSERT OR IGNORE INTO completion_table (pk, rank) VALUES (?, ?)", comp_batch)

    # --- Load IDS (Atoms) ---
    ids_path = os.path.join(sources_dir, 'ids.txt')
    if os.path.exists(ids_path):
        log(f"📥 Loading character atoms...", fg='cyan')
        batch = []
        with open(ids_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip(): continue
                parts = line.strip().split('\t')
                if len(parts) >= 3:
                    char = parts[1]
                    components = parts[2]
                    batch.append((char, components, "", "0", "atoms"))
                if len(batch) >= 5000:
                    cursor.executemany("INSERT INTO entries (pk, desc, tags, val, source) VALUES (?, ?, ?, ?, ?)", batch)
                    batch = []
        if batch:
            cursor.executemany("INSERT INTO entries (pk, desc, tags, val, source) VALUES (?, ?, ?, ?, ?)", batch)

    conn.commit()
    conn.close()
    log("✅ Lexicon initialized with FTS5.", fg='green', bold=True)

@cli.command()
@click.argument('query', required=False)
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['view', 'json', 'plain', 'stream']), default='view')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--limit', default=10, help='Max results')
def search(query, stdin, output, field, limit):
    """Universal search across words and characters."""
    conn = get_db()
    cursor = conn.cursor()
    
    if is_headless() and output == 'view':
        output = 'stream'
        
    for q in get_input_stream(query, stdin):
        if not q: continue
        # Use FTS5 MATCH for speed. Try prefix match.
        cursor.execute("SELECT * FROM entries WHERE pk MATCH ? ORDER BY CAST(val AS INTEGER) DESC LIMIT ?", (f"{q}*", limit))
        rows = cursor.fetchall()
        for row in rows:
            format_output(row, output, field)
    conn.close()

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
        log(f"📊 Lexicon Stats:")
        log(f"  - Path: {DB_PATH}")
        log(f"  - Size: {size:.2f} MB")
        log(f"  - Total Entries: {count}")
    finally:
        conn.close()

@cli.command()
@click.argument('query')
def complete(query):
    """Fast completion for shell tab."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pk FROM completion_table WHERE pk LIKE ? ORDER BY rank DESC LIMIT 10", (f"{query}%",))
    for row in cursor:
        click.echo(row['pk'])
    conn.close()

@cli.command()
@click.argument('char')
def atoms(char):
    """Shortcut: Get components of a character."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entries WHERE pk = ? AND source = 'atoms'", (char,))
    row = cursor.fetchone()
    if row:
        format_output(row, 'view')
    conn.close()

if __name__ == '__main__':
    cli()
