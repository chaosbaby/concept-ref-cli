import click
import json
import sqlite3
import os
import sys
import zhconv
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# 数据库路径：指向项目根目录下的 data 目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "xh_xinhua.db")
CONFIG_PATH = os.path.expanduser("~/.xh.json")

console = Console()

class ConfigManager:
    DEFAULT_CONFIG = {
        "output": "show",
        "limit": 10
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
    return conn

from pathlib import Path

def get_manifest():
    manifest_path = Path(__file__).parent / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            return json.load(f)
    return {"features": []}

@click.group()
def cli():
    """中华新华字典 CLI 查找工具"""
    # 如果数据库不存在且不是调用 init 命令，则提示或自动初始化
    if not os.path.exists(DB_PATH) and len(sys.argv) > 1 and sys.argv[1] != 'init':
        click.secho("数据库未初始化，正在自动执行初始化...", fg='cyan')
        ctx = click.get_current_context()
        ctx.invoke(init)
    pass

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    global_manifest_path = Path("skills/concept-cli-factory/references/features-manifest.json")
    local_manifest = get_manifest()
    
    if not global_manifest_path.exists(): click.secho("❌ Global Manifest missing.", fg='red'); return
    with open(global_manifest_path, 'r') as f: manifest = json.load(f)
    
    click.secho("\n🚀 Xinhua Integrated Feature Matrix\n", fg='cyan', bold=True)
    click.echo(f" {'STATUS':<10} | {'FEATURE':<20} | {'DESCRIPTION'}")
    click.echo("-" * 80)
    for feat in manifest:
        f_id = feat['id']
        local_feat = next((f for f in local_manifest.get('features', []) if f['id'] == f_id), None)
        f_status = local_feat['status'] if local_feat else ('miss' if feat.get('status') == 'mandatory' else 'opt')
        
        if status and f_status != status: continue
        
        st = click.style("✅ OK", fg='green') if f_status == 'implemented' else (click.style("❌ MISSING", fg='red') if f_status == 'miss' else click.style("⚪ OPT", fg='yellow'))
        click.echo(f" {st:<19} | {feat['label']:<20} | {feat['description']}")
    click.echo("")

@cli.command()
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']))
def completion(shell):
    """生成命令补全脚本指令"""
    cmd = f"eval \"$(_XH_COMPLETE={shell}_source xh)\""
    click.echo(f"# 请将以下命令添加到你的 shell 配置文件中 (如 ~/.bashrc 或 ~/.zshrc):")
    click.echo(cmd)

def handle_search(cursor, query, output_mode, strict):
    results = {'idioms': [], 'cis': [], 'words': []}
    query = zhconv.convert(query, 'zh-hans')
    
    if strict:
        # 严格模式仍使用基础表查询
        cursor.execute("SELECT * FROM idiom WHERE word = ?", (query,))
        results['idioms'] = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM ci WHERE ci = ?", (query,))
        results['cis'] = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM word WHERE word = ?", (query,))
        results['words'] = [dict(r) for r in cursor.fetchall()]
    else:
        # FTS5 高性能搜索
        tokenized_query = " ".join(list(query))
        sql = "SELECT type, source_id FROM fts_xh WHERE fts_xh MATCH ? LIMIT 20"
        cursor.execute(sql, (f'"{tokenized_query}"',))
        fts_results = cursor.fetchall()
        
        for row in fts_results:
            t = row['type']
            sid = row['source_id']
            if t == 'idiom':
                cursor.execute("SELECT * FROM idiom WHERE word = ?", (sid,))
                res = cursor.fetchone()
                if res: results['idioms'].append(dict(res))
            elif t == 'ci':
                cursor.execute("SELECT * FROM ci WHERE ci = ?", (sid,))
                res = cursor.fetchone()
                if res: results['cis'].append(dict(res))
            elif t == 'word':
                cursor.execute("SELECT * FROM word WHERE word = ?", (sid,))
                res = cursor.fetchone()
                if res: results['words'].append(dict(res))

    if output_mode == 'json':
        click.echo(json.dumps(results, ensure_ascii=False))
    elif output_mode == 'ndjson':
        for category in ['idioms', 'cis', 'words']:
            for item in results[category]:
                click.echo(json.dumps(item, ensure_ascii=False))
    else:
        for k, v in [('idiom', results['idioms']), ('ci', results['cis']), ('word', results['words'])]:
            for item in v:
                render_entry(k, item, output_mode)

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'ndjson', 'plain']), help='Output mode')
@click.option('--strict', is_flag=True, help='Strict mode (exact match)')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def search(query, output, strict, stream):
    """全局搜索 (跨表查找)"""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    if is_headless() and output == 'show': output = 'plain'

    conn = get_db()
    cursor = conn.cursor()
    
    for q in get_input_stream(query, stream):
        handle_search(cursor, q, output, strict)

    conn.close()

@cli.command()
@click.option('--data-dir', default='sources/xinhua-json', help='JSON 数据目录')
def init(data_dir):
    """初始化数据库并建立索引 (JSON -> SQLite)"""
    if not os.path.exists(data_dir):
        click.echo(f"错误: 目录 {data_dir} 不存在。")
        return

    conn = get_db()
    cursor = conn.cursor()

    # 创建表
    click.echo("正在创建表...")
    cursor.execute("DROP TABLE IF EXISTS idiom")
    cursor.execute("""
        CREATE TABLE idiom (
            word TEXT PRIMARY KEY,
            pinyin TEXT,
            abbreviation TEXT,
            explanation TEXT,
            derivation TEXT,
            example TEXT
        )
    """)
    
    cursor.execute("DROP TABLE IF EXISTS ci")
    cursor.execute("""
        CREATE TABLE ci (
            ci TEXT PRIMARY KEY,
            explanation TEXT
        )
    """)

    cursor.execute("DROP TABLE IF EXISTS word")
    cursor.execute("""
        CREATE TABLE word (
            word TEXT PRIMARY KEY,
            pinyin TEXT,
            radicals TEXT,
            strokes INTEGER,
            explanation TEXT,
            more TEXT
        )
    """)

    cursor.execute("DROP TABLE IF EXISTS xiehouyu")
    cursor.execute("""
        CREATE TABLE xiehouyu (
            riddle TEXT,
            answer TEXT
        )
    """)

    # 导入数据
    def load_json(filename):
        path = os.path.join(data_dir, filename)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    click.echo("正在导入成语...")
    idioms = load_json('idiom.json')
    cursor.executemany(
        "INSERT OR REPLACE INTO idiom VALUES (?, ?, ?, ?, ?, ?)",
        [(item.get('word'), item.get('pinyin'), item.get('abbreviation'), 
          item.get('explanation'), item.get('derivation'), item.get('example')) for item in idioms]
    )

    click.echo("正在导入词语 (这可能需要一点时间)...")
    cis = load_json('ci.json')
    cursor.executemany(
        "INSERT OR REPLACE INTO ci VALUES (?, ?)",
        [(item.get('ci'), item.get('explanation')) for item in cis]
    )

    click.echo("正在导入汉字...")
    words = load_json('word.json')
    cursor.executemany(
        "INSERT OR REPLACE INTO word VALUES (?, ?, ?, ?, ?, ?)",
        [(item.get('word'), item.get('pinyin'), item.get('radicals'), 
          item.get('strokes'), item.get('explanation'), item.get('more')) for item in words]
    )

    click.echo("正在导入歇后语...")
    xies = load_json('xiehouyu.json')
    cursor.executemany(
        "INSERT INTO xiehouyu VALUES (?, ?)",
        [(item.get('riddle'), item.get('answer')) for item in xies]
    )

    # 建立索引
    click.echo("正在建立查询索引...")
    cursor.execute("CREATE INDEX idx_idiom_abbr ON idiom(abbreviation)")
    cursor.execute("CREATE INDEX idx_idiom_pinyin ON idiom(pinyin)")
    cursor.execute("CREATE INDEX idx_word_pinyin ON word(pinyin)")
    
    # 建立 FTS5 虚拟表
    click.echo("正在建立 FTS5 全文搜索索引...")
    cursor.execute("DROP TABLE IF EXISTS fts_xh")
    cursor.execute("""
        CREATE VIRTUAL TABLE fts_xh USING fts5(
            type UNINDEXED,
            source_id UNINDEXED,
            content,
            pinyin,
            tokenize='unicode61'
        )
    """)
    
    # 填充 FTS5 数据 - 使用自定义函数进行分词（每个字加空格）
    click.echo("正在填充全文索引数据...")
    
    def tokenize_zh(text):
        if not text: return ""
        return " ".join(list(text))

    # 我们需要先获取数据再插入，或者使用 SQLite 函数（但内置函数受限）
    # 这里采用批量获取并处理的方式
    cursor.execute("SELECT word, pinyin FROM idiom")
    cursor.executemany("INSERT INTO fts_xh(type, source_id, content, pinyin) VALUES ('idiom', ?, ?, ?)",
                       [(r[0], tokenize_zh(r[0]), r[1]) for r in cursor.fetchall()])
    
    cursor.execute("SELECT word, pinyin FROM word")
    cursor.executemany("INSERT INTO fts_xh(type, source_id, content, pinyin) VALUES ('word', ?, ?, ?)",
                       [(r[0], tokenize_zh(r[0]), r[1]) for r in cursor.fetchall()])
    
    cursor.execute("SELECT ci FROM ci")
    cursor.executemany("INSERT INTO fts_xh(type, source_id, content, pinyin) VALUES ('ci', ?, ?, ?)",
                       [(r[0], tokenize_zh(r[0]), "") for r in cursor.fetchall()])

    conn.commit()
    conn.close()
    click.echo(f"初始化完成！数据库已保存至: {DB_PATH}")

@cli.command()
def schema():
    """输出底层数据库字段定义 (Schema Reflection)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = cursor.fetchall()
    
    click.secho("\n📊 Database Schema Definition\n", fg='cyan', bold=True)
    for table in tables:
        table_name = table['name']
        click.secho(f"Table: {table_name}", fg='green', bold=True)
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        for col in columns:
            click.echo(f"  - {col['name']:<15} {col['type']}")
        click.echo("")
    conn.close()

@cli.command()
def doctor():
    """DB 完整性及统计分布检查 (Health Diagnosis)"""
    conn = get_db()
    cursor = conn.cursor()
    
    click.secho("\n🩺 Database Health Report\n", fg='cyan', bold=True)
    
    tables = ['idiom', 'word', 'ci', 'xiehouyu']
    total = 0
    for table in tables:
        try:
            cursor.execute(f"SELECT count(*) FROM {table}")
            count = cursor.fetchone()[0]
            click.echo(f"  - {table:<10}: {count:>8} records")
            total += count
        except sqlite3.OperationalError:
            click.secho(f"  - {table:<10}: ❌ Missing", fg='red')
            
    click.echo("-" * 30)
    click.secho(f"  Total Records: {total:>8}", bold=True)
    
    # DB File size
    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    click.echo(f"  Database Size: {size_mb:.2f} MB")
    
    conn.close()

@cli.command()
@click.option('--type', 'entry_type', type=click.Choice(['idiom', 'word', 'ci']), default='idiom')
def pick(entry_type):
    """随机灵感捡拾 (Random Inspiration)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(f"SELECT * FROM {entry_type} ORDER BY RANDOM() LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        render_entry(entry_type, dict(row))
    else:
        click.echo("数据库为空。")
    conn.close()

def is_headless():
    return not sys.stdout.isatty() or os.environ.get('HEADLESS') == '1'

def get_input_stream(query, stream_flag):
    if query == '-' or stream_flag:
        for line in sys.stdin:
            yield line.strip()
    elif query:
        yield query

def render_entry(entry_type, data, output_mode='show'):
    """使用 rich 渲染词条，支持多种输出模式"""
    if output_mode == 'json':
        click.echo(json.dumps(data, ensure_ascii=False))
        return
    elif output_mode == 'plain':
        # 简单平铺输出
        click.echo(" | ".join([str(v) for k, v in data.items() if v]))
        return

    if entry_type == 'idiom':
        title = f"[bold green]{data['word']}[/bold green] [dim]({data['pinyin']})[/dim]"
        content = [f"[bold]释义:[/bold] {data['explanation']}"]
        if data.get('derivation'):
            content.append(f"[dim][italic]出处:[/italic] {data['derivation']}[/dim]")
        if data.get('example'):
            content.append(f"[dim][italic]示例:[/italic] {data['example']}[/dim]")
        
        console.print(Panel("\n".join(content), title=title, border_style="green", expand=False))
    
    elif entry_type == 'word':
        title = f"[bold yellow]{data['word']}[/bold yellow] [dim]({data['pinyin']})[/dim]"
        subtitle = f"部首: {data['radicals']} | 笔画: {data['strokes']}"
        content = [f"[bold]释义:[/bold]\n{data['explanation']}"]
        if data.get('more'):
            content.append(f"\n[bold]更多:[/bold]\n{data['more']}")
        
        console.print(Panel("\n".join(content), title=title, subtitle=subtitle, border_style="yellow", expand=False))
        
    elif entry_type == 'ci':
        title = f"[bold cyan]{data['ci']}[/bold cyan]"
        console.print(Panel(data['explanation'], title=title, border_style="cyan", expand=False))

def handle_sub(cursor, table, query, output_mode, strict):
    col = 'word' if table in ['idiom', 'word'] else ('ci' if table == 'ci' else 'riddle')
    pattern = query if strict else f"{query}%"
    op = "=" if strict else "LIKE"
    
    if table == 'idiom': # 成语额外支持拼音和缩写
        sql = f"SELECT * FROM idiom WHERE abbreviation = ? OR word {op} ? OR pinyin = ? LIMIT 10"
        cursor.execute(sql, (query.lower(), pattern, query))
    else:
        sql = f"SELECT * FROM {table} WHERE {col} {op} ? LIMIT 10"
        cursor.execute(sql, (pattern,))
    
    results = cursor.fetchall()
    if not results:
        if output_mode != 'json': click.secho(f"未找到相关结果。", fg='yellow')
        return

    for row in results:
        render_entry(table, dict(row), output_mode)

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'plain']), help='Output mode')
@click.option('--strict', is_flag=True, help='Strict mode (exact match)')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def idiom(query, output, strict, stream):
    """查找成语 (支持汉字、拼音、缩写)"""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    conn = get_db(); cursor = conn.cursor()
    for q in get_input_stream(query, stream): handle_sub(cursor, 'idiom', q, output, strict)
    conn.close()

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'plain']), help='Output mode')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def word(query, output, stream):
    """查找汉字"""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    conn = get_db(); cursor = conn.cursor()
    for q in get_input_stream(query, stream): handle_sub(cursor, 'word', q, output, True)
    conn.close()

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'plain']), help='Output mode')
@click.option('--strict', is_flag=True, help='Strict mode (exact match)')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def ci(query, output, strict, stream):
    """查找词语"""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    conn = get_db(); cursor = conn.cursor()
    for q in get_input_stream(query, stream): handle_sub(cursor, 'ci', q, output, strict)
    conn.close()

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', type=click.Choice(['show', 'json', 'plain']), help='Output mode')
@click.option('--strict', is_flag=True, help='Strict mode (exact match)')
@click.option('--stream', is_flag=True, help='Read queries from stdin')
def xie(query, output, strict, stream):
    """查找歇后语 (搜索谜面)"""
    cfg = ConfigManager.load()
    output = output or cfg['output']
    conn = get_db(); cursor = conn.cursor()
    for q in get_input_stream(query, stream): handle_sub(cursor, 'xiehouyu', q, output, strict)
    conn.close()

@cli.group()
def config_cmd():
    """管理持久化配置"""
    pass

@config_cmd.command(name='set')
@click.argument('key', type=click.Choice(['output', 'limit']))
@click.argument('value')
def config_set(key, value):
    cfg = ConfigManager.load()
    if key == 'limit': value = int(value)
    cfg[key] = value
    ConfigManager.save(cfg)
    click.secho(f"✅ 已设置 {key}={value}", fg='green')

@config_cmd.command(name='get')
@click.argument('key', required=False)
def config_get(key):
    cfg = ConfigManager.load()
    if key: click.echo(cfg.get(key, "未设置"))
    else: click.echo(json.dumps(cfg, indent=2, ensure_ascii=False))

cli.add_command(config_cmd, name='config')

try:
    from commands.query import create_query_cmd
    cmd = create_query_cmd(
        db_path=DB_PATH,
        table_prefix="",
        tables=['idiom', 'ci', 'word', 'xiehouyu'],
        help_text="查询词典数据库",
        cache_values=True
    )
    cli.add_command(cmd)
except ImportError as e:
    click.secho(f"Warning: Could not load 'query' command: {e}", fg='yellow')

if __name__ == '__main__':
    cli()
