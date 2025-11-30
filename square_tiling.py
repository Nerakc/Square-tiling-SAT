#!/usr/bin/env python3

from pathlib import Path
import argparse
import sys
import subprocess
import tempfile
import os
import re
import math


def read_instance_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"Error reading input file '{path}': {e}") from e


def prepare_dimacs(raw_instance: str, k: int) -> str:
    inst = parse_instance(raw_instance)
    dimacs = encode_instance_to_dimacs(inst, k)
    return dimacs


def encode_instance_to_dimacs(instance: dict, k: int) -> str:
    """Encode the instance into DIMACS CNF and return (dimacs_str, mapping).

    For now this constructs variable names for the facts "on tile(i,j) is tile t"
    using the convention <zeropadded_i><zeropadded_j><zeropadded_t> where the
    padding widths are computed as follows (per user request):
      - i and j are padded to ceil(log10(number of rows))
      - t is padded to ceil(log10(number of colors))

    The function returns an empty CNF (no clauses) together with a mapping
    from variable name to DIMACS variable id. This is the first step requested
    (variable naming / mapping); clause generation will be added later.
    """

    # number of rows in the square grid
    rows = int(k)
    # number of colours declared in the instance (may be 0)
    num_colors = max(1, len(instance.get("colors", {})))
    # number of tile types provided by the instance
    tiles = instance.get("tiles", [])
    num_tiles = max(0, len(tiles))

    def _pad_width(n: int) -> int:
        # follow the formula ceil(log10(n)) but ensure at least 1
        if n <= 1:
            return 1
        return max(1, math.ceil(math.log10(n)))

    w_i = _pad_width(rows+1)
    w_j = _pad_width(rows+1)
    # per the user's instruction use number of colours to size the tile index
    w_t = _pad_width(num_colors+1)

    def var_name(i: int, j: int, t: int) -> str:
        """Return the variable name for position (i,j) and tile index t.

        i, j, t are zero-based indices; produced name uses 1-based values
        but zero-padded according to computed widths.
        """
        si = str(i + 1).zfill(w_i)
        sj = str(j + 1).zfill(w_j)
        st = str(t + 1).zfill(w_t)
        return f"{si}{sj}{st}"

    # number of propositional variables: one per grid cell and tile type
    num_vars = rows * rows * num_tiles
    clauses: list[str] = []

    # on each position (i,j), exactly one tile t is placed
    for i in range(rows):
        for j in range(rows):
            # at least one tile t is placed at (i,j)
            at_least_one = []
            for t in range(num_tiles):
                vname = var_name(i, j, t)
                at_least_one.append(str(vname))
            clauses.append(" ".join(at_least_one) + " 0")

            # at most one tile t is placed at (i,j)
            for t1 in range(num_tiles):
                for t2 in range(t1 + 1, num_tiles):
                    vname1 = var_name(i, j, t1)
                    vname2 = var_name(i, j, t2)
                    clauses.append(f"-{vname1} -{vname2} 0")

    # check neighboring tiles for edge colour matching
    for i in range(rows):
        for j in range(rows):
            for t1 in range(num_tiles):
                tile1 = tiles[t1]
                # right neighbor
                if j + 1 < rows:
                    for t2 in range(num_tiles):
                        tile2 = tiles[t2]
                        if tile1[1] != tile2[3]:
                            vname1 = var_name(i, j, t1)
                            vname2 = var_name(i, j + 1, t2)
                            clauses.append(f"-{vname1} -{vname2} 0")
                # bottom neighbor
                if i + 1 < rows:
                    for t2 in range(num_tiles):
                        tile2 = tiles[t2]
                        if tile1[2] != tile2[0]:
                            vname1 = var_name(i, j, t1)
                            vname2 = var_name(i + 1, j, t2)
                            clauses.append(f"-{vname1} -{vname2} 0")

    dimacs_lines = [f"p cnf {num_vars} {len(clauses)}"]
    dimacs_lines.extend(clauses)
    dimacs = "\n".join(dimacs_lines) + "\n"

    return dimacs


def call_glucose(k: int, num_tiles: int) -> tuple[bool, list[list[int]], str]:
    # Invoke the `glucose-syrup` binary located in the project root and pass
    # the default CNF file name `output.cnf`. Capture the solver output and
    # decode any model lines that start with 'v '. Return a 2D model (or an
    # empty list on parse failure) to avoid type mismatches in callers.
    project_root = Path(__file__).resolve().parent
    bin_path = project_root / "glucose-syrup"

    proc = subprocess.run([str(bin_path), "-model", "output.cnf"],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,
                          text=True,
                          cwd=project_root,
                          check=False)

    output = proc.stdout or ""

    # Determine satisfiability from solver output
    is_sat = False
    for line in output.splitlines():
        if line.startswith("s SATISFIABLE"):
            is_sat = True
            break
        elif line.startswith("s UNSATISFIABLE"):
            is_sat = False
            break

    if not is_sat:
        return is_sat, [], output

    # Collect all 'v' lines and join their contents into a single text blob
    v_parts: list[str] = []
    for line in output.splitlines():
        if line.startswith("v "):
            v_parts.append(line[2:].strip())
    v_text = " ".join(v_parts)

    model: list[list[int]] = []
    try:
        model = solve_instance(v_text, k, num_tiles)
    except Exception:
        model = []

    return is_sat, model, output


def solve_instance(v_text: str, k: int, tiles: int) -> list[list[int]]:
    w_t = max(1, math.ceil(math.log10(tiles)))
    w_i = max(1, math.ceil(math.log10(k)))
    w_j = max(1, math.ceil(math.log10(k)))
    model = [[0 for _ in range(k)] for _ in range(k)]

    for num in v_text.split():
        val = int(num)
        if val > 0:
            print(num)
            s = str(val).zfill(w_i + w_j + w_t)
            i = int(s[0:w_i]) - 1
            j = int(s[w_i:w_i + w_j]) - 1
            # compute t now so we can store it immediately (the original t=... line
            # that follows will simply overwrite with the same value)
            t = int(s[w_i + w_j:])
            model[i][j] = t
    return model

def parse_instance(raw: str) -> dict:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return {"colors": {}, "tiles": []}

    idx = 0
    first_tokens = lines[0].split()
    if len(first_tokens) == 1 and first_tokens[0].isdigit():
        idx = 1

    if idx >= len(lines):
        return {"colors": {}, "tiles": []}

    colours_line = lines[idx]
    colour_names = [c for c in re.split(r"[,\s]+", colours_line.strip()) if c]
    colours = {name: i + 1 for i, name in enumerate(colour_names)}
    idx += 1

    tiles = []
    for line in lines[idx:]:
        s = line.strip()
        if s.startswith("<") and s.endswith(">"):
            s = s[1:-1].strip()
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        if len(parts) != 4:
            continue
        try:
            tiles.append(tuple(colours[p] for p in parts))
        except KeyError:
            continue

    return {"colors": colours, "tiles": tiles}


def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("k", type=int)
    p.add_argument("input_file", type=Path)
    p.add_argument("--dimacs-out", type=Path,
                   help="optional path to write DIMACS CNF (UTF-8) and exit")
    p.add_argument("--print-dimacs", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.k <= 0:
        print("k must be > 0", file=sys.stderr)
        return 2

    if not args.input_file.exists():
        print(f"input file '{args.input_file}' not found", file=sys.stderr)
        return 2

    raw = read_instance_file(args.input_file)

    instance = parse_instance(raw)

    # Always produce DIMACS encoding for the instance; by default write it
    # to `output.cnf` in the project directory so it can be inspected or
    # passed to the `glucose-syrup` binary. The `--dimacs-out` flag still
    # allows writing to a custom path and exiting early.
    dimacs = prepare_dimacs(raw, args.k)

    if args.dimacs_out:
        try:
            args.dimacs_out.write_text(dimacs, encoding='utf-8')
            print(f"Wrote DIMACS to {args.dimacs_out}")
        except Exception as e:
            print(
                f"Failed to write DIMACS to {args.dimacs_out}: {e}", file=sys.stderr)
            return 2
        return 0

    # default output path is `output.cnf` next to this script
    project_root = Path(__file__).resolve().parent
    default_cnf = project_root / "output.cnf"
    try:
        default_cnf.write_text(dimacs, encoding='utf-8')
        # print(f"Wrote DIMACS to {default_cnf}")
    except Exception as e:
        print(f"Failed to write DIMACS to {default_cnf}: {e}", file=sys.stderr)
        return 2

    if args.print_dimacs:
        print(dimacs)
        return 0

    # Call the external solver and show its output. The solver prints
    # detailed logs; when it reports SAT we print that output and exit
    # with the conventional exit code (10 for SAT, 20 for UNSAT).
    num_tiles = len(instance.get("tiles", []))
    is_sat, model, _ = call_glucose(args.k, num_tiles)

    if not is_sat:
        print("s UNSATISFIABLE")
        return 20

    # Solver reports SAT. Currently model decoding into an actual tiling
    # is not implemented, so just report satisfiable and exit 10.
    print("s SATISFIABLE")
    print("Model:")
    for row in model:
        print(" ".join(str(t) for t in row))
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
