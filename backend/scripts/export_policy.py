"""Load and validate policy JSON, then export the normalized configuration."""

import argparse
import json
from pathlib import Path

from backend.loader.policy_loader import load_policy


def export_policy(source: str | Path, output: str | Path, *, overwrite: bool = False) -> Path:
    """Export schema-validated policy; monetary limits remain decimal strings."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
        raise ValueError("Input and output must be different files")
    policy = load_policy(source)
    serialized = json.dumps(policy, indent=2, ensure_ascii=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8") as target:
        target.write(serialized)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/policy/policy.json"))
    parser.add_argument("--output", type=Path, default=Path("data/out/policy.json"))
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()
    try:
        output = export_policy(args.input, args.output, overwrite=args.force)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Exported validated policy to {output}")


if __name__ == "__main__":
    main()
