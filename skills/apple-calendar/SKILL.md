---
name: apple-calendar
description: Read or write Apple Calendar on macOS. Use this when the user asks about Apple Calendar, Calendar.app, local calendar events, today’s Apple Calendar schedule, or creating/updating/deleting events in Apple Calendar rather than Google Calendar.
---

Read Apple Calendar directly from the local SQLite DB at `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` using read-only sqlite connections.

Use `CalendarItem` joined to `Calendar` for events. Apple timestamps are seconds since `2001-01-01 00:00:00 UTC`.

Write Apple Calendar events through Calendar.app AppleScript with `osascript`, for example `tell application "Calendar"` and `make new event at end of events of targetCalendar`.

To target a specific account or calendar, enumerate Calendar.app calendars first, then select the intended calendar by unique name or UID before writing.
