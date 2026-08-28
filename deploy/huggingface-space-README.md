---
title: Podium
emoji: 🎤
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Podium

Speaking practice for children aged 6 to 14. It scores what they said as well as
how they said it.

Source: https://github.com/Almas-ansari/podium

## Space secrets to set

Settings → Variables and secrets:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | from https://console.groq.com/keys |
| `GOOGLE_CLIENT_ID` | from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | from Google Cloud Console |
| `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | a free Neon Postgres connection string |
| `ALLOW_DEV_LOGIN` | `false` |

Add `https://<your-space>.hf.space/auth/callback` to the Google OAuth client's
authorised redirect URIs, or sign-in will fail with `redirect_uri_mismatch`.
