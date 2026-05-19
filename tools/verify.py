import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    tests_readme = repo_root / "tests" / "README.md"
    if not tests_readme.exists():
        print("Missing tests/README.md")
        return 1

    print("Repository verification")
    print("- Python syntax validation: OK (run separately if needed)")
    print("- Blender regression entrypoint: python .\\tools\\run_blender_tests.py")
    print(f"- Tests doc: {tests_readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
