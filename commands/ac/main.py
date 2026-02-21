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
    # Enable WAL mode for performance
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

# --- Utility functions for CJK character display width ---
def get_display_width(s):
    """Calculate the actual display width of a string (considering CJK characters)."""
    width = 0
    for char in s:
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width

def pad_cjk(s, width):
    """Pad string considering CJK width."""
    d_width = get_display_width(s)
    return s + " " * max(0, width - d_width)
# --- End of Utility functions ---


# --- Dynamic Completers ---
def source_completer(ctx, param, incomplete):
    """Dynamically complete --source argument."""
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
        click.confirm("Are you sure you want to drop all data and rebuild the database?", abort=True)
        click.echo("Dropping all tables...")
        cursor.execute("DROP TABLE IF EXISTS sessions")
        cursor.execute("DROP TABLE IF EXISTS messages")
        cursor.execute("DROP TABLE IF EXISTS search_index")
        click.secho("All tables dropped.", fg='yellow')
    
    # Initialize Schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        source TEXT,
        title TEXT,
        create_time REAL,
        message_count INTEGER,
        file_mtime REAL
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        create_time REAL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )""")
    # Schema upgrade: Add message_id to link back to the exact message
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
        session_id UNINDEXED,
        message_id UNINDEXED,
        title,
        content,
        tokenize='unicode61'
    )""")
    conn.commit()

    data_path = Path(data_dir)
    if not data_path.exists():
        click.secho(f"❌ Data directory {data_dir} not found.", fg='red')
        return

    files = list(data_path.glob("*.json"))
    new_count = 0
    with click.progressbar(files, label="Syncing logs") as bar:
        for f_path in bar:
            mtime = f_path.stat().st_mtime
            # Check if sync needed
            cursor.execute("SELECT file_mtime FROM sessions WHERE id = ?", (f_path.stem,))
            row = cursor.fetchone()
            if row and row['file_mtime'] >= mtime and not rebuild:
                continue

            try:
                with open(f_path, 'r') as f:
                    data = json.load(f)
                
                sid = data.get('id', f_path.stem)
                source = data.get('source', 'unknown')
                title = data.get('title', 'Untitled')
                ctime = data.get('create_time', mtime)
                msgs = data.get('messages', [])

                # Atomic update
                cursor.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                cursor.execute("DELETE FROM search_index WHERE session_id = ?", (sid,))
                
                cursor.execute("""
                INSERT OR REPLACE INTO sessions (id, source, title, create_time, message_count, file_mtime)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (sid, source, title, ctime, len(msgs), mtime))

                for m in msgs:
                    content = m.get('content', '')
                    if isinstance(content, list):
                        content = "\n".join([item.get('text', '') for item in content if isinstance(item, dict) and 'text' in item])
                    
                    cursor.execute("""
                    INSERT INTO messages (session_id, role, content, create_time)
                    VALUES (?, ?, ?, ?)
                    """, (sid, m['role'], content, m.get('create_time')))
                    message_id = cursor.lastrowid
                    
                    # Indexing with message_id
                    cursor.execute("""
                    INSERT INTO search_index (session_id, message_id, title, content)
                    VALUES (?, ?, ?, ?)
                    """, (sid, message_id, title, content))
                
                new_count += 1
            except Exception as e:
                click.echo(f"Error parsing {f_path.name}: {e}")
    
    conn.commit()
    conn.close()
    if rebuild:
        click.secho(f"✅ Rebuild complete. {new_count} files processed.", fg='green')
    else:
        click.secho(f"✅ Sync complete. {new_count} files updated.", fg='green')


@cli.command()
@click.option('--data-dir', default="sources/ai-chat/conversations", help='Directory containing conversation JSONs')
@click.option('--rebuild', is_flag=True, help='Drop all tables and rebuild the database from scratch.')
def sync(data_dir, rebuild):
    """Incremental sync from JSON logs to SQLite. Use --rebuild to start fresh."""
    conn = get_db()
    cursor = conn.cursor()

    if rebuild:
        click.confirm("Are you sure you want to drop all data and rebuild the database?", abort=True)
        click.echo("Dropping all tables...")
        cursor.execute("DROP TABLE IF EXISTS sessions")
        cursor.execute("DROP TABLE IF EXISTS messages")
        cursor.execute("DROP TABLE IF EXISTS search_index")
        click.secho("All tables dropped.", fg='yellow')
    
    # Initialize Schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        source TEXT,
        title TEXT,
        create_time REAL,
        message_count INTEGER,
        file_mtime REAL
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        create_time REAL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )""")
    # Schema upgrade: Add message_id to link back to the exact message
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
        session_id UNINDEXED,
        message_id UNINDEXED,
        title,
        content,
        tokenize='unicode61'
    )""")
    conn.commit()

    data_path = Path(data_dir)
    if not data_path.exists():
        click.secho(f"❌ Data directory {data_dir} not found.", fg='red')
        return

    files = list(data_path.glob("*.json"))
    new_count = 0
    with click.progressbar(files, label="Syncing logs") as bar:
        for f_path in bar:
            mtime = f_path.stat().st_mtime
            # Check if sync needed
            cursor.execute("SELECT file_mtime FROM sessions WHERE id = ?", (f_path.stem,))
            row = cursor.fetchone()
            if row and row['file_mtime'] >= mtime and not rebuild:
                continue

            try:
                with open(f_path, 'r') as f:
                    data = json.load(f)
                
                sid = data.get('id', f_path.stem)
                source = data.get('source', 'unknown')
                title = data.get('title', 'Untitled')
                ctime = data.get('create_time', mtime)
                msgs = data.get('messages', [])

                # Atomic update
                cursor.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                cursor.execute("DELETE FROM search_index WHERE session_id = ?", (sid,))
                
                cursor.execute("""
                INSERT OR REPLACE INTO sessions (id, source, title, create_time, message_count, file_mtime)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (sid, source, title, ctime, len(msgs), mtime))

                for m in msgs:
                    content = m.get('content', '')
                    if isinstance(content, list):
                        content = "\n".join([item.get('text', '') for item in content if isinstance(item, dict) and 'text' in item])
                    
                    cursor.execute("""
                    INSERT INTO messages (session_id, role, content, create_time)
                    VALUES (?, ?, ?, ?)
                    """, (sid, m['role'], content, m.get('create_time')))
                    message_id = cursor.lastrowid
                    
                    # Indexing with message_id
                    cursor.execute("""
                    INSERT INTO search_index (session_id, message_id, title, content)
                    VALUES (?, ?, ?, ?)
                    """, (sid, message_id, title, content))
                
                new_count += 1
            except Exception as e:
                click.echo(f"Error parsing {f_path.name}: {e}")
    
    conn.commit()
    conn.close()
    if rebuild:
        click.secho(f"✅ Rebuild complete. {new_count} files processed.", fg='green')
    else:
        click.secho(f"✅ Sync complete. {new_count} files updated.", fg='green')

# --- Dynamic Search Implementation ---
class RangeParser:
    """Parse numeric ranges like '2', '1-', '1-5', '-20', '10,20'."""
    @staticmethod
    def to_sql(col_name, range_str):
        if not range_str: return None, []
        range_str = str(range_str).strip()
        
        if ',' in range_str:
            parts = range_str.split(',')
            start, end = parts[0].strip(), parts[1].strip()
            if start and end:
                try: return f"CAST({col_name} AS REAL) BETWEEN ? AND ?", [float(start), float(end)];
                except ValueError: return None, []
        if '-' in range_str:
            parts = range_str.split('-')
            start, end = parts[0].strip(), parts[1].strip()
            if start and end:
                try: return f"CAST({col_name} AS REAL) BETWEEN ? AND ?", [float(start), float(end)];
                except ValueError: return None, []
            elif start:
                try: return f"CAST({col_name} AS REAL) >= ?", [float(start)];
                except ValueError: return None, []
            elif end:
                try: return f"CAST({col_name} AS REAL) <= ?", [float(end)];
                except ValueError: return None, []
        try:
            return f"{col_name} = ?", [float(range_str)]
        except ValueError:
            return f"{col_name} LIKE ?", [f'%{range_str}%']

class DynamicOptions:
    def __init__(self, db_path, table_name='sessions'):
        self.db_path = db_path
        self.table_name = table_name
        self.numeric_types = ['INT', 'INTEGER', 'REAL', 'FLOAT', 'DOUBLE']
        self.excluded_fields = ['id', 'title', 'file_mtime']

    def get_schema(self):
        if not os.path.exists(self.db_path): return []
        conn = sqlite3.connect(self.db_path); cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({self.table_name})")
        schema = cursor.fetchall(); conn.close()
        return schema

    def generate_options(self):
        options = []
        for col in self.get_schema():
            col_name, col_type = col[1], col[2].upper()
            if col_name in self.excluded_fields: continue
            
            param_name = col_name.replace('_', '-')
            if any(t in col_type for t in self.numeric_types):
                options.append(click.Option([f'--{param_name}'], help=f"Filter by {col_name} (e.g., 1-5, 10,20).", type=str))
            else:
                options.append(click.Option([f'--{param_name}'], help=f"Filter by {col_name} (text).", type=str, shell_complete=source_completer if col_name == 'source' else None))
        return options

    def add_to_command(self, command):
        for option in self.generate_options(): command.params.append(option)
        return command

def format_output(row, mode, fields=None):
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    
    if mode == 'json': click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'ndjson': click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        click.echo(" | ".join([str(data.get(k, '')) for k in (fields or data.keys())]))
    else: # show
        title = data.get('title', 'No Title')
        sid = data.get('session_id', data.get('id'))
        
        if fields:
            for k in fields:
                val = data.get(k, 'N/A')
                if 'time' in k and isinstance(val, (int, float)): val = datetime.fromtimestamp(val).strftime('%Y-%m-%d %H:%M')
                click.echo(f"[bold]{k}[/bold]: {val}")
            click.echo("-" * 20)
        else:
            ts = datetime.fromtimestamp(data['create_time']).strftime('%Y-%m-%d %H:%M')
            content_preview = data.get('content', '').replace('\n', ' ').strip()
            if get_display_width(content_preview) > 80: content_preview = ''.join(list(content_preview)[:50]) + "..."
            click.secho(f"▶ {title} ", fg='cyan', nl=False); click.secho(f"({ts})", fg='green')
            click.echo(f"  ID: {sid}")
            if 'content' in data: click.echo(f"  Preview: {content_preview}")

@click.command(name="search")
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), help='Output mode')
@click.option('--field', '-f', multiple=True, help='Select specific fields for output')
@click.option('--limit', type=int, help='Maximum number of results to return')
@click.option('--logic', type=click.Choice(['AND', 'OR']), default='AND', help='Logic to combine filters')
@click.option('--stdin', is_flag=True, help='Read query from stdin')
@click.pass_context
def search_cmd(ctx, query, output, field, limit, logic, stdin, **kwargs):
    """Search conversation history with dynamic, schema-aware filters."""
    cfg = ConfigManager.load()
    output, limit = output or cfg['output'], limit if limit is not None else cfg.get('limit', 10)
    if stdin or query == '-': query = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    if not query: click.echo(ctx.get_help()); return

    conn = get_db(); cursor = conn.cursor()
    base_sql = "FROM sessions s JOIN search_index si ON s.id = si.session_id"
    where_clauses, params = ["si.search_index MATCH ?"], [query]
    
    processed_kwargs = {k.replace('-', '_'): v for k, v in kwargs.items()}
    for key, value in processed_kwargs.items():
        if value is not None:
            c, p = RangeParser.to_sql(f"s.{key}", value)
            if c: where_clauses.append(c); params.extend(p)

    if len(where_clauses) > 1:
        fts_clause = where_clauses.pop(0)
        sql = f"SELECT s.*, si.content, si.rank {base_sql} WHERE {fts_clause} AND ({f' {logic} '.join(where_clauses)})"
    else:
        sql = f"SELECT s.*, si.content, si.rank {base_sql} WHERE {where_clauses[0]}"
        
    sql += " ORDER BY si.rank DESC LIMIT ?"
    params.append(limit)
    
    try:
        cursor.execute(sql, params)
        results = [dict(row) for row in cursor.fetchall()]
        if not results: click.secho("No results found.", fg='yellow'); return
        for row in results: format_output(row, output, field)
    except sqlite3.OperationalError as e:
        click.secho(f"DB Error: {e}\nQuery: {sql}\nParams: {params}", fg='red')
    conn.close()

cli.add_command(search_cmd)
DynamicOptions(DB_PATH).add_to_command(search_cmd)

@cli.command()
def doctor():
    """Check DB health and statistics."""
    if not os.path.exists(DB_PATH):
        click.secho("❌ Database not found. Run 'ac sync' first.", fg='red')
        return
    
    conn = get_db()
    cursor = conn.cursor()
    s_count = cursor.execute("SELECT count(*) FROM sessions").fetchone()[0]
    m_count = cursor.execute("SELECT count(*) FROM messages").fetchone()[0]
    size = os.path.getsize(DB_PATH) / 1024 / 1024
    
    click.echo(f"Database: {DB_PATH}")
    click.echo(f"Size:     {size:.2f} MB")
    click.echo(f"Sessions: {s_count}")
    click.echo(f"Messages: {m_count}")
    click.secho("✅ Integrity check passed.", fg='green')
    conn.close()

@cli.command()
def schema():
    """Show database schema."""
    conn = get_db()
    cursor = conn.cursor()
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in tables:
        click.secho(f"\nTable: {t['name']}", bold=True, fg='cyan')
        cols = cursor.execute(f"PRAGMA table_info({t['name']})").fetchall()
        for c in cols:
            click.echo(f"  - {c['name']} ({c['type']})")
    conn.close()

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'na', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    global_manifest_path = Path("skills/concept-cli-factory/references/features-manifest.json")
    local_manifest_path = Path(__file__).parent / "manifest.json"

    if not global_manifest_path.exists():
        click.secho("❌ Global Features Manifest not found.", fg='red')
        return
    if not local_manifest_path.exists():
        click.secho("❌ Local Features Manifest not found.", fg='red')
        return

    with open(global_manifest_path, 'r') as f:
        global_features = json.load(f)
    with open(local_manifest_path, 'r') as f:
        local_features_data = json.load(f)
        local_feature_map = {f['id']: f for f in local_features_data} # Assuming local_features_data is a list of features

    click.secho(f"\n🚀 AI-Chat CLI Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 90)
    
    # Sort global features by rank (highest first)
    sorted_global_features = sorted(global_features, key=lambda x: x.get('rank', 0), reverse=True)

    for g_feat in sorted_global_features:
        f_id = g_feat['id']
        f_status_display = "⚪ OPT" # Default to optional
        f_color = "yellow"
        dim = False

        if f_id in local_feature_map:
            l_feat = local_feature_map[f_id]
            if l_feat['status'] == 'implemented':
                f_status_display = "✅ OK"
                f_color = "green"
            elif l_feat['status'] == 'na':
                f_status_display = "🚫 N/A"
                f_color = "red"
                dim = True
        else:
            if g_feat.get('status') == 'mandatory':
                f_status_display = "❌ MISSING"
                f_color = "red"
            elif g_feat.get('status') == 'recommended':
                f_status_display = "⚪ OPT" # Explicitly optional for recommended not implemented
                f_color = "yellow"
            elif g_feat.get('status') == 'optional':
                f_status_display = "⚪ OPT"
                f_color = "yellow"

        # Filter if --status option is used
        if status:
            if status == 'ok' and f_status_display != "✅ OK": continue
            if status == 'na' and f_status_display != "🚫 N/A": continue
            if status == 'miss' and f_status_display != "❌ MISSING": continue
            if status == 'opt' and f_status_display != "⚪ OPT": continue
        
        st_styled = click.style(f_status_display, fg=f_color, dim=dim)
        st_padding = " " * (10 - get_display_width(f_status_display))
        feat_label = pad_cjk(g_feat['label'], 20)
        
        click.echo(f" {st_styled}{st_padding} | {feat_label} | {g_feat['description']}")
    click.echo("")

# -- Config Commands --
# Must be defined before config_cmd uses it
def config_key_complete(ctx, param, incomplete):
    keys = list(ConfigManager.DEFAULT_CONFIG.keys())
    return [k for k in keys if k.startswith(incomplete)]

@cli.group(name='config') # Directly registers as 'config'
def config_cmd():
    """Manage persistent defaults."""
    pass

@config_cmd.command(name='set')
@click.argument('key', shell_complete=config_key_complete)
@click.argument('value')
def config_set(key, value):
    cfg = ConfigManager.load()
    if key == 'limit':
        try:
            value = int(value)
        except ValueError:
            click.secho(f"❌ Invalid value for limit: {value}. Must be an integer.", fg='red')
            return
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ Set {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False, shell_complete=config_key_complete)
def config_get(key):
    cfg = ConfigManager.load()
    if key:
        click.echo(cfg.get(key, "Not set"))
    else:
        click.echo(json.dumps(cfg, indent=2))

# -- Completion Command --
@cli.group(name='completion')
def completion_cmd():
    """Manage shell completion scripts."""
    pass

@completion_cmd.command(name='show')
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
def completion_show(shell):
    """Show the completion script for the specified shell."""
    if not shell:
        shell = os.path.basename(os.environ.get('SHELL', 'bash'))
    
    prog_name = "ac"
    
    # Click's completion generation is triggered by environment variables.
    # We spawn a new process for the CLI itself with the right env var.
    env = os.environ.copy()
    env[f'_{prog_name.upper()}_COMPLETE'] = f'{shell}_source'
    
    result = subprocess.run([prog_name], env=env, capture_output=True, text=True, shell=False)
    click.echo(result.stdout)


@completion_cmd.command(name='install')
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
def completion_install(shell):
    """Install the completion script for the specified shell."""
    if not shell:
        shell = os.path.basename(os.environ.get('SHELL', 'bash'))

    prog_name = "ac"
    rc_file = None
    install_line = f'eval "$(_{prog_name.upper()}_COMPLETE={shell}_source {prog_name})"'

    if shell == 'bash':
        rc_file = os.path.expanduser("~/.bashrc")
    elif shell == 'zsh':
        rc_file = os.path.expanduser("~/.zshrc")
    elif shell == 'fish':
        fish_completion_path = os.path.expanduser(f"~/.config/fish/completions/{prog_name}.fish")
        if not os.path.exists(os.path.dirname(fish_completion_path)):
            os.makedirs(os.path.dirname(fish_completion_path))
        
        env = os.environ.copy()
        env[f'_{prog_name.upper()}_COMPLETE'] = 'fish_source'
        
        with open(fish_completion_path, 'w') as f:
            result = subprocess.run([prog_name], env=env, capture_output=True, text=True)
            f.write(result.stdout)
            
        click.secho(f"✅ Installed completion for fish at {fish_completion_path}", fg='green')
        click.echo("Please restart your shell to activate.")
        return

    if not rc_file or not os.path.exists(rc_file):
        click.secho(f"Could not find shell config file for {shell}.", fg='red')
        return

    with open(rc_file, 'r+') as f:
        content = f.read()
        if install_line in content:
            click.secho(f"✅ Completion already installed in {rc_file}", fg='yellow')
            return
        
        f.write(f"\n# {prog_name} completion\n")
        f.write(f"{install_line}\n")
    
    click.secho(f"✅ Installed completion in {rc_file}", fg='green')
    click.echo("Please restart your shell or run:")
    click.echo(f"  source {rc_file}")

def main():
    """Main entry point for the CLI."""
    try:
        # The path to the factory needs to be correct relative to how the script is run.
        # Assuming it's run from the project root, this relative import might fail.
        # A more robust solution is to manage python paths. For now, let's adjust.
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
        from commands.common.dynamic_cli_factory import create_table_search_command
        
        tables_to_expose = ['sessions', 'messages']
        for table in tables_to_expose:
            command = create_table_search_command(DB_PATH, table)
            cli.add_command(command)
    except ImportError as e:
        click.secho(f"Warning: Could not import subcommand factory: {e}. Dynamic commands are unavailable.", fg='yellow')
    
    cli()

if __name__ == '__main__':
    main()
