import pytest

from resource_scope import SCOPE, SCHEMAS, remap_schemas, sql_statements


def test_shared_vm_names_cannot_target_other_projects():
    assert len(set(SCHEMAS.values())) == 9
    assert all(v.startswith("aillisten_dev_") for v in SCHEMAS.values())
    for name in ("*", "_all", "tingshu", "aillisten-dev-*", "cc-lg-kb"):
        with pytest.raises(ValueError):
            SCOPE.assert_es_index(name)
    with pytest.raises(ValueError):
        SCOPE.schema("mysql")


def test_schema_rendering_does_not_replace_similar_identifiers():
    assert remap_schemas("`tingshu_user`.access JOIN tingshu_album.track") == (
        "`aillisten_dev_user`.access JOIN aillisten_dev_album.track")
    assert remap_schemas("other_tingshu_user tingshu_username") == (
        "other_tingshu_user tingshu_username")


def test_dump_split_handles_semicolons_in_data_and_comments():
    text = "-- note;\nSET NAMES utf8mb4; INSERT INTO t VALUES ('a;b','c\\\'d'); /* note; */ SELECT `x;y`;"
    parts = list(sql_statements(text))
    assert len(parts) == 3
    assert "'a;b'" in parts[1]
    assert "`x;y`" in parts[2]
    assert list(sql_statements("/*!40101 SET @a='x;y' */;")) == ["/*!40101 SET @a='x;y' */"]


@pytest.mark.parametrize("text", ["SELECT 'open", "/* open"])
def test_incomplete_dump_is_rejected(text):
    with pytest.raises(ValueError):
        list(sql_statements(text))
