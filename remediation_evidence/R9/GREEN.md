# R9 green evidence

## Targeted acceptance

- Command: `python -m unittest tests.test_remediation_r9_protected -v`
- Result: **11/11 green**.
- Retained legacy synthetic harness tests: **3/3 green**.

## Full regression

- Command: `python -m unittest discover -s tests -t . -v`
- Result: **107/107 green**.
- Command: `python -m compileall -q src tests remediation_evidence/R9/red_before_probe.py`
- Result: **green**.
- Command: `git diff --check`
- Result: **green** (only Windows line-ending notices).
