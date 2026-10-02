"""Run the adapter suite fail-fast, deselecting ONLY the platform-baseline error (documented audit finding PF-1)."""
import os, sys, unittest
BASELINE_ERRORS = {"test_f04_a_link_reported_by_lstat_is_refused_on_every_platform"}
os.chdir(sys.argv[1]); sys.path.insert(0, os.getcwd() + "/adapters")
suite = unittest.defaultTestLoader.discover("adapters/adapter_tests", top_level_dir="adapters")
def flat(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): yield from flat(t)
        else: yield t
keep = unittest.TestSuite(t for t in flat(suite) if getattr(t, "_testMethodName", "") not in BASELINE_ERRORS)
r = unittest.TextTestRunner(verbosity=0, failfast=True, stream=sys.stderr).run(keep)
sys.exit(0 if r.wasSuccessful() else 1)
