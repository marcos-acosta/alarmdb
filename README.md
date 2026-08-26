# AlarmDB

AlarmDB is a memory-addressed, schema-driven row-based database backed by the Apple Clock app. It also comes with NyQL, a bespoke SQL-like query language for interfacing with AlarmDB.

Read the full writeup [here](https://marcos.ac/blog/nyql)!

## Example queries

Interfacing with AlarmDB is simple thanks to NyQL, a SQL-like query language. In the examples below, we perform "Alarmception" and encode alarm data as alarms in AlarmDB. Note the absence of the `FROM` clause, as there is only one table.

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

## Installing AlarmDB

AlarmDB is easy-to-use, open-source, and free. To get started, clone this repo and install the required packages with `uv sync`. Then, install the following Shortcuts:

- [NyQL write](https://www.icloud.com/shortcuts/96feeb006b4f444f9d140345c8b7e6fe) (called internally)
- [NyQL read](https://www.icloud.com/shortcuts/6b29e8de9a184dcfa31d205a0bdd2846) (called internally)
- [NyQL](https://www.icloud.com/shortcuts/c2dc76296bf04a0f9e5527891e1d4147) (entrypoint)

Notes:
- You will need to update the placeholder `cd /path/to/your/alarmdb` in the `Run Shell Script` action of the `NyQL` shortcut to point to your local copy of this repo
- If running on iOS, the `Run Shell Script` will need to be replaced with an equivalent `Run Script Over SSH` action
- It's convenient to add the `AlarmDB` shortcut to Quick Actions so that you can run NyQL anywhere by highlighting the text, right clicking, and `Services > NyQL`

### Recommended IDEs

- Notes app
- Messages app
