"""Generate the klt functional-verification requests (issue #202).

    $(PYTHON) verification/fv/make_requests.py --out manifests/requests/fv
    $(PYTHON) verification/fv/make_requests.py --check

Every request's `sources` come from `rtl/baseband.f` through
`verification/rtl_sources.py` (via suite.py), so the file list still has one
place it is declared. The generated documents are committed: they are the
exact inputs the committed reports were produced from. `--check` regenerates
them into a scratch directory and byte-compares -- a hand-edited request, a
`rtl/baseband.f` change or a suite.py change without regeneration fails
`make fv-requests-check` (part of `make lint`), so the committed requests can
never silently drift from the file list.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import suite  # noqa: E402


def documents():
    """{(request file name): request document}, positives then negatives."""
    docs = {f"{b['name']}.json": suite.request(b) for b in suite.POSITIVE}
    docs.update({n["name"] + ".json": suite.request(suite.positive_by_name(n["base"]),
                                                    extra_env=n["env"])
                 for n in suite.NEGATIVE})
    return docs


def write(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name, doc in sorted(documents().items()):
        (out / name).write_text(_render(doc) + "\n")


def _render(doc):
    import json
    return json.dumps(doc, indent=2)


def check(outdir):
    """Regenerate into a scratch dir and compare against the committed set."""
    committed = {p.name for p in Path(outdir).glob("*.json")}
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp)
        fresh = {p.name for p in Path(tmp).glob("*.json")}
        for name in sorted(committed - fresh):
            problems.append(f"{outdir}/{name}: committed but no longer generated; "
                            f"delete it (suite changed)")
        for name in sorted(fresh - committed):
            problems.append(f"{outdir}/{name}: generated but not committed; "
                            f"run 'make fv-requests'")
        for name in sorted(committed & fresh):
            want = (Path(tmp) / name).read_text()
            got = (Path(outdir) / name).read_text()
            if want != got:
                problems.append(f"{outdir}/{name}: differs from the generated "
                                f"document; run 'make fv-requests'")
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1
    n_pos, n_neg = len(suite.POSITIVE), len(suite.NEGATIVE)
    print(f"fv-requests OK: {n_pos} requests + {n_neg} negative controls, "
          f"all match rtl/baseband.f through verification/rtl_sources.py")
    return 0


def main(argv):
    out, mode = suite.REQUESTS_DIR, "write"
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = next(it, None)
            if out is None:
                return _usage("--out needs a directory")
        elif a == "--check":
            mode = "check"
        else:
            return _usage(f"unknown argument {a}")
    if mode == "check":
        return check(out)
    write(out)
    print(f"wrote {len(documents())} request documents to {out}")
    return 0


def _usage(msg):
    print(f"ERROR: {msg}\n"
          f"usage: {Path(__file__).name} [--out DIR] [--check]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
