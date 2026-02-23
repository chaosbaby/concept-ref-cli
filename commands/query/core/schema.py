"""数据库 Schema 管理模块"""

import os
import sqlite3
from typing import Dict, List, Optional

from ..utils.constants import FIELD_TYPES


class SchemaManager:
    """Inspects and caches the DB schema for a specific database."""
    
    def __init__(self, db_path: str, table_prefix: str = ""):
        self.db_path = os.path.expanduser(db_path)
        self.table_prefix = table_prefix
        self.schema: Dict[str, Dict[str, str]] = {}
        self.physical_tables: Dict[str, str] = {}
        self._load_schema()

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
