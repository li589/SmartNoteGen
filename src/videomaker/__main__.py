"""包执行入口：允许 python -m videomaker 运行 CLI。"""

from videomaker.cli import app

if __name__ == "__main__":
    app()
