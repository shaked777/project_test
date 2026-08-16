#!/usr/bin/env python3
"""
Automated Exam Grader - desktop application.

A native desktop window (Tkinter, part of the Python standard library) around
the grading pipeline in grader_core.py. Pick a submission PDF, choose whether
it is an exam or homework, and the local Ollama model grades it.

Run with:  python3 app.py
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import grader_core
from grader_core import GRADING_MODES, GradingError

APP_TITLE = "Automated Exam Grader"
DPI_CHOICES = (72, 100, 150, 200)


class GraderApp(ttk.Frame):
    """Main application window."""

    def __init__(self, master):
        super().__init__(master, padding=16)
        self.grid(row=0, column=0, sticky="nsew")

        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # Messages published by the worker thread, drained on the UI thread.
        self._events = queue.Queue()
        self._worker = None
        self._started_at = None
        self._streaming = False
        self._last_status = "Ready."
        self._report = ""

        self.mode_var = tk.StringVar(value="exam")
        self.pdf_var = tk.StringVar(value=self._default_pdf("exam"))
        self.dpi_var = tk.IntVar(value=72)
        self.status_var = tk.StringVar(value="Ready.")

        self._build_menu(master)
        self._build_submission_section()
        self._build_options_section()
        self._build_action_section()
        self._build_output_section()
        self._build_status_bar()

        self.after(100, self._drain_events)

    # ---------------------------------------------------------------- layout

    def _build_menu(self, master):
        menubar = tk.Menu(master)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open PDF...", accelerator="Cmd+O", command=self.browse_pdf)
        file_menu.add_command(label="Save Report...", accelerator="Cmd+S", command=self.save_report)
        file_menu.add_separator()
        file_menu.add_command(label="Clear Output", command=self.clear_output)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=f"About {APP_TITLE}", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        master.config(menu=menubar)
        master.bind("<Command-o>", lambda _event: self.browse_pdf())
        master.bind("<Command-s>", lambda _event: self.save_report())
        master.bind("<Control-o>", lambda _event: self.browse_pdf())
        master.bind("<Control-s>", lambda _event: self.save_report())

    def _build_submission_section(self):
        box = ttk.LabelFrame(self, text="Submission", padding=12)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="PDF file:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        entry = ttk.Entry(box, textvariable=self.pdf_var)
        entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(box, text="Browse...", command=self.browse_pdf).grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )

    def _build_options_section(self):
        box = ttk.LabelFrame(self, text="Grading options", padding=12)
        box.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(3, weight=1)

        ttk.Label(box, text="Submission type:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        for column, (mode, config) in enumerate(GRADING_MODES.items(), start=1):
            ttk.Radiobutton(
                box,
                text=config["label"],
                value=mode,
                variable=self.mode_var,
                command=self._on_mode_changed,
            ).grid(row=0, column=column, sticky="w", padx=(0, 12))

        ttk.Label(box, text="Page quality (DPI):").grid(
            row=1, column=0, sticky="w", pady=(10, 0), padx=(0, 8)
        )
        dpi_box = ttk.Combobox(
            box,
            textvariable=self.dpi_var,
            values=DPI_CHOICES,
            state="readonly",
            width=6,
        )
        dpi_box.grid(row=1, column=1, sticky="w", pady=(10, 0))
        ttk.Label(box, text="Higher DPI reads handwriting better but is slower.").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(10, 0)
        )

    def _build_action_section(self):
        box = ttk.Frame(self)
        box.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)

        self.grade_button = ttk.Button(box, text="Grade Submission", command=self.start_grading)
        self.grade_button.grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

    def _build_output_section(self):
        box = ttk.LabelFrame(self, text="Result", padding=8)
        box.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.output = tk.Text(box, wrap="word", height=18, width=88, state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(box, orient="vertical", command=self.output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)

        self.output.tag_configure("heading", font=("Helvetica", 13, "bold"))
        self.output.tag_configure("info", foreground="#555555")
        self.output.tag_configure("error", foreground="#B00020")

    def _build_status_bar(self):
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=4, column=0, sticky="ew", pady=(10, 0)
        )

    # --------------------------------------------------------------- actions

    def _default_pdf(self, mode):
        """Resolves a mode's sample PDF next to this file, if it exists."""
        candidate = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), GRADING_MODES[mode]["default_pdf"]
        )
        return os.path.normpath(candidate) if os.path.exists(candidate) else ""

    def _on_mode_changed(self):
        """Swaps in the new mode's sample PDF only while the field still holds the old one."""
        other_defaults = {self._default_pdf(mode) for mode in GRADING_MODES}
        current = self.pdf_var.get().strip()
        if current == "" or current in other_defaults:
            self.pdf_var.set(self._default_pdf(self.mode_var.get()))

    def browse_pdf(self):
        current = self.pdf_var.get().strip()
        initial_dir = os.path.dirname(current) if current else os.path.dirname(
            os.path.abspath(__file__)
        )
        path = filedialog.askopenfilename(
            title="Choose a submission PDF",
            initialdir=initial_dir,
            filetypes=[("PDF documents", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_var.set(path)

    def start_grading(self):
        if self._worker and self._worker.is_alive():
            return

        pdf_path = self.pdf_var.get().strip()
        if not pdf_path:
            messagebox.showwarning(APP_TITLE, "Please choose a submission PDF first.")
            return
        if not os.path.isfile(pdf_path):
            messagebox.showerror(APP_TITLE, f"File not found:\n{pdf_path}")
            return

        mode = self.mode_var.get()
        dpi = int(self.dpi_var.get())

        self.clear_output()
        self._append(
            f"Grading {GRADING_MODES[mode]['label'].lower()}: {os.path.basename(pdf_path)}\n\n",
            "heading",
        )
        self._streaming = False
        self._set_busy(True)

        self._worker = threading.Thread(
            target=self._run_grading, args=(pdf_path, mode, dpi), daemon=True
        )
        self._worker.start()

    def _run_grading(self, pdf_path, mode, dpi):
        """Runs on the worker thread; talks to the UI only through the queue."""
        try:
            report = grader_core.grade_pdf(
                pdf_path,
                mode,
                dpi=dpi,
                on_progress=lambda message: self._events.put(("progress", message)),
                on_token=lambda piece: self._events.put(("token", piece)),
            )
            self._events.put(("result", report))
        except GradingError as e:
            self._events.put(("error", str(e)))
        except Exception as e:  # unexpected failures should still reach the window
            self._events.put(("error", f"Unexpected failure: {e}"))
        finally:
            self._events.put(("done", None))

    def _drain_events(self):
        """Pumps worker messages into the widgets on the UI thread."""
        try:
            while True:
                kind, payload = self._events.get_nowait()

                if kind == "progress":
                    self._set_status(payload)
                    self._append(f"{payload}\n", "info")
                elif kind == "token":
                    if not self._streaming:
                        # First words back from the model: open the report section.
                        self._streaming = True
                        self._append(f"\n{'-' * 60}\n\n")
                        self._set_status("Writing the report...")
                    self._append(payload)
                elif kind == "result":
                    # The text already streamed in; keep the clean copy for saving.
                    self._report = payload
                    self._append("\n")
                    self._set_status("Grading complete.")
                elif kind == "error":
                    self._append(f"\n{payload}\n", "error")
                    self._set_status("Grading failed.")
                    messagebox.showerror(APP_TITLE, payload)
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass

        self.after(100, self._drain_events)

    def _set_busy(self, busy):
        if busy:
            self._started_at = time.time()
            self.grade_button.state(["disabled"])
            self.progress.start(12)
            self._tick_clock()
        else:
            self._started_at = None
            self.grade_button.state(["!disabled"])
            self.progress.stop()

    def _set_status(self, message):
        """Records the current step; the clock re-renders it with elapsed time."""
        self._last_status = message
        self.status_var.set(self._decorate_status(message))

    def _decorate_status(self, message):
        if self._started_at is None:
            return message
        elapsed = int(time.time() - self._started_at)
        return f"{message}   [{elapsed // 60}:{elapsed % 60:02d} elapsed]"

    def _tick_clock(self):
        """Keeps a visible timer running so a slow model never looks frozen."""
        if self._started_at is None:
            return
        self.status_var.set(self._decorate_status(self._last_status))
        self.after(1000, self._tick_clock)

    def _append(self, text, tag=None):
        self.output.configure(state="normal")
        self.output.insert("end", text, tag or ())
        self.output.see("end")
        self.output.configure(state="disabled")

    def clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._report = ""
        self._set_status("Ready.")

    def save_report(self):
        report = self.output.get("1.0", "end").strip()
        if not report:
            messagebox.showinfo(APP_TITLE, "There is no report to save yet.")
            return

        suggested = "grading-report-{}.txt".format(datetime.now().strftime("%Y%m%d-%H%M%S"))
        path = filedialog.asksaveasfilename(
            title="Save grading report",
            defaultextension=".txt",
            initialfile=suggested,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report + "\n")
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not save the report:\n{e}")
            return

        self.status_var.set(f"Report saved to {path}")

    def show_about(self):
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE}\n\n"
            "Grades handwritten Discrete Mathematics submissions locally.\n\n"
            f"Model: {grader_core.MODEL_NAME} via Ollama ({grader_core.OLLAMA_HOST})\n"
            "PDF pages are rendered with poppler and never leave this computer.",
        )


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(760, 620)

    # ttk's 'aqua' theme on macOS already matches the system look; 'clam'
    # is the closest sane fallback elsewhere.
    style = ttk.Style()
    if sys.platform != "darwin" and "clam" in style.theme_names():
        style.theme_use("clam")

    GraderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
