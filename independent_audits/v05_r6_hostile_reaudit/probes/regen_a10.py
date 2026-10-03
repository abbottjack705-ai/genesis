"""Regenerate case <i> of a10 seed <s> (the generator consumes rng only in mutate()); write the body to out/."""
import sys
seed, idx = int(sys.argv[1]), int(sys.argv[2])
sys.argv = [sys.argv[0], str(seed), "0"]
src = open(__file__.replace("regen_a10.py", "a10_fuzz_e2e.py")).read().split("classes = collections.Counter()")[0]
exec(compile(src, "a10_fuzz_e2e.py", "exec"))
for i in range(idx + 1):
    raw, ops = mutate()
print("case", idx, "ops:", ops, "bytes:", len(raw))
open(SP + "/out/a10_seed%d_case%d_regen.json" % (seed, idx), "wb").write(raw)
