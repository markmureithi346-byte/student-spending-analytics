# Runbook: publishing Plan It on a public HTTPS server

This runbook describes one supported deployment: a single Linux host, the Python
standard library only, SQLite on local disk, and a reverse proxy that terminates
TLS. It is deliberately small. It does not provision DNS, certificates, an
encrypted disk, monitoring or legal review; those remain the operator's
responsibilities.

Nothing here requires Docker, a cloud platform or a third-party Python package.

## 1. What the deployment contains

| Component | Purpose |
| --- | --- |
| `student-spending serve` | The application, bound to `127.0.0.1:8000` |
| Caddy **or** nginx | Public listener, automatic certificates, request limits |
| systemd unit | Restarts the app, applies a strict sandbox and `UMask=0077` |
| `plan-it-prune.timer` | Deletes uploaded analyses older than the retention period |
| `plan-it-backup.timer` | Writes a daily online snapshot to `/var/backups/plan-it` |
| `scripts/backup_planit.py` | Consistent SQLite and file snapshot for backups |

The app never talks to a bank, card network or mobile-money API. It stores the
accounts, plans and uploaded files described in the privacy notice.

## 2. Host prerequisites

- A 64-bit Linux server with a public IPv4 or IPv6 address.
- A DNS record such as `planit.example.com` pointing at that address.
- Python 3.12 or newer, `python3-venv`, `sqlite3` and `rsync`.
- Ports 80 and 443 reachable from the internet. Port 8000 must **not** be
  reachable: the app binds loopback and the proxy forwards to it.
- Enough disk for the sample warehouse, uploads and backups. Uploaded analyses
  are retained for 30 days by default.

The examples use Ubuntu 24.04 and `/opt/plan-it`.

## 3. Create the service account and directories

```bash
sudo adduser --system --group --home /opt/plan-it --shell /usr/sbin/nologin planit
sudo mkdir -p /opt/plan-it /etc/plan-it /var/lib/plan-it /var/log/plan-it
sudo chown -R planit:planit /opt/plan-it /var/lib/plan-it /var/log/plan-it
sudo chmod 750 /var/lib/plan-it /var/log/plan-it
sudo chmod 750 /etc/plan-it
```

The application creates its own data, warehouse, report and upload directories
with mode `0700`, and writes account, upload and metadata files with mode
`0600`. Files copied into the server by hand should follow the same rule; the
environment file is created in section 5.

## 4. Install the application

```bash
sudo -u planit git clone https://github.com/markmureithi346-byte/student-spending-analytics.git /opt/plan-it
cd /opt/plan-it
sudo -u planit python3 -m venv .venv
sudo -u planit .venv/bin/python -m pip install --upgrade pip
sudo -u planit .venv/bin/pip install .
```

`pip install .` installs the SQL schema and the logo as package data, so a wheel
install works outside the checkout. An editable install (`pip install -e .`) is
also fine for a server that tracks the repository.

Build the public sample warehouse once. It is synthetic sample data and is the
dataset shown to signed-out visitors:

```bash
cd /opt/plan-it
sudo -u planit .venv/bin/student-spending --full-refresh
```

## 5. Configure the service

Copy `.env.example` from the repository to `/etc/plan-it/plan-it.env` and fill in
every value. Production refuses to start while any required value is missing.

```bash
sudo install -m 600 -o planit -g planit /opt/plan-it/.env.example /etc/plan-it/plan-it.env
sudoedit /etc/plan-it/plan-it.env
```

The values that must be correct before launch:

| Variable | Notes |
| --- | --- |
| `PLANIT_ENV=production` | Enables the startup guard and production copy |
| `PLANIT_PUBLIC_URL` | Must be the public `https://` origin |
| `PLANIT_HOST=127.0.0.1` | Never bind a public interface |
| `PLANIT_SECURE_COOKIES=1` | Required; refuses to start without it |
| `PLANIT_TRUST_PROXY=1` | Only when your proxy overwrites `X-Forwarded-For` |
| `PLANIT_DATA_DIR`, `PLANIT_WAREHOUSE_DIR`, `PLANIT_REPORTS_DIR`, `PLANIT_LOG_DIR` | Writable by `planit` and nobody else |
| `PLANIT_OPERATOR_NAME`, `PLANIT_OPERATOR_ADDRESS`, `PLANIT_PRIVACY_EMAIL` | Fill the privacy notice and terms |
| `PLANIT_ODPC_REGISTRATION` | Registration number, or the exact status you can defend |
| `PLANIT_HOSTING_PROVIDER` | Provider and location, for the transfer disclosure |
| `PLANIT_EFFECTIVE_DATE` | Date the published policy takes effect |
| `PLANIT_LIABILITY_CAP` | Reviewed wording; not a placeholder |
| `PLANIT_LEGAL_REVIEWED=1` | Set **only** after a qualified Kenyan lawyer reviews both pages |

`PLANIT_POLICY_VERSION` is stored with each account's consent. Bump it when the
notice materially changes; the next sign-in asks the account holder to consent
again.

Check the configuration after installing the unit in the next section. The guard runs on
every start: `sudo systemctl start plan-it` exits with code `2` and writes each missing
value to the journal instead of serving an insecure or incomplete site.

## 6. Run it under systemd

Copy and enable the supplied unit:

```bash
sudo cp /opt/plan-it/deploy/plan-it.service /etc/systemd/system/plan-it.service
sudo systemctl daemon-reload
sudo systemctl enable --now plan-it
sudo systemctl status plan-it --no-pager
```

The unit runs as `planit`, loads `/etc/plan-it/plan-it.env`, binds
`127.0.0.1:8000`, sets `UMask=0077` and allows writes only to
`/var/lib/plan-it` and `/var/log/plan-it`. Adjust `WorkingDirectory`,
`ExecStart` and `ReadWritePaths` if you installed elsewhere.

Follow the log:

```bash
sudo journalctl -u plan-it -f
```

## 7. Put TLS in front of it

Choose **one** proxy. Either one must overwrite `X-Forwarded-For`, because the
app trusts that header only when `PLANIT_TRUST_PROXY=1` and uses it for rate
limiting.

### Caddy (automatic certificates)

```bash
sudo apt install caddy
sudo cp /opt/plan-it/deploy/Caddyfile /etc/caddy/Caddyfile
sudo editor /etc/caddy/Caddyfile       # replace planit.example.com
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy obtains and renews certificates for the hostname. The supplied file caps
request bodies at 4 MB and writes an access log to
`/var/log/caddy/planit-access.log`.

### nginx with certbot

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp /opt/plan-it/deploy/nginx.conf /etc/nginx/sites-available/plan-it
sudo editor /etc/nginx/sites-available/plan-it   # replace hostname and paths
sudo ln -s /etc/nginx/sites-available/plan-it /etc/nginx/sites-enabled/plan-it
sudo nginx -t
sudo certbot --nginx -d planit.example.com
sudo systemctl reload nginx
```

The supplied file redirects HTTP to HTTPS, enables HSTS, caps request bodies at
4 MB and proxies to loopback.

### Firewall

Allow only SSH, HTTP and HTTPS, and confirm that the app port is closed from
outside:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ss -ltnp | grep 8000        # should show 127.0.0.1:8000
```

From another machine, `https://planit.example.com/healthz` should work and
`http://planit.example.com:8000/` should not.

## 8. Verify the running service

```bash
curl -fsS https://planit.example.com/healthz
```

A healthy response is:

```json
{"checks": {"accounts": true, "warehouse": true}, "status": "ok", "version": "..."}
```

A degraded warehouse or an unreadable accounts database returns HTTP `503` and
`"status": "degraded"`. Point your monitoring at this endpoint, and alert on
any non-200 response or a missing response.

Manual checks after the first deploy:

1. Open `/` and confirm the sample dashboard renders without signing in.
2. Create a test account, export it, change its password and delete it.
3. Upload a small CSV and confirm the analysis appears only for that account.
4. Sign out and confirm the session cookie is `Secure`, `HttpOnly` and
   `SameSite=Strict`.
5. Confirm `/privacy` and `/terms` contain your operator details and no Draft
   banner.

## 9. Backups

`scripts/backup_planit.py` uses the SQLite backup API, so it is safe to run while
the service is live. It copies the accounts database, the sample warehouse, every
uploaded warehouse, uploaded source files and reports into one timestamped
directory.

The supplied `plan-it-backup.service` loads the same environment file as the app,
so it uses the correct storage paths. Create the destination and enable the daily
timer:

```bash
sudo install -d -m 700 -o planit -g planit /var/backups/plan-it
sudo cp /opt/plan-it/deploy/plan-it-backup.service /etc/systemd/system/
sudo cp /opt/plan-it/deploy/plan-it-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plan-it-backup.timer
sudo systemctl start plan-it-backup.service
sudo journalctl -u plan-it-backup.service -n 20
```

For an ad-hoc snapshot with extra arguments, use `systemd-run` so the environment
file is parsed the same way as the service:

```bash
sudo systemd-run --wait --pipe --uid=planit \
  --property=EnvironmentFile=/etc/plan-it/plan-it.env \
  --property=WorkingDirectory=/opt/plan-it \
  /opt/plan-it/.venv/bin/python /opt/plan-it/scripts/backup_planit.py \
    --dest /var/backups/plan-it --label manual
```

The snapshot is **plaintext**. Encrypt it before it leaves the server, for
example with restic, Borg, `gpg` or an encrypted volume. Keep backups off the
same disk as the live data, restrict access, and publish a retention period in
`PLANIT_BACKUP_RETENTION`. Test a restore before launch and after any storage
change.

A restore is:

```bash
sudo systemctl stop plan-it
# Restore accounts.db, warehouse/ and uploads/ into the paths in plan-it.env.
# Preserve ownership planit:planit and mode 0600 for files / 0700 for directories.
sudo systemctl start plan-it
curl -fsS https://planit.example.com/healthz
```

Take a fresh snapshot before every upgrade. Never restore a snapshot over live
data without first preserving the current files.

## 10. Retention and pruning

Uploaded analyses are deleted after the published retention period. The supplied
timer runs the default-dry-run command with `--apply --days 30` every day at
03:15 plus up to 20 minutes of jitter:

```bash
sudo cp /opt/plan-it/deploy/plan-it-prune.service /etc/systemd/system/
sudo cp /opt/plan-it/deploy/plan-it-prune.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plan-it-prune.timer
systemctl list-timers plan-it-prune.timer
```

If you publish a different retention period, edit `--days` in the unit and the
matching value in `PLANIT_RETENTION_PERIOD`. The command never touches the sample
warehouse or the account database. Run it by hand first to see what it would
delete, using the same environment file as the service:

```bash
sudo systemd-run --wait --pipe --uid=planit \
  --property=EnvironmentFile=/etc/plan-it/plan-it.env \
  --property=WorkingDirectory=/opt/plan-it \
  /opt/plan-it/.venv/bin/student-spending prune-uploads --days 30
```

Log rotation is also the operator's job. A small `logrotate` rule for
`/var/log/plan-it/*.log` and the proxy's access logs, matching the published
`PLANIT_LOG_RETENTION`, keeps disk use bounded.

## 11. Upgrades and rollback

```bash
sudo systemctl start plan-it-backup.service
sudo systemctl stop plan-it
sudo -u planit git -C /opt/plan-it pull --ff-only
sudo -u planit /opt/plan-it/.venv/bin/pip install /opt/plan-it
sudo systemctl start plan-it
curl -fsS https://planit.example.com/healthz
```

The accounts database migrates itself on startup. Read `CHANGELOG.md` before an
upgrade for any data or configuration change. To roll back, stop the service,
check out the previous revision, reinstall it and restore the pre-upgrade
snapshot if the schema moved forward.

## 12. Security operations

The app implements sessions, CSRF tokens, rate limiting, upload isolation and
read-only warehouse connections. The following controls are outside the code and
must be handled by the operator:

- Keep the OS, Python, proxy and certificates patched. Reboot for kernel updates.
- Encrypt the data disk and every backup. Restrict SSH keys and disable password
  login.
- Keep `/etc/plan-it/plan-it.env`, `/var/lib/plan-it` and backups readable only
  by the service account and administrators.
- Run a trusted, off-site backup copy. Verify restores on a schedule.
- Monitor `/healthz`, disk space, failed sign-ins and proxy error rates. Ship logs
  somewhere they survive a disk failure.
- Decide and document who can access the server, how access is revoked, and how
  long logs and backups are kept.
- Keep a written incident-response plan. If a breach risks people's rights,
  notify the ODPC and affected people without undue delay and within 72 hours
  where the law requires it. Preserve evidence; do not delete logs.
- Treat a lost or stolen server as a personal-data incident until proven
  otherwise.

## 13. Legal and human responsibilities

The code can render a privacy notice and terms, but it cannot make them
compliant. Before accepting real users, the operator must:

- Have a qualified Kenyan lawyer review `/privacy` and `/terms`, then set
  `PLANIT_LEGAL_REVIEWED=1`.
- Register as a data controller with the Office of the Data Protection
  Commissioner where the Kenya Data Protection Act 2019 requires it, and record
  the registration number in `PLANIT_ODPC_REGISTRATION`.
- Confirm the lawful basis for each processing activity, the retention periods,
  the international-transfer position and the age-assurance approach.
- Publish a real liability cap and any consumer-rights wording that applies.
- Provide a working privacy contact and answer data-subject requests within the
  statutory period.
- Keep the sample dashboard labelled as synthetic data; it is not a user's data.

If any of these are unresolved, keep the service private. The startup guard is a
reminder, not a substitute for legal review or operational discipline.

## 14. Troubleshooting

| Symptom | Check |
| --- | --- |
| Service exits with code `2` | `journalctl -u plan-it` lists the missing `PLANIT_*` values or warehouse problem |
| `Warehouse not found` | Run `student-spending --full-refresh` as `planit` |
| 502 from the proxy | The app is not running or is bound to a different loopback port |
| Cookies are rejected | `PLANIT_PUBLIC_URL` must be HTTPS and `PLANIT_SECURE_COOKIES=1` |
| Uploads fail with 413 | The proxy limit must be at least 4 MB; the app accepts 3 MB |
| Rate limits hit the proxy's IP | Set `PLANIT_TRUST_PROXY=1` only when the proxy overwrites `X-Forwarded-For` |
| Permission denied on data files | Ownership must be `planit:planit`; directories `0700`, files `0600` |
| `/healthz` is 503 | Inspect the `checks` object; rebuild the warehouse or restore `accounts.db` |
