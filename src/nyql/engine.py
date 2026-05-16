from typing import Any, NamedTuple
from nyql import nyql_ast as nq
from alarm_layer import Field, DataType
from interface import AddCommand, AddSchemaCommand, DeleteCommand, Command, Table

MAX_DATA_ADDRESS = (1 << 10) - 1


class EngineResult(NamedTuple):
    table: Table | None = None
    commands: list[Command] | None = None


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
                return EngineResult(commands=self.run_insert_statement(statement))
            case nq.UpdateStmt():
                return EngineResult(commands=[])
            case nq.GetSchemaStmt():
                return EngineResult(table=self._run_get_schema_statement())
            case nq.SetSchemaStmt():
                return EngineResult(commands=[])
            case _:
                return EngineResult()

    def run_select_statement(self, statement: nq.SelectStmt) -> Table:
        records = self.records
        alias_map: dict[str, nq.Expr] = (
            {col.alias: col.expr for col in statement.cols if col.alias}
            if statement.cols is not None
            else {}
        )
        if statement.where is not None:
            records = [r for r in records if self._eval_condition(statement.where, r)]
        if statement.order_by is not None:
            records = self._sort_records(records, statement.order_by, alias_map)
        if statement.limit is not None:
            records = records[: statement.limit]
        if statement.cols is None:
            col_names = [field.name for field in self.schema]
            rows = [[r.get(col) for col in col_names] for r in records]
            return Table(cols=col_names, rows=rows)
        display_names = [self._display_name(col) for col in statement.cols]
        rows = [
            [self._eval_expr(col.expr, record) for col in statement.cols]
            for record in records
        ]
        return Table(cols=display_names, rows=rows)

    def _sort_records(
        self,
        records: list[dict],
        order_by: list[nq.OrderByCol],
        alias_map: dict[str, nq.Expr],
    ) -> list[dict]:
        def resolve(name: str, record: dict):
            if name in alias_map:
                return self._eval_expr(alias_map[name], record)
            return record.get(name)

        for col in reversed(order_by):
            records = sorted(
                records,
                key=lambda r, c=col: (resolve(c.name, r) is None, resolve(c.name, r)),
                reverse=not col.ascending,
            )
        return records

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
            case nq.Literal() | nq.ColRef():
                return bool(self._eval_expr(expr, record))
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

    def run_insert_statement(self, statement: nq.InsertStmt) -> list[Command]:
        num_bytes = sum(field.length_bytes for field in self.schema)
        commands: list[Command] = []
        for row in statement.rows:
            if len(row) != len(self.schema):
                raise ValueError(f"Expected {len(self.schema)} values, got {len(row)}")
            data = 0
            for field, literal in zip(self.schema, row):
                encoded = self._encode_value(literal.value, field)
                data = (data << (field.length_bytes * 8)) | encoded
            commands.append(AddCommand(data=data, num_bytes=num_bytes))
        return commands

    def _encode_value(self, value: str | int | float, field: Field) -> int:
        max_bits = field.length_bytes * 8
        match field.datatype:
            case DataType.TEXT:
                if not isinstance(value, str):
                    raise TypeError(
                        f"{field.name}: expected TEXT, got {type(value).__name__}"
                    )
                encoded = value.encode("utf-8")
                if len(encoded) > field.length_bytes:
                    raise ValueError(
                        f"{field.name}: value '{value}' is {len(encoded)} bytes, max {field.length_bytes}"
                    )
                padded = encoded.ljust(field.length_bytes, b"\x00")
                return int.from_bytes(padded, "big")
            case DataType.UINT | DataType.TIMESTAMP:
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise TypeError(
                        f"{field.name}: expected non-negative int, got {value!r}"
                    )
                if value >= (1 << max_bits):
                    raise ValueError(
                        f"{field.name}: value {value} exceeds {field.length_bytes} bytes"
                    )
                return value
            case DataType.INT:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise TypeError(
                        f"{field.name}: expected int, got {type(value).__name__}"
                    )
                lo, hi = -(1 << (max_bits - 1)), (1 << (max_bits - 1)) - 1
                if not lo <= value <= hi:
                    raise ValueError(
                        f"{field.name}: value {value} out of range [{lo}, {hi}]"
                    )
                return value & ((1 << max_bits) - 1)  # two's complement
            case DataType.BOOL:
                if not isinstance(value, (bool, int)) or value not in (0, 1):
                    raise TypeError(
                        f"{field.name}: expected BOOL (0 or 1), got {value!r}"
                    )
                return int(value)

    def _run_get_schema_statement(self):
        cols = ["col_name", "type", "length_bytes"]
        rows = [
            [field.name, field.datatype.name, field.length_bytes]
            for field in self.schema
        ]
        return Table(cols=cols, rows=rows)
