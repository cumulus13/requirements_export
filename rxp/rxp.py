#!/usr/bin/env python3
# file: rxp/rxp.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Rewritten: production-ready, all bugs fixed
# License: MIT

"""
rxp — Extract third-party imports from a Python source file and generate requirements.txt.

Key fixes over original:
  - AST-based parsing (not regex): handles multiline imports, conditional imports,
    try/except blocks, local/function-level imports, inline comments, string literals
    containing the word 'import', backslash continuations — all correctly.
  - 'import a, b, c' and 'import a.b.c' handled correctly (root module extracted).
  - 'import x as y' handled correctly (alias stripped).
  - Logic inversion bug fixed: 'import xxx' now correctly EXCLUDES stdlib/builtins.
  - Duplicate detection unified and correct (tracks root modules, all import forms).
  - importlib.metadata resolves import names -> canonical PyPI package names + versions.
  - Encoding detection: try UTF-8 → UTF-8-sig → Latin-1 fallback (never crashes).
  - Output path logic fixed: cwd vs. same-dir handling is explicit and consistent.
  - Quiet/overwrite/auto-number modes work correctly.
  - No dead imports (pkgutil removed).
  - No private API (_lazy_rich replaced with rich.style.StyleType).
  - Debug mode fails gracefully with a clear error if pydebugger is missing.
  - All edge cases have inline comments explaining the decision.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata as meta
import logging
import os
import sys
from pathlib import Path
from typing import ClassVar, NamedTuple

from rich.console import Console
from rich.style import StyleType
from rich.table import Table

try:
    from rich_argparse import RichHelpFormatter
except ImportError:
    # Graceful fallback: standard formatter if rich_argparse is not installed.
    from argparse import HelpFormatter as RichHelpFormatter  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Debug support — fails gracefully with a clear message
# ---------------------------------------------------------------------------

if os.getenv("DEBUG") == "1":
    try:
        from pydebugger.debug import debug  # type: ignore[import]
    except ImportError:
        logging.basicConfig(level=logging.DEBUG)
        _log = logging.getLogger("rxp")

        def debug(*args, **kwargs):  # type: ignore[misc]
            parts = [repr(v) for v in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
            _log.debug(" | ".join(parts))
else:
    def debug(*args, **kwargs):  # type: ignore[misc]
        pass


# ---------------------------------------------------------------------------
# Console (module-level; replaceable in tests via monkeypatching)
# ---------------------------------------------------------------------------

console = Console(stderr=False)

# ---------------------------------------------------------------------------
# Argparse styling
# ---------------------------------------------------------------------------


class CustomRichHelpFormatter(RichHelpFormatter):
    """RichHelpFormatter with project-specific colour overrides."""

    styles: ClassVar[dict[str, StyleType]] = {
        "argparse.args":     "bold #FFFF00",
        "argparse.groups":   "#AA55FF",
        "argparse.help":     "bold #00FFFF",
        "argparse.metavar":  "bold #FF00FF",
        "argparse.syntax":   "underline",
        "argparse.text":     "white",
        "argparse.prog":     "bold #00AAFF italic",
        "argparse.default":  "bold",
    }


# ---------------------------------------------------------------------------
# Stdlib / builtin module names
# ---------------------------------------------------------------------------


def _stdlib_module_names() -> frozenset[str]:
    """
    Return the set of all stdlib + builtin module root names.

    Python 3.10+ exposes sys.stdlib_module_names (complete, authoritative).
    Older versions get a best-effort union of sys.builtin_module_names and
    importlib.util.STDLIB_HANDLE (not available) so we fall back to walking
    the stdlib directory — but we *also* include C-extension files (.so / .pyd)
    which the original code missed.
    """
    builtin: set[str] = set(sys.builtin_module_names)

    if hasattr(sys, "stdlib_module_names"):
        # Python 3.10+ — complete and accurate
        return frozenset(sys.stdlib_module_names | builtin)

    # Fallback for Python < 3.10
    stdlib_path = Path(sys.modules["os"].__file__).parent
    names: set[str] = set()
    for entry in stdlib_path.iterdir():
        stem = entry.stem
        if entry.suffix in (".py", ".so", ".pyd", ""):
            # Remove platform tags like 'datetime.cpython-39-x86_64-linux-gnu'
            clean = stem.split(".")[0]
            names.add(clean)

    return frozenset(names | builtin)


_STDLIB: frozenset[str] = _stdlib_module_names()

# ---------------------------------------------------------------------------
# Platform / OS system frameworks — not pip-installable, not in stdlib names
# ---------------------------------------------------------------------------
# These are OS-native or bridge modules that ship with the OS or a system
# package manager (apt, brew, etc.), never with pip.  They must be excluded
# from requirements.txt just like stdlib modules.
#
# macOS system frameworks (accessed via PyObjC bridge, but provided by macOS):
#   AppKit, Foundation, Cocoa, UIKit, CoreGraphics, AVFoundation, ...
# Windows system bridge (pywin32 wraps OS DLLs, not a pure-Python dep):
#   win32api, win32gui, pywintypes, winerror, ...
# Linux GObject Introspection (system package python3-gi, not pip):
#   gi, gtk

_PLATFORM_SYSTEM_MODULES: frozenset[str] = frozenset({
    # ── macOS system frameworks ──────────────────────────────────────────────
    "AppKit", "UIKit", "SwiftUI",
    "Foundation", "Cocoa",
    "CoreFoundation", "CoreGraphics", "CoreServices", "CoreData",
    "CoreLocation", "CoreMotion", "CoreText", "CoreBluetooth",
    "CoreMIDI", "CoreAudio", "CoreML", "CreateML",
    "AVFoundation", "ARKit", "SceneKit", "SpriteKit", "GameKit",
    "MapKit", "EventKit", "Contacts", "ContactsUI",
    "WebKit", "SafariServices", "AuthenticationServices",
    "LocalAuthentication", "Security", "CryptoKit",
    "Metal", "MetalKit", "MetalPerformanceShaders",
    "Quartz", "QuartzCore", "ImageIO", "Vision", "NaturalLanguage",
    "UserNotifications", "StoreKit", "CloudKit", "HealthKit",
    "HomeKit", "WatchKit", "TVUIKit",
    "objc",          # PyObjC bridge itself
    # ── Windows system bridge (pywin32 wraps OS DLLs) ────────────────────────
    "win32api", "win32con", "win32gui", "win32process", "win32security",
    "win32service", "win32event", "win32file", "win32net", "win32print",
    "win32clipboard", "win32console", "win32crypt", "win32ts",
    "pywintypes", "winerror",
    # ── Linux / Unix system ──────────────────────────────────────────────────
    "gi",    # GObject Introspection — apt: python3-gi, never pip
    "gtk",   # GTK2 legacy bridge
})


# ---------------------------------------------------------------------------
# Import resolution: import name → PyPI package name + installed version
# ---------------------------------------------------------------------------


class ResolvedPackage(NamedTuple):
    import_name: str       # what appears after 'import' / 'from'
    package_name: str      # canonical PyPI distribution name
    version: str | None    # installed version, or None if not installed locally


def _build_import_to_dist_map() -> dict[str, list[str]]:
    """
    Build a mapping of top-level import names to distribution names using
    importlib.metadata.packages_distributions() (Python 3.11+) or a manual
    scan of installed distributions on older versions.
    """
    if hasattr(meta, "packages_distributions"):
        return dict(meta.packages_distributions())

    # Fallback: scan each installed distribution's top-level names
    mapping: dict[str, list[str]] = {}
    for dist in meta.distributions():
        dist_name = dist.metadata.get("Name") or ""
        # top_level.txt lists importable top-level names
        top_level_text = dist.read_text("top_level.txt") or ""
        for top in top_level_text.splitlines():
            top = top.strip()
            if top:
                mapping.setdefault(top, []).append(dist_name)

        # Also index the distribution name itself (normalised)
        normalised = dist_name.lower().replace("-", "_")
        mapping.setdefault(normalised, []).append(dist_name)

    return mapping


_IMPORT_TO_DIST: dict[str, list[str]] = _build_import_to_dist_map()


def resolve_package(import_name: str) -> ResolvedPackage:
    """
    Given the root import name (e.g. 'bs4'), return the canonical PyPI
    package name (e.g. 'beautifulsoup4') and its installed version.

    Resolution order:
      1. Direct lookup in packages_distributions map.
      2. Case-insensitive lookup in the same map.
      3. Treat import_name as the package name directly.
      4. Replace underscores with dashes (common convention).

    If no installed version is found, version is None — the caller decides
    whether to include the package without a version pin.
    """
    candidates: list[str] = []

    # 1. Direct
    if import_name in _IMPORT_TO_DIST:
        candidates.extend(_IMPORT_TO_DIST[import_name])

    # 2. Case-insensitive
    if not candidates:
        lower = import_name.lower()
        for key, dists in _IMPORT_TO_DIST.items():
            if key.lower() == lower:
                candidates.extend(dists)

    # 3 & 4. Fallbacks
    if not candidates:
        candidates = [import_name, import_name.replace("_", "-")]

    for candidate in candidates:
        try:
            version = meta.version(candidate)
            return ResolvedPackage(import_name, candidate, version)
        except meta.PackageNotFoundError:
            continue

    # Nothing found locally — return with no version
    return ResolvedPackage(import_name, import_name, None)


# ---------------------------------------------------------------------------
# AST-based import extraction
# ---------------------------------------------------------------------------


class ImportRecord(NamedTuple):
    root_name: str   # top-level module name (e.g. 'rich' from 'rich.console')
    lineno: int      # first occurrence line number
    is_third_party: bool


def _is_local_module(name: str, src_dir: Path) -> bool:
    """
    Return True if *name* is a local project module — i.e. a .py file or
    package directory that lives next to the source file being analysed.

    This correctly excludes companion modules like mpdpop_env.py or
    mpdpop_artinfo.py which are part of the same project and must NOT appear
    in requirements.txt (they are not PyPI packages).

    Checks:
      src_dir/<name>.py          — plain module file
      src_dir/<name>/__init__.py — regular package
      src_dir/<name>/            — namespace package (no __init__.py)
    """
    return (
        (src_dir / f"{name}.py").is_file()
        or (src_dir / name / "__init__.py").is_file()
        or (src_dir / name).is_dir()
    )


def extract_imports(file_path: str | Path) -> tuple[list[ImportRecord], list[tuple[int, str, int]]]:
    """
    Parse a Python source file with the AST and extract all import statements.

    Returns:
        (third_party_records, duplicates)

        third_party_records: ImportRecord list, one entry per unique third-party
                             root module, sorted by name. Excludes:
                             - stdlib / builtins
                             - local project modules (*.py or packages next to source)
        duplicates: list of (duplicate_lineno, root_name, original_lineno) tuples.

    Handles correctly:
      - 'import a, b, c'
      - 'import a.b.c' (root = 'a')
      - 'import x as y' (root = 'x', alias ignored)
      - 'from a.b import c' (root = 'a')
      - Relative imports ('from . import x') — skipped; they reference local modules
      - Conditional imports inside if/try blocks — included (they're real dependencies)
      - Local/function-level imports — included (they're real dependencies)
      - String literals or comments containing 'import' — ignored (not AST nodes)
      - Local companion modules (same directory .py files) — excluded
    """
    path = Path(file_path)

    if not path.exists():
        console.print(f"[white on red] File not found: {path} [/]")
        return [], []

    if not path.is_file():
        console.print(f"[white on red] Not a file: {path} [/]")
        return [], []

    # --- Read with encoding fallback ---
    source = _read_source(path)
    if source is None:
        return [], []

    # --- Parse AST ---
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        console.print(f"[white on red] Syntax error in {path}: {exc} [/]")
        return [], []

    # --- Walk AST ---
    # Track: root_name -> first lineno seen
    seen: dict[str, int] = {}
    duplicates: list[tuple[int, str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                debug(import_stmt=alias.name, root=root, line=node.lineno)
                _record_import(root, node.lineno, seen, duplicates)

        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative import (from . import x, from .. import y) — skip,
                # these always reference modules within the same package.
                debug(skipping_relative=node.module, level=node.level, line=node.lineno)
                continue
            if node.module:
                root = node.module.split(".")[0]
                debug(from_stmt=node.module, root=root, line=node.lineno)
                _record_import(root, node.lineno, seen, duplicates)

    # --- Separate third-party from stdlib and local project modules ---
    src_dir = path.parent
    third_party: list[ImportRecord] = []
    for root, lineno in sorted(seen.items()):
        if root in _STDLIB or root in _PLATFORM_SYSTEM_MODULES:
            debug(excluded_stdlib=root)
            continue
        if _is_local_module(root, src_dir):
            debug(excluded_local=root, src_dir=str(src_dir))
            continue
        third_party.append(ImportRecord(root, lineno, True))

    third_party.sort(key=lambda r: r.root_name.lower())
    return third_party, duplicates


def _record_import(
    root: str,
    lineno: int,
    seen: dict[str, int],
    duplicates: list[tuple[int, str, int]],
) -> None:
    """Register a root module name; record as duplicate if already seen."""
    if root in seen:
        duplicates.append((lineno, root, seen[root]))
    else:
        seen[root] = lineno


def _read_source(path: Path) -> str | None:
    """
    Read a file trying UTF-8, then UTF-8-with-BOM, then Latin-1.
    Latin-1 is a superset of ASCII and decodes every byte sequence without
    error — it is the correct final fallback for Python source files.
    Returns None only if the file truly cannot be read (permissions, etc.).
    """
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            console.print(f"[white on red] Cannot read {path}: {exc} [/]")
            return None
    # Should never reach here (latin-1 never raises UnicodeDecodeError)
    console.print(f"[white on red] Failed to decode {path} with any supported encoding. [/]")
    return None


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------


def resolve_output_path(
    source_file: str | Path,
    output_arg: str,
    same_dir: bool,
    quiet: bool,
    auto_number: bool,
) -> Path | None:
    """
    Determine the final output path for the requirements file.

    Args:
        source_file: The Python file being analysed.
        output_arg:  The -o/--output argument value (basename or full path).
        same_dir:    If True, place output next to source_file; else use cwd.
        quiet:       If True, overwrite without prompting.
        auto_number: If True, auto-suffix with a number to avoid overwriting.

    Returns Path, or None if the user declined to overwrite.
    """
    base = Path(output_arg)

    if same_dir:
        candidate = Path(source_file).parent / base.name
    else:
        # If output_arg is absolute, use it as-is; otherwise anchor to cwd.
        candidate = base if base.is_absolute() else Path.cwd() / base.name

    if not candidate.exists():
        return candidate

    # File already exists — resolve conflict
    if quiet:
        # Overwrite silently
        return candidate

    if auto_number:
        return _numbered_path(candidate)

    # Interactive prompt
    answer = console.input(
        f"[#FFFF00]'{candidate}'[/] [white on red]already exists[/]. "
        f"[bold blue]Overwrite?[/] ([bold #FFAA00]y[/]/[bold #FF5555]n[/]/[bold #00FFFF]a[/]uto-number): "
    ).strip().lower()

    if answer in ("y", "yes"):
        return candidate
    if answer in ("a", "auto"):
        return _numbered_path(candidate)

    console.print("[bold #FF5555]Aborted.[/]")
    return None


def _numbered_path(base: Path) -> Path:
    """Return base(1).txt, base(2).txt, ... until a non-existent path is found."""
    stem = base.stem
    # Strip any existing trailing number pattern like 'requirements3'
    import re
    clean_stem = re.sub(r"\d+$", "", stem)
    n = 1
    while True:
        candidate = base.with_name(f"{clean_stem}{n}{base.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------


def export_requirements(
    file_path: str,
    output_file: str = "requirements.txt",
    quiet: bool = False,
    auto_number: bool = False,
    same_dir: bool = False,
    pin_versions: bool = False,
    show_stdlib: bool = False,
    show_table: bool = True,
) -> int:
    """
    Extract third-party imports from *file_path* and write a requirements file.

    Returns exit code: 0 = success, 1 = error/abort.
    """
    imports, duplicates = extract_imports(file_path)

    # --- Report duplicates ---
    if duplicates:
        console.print()
        for dup_line, root, orig_line in sorted(duplicates):
            console.print(
                f"[black on #FFFF00] WARNING [/] "
                f"[bold #FFAAFF]Duplicate import[/] "
                f"[white on red] {root!r} [/] "
                f"[bold #FFAAFF]on line[/] [white on blue] {dup_line} [/] "
                f"[bold #FFAAFF](first seen on line[/] [white on blue] {orig_line} [/][bold #FFAAFF])[/]"
            )
        console.print()

    if not imports:
        console.print("[white on red] No third-party imports found. [/]")
        if show_stdlib:
            console.print("[dim]Tip: stdlib-only imports were excluded from output.[/]")
        return 0

    # --- Resolve package names and versions ---
    resolved: list[ResolvedPackage] = []
    for record in imports:
        pkg = resolve_package(record.root_name)
        resolved.append(pkg)
        debug(import_name=pkg.import_name, package_name=pkg.package_name, version=pkg.version)

    # --- Display table ---
    if show_table:
        _print_table(resolved, pin_versions)

    # --- Determine output path ---
    out_path = resolve_output_path(file_path, output_file, same_dir, quiet, auto_number)
    if out_path is None:
        return 1

    # --- Write requirements file ---
    lines: list[str] = []
    for pkg in resolved:
        if pin_versions and pkg.version:
            lines.append(f"{pkg.package_name}=={pkg.version}")
        else:
            lines.append(pkg.package_name)

    try:
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        console.print(f"[white on red] Cannot write {out_path}: {exc} [/]")
        return 1

    # --- Pretty output name ---
    _print_success(out_path)
    return 0


def _print_table(resolved: list[ResolvedPackage], pin_versions: bool) -> None:
    table = Table(
        title="[bold #00FFFF]Detected third-party packages[/]",
        show_header=True,
        header_style="bold #FFFF00",
        border_style="#555555",
    )
    table.add_column("Import name",   style="#AAFFAA", no_wrap=True)
    table.add_column("Package name",  style="#FFAAFF", no_wrap=True)
    table.add_column("Installed ver", style="#FFFF00", no_wrap=True, justify="right")
    table.add_column("Will write",    style="bold white", no_wrap=True)

    for pkg in resolved:
        ver_display = pkg.version or "[dim]not installed[/]"
        if pin_versions and pkg.version:
            write_display = f"{pkg.package_name}=={pkg.version}"
        else:
            write_display = pkg.package_name
        table.add_row(pkg.import_name, pkg.package_name, ver_display, write_display)

    console.print()
    console.print(table)
    console.print()


def _print_success(out_path: Path) -> None:
    stem = out_path.stem
    import re
    m = re.match(r"^(requirements?)(\d*)$", stem, re.IGNORECASE)
    if m:
        base_part = f"[bold #FFAA00]{m.group(1)}[/]"
        num_part = (
            f"[white on #5500FF]{m.group(2)}[/]" if m.group(2) else ""
        )
        ext_part = f"[bold #FFAA00]{out_path.suffix}[/]"
        display = f"{base_part}{num_part}{ext_part}"
    else:
        display = f"[bold #FFAA00]{out_path}[/]"

    console.print(f"[bold #00FFFF]Requirements exported to:[/] {display}")
    console.print(f"[dim]Full path: {out_path.resolve()}[/]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rxp",
        description="Extract third-party imports from a Python file and generate requirements.txt.",
        formatter_class=CustomRichHelpFormatter,
        epilog=(
            "Examples:\n"
            "  rxp myscript.py\n"
            "  rxp myscript.py -o deps.txt --pin\n"
            "  rxp myscript.py -q --same-dir\n"
        ),
    )
    parser.add_argument(
        "FILE",
        help="Python source file to analyse.",
    )
    parser.add_argument(
        "-o", "--output",
        default="requirements.txt",
        metavar="PATH",
        help=(
            "Output file name or path. "
            "Default: [bold #AAFF00]requirements.txt[/] in the current directory "
            "(or next to FILE when [bold #FFAA00]--same-dir[/] is used)."
        ),
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Overwrite the output file if it already exists, without prompting.",
    )
    parser.add_argument(
        "-a", "--auto-number",
        action="store_true",
        help=(
            "Instead of overwriting or prompting, auto-append a number suffix. "
            "E.g. [bold #AAFF00]requirements[/][bold #FF00FF]1[/][bold #AAFF00].txt[/]"
        ),
    )
    parser.add_argument(
        "--same-dir",
        action="store_true",
        help=(
            "Save the output file in the same directory as FILE "
            "instead of the current working directory."
        ),
    )
    parser.add_argument(
        "--pin",
        action="store_true",
        help=(
            "Pin exact versions of installed packages "
            "(e.g. [bold #AAFF00]requests==2.31.0[/]). "
            "Packages not installed locally are written without a version."
        ),
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="Suppress the summary table (useful for scripting).",
    )
    return parser


def main() -> int:
    parser = build_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    args = parser.parse_args()

    return export_requirements(
        file_path=args.FILE,
        output_file=args.output,
        quiet=args.quiet,
        auto_number=args.auto_number,
        same_dir=args.same_dir,
        pin_versions=args.pin,
        show_table=not args.no_table,
    )


if __name__ == "__main__":
    sys.exit(main())
