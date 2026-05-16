from typing import Any, NamedTuple
from nyql import nyql_ast as nq
from alarm_layer import Field, DataType, PK_FIELD_NAME
from interface import AddCommand, DeleteCommand, Command, Table

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
                return EngineResult(commands=self.run_delete_statement(statement))
            case nq.InsertStmt():
                return EngineResult(commands=self.run_insert_statement(statement))
            case nq.UpdateStmt():
                return EngineResult(commands=self.run_update_statement(statement))
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
        group_by_names = statement.group_by
        if group_by_names is None and self._needs_implicit_grouping(statement):
            group_by_names = []
        if group_by_names is not None:
            return self._run_grouped_select(
                statement, records, alias_map, group_by_names
            )
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

    def _needs_implicit_grouping(self, statement: nq.SelectStmt) -> bool:
        if statement.having is not None:
            return True
        if statement.cols is None:
            return False
        return any(self._has_aggregate(col.expr) for col in statement.cols)

    def _has_aggregate(self, expr: nq.Expr) -> bool:
        match expr:
            case nq.FuncCall():
                return True
            case nq.BinOp(left=l, right=r):
                return self._has_aggregate(l) or self._has_aggregate(r)
            case _:
                return False

    def _run_grouped_select(
        self,
        statement: nq.SelectStmt,
        records: list[dict],
        alias_map: dict[str, nq.Expr],
        group_by_names: list[str],
    ) -> Table:
        group_exprs = [
            self._resolve_aliases(nq.ColRef(name=name), alias_map)
            for name in group_by_names
        ]

        groups: dict[tuple, list[dict]] = {}
        for r in records:
            key = tuple(self._eval_expr(e, r) for e in group_exprs)
            groups.setdefault(key, []).append(r)

        items = list(groups.items())

        if statement.having is not None:
            having_expr = self._resolve_aliases(statement.having, alias_map)
            items = [
                (k, gr)
                for k, gr in items
                if self._eval_grouped_condition(having_expr, k, gr, group_exprs)
            ]

        if statement.order_by is not None:
            for col in reversed(statement.order_by):
                order_expr = self._resolve_aliases(nq.ColRef(name=col.name), alias_map)

                def key_fn(item, e=order_expr):
                    v = self._eval_grouped_expr(e, item[0], item[1], group_exprs)
                    return (v is None, v)

                items = sorted(items, key=key_fn, reverse=not col.ascending)

        if statement.limit is not None:
            items = items[: statement.limit]

        if statement.cols is None:
            return Table(cols=list(group_by_names), rows=[list(k) for k, _ in items])

        display_names = [self._display_name(col) for col in statement.cols]
        rows = [
            [
                self._eval_grouped_expr(
                    self._resolve_aliases(col.expr, alias_map), k, gr, group_exprs
                )
                for col in statement.cols
            ]
            for k, gr in items
        ]
        return Table(cols=display_names, rows=rows)

    def _resolve_aliases(self, expr: nq.Expr, alias_map: dict[str, nq.Expr]) -> nq.Expr:
        match expr:
            case nq.ColRef(name=n) if n in alias_map:
                return self._resolve_aliases(alias_map[n], alias_map)
            case nq.BinOp(op=op, left=l, right=r):
                return nq.BinOp(
                    op=op,
                    left=self._resolve_aliases(l, alias_map),
                    right=self._resolve_aliases(r, alias_map),
                )
            case nq.FuncCall(name=name, arg=arg):
                return nq.FuncCall(name=name, arg=self._resolve_aliases(arg, alias_map))
            case _:
                return expr

    def _eval_grouped_expr(
        self,
        expr: nq.Expr,
        group_key: tuple,
        group_records: list[dict],
        group_exprs: list[nq.Expr],
    ) -> Any:
        for i, ge in enumerate(group_exprs):
            if expr == ge:
                return group_key[i]
        match expr:
            case nq.Literal(value=v):
                return v
            case nq.FuncCall(name=name, arg=arg):
                return self._eval_aggregate(name, arg, group_records)
            case nq.ColRef(name=n):
                raise ValueError(
                    f"Column '{n}' must appear in GROUP BY or be inside an aggregate"
                )
            case nq.BinOp(op=op, left=l, right=r):
                lv = self._eval_grouped_expr(l, group_key, group_records, group_exprs)
                rv = self._eval_grouped_expr(r, group_key, group_records, group_exprs)
                return self._apply_arith(op, lv, rv)
            case _:
                raise ValueError(f"Unsupported expression type: {type(expr)}")

    def _eval_grouped_condition(
        self,
        expr: nq.Expr,
        group_key: tuple,
        group_records: list[dict],
        group_exprs: list[nq.Expr],
    ) -> bool:
        match expr:
            case nq.BinOp(op="AND", left=l, right=r):
                return self._eval_grouped_condition(
                    l, group_key, group_records, group_exprs
                ) and self._eval_grouped_condition(
                    r, group_key, group_records, group_exprs
                )
            case nq.BinOp(op="OR", left=l, right=r):
                return self._eval_grouped_condition(
                    l, group_key, group_records, group_exprs
                ) or self._eval_grouped_condition(
                    r, group_key, group_records, group_exprs
                )
            case nq.BinOp(op=op, left=l, right=r) if op in (
                ">",
                ">=",
                "<",
                "<=",
                "=",
                "!=",
            ):
                lv = self._eval_grouped_expr(l, group_key, group_records, group_exprs)
                rv = self._eval_grouped_expr(r, group_key, group_records, group_exprs)
                return self._apply_comp(op, lv, rv)
            case _:
                return bool(
                    self._eval_grouped_expr(expr, group_key, group_records, group_exprs)
                )

    def _eval_aggregate(self, name: str, arg: nq.Expr, records: list[dict]) -> Any:
        values = [self._eval_expr(arg, r) for r in records]
        non_null = [v for v in values if v is not None]
        match name.upper():
            case "SUM":
                return sum(non_null)
            case "COUNT":
                return len(non_null)
            case "MIN":
                return min(non_null) if non_null else None
            case "MAX":
                return max(non_null) if non_null else None
            case "AVG":
                return sum(non_null) / len(non_null) if non_null else None
            case _:
                raise ValueError(f"Unknown aggregate function: {name}")

    def _apply_arith(self, op: str, lv: Any, rv: Any) -> Any:
        if not isinstance(lv, (int, float)) or not isinstance(rv, (int, float)):
            raise TypeError(f"Arithmetic on non-numeric values: {lv!r} {op} {rv!r}")
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
                raise ValueError(f"Unsupported arithmetic operator: {op}")

    def _apply_comp(self, op: str, lv: Any, rv: Any) -> bool:
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
                raise ValueError(f"Unsupported comparison operator: {op}")

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

    def run_delete_statement(self, statement: nq.DeleteStmt) -> list[Command]:
        return [
            DeleteCommand(address=record[PK_FIELD_NAME])
            for record in self.records
            if self._eval_condition(statement.where, record)
        ]

    def run_update_statement(self, statement: nq.UpdateStmt) -> list[Command]:
        schema_names = {field.name for field in self.schema}
        for a in statement.assignments:
            if a.col not in schema_names:
                raise ValueError(f"Unknown column in UPDATE: {a.col}")

        overrides = {a.col: a.value.value for a in statement.assignments}
        num_bytes = sum(field.length_bytes for field in self.schema)
        commands: list[Command] = []

        for record in self.records:
            if statement.where is not None and not self._eval_condition(
                statement.where, record
            ):
                continue
            data = 0
            for field in self.schema:
                if field.name in overrides:
                    value = overrides[field.name]
                else:
                    value = record[field.name]
                encoded = self._encode_value(value, field)
                data = (data << (field.length_bytes * 8)) | encoded
            commands.append(DeleteCommand(address=record[PK_FIELD_NAME]))
            commands.append(AddCommand(data=data, num_bytes=num_bytes))

        return commands

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

    def _encode_value(self, value: str | int | float | bool, field: Field) -> int:
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
