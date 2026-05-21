from alarmdb.interface import AddCommand, DeleteCommand, AddSchemaCommand, Command
from typing import Tuple
from functools import reduce
from enum import Enum
from collections import defaultdict
from dataclasses import dataclass
import copy
import math
import bisect
import struct

PK_FIELD_NAME = "_id"

MAX_NUM_BYTES = 1 << 5
MAX_DATA_ADDRESS = (1 << 5) - 1  # 31
SCHEMA_BASE_ADDRESS = 1 << 5  # 32

ENCODED_DAYS_OF_WEEK = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]

SUNDAY = "sunday"


class DataType(Enum):
    TEXT = 0
    UINT = 1
    INT = 2
    TIMESTAMP = 3
    BOOLEAN = 4
    FLOAT = 5


@dataclass
class Alarm:
    time: str
    enabled: bool
    snooze: bool
    repeat_days: list[str]
    label: str


@dataclass
class AddressedByte:
    address: int
    byte_offset: int
    data: int
    label: str | None = None


@dataclass
class Field:
    name: str
    datatype: DataType
    length_bytes: int
    start_offset_bytes: int
    end_offset_bytes: int


@dataclass
class Word:
    address: int
    bytes: list[AddressedByte]


# =================== #
#   DESERIALIZATION   #
# =================== #


def create_empty_byte(address, byte_offset):
    return AddressedByte(address=address, byte_offset=byte_offset, data=0)


def get_absolute_byte_offset(byte: AddressedByte):
    return (byte.address << 5) | byte.byte_offset


def is_schema_byte(byte: AddressedByte):
    return (byte.address >> 5) & 1 == 1


def is_data_byte(byte: AddressedByte):
    return (byte.address >> 5) == 0


def convert_time(t: str) -> str:
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
    return total_minutes >> 5, total_minutes & ((1 << 5) - 1)


def one_if_present(list, string):
    return 1 if string in list else 0


def convert_repeat_days_to_int(repeat_days: list[str]):
    bits = [
        one_if_present(repeat_days, d)
        for d in [d.capitalize() for d in ENCODED_DAYS_OF_WEEK]
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


def read_bytes_as_boolean(bytes: list[AddressedByte]) -> bool:
    return read_bytes_as_uint(bytes) > 0


def read_bytes_as_float(bytes: list[AddressedByte]) -> float:
    uint = read_bytes_as_uint(bytes)
    return struct.unpack("<f", struct.pack("<I", uint))[0]


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
                row[field.name] = read_bytes_as_uint(bytes)
            case DataType.BOOLEAN:
                row[field.name] = read_bytes_as_boolean(bytes)
            case DataType.FLOAT:
                row[field.name] = read_bytes_as_float(bytes)
            case _:
                pass
    return row


def read_words_with_schema(words: list[Word], schema: list[Field]) -> list[dict]:
    return [read_word_with_schema(word, schema) for word in words]


def parse_serialized_alarms(
    serialized_alarms: str,
) -> Tuple[list[AddressedByte], list[dict], list[Field]]:
    bytes = parse_data_to_bytes(serialized_alarms)
    schema = read_schema(bytes)
    data_words = get_data_words(bytes)
    records = read_words_with_schema(data_words, schema)
    return bytes, records, schema


# ================= #
#   SERIALIZATION   #
# ================= #


type Instruction = str


def _get_delete_instruction(index: int) -> Instruction:
    return f"DELETE|{index + 1}"


def _get_disable_instruction(index: int) -> Instruction:
    return f"DISABLE|{index + 1}"


def _absolute_offset_to_time(offset: int) -> str:
    hours = math.floor(offset / 60)
    minutes = offset % 60
    minutes = "{:0>2}".format(minutes)
    pm = False
    if hours > 12:
        hours = hours - 12
        pm = True
    if hours == 0:
        hours = 12
    return f"{hours}:{minutes} {'PM' if pm else 'AM'}"


def _data_to_repeat_days(data: int) -> str:
    repeat_day_bytes = data >> 2
    days = []
    for day in reversed(ENCODED_DAYS_OF_WEEK):
        if repeat_day_bytes & 1 == 1:
            days.append(day)
        repeat_day_bytes = repeat_day_bytes >> 1
    if len(days) == 1:
        days.append(SUNDAY)
    return " ".join(days)


def _data_to_allow_snooze(data: int) -> str:
    return "true" if data & 1 == 1 else "false"


def _should_disable(data: int) -> bool:
    return (data >> 1) & 1 == 0


def _convert_addressed_byte_to_instruction(
    b: AddressedByte,
) -> Tuple[Instruction, bool]:
    absolute_offset = get_absolute_byte_offset(b)
    time = _absolute_offset_to_time(absolute_offset)
    repeat_days = _data_to_repeat_days(b.data)
    allow_snooze = _data_to_allow_snooze(b.data)
    should_disable = _should_disable(b.data)
    instruction = f"ADD|{time}|{repeat_days}|{allow_snooze}|{b.label or 'Alarm'}"
    return instruction, should_disable


def _convert_add_command_to_addressed_bytes(
    a: AddCommand, address: int
) -> list[AddressedByte]:
    bytes = []
    for offset in range(a.num_bytes):
        shift = (a.num_bytes - 1 - offset) * 8
        byte_value = (a.data >> shift) & 0xFF
        bytes.append(AddressedByte(address, offset, byte_value))
    return bytes


def _find_next_data_address(mutable_bytes: list[AddressedByte]) -> int:
    used = {b.address for b in mutable_bytes if b.address < SCHEMA_BASE_ADDRESS}
    for a in range(MAX_DATA_ADDRESS + 1):
        if a not in used:
            return a
    raise ValueError("No available data addresses")


def _find_next_schema_byte_offset(mutable_bytes: list[AddressedByte]) -> int:
    used_abs = {
        get_absolute_byte_offset(b)
        for b in mutable_bytes
        if b.address >= SCHEMA_BASE_ADDRESS
    }
    abs_offset = SCHEMA_BASE_ADDRESS << 5
    while abs_offset in used_abs:
        abs_offset += 1
    return abs_offset


def _create_instructions_from_bytes(
    mutable_bytes: list[AddressedByte], bytes: list[AddressedByte]
) -> list[Instruction]:
    instructions = []
    for byte in bytes:
        instruction, should_disable = _convert_addressed_byte_to_instruction(byte)
        instructions.append(instruction)
        new_index = _insert_and_get_index(mutable_bytes, byte)
        if should_disable:
            instructions.append(_get_disable_instruction(new_index))
    return instructions


def _insert_and_get_index(mutable_bytes: list[AddressedByte], new_byte: AddressedByte):
    new_index = bisect.bisect_left(
        mutable_bytes,
        get_absolute_byte_offset(new_byte),
        key=lambda b: get_absolute_byte_offset(b),
    )
    mutable_bytes.insert(new_index, new_byte)
    return new_index


def _convert_add_command_to_instructions(
    a: AddCommand, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    address = _find_next_data_address(mutable_bytes)
    bytes = _convert_add_command_to_addressed_bytes(a, address)
    nonzero_bytes = [b for b in bytes if b.data != 0]
    return _create_instructions_from_bytes(mutable_bytes, nonzero_bytes)


def _convert_add_schema_command_to_instructions(
    a: AddSchemaCommand, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    abs_offset = _find_next_schema_byte_offset(mutable_bytes)
    byte = AddressedByte(abs_offset >> 5, abs_offset & 31, a.data, a.label)
    return _create_instructions_from_bytes(mutable_bytes, [byte])


def _get_delete_command_for_byte(
    byte: AddressedByte, mutable_bytes: list[AddressedByte]
) -> Instruction:
    index_to_delete = mutable_bytes.index(byte)
    mutable_bytes.pop(index_to_delete)
    return _get_delete_instruction(index_to_delete)


def _convert_delete_command_to_instruction(
    d: DeleteCommand, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    if d.address is None:
        if not mutable_bytes:
            return []
        return [_get_delete_command_for_byte(mutable_bytes[0], mutable_bytes)]
    bytes_to_delete = [b for b in mutable_bytes if b.address == d.address]
    return [_get_delete_command_for_byte(b, mutable_bytes) for b in bytes_to_delete]


def _convert_command_to_instructions(
    c: Command, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    match c:
        case AddCommand():
            return _convert_add_command_to_instructions(c, mutable_bytes)
        case AddSchemaCommand():
            return _convert_add_schema_command_to_instructions(c, mutable_bytes)
        case DeleteCommand():
            return _convert_delete_command_to_instruction(c, mutable_bytes)


def convert_commands_to_instructions(
    commands: list[Command], bytes: list[AddressedByte]
) -> str:
    mutable_bytes = sorted(
        copy.deepcopy(bytes), key=lambda b: get_absolute_byte_offset(b)
    )
    instructions = []
    for command in commands:
        instructions.extend(_convert_command_to_instructions(command, mutable_bytes))
    return "\n".join(instructions)
