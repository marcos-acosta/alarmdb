from pathlib import Path
from typing import NamedTuple, Tuple
from functools import reduce
from enum import Enum
from collections import defaultdict
from datetime import datetime
import csv
import io

HOMEDIR = Path("/Users/marcos/m/code/scripting/alarmdb/")
LOGDIR = HOMEDIR / "logs"
LOGDIR.mkdir(exist_ok=True)
LOGPATH = LOGDIR / "logfile.txt"

PK_FIELD_NAME = "_id"


class DataType(Enum):
    TEXT = 0
    UINT = 1
    INT = 2
    TIMESTAMP = 3
    BOOL = 4


class Alarm(NamedTuple):
    time: str
    enabled: bool
    snooze: bool
    repeat_days: list[str]
    label: str


class AddressedByte(NamedTuple):
    address: int
    byte_offset: int
    data: int
    label: str | None = None


class Field(NamedTuple):
    name: str
    datatype: DataType
    length_bytes: int
    start_offset_bytes: int
    end_offset_bytes: int


class Word(NamedTuple):
    address: int
    bytes: list[AddressedByte]


def create_empty_byte(address, byte_offset):
    return AddressedByte(address=address, byte_offset=byte_offset, data=0)


def get_absolute_byte_offset(byte: AddressedByte):
    return (byte.address << 5) + byte.byte_offset


def is_schema_byte(byte: AddressedByte):
    return byte.address >> 10 == 1


def is_data_byte(byte: AddressedByte):
    return byte.address >> 10 == 0


def convert_time(t: str):
    return t.replace("\u202f", " ")


def convert_boolean(b: str):
    return b == "Yes"


def convert_repeat_days(d: str):
    return [] if d == "No" else d.split(" ")


def convert_time_to_address_and_offset(t: str):
    h = int(t.split(":")[0]) % 12
    mm = int(t.split(":")[1].split(" ")[0])
    am_pm = t.split(" ")[1]
    hh = h if am_pm == "AM" else h + 12
    total_minutes = hh * 60 + mm
    return ((total_minutes >> 5) << 5), total_minutes & ((1 << 5) - 1)


def one_if_present(list, string):
    return 1 if string in list else 0


def convert_repeat_days_to_int(repeat_days: list[str]):
    bits = [
        one_if_present(repeat_days, d)
        for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    ]
    return reduce(lambda a, b: (a << 1) + b, bits, 0)


def convert_alarm_to_byte(alarm: Alarm):
    address, byte_offset = convert_time_to_address_and_offset(alarm.time)
    repeat_days_int = convert_repeat_days_to_int(alarm.repeat_days)
    data = (repeat_days_int << 2) + (+alarm.enabled << 1) + +alarm.snooze
    return AddressedByte(
        address=address, byte_offset=byte_offset, data=data, label=alarm.label
    )


def parse_data_to_bytes(data):
    lines = data.split("|")
    num_entries = int(lines[0])
    data_lines = lines[1:]
    times = data_lines[:num_entries]
    enabled = data_lines[num_entries : 2 * num_entries]
    snooze = data_lines[2 * num_entries : 3 * num_entries]
    label = data_lines[3 * num_entries : 4 * num_entries]
    repeat_days = data_lines[4 * num_entries : 5 * num_entries]
    alarms = [
        Alarm(
            convert_time(times[i]),
            convert_boolean(enabled[i]),
            convert_boolean(snooze[i]),
            convert_repeat_days(repeat_days[i]),
            label[i],
        )
        for i in range(num_entries)
    ]
    return [convert_alarm_to_byte(alarm) for alarm in alarms]


def read_schema(bytes: list[AddressedByte]) -> list[Field]:
    schema_bytes = [byte for byte in bytes if is_schema_byte(byte)]
    schema_bytes = sorted(schema_bytes, key=get_absolute_byte_offset)
    schema = []
    current_offset = 0
    for schema_byte in schema_bytes:
        # Top 3 bits
        type = DataType(schema_byte.data >> 5)
        # Bottom 5 bits (add 1 to represent 1-32 instead of 0-31)
        length_bytes = (schema_byte.data & ((1 << 5) - 1)) + 1
        schema.append(
            Field(
                name=schema_byte.label or "",
                datatype=type,
                length_bytes=length_bytes,
                start_offset_bytes=current_offset,
                end_offset_bytes=current_offset + length_bytes,
            )
        )
        current_offset = current_offset + length_bytes
    return schema


def get_data_words(bytes: list[AddressedByte]) -> list[Word]:
    data_bytes = [byte for byte in bytes if is_data_byte(byte)]
    sorted_bytes = sorted(data_bytes, key=get_absolute_byte_offset)
    words = defaultdict(list)
    for byte in sorted_bytes:
        words[byte.address].append(byte)
    return [Word(address=address, bytes=bytes) for address, bytes in words.items()]


def read_word_bytes_in_offset_range_with_defaults(
    word: Word, start_offset: int, end_offset: int
) -> list[AddressedByte]:
    return [
        next((b for b in word.bytes if b.byte_offset == o), None)
        or create_empty_byte(word.address, o)
        for o in range(start_offset, end_offset)
    ]


def read_bytes_as_string(bytes: list[AddressedByte]) -> str:
    string = "".join([chr(b.data) for b in bytes])
    return string.split("\x00")[0]


def read_bytes_as_uint(bytes: list[AddressedByte]) -> int:
    return reduce(lambda a, b: (a << 8) + b, [b.data for b in bytes], 0)


def read_bytes_as_signed_int(bytes: list[AddressedByte]) -> int:
    uint = read_bytes_as_uint(bytes)
    total_num_bits = len(bytes) * 8
    is_negative = uint >> (total_num_bits - 1) == 1
    return -(uint ^ ((1 << total_num_bits) - 1)) - 1 if is_negative else uint


def read_bytes_as_timestamp(bytes: list[AddressedByte]) -> datetime:
    return datetime.fromtimestamp(read_bytes_as_uint(bytes))


def read_bytes_as_boolean(bytes: list[AddressedByte]) -> bool:
    return read_bytes_as_uint(bytes) > 0


def read_word_with_schema(word: Word, schema: list[Field]):
    row = dict()
    row[PK_FIELD_NAME] = word.address
    for field in schema:
        bytes = read_word_bytes_in_offset_range_with_defaults(
            word, field.start_offset_bytes, field.end_offset_bytes
        )
        match field.datatype:
            case DataType.TEXT:
                row[field.name] = read_bytes_as_string(bytes)
            case DataType.UINT:
                row[field.name] = read_bytes_as_uint(bytes)
            case DataType.INT:
                row[field.name] = read_bytes_as_signed_int(bytes)
            case DataType.TIMESTAMP:
                row[field.name] = read_bytes_as_timestamp(bytes)
            case DataType.BOOL:
                row[field.name] = read_bytes_as_boolean(bytes)
            case _:
                pass
    return row


def read_words_with_schema(words: list[Word], schema: list[Field]) -> list[dict]:
    return [read_word_with_schema(word, schema) for word in words]


def parse_serialized_alarms(serialized_alarms: str) -> Tuple[list[dict], list[Field]]:
    bytes = parse_data_to_bytes(serialized_alarms)
    schema = read_schema(bytes)
    data_words = get_data_words(bytes)
    records = read_words_with_schema(data_words, schema)
    return records, schema
