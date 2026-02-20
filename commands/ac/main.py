import click
import json
import sqlite3
import os
import sys
import time
from pathlib import Path
from datetime import datetime

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
def search(query, output, limit):
    """Search conversation history."""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    
    # Prioritize command-line limit, then config limit, then hardcoded default
    effective_limit = limit if limit is not None else cfg.get('limit', 10)
    
    conn = get_db()
    cursor = conn.cursor()
    
    processed_rows = []

    if not query:
        cursor.execute("SELECT * FROM sessions ORDER BY create_time DESC LIMIT ?", (effective_limit,))
        rows = cursor.fetchall()
        processed_rows = [dict(r) for r in rows]
    else:
        # Step 1: Search FTS5 and get session_ids and snippets
        fts_sql = """
        SELECT session_id, snippet(search_index, 2, '>', '<', '...', 10) as highlight, rank
        FROM search_index
        WHERE search_index MATCH ?
        ORDER BY rank
        LIMIT ?
        """
        cursor.execute(fts_sql, (query, effective_limit))
        fts_results = cursor.fetchall()

        # Collect unique session_ids and map snippets
        session_snippets = {}
        # Use an ordered list to preserve FTS rank order
        ranked_session_ids = [] 
        for r in fts_results:
            if r['session_id'] not in session_snippets: # Only take the first snippet for a session
                ranked_session_ids.append(r['session_id'])
                session_snippets[r['session_id']] = r['highlight']

        if not ranked_session_ids:
            click.echo("No results found.")
            conn.close()
            return

        # Step 2: Fetch full session details in the same order
        session_placeholders = ','.join('?' for _ in ranked_session_ids)
        sessions_sql = f"SELECT * FROM sessions WHERE id IN ({session_placeholders})"
        cursor.execute(sessions_sql, ranked_session_ids)
        session_rows = cursor.fetchall()

        # Create a map for quick lookup
        session_map = {row['id']: dict(row) for row in session_rows}

        # Combine session data with snippets, preserving FTS rank order
        for sid in ranked_session_ids:
            if sid in session_map:
                row_dict = session_map[sid]
                row_dict['highlight'] = session_snippets.get(sid, '')
                processed_rows.append(row_dict)
    
    # Existing output formatting logic
    if output == 'json':
        click.echo(json.dumps(processed_rows, ensure_ascii=False, indent=2))
    elif output == 'ndjson':
        for r in processed_rows:
            click.echo(json.dumps(r, ensure_ascii=False))
    elif output == 'plain':
        for r in processed_rows:
            click.echo(f"{r['id']} | {r['title']}")
    else: # show
        for r in processed_rows:
            dt = datetime.fromtimestamp(r['create_time']).strftime('%Y-%m-%d %H:%M')
            click.secho(f"[{dt}] ", dim=True, nl=False)
            click.secho(f"【{r['source']}】", fg='yellow', nl=False)
            click.secho(f" {r['title']}", bold=True)
            if 'highlight' in r.keys() and r['highlight']:
                hl = r['highlight'].replace('>', '\033[32m').replace('<', '\033[0m')
                click.echo(f"  └── Snippet: {hl}")
            click.echo("-" * 40)
    
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
def features():
    """List implemented and recommended features."""
    manifest_path = Path(__file__).parent / "manifest.json"
    if not manifest_path.exists():
        click.secho("❌ manifest.json not found.", fg='red')
        return
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    click.secho(f"\n🚀 AI-Chat CLI Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 90)
    
    for feat in manifest:
        st = feat['status']
        st_styled = click.style("✅ OK" if st == 'implemented' else "⚪ OPT", fg='green' if st == 'implemented' else 'yellow')
        click.echo(f" {st_styled:<18} | {feat['label']:<20} | {feat['description']}")
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


if __name__ == '__main__':
    cli()
