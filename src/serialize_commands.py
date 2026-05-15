from nyql.engine import AddCommand, DeleteCommand, Command
import math

ENCODED_DAYS_OF_WEEK = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]
SUNDAY = "sunday"


def _serialize_delete_command(d: DeleteCommand):
    return f"DELETE|{d.index + 1}"


def _address_to_time(address: int) -> str:
    hours = math.floor(address / 60)
    minutes = address % 60
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


def _serialize_add_command(a: AddCommand) -> list[str]:
    time = _address_to_time(a.address)
    repeat_days = _data_to_repeat_days(a.data)
    allow_snooze = _data_to_allow_snooze(a.data)
    should_disable = _should_disable(a.data)
    serialized_add_command = (
        f"ADD|{time}|{repeat_days}|{allow_snooze}|{a.label or 'Alarm'}"
    )
    commands = [serialized_add_command]
    if should_disable:
        commands.append(f"DISABLE|{a.index + 1}")
    return commands


def _serialize_command(c: Command) -> str:
    match c:
        case AddCommand():
            return "\n".join(_serialize_add_command(c))
        case DeleteCommand():
            return _serialize_delete_command(c)


def serialize_commands(commands: list[Command]) -> str:
    return "\n".join([_serialize_command(c) for c in commands])
