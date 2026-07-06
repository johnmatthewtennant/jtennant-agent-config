---
name: apple-calendar
description: Read, search, or write Apple Calendar on macOS. Use this when the user asks about Apple Calendar, Calendar.app, local calendar events, today’s Apple Calendar schedule, finding events, or creating/updating/deleting events in Apple Calendar rather than Google Calendar.
---

Use EventKit for Apple Calendar reads, searches, and writes. It handles permissions, recurrence expansion, calendars, and identifiers more reliably than direct SQLite or Calendar.app AppleScript.

For targeted writes, enumerate calendars first, then select the intended calendar before mutating.

The local SQLite DB at `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` can be useful for read-only debugging, but never mutate it directly.
