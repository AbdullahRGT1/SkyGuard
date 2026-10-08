import runpy
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).resolve().parent / "operator" / "app.py"
    runpy.run_path(str(app_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

