# R7 green evidence

## Targeted acceptance

- Command: `python -m unittest tests.test_remediation_r7_settlement -v`
- Result: **7/7 green**.

## Full regression

- Command: `python -m unittest discover -s tests -t . -v`
- Result: **82/82 green**.
- Command: `python -m compileall -q src tests`
- Result: **green**.
- Command: `git diff --check`
- Result: **green** (only Windows line-ending notices).
