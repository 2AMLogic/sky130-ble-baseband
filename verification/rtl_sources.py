"""The one place a Verilog source list comes from: rtl/baseband.f.

`rtl/baseband.f` is the file list of `baseband_top`, one repo-relative path per
line, read directly by `verilator -f`, `flow/synth/synth.tcl` and
`flow/synth/profile.sh`. Its `# block:` / `# reuse:` comments (format documented
in the file's own header) group those paths into the per-block lists that the
block lints and the block benches compile, so each block's membership is
declared once and both consumers read that declaration:

    from rtl_sources import block_sources     # verification/*/run_*.py
    python3 verification/rtl_sources.py --out <f> <block>   # `make lint`

Both markers must start at column 0 and read exactly `# block: ` / `# reuse: `.
A marker-looking line that is indented is an error rather than a silently
ignored comment: the three consumers that read `rtl/baseband.f` directly do not
agree on leading whitespace (`verilator -f` and verification/top/run_top.py's
historical filter required column 0, synth.tcl and profile.sh trim first), so
column 0 is the only position that means the same thing everywhere.
"""

import sys
from pathlib import Path

LIST = Path(__file__).resolve().parents[1] / "rtl" / "baseband.f"

_BLOCK = "block:"
_REUSE = "reuse:"


def _parse(list_path):
    """Return (every path in file order, {block name: [path, ...]}).

    Paths are repo-relative strings, exactly as written in the list.
    """
    top, blocks, current = [], {}, None
    for lineno, raw in enumerate(list_path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            body = line[1:].strip()
            tag = next((t for t in (_BLOCK, _REUSE) if body.startswith(t)), None)
            if tag is None:
                continue  # an ordinary comment
            if not raw.startswith("# " + tag + " "):
                raise ValueError(
                    f"{list_path}:{lineno}: a '# {tag}' marker must start at column 0 "
                    f"and read exactly '# {tag} <argument>...'; got {raw!r}")
            args = body[len(tag):].split()
            if tag == _BLOCK:
                if len(args) != 1:
                    raise ValueError(f"{list_path}:{lineno}: '# {_BLOCK}' takes one "
                                     f"block name, got {args}")
                current = args[0]
                if current in blocks:
                    raise ValueError(f"{list_path}:{lineno}: block {current!r} is "
                                     f"declared more than once")
                blocks[current] = []
            else:
                if current is None:
                    raise ValueError(f"{list_path}:{lineno}: '# {_REUSE}' outside any "
                                     f"'# {_BLOCK}' section")
                if not args:
                    raise ValueError(f"{list_path}:{lineno}: '# {_REUSE}' needs at "
                                     f"least one path")
                for path in args:
                    if path not in top:
                        raise ValueError(
                            f"{list_path}:{lineno}: '# {_REUSE} {path}' is not "
                            f"declared earlier in this file; reuse only names a "
                            f"path another block already owns")
                    if path in blocks[current]:
                        raise ValueError(f"{list_path}:{lineno}: {path!r} is already "
                                         f"in block {current!r}")
                    blocks[current].append(path)
            continue
        if current is None:
            raise ValueError(f"{list_path}:{lineno}: {line!r} appears before any "
                             f"'# {_BLOCK}' marker")
        if line in top:
            raise ValueError(f"{list_path}:{lineno}: {line!r} is listed more than once")
        top.append(line)
        blocks[current].append(line)
    return top, blocks


def _resolve(paths, list_path):
    root = Path(list_path).resolve().parents[1]
    return [root / p for p in paths]


def rtl_sources(list_path=LIST):
    """Every source of `baseband_top`, in list order, as absolute paths."""
    return _resolve(_parse(Path(list_path))[0], list_path)


def block_sources(name, list_path=LIST):
    """The sources of one `# block:` section, in list order, as absolute paths."""
    blocks = _parse(Path(list_path))[1]
    if name not in blocks:
        raise KeyError(f"{list_path}: no '# {_BLOCK} {name}' section "
                       f"(declared: {', '.join(blocks)})")
    return _resolve(blocks[name], list_path)


def block_modules(name, list_path=LIST):
    """The module names of one block: one module per file, named after its file."""
    return [p.stem for p in block_sources(name, list_path)]


def check(list_path=LIST):
    """Problems with the list, as messages; empty means it is complete.

    A `.v` under rtl/ that no section declares would be linted by nothing
    and synthesised into nothing -- the silent gap dropping the directory
    globs would otherwise leave. A declared path that does not exist breaks
    both consumers at once.
    """
    path = Path(list_path)
    root = path.resolve().parents[1]
    declared = _parse(path)[0]
    problems = [f"{p}: declared in {path.name} but not on disk"
                for p in declared if not (root / p).is_file()]
    problems += [f"{p}: on disk but no '# {_BLOCK}' section declares it; add it "
                 f"to {path.name} or delete it"
                 for p in sorted(str(v.relative_to(root))
                                 for v in (root / "rtl").rglob("*.v"))
                 if p not in declared]
    return problems


def main(argv):
    out, modules, args = None, False, []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = next(it, None)
            if out is None:
                return _usage("--out needs a path")
        elif a == "--modules":
            modules = True
        elif a == "--check":
            problems = check()
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"rtl-list OK: {len(rtl_sources())} files, all declared and present")
            return 0
        elif a == "--all":
            args.append(a)
        elif a.startswith("-"):
            return _usage(f"unknown option {a}")
        else:
            args.append(a)
    if len(args) != 1:
        return _usage("expected exactly one block name (or --all)")
    if modules and args[0] == "--all":
        return _usage("--modules takes a block name, not --all")
    try:
        if modules:
            lines = block_modules(args[0])
        elif args[0] == "--all":
            lines = [p.relative_to(LIST.parents[1]) for p in rtl_sources()]
        else:
            lines = [p.relative_to(LIST.parents[1]) for p in block_sources(args[0])]
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e.args[0]}", file=sys.stderr)
        return 1
    text = "".join(f"{v}\n" for v in lines)
    if out is None:
        sys.stdout.write(text)
    else:
        header = ("# Generated from rtl/baseband.f by verification/rtl_sources.py "
                  f"({args[0]}). Do not edit.\n")
        dest = Path(out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(header + text)
    return 0


def _usage(msg):
    print(f"ERROR: {msg}\n"
          f"usage: {Path(__file__).name} [--out FILE] [--modules] <block>|--all\n"
          f"       {Path(__file__).name} --check",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
