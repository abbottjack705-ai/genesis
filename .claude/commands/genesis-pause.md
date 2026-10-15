---
description: Pause the Genesis construction loop at its next safe point, with a reason
argument-hint: <reason>
allowed-tools: Bash(python -B autonomy/genesis_workflow.py *)
---

Run `python -B autonomy/genesis_workflow.py pause --reason "$ARGUMENTS"` from the repository root and report the
JSON. If a `go` is running, the engine stops at its next safe point and says so; report that. Pausing changes
no code and no evidence. To continue later, the operator runs `/genesis-go` after `resume`.

If no reason was given, ask the operator for one in a single line before pausing.
