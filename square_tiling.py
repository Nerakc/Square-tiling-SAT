#!/usr/bin/env python3

import math
from pathlib import Path
import argparse
import sys
import re
import subprocess
import shutil
import tempfile
import os


def read_instance_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        raise SystemExit(f"Error reading input file '{path}': {e}") from e


def prepare_dimacs(raw_instance: str, k: int) -> str:
    inst = parse_instance(raw_instance)
    dimacs, _mapping = encode_instance_to_dimacs(inst, k)
    return dimacs


def encode_instance_to_dimacs(instance: dict, k: int) -> tuple[str, dict]:
    """Encode the given instance to DIMACS format.
    Returns a tuple of (dimacs_string, variable_mapping_dict).

    The variable_mapping_dict maps (i, j, tile_index) to DIMACS variable numbers.
    The fact that on position (i, j) tile with index tile_index is encoded as zero-padded decimal number tripplets
    """
    colors = instance.get("colors", {})
    tiles = instance.get("tiles", [])

    # count how large the decimal encoding needs to be
    color_dec_len = math.ceil(math.log10(len(colors))) if colors else 0
    tile_dec_len = math.ceil(math.log10(len(tiles))) if tiles else 0
    var_mapping = {}
    clauses = []
    var_counter = 1
    for i in range(k):
        for j in range(k):
            for t_index, tile in enumerate(tiles):
                var_mapping[(i, j, t_index)] = var_counter
                var_counter += 1
            # Add clauses to ensure at least one tile is placed at (i, j)
            clause = [var_mapping[(i, j, t_index)]
                      for t_index in range(len(tiles))]
            clauses.append(clause)
            # Add clauses to ensure at most one tile is placed at (i, j)
            for t1 in range(len(tiles)):
                for t2 in range(t1 + 1, len(tiles)):
                    clauses.append(
                        [-var_mapping[(i, j, t1)], -var_mapping[(i, j, t2)]])
    # Additional clauses to ensure adjacent tiles match colors can be added here.
    dimacs_lines = [f"p cnf {var_counter - 1} {len(clauses)}"]
    for clause in clauses:
        dimacs_lines.append(" ".join(map(str, clause)) + " 0")
    dimacs_str = "\n".join(dimacs_lines)
    return dimacs_str, var_mapping


def call_glucose(cnf_path: Path) -> tuple[bool, list[int]]:
    """Find the Glucose executable in the project root and call it on `cnf_path`.

    Returns (is_sat, model_list) where model_list is a list of integers (literals)
    as returned by the solver (positive numbers mean variable true).
    If Glucose cannot be found or an error occurs the function returns (False, []).
    """
    # Locate glucose in the project root (same directory as this script)
    root = Path(__file__).resolve().parent
    candidates = [root / "glucose", root / "glucose.exe", root / "glucose-syrup", root / "glucose-syrup.exe"]
    gs_dir = root / "glucose-syrup"
    if gs_dir.is_dir():
        for p in gs_dir.iterdir():
            if p.is_file() and "glucose" in p.name.lower():
                candidates.append(p)

    bin_path = None
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            bin_path = c
            break

    if bin_path is None:
        print("Glucose executable not found in project root; looked for: {}".format(
            ", ".join(str(x) for x in candidates)), file=sys.stderr)
        return False, []

    try:
        # Call glucose. Many versions accept the CNF file as the single arg.
        proc = subprocess.run([str(bin_path), str(cnf_path)], capture_output=True, text=True, timeout=60)
    except Exception as e:
        print(f"Error running Glucose: {e}", file=sys.stderr)
        return False, []

    out = proc.stdout or ""
    # Parse output: look for 's SATISFIABLE' / 's UNSATISFIABLE' and 'v' lines
    sat = None
    model_literals: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("s "):
            if "UNSAT" in line.upper():
                sat = False
            elif "SAT" in line.upper():
                sat = True
        elif line.startswith("v "):
            parts = line.split()[1:]
            for p in parts:
                try:
                    lit = int(p)
                except ValueError:
                    continue
                if lit == 0:
                    continue
                model_literals.append(lit)

    # If solver printed model on stderr (some builds), also check stderr
    if not model_literals and proc.stderr:
        for line in proc.stderr.splitlines():
            line = line.strip()
            if line.startswith("v "):
                parts = line.split()[1:]
                for p in parts:
                    try:
                        lit = int(p)
                    except ValueError:
                        continue
                    if lit == 0:
                        continue
                    model_literals.append(lit)

    if sat is None:
        # fallback: if any model literals seen, assume SAT
        sat = bool(model_literals)

    return bool(sat), model_literals


def solve_instance(instance: dict, k: int):
    """Encode instance to DIMACS, call Glucose, and translate model to tiling.

    Returns (sat_bool, tiling_matrix_or_None)
    """
    dimacs_str, var_mapping = encode_instance_to_dimacs(instance, k)

    # write dimacs to a temporary file
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".cnf") as f:
            f.write(dimacs_str)
            tmp = Path(f.name)

        sat, model = call_glucose(tmp)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except Exception:
                pass

    if not sat:
        return False, None

    # Build reverse mapping from varnum -> (i,j,t_index)
    rev = {v: coords for coords, v in var_mapping.items()}

    # Initialize tiling with None
    tiling = [[None for _ in range(k)] for _ in range(k)]
    if model:
        for lit in model:
            if lit <= 0:
                continue
            coords = rev.get(lit)
            if coords is None:
                continue
            i, j, t_index = coords
            # place tile index
            if 0 <= i < k and 0 <= j < k:
                tiling[i][j] = t_index

    return True, tiling


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

    if args.print_dimacs:
        print(prepare_dimacs(raw, args.k))
        return 0

    sat, tiling = solve_instance(instance, args.k)
    if not sat:
        print("s UNSATISFIABLE")
        return 20

    # succeeded: print simple human-readable tiling
    print("s SATISFIABLE")
    colors_map = instance.get('colors', {})
    inv_colors = {v: k for k, v in colors_map.items()}
    tiles = instance.get('tiles', [])
    assert tiling is not None
    for i in range(args.k):
        row = []
        for j in range(args.k):
            t = tiling[i][j]
            if t is None:
                row.append(".")
            else:
                # represent tile by its 4 colours
                cols = tiles[t]
                names = [inv_colors.get(x, str(x)) for x in cols]
                row.append("<" + ",".join(names) + ">")
        print(" ".join(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
