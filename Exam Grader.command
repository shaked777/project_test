#!/bin/bash
# Double-click this file in Finder to launch the Automated Exam Grader window.
cd "$(dirname "$0")" || exit 1
exec python3 app.py
