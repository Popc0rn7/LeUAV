"""LeUAV development framework."""
import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "resources":
        from leuav.resources import main as command
        raise SystemExit(command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "adrl":
        from leuav.adrl.cli import main as command
        raise SystemExit(command(sys.argv[2:]))
    print("用法: leuav resources --help | leuav adrl --help")
    raise SystemExit(0 if len(sys.argv) == 1 else 2)
