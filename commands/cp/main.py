import click
import json
import sqlite3
import os
import sys
import random
import zhconv
from pathlib import Path

# 数据库路径：指向项目根目录下的 data 目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "cp_poetry.db")
CONFIG_PATH = os.path.expanduser("~/.cpt.json")

class ConfigManager:
    DEFAULT_CONFIG = {
        "output": "plain",
        "limit": 10,
        "dynasty": None
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

def get_manifest():
    manifest_path = Path(__file__).parent / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            return json.load(f)
    return {"features": []}

def parse_range(range_str):
    """解析区间字符串，如 '100-', '-500', '10-20'"""
    if not range_str: return None, None
    if '-' not in range_str:
        try: return int(range_str), int(range_str)
        except: return None, None
    
    parts = range_str.split('-')
    start = int(parts[0]) if parts[0] else None
    end = int(parts[1]) if parts[1] else None
    return start, end

@click.group()
def cli():
    """中华诗歌 CLI 工具 - 高性能修正版"""
    pass

@cli.command()
@click.option('--status', type=click.Choice(['ok', 'miss', 'opt']), help='Filter by status')
def features(status):
    """Display the full Capability Matrix with accurate status."""
    global_manifest_path = Path("skills/concept-cli-factory/references/features-manifest.json")
    local_manifest = get_manifest()
    
    if not global_manifest_path.exists(): click.secho("❌ Global Manifest missing.", fg='red'); return
    with open(global_manifest_path, 'r') as f: manifest = json.load(f)
    
    click.secho("\n🚀 Poetry Integrated Feature Matrix\n", fg='cyan', bold=True)
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
    else: # plain or show
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

def get_input_stream(query, stream):
    """统一输入流处理器"""
    if stream:
        for line in sys.stdin:
            q = line.strip()
            if q: yield q
    elif query:
        yield query

def handle_search(cursor, query, output_format, dynasty=None, limit=10, show_strains=False, weight_range=None, len_range=None, poetry_type=None):
    params = []
    # 统一转简体进行匹配
    query = zhconv.convert(query, 'zh-hans')
    
    # 基础过滤条件构建
    where_clauses = []
    
    # 尝试 FTS5 全文搜索
    if query:
        where_clauses.append("poetry.id IN (SELECT rowid FROM poetry_fts WHERE poetry_fts MATCH ?)")
        params.append(query)
    
    if dynasty:
        where_clauses.append("poetry.dynasty = ?")
        params.append(dynasty)
        
    if poetry_type:
        where_clauses.append("poetry.type = ?")
        params.append(poetry_type)
        
    if weight_range:
        start, end = parse_range(weight_range)
        if start is not None:
            where_clauses.append("poetry.weight >= ?")
            params.append(start)
        if end is not None:
            where_clauses.append("poetry.weight <= ?")
            params.append(end)

    if len_range:
        start, end = parse_range(len_range)
        if start is not None:
            where_clauses.append("LENGTH(poetry.content) >= ?")
            params.append(start)
        if end is not None:
            where_clauses.append("LENGTH(poetry.content) <= ?")
            params.append(end)

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    sql = f"SELECT * FROM poetry {where_sql} ORDER BY weight DESC, id ASC LIMIT ?"
    params.append(limit)
    
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []

    # Fallback 逻辑仅在 query 存在且 FTS 没结果时触发
    if query and not rows:
        like_clauses = ["(title LIKE ? OR author LIKE ? OR content LIKE ?)"]
        like_params = [f"%{query}%", f"%{query}%", f"%{query}%"]
        
        # 重新应用过滤条件
        if dynasty:
            like_clauses.append("dynasty = ?")
            like_params.append(dynasty)
        if poetry_type:
            like_clauses.append("type = ?")
            like_params.append(poetry_type)
        if weight_range:
            start, end = parse_range(weight_range)
            if start is not None: like_clauses.append("weight >= ?"); like_params.append(start)
            if end is not None: like_clauses.append("weight <= ?"); like_params.append(end)
        if len_range:
            start, end = parse_range(len_range)
            if start is not None: like_clauses.append("LENGTH(content) >= ?"); like_params.append(start)
            if end is not None: like_clauses.append("LENGTH(content) <= ?"); like_params.append(end)

        like_sql = "SELECT * FROM poetry WHERE " + " AND ".join(like_clauses) + " ORDER BY weight DESC LIMIT ?"
        like_params.append(limit)
        cursor.execute(like_sql, like_params)
        rows = cursor.fetchall()

    output_result(rows, output_format, show_strains)

@cli.command()
@click.argument('query', required=False)
@click.option('--output', '-o', 'output_format', type=click.Choice(['plain', 'json', 'ndjson', 'show']), help='输出格式')
@click.option('--dynasty', help='按朝代过滤 (enum: 唐, 宋, 等)')
@click.option('--type', 'poetry_type', help='按诗歌类型/来源过滤 (enum: 全唐诗, 全宋词, 等)')
@click.option('--weight', help='按权重区间过滤 (range: 100-, -500, 10-20)')
@click.option('--len', 'len_range', help='按字数区间过滤 (range: 20-50)')
@click.option('--limit', type=int, help='结果数量限制')
@click.option('--strains', is_flag=True, help='显示平仄')
@click.option('--stream', is_flag=True, help='流处理模式：从标准输入读取查询')
def search(query, output_format, dynasty, poetry_type, weight, len_range, limit, strains, stream):
    """搜索诗词 (支持多维区间过滤)"""
    cfg = ConfigManager.load()
    output_format = output_format or cfg['output']
    limit = limit or cfg['limit']
    dynasty = dynasty or cfg['dynasty']

    conn = get_db()
    cursor = conn.cursor()
    for q in get_input_stream(query, stream):
        handle_search(cursor, q, output_format, dynasty, limit, strains, weight, len_range, poetry_type)
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
@click.option('--count', default=1, help='随机获取的数量')
@click.option('--output', '-o', 'output_format', type=click.Choice(['plain', 'json', 'show']), default='plain', help='输出格式')
def pick(count, output_format):
    """随机灵感捡拾"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM poetry ORDER BY RANDOM() LIMIT ?", (count,))
    rows = cursor.fetchall()
    if rows:
        output_result(rows, output_format)
    conn.close()

@cli.command()
@click.argument('action', type=click.Choice(['set', 'get', 'list']))
@click.argument('key', required=False)
@click.argument('value', required=False)
def config(action, key, value):
    """配置管理"""
    cfg = ConfigManager.load()
    if action == 'list':
        for k, v in cfg.items():
            click.echo(f"{k} = {v}")
    elif action == 'get':
        if key in cfg:
            click.echo(cfg[key])
        else:
            click.secho(f"❌ 未知配置项: {key}", fg='red')
    elif action == 'set':
        if key in ConfigManager.DEFAULT_CONFIG:
            # 简单类型转换
            if key == 'limit': value = int(value)
            cfg[key] = value
            ConfigManager.save(cfg)
            click.echo(f"✅ 已设置 {key} = {value}")
        else:
            click.secho(f"❌ 不支持的配置项: {key}", fg='red')

@cli.command()
@click.argument('statement')
def sql(statement):
    """执行 SQL 查询 (仅限 SELECT)"""
    if not statement.lower().strip().startswith("select"):
        click.secho("❌ 安全限制：仅允许 SELECT 语句。", fg='red')
        return
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(statement)
        rows = cursor.fetchall()
        if rows:
            # 简单展示结果
            headers = rows[0].keys()
            click.secho(" | ".join(headers), bold=True, fg='cyan')
            click.echo("-" * 40)
            for r in rows:
                click.echo(" | ".join([str(v) for v in r]))
        else:
            click.echo("无结果。")
    except Exception as e:
        click.secho(f"❌ SQL 错误: {e}", fg='red')
    finally:
        conn.close()

@cli.command()
@click.argument('action', type=click.Choice(['show', 'install']))
@click.pass_context
def completion(ctx, action):
    """Shell 补全管理器"""
    shell = os.environ.get('SHELL', '').split('/')[-1]
    if shell not in ['bash', 'zsh', 'fish']:
        shell = 'bash'
    
    # Click 规范：环境变量名需大写，且对于 zsh 建议增加 unsetopt nomatch 防止通配报错
    env_var = f"_{'CPT'}_COMPLETE"
    cmd = f"{env_var}={shell}_source cpt"
    
    if action == 'show':
        click.echo(f"# Run this to enable completion for {shell}:")
        if shell == 'zsh':
            click.echo(f'unsetopt nomatch 2>/dev/null; eval "$({cmd})"; setopt nomatch 2>/dev/null')
        else:
            click.echo(f'eval "$({cmd})"')
    else:
        rc_map = {'bash': '.bashrc', 'zsh': '.zshrc', 'fish': '.config/fish/config.fish'}
        rc_path = Path.home() / rc_map.get(shell, '.bashrc')
        
        if shell == 'zsh':
            line = f'unsetopt nomatch 2>/dev/null; eval "$({cmd})"; setopt nomatch 2>/dev/null'
        else:
            line = f'eval "$({cmd})"'
        
        if rc_path.exists():
            with open(rc_path, 'r') as f:
                if line in f.read():
                    click.echo("✅ 补全已存在。")
                    return
            with open(rc_path, 'a') as f:
                f.write(f"\n{line}\n")
            click.echo(f"✅ 已注入补全到 {rc_path}，请重启 Shell 或执行 source {rc_path}")
        else:
            click.secho(f"❌ 未找到配置文件: {rc_path}", fg='red')

@cli.command()
def doctor():
    """数据库健康诊断"""
    if not os.path.exists(DB_PATH):
        click.secho(f"❌ 数据库文件不存在: {DB_PATH}", fg='red')
        return
    
    conn = get_db()
    cursor = conn.cursor()
    click.secho(f"🚀 正在诊断数据库: {DB_PATH}", fg='cyan', bold=True)
    
    try:
        cursor.execute("SELECT count(*) FROM poetry")
        p_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM authors")
        a_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM poetry WHERE weight > 0")
        w_count = cursor.fetchone()[0]
        
        click.echo(f"  - 诗词总数: {p_count}")
        click.echo(f"  - 作者总数: {a_count}")
        click.echo(f"  - 已关联热度: {w_count}")
        
        cursor.execute("PRAGMA integrity_check")
        status = cursor.fetchone()[0]
        st_color = 'green' if status == 'ok' else 'red'
        click.echo(f"  - 完整性检查: ", nl=False)
        click.secho(status, fg=st_color)
    except Exception as e:
        click.secho(f"❌ 诊断失败: {e}", fg='red')
    finally:
        conn.close()

@cli.command()
def schema():
    """输出底层数据库字段定义"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='poetry'")
        row = cursor.fetchone()
        if row:
            click.secho("\n--- Poetry Table Schema ---", fg='cyan')
            click.echo(row[0])
            
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='poetry_fts'")
        row = cursor.fetchone()
        if row:
            click.secho("\n--- FTS5 Index Schema ---", fg='cyan')
            click.echo(row[0])
    except Exception as e:
        click.secho(f"❌ 获取 Schema 失败: {e}", fg='red')
    finally:
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
                        fp = get_fingerprint(c_s)
                        
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
