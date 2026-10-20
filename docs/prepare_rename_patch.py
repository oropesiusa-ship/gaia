"""Render (do not apply) a mechanical identity-only patch for review."""
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def renamed(text):
    for old, new in (("tinygpt-", "gaia-transformer-"),
                     ("tinygpt", "gaia_transformer"),
                     ("TinyGPT", "GaiaTransformer"),
                     ("tinyGPT", "GaiaTransformer"),
                     ("TINYGPT", "GAIA_TRANSFORMER")):
        text = text.replace(old, new)
    return text


def main():
    paths = [ROOT / "gaia.py", ROOT / ".gitignore"]
    paths += [p for folder in ("gaia", "tests", "requirements", "examples")
              for p in (ROOT / folder).rglob("*")
              if p.is_file() and "__pycache__" not in p.parts]
    patch = ["*** Begin Patch"]
    for path in sorted(paths):
        old = path.read_text()
        new = renamed(old)
        relative = path.relative_to(ROOT).as_posix()
        destination = renamed(relative)
        if old == new and relative == destination:
            continue
        patch.append(f"*** Update File: {relative}")
        if relative != destination:
            patch.append(f"*** Move to: {destination}")
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), n=1))[2:]
        if diff:
            patch.extend("@@" if line.startswith("@@") else line for line in diff)
        else:
            patch.extend(["@@", "-" + old.splitlines()[0], "+" + old.splitlines()[0]])
    patch.append("*** End Patch")
    output = Path("/tmp/opencode/gaia_rename.patch")
    output.write_text("\n".join(patch) + "\n")
    print(f"Patch rendered: {output}; {len(patch)} lines")


if __name__ == "__main__":
    main()
