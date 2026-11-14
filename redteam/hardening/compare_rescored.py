#!/usr/bin/env python3
"""Compare the official scores of the verification run (a fresh run at the final
budget) with the scores obtained earlier by rescoring a larger-cap run.

Only ranked metrics are compared: audit fields such as budget_stop_count
legitimately differ between a run capped at 60G and one capped at 30G."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    old_dir = ROOT / "tmp" / "rescored"
    reference = json.loads((ROOT / "scoring" / "reference.json").read_text())["experiments"]
    ranked = {(e, m) for e, ex in reference.items() for m, md in ex["metrics"].items() if md["coefficient"] != 0}
    out = {}
    for split in ("test", "train"):
        old = json.loads((old_dir / f"scores_{split}.json").read_text())
        new = json.loads((ROOT / "scoring" / f"scores_{split}.json").read_text())
        diffs = {}
        for exp, block in new["experiments"].items():
            for method, metrics in block["results"].items():
                for metric, value in metrics.items():
                    if not isinstance(value, (int, float)) or (exp, metric) not in ranked:
                        continue
                    before = old["experiments"].get(exp, {}).get("results", {}).get(method, {}).get(metric)
                    if before is None or abs(before - value) > 1e-9:
                        diffs[f"{exp}/{method}/{metric}"] = [before, value]
        out[split] = diffs
        print(f"{split}: {len(diffs)} differing scored values" + (f": {json.dumps(diffs)[:2000]}" if diffs else ""))
    (ROOT / "redteam" / "hardening" / "verification_vs_rescored.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
