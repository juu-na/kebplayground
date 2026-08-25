# Runbook

How to run, deploy and look after the web app. The pipeline itself is
described in [ARCHITECTURE](ARCHITECTURE.md); setup for the command line is
in the [README](README.md).

## Settings

| Name | Where it lives | What it does |
| --- | --- | --- |
| `GEMINI_API_KEY` | Secret Manager `gemini-api-key` | Writes the match messages. Without it the messages are the plain ones. |
| `ADMIN_TOKEN` | Secret Manager `admin-token` | Guards every admin page, passed as `?token=`. |
| `GOOGLE_CLIENT_ID` | Secret Manager `google-client-id` | Signing in. |
| `GOOGLE_CLIENT_SECRET` | Secret Manager `google-client-secret` | Signing in. |
| `SESSION_SECRET` | Secret Manager `session-secret` | Signs the session cookie. Changing it signs everybody out. |
| `STORE` | env var | `firestore` when deployed. Anything else means the in-memory store. |
| `LLM_CACHE_PATH` | env var | Where LLM answers are kept, `/tmp/llm_cache.json` when deployed. |
| `ALLOWED_EMAIL_DOMAIN` | env var | Who may sign in. Left out, only `aucklanduni.ac.nz`. |

Locally these come from `.env`, copied from `.env.example`.

The pool size is not an env var. It is held in Firestore and changed from
the admin page while the app is running.

## Running it locally

```
uv sync
uv run uvicorn kebplayground.web.app:app --port 8123 --reload
```

That uses the in-memory store, so everything is lost when you stop it. Sign
in still goes to the real Google, so `http://localhost:8123/auth/callback`
has to be listed on the OAuth client.

Tests:

```
uv run python -m unittest discover -s tests -t .
```

## Deploying

```
gcloud run deploy kiwe-match --source . --region australia-southeast1 \
  --allow-unauthenticated --max-instances 1 --min-instances 0 \
  --concurrency 80 --memory 512Mi --cpu 1 --no-cpu-throttling \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,ADMIN_TOKEN=admin-token:latest,GOOGLE_CLIENT_ID=google-client-id:latest,GOOGLE_CLIENT_SECRET=google-client-secret:latest,SESSION_SECRET=session-secret:latest \
  --set-env-vars STORE=firestore,LLM_CACHE_PATH=/tmp/llm_cache.json
```

`--set-secrets` and `--set-env-vars` replace the whole set each time, so
every one has to be listed even when only one changed.

`--no-cpu-throttling` matters. Without it Cloud Run takes the CPU away once
a response is sent, and a round started in the background by the tenth
signup would stall part way.

`--max-instances 1` matters too. Only one round may run at a time, and that
is enforced by a lock inside the process.

### One-time setup

Firestore in native mode, in the same region:

```
gcloud firestore databases create --location=australia-southeast1
```

The runtime service account needs `roles/datastore.user` and
`roles/secretmanager.secretAccessor`.

The OAuth client needs both callbacks listed under authorised redirect URIs:

```
http://localhost:8123/auth/callback
https://YOUR-SERVICE-URL/auth/callback
```

The consent screen has to be published, not left in testing, or only
accounts listed as testers can sign in.

## Running the demo

Open `/admin?token=...`. To get the token:

```
gcloud secrets versions access latest --secret=admin-token
```

The admin page does five things.

**Pool size** sets how many people have to be waiting before a round starts
on its own. Lowering it can start a round straight away.

**Run the matching** forces a round on whoever is waiting, however few. Use
it when fewer people turned up than the pool size, or to retry after an
error. It runs while you wait, so the page comes back when it has finished.

**Seed demo users** adds made up people so you can rehearse alone. They
accept their match on their own, so the flow reaches the page saying where
to meet. Fourteen made up people usually make only one or two pairs, since
they are spread across every major and interest; thirty make four to six.

**Download signups** and **download matches** give you the CSVs. Take them
before resetting.

**Reset everything** clears the users, the matches and the runs, and puts
the pool size back to 10. Use it between practice runs.

## What happens during a round

Everyone waiting is claimed at once, so anybody signing up mid-round belongs
to the next one. Matched people are offered their match; anyone not matched
goes straight back in the pool. A round does not start again just because
the same leftover people are still waiting, since it would give the same
answer forever.

## When something goes wrong

**First visit after a quiet spell is slow.** Cold start. Open the site a few
minutes before the demo.

**People stuck saying a round is going.** The instance was stopped part way
through a round. The next round sweeps them back into the pool, so press
"Run the matching".

**Match messages are dull and all alike.** That is `plain_message`, the
fallback used when Gemini could not be reached. Check `GEMINI_API_KEY`, and
remember a rotated secret only reaches the app on the next deploy.

**`redirect_uri_mismatch` when signing in.** The callback for the URL you
are on is not listed on the OAuth client. It has to match exactly, including
the scheme and the port.

**Sign-in says the account cannot be used.** The address is not on
`ALLOWED_EMAIL_DOMAIN`. Widen it at deploy time rather than changing code.

**Everyone got signed out.** `SESSION_SECRET` changed. Signing in again is
the whole fix.
