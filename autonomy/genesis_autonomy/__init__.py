"""Genesis autonomous construction workflow: deterministic state, gates, evidence and review.

The Claude Code session acts as the Genesis Lead. This package is the integration and state layer:
it decides what happens next, records every transition, and refuses (fails closed) whenever the
repository, the evidence or the state does not match what it expects. It never writes product code
and never certifies its own work.
"""
