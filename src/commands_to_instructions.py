from nyql.engine import AddCommand, DeleteCommand, AddSchemaCommand, Command
from parse_alarms import AddressedByte, get_absolute_byte_offset
import copy
import math
from typing import Tuple
import bisect

ENCODED_DAYS_OF_WEEK = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]
SUNDAY = "sunday"

type Instruction = str

MAX_NUM_BYTES = 1 << 5
MAX_DATA_ADDRESS = (1 << 5) - 1  # 31
SCHEMA_BASE_ADDRESS = 1 << 5  # 32


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
    return _create_instructions_from_bytes(mutable_bytes, bytes)


def _get_instructions_to_wipe_db(
    mutable_bytes: list[AddressedByte],
) -> list[Instruction]:
    instructions = []
    num_bytes = len(mutable_bytes)
    for _ in range(num_bytes):
        instructions.append(_get_delete_instruction(0))
    mutable_bytes = []
    return instructions


def _convert_add_schema_command_to_instructions(
    a: AddSchemaCommand, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    wipe_instructions = _get_instructions_to_wipe_db(mutable_bytes)
    abs_offset = _find_next_schema_byte_offset(mutable_bytes)
    byte = AddressedByte(abs_offset >> 5, abs_offset & 31, a.data, a.label)
    return wipe_instructions + _create_instructions_from_bytes(mutable_bytes, [byte])


def _convert_command_to_instructions(
    c: Command, mutable_bytes: list[AddressedByte]
) -> list[Instruction]:
    match c:
        case AddCommand():
            return _convert_add_command_to_instructions(c, mutable_bytes)
        case AddSchemaCommand():
            return _convert_add_schema_command_to_instructions(c, mutable_bytes)
        case DeleteCommand():
            return []


def convert_commands_to_instructions(
    commands: list[Command], bytes: list[AddressedByte]
) -> list[Instruction]:
    mutable_bytes = sorted(
        copy.deepcopy(bytes), key=lambda b: get_absolute_byte_offset(b)
    )
    instructions = []
    for command in commands:
        instructions.extend(_convert_command_to_instructions(command, mutable_bytes))
    return instructions
