# Launch checklist: family, friends and beta testers

Tick a box by changing `[ ]` to `[x]`.

## 1. Must fix first

- [ ] Custom SMTP in Supabase (Auth > SMTP, e.g. Resend or Postmark). The built-in mailer sends only a few magic links an hour.
- [x] Render off the free plan (`render.yaml` says `plan: free`). A sleeping server makes the first visitor wait 30 to 60 seconds.
- [ ] Voice: move off the Cognigy trial endpoint (`web/index.html`, `VOICE_CONFIG_URL`), or confirm its limits and expiry.
- [ ] Privacy and Terms: fill every [bracketed] part (operator name, retention, backup window, age, jurisdiction).
- [ ] `hello@adullum.app` is a real inbox that reaches me.
- [ ] Link previews: add `og:title`, `og:description`, `og:image` (1200x630) and `og:url` to `web/index.html`.
- [ ] Spending: hard monthly limit set with the model provider.
- [x] Daily limits live: run `supabase/migrations/20261121_usage_limits.sql`, then ask as a guest 6 times and see the gentle "Sign in" message.
- [ ] `MCP_SECRET` set on Render and added to Cognigy's MCP node (as `Authorization: Bearer ...` or `?key=...` on the URL); a voice call still answers.
- [ ] Guest counting checked on Render: two phones on different networks each get their own 5 questions (confirms the real address header arrives).
- [ ] Cognigy's per-minute price known and set as `COST_VOICE_CALL_USD`; a maximum session length set in Cognigy too.
- [ ] Every migration run in production, through `20261120_admin_desk.sql`; every tab opened signed in with no "run this" message.
- [ ] Render secrets set: VAPID keys, `VAPID_SUBJECT`, `CRON_SECRET`, Langfuse, support links.
- [ ] GitHub repo secrets set: `DEPLOY_URL`, `CRON_SECRET`.
- [ ] Supabase Auth redirect URLs include the final domain.
- [x] change name to adullam

## 2. AI provider

- [x] OpenAI account topped up (embeddings and moderation need it even if chat moves elsewhere).
- [ ] Chat model and provider configurable from `.env` (one shared factory instead of `ChatOpenAI(...)` in each file).
- [ ] Test set of ~30 real questions (study, Refuge, Declare, plans, meta) run against each candidate model.
- [ ] Chosen model passes: no invented verses, ground check works, structured outputs parse, no em dashes, care check catches distress.
- [ ] Privacy page updated to name the new provider and where it processes data.

## 3. Voice call

- [ ] Spoken turns appear as ordinary bubbles in the Refuge talk thread, not the floating `#callTranscript` card.
- [ ] Call bar sits with the composer, not floating apart from the talk.
- [ ] After a call, Keep and Let it go work on the spoken talk like a typed one.
- [ ] "Connecting..." shows until Aquila's first words.
- [ ] Tested on iPhone and Android: mic allowed, mic refused, call never connects, hang up, screen locked mid-call.
- [ ] Time from tapping call to Aquila's first words measured: ______ seconds.

## 4. Speed

- [ ] Langfuse p95 time to first word on `/chat/stream` measured: ______ seconds (aim under 3).
- [ ] Something appears within 300 ms of pressing Send.
- [ ] Ground-check retry cost checked; capped at one retry if it often doubles the wait.
- [ ] Home screen tested on throttled 4G, cold and cached.
- [ ] Welcome page usable within ~2 seconds on a phone over cellular, private window.

## 5. Amens

- [ ] Wall seeded: 3 to 5 trusted people post real requests and good news in week one.
- [ ] A few people commit to praying through the wall daily, so every post gets amens within hours.
- [ ] "Add to Home Screen" nudge after a first post (iPhone needs it for notifications).
- [ ] Full loop tested on two accounts: post, amen, kind word, evening notification, mark answered.
- [ ] Moderation: urgent alerts reach my phone, the desk works on mobile, a report takes a post down at once.
- [ ] One-sentence description of Amens written for social posts.

## 6. Beta tester basics

- [ ] "Send feedback" link in the account menu (mailto or a form is enough).
- [ ] Welcome message for testers: what Adullam is, three things to try, how to report a bug.
- [ ] Error monitoring on (Sentry or similar), or at least a habit of checking Render logs.
- [ ] Full run on a real iPhone (Safari and Home Screen app) and Android: sign up, magic link, Aquila, Refuge, Amens, Prayers, Declare, Bible, Church.
- [ ] Dark themes and the largest text size checked for readability.
- [ ] Sign in, export and account deletion work end to end.
- [ ] Custom domain (optional, looks more trustworthy than onrender.com).

## 7. Social account

- [ ] Same handle everywhere, app icon as the picture, link in bio.
- [ ] Posts ready: what Adullam is, a screen recording of a grounded answer, Amens, the story of the name (1 Samuel 22).
