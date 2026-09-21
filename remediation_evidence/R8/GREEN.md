# R8 green evidence

## Targeted acceptance

- Command: `python -m unittest tests.test_remediation_r8_quota -v`
- Result: **14/14 green**.
- Revised retained quota test: **1/1 green**.

## Full regression

- Command: `python -m unittest discover -s tests -t . -v`
- Result: **96/96 green**.
- Command: `python -m compileall -q src tests remediation_evidence/R8/red_before_probe.py`
- Result: **green**.
- Command: `git diff --check`
- Result: **green** (only Windows line-ending notices).
