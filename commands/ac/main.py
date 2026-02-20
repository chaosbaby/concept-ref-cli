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
def sync(data_dir):
    """Incremental sync from JSON logs to SQLite."""
    conn = get_db()
    cursor = conn.cursor()
    
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
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
        session_id UNINDEXED,
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
            if row and row['file_mtime'] >= mtime:
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
                    
                    # Indexing
                    cursor.execute("""
                    INSERT INTO search_index (session_id, title, content)
                    VALUES (?, ?, ?)
                    """, (sid, title, content))
                
                new_count += 1
            except Exception as e:
                click.echo(f"Error parsing {f_path.name}: {e}")
    
    conn.commit()
    conn.close()
    click.secho(f"✅ Sync complete. {new_count} files updated.", fg='green')

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'plain', 'json', 'ndjson']), help='Output mode')
@click.option('--limit', type=int, help='Maximum number of results to return')
@click.option('--source', shell_complete=source_completer, help='Filter by source')
@click.option('--stdin', is_flag=True, help='Read query from stdin')
@click.option('--full', is_flag=True, help='Display full conversation text instead of snippet.')
def search(query, output, limit, source, stdin, full):
    """Search conversation history."""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    
    if stdin or query == '-':
        if not sys.stdin.isatty():
            query = sys.stdin.read().strip()
        else:
            click.secho("Reading from stdin... (Press Ctrl+D to finish)", dim=True)
            query = sys.stdin.read().strip()

    effective_limit = limit if limit is not None else cfg.get('limit', 10)
    
    conn = get_db()
    cursor = conn.cursor()
    
    processed_rows = []
    
    # Parameters and query parts
    params = []
    where_clauses = []
    
    # FTS query to get session_ids
    session_snippets = {}
    if query:
        fts_sql = "SELECT session_id, snippet(search_index, 2, '>', '<', '...', 10) as highlight FROM search_index WHERE search_index MATCH ? ORDER BY rank"
        cursor.execute(fts_sql, (query,))
        fts_results = cursor.fetchall()
        
        session_snippets = {r['session_id']: r['highlight'] for r in fts_results}
        session_ids = list(session_snippets.keys())
        
        if not session_ids:
            click.echo("No results found.")
            conn.close()
            return
            
        where_clauses.append(f"id IN ({','.join('?' for _ in session_ids)})")
        params.extend(session_ids)

    # Source filter
    if source:
        where_clauses.append("source = ?")
        params.append(source)
        
    # Construct the final query
    sql = "SELECT * FROM sessions"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    
    sql += " ORDER BY create_time DESC LIMIT ?"
    params.append(effective_limit)
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
    # Re-add snippets and create processed_rows
    for row in rows:
        row_dict = dict(row)
        if query:
            row_dict['highlight'] = session_snippets.get(row['id'], '')
        processed_rows.append(row_dict)
    
    # ... (output formatting)
    if output == 'json':
        click.echo(json.dumps(processed_rows, ensure_ascii=False, indent=2))
    elif output == 'ndjson':
        for r in processed_rows:
            click.echo(json.dumps(r, ensure_ascii=False))
    elif output == 'plain':
        for r in processed_rows:
            click.echo(f"{r['id']} | {r['title']}")
    else: # show
        term_width = shutil.get_terminal_size().columns
        for r in processed_rows:
            dt = datetime.fromtimestamp(r['create_time']).strftime('%Y-%m-%d %H:%M')
            click.secho(f"[{dt}] ", dim=True, nl=False)
            click.secho(f"【{r['source']}】", fg='yellow', nl=False)
            click.secho(f" {r['title']}", bold=True)
            
            rule_len = min(term_width, 80)

            if full:
                # New Full-Text Logic
                click.secho("  └─ Full Conversation:", dim=True)
                cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY create_time ASC", (r['id'],))
                messages = cursor.fetchall()
                for i, msg in enumerate(messages):
                    role = msg['role'].capitalize()
                    role_color = 'blue' if msg['role'] == 'user' else 'green'
                    
                    is_last = i == len(messages) - 1
                    
                    click.secho(f"    ╭─ {role}", fg=role_color, bold=True)
                    
                    content = msg['content']
                    content = re.sub(r'\*\*(.*?)\*\*', r'\033[1m\1\033[0m', content)
                    content = re.sub(r'`(.*?)`', r'\033[36m\1\033[0m', content)
                    
                    wrapped_text = textwrap.fill(content, width=term_width - 8, initial_indent='    │ ', subsequent_indent='    │ ', break_long_words=False, replace_whitespace=False)
                    click.echo(wrapped_text)
                    if is_last:
                        click.echo("    ╰" + "─" * (rule_len - 5))

            elif 'highlight' in r.keys() and r['highlight']:
                # Existing Snippet Logic
                hl = r['highlight']
                # Markdown-like highlighting
                hl = re.sub(r'\*\*(.*?)\*\*', r'\033[1m\1\033[0m', hl) # Bold
                hl = re.sub(r'`(.*?)`', r'\033[36m\1\033[0m', hl)      # Code
                # FTS5 Highlight markers
                hl = hl.replace('>', '\033[1;32m').replace('<', '\033[0m')
                
                prefix = "  └── Snippet: "
                click.echo(f"{prefix}{hl}")
            
            # Simple horizontal rule
            click.secho("-" * rule_len, dim=True)
    
    conn.close()

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

if __name__ == '__main__':
    cli()
