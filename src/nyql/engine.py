from dataclasses import dataclass
from typing import Any, NamedTuple
from nyql import nyql_ast as nq
from parse_alarms import Field


@dataclass
class Table:
    cols: list[str]
    rows: list[list]


class EngineResult(NamedTuple):
    table: Table | None = None
    commands: list[str] | None = None


class NyQLEngine:
    def __init__(self, records: list[dict], schema: list[Field]):
        self.records = records
        self.schema = schema

    def run_nyql_statement(self, statement: Any) -> EngineResult:
        match statement:
            case nq.SelectStmt():
                return EngineResult(table=self.run_select_statement(statement))
            case nq.DeleteStmt():
                return EngineResult(commands=[])
            case nq.InsertStmt():
                return EngineResult(commands=[])
            case nq.UpdateStmt():
                return EngineResult(commands=[])
            case nq.GetSchemaStmt():
                return EngineResult(commands=[])
            case nq.SetSchemaStmt():
                return EngineResult(commands=[])
            case _:
                return EngineResult()

    def run_select_statement(self, statement: nq.SelectStmt) -> Table:
        col_names = [
            col.expr.name for col in statement.cols if isinstance(col.expr, nq.ColRef)
        ]
        rows = [[record.get(col, None) for col in col_names] for record in self.records]
        return Table(cols=col_names, rows=rows)
