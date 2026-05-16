import pytest
from alarm_layer import Field, DataType
from interface import AddCommand, AddSchemaCommand, DeleteCommand
from nyql.grammar import parse_nyql
from nyql.nyql_ast import NyQLTransformer
from nyql.engine import NyQLEngine


@pytest.fixture
def schema():
    return [
        Field("name", DataType.TEXT, 6, 0, 6),
        Field("age", DataType.UINT, 1, 6, 7),
    ]


@pytest.fixture
def records():
    return [
        {"_id": 0, "name": "marcos", "age": 25},
        {"_id": 1, "name": "ava", "age": 27},
        {"_id": 2, "name": "warcos", "age": 99},
        {"_id": 3, "name": "bob", "age": 5},
    ]


def run(query: str, records, schema):
    ast = NyQLTransformer().transform(parse_nyql(query))
    return NyQLEngine(records, schema).run_nyql_statement(ast)


# ---------------- SELECT ----------------


def test_select_star_returns_all_columns(records, schema):
    res = run("SELECT *;", records, schema)
    assert res.table is not None
    assert res.table.cols == ["name", "age"]
    assert len(res.table.rows) == 4


def test_select_specific_columns(records, schema):
    res = run("SELECT name;", records, schema)
    assert res.table.cols == ["name"]
    assert res.table.rows == [["marcos"], ["ava"], ["warcos"], ["bob"]]


def test_select_with_where(records, schema):
    res = run("SELECT name WHERE age > 20;", records, schema)
    assert res.table.rows == [["marcos"], ["ava"], ["warcos"]]


def test_select_with_alias_and_arithmetic(records, schema):
    res = run("SELECT name, age + 1 AS next_age WHERE age = 25;", records, schema)
    assert res.table.cols == ["name", "next_age"]
    assert res.table.rows == [["marcos", 26]]


def test_select_order_by_asc(records, schema):
    res = run("SELECT name ORDER BY age ASC;", records, schema)
    assert res.table.rows == [["bob"], ["marcos"], ["ava"], ["warcos"]]


def test_select_order_by_desc(records, schema):
    res = run("SELECT name ORDER BY age DESC;", records, schema)
    assert res.table.rows == [["warcos"], ["ava"], ["marcos"], ["bob"]]


def test_select_limit(records, schema):
    res = run("SELECT name ORDER BY age ASC LIMIT 2;", records, schema)
    assert res.table.rows == [["bob"], ["marcos"]]


def test_select_aggregate_no_group_by(records, schema):
    res = run("SELECT SUM(age) AS total;", records, schema)
    assert res.table.rows == [[156]]


def test_select_group_by_with_having(schema):
    rs = [
        {"_id": 0, "name": "a", "age": 5},
        {"_id": 1, "name": "a", "age": 3},
        {"_id": 2, "name": "b", "age": 7},
        {"_id": 3, "name": "c", "age": 1},
    ]
    res = run(
        "SELECT name, SUM(age) AS total GROUP BY name HAVING total > 5;",
        rs,
        schema,
    )
    assert sorted(res.table.rows) == [["a", 8], ["b", 7]]


def test_select_where_true(records, schema):
    res = run("SELECT name WHERE TRUE;", records, schema)
    assert len(res.table.rows) == 4


def test_select_where_false(records, schema):
    res = run("SELECT name WHERE FALSE;", records, schema)
    assert res.table.rows == []


# ---------------- DELETE ----------------


def test_delete_emits_one_command_per_match(records, schema):
    res = run("DELETE WHERE age > 50;", records, schema)
    assert res.commands == [DeleteCommand(address=2)]


def test_delete_no_match(records, schema):
    res = run("DELETE WHERE age > 1000;", records, schema)
    assert res.commands == []


def test_delete_all(records, schema):
    res = run("DELETE WHERE TRUE;", records, schema)
    addresses = [c.address for c in res.commands]
    assert addresses == [0, 1, 2, 3]


# ---------------- INSERT ----------------


def test_insert_single_row(records, schema):
    res = run('INSERT VALUES ("zoe", 30);', records, schema)
    assert len(res.commands) == 1
    assert isinstance(res.commands[0], AddCommand)
    assert res.commands[0].num_bytes == 7


def test_insert_multiple_rows(records, schema):
    res = run('INSERT VALUES ("a", 1), ("b", 2), ("c", 3);', records, schema)
    assert len(res.commands) == 3
    assert all(isinstance(c, AddCommand) for c in res.commands)


def test_insert_wrong_value_count_raises(records, schema):
    with pytest.raises(ValueError, match="Expected 2 values"):
        run('INSERT VALUES ("a", 1, 2);', records, schema)


def test_insert_text_too_long_raises(records, schema):
    with pytest.raises(ValueError, match="bytes"):
        run('INSERT VALUES ("toolongname", 1);', records, schema)


# ---------------- UPDATE ----------------


def test_update_emits_delete_then_add_per_match(records, schema):
    res = run('UPDATE SET name = "marcos", age = 50 WHERE name = "warcos";', records, schema)
    assert len(res.commands) == 2
    assert isinstance(res.commands[0], DeleteCommand)
    assert res.commands[0].address == 2
    assert isinstance(res.commands[1], AddCommand)
    assert res.commands[1].num_bytes == 7


def test_update_no_match_emits_nothing(records, schema):
    res = run('UPDATE SET age = 0 WHERE age > 1000;', records, schema)
    assert res.commands == []


def test_update_all_records(records, schema):
    res = run('UPDATE SET age = 0 WHERE TRUE;', records, schema)
    # one delete + one add per record
    assert len(res.commands) == 8
    deletes = [c for c in res.commands if isinstance(c, DeleteCommand)]
    adds = [c for c in res.commands if isinstance(c, AddCommand)]
    assert len(deletes) == 4
    assert len(adds) == 4
    assert sorted(c.address for c in deletes) == [0, 1, 2, 3]


def test_update_preserves_unmentioned_fields(records, schema):
    # Update only name; age should be preserved in the new ADD's data
    res = run('UPDATE SET name = "x" WHERE age = 25;', records, schema)
    assert len(res.commands) == 2
    add = res.commands[1]
    assert isinstance(add, AddCommand)
    # Last byte (age) should still be 25
    assert add.data & 0xFF == 25


def test_update_unknown_column_raises(records, schema):
    with pytest.raises(ValueError, match="Unknown column"):
        run('UPDATE SET nonexistent = 1 WHERE TRUE;', records, schema)


# ---------------- SET SCHEMA ----------------


def test_set_schema_emits_one_add_per_col(records, schema):
    res = run('SET SCHEMA ("name", TEXT, 6), ("age", INT, 1);', records, schema)
    adds = [c for c in res.commands if isinstance(c, AddSchemaCommand)]
    assert len(adds) == 2
    assert adds[0].label == "name"
    assert adds[1].label == "age"


def test_set_schema_encodes_type_and_length(records, schema):
    res = run('SET SCHEMA ("name", TEXT, 6), ("age", INT, 1);', records, schema)
    adds = [c for c in res.commands if isinstance(c, AddSchemaCommand)]
    # TEXT = 0, length 6 → (0 << 5) | (6-1) = 5
    assert adds[0].data == 5
    # INT = 2, length 1 → (2 << 5) | (1-1) = 64
    assert adds[1].data == 64


def test_set_schema_invalid_length_raises(records, schema):
    with pytest.raises(ValueError, match="must be 1-32"):
        run('SET SCHEMA ("name", TEXT, 0);', records, schema)
    with pytest.raises(ValueError, match="must be 1-32"):
        run('SET SCHEMA ("name", TEXT, 33);', records, schema)


def test_set_schema_prepends_wipe_deletes(records, schema):
    # 4 records * (6 + 1) bytes per record + 2 schema bytes = 30 total
    res = run('SET SCHEMA ("name", TEXT, 6), ("age", INT, 1);', records, schema)
    deletes = [c for c in res.commands if isinstance(c, DeleteCommand)]
    adds = [c for c in res.commands if isinstance(c, AddSchemaCommand)]
    assert len(deletes) == 30
    assert all(d.address is None for d in deletes)
    assert len(adds) == 2
    # Deletes come before adds
    assert all(isinstance(c, DeleteCommand) for c in res.commands[:30])


def test_set_schema_with_empty_db_emits_no_deletes():
    res = run('SET SCHEMA ("x", INT, 1);', [], [])
    assert all(not isinstance(c, DeleteCommand) for c in res.commands)
    assert len(res.commands) == 1
