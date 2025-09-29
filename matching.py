from fastapi import FastAPI, File, UploadFile, Body
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import json
import re
import traceback
import numpy as np
import PyPDF2
import google.generativeai as genai
from typing import List, Dict, Any
from sklearn.metrics.pairwise import cosine_similarity
from interview_questions import generate_interview_questions

# ---------- Environment Configuration ----------
load_dotenv(os.path.join(os.path.dirname(__file__), ".env")) # Load environment variables from .env file
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file!")

genai.configure(api_key=API_KEY)
print("🧪 Loaded API Key from .env:", API_KEY[:8], "...")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or use ["http://127.0.0.1:5500"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/") # Root endpoint for testing
def read_root():
    return {"message": "Welcome to the Resume Job Matcher API!"}

# ---------- Load Job Descriptions ----------
job_file_path = os.path.join(os.path.dirname(__file__), "job_descriptions.json")
with open(job_file_path, "r") as f:
    inbuilt_job_data = json.load(f)

# ---------- Resume Matcher Class ----------
class ResumeJobMatcher:
    def __init__(self, model_name="text-embedding-3-small"):
        self.embedding_model = model_name

    def generate_embedding(self, text: str) -> List[float]:
        import hashlib
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % 10000
        np.random.seed(seed)
        return np.random.rand(384).tolist()

    def calculate_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        return float(cosine_similarity([vec1], [vec2])[0][0])

    def format_resume(self, data: Dict[str, Any]) -> str:   # Converts resume data to a string format for embedding
        parts = [
            f"Name: {data.get('name', '')}",
            f"Skills: {', '.join(data.get('skills', []))}"
        ]
        for job in data.get("work_experience", []):
            parts.append(f"{job.get('job_title', '')} at {job.get('company', '')}")
            parts.extend(job.get("responsibilities", []))
        for edu in data.get("education", []):
            parts.append(f"{edu.get('degree', '')} in {edu.get('field_of_study', '')} from {edu.get('university', '')}")
        return "\n".join(parts)

    def format_job(self, job: Dict[str, Any]) -> str: # Converts job description data to a string format for embedding
        parts = [
            f"{job.get('Job Title', '')} at {job.get('Company', '')}",
            job.get("Location", ""),
            job.get("Job Type", "")
        ]
        parts += job.get("Responsibilities", []) + job.get("Requirements", [])
        parts.append(job.get("About the Company", ""))
        return "\n".join(parts)

    # Matches resume data to job descriptions based on experience level and similarity
    # Returns a list of job matches with similarity scores
    def match_resume_to_jobs(self, resume_data: Dict[str, Any], jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        resume_text = self.format_resume(resume_data)
        resume_vec = self.generate_embedding(resume_text)
        experience_level = resume_data.get("experience_level", "fresher").lower()

        results = []
        for job in jobs:
            required_level = job.get("Experience Level", "").lower()
            if required_level and required_level != experience_level:
                continue

            job_text = self.format_job(job)
            job_vec = self.generate_embedding(job_text)
            similarity = self.calculate_similarity(resume_vec, job_vec)

            results.append({
                "id": job.get("id"),
                "job_title": job.get("Job Title"),
                "company": job.get("Company"),
                "location": job.get("Location"),
                "job_type": job.get("Job Type"),
                "requirements": job.get("Requirements", []),
                "experience_required": required_level or "not specified",
                "similarity_percentage": round(similarity * 100, 2)
            })# Store job match results

        return sorted(results, key=lambda x: x["similarity_percentage"], reverse=True)[:5]

# ---------- Utility Functions ----------
def extract_text_from_pdf(file) -> str:
    reader = PyPDF2.PdfReader(file)
    return "".join(page.extract_text() or "" for page in reader.pages).strip()

def build_prompt(resume_text: str) -> str: # Constructs the prompt for the Gemini model to extract structured information from the resume
    return f"""
You are an AI assistant that extracts structured information from resumes.

Given the following resume text, extract the information in the specified JSON format. Return only the JSON.

Resume Text:
\"\"\"
{resume_text}
\"\"\"

Extract and return this structure:
{{
  "name": "", "email": "", "phone": "", "skills": [],
  "linkedin": "",
  "work_experience": [{{"job_title": "", "company": "", "location": "", "start_date": "", "end_date": "", "responsibilities": []}}],
  "education": [{{"degree": "", "field_of_study": "", "university": "", "start_year": "", "end_year": ""}}],
  "certifications": [{{"name": "", "issuer": "", "date": ""}}],
  "trainings": [{{"name": "", "provider": "", "date": ""}}],
  "projects": [{{"title": "", "description": "", "technologies": []}}],
  "awards": [], "languages": [], "publications": [], "volunteer_experience": []
}}

Rules for Calculating Total Work Experience and Determining Experience Level:

1. Work experience should be calculated only from full-time or part-time job roles — do NOT count internships as professional experience.
2. If a "work_experience" entry mentions keywords like "intern", "internship", or similar in the "job_title", treat it as internship and exclude it from experience calculation.
3. If the candidate has **only internships** and no full-time/part-time job roles, they are considered a **Fresher**.
4. If the candidate has both internships and valid job roles, count only the valid job roles when calculating total experience.

5. For valid job entries:
   a. Calculate the number of months between "start_date" and "end_date".
   b. If "end_date" is "Present" or missing, assume the current date.
   c. If job periods overlap, count overlapping time only once.

6. Sum the non-overlapping durations of all valid job entries to compute total experience in months.
7. Convert the total months into years (e.g., 18 months = 1.5 years), rounded to 1 decimal place.

8. Based on total valid experience (excluding internships), assign experience level:
   - If total experience < 1.0 years: `"experience_level": "Fresher"`
   - If total experience ≥ 1.0 years: `"experience_level": "Experienced"`

The output must include:
- `"total_experience_years"`: Total valid (non-internship) experience in years, as a float (e.g., "0.8", "2.3").
- `"experience_level"`: Either "Fresher" or "Experienced".

"""

def extract_json(text: str) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("Failed to extract JSON from Gemini response.")

# ---------- API Endpoint ----------
@app.post("/") # Root endpoint for testing
def root():
    return {"message": "Welcome to the Resume Job Matcher API!"}

@app.post("/upload-resume/")# Endpoint to upload a resume and match it to jobs
async def upload_resume(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith(".pdf"):  # Check if the uploaded file is a PDF
            return JSONResponse(content={"error": "Only PDF files are allowed."}, status_code=400)

        resume_text = extract_text_from_pdf(file.file)  # Extract text from the PDF file
        if not resume_text:
            return JSONResponse(content={"error": "Could not extract text from PDF."}, status_code=400)

        prompt = build_prompt(resume_text)  # Implement the prompt for the Gemini model
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")    
        # model.configure(api_key=API_KEY)
        print("✅ Gemini model instantiated, generating content...")
        response = model.generate_content(prompt)
        resume_data = extract_json(response.text.strip())
        
        matcher = ResumeJobMatcher()
        matches = matcher.match_resume_to_jobs(resume_data, inbuilt_job_data)

        interview_questions = generate_interview_questions(resume_data, matches)  # imported from interview_questions.py

        return JSONResponse(content={
            "resume_data": resume_data,
            "total_experience_years": resume_data.get("total_experience_years"),
            "experience_level": resume_data.get("experience_level"),
            "match_results": matches,
            "interview_questions": interview_questions
        })  # Return structured response with resume data, matches, and interview questions
        
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)
    
@app.post("/generate-questions/") # Endpoint to generate interview questions based on resume and job
async def generate_questions(payload: Dict[str, Any] = Body(...)):
    try:
        resume_data = payload.get("resume_data")
        selected_job = payload.get("job")

        if not resume_data or not selected_job:
            return JSONResponse(content={"error": "Missing resume_data or job"}, status_code=400)

        questions = generate_interview_questions(resume_data, [selected_job]) #
        return JSONResponse(content={"questions": questions})

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(content={"error": str(e)}, status_code=500)
        
