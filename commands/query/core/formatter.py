"""输出格式化模块"""

import json
import sqlite3
from typing import List, Dict, Any, Optional


class OutputFormatter:
    """Handles different output formats."""
    
    @staticmethod
    def format_results(results: List[sqlite3.Row], 
                      output_mode: str,
                      fields: List[str] = None) -> str:
        """Format results according to output mode."""
        if not results:
            return ""
        
        if output_mode == 'json':
            # Single JSON array
            return json.dumps([dict(row) for row in results], 
                            ensure_ascii=False, indent=2)
        
        elif output_mode == 'ndjson':
            # Newline-delimited JSON
            lines = []
            for row in results:
                lines.append(json.dumps(dict(row), ensure_ascii=False))
            return '\n'.join(lines)
        
        elif output_mode == 'plain':
            # Plain text (one field per line)
            if fields:
                # Show only specified fields
                lines = []
                for row in results:
                    for field in fields:
                        if field in row.keys():
                            lines.append(str(row[field]))
                return '\n'.join(lines)
            else:
                # Show all fields
                lines = []
                for row in results:
                    lines.append(' '.join(str(v) for v in row))
                return '\n'.join(lines)
        
        elif output_mode == 'show':
            # Pretty table format
            if not results:
                return ""
            
            headers = results[0].keys()
            
            # If fields specified, filter headers
            if fields:
                headers = [h for h in headers if h in fields]
            
            # Calculate column widths
            col_widths = {h: len(h) for h in headers}
            rows_data = []
            
            for row in results:
                row_dict = dict(row)
                rows_data.append(row_dict)
                for h in headers:
                    val = str(row_dict.get(h, ''))
                    col_widths[h] = max(col_widths[h], len(val))
            
            # Build table
            lines = []
            
            # Header
            header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
            lines.append(header_line)
            lines.append('-' * len(header_line))
            
            # Rows
            for row_dict in rows_data:
                row_line = ' | '.join(
                    str(row_dict.get(h, '')).ljust(col_widths[h]) 
                    for h in headers
                )
                lines.append(row_line)
            
            return '\n'.join(lines)
        
        return ""
    
    @staticmethod
    def print_results(results: List[Dict[str, Any]], 
                     output_mode: str,
                     fields: List[str] = None,
                     quiet: bool = False):
        """Print results to stdout."""
        if output_mode == 'json':
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif output_mode == 'ndjson':
            for row in results:
                print(json.dumps(row, ensure_ascii=False))
        elif output_mode == 'plain':
            if fields:
                for row in results:
                    values = [str(row.get(f, '')) for f in fields]
                    print(' '.join(values))
            else:
                for row in results:
                    print(' '.join(str(v) for v in row.values()))
        else:  # show
            if not results:
                return
            
            headers = list(results[0].keys())
            if fields:
                headers = [h for h in headers if h in fields]
            
            # Calculate column widths
            col_widths = {h: len(h) for h in headers}
            for row in results:
                for h in headers:
                    val = str(row.get(h, ''))
                    col_widths[h] = max(col_widths[h], len(val))
            
            # Print header
            header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
            print(header_line)
            print('-' * len(header_line))
            
            # Print rows
            for row in results:
                row_line = ' | '.join(str(row.get(h, '')).ljust(col_widths[h]) for h in headers)
                print(row_line)
        
        if not quiet:
            print(f"\n找到 {len(results)} 条结果")
