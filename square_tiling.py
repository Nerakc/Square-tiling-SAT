#!/usr/bin/env python3

from pathlib import Path
import argparse
import sys
import subprocess
import re


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
    """Encode the instance into a DIMACS-like CNF text string.

    Variables are named using zero-padded indices for row, column and tile
    (each using 1-based values). The returned string is a text CNF where
    variable tokens are these padded names (follow-up tools may translate
    them to numeric DIMACS IDs if needed).
    """

    rows = int(k)
    tiles = instance.get("tiles", [])
    num_tiles = max(0, len(tiles))

    def digits(n: int) -> int:
        if n <= 0:
            return 1
        return len(str(n))

    w_i = digits(rows)
    w_j = digits(rows)
    w_t = digits(num_tiles)

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
    # because of our usage of named variables the number is actually the largest name
    num_vars = 0
    clauses: list[str] = []

    # on each position (i,j), exactly one tile t is placed
    for i in range(rows):
        for j in range(rows):
            at_least_one = [var_name(i, j, t) for t in range(num_tiles)]
            if at_least_one:
                clauses.append(" ".join(at_least_one) + " 0")
            num_vars = max(num_vars, int(at_least_one[-1]))
            for t1 in range(num_tiles):
                for t2 in range(t1 + 1, num_tiles):
                    vname1 = var_name(i, j, t1)
                    vname2 = var_name(i, j, t2)
                    clauses.append(f"-{vname1} -{vname2} 0")
                    num_vars = max(num_vars, int(vname1), int(vname2))

    # adjacency constraints: enforce matching edge colours between neighbours
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
                            num_vars = max(num_vars, int(vname1), int(vname2))
                # bottom neighbor
                if i + 1 < rows:
                    for t2 in range(num_tiles):
                        tile2 = tiles[t2]
                        if tile1[2] != tile2[0]:
                            vname1 = var_name(i, j, t1)
                            vname2 = var_name(i + 1, j, t2)
                            clauses.append(f"-{vname1} -{vname2} 0")
                            num_vars = max(num_vars, int(vname1), int(vname2))

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


def parse_solver_stats(output: str) -> dict:
    """Parse common solver statistics from Glucose/MiniSat-like output.

    Returns a dict with any of the keys: 'restarts', 'conflicts', 'decisions',
    'propagations', 'conflict_literals', 'memory_mb', 'cpu_seconds'. Values
    are ints for counts and floats for memory/time when available.
    """
    stats: dict = {}

    def to_int(s: str) -> int:
        return int(s.replace(",", ""))

    # Common patterns
    patterns = [
        (r"restarts?\s*[:=]\s*(\d+)", 'restarts', int),
        (r"conflicts?\s*[:=]\s*([\d,]+)", 'conflicts', to_int),
        (r"decisions?\s*[:=]\s*([\d,]+)", 'decisions', to_int),
        (r"propagations?\s*[:=]\s*([\d,]+)", 'propagations', to_int),
        (r"conflict literals?\s*[:=]\s*([\d,]+)", 'conflict_literals', to_int),
        (r"Memory used\s*[:=]\s*([\d.]+)\s*MB", 'memory_mb', float),
        (r"Memory\s*[:=]\s*([\d.]+)\s*MB", 'memory_mb', float),
        (r"CPU time\s*[:=]\s*([\d.]+)\s*s", 'cpu_seconds', float),
        (r"CPU time\s*[:=]\s*([\d.]+)\s*sec", 'cpu_seconds', float),
        (r"Time\s*[:=]\s*([\d.]+)\s*s", 'cpu_seconds', float),
        (r"solving time\s*[:=]\s*([\d.]+)\s*s", 'cpu_seconds', float),
    ]

    for line in output.splitlines():
        l = line.strip()
        for pat, key, caster in patterns:
            m = re.search(pat, l, flags=re.IGNORECASE)
            if m:
                try:
                    stats[key] = caster(m.group(1))
                except Exception:
                    # ignore casting errors
                    pass

    return stats


def print_solver_stats(stats: dict) -> None:
    if not stats:
        print("Solver statistics: (none found)")
        return
    print("Solver statistics:")
    order = [
        ('restarts', 'Restarts'),
        ('conflicts', 'Conflicts'),
        ('decisions', 'Decisions'),
        ('propagations', 'Propagations'),
        ('conflict_literals', 'Conflict literals'),
        ('memory_mb', 'Memory (MB)'),
        ('cpu_seconds', 'CPU time (s)'),
    ]
    for key, label in order:
        if key in stats:
            print(f"- {label}: {stats[key]}")


def solve_instance(v_text: str, k: int, tiles: int) -> list[list[int]]:
    def digits(n: int) -> int:
        if n <= 0:
            return 1
        return len(str(n))

    w_t = digits(tiles)
    w_i = digits(k)
    w_j = digits(k)
    model = [[0 for _ in range(k)] for _ in range(k)]

    for num in v_text.split():
        val = int(num)
        if val > 0:
            s = str(val).zfill(w_i + w_j + w_t)
            i = int(s[0:w_i]) - 1
            j = int(s[w_i:w_i + w_j]) - 1
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
    p.add_argument("--solver-stats", action="store_true",
                   help="print solver statistics parsed from glucose output")
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

    project_root = Path(__file__).resolve().parent
    default_cnf = project_root / "output.cnf"
    try:
        default_cnf.write_text(dimacs, encoding='utf-8')
    except Exception as e:
        print(f"Failed to write DIMACS to {default_cnf}: {e}", file=sys.stderr)
        return 2

    if args.print_dimacs:
        print(dimacs)

    # Call the external solver and capture its output.
    num_tiles = len(instance.get("tiles", []))
    is_sat, model, output = call_glucose(args.k, num_tiles)

    # If requested, parse and print solver statistics from the solver output.
    if getattr(args, 'solver_stats', False):
        stats = parse_solver_stats(output)
        print_solver_stats(stats)

    if not is_sat:
        print("s UNSATISFIABLE")
        return 20

    # Solver reports SAT. Decoded model is printed below.
    print("s SATISFIABLE")
    print("Model:")
    for row in model:
        print(" ".join(str(t) for t in row))
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
