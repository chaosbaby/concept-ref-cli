"""常量定义模块"""

# 字段类型及其支持的操作符
FIELD_TYPES = {
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

# 输出模式选项
OUTPUT_MODES = ['show', 'plain', 'json', 'ndjson']

# 排序方向
SORT_DIRECTIONS = ['asc', 'desc']

# 逻辑运算符
LOGIC_OPERATORS = ['AND', 'OR']
