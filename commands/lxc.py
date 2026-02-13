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
    DEFAULT_CONFIG = {
        "output": "show", 
        "limit": 10, 
        "default_rank": None, 
        "default_len": None,
        "default_tag": None,
        "default_no_tag": None
    }
    
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
                # Ensure all default keys exist
                for k, v in ConfigManager.DEFAULT_CONFIG.items():
                    if k not in cfg: cfg[k] = v
                return cfg
        return ConfigManager.DEFAULT_CONFIG.copy()

    @staticmethod
    def save(config):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)

class RangeParser:
    """Parse numeric ranges like '2', '1-', '1-5', '-20'."""
    @staticmethod
    def to_sql(col_name, range_str):
        if not range_str: return None, []
        range_str = str(range_str).strip()
        
        if '-' in range_str:
            parts = range_str.split('-')
            start, end = parts[0].strip(), parts[1].strip()
            if start and end:
                return f"CAST({col_name} AS INTEGER) BETWEEN ? AND ?", [int(start), int(end)]
            elif start: # '1-'
                return f"CAST({col_name} AS INTEGER) >= ?", [int(start)]
            elif end: # '-20'
                return f"CAST({col_name} AS INTEGER) <= ?", [int(end)]
        
        try:
            return f"CAST({col_name} AS INTEGER) = ?", [int(range_str)]
        except ValueError:
            return None, []

SUPPORTED_FEATURES = [
    "fts-engine", "pipe-stream", "unified-output-protocol", 
    "sub-command-isolation", "direct-sql", "doctor-stat",
    "schema-reflection", "shell-completion-manager", "config-manager",
    "auto-completion-engine", "interactive-pick", "cross-ref-join",
    "multi-dimensional-filter"
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

    def get_all_tags(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT tag FROM source_dict WHERE tag != ''")
            return [r['tag'] for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []

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
        click.echo(" ".join([str(v) for k, v in data.items() if not k.startswith('_')]))
    else: # mode == 'show' (Default)
        color = 'cyan' if source_id == 'ids' else 'green'
        label = click.style(f"[{source_id}]", fg='white', dim=True) if source_id else ""
        pk = data.get('term') or data.get('char') or list(data.values())[0]
        click.secho(f"{label}【{pk}】", fg=color, bold=True, nl=False)
        vals = [str(v) for k, v in data.items() if k not in ['term', 'char', '_source', 'pk'] and not k.startswith('_')]
        if vals:
            click.echo(f"  " + click.style(" | ", fg='white', dim=True).join(vals))
        else:
            click.echo("")
        if '_joined' in data:
            for item in data['_joined']:
                j_label = click.style(f"  └── [Join:{item.get('_source', '?')}]", fg='yellow', dim=True)
                j_pk = item.get('char') or item.get('term') or "?"
                j_vals = [str(v) for k, v in item.items() if k not in ['char', 'term', '_source'] and not k.startswith('_')]
                click.echo(f"{j_label} 【{j_pk}】 {' | '.join(j_vals)}")

def get_all_tags_list():
    store = LexiconStore()
    tags = store.get_all_tags()
    store.close()
    return tags

def tag_complete(ctx, param, incomplete):
    tags = get_all_tags_list()
    return [t for t in tags if t.startswith(incomplete)]

def config_key_complete(ctx, param, incomplete):
    keys = list(ConfigManager.DEFAULT_CONFIG.keys())
    return [k for k in keys if k.startswith(incomplete)]

@click.group()
def cli():
    """Lexicon Engine: Universal, Isolated, and Feature-Rich."""
    pass

@cli.command()
@click.argument('query', required=False)
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'stream', 'plain']), help='Output mode')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--join', '-j', help='Join related info (e.g. ids)')
@click.option('--rank', help='Rank/Freq filter (e.g. 1000-, 1-500)')
@click.option('--len', 'length', help='Length filter (e.g. 2, 4-, 2-4)')
@click.option('--tag', 'tags', multiple=True, shell_complete=tag_complete, help='Include tags')
@click.option('--no-tag', 'no_tags', multiple=True, shell_complete=tag_complete, help='Exclude tags')
@click.option('--limit', type=int)
def search(query, stdin, output, field, join, rank, length, tags, no_tags, limit):
    """Global search across all sources with pipe support."""
    cfg = ConfigManager.load()
    output = output or cfg.get('output', 'show')
    limit = limit or cfg.get('limit', 10)
    rank = rank or cfg.get('default_rank')
    length = length or cfg.get('default_len')
    
    # Fallback for tags/no_tags from config (comma-separated string to list)
    if not tags and cfg.get('default_tag'):
        tags = [t.strip() for t in cfg.get('default_tag').split(',') if t.strip()]
    if not no_tags and cfg.get('default_no_tag'):
        no_tags = [t.strip() for t in cfg.get('default_no_tag').split(',') if t.strip()]
    
    if is_headless() and output == 'show': output = 'stream'
    store = LexiconStore()
    cursor = store.conn.cursor()
    
    for q in get_input_stream(query, stdin):
        if not q: continue
        for s_id in ['dict', 'ids']:
            table = f"source_{s_id}"
            pk_col = 'term' if s_id == 'dict' else 'char'
            sql_base = f"SELECT * FROM {table} WHERE {pk_col} MATCH ?"
            params = [f"{q}*"]
            
            if rank and s_id == 'dict':
                clause, p = RangeParser.to_sql('freq', rank)
                if clause: sql_base += f" AND {clause}"; params.extend(p)
            if length:
                clause, p = RangeParser.to_sql(f"length({pk_col})", length)
                if clause: sql_base += f" AND {clause}"; params.extend(p)

            if s_id == 'dict':
                if tags:
                    placeholders = ','.join(['?'] * len(tags))
                    sql_base += f" AND tag IN ({placeholders})"
                    params.extend(tags)
                if no_tags:
                    placeholders = ','.join(['?'] * len(no_tags))
                    sql_base += f" AND tag NOT IN ({placeholders})"
                    params.extend(no_tags)
                
            sql_base += f" LIMIT {limit}"
            try:
                cursor.execute(sql_base, params)
                rows = [dict(r) for r in cursor.fetchall()]
                if join == 'ids' and s_id == 'dict':
                    for row in rows:
                        term = row.get('term', '')
                        joined_data = []
                        for c in list(term):
                            cursor.execute("SELECT * FROM source_ids WHERE char = ?", (c,))
                            j_res = cursor.fetchone()
                            if j_res:
                                j_dict = dict(j_res); j_dict['_source'] = 'ids'
                                joined_data.append(j_dict)
                        if joined_data: row['_joined'] = joined_data
                for row in rows: format_output(row, output, source_id=s_id, fields=field)
            except sqlite3.OperationalError: continue
    store.close()

@cli.group()
def config_cmd():
    """[UX] Manage persistent defaults."""
    pass

@config_cmd.command(name='set')
@click.argument('key', shell_complete=config_key_complete)
@click.argument('value')
def config_set(key, value):
    """Set a configuration value."""
    cfg = ConfigManager.load()
    if key == 'limit': value = int(value)
    if key == 'output' and value not in ['show', 'json', 'stream', 'plain']:
        click.secho(f"⚠ Invalid output mode: {value}", fg='yellow')
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ Set {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False, shell_complete=config_key_complete)
def config_get(key):
    """Get configuration value(s)."""
    cfg = ConfigManager.load()
    if key: click.echo(cfg.get(key, "Not set"))
    else: click.echo(json.dumps(cfg, indent=2))

cli.add_command(config_cmd, name='config')

@cli.command()
@click.option('--sources-dir', default='sources/lexicon', help='Data sources directory')
@click.option('--clear', is_flag=True, help='Clear database')
def init(sources_dir, clear):
    """Initialize multiple isolated lexicon tables."""
    if clear and os.path.exists(DB_PATH): os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH); cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF"); cursor.execute("PRAGMA journal_mode = WAL")
    dict_path = Path(sources_dir) / "jieba_dict.txt"
    if dict_path.exists():
        cursor.execute("DROP TABLE IF EXISTS source_dict")
        cursor.execute("CREATE VIRTUAL TABLE source_dict USING fts5(term, freq, tag)")
        cursor.execute("DROP TABLE IF EXISTS comp_dict")
        cursor.execute("CREATE TABLE comp_dict (term TEXT PRIMARY KEY, freq INTEGER)")
        with open(dict_path, 'r', encoding='utf-8') as f:
            batch, comp_batch = [], []
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    term, freq = parts[0], parts[1]; tag = parts[2] if len(parts)>2 else ""
                    batch.append((term, freq, tag)); comp_batch.append((term, int(freq)))
                if len(batch) >= 5000:
                    cursor.executemany("INSERT INTO source_dict VALUES (?,?,?)", batch)
                    cursor.executemany("INSERT OR IGNORE INTO comp_dict VALUES (?,?)", comp_batch)
                    batch, comp_batch = [], []
            if batch: 
                cursor.executemany("INSERT INTO source_dict VALUES (?,?,?)", batch)
                cursor.executemany("INSERT OR IGNORE INTO comp_dict VALUES (?,?)", comp_batch)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comp_freq ON comp_dict(term, freq DESC)")
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
    conn.commit(); conn.close()
    click.secho("✅ Lexicon Initialized.", fg='green', bold=True)

@cli.command()
def schema():
    """Reflect database schema and table structures."""
    if not os.path.exists(DB_PATH): click.secho("❌ DB missing.", fg='red'); return
    store = LexiconStore(); cursor = store.conn.cursor()
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name LIKE 'source_%'")
    click.secho("\n📂 Lexicon Schema Reflection\n", fg='cyan', bold=True)
    for name, sql in cursor:
        click.secho(f" Table: {name}", fg='green', bold=True)
        cols_match = re.search(r'\((.*)\)', sql)
        if cols_match:
            for col in [c.strip() for c in cols_match.group(1).split(',')]: click.echo(f"  - {col}")
    click.echo(""); store.close()

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    manifest_path = 'factory/references/features-manifest.json'
    if not os.path.exists(manifest_path): click.secho("❌ Manifest missing.", fg='red'); return
    with open(manifest_path, 'r') as f: manifest = json.load(f)
    click.secho("\n🚀 Lexicon Integrated Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 80)
    for feat in manifest:
        f_id = feat['id']; f_status = 'ok' if f_id in SUPPORTED_FEATURES else ('miss' if feat.get('status') == 'mandatory' else 'opt')
        if status and f_status != status: continue
        st = click.style("✅ OK", fg='green') if f_status == 'ok' else (click.style("❌ MISSING", fg='red') if f_status == 'miss' else click.style("⚪ OPT", fg='yellow'))
        click.echo(f" {st:<19} | {feat['label']:<20} | {feat['description']}")
    click.echo("")

@cli.command()
@click.argument('statement')
def sql(statement):
    """Direct SQL access."""
    store = LexiconStore()
    try:
        cursor = store.conn.cursor(); cursor.execute(statement)
        for row in cursor.fetchall(): click.echo(json.dumps(dict(row), ensure_ascii=False))
    except Exception as e: click.secho(f"Error: {e}", fg='red')
    finally: store.close()

@cli.command()
@click.argument('query')
def complete(query):
    """Fast prefix completion for shell tab."""
    if not os.path.exists(DB_PATH): return
    store = LexiconStore(); cursor = store.conn.cursor()
    cursor.execute("SELECT term FROM comp_dict WHERE term LIKE ? ORDER BY freq DESC LIMIT 15", (f"{query}%",))
    for row in cursor: click.echo(row['term'])
    store.close()

@cli.command()
@click.option('--count', default=1, help='Number of items to pick')
def pick(count):
    """[UX] Pick high-quality random items."""
    if not os.path.exists(DB_PATH): return
    store = LexiconStore(); cursor = store.conn.cursor()
    cursor.execute("SELECT * FROM source_dict WHERE CAST(freq AS INTEGER) > 5000 ORDER BY RANDOM() LIMIT ?", (count,))
    for row in cursor: format_output(row, 'show', source_id='dict')
    store.close()

@cli.group()
def completion():
    """[UX] Shell completion management."""
    pass

@completion.command(name='show')
@click.option('--shell', type=click.Choice(['bash', 'zsh']), default='zsh')
def completion_show(shell):
    env = os.environ.copy(); env[f"_LXC_COMPLETE"] = f"{shell}_source"
    import subprocess
    result = subprocess.run([sys.executable, __file__], env=env, capture_output=True, text=True)
    click.echo(result.stdout if result.stdout else f'# Add to your profile: eval "$(_LXC_COMPLETE={shell}_source lxc)"')

@completion.command(name='install')
@click.confirmation_option(prompt='Install lxc completion?')
def completion_install():
    shell_path = os.environ.get('SHELL', ''); profile_path = ""
    if 'zsh' in shell_path: profile_path = os.path.expanduser("~/.zshrc"); eval_line = 'eval "$(_LXC_COMPLETE=zsh_source lxc)"'
    elif 'bash' in shell_path: profile_path = os.path.expanduser("~/.bashrc"); eval_line = 'eval "$(_LXC_COMPLETE=bash_source lxc)"'
    if not profile_path or not os.path.exists(profile_path): click.secho("❌ Profile not found.", fg='red'); return
    with open(profile_path, 'r') as f: content = f.read()
    if eval_line not in content:
        with open(profile_path, 'a') as f: f.write(f"\n# Lexicon completion\n{eval_line}\n")
        click.secho(f"✅ Installed to {profile_path}", fg='green')
    else: click.secho("✨ Already installed", fg='yellow')

@cli.command()
def doctor():
    """Check database health."""
    if not os.path.exists(DB_PATH): click.secho("❌ DB missing.", fg='red'); return
    store = LexiconStore(); cursor = store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'source_%'")
    for r in cursor:
        cursor.execute(f"SELECT count(*) FROM {r[0]}")
        click.echo(f" - {r[0]}: {cursor.fetchone()[0]} entries")
    store.close()

if __name__ == '__main__':
    cli()
