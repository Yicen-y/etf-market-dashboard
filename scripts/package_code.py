"""Create a code-only deployment archive without runtime market data."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .config import ROOT

FILES = ("server.py", "requirements.txt", "README.md")
DIRECTORIES = ("scripts", "web")


def package_code(output: Path, root: Path = ROOT) -> list[str]:
    output = output.resolve()
    if root.resolve() in output.parents:
        raise ValueError("write the deployment archive outside the source tree")
    names = []
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in FILES:
            path = root / name
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(path)
            archive.write(path, name)
            names.append(name)
        for directory in DIRECTORIES:
            for path in sorted((root / directory).rglob("*")):
                if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                    continue
                name = path.relative_to(root).as_posix()
                archive.write(path, name)
                names.append(name)
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    names = package_code(args.output)
    print(f"created {args.output} with {len(names)} code files; no data/ files")


if __name__ == "__main__":
    main()
