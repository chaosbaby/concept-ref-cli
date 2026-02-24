#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import click
import os

@click.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--db', '-d', required=True, help='输出数据库文件路径')
@click.option('--table', '-t', required=True, help='表名')
@click.option('--fields', '-f', required=True, 
              help='字段定义，格式: name1:type1,name2:type2,... 例如: word:text,pos:text,freq:integer')
@click.option('--delimiter', default='\t', help='字段分隔符，支持 \\t 表示制表符 (默认: \\t)')
@click.option('--encoding', default='utf-8', help='文件编码 (默认: utf-8)')
@click.option('--skip-lines', default=0, type=int, help='跳过文件开头的行数 (默认: 0)')
@click.option('--batch-size', default=10000, type=int, help='批量插入大小 (默认: 10000)')
@click.option('--null-value', default='\\N', help='表示NULL值的字符串 (默认: \\N)')
@click.option('--create-index', multiple=True, 
              help='创建索引的字段，可多次使用，例如: --create-index word --create-index freq')
@click.option('--verbose', '-v', is_flag=True, help='显示详细信息')
def convert(input_file, db, table, fields, delimiter, encoding, skip_lines, 
            batch_size, null_value, create_index, verbose):
    """
    将文本文件转换为 SQLite 数据库，支持灵活指定字段格式
    
    示例:
        # 转换 jieba 词典 (word, freq, pos)
        convert jieba_dict.txt --db words.db --table jieba --fields word:text,freq:integer,pos:text
        
        # 转换词频数据 (word, pos, freq)
        convert 3.6m-words.txt --db words.db --table word_freq --fields word:text,pos:text,freq:integer
        
        # 转换只有词和词频的数据
        convert words.txt --db words.db --table simple --fields word:text,freq:integer --delimiter ' '
        
        # 创建索引
        convert data.txt --db test.db --table mytable --fields a:text,b:integer,c:real --create-index a --create-index b
    """
    
    # 处理特殊转义字符
    if delimiter == '\\t':
        delimiter = '\t'
    if null_value == '\\N':
        null_value = '\\N'  # 保持原样
    
    # 解析字段定义
    field_defs = []
    field_names = []
    field_types = []
    
    for field_def in fields.split(','):
        try:
            name, type_ = field_def.strip().split(':')
            field_names.append(name.strip())
            field_types.append(type_.strip().lower())
            field_defs.append(f"{name.strip()} {type_.strip()}")
        except ValueError:
            raise click.BadParameter(f"字段定义格式错误: {field_def}，应为 name:type")
    
    if verbose:
        click.echo(f"解析到 {len(field_defs)} 个字段: {', '.join(field_defs)}")
    
    # 创建数据库连接
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    
    # 创建表
    create_sql = f"CREATE TABLE IF NOT EXISTS {table} (\n"
    create_sql += "  id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    for i, field_def in enumerate(field_defs):
        create_sql += f"  {field_def}"
        if i < len(field_defs) - 1:
            create_sql += ",\n"
        else:
            create_sql += "\n"
    create_sql += ")"
    
    if verbose:
        click.echo(f"创建表 SQL:\n{create_sql}")
    
    cursor.execute(create_sql)
    conn.commit()
    
    # 删除已有数据（可选，这里保持追加模式）
    # cursor.execute(f"DELETE FROM {table}")
    
    # 创建索引
    for index_field in create_index:
        if index_field in field_names:
            index_name = f"idx_{table}_{index_field}"
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({index_field})")
            if verbose:
                click.echo(f"创建索引: {index_name} ON {table}({index_field})")
        else:
            click.echo(f"警告: 字段 {index_field} 不存在，跳过索引创建", err=True)
    
    # 准备插入语句
    placeholders = ','.join(['?' for _ in field_names])
    insert_sql = f"INSERT INTO {table} ({','.join(field_names)}) VALUES ({placeholders})"
    
    if verbose:
        click.echo(f"插入 SQL: {insert_sql}")
    
    # 读取文件并批量插入
    batch_data = []
    line_count = 0
    success_count = 0
    error_count = 0
    
    if verbose:
        click.echo(f"开始处理文件: {input_file}")
    
    with open(input_file, 'r', encoding=encoding) as f:
        # 跳过指定行数
        for _ in range(skip_lines):
            next(f)
            line_count += 1
        
        for line in f:
            line_count += 1
            line = line.strip()
            if not line:  # 跳过空行
                continue
            
            # 按分隔符拆分
            parts = line.split(delimiter)
            
            # 检查字段数量
            if len(parts) != len(field_names):
                if verbose:
                    click.echo(f"警告: 第 {line_count} 行字段数不匹配 (期望 {len(field_names)}, 实际 {len(parts)}): {line[:50]}...", err=True)
                error_count += 1
                continue
            
            try:
                # 根据字段类型转换数据
                converted = []
                for i, (part, type_) in enumerate(zip(parts, field_types)):
                    if part == null_value:
                        converted.append(None)
                    elif type_ == 'integer' or type_ == 'int':
                        converted.append(int(part))
                    elif type_ == 'real' or type_ == 'float':
                        converted.append(float(part))
                    elif type_ == 'text' or type_ == 'string':
                        converted.append(part)
                    else:
                        converted.append(part)  # 默认当作文本
                
                batch_data.append(tuple(converted))
                success_count += 1
                
                # 批量插入
                if len(batch_data) >= batch_size:
                    cursor.executemany(insert_sql, batch_data)
                    conn.commit()
                    if verbose:
                        click.echo(f"已提交 {success_count} 条记录...")
                    batch_data = []
                    
            except Exception as e:
                if verbose:
                    click.echo(f"错误: 第 {line_count} 行处理失败: {e}", err=True)
                error_count += 1
    
    # 插入剩余数据
    if batch_data:
        cursor.executemany(insert_sql, batch_data)
        conn.commit()
        if verbose:
            click.echo(f"最后提交 {len(batch_data)} 条记录")
    
    # 获取总记录数
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    total_records = cursor.fetchone()[0]
    
    conn.close()
    
    # 输出结果
    click.echo("\n" + "="*60)
    click.echo(f"转换完成!")
    click.echo(f"输入文件: {input_file}")
    click.echo(f"数据库文件: {db}")
    click.echo(f"表名: {table}")
    click.echo(f"字段定义: {fields}")
    click.echo(f"总处理行数: {line_count - skip_lines}")
    click.echo(f"成功导入: {success_count} 条")
    click.echo(f"错误行数: {error_count} 条")
    click.echo(f"数据库总记录数: {total_records}")
    click.echo("="*60)

if __name__ == '__main__':
    convert()
