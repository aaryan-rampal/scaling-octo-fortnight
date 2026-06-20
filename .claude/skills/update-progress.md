# Update Progress

Log a timestamped progress update to `current.md` for one of the four RETURN hackathon team members: Aaryan, Derek, Nisa, or Selin.

## When to use

Invoke this skill when a team member wants to record what they've done or are working on. Use `/update-progress <name>` — the name argument is required.

## Steps

Follow these steps exactly, in order.

### 1. Identify the person

Extract the name argument from the invocation. Fuzzy-match it against the four known names:

- Aaryan (also: Aryan, aaryan)
- Derek (also: Derick, derek)
- Nisa (also: nisa)
- Selin (also: Celine, selin, celine)

Tell the user which name you matched. Ask them to confirm before proceeding:

> "I'll log this under **[Matched Name]** — is that right?"

If they say no or the name doesn't match any of the four, ask them to clarify.

### 2. Ask for the update

Once the name is confirmed, ask:

> "What's your progress update? Give as much or as little detail as you want — technical or user-friendly, whatever fits."

Wait for their response.

### 3. Get the current time

Get the current time in **US/Pacific timezone** formatted as `HH:MM PT` (24-hour clock, e.g. `14:32 PT`).

Run this command to get it:

```bash
TZ="America/Los_Angeles" date "+%H:%M PT"
```

### 4. Read current.md

Read `/Users/aaryanrampal/personal/programs/github_clones/recall/current.md` to get the current file contents.

### 5. Append the bullet

Find the `## [Confirmed Name]` section. Append a new bullet on a new line at the end of that section, before the next `##` heading (or end of file):

```
- [HH:MM PT] <their update text>
```

Write the updated file back.

### 6. Confirm

Tell the user:

> "Logged under **[Name]** at [HH:MM PT]. Here's what was added:
> `- [HH:MM PT] <update>`"
