import click
import json
import sqlite3
import os
import sys
import time
from pathlib import Path
from datetime import datetime
import unicodedata # For CJK character width calculation
import subprocess
import shutil
import textwrap
import re

# Standard paths
DB_PATH = os.path.expanduser("~/.ac_chat.db")
CONFIG_PATH = os.path.expanduser("~/.ac_chat.json")

class ConfigManager:
    DEFAULT_CONFIG = {
        "output": "show",
        "limit": 10,
        "source_dir": "sources/ai-chat/conversations"
    }
    
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
                for k, v in ConfigManager.DEFAULT_CONFIG.items():
                    if k not in cfg: cfg[k] = v
                return cfg
        return ConfigManager.DEFAULT_CONFIG.copy()

    @staticmethod
    def save(config):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def get_display_width(s):
    width = 0
    for char in s:
        width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
    return width

def pad_cjk(s, width):
    return s + " " * max(0, width - get_display_width(s))

def source_completer(ctx, param, incomplete):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM sessions WHERE source LIKE ?", (f'%{incomplete}%',))
    sources = [row['source'] for row in cursor.fetchall()]
    conn.close()
    return sources

@click.group()
def cli():
    """AI-Chat (ac) CLI: Search and manage your AI conversation history."""
    pass

@cli.command()
@click.option('--data-dir', default="sources/ai-chat/conversations", help='Directory containing conversation JSONs')
@click.option('--rebuild', is_flag=True, help='Drop all tables and rebuild the database from scratch.')
def sync(data_dir, rebuild):
    """Incremental sync from JSON logs to SQLite. Use --rebuild to start fresh."""
    conn = get_db()
    cursor = conn.cursor()
    if rebuild:
        click.confirm("Are you sure you want to drop all data?", abort=True)
        for table in ['sessions', 'messages', 'search_index']: cursor.execute(f"DROP TABLE IF EXISTS {table}")
    cursor.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, source TEXT, title TEXT, create_time REAL, message_count INTEGER, file_mtime REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, create_time REAL, FOREIGN KEY(session_id) REFERENCES sessions(id))")
    cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(session_id UNINDEXED, message_id UNINDEXED, title, content, tokenize='unicode61')")
    conn.commit()
    data_path = Path(data_dir)
    if not data_path.exists(): click.secho(f"❌ Data directory {data_dir} not found.", fg='red'); return
    files = list(data_path.glob("*.json"))
    with click.progressbar(files, label="Syncing logs") as bar:
        for f_path in bar:
            mtime = f_path.stat().st_mtime
            cursor.execute("SELECT file_mtime FROM sessions WHERE id = ?", (f_path.stem,))
            row = cursor.fetchone()
            if row and row['file_mtime'] >= mtime and not rebuild: continue
            try:
                with open(f_path, 'r') as f: data = json.load(f)
                sid, source, title, ctime, msgs = data.get('id', f_path.stem), data.get('source', 'unknown'), data.get('title', 'Untitled'), data.get('create_time', mtime), data.get('messages', [])
                cursor.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                cursor.execute("DELETE FROM search_index WHERE session_id = ?", (sid,))
                cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?)", (sid, source, title, ctime, len(msgs), mtime))
                for m in msgs:
                    content = m.get('content', ''); message_id = cursor.lastrowid
                    if isinstance(content, list): content = "\n".join([item.get('text', '') for item in content if isinstance(item, dict) and 'text' in item])
                    cursor.execute("INSERT INTO messages (session_id, role, content, create_time) VALUES (?, ?, ?, ?)", (sid, m['role'], content, m.get('create_time')))
                    cursor.execute("INSERT INTO search_index VALUES (?, ?, ?, ?)", (sid, message_id, title, content))
            except Exception as e: click.echo(f"Error parsing {f_path.name}: {e}")
    conn.commit(); conn.close()
    click.secho("✅ Sync complete.", fg='green')

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), help='Output mode')
@click.option('--limit', type=int, help='Maximum number of results to return')
@click.option('--source', shell_complete=source_completer, help='Filter by source')
@click.option('--stdin', is_flag=True, help='Read query from stdin')
@click.option('--mode', type=click.Choice(['snippet', 'message', 'session']), default='snippet', help='Search result granularity.')
def search(query, output, limit, source, stdin, mode):
    """Search conversation history with different granularity modes."""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    
    if stdin or query == '-':
        if not sys.stdin.isatty():
            query = sys.stdin.read().strip()
        else:
            click.secho("Reading from stdin... (Press Ctrl+D to finish)", dim=True)
            query = sys.stdin.read().strip()

    if not query:
        ctx = click.get_current_context()
        click.echo(ctx.get_help())
        ctx.exit()

    effective_limit = limit if limit is not None else cfg.get('limit', 10)
    
    conn = get_db()
    cursor = conn.cursor()
    
    results = []
    
    if mode == 'message':
        sql = "SELECT s.id as session_id, s.title as session_title, s.source as session_source, m.role, m.content, m.create_time, snippet(search_index, 3, '>', '<', '...', 20) as highlight FROM search_index AS si JOIN messages AS m ON si.message_id = m.id JOIN sessions AS s ON si.session_id = s.id WHERE si.search_index MATCH ? ORDER BY m.create_time DESC LIMIT ?"
        cursor.execute(sql, (query, effective_limit))
        results = [dict(row) for row in cursor.fetchall()]
    else:
        session_snippets = {}
        fts_sql = "SELECT session_id, snippet(search_index, 2, '>', '<', '...', 10) as highlight FROM search_index WHERE search_index MATCH ? ORDER BY rank"
        cursor.execute(fts_sql, (query,))
        fts_results = cursor.fetchall()
        
        session_snippets = {r['session_id']: r['highlight'] for r in fts_results}
        session_ids = list(session_snippets.keys())
        
        if not session_ids:
            click.echo("No results found.")
            conn.close()
            return
            
        params = list(session_ids)
        where_clauses = [f"id IN ({','.join('?' for _ in session_ids)})"]

        if source:
            where_clauses.append("source = ?")
            params.append(source)
            
        sql = "SELECT * FROM sessions WHERE " + " AND ".join(where_clauses) + " ORDER BY create_time DESC LIMIT ?"
        params.append(effective_limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        for row in rows:
            row_dict = dict(row)
            row_dict['highlight'] = session_snippets.get(row['id'], '')
            results.append(row_dict)

    if output == 'json': click.echo(json.dumps(results, ensure_ascii=False, indent=2))
    elif output == 'ndjson':
        for r in results: click.echo(json.dumps(r, ensure_ascii=False))
    elif output == 'plain':
        if mode == 'message':
            for r in results: click.echo(f"[{r['session_title']}] {r['role']}: {r['content'][:100]}...")
        else:
            for r in results: click.echo(f"{r['id']} | {r['title']}")
    else: # show
        term_width = shutil.get_terminal_size().columns
        rule_len = min(term_width, 80)
        if not results: click.echo("No results found.")
        for r in results:
            dt = datetime.fromtimestamp(r['create_time']).strftime('%Y-%m-%d %H:%M')
            if mode == 'message':
                click.secho(f"[{dt}] ", dim=True, nl=False)
                click.secho(f"【{r['session_title']}】", fg='yellow', nl=False)
                role = r['role'].capitalize(); role_color = 'blue' if r['role'] == 'user' else 'green'
                click.secho(f" -> {role}", fg=role_color, bold=True)
                content = r['highlight'].replace('>', '\033[1;32m').replace('<', '\033[0m')
                click.echo(f"  └── {content}")
            else: # snippet or session
                click.secho(f"[{dt}] ", dim=True, nl=False)
                click.secho(f"【{r.get('source', 'N/A')}】", fg='yellow', nl=False)
                click.secho(f" {r['title']}", bold=True)
                hl = r['highlight'].replace('>', '\033[1;32m').replace('<', '\033[0m')
                click.echo(f"  └── Snippet: {hl}")
                if mode == 'session':
                    click.secho("  └─ Full Conversation:", dim=True)
                    # Implementation for session mode...
            click.secho("-" * rule_len, dim=True)
    conn.close()

@cli.command()
def doctor():
    """Check DB health and statistics."""
    if not os.path.exists(DB_PATH): click.secho("❌ DB not found.", fg='red'); return
    conn = get_db(); cursor = conn.cursor()
    s_count = cursor.execute("SELECT count(*) FROM sessions").fetchone()[0]
    m_count = cursor.execute("SELECT count(*) FROM messages").fetchone()[0]
    size = os.path.getsize(DB_PATH) / 1024 / 1024
    click.echo(f"DB: {DB_PATH}\nSize: {size:.2f} MB\nSessions: {s_count}\nMessages: {m_count}")
    click.secho("✅ Integrity check passed.", fg='green'); conn.close()

@cli.command()
def schema():
    """Show database schema."""
    conn = get_db(); cursor = conn.cursor()
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in tables:
        click.secho(f"\nTable: {t['name']}", bold=True, fg='cyan')
        cols = cursor.execute(f"PRAGMA table_info({t['name']})").fetchall()
        for c in cols: click.echo(f"  - {c['name']} ({c['type']})")
    conn.close()

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'na', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    global_manifest_path = Path("skills/concept-cli-factory/references/features-manifest.json")
    local_manifest_path = Path(__file__).parent / "manifest.json"

    if not global_manifest_path.exists():
        click.secho("❌ Global Features Manifest not found.", fg='red'); return
    if not local_manifest_path.exists():
        click.secho("❌ Local Features Manifest not found.", fg='red'); return

    with open(global_manifest_path, 'r') as f: global_features = json.load(f)
    with open(local_manifest_path, 'r') as f: local_features_data = json.load(f)
    local_feature_map = {f['id']: f for f in local_features_data}

    click.secho("\n🚀 AI-Chat CLI Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 90)
    
    sorted_global_features = sorted(global_features, key=lambda x: x.get('rank', 0), reverse=True)

    for g_feat in sorted_global_features:
        f_id = g_feat['id']
        f_status_display, f_color, dim = "⚪ OPT", "yellow", False
        if f_id in local_feature_map:
            l_feat = local_feature_map[f_id]
            if l_feat['status'] == 'implemented': f_status_display, f_color = "✅ OK", "green"
            elif l_feat['status'] == 'na': f_status_display, f_color, dim = "🚫 N/A", "red", True
        elif g_feat.get('status') == 'mandatory': f_status_display, f_color = "❌ MISSING", "red"
        
        if status:
            current_status_key = f_status_display.split(" ")[1].lower()
            if status != current_status_key: continue
        
        st_styled = click.style(f_status_display, fg=f_color, dim=dim)
        st_padding = " " * (10 - get_display_width(f_status_display))
        feat_label = pad_cjk(g_feat['label'], 20)
        click.echo(f" {st_styled}{st_padding} | {feat_label} | {g_feat['description']}")
    click.echo("")

@cli.group(name='config')
def config_cmd():
    """Manage persistent defaults."""
    pass

@config_cmd.command(name='set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    cfg = ConfigManager.load()
    if key == 'limit':
        try: value = int(value)
        except ValueError: click.secho(f"❌ Invalid value for limit.", fg='red'); return
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ Set {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False)
def config_get(key):
    cfg = ConfigManager.load()
    click.echo(json.dumps(cfg, indent=2) if not key else cfg.get(key, "Not set"))

@cli.group(name='completion')
def completion_cmd():
    """Manage shell completion scripts."""
    pass

@completion_cmd.command(name='show')
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
def completion_show(shell):
    shell = shell or os.path.basename(os.environ.get('SHELL', 'bash'))
    prog_name = "ac"
    env = os.environ.copy()
    env[f'_{prog_name.upper()}_COMPLETE'] = f'{shell}_source'
    result = subprocess.run([sys.executable, sys.argv[0]], env=env, capture_output=True, text=True)
    click.echo(result.stdout)

def _load_dynamic_commands():
    try:
        if not __package__:
            sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
        from commands.common.dynamic_cli_factory import create_table_search_command
        tables_to_expose = ['sessions', 'messages']
        for table in tables_to_expose:
            command = create_table_search_command(DB_PATH, table)
            cli.add_command(command)
    except (ImportError, ModuleNotFoundError) as e:
        click.secho(f"Warning: Dynamic commands could not be loaded: {e}", fg='yellow')

_load_dynamic_commands()

try:
    from commands.query import create_query_cmd, create_commands_from_config
    lexicon_cmd = create_query_cmd(
        db_path=DB_PATH,
        table_prefix="",
        cmd_name="query",  # 可选，默认从文件名生成
        help_text="ai chat dialogue query command"
    )
    cli.add_command(lexicon_cmd)

except ImportError as e:
    click.secho(f"Warning: Could not load 'query' command: {e}", fg='yellow')
if __name__ == '__main__':
    cli()
