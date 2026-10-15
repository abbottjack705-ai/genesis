---
description: Show the resumable Genesis construction state and the next milestone, without advancing anything
allowed-tools: Bash(python -B autonomy/genesis_workflow.py *)
---

Run `python -B autonomy/genesis_workflow.py status` and `python -B autonomy/genesis_workflow.py go --select-only`
from the repository root. Report, briefly and in plain words:

- the phase, the active milestone and round, the remaining tasks, the candidate SHA if one is frozen;
- the validation, skeptic and Codex results for the active candidate, if any;
- any halt (kind and reason), any human gate, and the milestone `go` would start next;
- the ledger length and the state digest, so the operator can see the state is intact.

Do not run `go`, `task-done`, `record-skeptic` or any other command that changes state.
