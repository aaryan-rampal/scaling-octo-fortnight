# Connecting Slack MCP to Claude Code

This documents how to wire up the Slack MCP server so Claude can read channels, post messages, and search a Slack workspace — specifically for hackathon setups.

## What We Did

### Step 1 — Create a Slack App with the right scopes

Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.

Use a manifest to avoid manually adding scopes. Paste this into the **App Manifest** editor (YAML or JSON tab):

```json
{
  "display_information": {
    "name": "Slack MCP"
  },
  "oauth_config": {
    "scopes": {
      "user": [
        "channels:history",
        "channels:read",
        "groups:history",
        "groups:read",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "mpim:write",
        "users:read",
        "chat:write",
        "search:read",
        "usergroups:read",
        "usergroups:write"
      ]
    }
  },
  "settings": {
    "org_deploy_enabled": false,
    "socket_mode_enabled": false,
    "token_rotation_enabled": false
  }
}
```

After creating the app:
1. Go to **OAuth & Permissions** → click **Install to Workspace**
2. Copy the **User OAuth Token** (`xoxp-...`)

> **Critical:** Use the **User Token** (`xoxp-...`), not the Bot Token (`xoxb-...`). The MCP server uses user tokens by default via `SLACK_MCP_XOXP_TOKEN`.

### Step 2 — Add `.mcp.json` to the project root

Don't put this in `~/.claude/settings.json` — it won't reliably load. Instead create a `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": [
        "-y",
        "slack-mcp-server@latest",
        "--transport",
        "stdio"
      ],
      "env": {
        "SLACK_MCP_XOXP_TOKEN": "xoxp-YOUR-TOKEN-HERE"
      }
    }
  }
}
```

Replace `xoxp-YOUR-TOKEN-HERE` with the token from Step 1.

> **Note:** `.mcp.json` in the project root is the reliable path. `~/.claude/settings.json` requires a full Claude Code restart and can silently fail to load MCP servers.

### Step 3 — Restart Claude Code

MCP servers are initialized at session start. After creating `.mcp.json`, fully restart Claude Code in this directory. Then run `/mcp` — you should see `slack` listed as connected.

### Step 4 — Verify

Ask Claude: "list my Slack channels" — it should call `channels_list` and return results.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/mcp` shows no servers | MCP config not found — use `.mcp.json` in project root, not global settings |
| Server crashes with `missing_scope` | Add the missing scope in OAuth & Permissions on api.slack.com, reinstall the app, get a new token |
| `Authentication required` error running `npx slack-mcp-server` manually | That's expected — env vars come from `.mcp.json`, not your shell. The error is harmless if Claude can see the tools |
| Tools not available after restart | Run `/mcp` to check status; if still missing, check `.mcp.json` is valid JSON and the token starts with `xoxp-` |

## MCP Server Used

[`slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) — run via `npx`, no global install needed.
