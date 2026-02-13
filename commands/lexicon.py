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

def echo_data(data):
    if is_headless():
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))

@click.group()
def cli():
    """Lexicon Engine: Unified access to words, characters, and semantic components."""
    pass

@cli.command()
@click.option('--sources-dir', default='sources/lexicon', help='Directory containing raw txt files')
@click.option('--clear', is_flag=True, help='Clear existing database')
def init(sources_dir, clear):
    """Initialize the lexicon database from raw sources."""
    if clear and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = WAL")

    log("🏗️  Creating tables...", fg='cyan')
    
    # 1. Dictionary Table (Words & Freq)
    cursor.execute("DROP TABLE IF EXISTS dictionary")
    cursor.execute("""
        CREATE TABLE dictionary (
            term TEXT PRIMARY KEY,
            frequency INTEGER DEFAULT 0,
            tag TEXT,
            semantic_codes TEXT
        )
    """)
    
    # 2. Atoms Table (Characters & Components)
    cursor.execute("DROP TABLE IF EXISTS atoms")
    cursor.execute("""
        CREATE TABLE atoms (
            char TEXT PRIMARY KEY,
            components TEXT,
            unicode_hex TEXT
        )
    """)

    # 3. Traditional/Simplified Mapping
    cursor.execute("DROP TABLE IF EXISTS st_map")
    cursor.execute("""
        CREATE TABLE st_map (
            traditional TEXT PRIMARY KEY,
            simplified TEXT
        )
    """)

    # --- Load Jieba Dict ---
    jieba_path = os.path.join(sources_dir, 'jieba_dict.txt')
    if os.path.exists(jieba_path):
        log(f"📥 Loading dictionary from {jieba_path}...", fg='cyan')
        batch = []
        with open(jieba_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        term = parts[0]
                        freq = int(parts[1])
                        tag = parts[2] if len(parts) > 2 else None
                        batch.append((term, freq, tag))
                    except (ValueError, IndexError): continue
                if len(batch) >= 5000:
                    cursor.executemany("INSERT OR IGNORE INTO dictionary (term, frequency, tag) VALUES (?, ?, ?)", batch)
                    batch = []
        if batch:
            cursor.executemany("INSERT OR IGNORE INTO dictionary (term, frequency, tag) VALUES (?, ?, ?)", batch)

    # --- Load Cilin ---
    cilin_path = os.path.join(sources_dir, 'cilin.txt')
    if os.path.exists(cilin_path):
        log(f"📥 Loading semantic codes from {cilin_path}...", fg='cyan')
        term_to_codes = {}
        with open(cilin_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split()
                if len(parts) < 2: continue
                code = parts[0].rstrip('= #@')
                terms = parts[1:]
                for t in terms:
                    if t not in term_to_codes: term_to_codes[t] = set()
                    term_to_codes[t].add(code)
        
        batch = []
        for t, codes in term_to_codes.items():
            batch.append((",".join(codes), t))
            if len(batch) >= 2000:
                cursor.executemany("UPDATE dictionary SET semantic_codes = ? WHERE term = ?", batch)
                batch = []
        if batch:
            cursor.executemany("UPDATE dictionary SET semantic_codes = ? WHERE term = ?", batch)

    # --- Load IDS (Atoms) ---
    ids_path = os.path.join(sources_dir, 'ids.txt')
    if os.path.exists(ids_path):
        log(f"📥 Loading character atoms from {ids_path}...", fg='cyan')
        batch = []
        with open(ids_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip(): continue
                parts = line.strip().split('	')
                if len(parts) >= 3:
                    u_hex = parts[0]
                    char = parts[1]
                    components = parts[2]
                    batch.append((char, components, u_hex))
                if len(batch) >= 5000:
                    cursor.executemany("INSERT OR IGNORE INTO atoms (char, components, unicode_hex) VALUES (?, ?, ?)", batch)
                    batch = []
        if batch:
            cursor.executemany("INSERT OR IGNORE INTO atoms (char, components, unicode_hex) VALUES (?, ?, ?)", batch)

    # --- Load ST Map ---
    st_path = os.path.join(sources_dir, 'STCharacters.txt')
    if os.path.exists(st_path):
        log(f"📥 Loading ST mapping from {st_path}...", fg='cyan')
        batch = []
        with open(st_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip(): continue
                parts = line.strip().split('	')
                if len(parts) >= 2:
                    trad = parts[0]
                    simp = parts[1].split()[0] # Take first simplified version
                    batch.append((trad, simp))
        cursor.executemany("INSERT OR IGNORE INTO st_map (traditional, simplified) VALUES (?, ?)", batch)

    cursor.execute("CREATE INDEX idx_dict_freq ON dictionary(frequency DESC)")
    cursor.execute("CREATE INDEX idx_atoms_comp ON atoms(components)")
    
    conn.commit()
    conn.close()
    log("✅ Lexicon initialized successfully.", fg='green', bold=True)

@cli.command()
@click.argument('query')
@click.option('--limit', default=10, help='Max results')
def search(query, limit):
    """Search for terms in the dictionary."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dictionary WHERE term LIKE ? ORDER BY frequency DESC LIMIT ?", (f"%{query}%", limit))
    rows = cursor.fetchall()
    for r in rows:
        echo_data(dict(r))
    conn.close()

@cli.command()
@click.argument('char')
def atoms(char):
    """Get components of a character."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM atoms WHERE char = ?", (char,))
    row = cursor.fetchone()
    if row:
        echo_data(dict(row))
    else:
        log(f"No component data for: {char}", fg='yellow')
    conn.close()

@cli.command()
@click.argument('component')
@click.option('--limit', default=20, help='Max results')
def find(component, limit):
    """Find characters containing a specific component."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM atoms WHERE components LIKE ? LIMIT ?", (f"%{component}%", limit))
    rows = cursor.fetchall()
    for r in rows:
        echo_data(dict(r))
    conn.close()

@cli.command()
@click.option('--min-freq', default=1000, help='Minimum frequency')
@click.option('--limit', default=100, help='Max results')
def stream(min_freq, limit):
    """Stream high-frequency words."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dictionary WHERE frequency >= ? ORDER BY frequency DESC LIMIT ?", (min_freq, limit))
    for row in cursor:
        echo_data(dict(row))
    conn.close()

if __name__ == '__main__':
    cli()
