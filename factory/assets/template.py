import click
import json
import sqlite3
import os
import sys
import re
try:
    import zhconv
except ImportError:
    zhconv = None

# TODO: 修改数据库默认路径和名称
DB_PATH = os.path.expanduser("~/.{{ tool_id }}.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_fingerprint(text):
    """提取内容指纹（仅保留汉字，用于忽略排版差异的去重）"""
    if not text: return ""
    return re.sub(r'[^\u4e00-\u9fa5]', '', text)

@click.group()
def cli():
    """{{ description }}"""
    if not os.path.exists(DB_PATH) and sys.argv[-1] != 'init':
        click.secho("数据库未初始化，正在执行初始化...", fg='cyan')
        ctx = click.get_current_context()
        ctx.invoke(init)
    pass

@cli.command()
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']))
def completion(shell):
    """生成命令补全脚本"""
    cmd = f"eval \"$(_\{{ tool_name.upper() \}}_COMPLETE={shell}_source {{ tool_name }})\""
    click.echo(f"# 将此行添加到你的 shell 配置文件:")
    click.echo(cmd)

def handle_search(cursor, query, is_json, strict):
    # 统一简体搜索
    if zhconv:
        query = zhconv.convert(query, 'zh-hans')
        
    pattern = query if strict else f"%{query}%"
    
    # 示例搜索逻辑 (请根据 schema 修改)
    cursor.execute("SELECT * FROM entries WHERE content LIKE ? LIMIT 10", (pattern,))
    rows = cursor.fetchall()
    
    if is_json:
        click.echo(json.dumps([dict(r) for r in rows], ensure_ascii=False))
    else:
        for r in rows:
            click.echo(f"- {r['content']}")

@cli.command()
@click.argument('query', required=False)
@click.option('--json', 'is_json', is_flag=True, help='JSON 格式输出')
@click.option('--strict', is_flag=True, help='精确匹配')
@click.option('--stream', is_flag=True, help='从标准输入读取查询')
def search(query, is_json, strict, stream):
    """搜索功能"""
    conn = get_db()
    cursor = conn.cursor()
    
    if stream:
        for line in sys.stdin:
            q = line.strip()
            if q: handle_search(cursor, q, is_json, strict)
    elif query:
        handle_search(cursor, query, is_json, strict)
    else:
        click.echo("用法: {{ tool_name }} search [QUERY]")
    conn.close()

@cli.command()
@click.option('--data', 'data_path', required=True, help='数据文件路径')
@click.option('--clear', is_flag=True, help='强制清空旧数据')
def init(data_path, clear):
    """初始化数据库 (高性能导入 + 智能去重)"""
    if clear and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass

    conn = get_db()
    cursor = conn.cursor()
    
    # 高性能 PRAGMA
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = WAL")

    click.echo("正在创建表...")
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("""
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            content TEXT,
            metadata TEXT
        )
    """)

    click.echo("正在导入数据并去重...")
    seen_keys = set()
    
    # TODO: 实现具体的读取和去重逻辑
    # 示例去重逻辑：
    # fp = get_fingerprint(content)
    # key = (title, author, fp) # 或者根据 Phase 0 调整为仅 (title, author)
    # if key in seen_keys: continue
    # seen_keys.add(key)
    
    conn.commit()
    conn.close()
    click.echo(f"初始化完成！数据库: {DB_PATH}")

if __name__ == '__main__':
    cli()
