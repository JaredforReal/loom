# Gmail Setup Guide

This guide walks you through connecting Loom's Gmail adaptor to your own Gmail account. After finishing, Loom will poll your inbox and deliver new messages into the Mailbox for review.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- A Gmail account
- macOS or Linux (Windows users: replace `~` with `%USERPROFILE%`)

## Step 1 — Create a Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project picker in the top bar → **New Project**.
3. Name it `loom-gmail-dev` (or anything you like) and create it.
4. Make sure the new project is selected before continuing.

## Step 2 — Enable the Gmail API

1. Go to **APIs & Services → Library**.
2. Search for **Gmail API** and click it.
3. Click **Enable**.

## Step 3 — Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** and click **Create**.
3. Fill in the required fields:
   - **App name**: `Loom`
   - **User support email**: your email
   - **Developer contact**: your email
4. Click **Save and Continue** to reach the **Scopes** step.
5. Click **Add or Remove Scopes**, then add:
   ```
   https://www.googleapis.com/auth/gmail.modify
   ```
6. Click **Save and Continue** to reach **Test users**.
7. Add your own Gmail address. (External + Testing apps can only be used by listed test users.)
8. Save and finish.

## Step 4 — Create OAuth client credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. **Application type**: select **Desktop app**.
4. Give it a name (e.g. `loom-desktop`) and create it.
5. Click **Download JSON** on the resulting client.

## Step 5 — Place the credentials file

```bash
mkdir -p ~/.loom/credentials
mv ~/Downloads/client_secret_*.json ~/.loom/credentials/gmail-client-secrets.json
```

The path above is a **recommended** location and name for local development, not a required filename. `GmailAdaptor` accepts the credentials file path explicitly via `client_secrets_path`, so if you store the file elsewhere, make sure your harness or CLI passes that path to the adaptor.

## Step 6 — Install the gmail extra

From the repo root:

```bash
uv sync --extra gmail
```

This installs `google-api-python-client`, `google-auth-oauthlib`, and friends.

## Step 7 — First run (OAuth consent in the browser)

Start the adaptor (e.g. via your harness or smoke script). On the first run:

1. A browser window opens automatically.
2. Pick the Google account you added as a test user.
3. You will see **"Google hasn't verified this app"**. Click **Advanced → Go to Loom (unsafe)**. This is expected because the app is still in Testing mode — you are the developer.
4. Approve the `gmail.modify` scope.
5. The browser shows "The authentication flow has completed."

A new file is now written:

```
~/.loom/credentials/gmail-token.json
```

This contains your access + refresh tokens. Loom will refresh them automatically; you do not need to redo Step 7 unless the token is revoked.

## File layout reference

After setup, `~/.loom/credentials/` contains:

| File | Source | Purpose |
|---|---|---|
| `gmail-client-secrets.json` | You (downloaded in Step 4) | OAuth client identification |
| `gmail-token.json` | Auto-generated on first run | Access + refresh tokens |

Both live outside the repo. Do not commit them.

## Troubleshooting

**"Access blocked: ... has not completed the Google verification process"**
You are not on the Test users list. Go back to **OAuth consent screen → Test users** and add your Gmail address.

**`invalid_grant` or "Token has been expired or revoked"**
Delete the token and re-run:
```bash
rm ~/.loom/credentials/gmail-token.json
```
The next run will pop the OAuth window again.

**No emails arriving after several minutes**
- The default query is `is:unread -in:chats newer_than:1d`. Send yourself an email from another account so it lands as unread.
- Check that the Gmail account you authorized is the one receiving the test email.
- Loom polls every 30 seconds by default; wait one full cycle.

**Want to start fresh**
Delete the whole credentials dir and redo Steps 4–7:
```bash
rm ~/.loom/credentials/gmail-client-secrets.json
rm ~/.loom/credentials/gmail-token.json
```
