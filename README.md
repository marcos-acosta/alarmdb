# AlarmDB

AlarmDB is a word-addressed, schema-driven record store backed by the iOS Clock app.

## Address space

We use a 5-bit architecture i.e. there are 32 possible addresses, from `0x00000` to `0x11111`.

Each address is a word with 32 bytes.

## Encoding

An iOS alarm contains the following parameters:

- `Time` (e.g. `"12:15 PM"`)
- `Repeat Days` (e.g. `["Monday", "Friday"]`)
- `Is Enabled` (`"Yes"/"No"`)
- `Allows Snooze` (`"Yes"/"No"`)
- `Label` (arbitrary string)

Note that we _could_ store all our data in the label, but that would take all the fun out of it.

### Addressing

There are `24*60=1440` possible alarm times, which works out to 10.49 bits. AlarmDB uses the 10 full (i.e. least significant) bits for addressing: the first 5 bits encode the address of the word (`0-31`), and the next 5 bits encode the byte offset within the word (`0-31`). We treat each word as a record.

Note that, unlike a traditional computer where all the empty bytes are "there" by default, empty bytes are _implicit_ in AlarmDB, that is, there's just no alarm for it. For that reason, we have to explicitly encode the byte offset.

### Encoding the data byte

To construct a single byte of data, we use the `Repeat Days`, `Is Enabled`, and `Allows Snooze` properties of an iOS alarm. The latter two are simple booleans i.e. one bit each.

`Repeat Days` would seem to be equally simple, i.e. each weekday is treated as a bit (on or off), which would give us seven bits of data. However, due to a [bug in iOS Shortcuts](https://discussions.apple.com/thread/256008048?sortBy=rank), a Shortcut that tries to do anything with the `Repeat Days` of an alarm which has _exactly one_ repeat day will cause the Shortcut to fail. For this reason, we are forced to sacrifice one bit (I chose the Lord's day, Sunday) to guard against this possibility. Essentially, if the remaining six bits (days) is going to have a popcount of `1`, then the seventh bit (Sunday) flips on.

Since the Lord's day is now exempt from doing work, we have six bits from `Repeat Days` and two bits from the other two booleans, which gives us one even byte.

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

Here, I slightly caved and use the alarm's `Label` solely for the purpose of naming the field. There's a way to do it without it, but I didn't want to :)

Since the schema is user-defined, each record could be interpreted as a single 32-character string, 32 separate one-byte ints, or anything in between.

### Notes

One implication of this setup is that there is no concept of a `NULL` value. As long as there is at least one alarm at an address, it is assumed that the word at that address represents a full record. If there are no alarms in the byte offsets where the schema expects there to be, then they are assumed to be all zero. In other words, the "default" value for a missing int is `0`, `""` for missing strings, `false` for missing booleans, and `January 1, 1970` for missing timestamps.

## Input format

In order to parse and process iOS alarm data, AlarmDB expects it in a certain serialized format. I settled on a relatively naive approach i.e. a pipe-delimited list of the following:

- The number of alarms
- Each clock's `Time`
- Each clock's `Is Enabled`
- Each clock's `Allows Snooze`
- Each clock's `Label`
- Each clock's space-delimited `Repeat Days`
