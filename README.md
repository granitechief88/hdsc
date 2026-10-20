# Soar Scheduler

A gliding-club day-board scheduler inspired by [Click n' Glide](https://clicknglide.com).
Members sign up, ahead of each flying day, for the role they'll fill (instructor,
student, tug/winch driver, solo, etc.). Instructors open a chosen number of student
slots; overflow students queue on a waiting list and are **promoted automatically**
as capacity opens up.

Built with Flask + SQLAlchemy + SQLite, server-rendered (no build step).

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Create the database and load a demo club
.venv/bin/flask --app "app:create_app" init-demo

# Run
.venv/bin/python run.py
# open http://127.0.0.1:5000
```

### Demo logins (password `glide1234` for all)

| Email                 | Role                         |
|-----------------------|------------------------------|
| `alex@soardemo.club`  | Administrator + instructor   |
| `ivy@soardemo.club`   | Instructor                   |
| `sam@soardemo.club`   | Dual student                 |
| `tom@soardemo.club`   | Tug driver                   |
| `wendy@soardemo.club` | Winch driver                 |

The board opens on **today**. Navigate to **Mon 19 Oct 2026** (or the next weekday
after you seed) to see a pre-built example with a full student slot and a waiting list.
Weekends show *Full Day Group* fields instead of *Booked-Flying*.

## What it does

- **Day board** — per-day sign-up grid in three columns, different field sets for
  weekdays vs weekends. You only see sign-ups your roles permit.
- **Instructor-driven capacity** — an instructor chooses how many students to take;
  that opens exactly that many student slots.
- **Automatic waiting lists** — when slots are full, students queue; they're promoted
  (oldest first) when an instructor adds capacity or an active student drops out, and
  demoted back if capacity shrinks.
- **Per-sign-up comments**, removable sign-ups, and a **per-day forum** that
  accepts **image attachments** (post MM5 / RASP soaring-forecast images, etc.).
- **Events** — theory lessons, maintenance days, socials; one-click sign-up with
  optional capacity.
- **Internal mailbox** — message an individual or a group (all instructors, all
  students, everyone).
- **Automatic emails** (recorded in the admin *Email outbox* instead of being sent):
  2-day reminders, and staffing alerts to instructors when students are waiting.
- **Admin** — manage members and roles; **add/edit/remove the day-board sign-up
  fields** themselves (type, group links, weekday/weekend, allowed roles, column,
  order, caps); and view the email outbox. New members get a one-time activation
  link to set their password.

## Project layout

```
app/
  __init__.py        app factory, blueprint registration, `init-demo` CLI command
  extensions.py      db + login manager singletons
  models.py          Club, Member, Role, FieldDef, Signup, Event, Message, ...
  scheduling.py      capacity, waiting-list rebalance, email stub + notifications
  views_auth.py      login / activation / settings
  views_board.py     the day board and all sign-up actions
  views_events.py    events
  views_messages.py  internal mailbox
  views_admin.py     members, roles, fields, outbox
  seed.py            demo club data
  templates/  static/
run.py               dev entry point
```

## How the field model works

Each board column is a `FieldDef` with a `kind`:

- `LIST` — simple list (Winch Driver, Fly own glider, …), optionally capped.
- `PROVIDER` — instructors who open student slots (pick a count when signing up).
- `CONSUMER` — students who fill slots opened by providers in the same `group_key`.
- `WAITING` — overflow queue for that group's consumer field.

Capacity of a consumer field = sum of slots offered by its group's providers on that
day. `scheduling.rebalance_group()` keeps the active/waiting split in line with
capacity after every change. Fields, roles, and their role restrictions are all data,
so a club can be reconfigured without code changes — admins do exactly this from
**Admin → Sign-up fields** (add / edit / delete fields on the day board).

Forum image attachments are stored under `instance/uploads/` with random names and
served through a login-gated route (`/uploads/<name>`) that checks the file belongs
to the member's club; allowed types are PNG/JPG/GIF/WebP, capped at 12 MB each.

## Notes / next steps

- Email is stubbed to the `EmailOutbox` table so the automatic-notification behaviour
  is visible without an SMTP server. Wire `scheduling.queue_email` to real SMTP to send.
- Reminders run on demand from **Admin → Email outbox → Run 2-day reminders**; in
  production schedule `scheduling.generate_reminders()` as a daily cron job.
- Single-club by default; the schema carries `club_id` throughout so multi-club /
  multi-tenant support is a small extension.
- This is a development setup. For real deployment use a production WSGI server
  (gunicorn/uWSGI), set `SECRET_KEY`, and consider Postgres.
