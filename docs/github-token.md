# Getting and Configuring a GitHub Token

## Creating a Token

1. Go to GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** (recommended) or **Tokens (classic)**

   Direct link: https://github.com/settings/tokens

2. Click **Generate new token**

3. Fill in:

| Field | Value |
|---|---|
| Token name | `loom` |
| Expiration | As needed (90 days recommended) |
| Repository access | **Only select repositories** → pick the repos you want to monitor |
| Permissions → Issues | **Read and write** (read issues/PRs + post comments/close/label) |
| Permissions → Pull requests | **Read and write** (same as above) |

> If you're using a **Classic token**, check the `repo` scope — that covers everything you need.

4. Click **Generate token** and copy the generated token (starts with `github_pat_` or `ghp_`)

## Configuring the Token

### Option 1: Environment Variable (recommended)

```bash
# Add to your shell config for persistence
echo 'export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"' >> ~/.zshrc
source ~/.zshrc

# Verify
echo $GITHUB_TOKEN
```

### Option 2: .env File

```bash
# Create .env in the project root
echo 'GITHUB_TOKEN=ghp_xxxxxxxxxxxx' >> ~/.env
```

> Make sure `.env` is in `.gitignore` — never commit it to version control.

## Verifying the Token

```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/vllm-project/vllm/issues?per_page=1 \
  | head -5
```

If you get JSON data back (instead of `401` or `message: "Bad credentials"`), the token is configured correctly.

## Token Permissions Reference

| Action | Required Permission |
|---|---|
| Read issues/PRs | Issues: Read, Pull requests: Read |
| Post comments | Issues: Read and write |
| Close issues/PRs | Issues: Read and write |
| Add/remove labels | Issues: Read and write |

If you only need monitoring without executing actions, **Read-only** is sufficient.

## Rate Limits

The GitHub API allows **5,000 requests per hour** for authenticated users. Loom uses ETag caching and the `since` parameter to minimize requests — typical usage (monitoring 1–5 repos with a 120-second poll interval) consumes about 150–300 requests per hour, well within the limit.

```bash
# Check current rate limit status
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/rate_limit | python3 -m json.tool
```
