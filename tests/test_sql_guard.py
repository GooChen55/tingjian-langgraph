import pytest
from listening.guard import UnsafeSQL, validate_sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM v_user_summary",
    "SELECT user_count FROM v_user_summary; UPDATE v_user_summary SET user_count=0",
    "SELECT password FROM tingshu_user.user_info",
    "SELECT SLEEP(10) FROM v_user_summary",
    "SELECT LOAD_FILE('/etc/passwd') FROM v_user_summary",
    "SELECT user_count INTO OUTFILE '/tmp/data' FROM v_user_summary",
    "SELECT user_count FROM v_user_summary FOR UPDATE",
    "SELECT user_count FROM v_user_summary UNION SELECT user_count FROM v_user_summary",
    "SELECT * FROM v_user_summary",
    "WITH x AS (SELECT user_count FROM v_user_summary) SELECT user_count FROM x",
    "SELECT @x FROM v_user_summary",
    "SELECT user_count FROM v_user_summary JOIN v_content_summary ON 1=1",
    "SELECT (SELECT user_count FROM v_user_summary) FROM v_user_summary",
    "SELECT user_count FROM v_user_summary LIMIT 1000",
    "SELECT user_count FROM v_user_summary /* bypass */",
    "SELECT password AS password FROM v_user_summary",
    "SELECT 'unclosed FROM v_user_summary",
    "SELECT private_db.v_user_summary.user_count FROM v_user_summary",
])
def test_rejects_unsafe_queries(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql)


def test_aggregate_alias_and_limit():
    sql, view = validate_sql("SELECT category_name, SUM(album_count) AS total FROM v_category_content GROUP BY category_name ORDER BY total DESC LIMIT 5")
    assert view == "v_category_content"
    assert "LIMIT 5" in sql
    assert "LIMIT 100" in validate_sql("SELECT COUNT(*) AS total FROM v_user_daily")[0]


def test_date_and_month_functions():
    sql, _ = validate_sql("SELECT day, SUM(new_user_count) AS users FROM v_user_daily WHERE day >= DATE_SUB(CURRENT_DATE(), INTERVAL 29 DAY) AND day <= CURRENT_DATE() GROUP BY day")
    assert "DATE_SUB" in sql
    sql, _ = validate_sql("SELECT DATE_FORMAT(day, '%Y-%m') AS month, SUM(paid_order_amount) AS amount FROM v_order_daily GROUP BY month")
    assert "DATE_FORMAT" in sql
