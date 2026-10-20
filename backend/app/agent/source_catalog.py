"""当前允许 NL2SQL 查询的业务数据能力，供路由与 SQL 生成共用。

这是接入契约，不通过枚举应用数据库表推断能力，避免把会话等内部表当作业务源。
新增业务表时在此维护 Schema，而不是在路由提示词里追加领域特例。
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
