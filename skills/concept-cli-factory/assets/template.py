import click
import json
import sqlite3
import os
import sys
import re
from pathlib import Path

# Standard DB path
DB_PATH = os.path.expanduser("~/.{{ tool_id }}.db")
CONFIG_PATH = os.path.expanduser("~/.{{ tool_id }}.json")

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
            elif start:
                return f"CAST({col_name} AS INTEGER) >= ?", [int(start)]
            elif end:
                return f"CAST({col_name} AS INTEGER) <= ?", [int(end)]
        try:
            return f"CAST({col_name} AS INTEGER) = ?", [int(range_str)]
        except ValueError:
            return None, []

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def format_output(row, mode, fields=None):
    data = dict(row)
    if fields:
        data = {k: v for k, v in data.items() if k in fields}
    
    if mode in ['json', 'stream']:
        click.echo(json.dumps(data, ensure_ascii=False))
    elif mode == 'plain':
        click.echo(" ".join([str(v) for k, v in data.items() if not k.startswith('_')]))
    else: # 'view' or default
        pk = data.get('pk') or list(data.values())[0]
        desc = data.get('desc') or " | ".join([str(v) for k,v in data.items() if k != 'pk' and not k.startswith('_')])
        click.secho(f"【{pk}】", fg='cyan', nl=False)
        click.echo(f" {desc}")
        if '_joined' in data:
            for item in data['_joined']:
                j_pk = item.get('pk') or list(item.values())[0]
                click.echo(click.style(f"  └── [Joined] ", fg='yellow', dim=True) + f"【{j_pk}】")

def get_input_stream(query, stdin_flag):
    if query == '-' or stdin_flag:
        for line in sys.stdin: yield line.strip()
    elif query: yield query

def tag_complete(ctx, param, incomplete):
    # Template logic: needs to query actual tags from DB
    return []

def config_key_complete(ctx, param, incomplete):
    keys = list(ConfigManager.DEFAULT_CONFIG.keys())
    return [k for k in keys if k.startswith(incomplete)]

@click.group()
def cli():
    """{{ description }}"""
    pass

@cli.command()
@click.argument('query', required=False)
@click.option('--stdin', is_flag=True, help='Read from stdin')
@click.option('--output', '-o', type=click.Choice(['view', 'json', 'plain', 'stream']), help='Output mode')
@click.option('--field', '-f', multiple=True, help='Filter specific fields')
@click.option('--rank', help='Rank filter (e.g. 1000-, 1-500)')
@click.option('--len', 'length', help='Length filter (e.g. 2, 4-)')
@click.option('--tag', 'tags', multiple=True, help='Include tags')
@click.option('--no-tag', 'no_tags', multiple=True, help='Exclude tags')
@click.option('--limit', type=int)
def search(query, stdin, output, field, rank, length, tags, no_tags, limit):
    """Search with standardized input/output and multi-dim filters."""
    cfg = ConfigManager.load()
    output = output or cfg.get('output', 'view')
    limit = limit or cfg.get('limit', 20)
    rank = rank or cfg.get('default_rank')
    length = length or cfg.get('default_len')
    
    if not tags and cfg.get('default_tag'):
        tags = [t.strip() for t in cfg.get('default_tag').split(',') if t.strip()]
    if not no_tags and cfg.get('default_no_tag'):
        no_tags = [t.strip() for t in cfg.get('default_no_tag').split(',') if t.strip()]

    conn = get_db(); cursor = conn.cursor()
    if is_headless() and output == 'view': output = 'stream'
        
    for q in get_input_stream(query, stdin):
        if not q: continue
        sql = "SELECT * FROM entries WHERE pk MATCH ?"
        params = [f"{q}*"]
        
        if rank:
            c, p = RangeParser.to_sql('rank', rank)
            if c: sql += f" AND {c}"; params.extend(p)
        if length:
            c, p = RangeParser.to_sql('length(pk)', length)
            if c: sql += f" AND {c}"; params.extend(p)
            
        sql += f" LIMIT {limit}"
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            format_output(row, output, field)
    conn.close()

@cli.group()
def config_cmd():
    """Manage persistent defaults."""
    pass

@config_cmd.command(name='set')
@click.argument('key', shell_complete=config_key_complete)
@click.argument('value')
def config_set(key, value):
    cfg = ConfigManager.load()
    if key == 'limit': value = int(value)
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ Set {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False, shell_complete=config_key_complete)
def config_get(key):
    cfg = ConfigManager.load()
    if key: click.echo(cfg.get(key, "Not set"))
    else: click.echo(json.dumps(cfg, indent=2))

cli.add_command(config_cmd, name='config')

@cli.command()
@click.option('--data', required=True)
def init(data):
    """Initialize with FTS5 and completion index."""
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("CREATE VIRTUAL TABLE entries USING fts5(pk, desc, tags, val, rank)")
    cursor.execute("DROP TABLE IF EXISTS completion_table")
    cursor.execute("CREATE TABLE completion_table (pk TEXT PRIMARY KEY, rank INTEGER)")
    cursor.execute("CREATE INDEX idx_comp_pk ON completion_table(pk, rank DESC)")
    conn.commit(); conn.close()

import unicodedata

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

def get_manifest():
    manifest_path = Path(__file__).parent / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            return json.load(f)
    return {"features": []}

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    global_manifest_path = Path("skills/concept-cli-factory/references/features-manifest.json")
    local_manifest = get_manifest()
    
    if not global_manifest_path.exists(): click.secho("❌ Global Manifest missing.", fg='red'); return
    with open(global_manifest_path, 'r') as f: manifest = json.load(f)
    
    click.secho(f"\n🚀 {manifest.get('command', 'Tool').capitalize()} Integrated Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 90)
    
    for feat in manifest:
        f_id = feat['id']
        local_feat = next((f for f in local_manifest.get('features', []) if f['id'] == f_id), None)
        f_status = local_feat['status'] if local_feat else ('miss' if feat.get('status') == 'mandatory' else 'opt')
        
        if status and f_status != status: continue
        
        if f_status == 'implemented':
            st_text, st_color, dim = "✅ OK", "green", False
        elif f_status == 'na':
            st_text, st_color, dim = "🚫 N/A", "red", True
        elif f_status == 'miss':
            st_text, st_color, dim = "❌ MISSING", "red", False
        else:
            st_text, st_color, dim = "⚪ OPT", "yellow", False
            
        st_styled = click.style(st_text, fg=st_color, dim=dim)
        st_padding = " " * (10 - get_display_width(st_text))
        feat_label = pad_cjk(feat['label'], 20)
        
        click.echo(f" {st_styled}{st_padding} | {feat_label} | {feat['description']}")
    click.echo("")

if __name__ == '__main__':
    cli()
