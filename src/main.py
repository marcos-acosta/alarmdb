import sys
import io
import csv
from alarm_layer import parse_serialized_alarms, convert_commands_to_instructions
from nyql.grammar import parse_nyql
from nyql.engine import NyQLEngine
from interface import Table
from nyql.nyql_ast import NyQLTransformer

ERROR_CHAR_LIMIT = 1000


def display(data: str):
    print(f"DISPLAY\n{data}")


def run(commands: str):
    print(f"RUN\n{commands}")


def error(error_message: str):
    display(f"ERROR: {error_message[:ERROR_CHAR_LIMIT]}")


def table_to_csv(table: Table) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(table.cols)
    writer.writerows(table.rows)
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
            display(table_to_csv(result.table))
    except Exception as e:
        error(str(e))


if __name__ == "__main__":
    main()
