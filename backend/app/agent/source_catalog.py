"""Business data capabilities that NL2SQL is allowed to query, shared by routing and SQL generation.

This is the integration contract: capabilities are not inferred by enumerating application
tables, so internal tables such as conversations are never treated as business sources.
When adding a business table, maintain its schema here instead of adding domain special
cases to the routing prompt.
"""

BUSINESS_DB_SCHEMAS: dict[str, str] = {
    "zh-CN": """sales（销售记录表）：
- product VARCHAR(128)：产品名称
- quarter VARCHAR(16)：季度，格式 YYYYQn
- region VARCHAR(32)：销售区域
- amount DECIMAL(14,2)：销售额（元）""",
    "en-US": """sales (sales records):
- product VARCHAR(128): product name
- quarter VARCHAR(16): quarter in YYYYQn format
- region VARCHAR(32): sales region
- amount DECIMAL(14,2): sales amount in CNY""",
}
