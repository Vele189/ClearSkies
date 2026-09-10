#!/usr/bin/env python3
"""Keep the secret register honest, and preflight a job's environment.

`docs/secrets.md` carries a table of every variable this project reads. A table
in a document is a wish; this script is what makes it binding. It is the single
source of truth for two things that otherwise drift apart immediately: what
`.env.example` offers, and what the workflows consume.

Two subcommands:

    audit               the register, .env.example and the workflows agree
    check --role etl    the variables that role needs are actually present

`audit` runs in CI and in `make check`. `check` runs at the top of the nightly
job, before it touches the network or the database, so a missing credential is
one clear line at the start rather than an adapter traceback twenty minutes in.

Neither subcommand ever prints a value. `check` reports presence only, because
its output lands in a public Actions log.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs/secrets.md"
ENV_EXAMPLE = ROOT / ".env.example"
WORKFLOWS = ROOT / ".github/workflows"

KINDS = {"secret", "config", "public"}
PLACES = {"local", "actions", "railway"}
NEEDS = {"required", "optional", "—"}

# `| `NAME` | kind | places | etl | prose |`
ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|")
ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
SECRET_REF = re.compile(r"secrets\.([A-Z][A-Z0-9_]*)")


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str
    places: frozenset[str]
    etl: str

    @property
    def in_actions(self) -> bool:
        return "actions" in self.places


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def fail(problems: list[str], message: str) -> None:
    problems.append(message)


def is_local_value(value: str) -> bool:
    """Whether an example value is self-evidently a local-machine default.

    `DATABASE_URL` is a secret in every deployed environment and a throwaway in
    this one. Committing the localhost form is what lets `cp .env.example .env`
    be the whole of local setup, so the rule is about where a value points, not
    about which variable carries it.
    """
    return any(host in value for host in LOCAL_HOSTS)


def load_register() -> dict[str, Entry]:
    """Parse the Register section only.

    Scoping to one section matters: the page carries a second table listing
    where to obtain the adapter keys, whose rows look identical to a parser
    that is only matching on a backticked variable name.
    """
    entries: dict[str, Entry] = {}
    in_section = False
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Register"
            continue
        if not in_section:
            continue
        match = ROW.match(line)
        if match is None:
            continue
        name, kind, places, etl = (g.strip() for g in match.groups())
        listed = (p.strip() for p in places.split(","))
        entries[name] = Entry(
            name=name,
            kind=kind,
            places=frozenset(p for p in listed if p and p != "—"),
            etl=etl,
        )
    return entries


def load_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ASSIGNMENT.match(stripped)
        if match is not None:
            values[match.group(1)] = match.group(2).strip()
    return values


def load_workflow_refs() -> dict[str, set[str]]:
    """Every `secrets.NAME` a workflow reads, keyed by variable name."""
    refs: dict[str, set[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name in SECRET_REF.findall(path.read_text(encoding="utf-8")):
            refs.setdefault(name, set()).add(path.name)
    return refs


def audit() -> int:
    register = load_register()
    example = load_env_example()
    refs = load_workflow_refs()
    problems: list[str] = []

    if not register:
        fail(problems, f"{REGISTER.relative_to(ROOT)}: no Register table rows parsed")

    for entry in register.values():
        if entry.kind not in KINDS:
            fail(problems, f"{entry.name}: kind {entry.kind!r} is not one of {sorted(KINDS)}")
        unknown = entry.places - PLACES
        if unknown:
            fail(problems, f"{entry.name}: unknown location(s) {sorted(unknown)}")
        if entry.etl not in NEEDS:
            fail(
                problems,
                f"{entry.name}: nightly ETL column {entry.etl!r} is not one of {sorted(NEEDS)}",
            )
        if entry.etl in {"required", "optional"} and not entry.in_actions:
            fail(
                problems,
                f"{entry.name}: the nightly job needs it but 'actions' is not in its Set in column",
            )

    for name in sorted(set(example) - set(register)):
        fail(problems, f"{name}: in .env.example but not in the register")
    for name in sorted(set(register) - set(example)):
        fail(problems, f"{name}: in the register but not in .env.example")

    # The one file where a real credential could plausibly be pasted by
    # accident is the example that invites you to fill it in. A secret may
    # still carry a default there if it unambiguously points at the local
    # machine, which is what makes `cp .env.example .env` enough to start.
    for entry in register.values():
        value = example.get(entry.name, "")
        if entry.kind == "secret" and value and not is_local_value(value):
            fail(
                problems,
                f"{entry.name}: .env.example must leave a secret empty unless its default points "
                f"at localhost, and this one does neither",
            )

    for name, files in sorted(refs.items()):
        where = ", ".join(sorted(files))
        if name not in register:
            fail(problems, f"{name}: read by {where} but not in the register")
        elif not register[name].in_actions:
            fail(problems, f"{name}: read by {where} but its Set in column omits 'actions'")
    for entry in register.values():
        if entry.in_actions and entry.name not in refs:
            fail(problems, f"{entry.name}: register says 'actions' but no workflow reads it")

    if problems:
        print("The secret register is out of step:\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"\nReconcile docs/secrets.md, .env.example and .github/workflows/."
            f"\n{len(problems)} problem(s).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Register consistent: {len(register)} variables, "
        f"{sum(1 for e in register.values() if e.kind == 'secret')} secret, "
        f"{len(refs)} read by workflows."
    )
    return 0


def check(role: str, warn_only: bool = False) -> int:
    """Report presence for one role's variables. Never prints a value."""
    if role != "etl":
        print(f"unknown role {role!r}; the only role defined is 'etl'", file=sys.stderr)
        return 2

    register = load_register()
    wanted = sorted(
        (e for e in register.values() if e.etl in {"required", "optional"}),
        key=lambda e: (e.etl != "required", e.name),
    )
    if not wanted:
        print(f"no variables registered for role {role!r}", file=sys.stderr)
        return 1

    missing_required: list[str] = []
    missing_optional: list[str] = []
    for entry in wanted:
        present = bool(os.environ.get(entry.name, "").strip())
        if present:
            status = "present"
        else:
            status = "MISSING"
            (missing_required if entry.etl == "required" else missing_optional).append(entry.name)
        print(f"  {entry.name:<20} {entry.etl:<9} {status}")

    if missing_optional:
        # Degrading is the same posture the methodology takes toward a source
        # that has gone away: carry on, and let confidence record the gap.
        print(
            "\nDegraded: "
            + ", ".join(missing_optional)
            + ". Those adapters are skipped and the run continues."
        )
    if missing_required:
        stream = sys.stdout if warn_only else sys.stderr
        print(
            "\nCannot run without: " + ", ".join(missing_required) + "."
            "\nSet them as repository secrets; see docs/secrets.md.",
            file=stream,
        )
        if not warn_only:
            return 1
        print("Reporting only: nothing in Phase 0 reads them yet.", file=stream)
        return 0

    print("\nRequired configuration present.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit", help="the register, .env.example and the workflows agree")
    checker = sub.add_parser("check", help="the variables a role needs are present")
    checker.add_argument("--role", required=True, help="the only role defined is 'etl'")
    checker.add_argument(
        "--warn-only",
        action="store_true",
        help="report a missing required variable without failing (Phase 0, when nothing reads it)",
    )

    args = parser.parse_args()
    if args.command == "audit":
        return audit()
    return check(args.role, warn_only=args.warn_only)


if __name__ == "__main__":
    raise SystemExit(main())
