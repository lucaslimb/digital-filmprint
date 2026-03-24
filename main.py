"""
main.py
-------
CLI entry point for digital-filmprint.

Usage:
    python main.py                       # auto-detect the .zip in data/
    python main.py path/to/export.zip    # explicit path
"""

from src.report_builder import main

if __name__ == "__main__":
    main()
