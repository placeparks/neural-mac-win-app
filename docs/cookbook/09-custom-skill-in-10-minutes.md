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

## The Easiest Way: SkillScout

Before writing anything, check if someone has already published what you need:

```bash
neuralclaw scout find "what you need"
```

Scout searches public skill registries, picks the best candidate, and forges it through SkillForge automatically. If the result is close but not perfect, edit the generated file in `~/.neuralclaw/skills/`.

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
- Sandbox testing to verify the skill runs without errors when the packaged runtime can resolve a real Python interpreter
- Registration with the gateway so the router can call it immediately

### Windows packaged runtime note

In packaged desktop builds, SkillForge and `execute_python` depend on the sidecar resolving a real `python.exe`. NeuralClaw now prefers common installed interpreters and skips Microsoft Store `WindowsApps` aliases, but if sandbox verification still reports `Python was not found`, restart the backend after installing Python and confirm a real interpreter exists, for example:

```text
C:\Python313\python.exe
```

### Editing generated skills

The generated skill file lands in `~/.neuralclaw/skills/` and is a regular Python module. You can open it in any editor to adjust parameters, add error handling, or extend the logic. The gateway picks up changes automatically when `hot_reload = true` is set in the `[forge]` config section.
