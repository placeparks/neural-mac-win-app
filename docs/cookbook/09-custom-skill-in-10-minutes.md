# Tutorial 09 - Custom Skill in 10 Minutes

## Goal
Add a new built-in style skill and verify it loads.

## Steps
```bash
neuralclaw gateway --dev
```

Create the skill in the registry pattern already used by built-ins, restart the gateway, and inspect `/skills`.

## Expected result
The new skill shows up in the dashboard and can be called by the router.

## The Easy Way: SkillForge

Instead of manually writing a skill from scratch, you can use **SkillForge** to generate one in seconds.

### From Telegram

Send `/forge` in any paired chat:

```text
/forge twilio for: send appointment reminders
```

NeuralClaw generates the skill file, runs static analysis and sandbox tests, registers it with the gateway, and confirms -- all in one step.

### From the CLI

```bash
neuralclaw forge create "twilio" --use-case "send appointment reminders"
```

### What SkillForge handles automatically

- Boilerplate code with a valid `get_manifest()` entry point
- Skill manifest generation (name, description, parameters)
- Static analysis to catch security issues before registration
- Sandbox testing to verify the skill runs without errors
- Registration with the gateway so the router can call it immediately

### Editing generated skills

The generated skill file lands in `~/.neuralclaw/skills/` and is a regular Python module. You can open it in any editor to adjust parameters, add error handling, or extend the logic. The gateway picks up changes automatically when `hot_reload = true` is set in the `[forge]` config section.
