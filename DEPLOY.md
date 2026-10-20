# Deploying Soar Scheduler to PythonAnywhere (free tier)

PythonAnywhere's free "Beginner" plan runs this app well: it has a **persistent
disk**, so your SQLite database and uploaded forecast images survive restarts, and
you get a stable URL at `https://YOURNAME.pythonanywhere.com`.

The app is already deploy-ready:
- `wsgi.py` is the production entry point.
- On first visit it **auto-creates and seeds** the database (demo club, members,
  fields) — no shell commands required to get a working demo.
- Email is stubbed to the in-app outbox, and the app makes no outbound network
  calls, so the free tier's internet whitelist doesn't affect it.

Replace `YOURNAME` with your PythonAnywhere username throughout.

---

## 1. Create an account
Sign up for a free account at <https://www.pythonanywhere.com> (Beginner plan).

## 2. Get the code onto PythonAnywhere
Open a **Bash console** (Consoles tab → "Bash").

**If the project is on GitHub:**
```bash
git clone https://github.com/YOURUSER/click_n_glide.git ~/click_n_glide
```

**Otherwise, upload a zip:** on your machine, zip the project *without* `.venv`
and `instance` (both are rebuilt on the server):
```bash
# run locally, from the project's parent directory
zip -r click_n_glide.zip click_n_glide -x '*/.venv/*' '*/instance/*' '*/__pycache__/*'
```
Then **Files tab → Upload** the zip, and in the Bash console:
```bash
cd ~ && unzip click_n_glide.zip
```

## 3. Create a virtualenv and install dependencies
```bash
cd ~/click_n_glide
python3.10 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Generate a secret key (copy the output for step 6)
```bash
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

## 5. Create the web app
**Web tab → Add a new web app →**
- Domain: accept `YOURNAME.pythonanywhere.com`
- Framework: **Manual configuration** (⚠️ *not* the "Flask" quick-start — this app
  uses an application factory)
- Python version: **3.10** (match the venv you created)

## 6. Point the web app at the project
On the **Web tab**, set:

| Setting | Value |
|---|---|
| **Source code** | `/home/YOURNAME/click_n_glide` |
| **Working directory** | `/home/YOURNAME/click_n_glide` |
| **Virtualenv** | `/home/YOURNAME/click_n_glide/.venv` |

Then click the **WSGI configuration file** link (e.g.
`/var/www/YOURNAME_pythonanywhere_com_wsgi.py`), **delete everything in it**, and
replace with:

```python
import os, sys

project = "/home/YOURNAME/click_n_glide"
if project not in sys.path:
    sys.path.insert(0, project)

os.environ["SECRET_KEY"] = "PASTE-THE-KEY-FROM-STEP-4-HERE"
# os.environ["AUTO_SEED"] = "0"   # uncomment to start with an EMPTY database

from wsgi import application   # noqa: E402
```
Save it.

## 7. (Recommended) Serve static files efficiently
On the **Web tab → Static files**, add a mapping:

| URL | Directory |
|---|---|
| `/static/` | `/home/YOURNAME/click_n_glide/app/static` |

(Uploaded images are *not* static — they're served through a login-gated route, so
don't map `/uploads/`.)

## 8. Reload and visit
Click the big green **Reload** button, then open
`https://YOURNAME.pythonanywhere.com`.

Log in with the demo admin:
- **Email:** `alex@soardemo.club`  **Password:** `glide1234`

(Full demo login list is in `README.md`.)

---

## After it's live

**Change the demo password / lock it down.** Log in as the admin and change the
password under **Settings**. For a real club you'd delete the demo members and add
your own from **Admin → Add member**.

**Reset the demo data** (wipe sign-ups/uploads back to the seeded state):
```bash
cd ~/click_n_glide
rm -f instance/soar.db
rm -f instance/uploads/*
# then click Reload on the Web tab — first visit re-seeds
```
Or, equivalently: `.venv/bin/flask --app "app:create_app" init-demo`

**Optional — daily reminder emails.** The free tier includes one daily scheduled
task. **Tasks tab → add a daily task** with this command:
```bash
cd /home/YOURNAME/click_n_glide && .venv/bin/flask --app "app:create_app" send-reminders
```
(Reminders are queued into the in-app outbox, viewable at **Admin → Email outbox**.
To actually *send* mail you'd wire `app/scheduling.py:queue_email` to an SMTP
provider — see "Sending real email" below.)

## Free-tier things to know
- **3-month renewal:** PythonAnywhere asks you to click "run until 3 months from
  today" periodically (they email a reminder). One click keeps the site up.
- **Limited CPU/RAM:** fine for a demo and a small club; not for heavy traffic.
- **No background workers:** only the single daily scheduled task above.

## Updating the deployed app later
```bash
cd ~/click_n_glide
git pull                      # or re-upload changed files
.venv/bin/pip install -r requirements.txt   # if deps changed
```
Then click **Reload** on the Web tab. Your database and uploads are untouched by a
code update (they live in `instance/`, which isn't overwritten).

---

## Sending real email (optional, later)
Currently reminders, staffing alerts, and internal messages are recorded in the
`EmailOutbox` table instead of being sent. To send for real, implement SMTP inside
`queue_email()` in `app/scheduling.py` (e.g. via `smtplib` or a transactional-email
API). Note: PythonAnywhere's **free tier blocks most outbound connections** — you'd
need a paid plan (which lifts the whitelist) or a different host to send live email.

## Deploying elsewhere instead
`wsgi.py` works with any WSGI host. For a Docker/Procfile host (Render, Fly.io,
Railway) the run command is:
```
gunicorn wsgi:application
```
Set `SECRET_KEY` as an environment variable there. Remember that hosts with an
**ephemeral filesystem reset the SQLite DB and uploads on redeploy** — attach a
persistent volume/disk if you need the data to survive.
