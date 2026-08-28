# Login and accounts — design note

**Status: proposal, nothing implemented.** Written because the cookie model has a
correctness problem, not just a convenience one.

## What we have today

A `child_id` UUID in an httpOnly cookie, one year expiry. It keys sessions, the pitch and
volume baseline, topic history, streaks and consent. No account, no password, no PII.

## Why this actually breaks

Three of these are annoyances. The second is a bug.

1. **One browser only.** Practise on the laptop, and the tablet is a stranger with an empty
   history and no baseline.
2. **Siblings silently corrupt each other's baseline.** Two children on one browser share a
   `child_id`. The per-child pitch and volume baseline — the whole reason a 7 year old is not
   told they are shrieking — is then averaged across two different voices. It does not error.
   It just quietly produces wrong feedback for both of them. **This is the strongest argument
   for accounts and it is not a UX argument.**
3. **Clearing cookies deletes the streak.** Streaks are the retention mechanic; losing one to
   a browser clean-up is the kind of thing that ends the habit.
4. **The consent record cannot be verified.** A cookie plus a typed name does not demonstrate
   that a parent consented. DPDP 2023 asks for *verifiable* parental consent, and today we
   have an honour-system checkbox.

## The shape I would build

**The account belongs to the parent. Children are profiles under it.** A 7 year old should
never hold credentials, and a 13 year old should not be the party consenting to their own
data collection.

```
parents   (id, email, created_at, last_login_at)
children  (id, parent_id, name, age_band, created_at)
consents  (id, parent_id, child_id, granted_at, method, ip, user_agent)
devices   (id, parent_id, token_hash, label, created_at, last_seen_at)
sessions  (… child_id unchanged …)
```

Consent moves out of `children` into its own append-only `consents` table. If we ever have to
show *when* and *how* consent was obtained, a mutable column on the child row will not do it.

### Two different login paths, because two very different users

**Parent — email magic link.** Enter email, receive a one-time link, click it. No password to
store, no reset flow, no breach surface, and the email itself is the verifiable thing DPDP
wants attached to consent.

**Child — no login at all.** Once a parent has signed in on a device, that device holds a
long-lived token. The child sees a profile picker and taps their own name. Netflix, not
Gmail. An optional 4-digit PIN per profile if siblings need separating, off by default.

### Parent-gated areas

This matters more now that the child can see the full report. Two things must stay behind a
parent check, not just a link:

- **Delete all data** — irreversible, and trivially reachable by a bored child.
- **Changing or withdrawing consent.**

A "parent unlocked" flag on the session, cleared after ~15 minutes and re-obtained with a
fresh magic link or a parent PIN. The dashboard itself can stay open; the destructive
controls cannot.

### Migrating today's cookie users

On first sign-in, if the browser carries an anonymous `child_id` with sessions attached,
offer: *"We found 12 speeches on this device. Add them to <name>'s profile?"* Re-parent the
rows. Without this, signing up costs you your entire history and streak, which is a terrible
trade to offer someone at exactly the moment you are asking them to commit.

## What I would deliberately not do

- **No Google or Facebook login.** The app currently promises no third parties and makes zero
  external requests. Social login hands a family's identity to an ad company and makes that
  promise false.
- **No passwords for children.** They forget them, share them, and it teaches nothing.
- **No child email, no full name, no date of birth.** The app only ever uses the age band. A
  first name is enough to label a profile. Every extra field is liability on a database of
  minors' voices.
- **No usernames.** Another thing to forget, and it adds nothing over a profile picker.

## The real cost

One new external dependency: **sending email**. That is the whole complexity of this feature.
Resend or Postmark free tiers, or plain SMTP.

### The alternative that avoids email entirely

A **family code**: a short readable string (`brave-tiger-4417`) generated at signup and typed
on a second device. No email, no third party, no sending infrastructure, works offline.

I would not lead with it. It proves nothing about parenthood, so it does not improve the
consent position at all, and there is no recovery when it is lost. It is a good *addition* to
magic links for quickly pairing a tablet, and a poor replacement.

## Recommendation

Parent email magic link, child profile picker, consent moved to its own table, and a
claim-your-history migration.

Rough order if we build it:

1. `parents` / `children` / `consents` tables and the migration path from the cookie
2. Magic link sign-in for the parent
3. Profile picker and per-profile baselines — **this is the part that fixes the sibling bug**
4. Device tokens so the child is not asked to sign in
5. Parent-unlock gate on delete and consent

Step 3 is the one with real correctness value. Steps 1 and 2 exist to make step 3 possible.
If we only ever ship part of this, ship enough to get separate profiles.
