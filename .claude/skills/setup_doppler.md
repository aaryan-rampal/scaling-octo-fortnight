# Setting Up Doppler for Shared Secrets

This documents how to connect to our shared Doppler project so you get all the API keys
(like `OPENROUTER_API_KEY`) without anyone passing `.env` files around in Slack.

> **You are joining an existing project — do not create your own.** The project is already
> set up. Your job is just to install the CLI, log in, and link your local repo to it.
> A couple of steps need Aaryan to grant you access — those are flagged with **🔔 Ping Aaryan**.

## Project Facts

| What | Value |
|---|---|
| Doppler project | `berkeley-hackathon` |
| Config | `dev` |
| Secrets you'll get | `OPENROUTER_API_KEY` (more added over time) |

## Step 1 — 🔔 Ping Aaryan to add you

Before anything works, Aaryan needs to invite you to the Doppler workspace.

**Send Aaryan:** the email address you'll use for Doppler.

Wait for him to confirm you've been added before continuing — otherwise Step 4 fails with
an access error.

## Step 2 — Install the Doppler CLI

```bash
brew install dopplerhq/cli/doppler
```

Verify it installed:

```bash
doppler --version
```

## Step 3 — Log in

```bash
doppler login
```

This opens a browser. Log in with the **same email you gave Aaryan in Step 1**.

## Step 4 — Link the repo

From the root of the repo (where `doppler.yaml` lives), run:

```bash
doppler setup --no-interactive -p berkeley-hackathon -c dev
```

This reads `doppler.yaml` and binds your local directory to the `berkeley-hackathon`
project, `dev` config. You only do this once per clone.

## Step 5 — Verify it worked

```bash
doppler secrets
```

You should see `OPENROUTER_API_KEY` listed (value masked). If you do — you're done. 🎉

Check the binding too:

```bash
doppler configure
```

Should show `project = berkeley-hackathon` and `config = dev`.

## Step 6 — Run the app with secrets injected

Don't source a `.env` file. Prefix your start command with `doppler run --`:

```bash
doppler run -- <your start command>
# e.g.  doppler run -- python main.py
# e.g.  doppler run -- node index.js
```

Doppler injects every secret as an environment variable for that process.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `This token does not have access to requested project` | You haven't been added yet, or logged in with the wrong email. **🔔 Ping Aaryan** to confirm you're on the workspace, then re-run `doppler login` with the right email. |
| `doppler secrets` shows the wrong project | Stale local binding. Re-run Step 4: `doppler setup --no-interactive -p berkeley-hackathon -c dev`. |
| Still wrong after re-setup | Check for an override: `echo $DOPPLER_TOKEN`. If it's set, it overrides everything — unset it (`unset DOPPLER_TOKEN`) and retry. |
| `command not found: doppler` | CLI didn't install — re-run Step 2 and check `doppler --version`. |
| Missing a key you expected | The secret may not be added yet. **🔔 Ping Aaryan** to add it to the `dev` config. |

## Need a new secret added?

You can't add secrets yourself (and shouldn't). **🔔 Ping Aaryan** with the key name and
value — he'll add it to the `berkeley-hackathon` / `dev` config and it'll show up for
everyone on the next `doppler secrets` / `doppler run`.
