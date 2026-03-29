"""
Terminal UI helpers — colors, progress, prompts. Zero external dependencies.
"""
import sys
import time

# ANSI colors
R  = "\033[0m"
B  = "\033[1m"
DIM= "\033[2m"
CYN= "\033[36m"
GRN= "\033[32m"
YLW= "\033[33m"
RED= "\033[31m"
BLU= "\033[34m"
MGT= "\033[35m"
WHT= "\033[97m"

def _c(color, text):
    """Wrap text in an ANSI color code and reset it afterwards."""
    return f"{color}{text}{R}"


def header(text):
    """Print a prominent full-width banner, used at the start of every command."""
    width = 60
    print()
    print(_c(BLU+B, "─" * width))
    print(_c(BLU+B, f"  {text}"))
    print(_c(BLU+B, "─" * width))


def section(text):
    """Print a section heading with a cyan arrow, used to group related output."""
    print(f"\n{_c(CYN+B, '▸')} {_c(B, text)}")


def ok(text):
    """Print a green success line (✓ prefix)."""
    print(f"  {_c(GRN, '✓')} {text}")


def warn(text):
    """Print a yellow warning line (⚠ prefix)."""
    print(f"  {_c(YLW, '⚠')} {text}")


def error(text):
    """Print a red error line (✗ prefix)."""
    print(f"  {_c(RED, '✗')} {text}")


def info(text):
    """Print a dimmed informational line (· prefix)."""
    print(f"  {_c(DIM, '·')} {text}")


def step(n, total, text):
    """Print a progress step line '[n/total] resource_name' without a newline.

    Leaves the cursor at the end of the line so done()/fail() can append inline.
    """
    print(f"  {_c(DIM, f'[{n}/{total}]')} {text:<45}", end=" ", flush=True)


def done(count):
    """Print the item count at the end of a step() line (green)."""
    print(_c(GRN, f"{count} item(s)"))


def skip(reason):
    """Print a skip notice at the end of a step() line (yellow)."""
    print(_c(YLW, f"skipped ({reason})"))


def fail(reason):
    """Print an error notice at the end of a step() line (red, truncated to 60 chars)."""
    print(_c(RED, f"ERROR: {reason[:60]}"))


def ask(prompt, default=None):
    """Prompt the user for text input, showing the default value in brackets.

    Returns the default if the user presses Enter without typing anything.
    """
    suffix = f" [{_c(DIM, default)}]" if default else ""
    val = input(f"\n  {_c(WHT+B, '?')} {prompt}{suffix}: ").strip()
    return val if val else default


def ask_password(prompt):
    """Prompt for a password using getpass (input is not echoed to the terminal)."""
    import getpass
    return getpass.getpass(f"\n  {_c(WHT+B, '?')} {prompt}: ")


def confirm(prompt, default=True):
    """Ask a yes/no question and return a bool.

    The default answer (used when the user just presses Enter) is shown
    as the uppercase letter in the Y/n or y/N hint.
    """
    yn = "Y/n" if default else "y/N"
    val = input(f"\n  {_c(YLW+B, '?')} {prompt} ({yn}): ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def progress_bar(current, total, width=30):
    """Print an inline progress bar that overwrites the current line.

    Uses block characters (█ filled, ░ empty). Suitable for loops —
    call repeatedly with increasing current values, then print a newline when done.
    """
    filled = int(width * current / total) if total else 0
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total) if total else 0
    print(f"\r  {_c(BLU, bar)} {pct:3d}% ({current}/{total})", end="", flush=True)


def summary_table(rows: list[tuple]):
    """Print a compact aligned key/value table with per-row colors.

    Each row is a tuple of (label: str, value: any, color: str).
    Labels are padded to the width of the longest label in the list.
    """
    max_label = max(len(r[0]) for r in rows)
    for label, value, color in rows:
        print(f"  {_c(DIM, label.ljust(max_label))}  {_c(color, str(value))}")
