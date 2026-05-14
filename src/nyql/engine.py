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
        display_names = [self._display_name(col) for col in statement.cols]
        records = self.records
        if statement.where is not None:
            records = [r for r in records if self._eval_condition(statement.where, r)]
        if statement.order_by is not None:
            records = self._sort_records(records, statement.order_by)
        if statement.limit is not None:
            records = records[:statement.limit]
        rows = [
            [self._eval_expr(col.expr, record) for col in statement.cols]
            for record in records
        ]
        return Table(cols=display_names, rows=rows)

    def _sort_records(self, records: list[dict], order_by: list[str]) -> list[dict]:
        def sort_key(record: dict):
            return tuple((record.get(col) is None, record.get(col)) for col in order_by)
        return sorted(records, key=sort_key)

    def _display_name(self, col: nq.SelectCol) -> str:
        if col.alias:
            return col.alias
        if isinstance(col.expr, nq.ColRef):
            return col.expr.name
        raise ValueError(f"Expression requires an AS alias")

    def _eval_expr(self, expr: nq.Expr, record: dict) -> Any:
        match expr:
            case nq.Literal(value=v):
                return v
            case nq.ColRef(name=n):
                return record.get(n, None)
            case nq.BinOp(op=op, left=left, right=right):
                lv = self._eval_expr(left, record)
                rv = self._eval_expr(right, record)
                if not isinstance(lv, (int, float)) or not isinstance(rv, (int, float)):
                    raise TypeError(
                        f"Arithmetic on non-numeric values: {lv!r} {op} {rv!r}"
                    )
                match op:
                    case "+":
                        return lv + rv
                    case "-":
                        return lv - rv
                    case "*":
                        return lv * rv
                    case "/":
                        return lv / rv
                    case _:
                        raise ValueError(f"Unsupported operator in SELECT: {op}")
            case _:
                raise ValueError(f"Unsupported expression type: {type(expr)}")

    def _eval_condition(self, expr: nq.Expr, record: dict) -> bool:
        match expr:
            case nq.BinOp(op="AND", left=left, right=right):
                return self._eval_condition(left, record) and self._eval_condition(
                    right, record
                )
            case nq.BinOp(op="OR", left=left, right=right):
                return self._eval_condition(left, record) or self._eval_condition(
                    right, record
                )
            case nq.BinOp(op=op, left=left, right=right):
                lv = self._eval_expr(left, record)
                rv = self._eval_expr(right, record)
                match op:
                    case ">":
                        return lv > rv
                    case ">=":
                        return lv >= rv
                    case "<":
                        return lv < rv
                    case "<=":
                        return lv <= rv
                    case "=":
                        return lv == rv
                    case "!=":
                        return lv != rv
                    case _:
                        raise ValueError(f"Unsupported operator in WHERE: {op}")
            case _:
                raise ValueError(f"Expected a condition, got: {type(expr)}")
