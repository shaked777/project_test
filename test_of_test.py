import os
import sys
import base64
import requests
from io import BytesIO
from pdf2image import convert_from_path

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
            "Attached are images of a student's exam. The document contains TWO printed questions, "
            "each followed by a student's handwritten answer in English."
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
            "Attached are images of a student's homework submission. The document contains printed questions, "
            "each followed by the student's handwritten answer in English. The number of questions may vary, "
            "so grade every question you can identify."
        ),
        "grading_stance": (
            "Grade formatively, as homework is a learning exercise. Reward correct reasoning and a genuine "
            "attempt, be lenient on minor arithmetic slips, and make the feedback instructional so the student "
            "knows how to fix the mistake next time."
        ),
    },
}


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


def check_local_ollama_status():
    """
    Verifies if the local Ollama server is running on the standard port.
    Replaces the previous cloud environment key-check validation.
    """
    print("[Info] Checking local Ollama server status...")
    try:
        response = requests.get("http://localhost:11434/", timeout=5)
        if response.status_code == 200:
            print("[Info] Local Ollama server detected and active.")
            return True
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Ollama server is not running. Please start the Ollama application on your Mac.")
    return False

def extract_images_from_pdf(pdf_path, dpi=150):
    """
    Converts all pages of a given PDF into a list of PIL images.
    """
    print(f"[Info] Extracting images from: {pdf_path} with DPI={dpi}...")
    try:
        pages = convert_from_path(pdf_path, dpi=dpi)
        if not pages:
            raise ValueError("The PDF file is empty or could not be read.")
        print(f"[Info] Successfully extracted {len(pages)} pages.")
        return pages
    except Exception as e:
        print(f"[Error] Failed to process PDF. Ensure poppler is installed via Homebrew. Details: {e}")
        return None

def convert_pil_images_to_base64(pil_images):
    """
    Converts and RESIZES PIL images to base64.
    Resizing is critical to prevent local API timeouts.
    """
    print("[Info] Resizing and encoding pages for local processing...")
    base64_strings = []
    try:
        for index, img in enumerate(pil_images):
            # Limit maximum dimensions to 1024x1024 to speed up local inference
            img.thumbnail((1024, 1024))
            
            buffer = BytesIO()
            # Compress quality to 85% to save memory transfer
            img.save(buffer, format="JPEG", quality=85)
            
            encoded_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            base64_strings.append(encoded_str)
            print(f"[Info] Page {index + 1}/{len(pil_images)} optimized and encoded.")
            
        return base64_strings
    except Exception as e:
        print(f"[Error] Failed to encode images. Details: {e}")
        return []

def grade_images_local(base64_images, grading_rubric, mode):
    """
    Sends the base64 images and the specific grading rubric to the local gemma4:e4b model.
    The prompt framing and strictness follow the selected mode ('exam' or 'homework').
    """
    mode_config = GRADING_MODES[mode]
    print(f"[Info] Connecting to local gemma4:e4b model to evaluate the {mode_config['label'].lower()}...")

    ollama_url = "http://localhost:11434/api/generate"

    prompt = f"""
    You are an expert teaching assistant in a Discrete Mathematics course for a Software Engineering degree.
    {mode_config['document_description']}

    GRADING STANCE FOR THIS SUBMISSION ({mode_config['label'].upper()}):
    {mode_config['grading_stance']}

    CRITICAL GRADING GUIDELINES (RUBRIC):
    {grading_rubric}

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

    # Building the exact structural payload requested by Ollama's vision framework
    payload = {
        "model": "gemma4:e4b",
        "prompt": prompt,
        "images": base64_images,
        "stream": False
    }
    
    try:
        # 180 seconds timeout handles heavier multi-page visual inference tasks locally
        response = requests.post(ollama_url, json=payload, timeout=300)
        response.raise_for_status()
        
        result_json = response.json()
        return result_json.get("response", "Error: No text response payload received from model.")
        
    except requests.exceptions.Timeout:
        print("[Error] The local Gemma 4 model took too long to respond. Consider reducing DPI size.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Error] Network communication failed with local API endpoint. Details: {e}")
        return None

# --- Main Execution ---
if __name__ == "__main__":
    # Usage: python test_of_test.py [exam|homework] [path/to/file.pdf]
    try:
        mode = select_grading_mode(sys.argv)
        mode_config = GRADING_MODES[mode]

        # Standard macOS path formatting (Adjust path to target your localized workspace)
        pdf_file_path = sys.argv[2] if len(sys.argv) > 2 else mode_config["default_pdf"]
        rubric = mode_config["rubric"]

        print(f"\nStarting the automated LOCAL grading process ({mode_config['label']})...")
        print(f"[Info] Target document: {pdf_file_path}\n")

        # Validate that Ollama server is functional before triggering asset extraction
        if check_local_ollama_status():
            pil_images = extract_images_from_pdf(pdf_file_path, dpi=72)

            if pil_images:
                # Reformat image architecture to fit the local endpoint specifications
                base64_encoded_images = convert_pil_images_to_base64(pil_images)

                if base64_encoded_images:
                    result = grade_images_local(base64_encoded_images, rubric, mode)

                    if result:
                        print(f"\n--- Local Grading Result ({mode_config['label']}) ---\n")
                        print(result)
                        print("\n----------------------------\n")

    except Exception as e:
        print(f"[Error] Runtime execution failed: {e}")
