# Automated Exam Grader 📝🤖

An automated Python-based system designed to evaluate handwritten exams, starting with Discrete Mathematics. The system extracts images from student PDF submissions and leverages Google's Gemini 2.5 Flash Vision LLM to analyze mathematical and logical correctness, providing an automated grade and detailed feedback.

## Tech Stack
* **Language:** Python 3
* **PDF Processing:** `pdf2image`, `poppler`
* **AI Integration:** Google Gemini API (`google-genai` SDK)

## Prerequisites (macOS)
This project requires Poppler for PDF-to-image conversion and the official Google GenAI SDK. Run the following commands in your terminal to set up your environment:

```bash
# Install Poppler via Homebrew
brew install poppler

# Install required Python dependencies
pip3 install pdf2image google-genai
