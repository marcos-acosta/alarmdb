# AlarmDB

AlarmDB is a word-addressed, schema-driven row-based database backed by the iOS Clock app.

It can be interfaced via NyQL, a bespoke SQL-like query language.

## Address space

We use a 5-bit architecture i.e. there are 32 possible addresses, from `0x00000` to `0x11111`. Each address refers to a word of 32 bytes. Bytes within the word are referenced by their byte offset.

Conceptually, one memory address = one word = 32 bytes = one "row" of data in the database.

## Encoding

An iOS alarm contains the following parameters:

- `Time` (e.g. `"12:15 PM"`)
- `Repeat Days` (e.g. `["Monday", "Friday"]`)
- `Is Enabled` (`"Yes"/"No"`)
- `Allows Snooze` (`"Yes"/"No"`)
- `Label` (arbitrary string)

Note that we _could_ store all our data in the label, but that would be obviously cheating.

### Addressing

There are `24*60=1440` possible alarm times, which works out to 10.49 bits. AlarmDB uses the 10 full (i.e. least significant) bits for addressing: the first 5 bits encode the address of the word (`0-31`), and the next 5 bits encode the byte offset within the word (`0-31`).

### Encoding the data byte

To construct a single byte of data, we use the `Repeat Days`, `Is Enabled`, and `Allows Snooze` properties of an iOS alarm. The latter two are simple booleans i.e. one bit each.

`Repeat Days` would seem to be equally simple, i.e. each weekday is treated as a bit (on or off), which would give us seven bits of data. However, due to a [bug in iOS Shortcuts](https://discussions.apple.com/thread/256008048?sortBy=rank), a Shortcut that tries to do anything with the `Repeat Days` of an alarm which has _exactly one_ repeat day will cause the Shortcut to fail. For this reason, we are forced to sacrifice one bit (I chose the Lord's day, Sunday) to guard against this possibility. Essentially, if the remaining six bits (days) is going to have a popcount of `1`, then the seventh bit (Sunday) flips on.

Since the Lord's day is exempt from doing work, we have six bits from `Repeat Days` and two bits from the other two booleans, which gives us one even byte.

### Encoding the schema

Since we're only using the bottom 10 full bytes of the alarm address space, `0x10000000000-0x10110100000` i.e. 5:04PM-11:59PM is effectively "reserved" and we can use it to safely store the schema of the database separately from the data. In reality, only `0x10000000000-0x10000011111` (5:04PM-5:36PM) would be used because each record (word) has up to 32 bytes, so there can be at most 32 fields.

The bits of a field's byte are broken up into two parts:

- Bits 0-2: Data type
- Bits 3-7: Length in bytes minus 1 (i.e. `0x00000 -> 1` and `0x11111 -> 32`)

Despite allowing up to 8 data types, AlarmDB currently only supports five:

- `TEXT` (`0x000`): Parsed as UTF-8, truncated by null terminator (`\x00`)
- `UINT` (`0x001`): Parsed as an unsigned int
- `INT` (`0x010`): Parsed as a two's complement signed int
- `TIMESTAMP` (`0x011`): Parsed as an unsigned int and treated as a POSIX timestamp
- `BOOLEAN` (`0x100`): `false` if every bit is off, `true` otherwise

Here I caved slightly and used the alarm's `Label` solely for the purpose of naming the field. There's a way to do it without it (encode the strings in the rest of the reserved address space with a max field name length of 12), but I thought of that too late and no longer have the energy to implement :)

Since the schema is user-defined, each record could be interpreted as a single 32-character string, 32 separate one-byte ints, or anything in between.

## Querying: NyQL

Interfacing with AlarmDB is simple thanks to NyQL, a SQL-like query language. Below are some examples of NyQL queries (note the absence of a `FROM` clause because there is only one table):

```sql
-- Clears all rows and sets the schema for the table
-- Note that the total number of bytes cannot exceed 32
-- (column name, type, number of bytes)
SET SCHEMA
    ("alarm_name", TEXT, 8),
    ("repeat_bitmask", UINT, 1),
    ("hours", INT, 1),
    ("minutes", INT, 1),
    ("enabled", BOOLEAN, 1),
    ("allows_snooze", BOOLEAN, 1),
    ("timestamp_added", TIMESTAMP, 4);

-- Get the current schema
GET SCHEMA;

"""
Outputs ->
  col_name,type,length_bytes
  alarm_name,TEXT,16
  repeat_bitmask,UINT,1
  hours,INT,1
  minutes,INT,1
  enabled,BOOLEAN,1
  allows_snooze,BOOLEAN,1
  timestamp_added,TIMESTAMP,4
"""

-- Add rows
INSERT VALUES
    ("work", 62, 8, 15, TRUE, FALSE, 1778904247),
    ("do laundry", 8, 18, 0, TRUE, TRUE, 1778904372),
    ("write readme", 0, 19, 45, FALSE, TRUE, 1778905161);

-- Get all rows
SELECT *;

"""
Outputs ->
  alarm_name,repeat_bitmask,hours,minutes,enabled,allows_snooze,timestamp_added
  work,62,8,15,True,False,2026-05-16 00:04:07
  do laundry,8,18,0,True,True,2026-05-16 00:06:12
  write readme,0,19,45,False,True,2026-05-16 00:19:21
"""

-- More complex SELECT queries

SELECT AVG(hours) AS avg_hours, enabled GROUP BY enabled HAVING enabled;

"""
Outputs ->
  avg_hours,enabled
  13.0,True
"""

SELECT alarm_name AS morning_alarm_names WHERE hours < 12 AND enabled;

"""
Outputs ->
  morning_alarm_names
  work
"""

SELECT alarm_name, hours, minutes ORDER BY minutes DESC LIMIT 2;

"""
Outputs ->
  alarm_name,hours,minutes
  write readme,19,45
  work,8,15
"""

-- Delete by condition
DELETE WHERE alarm_name = "write readme";

SELECT *;

"""
Outputs ->
  alarm_name,repeat_bitmask,hours,minutes,enabled,allows_snooze,timestamp_added
  work,62,8,15,True,False,2026-05-16 00:04:07
  do laundry,8,18,0,True,True,2026-05-16 00:06:12
"""

-- Update by condition
UPDATE SET alarm_name = "pick up laundry", hours = 20 WHERE alarm_name = "do laundry";

SELECT *;

"""
Outputs ->
  alarm_name,repeat_bitmask,hours,minutes,enabled,allows_snooze,timestamp_added
  work,62,8,15,True,False,2026-05-16T00:04:07
  pick up laundry,8,20,0,True,True,2026-05-16T00:06:12
"""

-- Set a new schema (this also wipes the database)
SET SCHEMA ("name", TEXT, 8), ("age", INT, 1);
```

## Running AlarmDB

AlarmDB is easy-to-use, open-source, and free. To get started, download the following iOS shortcuts:

- [AlarmDB write](https://www.icloud.com/shortcuts/8b1ddb45834c4ab4b43f1d358f04ae03) (called internally)
- [AlarmDB read](https://www.icloud.com/shortcuts/a1d47283e9a34785aed1c658ef81f2fb) (called internally)
- [AlarmDB](https://www.icloud.com/shortcuts/0b5d7a254ce2484299ae7476e36c45a8) (entrypoint)

You will need to update the `cd` command in the `Run Shell Script` action of the `AlarmDB` shortcut so it can navigate to your local copy of this repo.

It's convenient to add the `AlarmDB` shortcut to Quick Actions so that you can run NyQL anywhere by selecting the text and going `Services > AlarmDB`.

### Recommended IDEs

- MacOS Notes app

## Running on mobile

AlarmDB was developed on desktop, but it can be run on mobile if the `Run Shell Script` action of the `AlarmDB` shortcut is replaced with a `Run Script Over SSH` action.

## Other notes

### NULLs

There is no concept of a `NULL` value in AlarmDB. As long as there is at least one alarm (byte) in an address, it is assumed that the word at that address represents a full record. If there are no alarms in the byte offsets where the schema expects there to be, then they are assumed to be all zero. In other words, the "default" value for a missing int is `0`, `""` for missing strings, `false` for missing booleans, and `January 1, 1970` for missing timestamps.

### Serialization limitations

The `AlarmDB read` shortcut pipe-delimits alarm data, so `|` cannot be used in the name of any field in the schema (since those get written directly into the alarm's label).