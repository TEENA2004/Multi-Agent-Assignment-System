# 🎓 EvLax AI — Multi-Agent Assessment System |  Major Project 2026

> **Major Project | BSc(H)-Data Anaytics and AI CSE |  IIS University, Jaipur | 2025–26**

An AI-powered assessment system for teachers to evaluate student answer sheets using multi-agent AI pipelines. Built with Flask, Groq LLM API, and SQLite.

---

## 📌 What This Project Does

IIS EduGrade AI helps teachers at IIS University automate the process of:
- Analyzing question papers for Bloom's Taxonomy levels
- Evaluating student handwritten answer sheets
- Detecting Course Outcome (CO) attainment levels (NBA Accreditation standard)
- Generating personalized AI feedback for each student

---

## 🧠 4 Core Modules (Tabs)

### 1️⃣ Question Analyzer
- Upload a CA exam question paper (PDF/Image)
- AI detects Bloom's Taxonomy level (L1–L6) for each question
- Checks if questions are within the CA syllabus (Unit 1 & Unit 2 only)
- Teacher can add their own BT level feedback
- Download report as Excel

### 2️⃣ Answer Evaluator
- Type or scan student answers per question
- Runs a **4-Agent AI Pipeline**:
  - **Agent 1** — Keyword Extractor
  - **Agent 2** — Keyword Matcher (60% weightage)
  - **Agent 3** — Semantic Evaluator (40% weightage)
  - **Orchestrator** — Final Judge (combines agents → final marks)
- CA Rule: 4 questions, student attempts any 3, 5 marks each = 15 marks total
- Not-attempted questions automatically get 0 marks
- Teacher can add/edit feedback per answer
- Download results as Excel

### 3️⃣ Level Detector
- Connected to Answer Evaluator
- Calculates **CO Attainment Score (0–5)** per student per subject
- College Target = 3/5 (Average) — NBA Accreditation Standard
- Shows Target Met / Below Target status
- Download Excel report

### 4️⃣ Feedback Generator
- Shows personalized AI feedback + teacher feedback + improvement tips per student
- Current session students only (no old history by default)
- Search history by name or roll number
- Teacher can add/edit feedback inline
- Download feedback Excel report

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python Flask |
| AI / LLM | Groq API (llama-3.3-70b-versatile + llama-4-scout vision) |
| Database | SQLite |
| Frontend | HTML, CSS, Vanilla JavaScript |
| Excel Export | openpyxl |
| PDF Processing | PyMuPDF (fitz) |

---

## 🚀 How to Run Locally

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/IIS-EduGrade-AI.git
cd IIS-EduGrade-AI
```

### 2. Install dependencies
```bash
pip install flask groq PyMuPDF openpyxl pillow flask-session
```

### 3. Add your Groq API Key
Open `app.py` and replace:
```python
groq_client = Groq(api_key="YOUR_GROQ_API_KEY_HERE")
```
Get free API key at: https://console.groq.com

### 4. Run the app
```bash
python app.py
```

### 5. Open in browser
```
http://127.0.0.1:5000
```

---

## 📁 Project Structure

```
IIS-EduGrade-AI/
├── app.py                        ← Main backend (Flask + Groq AI)
├── requirements.txt              ← Python dependencies
├── README.md
├── .gitignore
├── templates/
│   ├── home.html
│   ├── login.html
│   ├── register.html
│   ├── assess.html               ← Question Analyzer tab
│   ├── answer_evaluator.html     ← Answer Evaluator tab
│   ├── level_detector.html       ← Level Detector tab
│   ├── feedback_generator.html   ← Feedback Generator tab
│   └── student_dashboard.html    ← Student login view
└── static/
    └── iisu_logo.jpg
```

---

## 📋 CA Exam Format (IIS University)

- **Exam:** Continuous Assessment (CA)
- **Questions:** 4 questions per paper
- **Attempt:** Any 3 out of 4
- **Marks:** 5 marks per question = 15 marks total
- **Syllabus:** Unit 1 & Unit 2 only

---

## 🏫 CO Attainment Scale (NBA Standard)

| Score | % Range | Level |
|---|---|---|
| 0 | 0% | Not Attempted |
| 1 | 1–20% | Needs Improvement |
| 2 | 21–40% | Below Average |
| 3 | 41–60% | Average ⭐ College Target |
| 4 | 61–80% | Good |
| 5 | 81–100% | Excellent |

> ⭐ College Target = 3/5 — NBA Accreditation Standard: minimum 60% of students must achieve CO ≥ 3

---

## 👩‍💻 Developer

**Teena Sharma**
Bsc(H) Data Analyst and AI  — IIS University, Jaipur
Major Project 2025–26

> **Note:** Source code is kept private. 
> This repository contains project documentation and reports only.
> For code review or demo access, please connect via LinkedIn.

---

## 📄 License

This project was developed as a Major Project for academic purposes at IIS University, Jaipur.
