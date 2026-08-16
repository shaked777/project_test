"""
Core grading logic for the Automated Exam Grader.

This module holds everything that is independent of the user interface:
grading modes, PDF extraction, image encoding and the call to the local
Ollama model. Both the desktop app (app.py) and the command line script
(test_of_test.py) build on top of it.

Nothing in here prints or asks for input. Progress is reported through an
optional `on_progress` callback so the caller decides how to display it.
"""

import base64
import json
from io import BytesIO

import requests
from pdf2image import convert_from_path

OLLAMA_HOST = "http://localhost:11434"
# The chat endpoint is the one that actually forwards attached images to the
# vision model. /api/generate accepts an "images" field but drops it silently,
# which makes the model grade a page it never saw.
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
MODEL_NAME = "gemma4:e4b"

EXAM_RUBRIC = """
CRITICAL GRADING GUIDELINES (RUBRIC):

Question 2a: Mathematical Induction
- Base Case (n=1): Verify the student correctly substituted n=1 into both sides of the equation. Deduct 3 points if the base case is missing or incorrect.
- Induction Hypothesis: Verify the student explicitly stated the assumption for n=k. Deduct 2 points if the hypothesis is completely missing.
- Induction Step: Verify the mathematical manipulation to prove the statement for n=k+1. Deduct 4 points for minor algebraic errors. Deduct 7 points for fundamental logical failures or an inability to complete the proof.

Question 2b: Newton's Binomial Theorem
- Reference Values: The correct value for 'n' is 6. The correct coefficient for x^9 is 120.
- Finding 'n' (Total 6 points): The student must use the constant term (-192) to set up an equation and find 'n'. Deduct 6 points if 'n' is incorrect, missing, or if the method is completely wrong. Deduct 2 points for a minor arithmetic error if the logic is correct.
- Finding the coefficient of x^9 (Total 7 points): The student must correctly apply the binomial expansion formula. Deduct 7 points if the binomial theorem is not used or applied incorrectly. Deduct 3 points for minor calculation errors in determining the final coefficient.
"""

HOMEWORK_RUBRIC = """
CRITICAL GRADING GUIDELINES (RUBRIC):

General homework policy (applies to every question):
- Completion: A serious, complete attempt at the question earns the majority of its points. Deduct the full value of a question only if it is missing or left blank.
- Method over arithmetic: Homework rewards correct reasoning. Deduct at most 20% of the question's value for a minor arithmetic or algebraic slip when the method is correct.
- Fundamental errors: Deduct 50%-70% of the question's value when the chosen method is wrong or the logic breaks down, even if a final answer is written.
- Presentation: Deduct up to 10% of the question's value if intermediate steps are missing and the answer cannot be followed.
- Late/partial work is not penalized here; grade only the mathematical content that appears on the page.
"""

# Each grading mode carries its own prompt framing, rubric and default document.
GRADING_MODES = {
    "exam": {
        "label": "Exam",
        "default_pdf": "./test_03.pdf",
        "rubric": EXAM_RUBRIC,
        "document_description": (
            "You are looking at the scanned pages of a student's exam. The pages contain TWO printed "
            "questions, each followed by the student's handwritten answer in English."
        ),
        "grading_stance": (
            "Grade strictly, as an exam under time constraints is still expected to be rigorous. "
            "Apply every deduction listed in the rubric literally and do not award points for effort alone."
        ),
    },
    "homework": {
        "label": "Homework",
        "default_pdf": "./test_01.pdf",
        "rubric": HOMEWORK_RUBRIC,
        "document_description": (
            "You are looking at the scanned pages of a student's homework submission. The pages contain "
            "printed questions, each followed by the student's handwritten answer in English. The number of "
            "questions may vary, so grade every question you can identify."
        ),
        "grading_stance": (
            "Grade formatively, as homework is a learning exercise. Reward correct reasoning and a genuine "
            "attempt, be lenient on minor arithmetic slips, and make the feedback instructional so the student "
            "knows how to fix the mistake next time."
        ),
    },
}


class GradingError(Exception):
    """Raised when a grading run cannot be completed."""


def _noop(_message):
    """Default progress sink used when the caller does not supply one."""


def check_local_ollama_status(timeout=5):
    """
    Verifies that the local Ollama server is running on the standard port.
    Raises GradingError with an actionable message when it is not reachable.
    """
    try:
        response = requests.get(f"{OLLAMA_HOST}/", timeout=timeout)
    except requests.exceptions.RequestException:
        raise GradingError(
            "Ollama server is not running. Please start the Ollama application on your Mac."
        )

    if response.status_code != 200:
        raise GradingError(
            f"Ollama server answered with status {response.status_code} instead of 200."
        )
    return True


def extract_images_from_pdf(pdf_path, dpi=72, on_progress=None):
    """
    Converts all pages of a given PDF into a list of PIL images.
    """
    on_progress = on_progress or _noop
    on_progress(f"Extracting images from {pdf_path} at {dpi} DPI...")
    try:
        pages = convert_from_path(pdf_path, dpi=dpi)
    except Exception as e:
        raise GradingError(
            f"Failed to process the PDF. Ensure poppler is installed via Homebrew. Details: {e}"
        )

    if not pages:
        raise GradingError("The PDF file is empty or could not be read.")

    on_progress(f"Extracted {len(pages)} page(s).")
    return pages


def convert_pil_images_to_base64(pil_images, max_size=(1024, 1024), quality=85, on_progress=None):
    """
    Converts and RESIZES PIL images to base64.
    Resizing is critical to prevent local API timeouts.
    """
    on_progress = on_progress or _noop
    on_progress("Resizing and encoding pages for local processing...")

    base64_strings = []
    try:
        for index, img in enumerate(pil_images):
            # Limit maximum dimensions to speed up local inference
            img.thumbnail(max_size)

            buffer = BytesIO()
            # Compress to save memory transfer
            img.save(buffer, format="JPEG", quality=quality)

            base64_strings.append(base64.b64encode(buffer.getvalue()).decode("utf-8"))
            on_progress(f"Page {index + 1}/{len(pil_images)} optimized and encoded.")
    except Exception as e:
        raise GradingError(f"Failed to encode images. Details: {e}")

    return base64_strings


def build_prompt(mode, grading_rubric):
    """
    Builds the grading prompt for the selected mode.
    """
    mode_config = GRADING_MODES[mode]
    return f"""
    You are an expert teaching assistant in a Discrete Mathematics course for a Software Engineering degree.
    {mode_config['document_description']}

    GRADING STANCE FOR THIS SUBMISSION ({mode_config['label'].upper()}):
    {mode_config['grading_stance']}

    CRITICAL GRADING GUIDELINES (RUBRIC):
    {grading_rubric}

    The pages are supplied with this message and you can read them directly. Never claim that no
    images were provided; grade what is visible on the pages.

    Your task:
    1. Identify and extract the context of every printed question.
    2. Read the student's handwritten answer below each question carefully.
    3. Evaluate the student's logic, mathematical notations, and method.
    4. You MUST apply the 'CRITICAL GRADING GUIDELINES' provided above to determine the score.
    5. Grade each answer against the maximum score printed next to the question.
    6. Provide a short feedback explaining the deduction (if any) based exactly on the rubric.

    Return the response strictly in the following format, repeating the block once per question:

    Question [number]: [English translation of the printed question]
    Grade: [Score]/max from printed question
    Feedback: [Your feedback based on the rubric]
    """


def grade_images_local(
    base64_images, grading_rubric, mode, timeout=900, on_progress=None, on_token=None
):
    """
    Sends the base64 images and the specific grading rubric to the local model.
    The prompt framing and strictness follow the selected mode ('exam' or 'homework').

    The response is streamed. Each chunk of generated text is handed to `on_token`
    as it arrives, so a caller can show the report being written instead of
    sitting on a frozen screen while the model thinks. The full report is
    returned once the stream ends.

    `timeout` applies to each network read, not to the run as a whole, so a slow
    but healthy model is never cut off mid-report.
    """
    on_progress = on_progress or _noop
    on_token = on_token or _noop
    mode_config = GRADING_MODES[mode]
    on_progress(
        f"Sending {len(base64_images)} page(s) to the local {MODEL_NAME} model to evaluate the "
        f"{mode_config['label'].lower()}. The first words can take a minute or two to appear..."
    )

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": build_prompt(mode, grading_rubric),
                "images": base64_images,
            }
        ],
        "stream": True,
        # Deterministic decoding: the same submission should always earn the same grade.
        "options": {"temperature": 0},
    }

    chunks = []
    try:
        with requests.post(
            OLLAMA_CHAT_URL, json=payload, timeout=timeout, stream=True
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # ignore keep-alive or partial frames

                if event.get("error"):
                    raise GradingError(f"The model reported an error: {event['error']}")

                piece = event.get("message", {}).get("content", "")
                if piece:
                    chunks.append(piece)
                    on_token(piece)

                if event.get("done"):
                    break
    except requests.exceptions.Timeout:
        raise GradingError(
            "The local model stopped responding. Try a lower DPI setting, or check that "
            "the Ollama application is still running."
        )
    except requests.exceptions.RequestException as e:
        raise GradingError(f"Network communication failed with the local API endpoint. Details: {e}")

    result = "".join(chunks).strip()
    if not result:
        raise GradingError("No text response payload was received from the model.")
    return result


def grade_pdf(pdf_path, mode, dpi=72, on_progress=None, on_token=None):
    """
    Runs the full pipeline for one submission and returns the model's report.
    This is the single entry point used by both the desktop app and the CLI.
    """
    on_progress = on_progress or _noop

    if mode not in GRADING_MODES:
        raise GradingError(
            f"Unknown grading mode '{mode}'. Valid options: {', '.join(GRADING_MODES)}."
        )

    on_progress("Checking local Ollama server status...")
    check_local_ollama_status()
    on_progress("Local Ollama server detected and active.")

    pages = extract_images_from_pdf(pdf_path, dpi=dpi, on_progress=on_progress)
    encoded_pages = convert_pil_images_to_base64(pages, on_progress=on_progress)
    return grade_images_local(
        encoded_pages,
        GRADING_MODES[mode]["rubric"],
        mode,
        on_progress=on_progress,
        on_token=on_token,
    )
