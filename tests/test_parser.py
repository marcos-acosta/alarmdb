import pytest
from alarmdb.nyql.grammar import parse_nyql
from alarmdb.nyql.nyql_ast import (
    NyQLTransformer,
    SelectStmt,
    DeleteStmt,
    InsertStmt,
    UpdateStmt,
    GetSchemaStmt,
    SetSchemaStmt,
)


SELECT_QUERIES = [
    "SELECT *;",
    "SELECT name;",
    "SELECT name, age;",
    "SELECT name AS who, age AS years;",
    "SELECT age + 1;",
    "SELECT age + 1 AS modified_age;",
    "SELECT (age + 1) * 2 AS scaled;",
    "SELECT -age;",
    "SELECT -5 + age;",
    "SELECT name WHERE age > 5;",
    "SELECT name WHERE age >= 5 AND age <= 10;",
    "SELECT name WHERE age = -5;",
    "SELECT name WHERE name = \"marcos\";",
    "SELECT name WHERE TRUE;",
    "SELECT name WHERE FALSE OR age > 10;",
    "SELECT name WHERE age + 5 < 10 AND name != \"x\";",
    "SELECT name ORDER BY name;",
    "SELECT name ORDER BY name ASC;",
    "SELECT name ORDER BY name DESC;",
    "SELECT name ORDER BY name DESC, age ASC;",
    "SELECT name LIMIT 10;",
    "SELECT name WHERE age > 0 ORDER BY age DESC LIMIT 5;",
    "SELECT name, SUM(age) AS total GROUP BY name;",
    "SELECT name, SUM(age) AS total GROUP BY name HAVING total > 10;",
    "SELECT name, COUNT(age) AS n, MIN(age) AS lo, MAX(age) AS hi, AVG(age) AS av GROUP BY name;",
    "SELECT SUM(age) AS total;",
    "SELECT SUM(age) + 1 AS plus_one;",
    "SELECT name, age + 1 AS modified_age, SUM(age) AS sum_age WHERE age > 2 GROUP BY name, modified_age HAVING sum_age > 0 ORDER BY name LIMIT 10;",
]

DELETE_QUERIES = [
    "DELETE WHERE age > 100;",
    "DELETE WHERE name = \"marcos\" AND age < 25;",
    "DELETE WHERE TRUE;",
]

INSERT_QUERIES = [
    "INSERT VALUES (\"marcos\", 25);",
    "INSERT VALUES (\"marcos\", 25), (\"ava\", 27);",
    "INSERT VALUES (\"x\", -5);",
    "INSERT VALUES (\"x\", TRUE);",
]

UPDATE_QUERIES = [
    "UPDATE SET name = \"marcos\";",
    "UPDATE SET name = \"marcos\", age = 50 WHERE name = \"warcos\";",
    "UPDATE SET age = -1 WHERE TRUE;",
]

SCHEMA_QUERIES = [
    "GET SCHEMA;",
    "SET SCHEMA (\"name\", TEXT, 6);",
    "SET SCHEMA (\"name\", TEXT, 6), (\"age\", INT, 1);",
]

EXPECTED_TYPES = {
    "SELECT": SelectStmt,
    "DELETE": DeleteStmt,
    "INSERT": InsertStmt,
    "UPDATE": UpdateStmt,
    "GET": GetSchemaStmt,
    "SET": SetSchemaStmt,
}


@pytest.mark.parametrize(
    "query",
    SELECT_QUERIES + DELETE_QUERIES + INSERT_QUERIES + UPDATE_QUERIES + SCHEMA_QUERIES,
)
def test_query_parses(query):
    tree = parse_nyql(query)
    ast = NyQLTransformer().transform(tree)
    expected_type = EXPECTED_TYPES[query.split()[0]]
    assert isinstance(ast, expected_type), (
        f"expected {expected_type.__name__}, got {type(ast).__name__}"
    )


INVALID_QUERIES = [
    "SELECT;",
    "SELECT name WHERE;",
    "INSERT VALUES;",
    "DELETE;",                    # DELETE requires WHERE
    "SELECT name ORDER BY;",
    "SELECT name LIMIT;",
    "SELECT name AS;",
    "SELECT name WHERE age >;",
    "SELECT name WHERE 5 5;",
]


@pytest.mark.parametrize("query", INVALID_QUERIES)
def test_invalid_query_fails(query):
    with pytest.raises(Exception):
        parse_nyql(query)
