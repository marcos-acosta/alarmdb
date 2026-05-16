from dataclasses import dataclass


@dataclass
class AddCommand:
    data: int
    num_bytes: int


@dataclass
class AddSchemaCommand:
    data: int
    label: str


@dataclass
class DeleteCommand:
    address: int | None = None  # None = delete the first remaining byte


type Command = AddCommand | DeleteCommand | AddSchemaCommand


@dataclass
class Table:
    cols: list[str]
    rows: list[list]
