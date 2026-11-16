# KU Workshops

Collect students' GitHub usernames, review their accounts, and send invitations to **KU-Computing-Workshops**.

**Choose a workshop → submit a username → organiser reviews → organiser confirms → students accept**

Students can choose **KU Computing Workshops (CW)** or **KU Artificial Intelligence Workshops (AIW)**. Their submissions appear live on the organiser's computer. Both choices currently use the same GitHub organisation; workshop selection does not grant extra access.

> The organiser page stays on your computer. Only the student page and its restricted submission endpoint are public. No invitations are sent automatically, and students must accept them on GitHub.

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
