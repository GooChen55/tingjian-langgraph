import sqlglot
import os
from sqlglot import exp

from .catalog import CATALOG


class UnsafeSQL(ValueError):
    pass


def operations_database():
    name = os.environ.get("LISTENING_OPS_DATABASE", "listening_ops")
    if name not in {"listening_ops", "aillisten_dev_ops"}:
        raise UnsafeSQL("统计数据库配置不在项目清单中")
    return name


def validate_sql(sql: str) -> tuple[str, str]:
    """解析 AST 后重新生成 SQL。只允许单视图 SELECT，不信任模型声明的视图。"""
    if not isinstance(sql, str) or not 1 <= len(sql) <= 4000:
        raise UnsafeSQL("SQL 长度不合法")
    if any(marker in sql for marker in ["--", "/*", "#", "@", "\\"]):
        raise UnsafeSQL("不允许注释、变量或转义表达式")
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except sqlglot.errors.SqlglotError:
        raise UnsafeSQL("SQL 语法不合法") from None
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise UnsafeSQL("只允许单条 SELECT")
    tree = statements[0]
    if len(list(tree.walk())) > 160:
        raise UnsafeSQL("查询过于复杂")
    if tree.args.get("into") or tree.args.get("locks") or tree.args.get("with_"):
        raise UnsafeSQL("不支持写入、锁或 CTE")
    if len(list(tree.find_all(exp.Select))) != 1 or tree.find(exp.Join) or tree.find(exp.Subquery):
        raise UnsafeSQL("不支持关联或子查询")
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1:
        raise UnsafeSQL("只能查询一个统计视图")
    table = tables[0]
    if table.catalog or (table.db and table.db != operations_database()) or table.name not in CATALOG:
        raise UnsafeSQL("视图不在白名单中")
    view = table.name
    aliases = {a.alias for a in tree.find_all(exp.Alias)}
    table_aliases = {view, table.alias} - {""}
    for column in tree.find_all(exp.Column):
        if column.name not in CATALOG[view]["columns"] and not (column.name in aliases and column.find_ancestor(exp.Order, exp.Having, exp.Group)):
            raise UnsafeSQL("字段不在指标目录中")
        if column.table and column.table not in table_aliases:
            raise UnsafeSQL("字段限定表不合法")
        if column.catalog or (column.db and column.db != operations_database()):
            raise UnsafeSQL("不支持跨库字段引用")
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise UnsafeSQL("请使用显式字段")
    allowed_functions = {"SUM", "COUNT", "AVG", "MIN", "MAX", "ROUND", "COALESCE", "NULLIF",
                         "DATE", "CURRENT_DATE", "DATE_SUB", "TIME_TO_STR", "TS_OR_DS_TO_TIMESTAMP", "CAST", "IF"}
    for func in tree.find_all(exp.Func):
        if isinstance(func, (exp.And, exp.Or, exp.Not)):
            continue
        if func.sql_name() not in allowed_functions:
            raise UnsafeSQL("函数不在白名单中")
    if tree.args.get("offset"):
        raise UnsafeSQL("暂不支持偏移量")
    limit = tree.args.get("limit")
    if limit:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int or not 1 <= int(value.this) <= 100:
            raise UnsafeSQL("最多返回100行")
    else:
        tree = tree.limit(100)
    if len(tree.expressions) > 10:
        raise UnsafeSQL("最多返回10列")
    return tree.sql(dialect="mysql"), view
