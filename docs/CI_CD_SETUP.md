# CI/CD Setup — Auto-Deploy on Push to `main`

> Set this up once. After that, every commit to `main` auto-deploys to
> `weighbridgesetu.com` within ~2 minutes.

---

## What you're setting up

```
   git push origin main
          │
          ▼
   GitHub Actions runner (.github/workflows/deploy.yml)
          │ SSH (passwordless, key-based)
          ▼
   Hostinger VPS — runs scripts/ci-deploy.sh
          │
          ├─→ git pull origin main
          ├─→ if backend/ changed:  pip install + systemctl restart weighbridge
          ├─→ if frontend/ changed: npm ci + npm run build + cp dist/* to nginx
          ├─→ nginx reload
          ├─→ curl /api/v1/health  (rollback signal)
          └─→ append summary to /var/log/weighbridge-deploy.log
          │
          ▼ (then GitHub Actions)
   Purge Cloudflare cache (so the new build is visible immediately)
          │
          ▼
   curl https://weighbridgesetu.com  (final sanity ping)
```

Typical deploy time: **45–90 seconds**.

---

## One-time setup (30 minutes)

### Step 1 — On the VPS: create a dedicated CI deploy key

SSH into the VPS as root one last time:

```bash
ssh root@<VPS_IP_OR_HOSTNAME>
```

Generate an SSH key pair *on the VPS itself* (so the private key never
crosses the network), with no passphrase:

```bash
ssh-keygen -t ed25519 -C "github-actions@weighbridgesetu" \
  -f ~/.ssh/github_actions_deploy -N ""
```

Authorize the new key for incoming SSH:

```bash
cat ~/.ssh/github_actions_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Print the **private** key — you'll paste it into GitHub in Step 3:

```bash
cat ~/.ssh/github_actions_deploy
```

Copy the **entire** output, including the `-----BEGIN OPENSSH PRIVATE KEY-----`
and `-----END OPENSSH PRIVATE KEY-----` lines.

> **Security note**: This key has root SSH access to your VPS. Keep the
> private key only in two places: `/root/.ssh/github_actions_deploy` on the
> VPS, and in the GitHub repo secret `VPS_SSH_KEY` (Step 3). Don't email it,
> don't put it in chat, don't commit it.

### Step 2 — On the VPS: make sure `ci-deploy.sh` is in place

The script is already in the repo. Confirm:

```bash
ls -la /opt/weighbridge/scripts/ci-deploy.sh
```

If the file isn't there yet, pull latest:

```bash
cd /opt/weighbridge && git pull origin main && chmod +x scripts/ci-deploy.sh
```

Pre-create the log file so the script can append to it without root issues:

```bash
touch /var/log/weighbridge-deploy.log
chmod 644 /var/log/weighbridge-deploy.log
```

Test it manually (it should detect "no commits" and no-op):

```bash
cd /opt/weighbridge && bash scripts/ci-deploy.sh
```

You should see something like:
```
[2026-06-11T17:00:00Z] ━━━ CI/CD deploy started
[2026-06-11T17:00:00Z]   Before: 50a5fc3a...
[2026-06-11T17:00:00Z]   After:  50a5fc3a...
[2026-06-11T17:00:00Z]   No commits — nothing to deploy. Still running nginx -t for sanity.
[2026-06-11T17:00:00Z] ✅ No-op deploy complete in 0s
```

If you see errors here, fix them now — don't proceed until the manual run is clean.

### Step 3 — On GitHub: add the secrets

Go to the repo on GitHub → **Settings → Secrets and variables → Actions →
New repository secret**, then add these four:

| Name | Value |
|---|---|
| `VPS_HOST` | The VPS IP or hostname (e.g. `141.94.32.18` or `weighbridgesetu.com`). |
| `VPS_USER` | `root` (matches `scripts/deploy-vps.sh`). |
| `VPS_SSH_KEY` | The private key from Step 1 (paste the whole block, including BEGIN/END lines). |
| `VPS_PORT` | `22` — or whatever port SSH listens on. Skip if 22. |

Optional (enables auto Cloudflare cache purge after each deploy):

| Name | Value |
|---|---|
| `CF_ZONE_ID` | Cloudflare dashboard → your domain → Overview pane → bottom right, **Zone ID**. |
| `CF_API_TOKEN` | Cloudflare dashboard → My Profile → API Tokens → Create Token → "Custom token" with **Zone → Cache Purge → Purge**. |

> Without these two CF secrets, the deploy still works but the new build
> won't appear on `weighbridgesetu.com` until Cloudflare's edge cache
> expires (default: hours). Set them up unless you don't care about cache
> latency.

### Step 4 — Trigger the first deploy

Two ways to test:

**Manual trigger** (recommended for the first run — easier to debug):
1. Go to **Actions** tab in GitHub
2. Pick **"Deploy to VPS"** in the left sidebar
3. Click **"Run workflow"** → leave defaults → **"Run workflow"** button
4. Watch the log unfold

**Push-to-main trigger** (the real deal):
```bash
git commit --allow-empty -m "chore: kick CI/CD pipeline"
git push origin main
```

In both cases, head to the **Actions** tab — you should see a job running.

If everything is wired up right, you'll see:

```
✓ SSH + run ci-deploy.sh on VPS         52s
✓ Purge Cloudflare cache                 1s
✓ Sanity-check live site                 6s
```

---

## What to expect day-to-day

| You do | What happens automatically |
|---|---|
| `git push origin main` | Workflow runs. Backend restarts if any `backend/**` file changed. Frontend rebuilds if any `frontend/**` file changed. Nginx reloads. Cloudflare cache purges. Live site updated in ~1 min. |
| Push only `CLAUDE.md` or `docs/**` | Workflow is **skipped** (we ignore these paths). No restart, no purge. |
| Two pushes within seconds | They queue. Second deploy waits for first to finish (`concurrency: deploy-vps`). |
| Build / health check fails | Workflow fails, **the previous deploy stays live**. You get an email from GitHub. Run `bash /opt/weighbridge/scripts/ci-deploy.sh` manually to reproduce. |

---

## How to roll back a bad deploy

The fastest way:

```bash
ssh root@<VPS>
cd /opt/weighbridge
git log --oneline -10           # find the last known-good commit
git reset --hard <good-sha>
bash scripts/ci-deploy.sh        # script will redeploy that commit
```

Alternative: push a revert commit to GitHub. The pipeline will roll forward
to the revert. Slower but stays in git history.

---

## Troubleshooting

### "ssh: connect to host … port 22: Connection refused"
Your VPS doesn't accept SSH on port 22 (Hostinger sometimes uses a custom
port). Set `VPS_PORT` secret to the right port.

### "Permission denied (publickey)"
- The public key isn't in `/root/.ssh/authorized_keys` on the VPS, OR
- The private key in `VPS_SSH_KEY` doesn't match. Re-do Step 1.

### "fatal: not a git repository"
`/opt/weighbridge` wasn't cloned via git. Run on the VPS:
```bash
cd /opt && rm -rf weighbridge && git clone https://github.com/manhotraconsultingservices/mcs_weightbridge.git weighbridge
cd weighbridge && bash scripts/ci-deploy.sh
```

### Backend restarts but `weighbridge.service` status is `failed`
Check the journal:
```bash
journalctl -u weighbridge -n 50 --no-pager
```
Common cause: a Python import error in new code. The previous binary is gone
because we did `git reset --hard`. Roll back as above.

### "npm ci" fails with "missing script: build"
Frontend `package.json` doesn't match expectations. Check that you pushed the
`frontend/` directory fully — sometimes `.gitignore` accidentally excludes
files. Run `git ls-files frontend/ | head` to verify.

### Cloudflare purge step says "skipping"
Either `CF_ZONE_ID` or `CF_API_TOKEN` secrets aren't set. Add them, or
manually purge from the Cloudflare dashboard after each deploy.

### Deploy succeeded but the live site shows the old version
Cloudflare cache. Either the purge step didn't run (see above), or your
browser is caching. Try a hard reload (Ctrl + Shift + R), or check with:
```bash
curl -sI -H "Cache-Control: no-cache" https://weighbridgesetu.com/ | head -10
```

---

## Future improvements (not needed now)

- **Per-PR preview deploys** — spin up a temporary URL per pull request.
  Requires a separate VPS or container.
- **Blue/green** — keep two `/var/www/weighbridge-{blue,green}` roots,
  switch nginx symlink atomically. Zero downtime for frontend deploys.
- **Backend rolling restart** — currently `systemctl restart` causes a
  ~3 s blip. Could move to gunicorn `--graceful-timeout` + `systemctl
  reload` once we add a SIGHUP handler.
- **Slack/Telegram deploy notifications** — easy to add as a final
  workflow step using a curl to a webhook URL.

For now: every push to `main` is live in a minute. That's enough.
