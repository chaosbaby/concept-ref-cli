import click
import json
import sqlite3
import os
import sys
from pathlib import Path

# Standard DB path
DB_PATH = os.path.expanduser("~/.lexicon.db")

class LexiconStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_source_table(self, source_id):
        return f"source_{source_id.replace('-', '_')}"

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def format_output(row, mode, source_id=None):
    data = dict(row)
    if source_id: data['_source'] = source_id
    if mode in ['json', 'stream']:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        # Standard View
        color = 'cyan' if source_id == 'ids' else 'green'
        label = f"[{source_id}]" if source_id else ""
        pk = data.get('term') or data.get('char') or list(data.values())[0]
        click.secho(f"{label}【{pk}】", fg=color, nl=False)
        vals = [str(v) for k, v in data.items() if k not in ['term', 'char', '_source', 'pk']]
        click.echo(f" {' | '.join(vals)}")

@click.group()
def cli():
    """Lexicon Engine: Universal, Isolated, and Feature-Rich."""
    pass

# --- Core Management ---

@cli.command()
@click.option('--sources-dir', default='sources/lexicon', help='Data sources directory')
@click.option('--clear', is_flag=True, help='Clear database')
def init(sources_dir, clear):
    """Initialize multiple isolated lexicon tables."""
    if clear and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = WAL")
    
    # Init Table: Dictionary
    dict_path = Path(sources_dir) / "jieba_dict.txt"
    if dict_path.exists():
        cursor.execute("DROP TABLE IF EXISTS source_dict")
        cursor.execute("CREATE VIRTUAL TABLE source_dict USING fts5(term, freq, tag)")
        with open(dict_path, 'r', encoding='utf-8') as f:
            batch = []
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    batch.append((parts[0], parts[1], parts[2] if len(parts)>2 else ""))
                if len(batch) >= 5000:
                    cursor.executemany("INSERT INTO source_dict VALUES (?,?,?)", batch)
                    batch = []
            if batch: cursor.executemany("INSERT INTO source_dict VALUES (?,?,?)", batch)

    # Init Table: IDS
    ids_path = Path(sources_dir) / "ids.txt"
    if ids_path.exists():
        cursor.execute("DROP TABLE IF EXISTS source_ids")
        cursor.execute("CREATE VIRTUAL TABLE source_ids USING fts5(char, components)")
        with open(ids_path, 'r', encoding='utf-8') as f:
            batch = []
            for line in f:
                if line.startswith('#') or not line.strip(): continue
                parts = line.strip().split('\t')
                if len(parts) >= 3: batch.append((parts[1], parts[2]))
                if len(batch) >= 5000:
                    cursor.executemany("INSERT INTO source_ids VALUES (?,?)", batch)
                    batch = []
            if batch: cursor.executemany("INSERT INTO source_ids VALUES (?,?)", batch)

    conn.commit()
    conn.close()
    click.secho("✅ Lexicon Initialized.", fg='green', bold=True)

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['view', 'json', 'stream']), default='view')
@click.option('--limit', default=10)
def search(query, output, limit):
    """Global search across all sources."""
    if is_headless() and output == 'view': output = 'stream'
    store = LexiconStore()
    cursor = store.conn.cursor()
    
    for s_id in ['dict', 'ids']:
        table = f"source_{s_id}"
        cursor.execute(f"SELECT * FROM {table} LIMIT {limit}") # Simplified for demo
        for row in cursor:
            format_output(row, output, source_id=s_id)
    store.close()

# --- Advanced Features ---

@cli.command()
def features():
    """Display the full Capability Matrix."""
    with open('factory/references/features-manifest.json', 'r') as f:
        manifest = json.load(f)
    click.secho("\n🚀 Lexicon Integrated Feature Matrix\n", fg='cyan', bold=True)
    for feat in manifest:
        click.echo(f" ✅ {feat['label']:<20} | {feat['category']:<12} | {feat['description']}")
    click.echo("")

@cli.command()
@click.argument('statement')
def sql(statement):
    """Direct SQL access."""
    store = LexiconStore()
    try:
        cursor = store.conn.cursor()
        cursor.execute(statement)
        for row in cursor.fetchall():
            click.echo(json.dumps(dict(row), ensure_ascii=False))
    except Exception as e: click.secho(f"Error: {e}", fg='red')
    finally: store.close()

# --- Sub-commands (Isolated Filters) ---

@cli.group()
def dict_cmd():
    """[Sub-command] Dictionary with Parametric Filtering."""
    pass

@dict_cmd.command(name='search')
@click.argument('query', required=False)
@click.option('--rank-min', type=int)
@click.option('--tag')
@click.option('--limit', default=20)
def dict_search(query, rank_min, tag, limit):
    """Search dictionary with rank and tag filters."""
    store = LexiconStore()
    conds = []
    params = []
    if query: conds.append("term MATCH ?"); params.append(f"{query}*")
    if rank_min: conds.append("CAST(freq AS INTEGER) >= ?"); params.append(rank_min)
    if tag: conds.append("tag = ?"); params.append(tag)
    
    sql_q = "SELECT * FROM source_dict"
    if conds: sql_q += " WHERE " + " AND ".join(conds)
    sql_q += f" ORDER BY CAST(freq AS INTEGER) DESC LIMIT {limit}"
    
    cursor = store.conn.cursor()
    cursor.execute(sql_q, params)
    for row in cursor: format_output(row, 'view', 'dict')
    store.close()

# Rename sub-command group for clean CLI
cli.add_command(dict_cmd, name='dict')

@cli.command()
def doctor():
    """Check database health."""
    if not os.path.exists(DB_PATH):
        click.secho("❌ DB missing.", fg='red')
        return
    store = LexiconStore()
    cursor = store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'source_%'")
    for r in cursor:
        cursor.execute(f"SELECT count(*) FROM {r[0]}")
        click.echo(f" - {r[0]}: {cursor.fetchone()[0]} entries")
    store.close()

if __name__ == '__main__':
    cli()
