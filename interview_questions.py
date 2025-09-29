import google.generativeai as genai
import json
import os
import re
from dotenv import load_dotenv

# Assuming you've already configured your API key
# ---------- Environment Configuration ----------
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file!")


import google.generativeai as genai

def generate_interview_questions(resume_data, matches):
    # Define the prompt template for interview questions generation
    prompt = f"""
You are a professional interviewer. Based on the candidate's resume and the job matches, generate a list of interview questions.

Candidate's Resume:
{resume_data}

Top 5 Job Matches:
{matches}

Generate relevant interview questions based on the job and the resume.
Give me 5 resume-based interview questions and 5 job-based interview questions.
The questions should be specific and tailored to the candidate's experience and the job requirements.
Use match_results to create job-based questions. 
Give 5 job-based questions for each job match.
Give questions in simple wording.
In resume-based questions give 5 technical questions based on resume and 3 HR questions and 2 soft skills questions, give 3 senario-based questions.
Job-based questions should have format:
 Job Role :
 Company :
 Questions 
"""
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    
    try:
        # Send request to Gemini API
        response = model.generate_content(prompt)
        
        # Log the entire response for debugging purposes
        print(f"API Response: {response.text}")  # This logs the entire response from Gemini API
        
        if response.text.strip():  # Ensure response is not empty
            return response.text.strip().split("\n")  # Split into lines if necessary
        else:
            raise ValueError("Received empty response from API.")
    
    except Exception as e:
        # Log the error and return an error message
        print(f"Error generating interview questions: {e}")
        return {"error": str(e)}
