# Host Ring for free with Render and Neon

Use Render's **Free web service** for this Docker/Flask application and Neon's
**Free PostgreSQL** plan for its data. This is a suitable setup for sharing the
current demo. Choose the Free plans and stay within their usage allowances;
free hosting does not mean unlimited resources or always-on service.
[Render free hosting](https://render.com/docs/free),
[Neon plans](https://github.com/neondatabase/website/blob/main/content/docs/introduction/plans.md).

```text
Browser → HTTPS on Render → Flask/Gunicorn → PostgreSQL on Neon
```

The repository already contains the application Dockerfile. The new
[`render.yaml`](../render.yaml) supplies Render's service settings and asks for
your database credentials. The Dockerfile runs [`app/start.sh`](../app/start.sh)
to initialize the existing `users` table before starting Gunicorn. Social and
arena state is seeded automatically on first use.

You need a GitHub account with this repository, a Render account, and a Neon
account. The account setup and database credentials must be completed in those
services. No AWS credentials, ECR image, Nginx server, ALB, or Terraform deployment
are needed for this hosting route.

## 1. Put the current website on GitHub

Your current application edits include new Python modules and static assets.
Render must receive those files together with the configuration.

The existing GitHub Actions workflow deploys to AWS on pushes to `main`.
Use a separate `free-hosting` branch to publish this demo without triggering
that deployment. Run these commands yourself from the repository root:

```bash
git switch -c free-hosting
git add render.yaml docs/free-hosting.md docs/sportspace-database.md
git add app/Dockerfile app/start.sh app/.dockerignore app/requirements.txt
git add app/app.py app/db.py app/social.py app/arena.py
git add app/static app/tests/*.py
git diff --cached --stat
git diff --cached
git commit -m "Prepare Ring demo for free Render hosting"
git push -u origin free-hosting
```

Review the staged diff before committing. Keep passwords, `.env` files, AWS
credentials, Terraform state, and Python bytecode out of the commit. If you
already have a `free-hosting` branch, switch to it with `git switch free-hosting`.
These instructions do not change or remove any running AWS resources.

## 2. Create the PostgreSQL database in Neon

1. Open the [Neon console](https://console.neon.tech/) and sign up or sign in.
2. Create a project named `byte-ring-demo` on the **Free** plan.
3. Select a region near your app. The supplied Render configuration uses
   Singapore; choose a nearby Neon region that the console offers.
4. Open **Connect**, select the database and role, and record the host,
   database name, username, and password privately.
5. For this small two-worker app, use the **direct** connection host to start.
   Neon also offers pooled connections for larger numbers of connections.

Neon provides these details in its connection string.
[Neon's connection guide](https://github.com/neondatabase/website/blob/main/content/docs/get-started/connect-neon.md).

For example, this **fake** URL:

```text
postgresql://example_user:example_password@ep-example.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

maps to the following Render variables:

| Variable | Value to enter |
| --- | --- |
| `DB_HOST` | Neon hostname only, such as `ep-example.ap-southeast-1.aws.neon.tech` |
| `DB_NAME` | The selected database name, often `neondb` |
| `DB_USER` | The selected Neon role name |
| `DB_PASSWORD` | The actual password from Neon |
| `DB_PORT` | `5432` (already configured) |
| `PGSSLMODE` | `require` (already configured) |
| `PORT` | `8080` (already configured) |

Use the actual password from the console, rather than a percent-encoded password
copied from a URL. `DB_HOST` must not include `postgresql://`, credentials, a
path, or URL query parameters. This app currently reads the separate `DB_*`
variables; setting only `DATABASE_URL` will not configure it.

`PGSSLMODE=require` makes the PostgreSQL driver require an encrypted connection.
[PostgreSQL environment variables](https://www.postgresql.org/docs/17/libpq-envars.html).
Leave `SPORTSPACE_SOCIAL_DB` **unset** so social and arena data use PostgreSQL.

## 3. Deploy using the supplied Render Blueprint

1. Open the [Render dashboard](https://dashboard.render.com/) and sign in.
2. Choose **New → Blueprint** and connect your GitHub repository.
3. Select the **free-hosting** branch and use `render.yaml` as the Blueprint file.
4. Review the resources: one Docker web service named `byte-ring-demo`, with
   compute plan **Free**. Rename it in `render.yaml` first if needed.
5. Fill in the prompted `DB_HOST`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` values
   from Neon, then deploy.
6. Wait for a successful build and service deployment. Inspect the service's
   logs if it fails.

The Blueprint sets the Docker context to `app`, the Dockerfile to
`app/Dockerfile`, and the health check to `/health`. It runs table initialization
through the Dockerfile's startup script because Gunicorn does not execute the
`if __name__ == "__main__"` block in `app.py`.
[Render Blueprint reference](https://render.com/docs/blueprint-spec).

Keep credentials in Render's environment settings. No secrets belong in
`render.yaml`. Render builds the image directly from this repository.
[Docker on Render](https://render.com/docs/docker).

### If you selected New Web Service instead

The **New Web Service** form uses manual settings. Enter the following values:

| Field | Value |
| --- | --- |
| Name | `byte-devops` (or another available name) |
| Language | `Docker` |
| Branch | `free-hosting` |
| Region | `Singapore` |
| Root Directory | `app` |
| Compute | `Free` |

Add the seven environment variables listed in step 2, using your actual Neon
connection details for the four `DB_*` credentials. Create the Neon database
before deploying if you have not already done so.

Expand **Advanced** and set:

| Field | Value |
| --- | --- |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context Directory (if shown) | `.` |
| Health Check Path | `/health` |
| Docker Command | Leave empty to use the Dockerfile's startup script |

These Docker paths are relative to the selected `app` root directory.
[Render root-directory settings](https://render.com/docs/monorepo-support).
If you previously entered a command, clear it in the service's **Settings →
Build & Deploy → Docker Command** field. The Dockerfile now invokes
`/bin/sh /app/start.sh`, which initializes the users table and starts Gunicorn.
It listens on `PORT` (default `8080`) and uses `WEB_CONCURRENCY` workers
(default `2`; Render can set `1` for its Free service).

Click **Deploy web service** after entering all database values. Continue to step 4 once the
deployment succeeds. The repository's `render.yaml` is used by Blueprint
deployments; update settings for this manually created service in its dashboard.

## 4. Open and verify the website

Use the actual URL shown in your Render service dashboard. For example:

```text
https://YOUR-SERVICE.onrender.com/ring
```

`/sportspace` also opens the website. `/` currently returns application JSON,
so share the URL ending in **`/ring`**.

Check the deployment from a terminal, replacing the example hostname:

```bash
curl --fail --show-error https://YOUR-SERVICE.onrender.com/health
curl --fail --show-error https://YOUR-SERVICE.onrender.com/health/db
curl --show-error --include https://YOUR-SERVICE.onrender.com/api/friends
```

Expected results: healthy process, connected database, and a `401` sign-in response
from `/api/friends` without a session. A `404` means the friend routes are not
deployed. Open `/ring`, register two separate accounts, send and accept a friend
request, then reload to check persistence. Test **Edit profile → Who can see your
photos? → Friends only** with a third account that is not a friend.
Configure email delivery using [password-reset.md](password-reset.md) to test
Forgot password with an actual email verification code.

## 5. Publish future changes

Commit and push application updates to the branch linked to the Render service.
Enable automatic deploys for that branch in the service settings, or use
**Manual Deploy → Deploy latest commit** in the dashboard. Review a change to
`render.yaml` through the Blueprint before applying it.

The AWS GitHub Actions workflow is independent of Render. Merging or pushing to
`main` can still trigger the existing AWS deployment.

## Free-plan limits and costs

| Component | Free setup |
| --- | --- |
| Application hosting | Render Free web service |
| Database | Neon Free PostgreSQL project |
| Public address | Render-provided `onrender.com` URL |
| HTTPS | Render-managed certificate |
| Custom domain purchase | Optional; not included in this setup |

Render's free service sleeps after 15 minutes without inbound traffic and takes
about a minute to wake. A workspace has 750 free instance hours per month shared
across its services. Bandwidth and build minutes also have limits; overages may
be billed when a payment method is present. Free services cannot attach a
persistent disk. Render's own free PostgreSQL database expires after 30 days,
which is why this setup uses Neon.
[Render's free-plan details](https://render.com/docs/free).

Neon's Free plan has monthly compute and network-transfer quotas and a storage
limit. Check the current allowances in the console and stay on the Free plan.
Its database can sleep while idle; stored data survives that sleep. Monitor
usage especially if you upload many avatars or generate frequent API requests.
[Neon Free plan quotas](https://github.com/neondatabase/website/blob/main/content/faqs/free-plan-limits-and-quotas.md).

This deployment does not stop existing AWS billing. Any EC2, RDS, ALB, or other
resources already provisioned continue to incur their applicable charges until
you separately remove them. Do not run Terraform for this free-hosting setup.

## What this demo supports

- Social posts, player profiles, avatars, awards, and arena state live in Neon.
- Bookings and tournament registration demos remain in each browser's storage.
- Visitors register separate authenticated accounts, send and accept friend
  requests, and restrict their photos to accepted friends. Real booking and
  payment workflows are not implemented.
- Avatars are stored as image data in PostgreSQL. Other demo images load from
  external URLs.

Sample match and award content remains a demonstration. Player accounts cannot
use the demo organizer actions. See
[the website README](../app/static/sportspace/README.md) and
[the current database design](sportspace-database.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Home page shows JSON | Open `/ring` or `/sportspace`. |
| First visit takes a while | Render's free instance may be waking from sleep. |
| `COPY` fails during the Docker build | Use Docker context `app` and Dockerfile `app/Dockerfile`, as in the Blueprint. |
| `ModuleNotFoundError` for `social` or `arena` | Commit and push `social.py`, `arena.py`, and the current Dockerfile. |
| Website assets return 404 | Commit and push `app/static`, including all CSS, JS, and icons. |
| Database connection targets localhost | Configure all `DB_*` variables; `DATABASE_URL` alone is ignored. |
| SSL or connection error | Verify the Neon hostname, raw password, database, role, and `PGSSLMODE=require`; inspect Render logs. |
| A whole quoted startup command ends with `not found` | Push the updated Dockerfile and `app/start.sh`, then clear Render's Docker Command override and redeploy. |
| `relation "users" does not exist` | Clear any old Docker Command override so the Dockerfile runs `start.sh` and initializes the table. |
| Data disappears after a restart | Remove `SPORTSPACE_SOCIAL_DB`; it selects local SQLite instead of Neon. |
| `/health` passes but social features fail | Check `/health/db` and the API endpoints; `/health` tests only the process. |
| Startup reports a database timeout | Check Neon status and credentials; retry the deploy after the database wakes. |
| Service is suspended | Check Render and Neon usage dashboards for exhausted free quotas. |

For optional local Docker verification with your own database environment file
stored outside the repository:

```bash
docker build -t byte-ring-demo ./app
docker run --rm --env-file /path/to/private/database.env -e PORT=8080 -p 8080:8080 byte-ring-demo
```

The private environment file should contain the `DB_*` values and
`PGSSLMODE=require`. Open `http://localhost:8080/ring` and stop with Ctrl+C.
Creating a fresh Neon database does not migrate existing local or AWS data.
