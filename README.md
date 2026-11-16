# KU Workshops

Collect students' GitHub usernames, review their accounts, and send invitations to **KU-Computing-Workshops**, entirely from your browser. Organisers do not need Python, Node.js, Cloudflare, or a terminal.

**Choose a workshop → submit a username → organiser reviews → organiser confirms → students accept**

Students choose **KU Computing Workshops (CW)** or **KU Artificial Intelligence Workshops (AIW)** at **[ku-tech-society.github.io/KUTS-Workshops/](https://ku-tech-society.github.io/KUTS-Workshops/)**. Both choices currently use the same GitHub organisation; workshop selection does not grant extra access.

The student page stays on GitHub Pages. Vercel hosts the organiser page and FastAPI backend. Upstash Redis holds shared, expiring state so submissions and batch checkpoints survive function restarts. Cloudflare Tunnel is no longer needed for hosted operation.

## Run a Workshop

After the one-time setup below:

1. Open the society's **Vercel organiser URL** and select **Sign in with GitHub**. Only approved GitHub accounts can access organiser operations.
2. Select **Open collection** and share the student page URL plus the six-character workshop code, for example `K7MP4R`. Letter case does not matter; codes avoid `0`, `1`, `I`, `L`, and `O`.
3. Submissions appear in the inbox, refreshed about every three seconds. Choose **Use usernames in fresh import**, or upload/paste usernames from another signup form.
4. Import, optionally select an existing team, and select **Resolve accounts (read-only)**. Visually check the resolved profiles and deselect anyone you do not intend to invite. A valid GitHub account is not proof of student identity.
5. Review the exact usernames, organisation, ordinary-member role, team, and count. Tick the confirmation and select **Send N invitations to KU-Computing-Workshops**.
6. Check per-account results and export a results CSV if needed. Students must accept invitations on GitHub; submission is not automatic membership.
7. Close collection, export anything needed, and select **Clear session**. This clears the shared workshop inbox and all previews/results, closes collection, and rotates the code for everyone. Sign out when finished.

Team membership can grant existing repository access. Existing members are skipped rather than automatically added to teams. Pending invitations are not resent or cancelled. New submissions never change a review that is already in progress.

## One-Time Hosted Setup

A society maintainer with GitHub repository, Vercel, and organisation-owner access completes this once. Regular organisers only need their approved GitHub account and the organiser URL afterward.

### 1. Connect the Repository to Vercel

Import this GitHub repository into a Vercel project. Keep the **Root Directory at the repository root**, not `backend/` or `frontend/`. Use the FastAPI framework preset and retain the repository's build settings.

[pyproject.toml](pyproject.toml) selects `backend.main:app`. [vercel.json](vercel.json) builds the organiser UI into `public/` and sets a 300-second function limit. [requirements.txt](requirements.txt) installs the backend dependencies, and [.python-version](.python-version) selects Python 3.12. No development server or dual-port launcher runs on Vercel.

Choose a stable production domain, for example `https://your-project.vercel.app`. Use that same origin consistently for sign-in and the student API. Required environment variables must be configured before a successful deployment; missing auth/storage configuration fails closed.

### 2. Connect Upstash Redis

From Vercel's Marketplace/Storage integration, create or connect **Upstash Redis**. Choose a suitable region and a plan/retention policy for the society's data. Connect it to the production project so `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are available to the backend. Use the normal server-side REST token, not a read-only token. Do not expose it in frontend variables.

Use a persistent database without eviction for workshop state: losing Redis data can also lose replay protection. If storage is unavailable or has been reset, stop invitation operations and reconcile GitHub members/pending invitations before another reviewed batch. Enable appropriate Vercel edge rate limiting, spending limits, and monitoring for the public intake endpoint.

### 3. Register GitHub Sign-In

Create a dedicated **GitHub OAuth App** in GitHub **Settings → Developer settings → OAuth Apps**:

| Setting | Value |
| --- | --- |
| Homepage URL | Your stable Vercel organiser origin |
| Authorization callback URL | `https://your-project.vercel.app/auth/callback` |
| Callback wildcard matching | Disabled; use the exact callback URL |

Copy the client ID and generated client secret into the server-side Vercel settings below. This OAuth app identifies organisers only; it requests no extra repository/organisation scopes and does not send invitations with a user's OAuth token. Login uses state, PKCE, and an opaque Secure/HttpOnly session cookie.

Approve organisers by their **numeric GitHub account IDs**, not changeable usernames. Obtain each account's `id` from GitHub's documented `GET https://api.github.com/users/USERNAME` endpoint and independently confirm it is the intended person. Remove an ID and redeploy to revoke access; every authenticated request checks the configured allowlist.

### 4. Set the Production Environment Variables

In Vercel **Settings → Environment Variables**, set the following for **Production**, then redeploy. [.env.example](.env.example) contains placeholders only; do not upload your local `.env`.

| Variable | Value |
| --- | --- |
| `APP_ORIGIN` | Exact organiser origin, e.g. `https://your-project.vercel.app`, without a path |
| `STUDENT_ORIGIN` | `https://ku-tech-society.github.io`, without `/KUTS-Workshops/` |
| `GITHUB_OAUTH_CLIENT_ID` | OAuth App client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | OAuth App client secret; server only |
| `ORGANISER_GITHUB_IDS` | Comma-separated approved numeric IDs, e.g. `12345678,87654321` |
| `GITHUB_TOKEN` | Organisation owner's fine-grained PAT restricted to KU-Computing-Workshops with organisation **Members: read and write** only |
| `UPSTASH_REDIS_REST_URL` | HTTPS Redis REST endpoint from Upstash |
| `UPSTASH_REDIS_REST_TOKEN` | Server-side Redis REST token |

The invitation PAT needs no repository write permissions. Its owner must be an organisation owner; approval and SSO policy still apply. Fine-grained PATs are SSO-authorised during creation. Prefer a short expiry and rotate/revoke it in GitHub when appropriate.

**Allowlisting an organiser delegates the ability to send ordinary-member invitations through the server-held owner's PAT.** Keep that list restricted to trusted organisers, including where the organiser is not personally an organisation owner. They never receive the PAT. Never put PATs, OAuth secrets, Redis tokens, session cookies, or workshop codes into `VITE_*` variables, URLs, Actions inputs, logs, or messages.

Set secrets for Production only unless you have a separate staging configuration. Preview deployments need their own OAuth callback/origin and separate Redis namespace/database; never point an untrusted preview at production data or credentials. `REDIS_NAMESPACE` optionally overrides the default `kuts-<VERCEL_ENV>` key prefix. Local-only settings `FRONTEND_ORIGIN` and `STUDENT_API_HOST` are not needed by hosted mode.

Use Vercel's **production domain**, not a generated preview/deployment URL. The public student endpoint must be reachable without Vercel's platform login: retain protection on previews but do not require platform authentication for the production student API. Organiser API access is protected by this application's GitHub sessions and allowlist. Do not place a platform bypass secret in the student page.

### 5. Point GitHub Pages at Vercel

In the GitHub repository, set **Settings → Pages → Source** to **GitHub Actions**. Under **Settings → Secrets and variables → Actions → Variables**, add `STUDENT_API_URL` with your stable Vercel origin. This URL is public configuration, not a credential.

Run **Actions → Publish student page → Run workflow** once. Leave the optional `api_url` input empty to use the repository variable, or enter a new HTTPS backend origin to override it. The workflow publishes only the student build. Both the root URL and `/student.html` work; the organiser app is not published to Pages.

No tunnel or local computer needs to stay running. The stable backend URL only needs updating in Pages if you change the Vercel production domain.

### 6. Check Before a Real Workshop

Sign in using an approved account, open collection, and submit a fictional username from the student page. Confirm it appears with CW/AIW in the organiser inbox. Check that signed-out/unapproved accounts cannot access organiser data. Clear the test session afterward. Do not click **Send** merely to test deployment.

## Hosted Recovery, Limits, and Privacy

- Reviews are bound to the organiser who created them and expire after 15 minutes. Another organiser cannot confirm or inspect that private review/batch by replacing an ID.
- Redis holds the shared inbox, preview/batch state, sessions, rate limits, and operation locks. Closing a tab or restarting a Vercel function does not clear workshop data. The inbox expires after four hours. Sessions expire after eight hours or on sign-out. OAuth state is single-use and expires after ten minutes.
- Expired previews are rejected and removed on subsequent state processing. Core records have a 24-hour default idle storage TTL; active workshop writes can extend the physical storage of expired records until cleanup. Clear session to remove the current shared workshop data promptly. Hosting/Redis provider backups and platform log retention are separate policies to configure with the society.
- There are at most 50 invitations per reviewed batch, sent sequentially, with server-side member role and approved team IDs. Durable consumed-preview markers and ownership-checked distributed locks prevent repeat clicks and overlapping batches across instances.
- Before any invitation request, the reviewed batch and unfinished per-account outcomes are checkpointed. Results are saved as accounts are processed. If an invocation or connection fails, refresh the organiser page to recover the latest saved batch. An expired operation lease may take up to 60 seconds to release. Unfinished actions are **status unknown - review required**, not automatically retried. Exactly-once delivery is not claimed.
- Vercel requests have a 300-second limit; the app budgets 240 seconds for a core operation. A slow/large lookup may need a smaller fresh import. An interrupted invitation batch must be reconciled in GitHub before any fresh retry. There is no background queue or automatic whole-batch retry.
- The inbox polls every three seconds while the organiser page is open. Original bounds remain: 1 MiB/500 import rows, 500 inbox entries, one username per student request, 2 KiB student request bodies, and 120 student attempts per minute across instances. These are abuse controls, not student identity verification or full DDoS protection.
- No credentials reach browser storage or the student bundle. OAuth access tokens are used only server-side to verify identity and are not persisted in the app. Student GitHub usernames and batch results are personal data; configure Vercel/Redis regions and retention appropriately. Do not enable body/header debug logging. GitHub request errors are redacted; platform-level logging must also be reviewed.

## Hosted Troubleshooting

| Problem | Check |
| --- | --- |
| Vercel build/start fails | Import from repository root with FastAPI selected. Keep the checked-in entrypoint/build settings and configure all required Production variables, then redeploy. |
| Sign-in says account is not approved | Verify the numeric GitHub ID, not username, is in `ORGANISER_GITHUB_IDS`. Redeploy after updating it. |
| GitHub callback fails | Match `APP_ORIGIN`, production domain, and the OAuth App's exact `/auth/callback` URL. Start sign-in again if state expired; do not reuse an old callback link. |
| Students get 403 or cannot submit | Open collection, check the six-character code and exact `STUDENT_ORIGIN`. Republish Pages if the backend URL changed. Ensure production is not behind a Vercel platform login. |
| Operation busy | Wait for the active organiser action or its 60-second lease to end. Do not keep resending an invitation request. |
| Session expires | Sign in again. Your saved batch is recovered; check results before any new review. |
| GitHub denies access | Check PAT expiry, Members permission, owner role, organisation approval, and SSO. A successful organiser sign-in is separate from invitation-token permission. |
| Storage unavailable or status unknown | Stop sending. Restore storage if needed, inspect GitHub members/pending invitations, and reconcile saved results before any fresh reviewed batch. |

## Development and Automated Checks

Developers need Python 3.12 and Node.js 22. From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
PYTHONPATH=backend python3 -m pytest backend/tests
npm --prefix frontend test
npm --prefix frontend run build:hosted
VITE_STUDENT_API_URL=https://your-project.vercel.app npm --prefix frontend run build:student
```

Backend tests use mocked GitHub responses and a local Redis emulator, including real Lua scripts and the Upstash SDK command interface. They do not connect to live Redis or send live invitations. Browser automation fixtures must stay separate from normal operation. Live GitHub OAuth, Vercel deployment, and provisioned Redis require the maintainer's real setup and are not implied by passing local tests.

References: [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [Vercel function limits](https://vercel.com/docs/functions/limitations), [GitHub OAuth](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [Upstash Python SDK](https://upstash.com/docs/redis/sdks/py/gettingstarted).

<details>
<summary>Optional local development and legacy tunnel mode</summary>

The guide below is for the original local-only development mode, not the hosted organiser workflow. It uses in-memory state, a separate local API, and optional Cloudflare Tunnel. Its `.env`, privacy, and startup instructions apply only to that legacy mode; do not use its local organiser entrypoint for Vercel.

## Before You Start

You will need:

- A Linux or macOS computer that can stay online throughout the workshop. The commands below use Bash; native Windows setup is not covered.
- Python 3.10 or later and Node.js 22 LTS, with `npm`.
- A local copy of this repository, cloned or downloaded from GitHub.
- A GitHub **organisation owner** to create the invitation token. An ordinary organisation member's token cannot send invitations.
- Permission to run Actions and configure GitHub Pages in this repository, if you want students to submit online.
- [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) for online submissions. You do not need it for CSV or pasted usernames.

Already collecting usernames through another form? Complete **First-Time Setup** and **Start the Organiser Page**, then go straight to **Review and Send Invitations**. GitHub Pages and Cloudflare are optional for that workflow.

## First-Time Setup

### 1. Install the Dependencies

Open a terminal in the repository's top-level folder, the one containing this README, `backend/`, and `frontend/`.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
npm --prefix frontend ci
cp .env.example .env
```

Run the copy command only during initial setup: it replaces any existing `.env`. On Debian/Ubuntu, if virtual environment creation reports that `ensurepip` is missing, install the matching `python3-venv` system package, then rerun the setup.

### 2. Configure Your GitHub Token

An owner of **KU-Computing-Workshops** should open GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.

| Setting | Value |
| --- | --- |
| Resource owner | `KU-Computing-Workshops` |
| Expiration | A short lifetime covering the workshop |
| Organisation permissions | **Members: Read and write** |
| Repository permissions | None required; do not grant repository write access |
| Account permissions | None required for public profile lookups |

Open the project-root `.env` file and replace the `GITHUB_TOKEN` placeholder with your token. Leave the other defaults unchanged for now.

**Keep the token on the organiser's computer only.** Never add it to GitHub Pages, an Actions input, a `VITE_*` setting, a screenshot, or a message. The `.env` file is Git-ignored. Each organiser should use their own credential rather than sharing a token.

Use a **fine-grained personal access token** with KU-Computing-Workshops as its resource owner and only the organization **Members: write** permission. The required read operations (listing members, invitations, and teams) use the same Members permission; profile lookups use public user information. Do not grant repository permissions. The invitation API requires the authenticated user to be an **organization owner**; the token permission does not replace that role.

An organization may require approval for fine-grained tokens; while pending, a token can only read public resources, and an organization owner's request is automatically approved. Fine-grained tokens are SSO-authorized during creation. A classic token requires the broader `admin:org` scope and separate SSO authorization when SAML SSO applies, so it is not recommended here. If the token is denied, the app fails closed and reports access errors instead of treating members as non-members.

## Start the Organiser Page

Keep these two terminals open. Start each from the repository's top-level folder.

**Terminal 1: backend**

```bash
. .venv/bin/activate
PYTHONPATH=backend python3 -m app.serve
```

**Terminal 2: organiser page**

```bash
npm --prefix frontend run dev
```

Open **[the organiser page](http://127.0.0.1:5173/)** on this computer. Collection starts closed. Keep this page private; it is not the link to share with students.

The launcher runs separate organiser and student APIs on local ports **8000** and **8001**. Use this launcher rather than separate backend processes or multiple workers: session data is shared in memory. All local servers bind to `127.0.0.1`.

## Let Students Submit Online

Complete this section only if you want the student signup page. Your computer, both local servers, and the tunnel must remain running while students submit.

### 1. Start the Student Tunnel

In a third terminal, run:

```bash
cloudflared tunnel --url http://127.0.0.1:8001
```

Cloudflare prints an HTTPS address such as `https://example.trycloudflare.com`. Use your actual address below; this example is only a placeholder.

**Tunnel port 8001 only. Never tunnel port 8000, port 5173, or the organiser page.** The student API can accept usernames but cannot list students, read credentials, access previews, or send invitations.

### 2. Set the Student Addresses

Edit these values in the project-root `.env` file:

```dotenv
STUDENT_API_HOST=example.trycloudflare.com
STUDENT_ORIGIN=https://ku-computing-workshops.github.io
```

`STUDENT_API_HOST` is your tunnel hostname, without `https://` or a path. `STUDENT_ORIGIN` is the origin of your GitHub Pages site, without the repository path. For example, `https://ku-computing-workshops.github.io/KUTS-Workshops/student.html` uses the origin shown above.

Restart the backend in Terminal 1 with **Ctrl+C**, then run:

```bash
PYTHONPATH=backend python3 -m app.serve
```

Restarting clears in-memory session data, so configure this before collecting real submissions.

### 3. Publish the Student Page

In the GitHub repository, open **Settings → Pages** and set **Source** to **GitHub Actions**. This only needs doing once.

Open **Actions → Publish student page → Run workflow**. Choose the branch containing your current changes and enter the full HTTPS tunnel address in `api_url`, for example `https://example.trycloudflare.com`.

Wait for the workflow to succeed, then open its deployment link. The student page ends in **`/student.html`**. For a project site, the address is `https://<owner>.github.io/<repository>/student.html`.

The [publishing workflow](.github/workflows/student-pages.yml) runs only when manually requested and publishes only the student build. The tunnel URL is public configuration, not a credential. Do not enter your GitHub token or workshop code in the workflow.

### 4. Open Collection and Share

On your local organiser page, select **Open collection**. Share these two things with attendees:

- The GitHub Pages **student page URL**.
- The **workshop code** displayed in the organiser inbox: six letters/digits, for example `K7MP4R`. Letter case does not matter. Codes avoid `0`, `1`, `I`, `L`, and `O` to reduce typing mistakes.

Students choose CW or AIW, continue to the join form, and submit their GitHub username and workshop code. They should never enter a password, token, or email. Usernames, `@usernames`, and GitHub profile URLs are accepted.

Submissions and workshop labels appear in your inbox within about one second, without refreshing. A username is deduplicated within each workshop; the same student may register for both. New arrivals do not change a batch you are already reviewing.

> A Quick Tunnel gets a new hostname whenever it restarts. Update `.env`, restart the backend, and rerun **Publish student page** with the new address. For regular use, consider a [named Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/) with a stable hostname mapped only to port 8001. Quick Tunnels are intended for development and have no uptime guarantee.

## Review and Send Invitations

1. Choose **Use usernames in fresh import** from the live inbox, upload a CSV, or paste one username per line.
2. For CSV files, indicate whether there is a header row and choose the GitHub username column. Unrelated columns are discarded during parsing.
3. Optionally select an existing team. Check its name and slug: team membership can grant access to existing repositories.
4. Select **Resolve accounts (read-only)**. This looks up accounts and identifies existing members, pending invitations, duplicates, invalid input, and lookup failures. It does not send anything.
5. Visually review each resolved account. A valid GitHub account is not proof of student identity. Select only the eligible accounts you intend to invite.
6. Review the exact usernames, organisation, ordinary-member role, team, and invitation count. Tick the review confirmation and select **Send N invitations to KU-Computing-Workshops**.
7. Check the per-account results and export a results CSV if needed. Remind students to accept their GitHub invitations.

Example CSV (fictional usernames):

```csv
student,github_username
Example Student,workshop-example-01
Another Student,workshop-example-02
```

Repository URLs and non-GitHub hosts are rejected. Existing members are skipped and are not automatically added to teams. Pending invitations are not cancelled or resent. Failed or uncertain requests are not automatically replayed; any retry needs a fresh review and confirmation. Check **status unknown** outcomes in GitHub before attempting another invitation.

## Finish a Workshop

1. Select **Close collection** to stop new submissions.
2. Export any results you need before clearing the session. Treat exported usernames as personal data.
3. Select **Clear session** to remove the inbox, previews, and results, close collection, and rotate the workshop code.
4. Stop the tunnel and both local servers with **Ctrl+C** in their terminals. The published student page may remain visible, but cannot collect submissions while your backend or tunnel is stopped.
5. Revoke a workshop-only token in GitHub **Settings → Developer settings → Personal access tokens**, and remove its value from your local `.env` when no longer needed.

## Next Workshop Checklist

- Start the backend and organiser page using the commands above.
- Check the token has not expired and collection is initially closed.
- Start the student tunnel if needed. If its address changed, update the backend settings and republish the student page before opening collection.
- Share the student page and the current workshop code, not the organiser URL.
- Collect → import → resolve → review → confirm → remind students to accept.
- Export results, clear the session, and stop the tunnel when finished.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `python3 -m venv` fails | On Debian/Ubuntu, install the matching `python3-venv` package, then recreate the environment. |
| Backend will not start | Run from the repository root, activate `.venv`, and install `backend/requirements.txt`. Check ports 8000 and 8001 are not already occupied. |
| Organiser page cannot connect | Keep both terminals running. Use `http://127.0.0.1:5173/`, with `FRONTEND_ORIGIN=http://127.0.0.1:5173` in `.env`. |
| GitHub returns 403 or denies access | Check the token belongs to an organisation owner, targets KU-Computing-Workshops, has Members: read and write, is approved/SSO-authorised, and has not expired. Restart the backend after changing `.env`. |
| Student page cannot submit | Open collection, check the code, keep the tunnel running, and confirm the published page uses the current HTTPS tunnel URL. Check `STUDENT_API_HOST` and `STUDENT_ORIGIN` match their formats above. |
| Pages workflow is unavailable | Ensure the workflow is on the repository's default branch, GitHub Actions is enabled, and you have permission to run it. Set Pages source to GitHub Actions. |
| Inbox says reconnecting | Keep the local backend running. It will replay the current inbox when the connection returns. Use the launcher shown above. |
| Invitation already pending | Ask the student to check GitHub for the existing invitation. This tool deliberately does not resend it. |
| Rate limited | Wait for the displayed retry/reset guidance. Do not repeatedly resubmit a batch. |
| Status unknown | Review organisation members, pending invitations, and activity in GitHub before any fresh attempt. |

## Limits and Privacy

This is a lightweight organiser tool, not a learning-management system. It has no database, student accounts, or identity verification. GitHub Classroom is not used. It does not create teams, change repository permissions, or grant owner access.

| Limit | Default |
| --- | --- |
| CSV/pasted import | 1 MiB and 500 rows |
| Combined student inbox | 500 submissions |
| Public submission | One username; 256 UTF-8 bytes; 2 KiB request body |
| Submission attempts | 120 per minute across the workshop instance |
| Invitation batch | At most 50 accounts; processed sequentially |
| Reviewed preview lifetime | 15 minutes |
| Student inbox lifetime | Four hours |

Import limits and preview expiry can be adjusted using the variables in [.env.example](.env.example). `MAX_INVITES_PER_BATCH` can lower the 50-account cap, but cannot raise it. GitHub also applies its own limits: currently 50 invitations per 24 hours, or 500 for organisations over a month old or on a paid plan. Authenticated REST requests typically have a 5,000-per-hour primary limit, with additional secondary limits. The app surfaces rate limits rather than blindly retrying.

The shared workshop code is not student authentication. Anyone with the code may submit a valid-looking username, and Cloudflare processes traffic sent through its tunnel. Review accounts carefully. Host/origin checks, JSON-only writes, restricted CORS, and exact-origin CSRF checks protect the intended local workflow; they are not a complete security design for public organiser access. Quick Tunnels allow at most 200 in-flight requests and do not support SSE; the organiser's live feed stays local and does not traverse the tunnel.

- Keep the organiser page and API local-only. The only approved remotely reachable surface is the isolated student intake on port 8001 through the tunnel described above.
- The token is read from backend `.env`, never from a `VITE_*` setting, browser storage, URL, API response, or frontend bundle. Do not paste it into logs or screenshots. `.env` and local CSV exports are ignored by Git.
- Session data is in memory only and is lost when the backend stops. Use **Clear session** to remove the inbox, previews, and results and rotate the workshop code. The launcher disables HTTP access logs; do not enable request-body logging for student data.
- Exported CSV includes only submitted/resolved usernames, outcome, invitation ID, and explanation. Formula-leading values are neutralised for spreadsheet safety.

## Safe Practice and Development

### Mocked Dry Run

Automated tests use an in-memory fake GitHub client; they never make live API requests or send invitations. The mocked dry run drives the same import → resolve → confirm API flow and asserts that only the fake client receives the resolved account ID and ordinary-member role:

```bash
python3 -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python3 -m pytest backend/tests
PYTHONPATH=backend python3 -m pytest backend/tests/test_api.py::test_invitation_uses_server_resolved_id_direct_member_role_and_bound_team -q
npm --prefix frontend test
```

The named test uses a fictional account and a fake client whose `invite` method only records the request in memory. It returns an example invitation ID; it cannot reach GitHub. The normal application has no simulated GitHub responses or dry-run switch; it requires a working token to resolve accounts and send real invitations. Do not use a production token merely to test the UI.

### Test the Student Form Locally

Stop any existing backend/frontend instances first. From the repository root, run the backend with the GitHub token explicitly empty:

```bash
. .venv/bin/activate
GITHUB_TOKEN='' STUDENT_ORIGIN=http://127.0.0.1:5173 STUDENT_API_HOST=127.0.0.1:8001 PYTHONPATH=backend python3 -m app.serve
```

In another terminal at the repository root:

```bash
VITE_STUDENT_API_URL=http://127.0.0.1:8001 npm --prefix frontend run dev
```

Open collection on the organiser page and visit [the local student page](http://127.0.0.1:5173/student.html). Choose a workshop and submit a fictional username using the displayed code. Check it arrives live, then clear the session. This tests real local submission handling without a tunnel; no GitHub features are available with the empty token.

### Build the Frontends

Run from the repository root. Replace the example tunnel URL with your own:

```bash
npm --prefix frontend run build
VITE_STUDENT_API_URL=https://example.trycloudflare.com npm --prefix frontend run build:student
```

The organiser build goes to `frontend/dist/`; the student build goes to `frontend/dist-student/`. Publish only the student artifact. A production student build rejects missing, HTTP, or loopback API URLs. The submission API requires a `workshop` value of `CW` or `AIW`; workshop labels never override server-side invitation targets.

## Official References

### Cloudflare

- [Quick Tunnels: command, lifetime, and limitations](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [Named Cloudflare Tunnels](https://developers.cloudflare.com/tunnel/get-started/)

### GitHub

- [Get a user](https://docs.github.com/en/rest/users/users#get-a-user)
- [Organization members and invitations](https://docs.github.com/en/rest/orgs/members)
- [List teams](https://docs.github.com/en/rest/teams/teams#list-teams)
- [Fine-grained token permissions required by REST endpoints](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)
- [REST API pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Inviting users to an organisation](https://docs.github.com/en/organizations/managing-membership-in-your-organization/inviting-users-to-join-your-organization)
- [Personal access token SSO authorization](https://docs.github.com/en/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on)

</details>
