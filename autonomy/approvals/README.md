# Human approvals for gated milestones

A milestone with a `human_gate` in `autonomy/ROADMAP.json` does not start until a human operator
commits `autonomy/approvals/<gate_id>.json`, shaped like this:

```json
{
  "gate_id": "HG-A2-LIVE-PROVIDER",
  "approved_by": "human-operator",
  "approval_reference": "<ADR, PR, signed tag or message link that holds the approval>",
  "scope": "exactly what is being approved, and nothing more"
}
```

Agents must never create, edit or commit a file in this directory. The engine checks the shape of the
file; it cannot prove who wrote it. Keeping that rule is a procedure, not a mechanism (see
autonomy/README.md, residuals).
