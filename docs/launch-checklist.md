# Launch checklist: family, friends and beta testers

Tick a box by changing `[ ]` to `[x]`.

## 1. Must fix first

- [x] Custom SMTP in Supabase (Auth > SMTP, e.g. Resend or Postmark). The built-in mailer sends only a few magic links an hour.
- [x] Render off the free plan (`render.yaml` says `plan: free`). A sleeping server makes the first visitor wait 30 to 60 seconds.
- [x] Voice: move off the Cognigy trial endpoint (`web/index.html`, `VOICE_CONFIG_URL`), or confirm its limits and expiry.
- [x] Privacy and Terms: fill every [bracketed] part (operator name, retention, backup window, age, jurisdiction). Operator reads "a team of two, not-for-profit"; put the legal name in once there is one.
- [x] `hello@adullamapp.com` is a real inbox that reaches me.
- [x] Link previews: add `og:title`, `og:description`, `og:image` (1200x630) and `og:url` to `web/index.html`.
- [x] Spending: hard monthly limit set with the model provider.
- [x] Daily limits live: run `supabase/migrations/20261121_usage_limits.sql`, then ask as a guest 6 times and see the gentle "Sign in" message.
- [x] `MCP_SECRET` set on Render and added to Cognigy's MCP node (as `Authorization: Bearer ...` or `?key=...` on the URL); a voice call still answers.
- [ ] Guest counting checked on Render: two phones on different networks each get their own 5 questions (confirms the real address header arrives).
- [ ] Cognigy's per-minute price known and set as `COST_VOICE_CALL_USD`; a maximum session length set in Cognigy too.
- [x] Every migration run in production, through `20261127_amens_news.sql`; every tab opened signed in with no "run this" message.
- [x] Render secrets set: VAPID keys, `VAPID_SUBJECT`, `CRON_SECRET`, Langfuse, support links, `SENTRY_DSN`, `DEEPGRAM_API_KEY`, and `BETA=true`.
- [x] GitHub repo secrets set: `DEPLOY_URL`, `CRON_SECRET`.
- [x] Supabase Auth redirect URLs include the final domain.
- [x] change name to adullam
- [ ] Stray files out of the repo: `build/lib/` (a copy of `app/` from a local package build) and `--laptop/` (test screenshots), with `build/` added to `.gitignore`.

## 2. AI provider

- [x] OpenAI account topped up (embeddings and moderation need it even if chat moves elsewhere).
- [ ] Chat model and provider configurable from `.env` (one shared factory instead of `ChatOpenAI(...)` in each file).
- [ ] Test set of ~30 real questions (study, Refuge, Declare, plans, meta) run against each candidate model.
- [ ] Chosen model passes: no invented verses, ground check works, structured outputs parse, no em dashes, care check catches distress.
- [x] Privacy page updated to name the new provider and where it processes data.

## 3. Voice call

- [x] Spoken turns appear as ordinary bubbles in the Refuge talk thread, not the floating `#callTranscript` card.
- [x] Call bar sits with the composer, not floating apart from the talk.
- [ ] After a call, Keep and Let it go work on the spoken talk like a typed one.
- [x] "Connecting..." shows until Aquila's first words.
- [x] Tested on iPhone and Android: mic allowed, mic refused, call never connects, hang up, screen locked mid-call.
- [x] Time from tapping call to Aquila's first words measured: ______ seconds.

### Speak with Aquila (Deepgram)

- [ ] Deepgram account has a spending limit, and its price per turn is checked against `COST_SPEECH_USD` (0.002 now).
- [ ] Mic shows beside Send and on the home ask box only when signed in; the note on where the voice goes appears before the first use.
- [ ] Tested on iPhone and Android: a full back and forth, Stop, Done when the pause isn't heard, 30 quiet seconds, leaving Aquila, locking the screen.
- [ ] A spoken question shows up in the conversation rail like a typed one, with its citations.
- [ ] A long answer reads aloud with no gap or cut-off between pieces.

## 4. Speed

- [ ] Langfuse p95 time to first word on `/chat/stream` measured: ______ seconds (aim under 3).
- [ ] Something appears within 300 ms of pressing Send.
- [ ] Ground-check retry cost checked; capped at one retry if it often doubles the wait.
- [ ] Home screen tested on throttled 4G, cold and cached.
- [ ] Welcome page usable within ~2 seconds on a phone over cellular, private window.

## 5. Amens

- [ ] Wall seeded: 3 to 5 trusted people post real requests and good news in week one.
- [ ] A few people commit to praying through the wall daily, so every post gets amens within hours.
- [x] "Add to Home Screen" nudge after a first post (iPhone needs it for notifications). Elsewhere it offers notifications instead (`notify.js::offerAfterPost`).
- [ ] Full loop tested on two accounts: post, amen, kind word, evening notification, mark answered.
- [ ] Moderation: urgent alerts reach my phone, the desk works on mobile, a report takes a post down at once.
- [ ] One-sentence description of Amens written for social posts.

## 6. Beta tester basics

- [x] "Send feedback" link in the account menu (mailto or a form is enough). Also in Settings and the welcome footer.
- [x] Welcome message for testers: what Adullam is, three things to try, how to report a bug (`docs/beta-welcome.md`).
- [x] Beta note opens after the welcome tour (or on the home screen for anyone welcomed before), with the Beta tag by the logo and About the beta in Settings to bring it back.
- [x] Welcome tour and beta note scroll to their buttons on phones, tablets and laptops.
- [ ] Error monitoring on: create a Sentry project and set `SENTRY_DSN` on Render (server side is built in, `app/monitoring.py`).
- [ ] Full run on a real iPhone (Safari and Home Screen app) and Android: sign up, magic link, the welcome tour and beta note, every home shortcut, Aquila (typed and spoken), Refuge, Amens, Prayers, Declare, Bible, Church.
- [ ] Dark themes and the largest text size checked for readability.
- [x] Sign in, export and account deletion work end to end.
- [x] Custom domain: adullamapp.com added on Render, DNS set in Cloudflare (DNS only), certificate issued, and the address added to Supabase Auth > URL Configuration.

## 7. Social account

- [ ] Same handle everywhere, app icon as the picture, link in bio.
- [ ] Posts ready: what Adullam is, a screen recording of a grounded answer, Amens, the story of the name (1 Samuel 22).

## 8. When the beta ends

- [ ] `BETA=false` on Render, so the note, the Beta tag and About the beta go away.
- [ ] Testers thanked, and `docs/beta-welcome.md` kept for the next round or retired.
