"""Regenerate the frozen LongMemEval_S 100-instance subset data file.

Frozen definition (2026-07-04): all 30 abstention instances plus 70
non-abstention instances sampled proportionally per question_type with
largest-remainder allocation, random.Random(42), from
data/longmemeval_s_cleaned.json. The resulting question_id list is committed
as data/longmemeval_s_subset100.txt; this script re-derives the data file
from that list (dataset order preserved), so the subset survives the
gitignored data/ tree.

Usage: python scripts/make_lme_subset100.py  (from the membench/ directory)
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    ids = set(
        (DATA_DIR / "longmemeval_s_subset100.txt").read_text().split(),
    )
    data = json.loads((DATA_DIR / "longmemeval_s_cleaned.json").read_text())
    subset = [e for e in data if str(e["question_id"]) in ids]
    if len(subset) != len(ids):
        missing = ids - {str(e["question_id"]) for e in subset}
        msg = f"dataset is missing {len(missing)} frozen instances: {sorted(missing)[:5]}"
        raise SystemExit(msg)
    out = DATA_DIR / "longmemeval_s_subset100.json"
    _ = out.write_text(json.dumps(subset))
    print(f"wrote {out} ({len(subset)} instances)")


if __name__ == "__main__":
    main()
