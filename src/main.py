import sys
import io
import csv
from parse_alarms import parse_serialized_alarms
from nyql.grammar import parse_nyql
from nyql.engine import NyQLEngine, Table
from nyql.nyql_ast import NyQLTransformer

ERROR_CHAR_LIMIT = 1000


def display(data: str):
    print(f"DISPLAY\n{data}")


def run(commands: list[str]):
    nl_commands = "\n".join(commands)
    print(f"RUN\n{nl_commands}")


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
    records, schema = parse_serialized_alarms(serialized_alarms)
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
            run(result.commands)
        elif result.table is not None:
            display(table_to_csv(result.table))
    except Exception as e:
        error(str(e))


if __name__ == "__main__":
    main()
