from lark import Lark

grammar = r"""
    start: stmt ";"

    stmt: select_stmt
        | delete_stmt
        | insert_stmt
        | update_stmt
        | get_schema_stmt
        | set_schema_stmt

    select_stmt: "SELECT" select_cols where_clause? group_by_clause? having_clause? order_by_clause? limit_clause?

    where_clause:    "WHERE" expr
    group_by_clause: "GROUP" "BY" name_list
    having_clause:   "HAVING" expr
    order_by_clause: "ORDER" "BY" order_col ("," order_col)*
    !order_col: NAME ("ASC" | "DESC")?
    limit_clause:    "LIMIT" INT

    select_cols: "*"                        -> select_all
               | select_col ("," select_col)*
    select_col:  expr ("AS" NAME)?

    delete_stmt: "DELETE" "WHERE" expr

    insert_stmt: "INSERT" "VALUES" value_row ("," value_row)*
    value_row:   "(" signed_literal ("," signed_literal)* ")"

    update_stmt: "UPDATE" "SET" assignment ("," assignment)* ("WHERE" expr)?
    assignment:  NAME "=" signed_literal

    ?signed_literal: literal
                   | "-" literal -> neg_literal

    get_schema_stmt: "GET" "SCHEMA"
    set_schema_stmt: "SET" "SCHEMA" schema_col ("," schema_col)*
    schema_col:      "(" ESCAPED_STRING "," col_type "," INT ")"
    !col_type:       "TEXT" | "INT" | "UINT" | "BOOLEAN" | "TIMESTAMP"

    name_list: NAME ("," NAME)*

    // Expression grammar — outermost = lowest precedence
    ?expr: or_expr

    ?or_expr:  or_expr  "OR"  and_expr  -> or_expr
            | and_expr

    ?and_expr: and_expr "AND" comp_expr -> and_expr
            | comp_expr

    ?comp_expr: arith comp_op arith     -> comparison
            | arith

    ?arith: arith "+" term -> add
        | arith "-" term -> sub
        | term

    ?term: term "*" factor -> mul
        | term "/" factor -> div
        | factor

    ?factor: NAME "(" expr ")" -> func_call
            | NAME               -> col_ref
            | literal
            | "(" expr ")"
            | "-" factor         -> neg

    !comp_op: ">" | ">=" | "<" | "<=" | "=" | "!="
    literal: ESCAPED_STRING | INT | FLOAT | TRUE | FALSE
    TRUE:  "TRUE"
    FALSE: "FALSE"

    NAME: /[a-zA-Z_]\w*/

    %import common.ESCAPED_STRING
    %import common.INT
    %import common.FLOAT
    %import common.WS_INLINE
    %import common.NEWLINE
    %ignore WS_INLINE
    %ignore NEWLINE
"""

parser = Lark(grammar, parser="lalr")


def parse_nyql(raw_nyql: str):
    return parser.parse(raw_nyql)
