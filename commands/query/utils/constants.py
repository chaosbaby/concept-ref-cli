"""常量定义模块"""

def get_all_operators(with_not=True):
    """
    获取所有操作符，可以选择是否包含 NOT 版本
    
    参数:
        with_not: 是否包含 NOT 版本的操作符
    """
    base_operators = {
        'string': {
            'operators': ['is', 'contains', 'startswith', 'endswith', 'regex', 'length_is', 'length_gt', 'length_lt', 'in'],
            'value_type': 'string'
        },
        'integer': {
            'operators': ['is', 'gt', 'gte', 'lt', 'lte', 'between', 'in'],
            'value_type': 'number'
        },
        'datetime': {
            'operators': ['after', 'before', 'between', 'last', 'next', 'on'],
            'value_type': 'date'
        },
        'boolean': {
            'operators': ['is', 'is_not'],
            'value_type': 'boolean'
        }
    }
    
    if not with_not:
        return base_operators
    
    # 添加 NOT 版本的操作符
    enhanced_operators = {}
    for type_name, type_info in base_operators.items():
        enhanced_ops = type_info['operators'].copy()
        
        # 为每个操作符添加 NOT 版本（除了 boolean 的 is_not 已经存在）
        for op in type_info['operators']:
            if op != 'is_not':  # is_not 已经是 NOT 版本
                enhanced_ops.append(f"not:{op}")
        
        enhanced_operators[type_name] = {
            'operators': enhanced_ops,
            'value_type': type_info['value_type']
        }
    
    return enhanced_operators

# 默认导出包含 NOT 版本的操作符
FIELD_TYPES = get_all_operators(with_not=True)

# 为了方便验证，也可以导出基础操作符
BASE_OPERATORS = get_all_operators(with_not=False)

# 输出模式选项
OUTPUT_MODES = ['show', 'plain', 'json', 'ndjson']

# 排序方向
SORT_DIRECTIONS = ['asc', 'desc']

# 逻辑运算符
LOGIC_OPERATORS = ['AND', 'OR']

# 辅助函数：检查操作符是否有效
def is_valid_operator(op: str, column_type: str) -> bool:
    """检查操作符是否有效"""
    if column_type not in FIELD_TYPES:
        return False
    
    valid_ops = FIELD_TYPES[column_type]['operators']
    return op in valid_ops

# 辅助函数：获取实际操作符（去掉 not: 前缀）
def get_actual_operator(op: str) -> str:
    """获取实际操作符（去掉 not: 前缀）"""
    if op.startswith('not:'):
        return op[4:]
    return op

# 辅助函数：检查是否是 NOT 操作符
def is_not_operator(op: str) -> bool:
    """检查是否是 NOT 操作符"""
    return op.startswith('not:')
