#!/usr/bin/env python3
"""
任意 JSON 转 SQLite 数据库工具
支持作为模块导入，也可作为命令行工具使用
"""

import json
import sqlite3
import click
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
import re

# ========== 核心函数 ==========

def infer_sqlite_type(value: Any) -> str:
    """推断值的 SQLite 数据类型"""
    if value is None:
        return "TEXT"
    if isinstance(value, bool):
        return "INTEGER"  # SQLite 用 0/1 表示布尔
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, (str, list, dict)):
        return "TEXT"
    return "TEXT"

def detect_json_format(data: Any) -> Tuple[str, List[Dict]]:
    """
    检测 JSON 格式并返回标准化的记录列表
    返回: (format_type, records)
    """
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return "array", data
        else:
            return "simple_array", [{"value": item} for item in data]
    
    elif isinstance(data, dict):
        if all(isinstance(v, (str, int, float, bool, dict, list)) for v in data.values()):
            records = []
            for k, v in data.items():
                if isinstance(v, dict):
                    v['_key'] = k
                    records.append(v)
                else:
                    records.append({"key": k, "value": v})
            return "object", records
        else:
            return "single", [data]
    
    else:
        raise ValueError(f"不支持的 JSON 格式: {type(data)}")

def create_table_from_records(conn: sqlite3.Connection, table_name: str, 
                              records: List[Dict], 
                              drop_existing: bool = False,
                              batch_size: int = 10000,
                              progress_callback: Optional[callable] = None) -> Dict:
    """
    从记录列表创建表
    返回: 字段信息
    """
    if not records:
        raise ValueError("没有数据可导入")
    
    # 收集所有字段
    all_keys = set()
    for record in records:
        all_keys.update(record.keys())
    
    # 推断每个字段的类型
    field_types = {}
    for key in all_keys:
        values = [r[key] for r in records if key in r and r[key] is not None]
        if values:
            field_types[key] = infer_sqlite_type(values[0])
        else:
            field_types[key] = "TEXT"
    
    # 处理已存在的表
    if drop_existing:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    
    # 生成 CREATE TABLE 语句
    columns = []
    for key, typ in field_types.items():
        safe_key = f'"{key}"' if not key.isidentifier() else key
        columns.append(f"{safe_key} {typ}")
    
    has_id = 'id' in all_keys
    if not has_id:
        columns.insert(0, "id INTEGER PRIMARY KEY AUTOINCREMENT")
    
    create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(columns) + "\n)"
    
    conn.execute(create_sql)
    
    # 插入数据
    placeholders = ", ".join(["?"] * len(columns))
    column_names = [c.split()[0].strip('"') for c in columns]
    insert_sql = f"INSERT INTO {table_name} ({', '.join(column_names)}) VALUES ({placeholders})"
    
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i+batch_size]
        for record in batch:
            values = []
            for col in column_names:
                if col == 'id' and col not in record and has_id:
                    values.append(None)
                else:
                    val = record.get(col)
                    if isinstance(val, (dict, list)):
                        val = json.dumps(val, ensure_ascii=False)
                    values.append(val)
            
            try:
                conn.execute(insert_sql, values)
            except sqlite3.IntegrityError:
                pass  # 忽略重复键
        
        conn.commit()
        
        if progress_callback:
            progress_callback(min(i+batch_size, total), total)
    
    return field_types

def create_fts_table(conn: sqlite3.Connection, table_name: str, 
                     fts_columns: List[str],
                     drop_existing: bool = False) -> bool:
    """
    为已有表创建 FTS5 虚拟表
    """
    if not fts_columns:
        return False
    
    fts_table = f"{table_name}_fts"
    
    if drop_existing:
        conn.execute(f"DROP TABLE IF EXISTS {fts_table}")
    
    # 检查表是否存在
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cursor.fetchone():
        raise ValueError(f"表 {table_name} 不存在")
    
    # 创建 FTS5 表
    columns_def = ", ".join(fts_columns)
    create_sql = f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} USING fts5(
        {columns_def},
        content={table_name},
        content_rowid=id
    )
    """
    
    conn.execute(create_sql)
    
    # 填充 FTS 表
    select_cols = ["id"] + fts_columns
    select_sql = f"SELECT {', '.join(select_cols)} FROM {table_name}"
    
    rows = conn.execute(select_sql).fetchall()
    
    for row in rows:
        rowid = row[0]
        values = row[1:]
        
        placeholders = ", ".join(["?"] * len(values))
        insert_sql = f"INSERT OR IGNORE INTO {fts_table}(rowid, {', '.join(fts_columns)}) VALUES (?, {placeholders})"
        
        try:
            conn.execute(insert_sql, (rowid,) + tuple(values))
        except sqlite3.Error:
            pass
    
    conn.commit()
    return True

def json_file_to_sqlite(json_file: Union[str, Path], 
                        db_path: Union[str, Path],
                        table_name: Optional[str] = None,
                        fts_columns: Optional[List[str]] = None,
                        drop_existing: bool = False,
                        batch_size: int = 10000,
                        verbose: bool = False) -> Dict:
    """
    主函数：将 JSON 文件转换为 SQLite 数据库
    
    返回: 统计信息
    """
    json_path = Path(json_file)
    db_path = Path(db_path)
    
    # 确定表名
    if not table_name:
        table_name = json_path.stem.replace('-', '_').replace(' ', '_')
    
    # 读取 JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 检测格式并获取记录
    format_type, records = detect_json_format(data)
    
    if verbose:
        print(f"格式: {format_type}, 记录数: {len(records)}")
    
    # 连接数据库
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    
    # 创建表
    def progress(current, total):
        if verbose and current % 10000 == 0:
            print(f"已处理 {current}/{total} 条")
    
    field_types = create_table_from_records(
        conn, table_name, records, 
        drop_existing=drop_existing,
        batch_size=batch_size,
        progress_callback=progress if verbose else None
    )
    
    # 创建 FTS 表
    fts_created = False
    if fts_columns:
        try:
            fts_created = create_fts_table(
                conn, table_name, fts_columns,
                drop_existing=drop_existing
            )
        except Exception as e:
            if verbose:
                print(f"FTS 创建失败: {e}")
    
    # 统计信息
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "db_path": str(db_path),
        "table_name": table_name,
        "record_count": count,
        "fields": list(field_types.keys()),
        "fts_created": fts_created,
        "fts_columns": fts_columns if fts_created else []
    }

# ========== 交互式选择 FTS 字段 ==========

def interactive_select_fts(records: List[Dict]) -> List[str]:
    """交互式选择 FTS 字段"""
    if not records:
        return []
    
    sample = records[0]
    text_fields = [k for k, v in sample.items() 
                  if isinstance(v, str) and len(str(v)) > 0]
    
    if not text_fields:
        return []
    
    click.echo("\n可选的文本字段:")
    for i, field in enumerate(text_fields, 1):
        sample_val = str(sample.get(field, ''))[:50]
        click.echo(f"  {i}. {field}: {sample_val}...")
    
    default = ",".join([str(i+1) for i in range(min(3, len(text_fields)))])
    choices = click.prompt(
        "选择要加入 FTS 的字段 (用逗号分隔序号或字段名)", 
        default=default
    ).split(',')
    
    fts_columns = []
    for choice in choices:
        choice = choice.strip()
        if choice.isdigit() and 1 <= int(choice) <= len(text_fields):
            fts_columns.append(text_fields[int(choice)-1])
        elif choice in sample:
            fts_columns.append(choice)
    
    return fts_columns

# ========== Click CLI 命令 ==========

@click.command(name='json2sqlite')
@click.argument('json_file', type=click.Path(exists=True))
@click.option('-d', '--db', default='output.db', help='SQLite 数据库文件 (默认: output.db)')
@click.option('-t', '--table', help='表名 (默认: 使用文件名)')
@click.option('--fts/--no-fts', default=True, help='是否创建 FTS 虚拟表 (默认: 创建)')
@click.option('--fts-columns', help='指定 FTS 字段，用逗号分隔 (例如: word,definition)')
@click.option('--force', is_flag=True, help='强制覆盖已存在的表')
@click.option('--batch-size', default=10000, help='批量插入的批次大小 (默认: 10000)')
@click.option('--verbose', is_flag=True, help='显示详细信息')
@click.option('--interactive', is_flag=True, help='交互式选择 FTS 字段')
def json2sqlite_cmd(json_file, db, table, fts, fts_columns, force, batch_size, verbose, interactive):
    """
    任意 JSON 文件转 SQLite 数据库
    
    JSON 文件可以是:
    - 对象数组: [{"word": "意义", "def": "..."}, ...]
    - 键值对象: {"意义": "释义...", "正义": "..."}
    - 简单数组: ["意义", "正义", ...]
    """
    try:
        # 处理 FTS 字段
        final_fts_columns = None
        if fts:
            if interactive:
                # 需要先读取 JSON 来获取字段
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _, records = detect_json_format(data)
                final_fts_columns = interactive_select_fts(records)
            elif fts_columns:
                final_fts_columns = [c.strip() for c in fts_columns.split(',')]
        
        # 执行转换
        result = json_file_to_sqlite(
            json_file=json_file,
            db_path=db,
            table_name=table,
            fts_columns=final_fts_columns if fts else None,
            drop_existing=force,
            batch_size=batch_size,
            verbose=verbose
        )
        
        # 输出结果
        click.echo(f"\n✅ 完成！")
        click.echo(f"数据库: {result['db_path']}")
        click.echo(f"表: {result['table_name']}")
        click.echo(f"记录数: {result['record_count']}")
        click.echo(f"字段: {', '.join(result['fields'])}")
        
        if result['fts_created']:
            click.echo(f"FTS 表: {result['table_name']}_fts")
            click.echo(f"FTS 字段: {', '.join(result['fts_columns'])}")
        
        # 示例查询
        click.echo("\n示例查询:")
        click.echo(f"  # 查询: sqlite3 {db} \"SELECT * FROM {result['table_name']} LIMIT 5;\"")
        if result['fts_created']:
            click.echo(f"  # 搜索: sqlite3 {db} \"SELECT * FROM {result['table_name']}_fts WHERE {result['table_name']}_fts MATCH '关键词' ORDER BY rank;\"")
            
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        raise click.Abort()

# ========== 主 CLI 组 ==========

@click.group()
def cli():
    """JSON 转 SQLite 工具集"""
    pass

cli.add_command(json2sqlite_cmd)

# ========== 作为独立脚本运行 ==========

if __name__ == '__main__':
    cli()
