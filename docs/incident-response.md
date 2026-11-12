# When something goes wrong with people's data

What to do if Adullam's data may have been seen, changed or lost by someone who shouldn't have it. People keep prayers, grief and marriages here, so treat a suspected leak as real until you've shown it isn't.

Owner: [name, phone]. Backup: [name, phone].

## 1. Contain (first hour)

Do whatever stops it getting worse, even if it takes the site down.

| What leaked or broke | Do this |
| --- | --- |
| Supabase service key | Supabase > Project Settings > API: roll the service role key and JWT secret. Put the new key in Render's `SUPABASE_SERVICE_KEY`. Rolling the JWT secret signs everyone out. |
| OpenAI, Langfuse, VAPID or `CRON_SECRET` | Revoke at the provider, generate new ones, update Render. New VAPID keys mean every device must turn notifications on again. |
| A bug that shows one person another's data | Suspend the Render service (Render > Settings > Suspend) or roll back to the last good deploy, then fix. |
| An admin's account | Remove the address from `ADMIN_EMAILS` on Render, then reset that person's password (`scripts/set_password.py`). |
| A harmful post on the Amens wall | Remove it on the admin desk (`#desk`). Set `AMENS_AUTO_APPROVE=false` if the automatic check is letting things through. |
| The voice widget or another third-party script | Remove it from `web/index.html` and redeploy. |

Then keep evidence: copy Render's logs and Supabase's API, auth and Postgres logs for the window before they roll off, and write down what you did and when.

## 2. Understand (first day)

Answer, in writing:

- What happened, when it started and when it stopped.
- Whose data, how many people, and which kinds. Refuge, the journal, prayers and conversations count as the most sensitive. Faith can be special category data under UK/EU law.
- Whether it was read, changed, deleted or copied out.
- How it happened, and whether the same hole exists anywhere else. The rules every route must follow are in `CLAUDE.md` (every `/me` query filters by `user_id` in code; the browser never holds a Supabase key).

## 3. Tell people (within 72 hours)

- **The regulator**: if personal data was exposed and it's likely to harm people, report it within 72 hours of finding out. [UK: the ICO, ico.org.uk/report-a-breach. EU: the lead authority.] Report what you know, and follow up as you learn more.
- **The people affected**: if the risk to them is high, tell them directly and plainly: what happened, what of theirs was involved, what you've done, and what they can do. No reassurance you can't back up.
- **Providers**: tell Supabase, OpenAI, Langfuse, Render or Cognigy if the problem was on their side or touched their systems.

## 4. Recover and learn

- Fix the cause, add a test that would have caught it, and deploy.
- Restore anything lost from Supabase's backups if needed.
- Write a short note in `docs/incidents/` (date, what happened, who was affected, what changed) so the next person knows.
- Check the Privacy page (`#privacy` in `web/index.html`) still says what's true.

## Regular checks

- Every few months, and before inviting new people in: try each `/me` route signed in as one person with another person's ids (the tests in `tests/` cover the main paths; add one for each new route).
- Keep `ADMIN_EMAILS` to the people who need it, and remove anyone who leaves.
- Rotate the service key and `CRON_SECRET` once a year.
- Make sure Langfuse's retention and Supabase's backup window match what the Privacy page says.
