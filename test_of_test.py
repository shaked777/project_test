import os
import time
from dotenv import load_dotenv
from google import genai
from pdf2image import convert_from_path

def setup_gemini_client():
    """
    Configures the Gemini API client using the google-genai SDK.
    Loads credentials safely from a local .env file.
    """
    load_dotenv()
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Environment variable GEMINI_API_KEY is not set. Please check your .env file.")
    
    print("[Info] Gemini API key loaded successfully.")
    return genai.Client(api_key=api_key)

def extract_images_from_pdf(pdf_path, dpi=150):
    """
    Converts all pages of a given PDF into a list of images.
    Optimized DPI to 150 to prevent API token quota exhaustion while maintaining readability.
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

def grade_exam_images(client, exam_images, grading_rubric, max_retries=3, base_delay=5):
    """
    Sends the exam images and the specific grading rubric to Gemini 1.5 Flash.
    Includes Exponential Backoff logic to handle API rate limits and server overloads.
    """
    print("[Info] Analyzing the exam and applying grading guidelines...")
    
    prompt = f"""
    You are an expert teaching assistant in a Discrete Mathematics course for a Software Engineering degree.
    Attached are images of a student's exam. The document contains TWO printed questions, each followed by a student's handwritten answer in English.
    
    CRITICAL GRADING GUIDELINES (RUBRIC):
    {grading_rubric}
    
    Your task:
    1. Identify and extract the context of the two printed questions.
    2. Read the student's handwritten answer below each question carefully.
    3. Evaluate the student's logic, mathematical notations, and method.
    4. You MUST apply the 'CRITICAL GRADING GUIDELINES' provided above to determine the score.
    5. Grade each answer on a scale of 0 to extract the grade from the two printed questions.
    6. Provide a short feedback explaining the deduction (if any) based exactly on the rubric.
    
    Return the response strictly in the following format:
    
    Question 1: [English translation of the printed question]
    Grade: [Score]/max from printed question
    Feedback: [Your feedback based on the rubric]
    
    Question 2: [English translation of the printed question]
    Grade: [Score]/max from printed question
    Feedback: [Your feedback based on the rubric]
    """
    
    contents_payload = [prompt] + exam_images
    
    for attempt in range(max_retries):
        try:
            # Using 1.5-flash for the most generous free-tier limits
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents_payload
            )
            return response.text
            
        except Exception as e:
            error_message = str(e).lower()
            if "429" in error_message or "503" in error_message or "overloaded" in error_message or "quota" in error_message:
                if attempt == max_retries - 1:
                    print(f"[Error] Max retries reached. The model is still overloaded or out of quota. Details: {e}")
                    return None
                
                sleep_time = base_delay * (2 ** attempt)
                print(f"[Warning] Quota limit or server overload hit. Retrying in {sleep_time} seconds (Attempt {attempt + 1}/{max_retries})...")
                time.sleep(sleep_time)
            else:
                print(f"[Error] API Communication Error: {e}")
                return None

# --- Main Execution ---
if __name__ == "__main__":
    pdf_file_path = "test_03.pdf" 
    
    rubric = """
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
    
    print("\nStarting the automated grading process...\n")
    
    images = extract_images_from_pdf(pdf_file_path, dpi=150)
    
    if images:
        try:
            gemini_client = setup_gemini_client()
            result = grade_exam_images(gemini_client, images, rubric)
            
            if result:
                print("\n--- Grading Result ---\n")
                print(result)
        except Exception as e:
            print(f"[Error] Execution failed: {e}")