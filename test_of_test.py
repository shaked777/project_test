#!/usr/bin/env python3
"""
Command line entry point for the Automated Exam Grader.

The grading logic lives in grader_core.py, which the desktop app (app.py)
shares. This script only handles argument parsing and terminal output.

Usage: python3 test_of_test.py [exam|homework] [path/to/file.pdf]
"""

import sys

from grader_core import GRADING_MODES, GradingError, grade_pdf


def select_grading_mode(argv):
    """
    Resolves which grading mode to run: 'exam' or 'homework'.
    Reads the mode from the command line if provided, otherwise asks interactively.
    """
    if len(argv) > 1:
        requested = argv[1].strip().lower()
        if requested in GRADING_MODES:
            print(f"[Info] Grading mode selected from arguments: {GRADING_MODES[requested]['label']}")
            return requested
        raise ValueError(f"Unknown grading mode '{argv[1]}'. Valid options: {', '.join(GRADING_MODES)}.")

    print("\nWhich submission would you like to grade?")
    print("  1) Exam")
    print("  2) Homework")

    aliases = {"1": "exam", "exam": "exam", "e": "exam",
               "2": "homework", "homework": "homework", "hw": "homework", "h": "homework"}

    while True:
        choice = input("Enter your choice [1/2]: ").strip().lower()
        if choice in aliases:
            mode = aliases[choice]
            print(f"[Info] Grading mode selected: {GRADING_MODES[mode]['label']}")
            return mode
        print("[Error] Invalid choice. Please enter 1 for Exam or 2 for Homework.")


def main(argv):
    mode = select_grading_mode(argv)
    mode_config = GRADING_MODES[mode]

    pdf_file_path = argv[2] if len(argv) > 2 else mode_config["default_pdf"]

    print(f"\nStarting the automated LOCAL grading process ({mode_config['label']})...")
    print(f"[Info] Target document: {pdf_file_path}\n")

    result = grade_pdf(
        pdf_file_path,
        mode,
        dpi=72,
        on_progress=lambda message: print(f"[Info] {message}"),
    )

    print(f"\n--- Local Grading Result ({mode_config['label']}) ---\n")
    print(result)
    print("\n----------------------------\n")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except (GradingError, ValueError) as e:
        print(f"[Error] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[Info] Cancelled.")
        sys.exit(130)
