# B7 mode/safety RED reproduction — 2026-09-23

- Audited detached base: `27dd525c1fd7d531c4833c4bf7e44204a9345f19` at `work/t1-mode-red-27dd`.
- The detached worktree was clean before copying only `tests/test_astra_t1_mode.py` into it. No production file there was changed.
- Test source SHA-256: `CE089665C2487BA35C05899E44F93F3E1ACB461648C28DF66F0B3910A349365E`.
- Command from that detached worktree: `python -m unittest tests.test_astra_t1_mode -v`.
- Exit code: `1`; 6 tests, 6 failing invariant assertions, 0 setup/import errors. The stable PAPER positive and post-order settlement positive passed. The six failures covered DISABLED at pending/sent, crash between mode/safety rows at pending/sent, missing mode owner, and an unpaired safe safety head.
- Exact output: `b7_mode_red_27dd.txt`, SHA-256 `20C6E195922EB1FF06F9C696B5E9884789A43280F68CBAA25B81EB8D86AC51EC`.

The RED test is synthetic PAPER-only; it grants no operational strategy, adapter, campaign, shadow-research or live-money approval.
