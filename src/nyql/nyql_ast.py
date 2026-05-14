from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from lark import Transformer


# --- Expressions ---

@dataclass
class ColRef:
    name: str

@dataclass
class FuncCall:
    name: str
    arg: Expr

@dataclass
class BinOp:
    op: str
    left: Expr
    right: Expr

@dataclass
class Literal:
    value: str | int | float

Expr = ColRef | FuncCall | BinOp | Literal


# --- Select ---

@dataclass
class SelectCol:
    expr: Expr
    alias: Optional[str]

@dataclass
class SelectStmt:
    cols: list[SelectCol]
    where: Optional[Expr]
    group_by: Optional[list[str]]
    having: Optional[Expr]
    order_by: Optional[list[str]]
    limit: Optional[int]


# --- Other statements ---

@dataclass
class DeleteStmt:
    where: Expr

@dataclass
class InsertStmt:
    rows: list[list[Literal]]

@dataclass
class Assignment:
    col: str
    value: Literal

@dataclass
class UpdateStmt:
    assignments: list[Assignment]
    where: Optional[Expr]

@dataclass
class GetSchemaStmt:
    pass

@dataclass
class SchemaCol:
    name: str
    type: str
    order: int

@dataclass
class SetSchemaStmt:
    cols: list[SchemaCol]


Stmt = SelectStmt | DeleteStmt | InsertStmt | UpdateStmt | GetSchemaStmt | SetSchemaStmt


# --- Transformer ---

class NyQLTransformer(Transformer):
    # Expressions
    def col_ref(self, args):
        return ColRef(name=str(args[0]))

    def func_call(self, args):
        return FuncCall(name=str(args[0]), arg=args[1])

    def literal(self, args):
        token = args[0]
        if token.type == "ESCAPED_STRING":
            return Literal(str(token)[1:-1])  # strip quotes
        elif token.type == "INT":
            return Literal(int(token))
        else:
            return Literal(float(token))

    def comp_op(self, args):
        return str(args[0])

    def comparison(self, args):
        left, op, right = args
        return BinOp(op=op, left=left, right=right)

    def or_expr(self, args):
        return BinOp(op="OR", left=args[0], right=args[1])

    def and_expr(self, args):
        return BinOp(op="AND", left=args[0], right=args[1])

    def add(self, args): return BinOp(op="+", left=args[0], right=args[1])
    def sub(self, args): return BinOp(op="-", left=args[0], right=args[1])
    def mul(self, args): return BinOp(op="*", left=args[0], right=args[1])
    def div(self, args): return BinOp(op="/", left=args[0], right=args[1])

    # Select
    def select_col(self, args):
        expr = args[0]
        alias = str(args[1]) if len(args) > 1 else None
        return SelectCol(expr=expr, alias=alias)

    def select_cols(self, args):
        return list(args)

    def name_list(self, args):
        return [str(a) for a in args]

    def where_clause(self, args):    return ("where", args[0])
    def group_by_clause(self, args): return ("group_by", args[0])
    def having_clause(self, args):   return ("having", args[0])
    def order_by_clause(self, args): return ("order_by", args[0])
    def limit_clause(self, args):    return ("limit", int(args[0]))

    def select_stmt(self, args):
        cols = args[0]
        clauses = dict(args[1:])
        return SelectStmt(
            cols=cols,
            where=clauses.get("where"),
            group_by=clauses.get("group_by"),
            having=clauses.get("having"),
            order_by=clauses.get("order_by"),
            limit=clauses.get("limit"),
        )

    # Delete
    def delete_stmt(self, args):
        return DeleteStmt(where=args[0])

    # Insert
    def value_row(self, args):
        return list(args)

    def insert_stmt(self, args):
        return InsertStmt(rows=list(args))

    # Update
    def assignment(self, args):
        return Assignment(col=str(args[0]), value=args[1])

    def update_stmt(self, args):
        assignments = [a for a in args if isinstance(a, Assignment)]
        where = next((a for a in args if not isinstance(a, Assignment)), None)
        return UpdateStmt(assignments=assignments, where=where)

    # Schema
    def get_schema_stmt(self, args):
        return GetSchemaStmt()

    def col_type(self, args):
        return str(args[0])

    def schema_col(self, args):
        name = str(args[0])[1:-1]  # strip quotes
        col_type = args[1]
        order = int(args[2])
        return SchemaCol(name=name, type=col_type, order=order)

    def set_schema_stmt(self, args):
        return SetSchemaStmt(cols=list(args))

    # Unwrap start -> stmt
    def start(self, args):
        return args[0]

    def stmt(self, args):
        return args[0]
