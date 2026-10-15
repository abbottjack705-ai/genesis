---
description: Explain the current or next human gate, what it covers, and what a human must do to clear it
allowed-tools: Bash(python -B autonomy/genesis_workflow.py *), Read
---

Run `python -B autonomy/genesis_workflow.py explain-gate` and `python -B autonomy/genesis_workflow.py go --select-only`
from the repository root. Then explain, in plain words:

1. whether the loop is waiting on a human gate right now, and which one (`current_gate`);
2. which gates are pending for later milestones (`pending_gates`) and that they do not stop unrelated paper work;
3. the exact approval a human operator must commit to clear the gate: `autonomy/approvals/<gate_id>.json` with
   `gate_id`, `approved_by` set to `human-operator`, and an `approval_reference`. The trigger list is in
   `autonomy/ENVELOPE.json` under `human_gate_triggers`.

Do not create or edit any approval file. Do not run `go`.
