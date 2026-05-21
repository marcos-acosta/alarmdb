import sys
import io
import csv
from datetime import datetime
from alarmdb.alarm_layer import (
    parse_serialized_alarms,
    convert_commands_to_instructions,
    DataType,
    Field,
)
from alarmdb.nyql.grammar import parse_nyql
from alarmdb.nyql.engine import NyQLEngine
from alarmdb.interface import Table
from alarmdb.nyql.nyql_ast import NyQLTransformer

ERROR_CHAR_LIMIT = 1000


def display(data: str):
    print(f"DISPLAY\n{data}")


def run(commands: str):
    print(f"RUN\n{commands}")


def error(error_message: str):
    display(f"ERROR: {error_message[:ERROR_CHAR_LIMIT]}")


def format_value(value, datatype: DataType | None):
    if value is None:
        return ""
    if datatype == DataType.TIMESTAMP and isinstance(value, int):
        return datetime.fromtimestamp(value).isoformat()
    return value


def table_to_csv(table: Table, schema: list[Field]) -> str:
    type_by_col = {f.name: f.datatype for f in schema}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(table.cols)
    for row in table.rows:
        writer.writerow(
            format_value(v, type_by_col.get(col)) for v, col in zip(row, table.cols)
        )
    return buf.getvalue()


def main():
    inputs = sys.stdin.read()
    serialized_alarms, raw_nyql = inputs.split("%%BEGIN_NYQL%%")
    bytes, records, schema = parse_serialized_alarms(serialized_alarms)
    nyql_ast = None
    try:
        nyql_tree = parse_nyql(raw_nyql)
        nyql_ast = NyQLTransformer().transform(nyql_tree)
    except Exception as e:
        error(f"Failed to parse NyQL: {e}")
        return
    if nyql_ast is None:
        error("Invalid state")
        return
    engine = NyQLEngine(records, schema)
    try:
        result = engine.run_nyql_statement(nyql_ast)
        if result.commands is not None:
            instructions = convert_commands_to_instructions(result.commands, bytes)
            run(instructions)
        elif result.table is not None:
            display(table_to_csv(result.table, schema))
    except Exception as e:
        error(str(e))


if __name__ == "__main__":
    main()
