import click
import json
import sqlite3
import os
import sys
import re
from pathlib import Path

# Standard DB and Config paths
DB_PATH = os.path.expanduser("~/.lexicon.db")
CONFIG_PATH = os.path.expanduser("~/.lexicon.json")

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

SUPPORTED_FEATURES = [
    "fts-engine", "pipe-stream", "unified-output-protocol", 
    "sub-command-isolation", "direct-sql", "doctor-stat",
    "schema-reflection", "shell-completion-manager", "config-manager"
]

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

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def get_input_stream(query, stdin_flag):
    """Handle both argument query and stdin stream."""
    if query == '-' or stdin_flag:
        for line in sys.stdin:
            yield line.strip()
    elif query:
        yield query

def format_output(row, mode, source_id=None, fields=None):
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    if source_id: data['_source'] = source_id
    
    if mode in ['json', 'stream']:
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        # Pure values for unix tools like awk/cut
        click.echo(" ".join([str(v) for v in data.values()]))
    else: # mode == 'show' (Default)
        # Standard View with rich formatting
        color = 'cyan' if source_id == 'ids' else 'green'
        label = click.style(f"[{source_id}]", fg='white', dim=True) if source_id else ""
        
        # Primary key identification
        pk = data.get('term') or data.get('char') or list(data.values())[0]
        click.secho(f"{label}【{pk}】", fg=color, bold=True, nl=False)
        
        # Detail formatting
        vals = [str(v) for k, v in data.items() if k not in ['term', 'char', '_source', 'pk']]
        if vals:
            click.echo(f"  " + click.style(" | ", fg='white', dim=True).join(vals))
        else:
            click.echo("")

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
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'stream', 'plain']), help='Output mode')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--limit', type=int)
def search(query, stdin, output, field, limit):
    """Global search across all sources with pipe support."""
    cfg = ConfigManager.load()
    output = output or cfg.get('output', 'show')
    limit = limit or cfg.get('limit', 10)
    
    if is_headless() and output == 'show': output = 'stream'
    store = LexiconStore()
    cursor = store.conn.cursor()
    
    for q in get_input_stream(query, stdin):
        if not q: continue
        for s_id in ['dict', 'ids']:
            table = f"source_{s_id}"
            pk_col = 'term' if s_id == 'dict' else 'char'
            try:
                cursor.execute(f"SELECT * FROM {table} WHERE {pk_col} MATCH ? LIMIT ?", (f"{q}*", limit))
                for row in cursor:
                    format_output(row, output, source_id=s_id, fields=field)
            except sqlite3.OperationalError:
                continue
    store.close()

# --- Advanced Features ---

@cli.command()
def schema():
    """Reflect database schema and table structures."""
    if not os.path.exists(DB_PATH):
        click.secho("❌ DB missing. Run 'init' first.", fg='red')
        return
    store = LexiconStore()
    cursor = store.conn.cursor()
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name LIKE 'source_%'")
    click.secho("\n📂 Lexicon Schema Reflection\n", fg='cyan', bold=True)
    for name, sql in cursor:
        click.secho(f" Table: {name}", fg='green', bold=True)
        # Extract columns from FTS5 SQL
        cols_match = re.search(r'\((.*)\)', sql)
        if cols_match:
            cols = [c.strip() for c in cols_match.group(1).split(',')]
            for col in cols:
                click.echo(f"  - {col}")
    click.echo("")
    store.close()

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    manifest_path = 'factory/references/features-manifest.json'
    if not os.path.exists(manifest_path):
        click.secho("❌ Manifest missing.", fg='red')
        return
        
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    click.secho("\n🚀 Lexicon Integrated Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 80)
    
    for feat in manifest:
        f_id = feat['id']
        f_status = 'ok' if f_id in SUPPORTED_FEATURES else (
            'miss' if feat.get('status') == 'mandatory' else 'opt'
        )
        
        if status and f_status != status:
            continue

        if f_status == 'ok':
            status_text = click.style("✅ OK", fg='green')
        elif f_status == 'miss':
            status_text = click.style("❌ MISSING", fg='red')
        else:
            status_text = click.style("⚪ OPT", fg='yellow')
            
        click.echo(f" {status_text:<19} | {feat['label']:<20} | {feat['description']}")
    click.echo("")

@cli.command()
@click.argument('query')
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

@cli.group()
def config_cmd():
    """[UX] Manage persistent defaults."""
    pass

@config_cmd.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value."""
    cfg = ConfigManager.load()
    if key == 'limit': value = int(value)
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ Set {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False)
def config_get(key):
    """Get configuration value(s)."""
    cfg = ConfigManager.load()
    if key:
        click.echo(cfg.get(key, "Not set"))
    else:
        click.echo(json.dumps(cfg, indent=2))

cli.add_command(config_cmd, name='config')

@cli.group()
def completion():
    """[UX] Shell completion management."""
    pass

@completion.command(name='show')
@click.option('--shell', type=click.Choice(['bash', 'zsh']), default='zsh')
def completion_show(shell):
    """Show the shell completion script."""
    # Force the script to generate for 'lxc' regardless of how it's called
    env = os.environ.copy()
    env[f"_LXC_COMPLETE"] = f"{shell}_source"
    import subprocess
    result = subprocess.run([sys.executable, __file__], env=env, capture_output=True, text=True)
    if "Usage:" in result.stdout or not result.stdout:
        click.echo(f'# Add to your profile: eval "$(_LXC_COMPLETE={shell}_source lxc)"')
    else:
        click.echo(result.stdout)

@completion.command(name='install')
@click.confirmation_option(prompt='Do you want to automatically install lxc completion to your shell profile?')
def completion_install():
    """Automatically install lxc shell completion."""
    shell_path = os.environ.get('SHELL', '')
    profile_path = ""
    if 'zsh' in shell_path:
        profile_path = os.path.expanduser("~/.zshrc")
        eval_line = 'eval "$(_LXC_COMPLETE=zsh_source lxc)"'
    elif 'bash' in shell_path:
        profile_path = os.path.expanduser("~/.bashrc")
        eval_line = 'eval "$(_LXC_COMPLETE=bash_source lxc)"'
    
    if not profile_path:
        click.secho("❌ Could not detect shell profile (bash/zsh).", fg='red')
        return

    if not os.path.exists(profile_path):
        click.secho(f"❌ Profile {profile_path} not found.", fg='red')
        return

    with open(profile_path, 'r') as f:
        content = f.read()
    
    if eval_line in content:
        click.secho(f"✨ Completion already installed in {profile_path}", fg='yellow')
    else:
        with open(profile_path, 'a') as f:
            f.write(f"\n# Lexicon (lxc) CLI Completion\n{eval_line}\n")
        click.secho(f"✅ Installed completion to {profile_path}. Please restart your shell.", fg='green')

# --- Sub-commands (Isolated Filters) ---

@cli.group()
def dict_cmd():
    """[Sub-command] Dictionary with Parametric Filtering."""
    pass

@dict_cmd.command(name='search')
@click.argument('query', required=False)
@click.option('--rank-min', type=int)
@click.option('--tag')
@click.option('--limit', type=int)
def dict_search(query, rank_min, tag, limit):
    """Search dictionary with rank and tag filters."""
    cfg = ConfigManager.load()
    limit = limit or cfg.get('limit', 20)
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
