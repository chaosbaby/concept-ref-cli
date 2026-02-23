"""数据库 Schema 管理模块"""

import os
import sqlite3
from typing import Dict, List, Optional, Set
from collections import defaultdict

from ..utils.constants import FIELD_TYPES

LIMIT = 200  # 默认查询限制数量

class SchemaManager:
    """Inspects and caches the DB schema for a specific database."""
    
    def __init__(self, db_path: str, table_prefix: str = "", cache_values: bool = False, value_cache_limit: int = LIMIT):
        self.db_path = os.path.expanduser(db_path)
        self.table_prefix = table_prefix
        self.cache_values = cache_values
        self.value_cache_limit = value_cache_limit
        self.schema: Dict[str, Dict[str, str]] = {}
        self.physical_tables: Dict[str, str] = {}
        self.value_cache: Dict[str, Set[str]] = defaultdict(set)  # 表名.列名 -> 值的集合
        self._load_schema()
        if cache_values:
            self._load_value_cache()

    def _load_schema(self):
        """Load schema from the database."""
        if not os.path.exists(self.db_path):
            return
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            for physical_name in tables:
                if physical_name.startswith(self.table_prefix):
                    clean_name = physical_name[len(self.table_prefix):]
                else:
                    clean_name = physical_name
                
                self.physical_tables[clean_name] = physical_name
                self.schema[clean_name] = {}
                
                cursor.execute(f"PRAGMA table_info({physical_name})")
                for col in cursor.fetchall():
                    col_name, col_type = col[1], col[2]
                    self.schema[clean_name][col_name] = col_type
                    
        except sqlite3.Error as e:
            raise RuntimeError(f"Error loading schema from {self.db_path}: {e}")
        finally:
            if conn:
                conn.close()

    def _load_value_cache(self):
        """加载字段值的缓存"""
        if not os.path.exists(self.db_path):
            return
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for clean_name, physical_name in self.physical_tables.items():
                for column in self.schema[clean_name]:
                    try:
                        # 获取该列的唯一值，限制数量
                        query = f'SELECT DISTINCT "{column}" FROM "{physical_name}" WHERE "{column}" IS NOT NULL AND "{column}" != "" LIMIT ?'
                        cursor.execute(query, (self.value_cache_limit,))
                        values = cursor.fetchall()
                        
                        cache_key = f"{clean_name}.{column}"
                        for value in values:
                            if value[0] is not None:
                                self.value_cache[cache_key].add(str(value[0]))
                    except sqlite3.Error:
                        # 如果查询失败，跳过该列
                        continue
        except sqlite3.Error as e:
            # 静默失败，不影响主要功能
            pass
        finally:
            if conn:
                conn.close()

    def get_column_values(self, table: str, column: str, pattern: str = "", limit: int = LIMIT) -> List[str]:
        """
        获取列的可能值，用于补全
        
        参数:
            table: 表名
            column: 列名
            pattern: 匹配模式
            limit: 返回结果数量限制
        """
        if not self.table_exists(table) or not self.column_exists(table, column):
            return []
        
        # 如果启用了缓存，先从缓存中查找
        cache_key = f"{table}.{column}"
        if cache_key in self.value_cache:
            values = list(self.value_cache[cache_key])
            if pattern:
                values = [v for v in values if pattern.lower() in v.lower()]
            return values[:limit]
        
        # 如果没有缓存，直接查询数据库
        return self._query_column_values(table, column, pattern, limit)
    
    def _query_column_values(self, table: str, column: str, pattern: str = "", limit: int = LIMIT) -> List[str]:
        """直接从数据库查询列值"""
        if not os.path.exists(self.db_path):
            return []
        
        physical_name = self.get_physical_table_name(table)
        values = []
        
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if pattern:
                # 使用 LIKE 进行模糊匹配
                query = f'SELECT DISTINCT "{column}" FROM "{physical_name}" WHERE "{column}" IS NOT NULL AND "{column}" != "" AND "{column}" LIKE ? ORDER BY "{column}" LIMIT ?'
                cursor.execute(query, (f'%{pattern}%', limit))
            else:
                query = f'SELECT DISTINCT "{column}" FROM "{physical_name}" WHERE "{column}" IS NOT NULL AND "{column}" != "" ORDER BY "{column}" LIMIT ?'
                cursor.execute(query, (limit,))
            
            for row in cursor.fetchall():
                if row[0] is not None:
                    values.append(str(row[0]))
            
            return values
        except sqlite3.Error:
            return []
        finally:
            if conn:
                conn.close()

    def get_simple_type(self, table: str, column: str) -> Optional[str]:
        """Maps SQLite type to a simple type from FIELD_TYPES."""
        if table not in self.schema:
            return None
        if column not in self.schema[table]:
            return None
            
        sql_type = self.schema[table][column].upper()
        if 'INT' in sql_type:
            return 'integer'
        if 'TEXT' in sql_type or 'CHAR' in sql_type or not sql_type:
            return 'string'
        if 'BOOL' in sql_type:
            return 'boolean'
        if 'DATE' in sql_type or 'TIME' in sql_type:
            return 'datetime'
        if 'REAL' in sql_type or 'FLOA' in sql_type or 'DOUB' in sql_type:
            return 'integer'
        return 'string'

    def get_tables(self) -> List[str]:
        return list(self.schema.keys())

    def get_columns(self, table: str) -> List[str]:
        return list(self.schema.get(table, {}).keys())
    
    def get_physical_table_name(self, table: str) -> str:
        return self.physical_tables.get(table, table)
    
    def table_exists(self, table: str) -> bool:
        return table in self.schema
    
    def column_exists(self, table: str, column: str) -> bool:
        return table in self.schema and column in self.schema[table]
