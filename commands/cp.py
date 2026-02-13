import click
import json
import sqlite3
import os
import sys
import random
import zhconv
from pathlib import Path

# 数据库路径：指向项目根目录下的 data 目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "cp_poetry.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@click.group()
def cli():
    """中华诗歌 CLI 工具 - 高性能修正版"""
    pass

def print_poem_plain(r, show_strains=False):
    """人类易读的彩色排版"""
    click.echo("")
    click.secho(f"  {r['title']}", fg='green', bold=True)
    click.secho(f"  [{r['dynasty']}] {r['author']}", fg='cyan')
    click.echo("")
    
    content_lines = r['content'].split('\n')
    # 安全获取 strains
    strains_val = r['strains'] if 'strains' in r.keys() else ""
    strains_lines = strains_val.split('\n') if strains_val else []
    
    for i, line in enumerate(content_lines):
        click.echo(f"    {line}", nl=not show_strains)
        if show_strains and i < len(strains_lines):
            click.secho(f"  {strains_lines[i]}", fg='yellow', dim=True)
        elif show_strains:
            click.echo("")
            
    click.echo("")
    # 安全获取 weight
    weight_val = r['weight'] if 'weight' in r.keys() else 0
    weight_str = f" | Weight: {weight_val}" if weight_val > 0 else ""
    click.secho(f"  (ID: {r['id']} | Source: {r['type']}{weight_str})", dim=True)
    click.echo("-" * 40)

def output_result(rows, output_format, show_strains=False):
    """统一输出协议控制"""
    if output_format == 'json':
        click.echo(json.dumps([dict(r) for r in rows], ensure_ascii=False))
    elif output_format == 'ndjson':
        for r in rows:
            click.echo(json.dumps(dict(r), ensure_ascii=False))
    else: # plain
        if not rows:
            click.secho("未找到结果。", fg='yellow')
            return
        if len(rows) == 1:
            print_poem_plain(rows[0], show_strains)
        else:
            for r in rows:
                summary = r['content'].replace('\n', ' ')[:30] + "..."
                # 安全访问 weight
                weight_val = r['weight'] if 'weight' in r.keys() else 0
                weight_tag = f" [{weight_val}]" if weight_val > 0 else ""
                click.secho(f"【{r['title']}】", fg='green', nl=False)
                click.echo(f" {r['author']} ({r['dynasty']}){weight_tag} - ", nl=False)
                click.secho(summary, dim=True)

def handle_search(cursor, query, output_format, dynasty=None, limit=10, show_strains=False):
    params = []
    # 统一转简体进行匹配
    query = zhconv.convert(query, 'zh-hans')
    
    # 尝试 FTS5 全文搜索
    sql = """
        SELECT poetry.* FROM poetry_fts 
        JOIN poetry ON poetry.id = poetry_fts.rowid 
        WHERE poetry_fts MATCH ?
    """
    params.append(query)
    
    if dynasty:
        sql += " AND poetry.dynasty = ?"
        params.append(dynasty)
        
    sql += " ORDER BY poetry.weight DESC, poetry.id ASC LIMIT ?"
    params.append(limit)
    
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []

    # 如果 FTS5 没搜到，或者是语法错误，Fallback 到 LIKE 搜索
    if not rows:
        like_sql = "SELECT * FROM poetry WHERE (title LIKE ? OR author LIKE ? OR content LIKE ?)"
        like_params = [f"%{query}%", f"%{query}%", f"%{query}%"]
        if dynasty:
            like_sql += " AND dynasty = ?"
            like_params.append(dynasty)
        like_sql += " ORDER BY weight DESC LIMIT ?"
        like_params.append(limit)
        cursor.execute(like_sql, like_params)
        rows = cursor.fetchall()

    output_result(rows, output_format, show_strains)

@cli.command()
@click.argument('query', required=False)
@click.option('--format', 'output_format', type=click.Choice(['plain', 'json', 'ndjson']), default='plain')
@click.option('--dynasty', help='按朝代过滤')
@click.option('--limit', default=10, help='结果数量限制')
@click.option('--strains', is_flag=True, help='显示平仄')
@click.option('--stream', is_flag=True, help='流处理模式：从标准输入读取查询')
def search(query, output_format, dynasty, limit, strains, stream):
    """搜索诗词"""
    conn = get_db()
    cursor = conn.cursor()
    if stream:
        for line in sys.stdin:
            q = line.strip()
            if q: handle_search(cursor, q, output_format, dynasty, limit, strains)
    elif query:
        handle_search(cursor, query, output_format, dynasty, limit, strains)
    else:
        click.echo("用法: cp search [QUERY]")
    conn.close()

@cli.command()
@click.argument('name')
def author(name):
    """查询作者简介"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM authors WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        click.secho(f"【{row['name']}】", fg='green', bold=True)
        click.echo(f"\n{row['desc'] or '暂无简介。'}")
    else:
        click.secho(f"未找到作者: {name}", fg='yellow')
    conn.close()

@cli.command()
def random_one():
    """随机荐诗"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM poetry ORDER BY RANDOM() LIMIT 1")
    row = cursor.fetchone()
    if row:
        print_poem_plain(row)
    conn.close()

@cli.command()
@click.option('--poetry-dir', default='sources/chinese-poetry', help='数据目录')
def init(poetry_dir):
    """全量初始化"""
    poetry_path = Path(poetry_dir)
    config_path = poetry_path / "loader" / "datas.json"
    if not config_path.exists():
        click.echo("错误: 找不到配置")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = MEMORY")

    click.echo("重建表结构...")
    cursor.executescript("""
        DROP TABLE IF EXISTS poetry;
        DROP TABLE IF EXISTS authors;
        CREATE TABLE poetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, author TEXT, content TEXT, dynasty TEXT, type TEXT,
            weight INTEGER DEFAULT 0, strains TEXT,
            UNIQUE(title, author, content)
        );
        CREATE TABLE authors (name TEXT PRIMARY KEY, desc TEXT, dynasty TEXT);
    """)
    
    click.echo("导入作者...")
    for af in poetry_path.rglob("authors.*.json"):
        dynasty = "唐" if "tang" in af.name else "宋"
        try:
            with open(af, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cursor.executemany("INSERT OR REPLACE INTO authors VALUES (?, ?, ?)",
                    [(zhconv.convert(a['name'], 'zh-hans'), zhconv.convert(a.get('desc', ''), 'zh-hans'), dynasty) for a in data])
        except: continue
    conn.commit()

    # 优先导入明确朝代的文件，减少“未知”覆盖
    all_json_files = sorted(list(poetry_path.rglob("*.json")), 
                            key=lambda p: 0 if ("tang" in str(p) or "song" in str(p)) else 1)

    import re
    def get_fingerprint(text):
        # 移除所有非中文字符，仅保留汉字进行比对
        return re.sub(r'[^\u4e00-\u9fa5]', '', text)

    seen_poems = set() # 存储 (title, author, fingerprint)

    for key, ds in config['datasets'].items():
        full_path = poetry_path / ds['path']
        click.echo(f"导入: {ds['name']}...")
        
        def load_p(p):
            if p.suffix != '.json' or p.name in ds.get('excludes', []): return []
            res = []
            try:
                with open(p, 'r', encoding='utf-8') as pf:
                    d = json.load(pf); d = d if isinstance(d, list) else [d]
                    for i in d:
                        t = i.get('title') or i.get('rhythmic') or i.get('chapter') or "无题"
                        c = "\n".join(i.get(ds['tag'], [])) if isinstance(i.get(ds['tag'], []), list) else str(i.get(ds['tag'], ''))
                        dy = "唐" if "tang" in str(p).lower() else "宋" if "song" in str(p).lower() else "元" if "yuan" in str(p).lower() else "五代" if "wudai" in str(p).lower() else "未知"
                        
                        t_s = zhconv.convert(t, 'zh-hans')
                        a_s = zhconv.convert(i.get('author', '佚名'), 'zh-hans')
                        c_s = zhconv.convert(c, 'zh-hans')
                        
                        # 深度去重逻辑
                        # 1. 对于“无题”、“句”等占位类标题，结合内容指纹去重，防止误删不同作品
                        # 2. 对于正式标题，强力使用 (标题, 作者) 去重，解决排版微差导致的重复
                        if t_s in ("无题", "句") or len(t_s) <= 1:
                            key = (t_s, a_s, fp)
                        else:
                            key = (t_s, a_s)
                        
                        if key in seen_poems:
                            continue
                        
                        seen_poems.add(key)
                        res.append((t_s, a_s, c_s, dy, ds['name']))
            except: pass
            return res

        r = []
        if full_path.is_file(): r = load_p(full_path)
        elif full_path.is_dir():
            target_files = sorted(list(full_path.glob("*.json")),
                                 key=lambda p: 0 if ("tang" in p.name or "song" in p.name) else 1)
            for p in target_files: r.extend(load_p(p))
        
        if r:
            cursor.executemany("INSERT OR IGNORE INTO poetry (title, author, content, dynasty, type) VALUES (?,?,?,?,?)", r)
            conn.commit()

    click.echo("建立辅助索引...")
    cursor.execute("CREATE INDEX idx_lookup ON poetry (title, author)")
    conn.commit()

    click.echo("整合 Rank...")
    rank_files = list((poetry_path / "rank").rglob("*.json"))
    with click.progressbar(rank_files, label='Ranking') as bar:
        for rf in bar:
            try:
                with open(rf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 关键：对 rank 里的 title 和 author 也转简体
                    updates = []
                    for i in data:
                        w = int(i.get('baidu', 0)) + int(i.get('google', 0)) + int(i.get('bing', 0))
                        t_s = zhconv.convert(i['title'], 'zh-hans')
                        a_s = zhconv.convert(i['author'], 'zh-hans')
                        updates.append((w, t_s, a_s))
                    
                    # 更新所有匹配的记录（即使有多份拷贝也会一起更新权重）
                    cursor.executemany("UPDATE poetry SET weight = ? WHERE title = ? AND author = ?", updates)
            except: continue
        conn.commit()

    click.echo("整合 Strains...")
    strains_files = list((poetry_path / "strains").rglob("*.json"))
    with click.progressbar(strains_files, label='Strains') as bar:
        for sf in bar:
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    updates = []
                    for i in data:
                        s = "\n".join(i.get('strains', []))
                        t_s = zhconv.convert(i['title'], 'zh-hans')
                        a_s = zhconv.convert(i['author'], 'zh-hans')
                        updates.append((s, t_s, a_s))
                    
                    cursor.executemany("UPDATE poetry SET strains = ? WHERE title = ? AND author = ?", updates)
            except: continue
        conn.commit()

    click.echo("建立全文检索...")
    cursor.execute("DROP TABLE IF EXISTS poetry_fts")
    cursor.execute("CREATE VIRTUAL TABLE poetry_fts USING fts5(title, author, content, dynasty, type, content='poetry', content_rowid='id')")
    cursor.execute("INSERT INTO poetry_fts(poetry_fts) VALUES('rebuild')")
    conn.commit(); conn.close()
    click.echo("初始化圆满完成！")

if __name__ == '__main__':
    cli()
