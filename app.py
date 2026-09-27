from flask import Flask, render_template, request, jsonify, session, redirect, send_file
import sqlite3, json, re, base64, traceback
from groq import Groq

app = Flask(__name__)
app.secret_key = 'iis_edugrade_secret_2026'
# Use filesystem sessions so large PDF data (base64 pages) can be stored
# without hitting the 4KB cookie size limit
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '.flask_sessions'
app.config['SESSION_PERMANENT'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit

try:
    from flask_session import Session
    Session(app)
    print("[INFO] flask-session loaded — using filesystem sessions")
except ImportError:
    print("[INFO] flask-session not installed — using cookie sessions (large PDFs may fail)")
    print("[INFO] Run: pip install flask-session  to fix large PDF uploads")

groq_client = GROQ_API_KEY = "your-api-key-here"

DB = 'edugrade.db'

# ─────────────────────────────────────────────
#  AI HELPERS
# ─────────────────────────────────────────────
def gemini(prompt, max_tokens=800):
    models = ["llama-3.1-8b-instant", "mixtral-8x7b-32768"]
    last_error = None
    for model_name in models:
        try:
            response = groq_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Model Failed: {model_name}] -> {str(e)}")
            last_error = e
            continue
    return f"[Groq Error: {str(last_error)}]"

def gemini_vision(prompt_text, image_b64):
    try:
        response = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": prompt_text}
            ]}],
            max_tokens=2000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Vision error: {str(e)}]"

def pdf_to_images(pdf_b64):
    """Convert PDF base64 to list of JPEG base64 images, one per page."""
    try:
        import fitz
        pdf_bytes = base64.b64decode(pdf_b64)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for page in doc:
            rotation = page.rotation
            mat = fitz.Matrix(2.0, 2.0).prerotate(-rotation)
            pix = page.get_pixmap(matrix=mat)
            images.append(base64.b64encode(pix.tobytes("jpeg")).decode())
        doc.close()
        return images
    except Exception as e:
        print(f"[pdf_to_images error]: {e}")
        return []

def parse_json(text):
    text = re.sub(r'```json\s*|\s*```', '', text).strip()
    # Remove ALL invalid control characters (fixes "char 598" error from OCR text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    start = text.find('{')
    end   = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Second pass: remove control chars inside strings char by char
        cleaned = []
        in_str = False
        esc_next = False
        for ch in text:
            if esc_next:
                cleaned.append(ch); esc_next = False; continue
            if ch == '\\':
                esc_next = True; cleaned.append(ch); continue
            if ch == '"':
                in_str = not in_str; cleaned.append(ch); continue
            if in_str and ord(ch) < 32 and ch not in ('\t', '\n', '\r'):
                cleaned.append(' '); continue
            cleaned.append(ch)
        return json.loads(''.join(cleaned))

# ─────────────────────────────────────────────
#  SUBJECT / SYLLABUS DATA
# ─────────────────────────────────────────────
SUBJECTS = {
    "BCA": ["Ethical Hacking","Web Application Development-III","Fundamentals of Testing","Mobile Application Development","Machine Learning","Cloud Computing","Presentation Skills"],
    "BSc(H) Data Analytics & AI": ["Operations Research","Linear Algebra","Data Visualization","Computer Vision and IoT","Big Data and Text Mining","Presentation Skills"],
}

CA_SYLLABUS = {
    "Ethical Hacking": {"unit1":"Introduction to ethical hacking, hacking concepts, types of hackers, ethical hacking phases, footprinting and reconnaissance, Google hacking, WHOIS, DNS enumeration","unit2":"Scanning networks, port scanning, vulnerability scanning, enumeration techniques, NetBIOS enumeration, SNMP enumeration, LDAP enumeration, NTP enumeration"},
    "Web Application Development-III": {"unit1":"Introduction to Node.js, event-driven architecture, NPM, modules, file system, HTTP module, creating web server, Express.js basics, routing","unit2":"Middleware in Express, template engines (EJS/Pug), REST APIs, HTTP methods, request/response handling, JSON, form handling, CRUD operations"},
    "Fundamentals of Testing": {"unit1":"Software testing fundamentals, testing principles, test process, psychology of testing, testing levels, unit testing, integration testing, system testing","unit2":"Black box testing techniques, equivalence partitioning, boundary value analysis, decision table testing, state transition testing, white box testing, control flow"},
    "Mobile Application Development": {"unit1":"Introduction to Android, Android architecture, Android SDK, Activity lifecycle, Intents, layouts, Views, ViewGroups, XML layouts, LinearLayout, RelativeLayout","unit2":"UI components: TextView, EditText, Button, ImageView, RecyclerView, ListView, Adapters, event handling, menus, dialogs, Toast messages"},
    "Machine Learning": {"unit1":"Introduction to ML, types of ML (supervised, unsupervised, reinforcement), data preprocessing, feature engineering, train/test split, cross-validation, overfitting","unit2":"Linear regression, logistic regression, cost function, gradient descent, decision trees, random forest, evaluation metrics: accuracy, precision, recall, F1 score"},
    "Cloud Computing": {"unit1":"Introduction to cloud computing, characteristics, cloud deployment models (public, private, hybrid), cloud service models (IaaS, PaaS, SaaS), virtualization basics","unit2":"Cloud architecture, scalability, elasticity, load balancing, AWS/Azure/GCP overview, virtual machines, storage services, cloud security fundamentals"},
    "Presentation Skills": {"unit1":"Communication basics, verbal and non-verbal communication, public speaking, audience analysis, presentation planning, content structuring, introduction techniques","unit2":"Visual aids, slide design principles, body language, voice modulation, handling nervousness, Q&A sessions, business presentation etiquette"},
    "Operations Research": {"unit1":"Introduction to OR, linear programming formulation, graphical method, simplex method, maximization and minimization problems, Big-M method","unit2":"Duality in LPP, dual simplex method, sensitivity analysis, transportation problem, north-west corner method, MODI method, Vogel's approximation"},
    "Linear Algebra": {"unit1":"Matrices, types of matrices, matrix operations, determinants, properties of determinants, Cramer's rule, inverse of matrix, rank of matrix","unit2":"System of linear equations, Gauss elimination, Gauss-Jordan method, vector spaces, subspaces, linear independence, basis, dimension, span"},
    "Data Visualization": {"unit1":"Introduction to data visualization, importance, types of charts (bar, line, pie, scatter, histogram), principles of good visualization, data-ink ratio, Tufte's principles","unit2":"Matplotlib basics, Seaborn library, plotting functions, customization, multi-plot figures, Plotly introduction, interactive charts, color theory in visualization"},
    "Computer Vision and IoT": {"unit1":"Introduction to computer vision, image formation, pixel, image representation, color models (RGB, HSV, grayscale), image preprocessing, noise removal, filters","unit2":"Edge detection (Sobel, Canny), morphological operations, thresholding, contour detection, feature extraction, SIFT, SURF basics using OpenCV"},
    "Big Data and Text Mining": {"unit1":"Introduction to Big Data, 5 V's of Big Data, Hadoop ecosystem, HDFS architecture, MapReduce paradigm, YARN, Hive, Pig, HBase overview","unit2":"Text mining concepts, NLP basics, tokenization, stemming, lemmatization, stop words removal, TF-IDF, bag of words, text classification, sentiment analysis basics"},
}

# ─────────────────────────────────────────────
#  DATABASE INIT
# ─────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT UNIQUE, password TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_no TEXT UNIQUE NOT NULL,
            course TEXT NOT NULL,
            semester TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course TEXT, exam TEXT, subject TEXT,
            question_text TEXT, bt_level_ai TEXT,
            syllabus_check TEXT, difficulty TEXT,
            quality TEXT, marks TEXT, suggestion TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER, teacher_name TEXT,
            teacher_bt TEXT, teacher_suggestion TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT, student_name TEXT,
            exam TEXT, course TEXT, subject TEXT,
            q_number INTEGER DEFAULT 0,
            question_text TEXT, answer_text TEXT,
            keyword_score REAL, semantic_score REAL,
            final_score REAL, max_marks INTEGER, final_marks REAL,
            grade TEXT, performance TEXT, ai_feedback TEXT,
            teacher_marks REAL, teacher_feedback TEXT, teacher_name TEXT,
            improvement_tips TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute('ALTER TABLE evaluations ADD COLUMN q_number INTEGER DEFAULT 0')
            conn.commit()
        except Exception:
            pass
        conn.commit()

init_db()

# ─────────────────────────────────────────────
#  AUTH ROUTES — TEACHER
# ─────────────────────────────────────────────
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    data = request.get_json()
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute('SELECT name FROM users WHERE email=? AND password=?', (data['email'], data['password']))
        user = c.fetchone()
    if user:
        session['name']  = user[0]
        session['email'] = data['email']
        session['role']  = 'teacher'
        return jsonify({'success': True, 'name': user[0]})
    return jsonify({'error': 'Invalid email or password'})

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    data = request.get_json()
    try:
        with sqlite3.connect(DB) as conn:
            conn.execute('INSERT INTO users (name,email,password) VALUES (?,?,?)',
                         (data['name'], data['email'], data['password']))
            conn.commit()
        return jsonify({'success': True, 'name': data['name']})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already registered'})

# ─────────────────────────────────────────────
#  AUTH ROUTES — STUDENT
# ─────────────────────────────────────────────
@app.route('/student-login', methods=['GET','POST'])
def student_login():
    if request.method == 'GET':
        return render_template('student_login.html')
    data = request.get_json()
    email    = data.get('email','').strip().lower()
    password = data.get('password','').strip()
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM students WHERE email=? AND password=?', (email, password))
        student = c.fetchone()
    if student:
        session['name']    = student['name']
        session['email']   = student['email']
        session['role']    = 'student'
        session['roll_no'] = student['roll_no']
        session['course']  = student['course']
        return jsonify({'success': True, 'name': student['name']})
    return jsonify({'error': 'Invalid email or password'})

@app.route('/student-register', methods=['GET','POST'])
def student_register():
    if request.method == 'GET':
        return render_template('student_register.html')
    data     = request.get_json()
    name     = data.get('name','').strip()
    roll_no  = data.get('roll_no','').strip().upper()
    course   = data.get('course','').strip()
    semester = data.get('semester','').strip()
    email    = data.get('email','').strip().lower()
    password = data.get('password','').strip()
    if not all([name, roll_no, course, semester, email, password]):
        return jsonify({'error': 'All fields are required'})
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'})
    try:
        with sqlite3.connect(DB) as conn:
            conn.execute('INSERT INTO students (name,roll_no,course,semester,email,password) VALUES (?,?,?,?,?,?)',
                         (name, roll_no, course, semester, email, password))
            conn.commit()
        return jsonify({'success': True, 'name': name})
    except sqlite3.IntegrityError as e:
        if 'roll_no' in str(e):
            return jsonify({'error': 'Roll number already registered'})
        return jsonify({'error': 'Email already registered'})

@app.route('/student-dashboard')
def student_dashboard():
    if 'name' not in session or session.get('role') != 'student':
        return redirect('/student-login')
    return render_template('student_dashboard.html',
                           name=session['name'],
                           roll_no=session.get('roll_no',''),
                           course=session.get('course',''))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ─────────────────────────────────────────────
#  TEACHER ROUTES
# ─────────────────────────────────────────────
@app.route('/assess')
def assess():
    if 'name' not in session: return redirect('/login')
    return render_template('assess.html', name=session['name'])

@app.route('/answer-evaluator')
def answer_evaluator():
    if 'name' not in session: return redirect('/login')
    return render_template('answer_evaluator.html', name=session['name'])

@app.route('/level-detector')
def level_detector():
    if 'name' not in session: return redirect('/login')
    return render_template('level_detector.html', name=session['name'])

@app.route('/feedback-generator')
def feedback_generator():
    if 'name' not in session: return redirect('/login')
    return render_template('feedback_generator.html', name=session['name'])


# ─────────────────────────────────────────────
#  QUESTION ANALYSER
# ─────────────────────────────────────────────
@app.route('/analyze-question', methods=['POST'])
def analyze_question():
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    subject    = data.get('subject', '')
    exam_type  = data.get('exam_type', 'CA')
    course     = data.get('course', '')
    image_b64  = data.get('image_b64', '')
    media_type = data.get('media_type', 'image/jpeg')
    if not subject:
        return jsonify({'error': 'Subject is required'})
    syllabus_info = ""
    if exam_type == "CA" and subject in CA_SYLLABUS:
        s = CA_SYLLABUS[subject]
        syllabus_info = f"CA Syllabus (Unit 1 & 2 ONLY):\nUnit 1: {s['unit1']}\nUnit 2: {s['unit2']}\nQuestions from other units = OUT OF SYLLABUS."
    raw_text = ''
    if image_b64:
        if media_type == 'application/pdf':
            pages = pdf_to_images(image_b64)
            if pages:
                parts = []
                for i, pg in enumerate(pages):
                    ocr = gemini_vision(f"Read this question paper image carefully (page {i+1}). Extract ALL question text exactly as written. Include question numbers.", pg)
                    parts.append(ocr)
                raw_text = "\n".join(parts)
        else:
            raw_text = gemini_vision("Read this question paper image carefully. Extract ALL question text exactly as written. Include question numbers.", image_b64)
    if not raw_text or raw_text.startswith('[Vision error'):
        raw_text = f"[Question paper for {subject}. Generate 4 standard CA questions.]"
    prompt = f"""You are an expert academic evaluator at IIS University Jaipur.
Subject: {subject} | Course: {course} | Exam: {exam_type}
CA Format: 4 questions, attempt any 3, 5 marks each = 15 marks total.
{syllabus_info}
PAPER TEXT:
{raw_text}
Use EXACT questions from paper text. Only generate if text is empty/unreadable.
For each question: q_no, question_text, bt_level (L1-L6 with name), bt_reason, syllabus_status, difficulty, quality, marks_appropriate, suggestion.
Summary: total_questions, overall_bt_distribution, overall_quality, paper_suggestion.
ONLY JSON:
{{"questions":[{{"q_no":1,"question_text":"...","bt_level":"L2-Understand","bt_reason":"...","syllabus_status":"IN SYLLABUS","difficulty":"Medium","quality":"Good","marks_appropriate":"Yes","suggestion":"..."}}],"summary":{{"total_questions":4,"overall_bt_distribution":{{"L2":3,"L3":1}},"overall_quality":"Good","paper_suggestion":"..."}}}}"""
    try:
        result = parse_json(gemini(prompt, max_tokens=2000))
        saved_ids = []
        with sqlite3.connect(DB) as conn:
            for q in result.get('questions', []):
                cur = conn.execute(
                    'INSERT INTO analyses (course,exam,subject,question_text,bt_level_ai,syllabus_check,difficulty,quality,marks,suggestion) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (course, exam_type, subject, q['question_text'], q['bt_level'], q['syllabus_status'], q['difficulty'], q['quality'], '5' if exam_type == 'CA' else '-', q.get('suggestion', ''))
                )
                saved_ids.append(cur.lastrowid)
            conn.commit()
        for i, q in enumerate(result.get('questions', [])):
            q['db_id'] = saved_ids[i] if i < len(saved_ids) else None
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()})

@app.route('/save-feedback', methods=['POST'])
def save_feedback():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    with sqlite3.connect(DB) as conn:
        conn.execute('INSERT INTO feedback (analysis_id,teacher_name,teacher_bt,teacher_suggestion) VALUES (?,?,?,?)',
                     (data.get('analysis_id', 0), session['name'], data.get('teacher_bt', ''), data.get('teacher_suggestion', '')))
        conn.commit()
    return jsonify({'success': True})

@app.route('/get-questions')
def get_questions():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    subject = request.args.get('subject', '')
    exam    = request.args.get('exam', 'CA')
    course  = request.args.get('course', '')
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        latest = conn.execute('SELECT MAX(created_at) as max_ts FROM analyses WHERE subject=? AND exam=? AND course=?', (subject, exam, course)).fetchone()
        if not latest or not latest['max_ts']:
            return jsonify({'questions': []})
        rows = conn.execute("SELECT id, question_text, marks FROM analyses WHERE subject=? AND exam=? AND course=? AND created_at >= datetime(?, '-5 minutes') ORDER BY id ASC LIMIT 4", (subject, exam, course, latest['max_ts'])).fetchall()
    return jsonify({'questions': [{'id': r['id'], 'text': r['question_text'], 'marks': r['marks']} for r in rows]})

@app.route('/get-subjects')
def get_subjects():
    course = request.args.get('course', '')
    return jsonify(SUBJECTS.get(course, []))

@app.route('/get-saved-analyses')
def get_saved_analyses():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    subject = request.args.get('subject', '')
    exam    = request.args.get('exam', 'CA')
    course  = request.args.get('course', '')
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT id, question_text, bt_level_ai, syllabus_check, marks FROM analyses WHERE subject=? AND exam=? AND course=? ORDER BY created_at DESC LIMIT 4', (subject, exam, course)).fetchall()
    return jsonify({'questions': [dict(r) for r in rows]})

# ─────────────────────────────────────────────
#  PDF SESSION STORE
#  Store converted page images in Flask session
#  so they survive tab switching within same browser
# ─────────────────────────────────────────────

@app.route('/store-pdf-pages', methods=['POST'])
def store_pdf_pages():
    """
    Called once when teacher uploads PDF.
    Converts PDF -> JPEG pages, stores in Flask server-side session.
    Returns page count so frontend knows upload succeeded.
    """
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    try:
        data      = request.get_json()
        pdf_b64   = data.get('pdf_b64', '')
        roll_no   = data.get('roll_no', '').strip()

        if not pdf_b64:
            return jsonify({'error': 'No PDF data received'})

        pages = pdf_to_images(pdf_b64)
        if not pages:
            return jsonify({'error': 'Could not convert PDF. Make sure it is a valid PDF file.'})

        # Store in server session
        if 'pdf_store' not in session:
            session['pdf_store'] = {}
        session['pdf_store'][roll_no] = pages
        session.modified = True

        # Return pages to frontend so browser keeps them in memory
        # This means tab-switching never loses data
        return jsonify({
            'success': True,
            'page_count': len(pages),
            'pages': pages,
            'message': f'PDF loaded: {len(pages)} page(s) ready'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()})


@app.route('/store-image-pages', methods=['POST'])
def store_image_pages():
    """
    Called when teacher uploads images (not PDF) or camera pages.
    Stores pre-converted base64 pages directly in Flask session.
    """
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    try:
        data    = request.get_json()
        pages   = data.get('pages', [])
        roll_no = data.get('roll_no', '').strip()

        if not pages or not roll_no:
            return jsonify({'error': 'No pages or roll number received'})

        # Clean base64 — strip data URI prefix if present
        clean_pages = []
        for p in pages:
            if ',' in p:
                p = p.split(',')[1]
            clean_pages.append(p)

        if 'pdf_store' not in session:
            session['pdf_store'] = {}
        session['pdf_store'][roll_no] = clean_pages
        session.modified = True

        return jsonify({
            'success': True,
            'page_count': len(clean_pages),
            'message': f'{len(clean_pages)} image page(s) loaded for {roll_no}'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()})


@app.route('/clear-pdf-store', methods=['POST'])
def clear_pdf_store():
    """Called when teacher clicks Clear All — removes stored PDFs from session."""
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    session.pop('pdf_store', None)
    session.modified = True
    return jsonify({'success': True})


# ─────────────────────────────────────────────
#  ANSWER EVALUATOR HELPERS
# ─────────────────────────────────────────────

def extract_full_sheet_text_from_pages(pages):
    """
    Given a list of base64 JPEG pages, extract ALL handwritten text
    using vision AI with a detailed prompt that understands IIS copy format.
    Returns (full_text, per_page_texts)
    """
    if not pages:
        return "", []

    per_page = []
    for i, pg in enumerate(pages):
        prompt = (
            f"This is page {i+1} of {len(pages)} of a handwritten student answer sheet "
            f"from IIS University India (IISU CA Exam).\n\n"
            "IMPORTANT FORMAT: In IIS answer copies, each answer starts with a label "
            "on the LEFT MARGIN like 'Ans-1', 'Ans-2', 'Ans 1', 'Ans 2', 'Q1', 'Q2' etc. "
            "The actual answer text is written to the RIGHT of this label.\n\n"
            "Page 1 (cover page) has a printed marks table showing:\n"
            "  - Q.No. 1, 2, 3, 4 in rows\n"
            "  - 'Marks Obtained' row where examiner fills marks\n"
            "  READ THIS TABLE CAREFULLY to find which questions have marks filled.\n\n"
            "YOUR TASK:\n"
            "1. If this is the cover page, extract the marks table data completely\n"
            "2. Find every answer heading (Ans-1, Ans-2, Ans 3, etc.) written on LEFT side\n"
            "3. Extract the complete answer text for each heading\n"
            "4. Note exact spellings of headings as student wrote them\n\n"
            "Return the COMPLETE extracted text preserving all answer headings exactly."
        )
        text = gemini_vision(prompt, pg)
        per_page.append(f"[PAGE {i+1}]:\n{text}")

    full_text = "\n\n".join(per_page)
    return full_text, per_page


def detect_attempted_from_sheet(full_text, per_page_texts, all_questions):
    """
    IMPROVED detection logic:
    1. First checks cover page marks table
    2. Then checks for explicit 'Ans-N' labels in left margin
    3. Then checks for substantial content per answer
    Always enforces CA rule: exactly 3 attempted, 1 not attempted
    """
    q_list = "\n".join([f"Q{i+1}: {q[:120]}" for i, q in enumerate(all_questions)])

    # Build a focused summary of what we found
    cover_page_text = per_page_texts[0] if per_page_texts else ""

    prompt = f"""You are reading a student's IIS University CA exam answer sheet.

CA EXAM STRICT RULES:
- Paper has exactly 4 questions
- Student attempts EXACTLY 3 questions and SKIPS exactly 1
- Student CAN skip ANY question (Q1, Q2, Q3, or Q4)

IIS ANSWER COPY FORMAT:
- Student writes answer labels on the LEFT MARGIN: "Ans-1", "Ans-2", "Ans 3", "Ans-4" etc.
- If a question is NOT attempted, there will be NO such label for that question number
- The cover page has a marks table — read it to confirm which questions have marks

QUESTIONS IN THIS EXAM:
{q_list}

COMPLETE ANSWER SHEET TEXT (all pages):
{full_text[:4000]}

COVER PAGE TEXT:
{cover_page_text[:1500]}

YOUR TASK:
Step 1: Look at the cover page marks table — which Q.No rows have marks written by examiner?
Step 2: Search the full text for answer labels: "Ans-1", "Ans-2", "Ans 3", "Ans-4", "Ans 1", "Ans 2" etc.
Step 3: For each found label, extract the answer text that follows it (until the next label or page end)
Step 4: The question with NO label = not attempted. Exactly 1 question must be not attempted.

CRITICAL: If you find labels for Q1, Q2, Q4 but NOT Q3 — then attempted=[1,2,4], not_attempted=[3]
If you find labels for Q1, Q2, Q3 but NOT Q4 — then attempted=[1,2,3], not_attempted=[4]

Return ONLY valid JSON (no extra text):
{{
  "attempted": [1, 2, 4],
  "not_attempted": [3],
  "answers": {{
    "1": "full answer text for Q1",
    "2": "full answer text for Q2",
    "4": "full answer text for Q4"
  }},
  "cover_page_marks": {{"Q1": "5", "Q2": "4", "Q3": "0", "Q4": "4"}},
  "detection_method": "ans_labels_found",
  "confidence": "High",
  "labels_found": ["Ans-1", "Ans-2", "Ans-4"],
  "note": "Q3 label not found in any page"
}}"""

    try:
        result = parse_json(gemini(prompt, max_tokens=2500))

        attempted     = [int(x) for x in result.get('attempted', [])]
        not_attempted = [int(x) for x in result.get('not_attempted', [])]
        answers_map   = {str(k): v for k, v in result.get('answers', {}).items()}

        print(f"[Detection] Attempted: {attempted}, Not Attempted: {not_attempted}")
        print(f"[Detection] Method: {result.get('detection_method')}, Confidence: {result.get('confidence')}")
        print(f"[Detection] Labels found: {result.get('labels_found', [])}")

        # Enforce CA rule: exactly 3 attempted
        # If detection gave more than 3, keep only those with actual answer content
        if len(attempted) > 3:
            # Keep only 3 with longest answers
            scored = [(q, len(answers_map.get(str(q), ''))) for q in attempted]
            scored.sort(key=lambda x: x[1], reverse=True)
            attempted = [q for q, _ in scored[:3]]

        # If fewer than 3, fill from not_attempted (least likely skipped)
        if len(attempted) < 3:
            for q in [1, 2, 3, 4]:
                if q not in attempted and len(attempted) < 3:
                    attempted.append(q)

        attempted.sort()
        not_attempted = [q for q in [1, 2, 3, 4] if q not in attempted]

        return attempted, not_attempted, answers_map

    except Exception as e:
        print(f"[detect_attempted_from_sheet error]: {e}")
        # Safe fallback: Q1,Q2,Q3 attempted, Q4 not (most common pattern)
        return [1, 2, 3], [4], {}


def extract_specific_answer(pages, q_number, full_text, answers_map):
    """
    Extract the specific answer for question q_number.
    Uses the pre-extracted answers_map first, then falls back to
    targeted page-by-page vision search.
    """
    # Try from answers_map first
    if str(q_number) in answers_map and len(answers_map[str(q_number)].strip()) > 30:
        return answers_map[str(q_number)]

    # Targeted search across all pages
    all_texts = []
    for i, pg in enumerate(pages):
        prompt = (
            f"Search this handwritten answer sheet page for the answer to Question {q_number}.\n"
            f"Look for the label 'Ans-{q_number}', 'Ans {q_number}', 'Q{q_number}' on the LEFT MARGIN.\n"
            f"If found, extract ALL the answer text written after this label.\n"
            f"If NOT found on this page, reply: NOT_ON_THIS_PAGE\n"
            f"Return only the answer text, nothing else."
        )
        text = gemini_vision(prompt, pg)
        if 'NOT_ON_THIS_PAGE' not in text and len(text.strip()) > 20:
            all_texts.append(text.strip())

    if all_texts:
        return "\n".join(all_texts)

    # Last resort: use the chunk of full_text near this question's label
    label_patterns = [f'ans-{q_number}', f'ans {q_number}', f'ans.{q_number}', f'q{q_number}']
    lower_text = full_text.lower()
    for pat in label_patterns:
        idx = lower_text.find(pat)
        if idx != -1:
            # Extract up to 1000 chars after the label
            return full_text[idx:idx+1000].strip()

    return '[Answer not clearly readable in the uploaded sheet]'


def save_zero_marks(roll_no, student_name, exam, course, subject, q_number, question, max_marks, teacher_name):
    """Save a not-attempted question with 0 marks."""
    try:
        with sqlite3.connect(DB) as conn:
            existing = conn.execute(
                'SELECT id FROM evaluations WHERE roll_no=? AND subject=? AND q_number=?',
                (roll_no, subject, q_number)
            ).fetchone()
            if existing:
                conn.execute(
                    '''UPDATE evaluations SET student_name=?,answer_text=?,keyword_score=?,
                       semantic_score=?,final_score=?,max_marks=?,final_marks=?,grade=?,
                       performance=?,ai_feedback=?,teacher_name=?,improvement_tips=?
                       WHERE id=?''',
                    (student_name, '[Not Attempted]', 0, 0, 0, max_marks, 0,
                     'F', 'Not Attempted',
                     'Student did not attempt this question. Zero marks awarded.',
                     teacher_name, json.dumps(['Attempt all required questions in the exam.']),
                     existing[0])
                )
                conn.commit()
                return existing[0]
            else:
                cur = conn.execute(
                    '''INSERT INTO evaluations
                       (roll_no,student_name,exam,course,subject,q_number,question_text,
                        answer_text,keyword_score,semantic_score,final_score,max_marks,
                        final_marks,grade,performance,ai_feedback,teacher_name,improvement_tips)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (roll_no, student_name, exam, course, subject, q_number, question,
                     '[Not Attempted]', 0, 0, 0, max_marks, 0, 'F', 'Not Attempted',
                     'Student did not attempt this question. Zero marks awarded.',
                     teacher_name, json.dumps(['Attempt all required questions in the exam.']))
                )
                conn.commit()
                return cur.lastrowid
    except Exception as e:
        print(f"[save_zero_marks error]: {e}")
        return None


def evaluate_single_answer(question, answer_text, subject, exam, max_marks):
    """
    Multi-agent evaluation with robust JSON handling.
    Each agent prompt explicitly forbids special characters.
    """
    import json

    SAFE_PROMPT_SUFFIX = "\nIMPORTANT: Your JSON response must NOT contain any special/control characters. Use only standard ASCII in your JSON keys and values. Do not include raw newlines inside string values — use \\n instead."

    # Agent 1 — Keyword Extractor
    try:
        raw1 = gemini(f"""You are Agent 1 — Keyword Extraction Agent.
Subject: {subject} | Exam: {exam} | Max Marks: {max_marks}
Question: {question}
Respond ONLY with valid JSON, no markdown, no explanation.{SAFE_PROMPT_SUFFIX}
{{"must_have_keywords":["keyword1","keyword2"],"good_to_have_keywords":["keyword3"],"expected_answer_points":["point1","point2"]}}""", 600)
        agent1 = parse_json(raw1)
    except Exception as e:
        return None, None, None, None, f"Agent 1 failed: {str(e)}"

    # Agent 2 — Keyword Matcher
    try:
        raw2 = gemini(f"""You are Agent 2 — Keyword Matching Agent.
Question: {question}
Student Answer: {answer_text[:1500]}
Must-Have Keywords: {json.dumps(agent1.get('must_have_keywords', []))}
Good-to-Have Keywords: {json.dumps(agent1.get('good_to_have_keywords', []))}
Respond ONLY with valid JSON, no markdown, no explanation.{SAFE_PROMPT_SUFFIX}
{{"must_have_found":["kw1"],"must_have_missing":["kw2"],"good_to_have_found":[],"keyword_coverage_percent":70,"keyword_score_out_of_10":7.0,"keyword_reasoning":"brief reason"}}""", 600)
        agent2 = parse_json(raw2)
    except Exception as e:
        return agent1, None, None, None, f"Agent 2 failed: {str(e)}"

    # Agent 3 — Semantic Evaluator
    try:
        raw3 = gemini(f"""You are Agent 3 — Semantic Evaluation Agent.
Subject: {subject} | Max Marks: {max_marks}
Question: {question}
Student Answer: {answer_text[:1500]}
Expected Points: {json.dumps(agent1.get('expected_answer_points', []))}
Respond ONLY with valid JSON, no markdown, no explanation.{SAFE_PROMPT_SUFFIX}
{{"understanding_level":"Good","completeness":"Partial","accuracy":"Medium","depth":"Shallow","semantic_score_out_of_10":6.5,"strengths":["strength1"],"weaknesses":["weakness1"],"semantic_reasoning":"brief reason"}}""", 600)
        agent3 = parse_json(raw3)
    except Exception as e:
        return agent1, agent2, None, None, f"Agent 3 failed: {str(e)}"

    # Orchestrator
    try:
        kw_score    = round(float(agent2.get('keyword_score_out_of_10', 5)), 1)
        sem_score   = round(float(agent3.get('semantic_score_out_of_10', 5)), 1)
        final_10    = round((0.6 * kw_score) + (0.4 * sem_score), 1)
        final_marks = round((final_10 / 10) * max_marks, 1)

        raw_orch = gemini(f"""You are the Orchestrator — Final Judge.
Subject: {subject} | Max Marks: {max_marks}
Question: {question}
KW Score: {kw_score}/10 | Semantic: {sem_score}/10 | Final: {final_marks}/{max_marks}
Respond ONLY with valid JSON, no markdown, no explanation.{SAFE_PROMPT_SUFFIX}
{{"grade":"B","performance":"Average","model_answer_hints":["hint1"],"improvement_tips":["tip1","tip2"],"final_feedback":"2-3 sentence feedback."}}""", 600)
        orch = parse_json(raw_orch)
        return agent1, agent2, agent3, (orch, kw_score, sem_score, final_10, final_marks), None
    except Exception as e:
        return agent1, agent2, agent3, None, f"Orchestrator failed: {str(e)}"


# ─────────────────────────────────────────────
#  ANSWER EVALUATOR MAIN ROUTE
# ─────────────────────────────────────────────
@app.route('/evaluate-answer', methods=['POST'])
def evaluate_answer():
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'})

        roll_no              = data.get('roll_no', '').strip()
        student_name         = data.get('student_name', '').strip()
        question             = data.get('question', '').strip()
        subject              = data.get('subject', '')
        course               = data.get('course', '')
        exam                 = data.get('exam', 'CA')
        max_marks            = int(data.get('max_marks', 5))
        q_number             = int(data.get('q_number', 1))
        all_questions        = data.get('all_questions', [])
        force_not_attempted  = data.get('force_not_attempted', False)
        # Teacher explicitly marks which questions were attempted
        teacher_att  = [int(x) for x in data.get('attempted_questions', [])]
        teacher_natt = [int(x) for x in data.get('not_attempted_questions', [])]

        if not question:
            return jsonify({'error': 'Question is required'})
        if not roll_no or not student_name:
            return jsonify({'error': 'Roll number and student name are required'})

        # ── FORCE NOT ATTEMPTED (teacher marked this Q as not done) ──
        if force_not_attempted or (teacher_natt and q_number in teacher_natt):
            eval_id = save_zero_marks(
                roll_no, student_name, exam, course, subject,
                q_number, question, max_marks, session.get('name', '')
            )
            return jsonify({
                'success': True, 'not_attempted': True, 'eval_id': eval_id,
                'answer_text': '[Not Attempted]',
                'scores': {'keyword_score':0,'semantic_score':0,'final_score_10':0,'final_marks':0,'max_marks':max_marks},
                'agent2': {'must_have_found':[],'must_have_missing':[]},
                'agent3': {'understanding_level':'Not Attempted','depth':'None'},
                'orchestrator': {'grade':'F','performance':'Not Attempted','final_feedback':'Student did not attempt this question.'},
                'attempted_questions': teacher_att, 'not_attempted_questions': teacher_natt
            })

        # ── GET PAGES FROM SERVER SESSION ──
        pdf_store = session.get('pdf_store', {})
        pages = pdf_store.get(roll_no, [])

        if not pages:
            return jsonify({'error': 'No answer sheet found. Please upload the PDF again.'})

        print(f"[evaluate-answer] Student: {roll_no}, Q: {q_number}, Pages: {len(pages)}")

        # ── EXTRACT ALL TEXT FROM SHEET ──
        full_text, per_page_texts = extract_full_sheet_text_from_pages(pages)

        # ── USE TEACHER-PROVIDED ATTEMPT LIST (no AI guessing) ──
        if teacher_att:
            attempted     = teacher_att
            not_attempted = teacher_natt
            # Still extract answer text for this specific question
            answers_map   = {}
        else:
            questions_list = all_questions if all_questions else [question]
            attempted, not_attempted, answers_map = detect_attempted_from_sheet(
                full_text, per_page_texts, questions_list
            )

        print(f"[Detection] Attempted: {attempted}, Not Attempted: {not_attempted}")

        # ── HANDLE NOT ATTEMPTED ──
        if q_number in not_attempted:
            eval_id = save_zero_marks(
                roll_no, student_name, exam, course, subject,
                q_number, question, max_marks, session.get('name', '')
            )
            return jsonify({
                'success': True,
                'not_attempted': True,
                'eval_id': eval_id,
                'answer_text': '[Not Attempted]',
                'scores': {
                    'keyword_score': 0, 'semantic_score': 0,
                    'final_score_10': 0, 'final_marks': 0, 'max_marks': max_marks
                },
                'agent1': {'must_have_keywords': [], 'good_to_have_keywords': [], 'expected_answer_points': []},
                'agent2': {'must_have_found': [], 'must_have_missing': [], 'keyword_coverage_percent': 0, 'keyword_score_out_of_10': 0, 'keyword_reasoning': 'Not attempted'},
                'agent3': {'understanding_level': 'Not Attempted', 'depth': 'None', 'semantic_score_out_of_10': 0, 'strengths': [], 'weaknesses': ['Question not attempted']},
                'orchestrator': {'grade': 'F', 'performance': 'Not Attempted', 'model_answer_hints': [], 'improvement_tips': ['Attempt all required questions'], 'final_feedback': 'Student did not attempt this question. Zero marks awarded.'},
                'attempted_questions': attempted,
                'not_attempted_questions': not_attempted
            })

        # ── EXTRACT SPECIFIC ANSWER FOR THIS QUESTION ──
        answer_text = extract_specific_answer(pages, q_number, full_text, answers_map)

        if not answer_text or len(answer_text.strip()) < 10:
            answer_text = '[Answer not clearly readable in the uploaded sheet]'

        # ── RUN 4-AGENT EVALUATION PIPELINE ──
        agent1, agent2, agent3, orch_result, err = evaluate_single_answer(
            question, answer_text, subject, exam, max_marks
        )

        if err:
            return jsonify({'error': f'Evaluation pipeline failed: {err}'})

        orch, kw_score, sem_score, final_10, final_marks = orch_result

        # ── SAVE TO DATABASE ──
        eval_id = None
        try:
            with sqlite3.connect(DB) as conn:
                existing = conn.execute(
                    'SELECT id FROM evaluations WHERE roll_no=? AND subject=? AND q_number=?',
                    (roll_no, subject, q_number)
                ).fetchone()

                if existing:
                    conn.execute(
                        '''UPDATE evaluations SET student_name=?,answer_text=?,
                           keyword_score=?,semantic_score=?,final_score=?,max_marks=?,
                           final_marks=?,grade=?,performance=?,ai_feedback=?,
                           teacher_name=?,improvement_tips=? WHERE id=?''',
                        (student_name, answer_text, kw_score, sem_score, final_10,
                         max_marks, final_marks, orch.get('grade', ''),
                         orch.get('performance', ''), orch.get('final_feedback', ''),
                         session.get('name', ''), json.dumps(orch.get('improvement_tips', [])),
                         existing[0])
                    )
                    eval_id = existing[0]
                else:
                    cur = conn.execute(
                        '''INSERT INTO evaluations
                           (roll_no,student_name,exam,course,subject,q_number,
                            question_text,answer_text,keyword_score,semantic_score,
                            final_score,max_marks,final_marks,grade,performance,
                            ai_feedback,teacher_name,improvement_tips)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (roll_no, student_name, exam, course, subject, q_number,
                         question, answer_text, kw_score, sem_score, final_10,
                         max_marks, final_marks, orch.get('grade', ''),
                         orch.get('performance', ''), orch.get('final_feedback', ''),
                         session.get('name', ''), json.dumps(orch.get('improvement_tips', [])))
                    )
                    eval_id = cur.lastrowid
                conn.commit()
        except Exception as e:
            print(f"[DB save error]: {e}")

        return jsonify({
            'success': True,
            'eval_id': eval_id,
            'answer_text': answer_text,
            'scores': {
                'keyword_score': kw_score, 'semantic_score': sem_score,
                'final_score_10': final_10, 'final_marks': final_marks,
                'max_marks': max_marks
            },
            'agent1': agent1, 'agent2': agent2, 'agent3': agent3,
            'orchestrator': orch,
            'attempted_questions': attempted,
            'not_attempted_questions': not_attempted
        })

    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()})


# ─────────────────────────────────────────────
#  GET / SAVE EVALUATION DATA
# ─────────────────────────────────────────────
@app.route('/get-evaluations')
def get_evaluations():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    exam    = request.args.get('exam', 'CA')
    course  = request.args.get('course', '')
    subject = request.args.get('subject', '')
    query   = '''SELECT roll_no, student_name, exam, course, subject,
               ROUND(SUM(final_marks),1) as final_marks, 15 as max_marks
               FROM evaluations WHERE exam=?'''
    params  = [exam]
    if course:  query += ' AND course=?';   params.append(course)
    if subject: query += ' AND subject=?';  params.append(subject)
    query += ' GROUP BY roll_no, student_name ORDER BY roll_no'
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return jsonify({'evaluations': [dict(r) for r in rows]})


@app.route('/save-eval-feedback', methods=['POST'])
def save_eval_feedback():
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data          = request.get_json()
    eval_id       = data.get('eval_id')
    teacher_marks = data.get('teacher_marks', 0)
    teacher_fb    = data.get('teacher_feedback', '').strip()

    if not teacher_fb:
        return jsonify({'error': 'Feedback text is required'}), 400

    if not eval_id:
        return jsonify({'success': True, 'note': 'eval_id missing, saved locally only'})

    try:
        with sqlite3.connect(DB) as conn:
            conn.execute(
                'UPDATE evaluations SET teacher_marks=?, teacher_feedback=?, teacher_name=? WHERE id=?',
                (teacher_marks, teacher_fb, session['name'], eval_id)
            )
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/get-level-data')
def get_level_data():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    role    = session.get('role', 'teacher')
    roll_no = session.get('roll_no', '')
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        if role == 'student' and roll_no:
            rows = conn.execute(
                '''SELECT roll_no, student_name, exam, course, subject,
                          ROUND(SUM(final_marks), 1) as total_marks, COUNT(*) as q_count
                   FROM (SELECT roll_no, student_name, exam, course, subject,
                                q_number, final_marks,
                                ROW_NUMBER() OVER (PARTITION BY roll_no, subject, q_number ORDER BY id DESC) as rn
                         FROM evaluations WHERE roll_no=?)
                   WHERE rn = 1
                   GROUP BY roll_no, student_name, subject
                   ORDER BY subject''',
                (roll_no,)
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT roll_no, student_name, exam, course, subject,
                          ROUND(SUM(final_marks), 1) as total_marks, COUNT(*) as q_count
                   FROM (SELECT roll_no, student_name, exam, course, subject,
                                q_number, final_marks,
                                ROW_NUMBER() OVER (PARTITION BY roll_no, subject, q_number ORDER BY id DESC) as rn
                         FROM evaluations)
                   WHERE rn = 1
                   GROUP BY roll_no, student_name, subject
                   ORDER BY roll_no, subject'''
            ).fetchall()
    result = []
    for r in rows:
        tm = min(float(r['total_marks'] or 0), 15.0)
        result.append({
            'roll_no': r['roll_no'], 'student_name': r['student_name'],
            'exam': r['exam'], 'course': r['course'], 'subject': r['subject'],
            'final_marks': tm, 'max_marks': 15, 'q_count': r['q_count']
        })
    return jsonify({'rows': result})


@app.route('/get-feedback-report')
def get_feedback_report():
    if 'name' not in session: return jsonify({'error': 'Not logged in'}), 401
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''SELECT roll_no, student_name, subject, exam, course,
                      ai_feedback, teacher_feedback, improvement_tips, performance, final_marks
               FROM (SELECT roll_no, student_name, subject, exam, course,
                            q_number, ai_feedback, teacher_feedback, improvement_tips,
                            performance, final_marks,
                            ROW_NUMBER() OVER (PARTITION BY roll_no, subject, q_number ORDER BY id DESC) as rn
                     FROM evaluations)
               WHERE rn = 1
               ORDER BY roll_no, subject, q_number'''
        ).fetchall()
    grouped = {}
    for r in rows:
        key = (r['roll_no'], r['student_name'], r['subject'])
        if key not in grouped:
            grouped[key] = {'roll_no':r['roll_no'],'student_name':r['student_name'],'subject':r['subject'],'exam':r['exam'],'ai_feedbacks':[],'teacher_feedbacks':[],'all_tips':[],'performances':[],'total_marks':0.0}
        g = grouped[key]
        g['total_marks'] = round(g['total_marks'] + float(r['final_marks'] or 0), 1)
        if r['ai_feedback'] and r['ai_feedback'] != 'Student did not attempt this question. Zero marks awarded.':
            g['ai_feedbacks'].append(r['ai_feedback'])
        if r['teacher_feedback'] and str(r['teacher_feedback']).strip():
            g['teacher_feedbacks'].append(r['teacher_feedback'])
        if r['performance'] and r['performance'] != 'Not Attempted':
            g['performances'].append(r['performance'])
        try:
            tips = json.loads(r['improvement_tips'] or '[]')
            if isinstance(tips, list):
                g['all_tips'].extend([t for t in tips if t and t != 'Attempt all required questions.'])
        except Exception:
            pass
    result = []
    perf_order = ['Excellent','Good','Average','Below Average','Poor']
    for key, g in grouped.items():
        best_perf = '—'
        for p in perf_order:
            if p in g['performances']:
                best_perf = p; break
        seen = set(); unique_tips = []
        for t in g['all_tips']:
            if t not in seen: seen.add(t); unique_tips.append(t)
        tm = min(g['total_marks'], 15.0)
        result.append({
            'roll_no':g['roll_no'],'student_name':g['student_name'],'subject':g['subject'],'exam':g['exam'],'total_marks':tm,
            'performance':best_perf,'ai_feedback':' '.join(g['ai_feedbacks'][:2]) if g['ai_feedbacks'] else '—',
            'teacher_feedback':'; '.join(g['teacher_feedbacks']) if g['teacher_feedbacks'] else '',
            'improvement_tips':unique_tips[:4]
        })
    return jsonify({'rows': result})


@app.route('/save-feedback-generator', methods=['POST'])
def save_feedback_generator():
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    try:
        data         = request.get_json()
        roll_no      = data.get('roll_no', '').strip()
        fb_text      = data.get('teacher_feedback', '').strip()
        if not fb_text:
            return jsonify({'error': 'Feedback text is required'}), 400
        with sqlite3.connect(DB) as conn:
            conn.execute(
                'UPDATE evaluations SET teacher_feedback=?, teacher_name=? WHERE roll_no=?',
                (fb_text, session.get('name', ''), roll_no)
            )
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()})


# ─────────────────────────────────────────────
#  EXCEL DOWNLOADS
# ─────────────────────────────────────────────
@app.route('/download-excel')
def download_excel():
    if 'name' not in session: return redirect('/login')
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from io import BytesIO
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Assessment Report"
        hdr_font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        hdr_fill = PatternFill("solid", fgColor="8B1A1A")
        thin = Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
        headers = ["Q.No","Question","BT Level","Syllabus","Teacher Feedback"]; widths = [6,70,18,16,45]
        for ci,(h,w) in enumerate(zip(headers,widths),1):
            cell = ws.cell(row=1,column=ci,value=h)
            cell.font=hdr_font; cell.fill=hdr_fill
            cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
            cell.border=thin; ws.column_dimensions[cell.column_letter].width=w
        ws.row_dimensions[1].height=30
        with sqlite3.connect(DB) as conn:
            conn.row_factory=sqlite3.Row
            rows=conn.execute('SELECT a.*,f.teacher_bt,f.teacher_suggestion FROM analyses a LEFT JOIN feedback f ON f.analysis_id=a.id ORDER BY a.created_at DESC').fetchall()
        for ri,row in enumerate(rows,2):
            fill=PatternFill("solid",fgColor="F5F0E8") if ri%2==0 else PatternFill("solid",fgColor="FAF9F6")
            tf=(row['teacher_bt'] or '')
            if row['teacher_suggestion']: tf+=(' — ' if tf else '')+row['teacher_suggestion']
            vals=['Q.'+str(ri-1),row['question_text'],row['bt_level_ai'],row['syllabus_check'],tf or '—']
            for ci,val in enumerate(vals,1):
                cell=ws.cell(row=ri,column=ci,value=val)
                cell.font=Font(name="Calibri",size=10); cell.fill=fill
                cell.alignment=Alignment(wrap_text=True,vertical="top"); cell.border=thin
        output=BytesIO(); wb.save(output); output.seek(0)
        return send_file(output,as_attachment=True,download_name='IIS_EduGrade_Assessment.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return jsonify({'error':str(e),'trace':traceback.format_exc()})


@app.route('/download-eval-excel')
def download_eval_excel():
    if 'name' not in session: return redirect('/login')
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from io import BytesIO
        wb=openpyxl.Workbook(); ws=wb.active; ws.title="Student Evaluations"
        hdr_font=Font(bold=True,color="FFFFFF",name="Calibri",size=11)
        hdr_fill=PatternFill("solid",fgColor="8B1A1A")
        thin=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
        headers=["#","Roll No","Student Name","Course","Subject","Exam","Q No","AI Marks","Max Marks","Grade","Performance","Teacher Marks","Teacher Feedback","Date"]
        widths=[4,12,20,22,25,8,6,10,10,8,15,14,40,18]
        for ci,(h,w) in enumerate(zip(headers,widths),1):
            cell=ws.cell(row=1,column=ci,value=h)
            cell.font=hdr_font; cell.fill=hdr_fill
            cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
            cell.border=thin; ws.column_dimensions[cell.column_letter].width=w
        ws.row_dimensions[1].height=30
        with sqlite3.connect(DB) as conn:
            conn.row_factory=sqlite3.Row
            rows=conn.execute('SELECT * FROM evaluations ORDER BY roll_no,subject,q_number').fetchall()
        for ri,row in enumerate(rows,2):
            fill=PatternFill("solid",fgColor="F5F0E8") if ri%2==0 else PatternFill("solid",fgColor="FAF9F6")
            vals=[ri-1,row['roll_no'],row['student_name'],row['course'],row['subject'],row['exam'],
                  row['q_number'] or '—',row['final_marks'],row['max_marks'],row['grade'],row['performance'],
                  row['teacher_marks'] or '—',row['teacher_feedback'] or '—',str(row['created_at'])[:16]]
            for ci,val in enumerate(vals,1):
                cell=ws.cell(row=ri,column=ci,value=val)
                cell.font=Font(name="Calibri",size=10); cell.fill=fill
                cell.alignment=Alignment(wrap_text=True,vertical="top"); cell.border=thin
        output=BytesIO(); wb.save(output); output.seek(0)
        return send_file(output,as_attachment=True,download_name='IIS_EduGrade_Student_Evaluations.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return jsonify({'error':str(e)})


@app.route('/download-level-excel')
def download_level_excel():
    if 'name' not in session: return redirect('/login')
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from io import BytesIO
        def to_co(fm,mm):
            if not mm: return 0
            pct=(fm/mm)*100
            if pct==0: return 0
            if pct<=20: return 1
            if pct<=40: return 2
            if pct<=60: return 3
            if pct<=80: return 4
            return 5
        with sqlite3.connect(DB) as conn:
            conn.row_factory=sqlite3.Row
            rows=conn.execute(
                '''SELECT roll_no,student_name,exam,subject,ROUND(SUM(final_marks),1) as total_marks
                   FROM (SELECT roll_no,student_name,exam,subject,q_number,final_marks,
                                ROW_NUMBER() OVER (PARTITION BY roll_no,subject,q_number ORDER BY id DESC) as rn
                         FROM evaluations)
                   WHERE rn=1
                   GROUP BY roll_no,student_name,subject
                   ORDER BY roll_no'''
            ).fetchall()
        wb=openpyxl.Workbook(); ws=wb.active; ws.title="CO Attainment Report"
        hdr_font=Font(bold=True,color="FFFFFF",name="Calibri",size=11)
        hdr_fill=PatternFill("solid",fgColor="8B1A1A")
        thin=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
        headers=["#","Roll No","Student Name","Exam","Subject","Marks Obtained (out of 15)","CO Attained (0-5)","College Target (0-5)","Status"]
        widths=[4,14,22,8,28,22,20,20,16]
        for ci,(h,w) in enumerate(zip(headers,widths),1):
            cell=ws.cell(row=1,column=ci,value=h)
            cell.font=hdr_font; cell.fill=hdr_fill
            cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
            cell.border=thin; ws.column_dimensions[cell.column_letter].width=w
        ws.row_dimensions[1].height=28
        for ri,row in enumerate(rows,2):
            fm=min(float(row['total_marks'] or 0),15.0)
            pct=round((fm/15)*100)
            co=to_co(fm,15)
            status='Target Met' if co>=3 else 'Below Target'
            fill=PatternFill("solid",fgColor="F5F0E8") if ri%2==0 else PatternFill("solid",fgColor="FAF9F6")
            vals=[ri-1,row['roll_no'],row['student_name'],row['exam'],row['subject'],f"{fm}/15 ({pct}%)",f"{co}/5","3/5",status]
            for ci,val in enumerate(vals,1):
                cell=ws.cell(row=ri,column=ci,value=val)
                cell.font=Font(name="Calibri",size=10); cell.fill=fill
                cell.alignment=Alignment(wrap_text=True,vertical="top"); cell.border=thin
        output=BytesIO(); wb.save(output); output.seek(0)
        return send_file(output,as_attachment=True,download_name='IIS_CO_Attainment.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return jsonify({'error':str(e)})


@app.route('/download-feedback-excel')
def download_feedback_excel():
    if 'name' not in session: return redirect('/login')
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from io import BytesIO
        with sqlite3.connect(DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''SELECT roll_no, student_name, subject, exam, course,
                          ai_feedback, teacher_feedback, improvement_tips,
                          performance, final_marks
                   FROM (SELECT roll_no, student_name, subject, exam, course,
                                q_number, ai_feedback, teacher_feedback,
                                improvement_tips, performance, final_marks,
                                ROW_NUMBER() OVER (PARTITION BY roll_no, subject, q_number ORDER BY id DESC) as rn
                         FROM evaluations)
                   WHERE rn = 1
                   ORDER BY roll_no, subject, q_number'''
            ).fetchall()
        grouped = {}
        for r in rows:
            key = (r['roll_no'], r['student_name'], r['subject'])
            if key not in grouped:
                grouped[key] = {'roll_no':r['roll_no'],'student_name':r['student_name'],'subject':r['subject'],'exam':r['exam'],'ai_feedbacks':[],'teacher_feedbacks':[],'all_tips':[],'performances':[],'total_marks':0.0}
            g = grouped[key]
            g['total_marks'] = round(g['total_marks'] + float(r['final_marks'] or 0), 1)
            if r['ai_feedback'] and r['ai_feedback'] != 'Student did not attempt this question. Zero marks awarded.':
                g['ai_feedbacks'].append(r['ai_feedback'])
            if r['teacher_feedback'] and str(r['teacher_feedback']).strip():
                g['teacher_feedbacks'].append(r['teacher_feedback'])
            if r['performance'] and r['performance'] != 'Not Attempted':
                g['performances'].append(r['performance'])
            try:
                tips = json.loads(r['improvement_tips'] or '[]')
                if isinstance(tips, list):
                    g['all_tips'].extend([t for t in tips if t])
            except Exception:
                pass
        perf_order = ['Excellent','Good','Average','Below Average','Poor']
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Feedback Report"
        hdr_font=Font(bold=True,color="FFFFFF",name="Calibri",size=11)
        hdr_fill=PatternFill("solid",fgColor="8B1A1A")
        thin=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
        headers=["#","Roll No.","Student Name","Subject","Exam","Total Marks (/15)","Performance","AI Feedback","Teacher Feedback","Improvement Tips"]
        widths=[4,13,22,28,8,16,16,50,40,55]
        for ci,(h,w) in enumerate(zip(headers,widths),1):
            cell=ws.cell(row=1,column=ci,value=h)
            cell.font=hdr_font; cell.fill=hdr_fill
            cell.alignment=Alignment(horizontal="center",vertical="center",wrap_text=True)
            cell.border=thin; ws.column_dimensions[cell.column_letter].width=w
        ws.row_dimensions[1].height=30
        ri = 2
        for idx,(key,g) in enumerate(grouped.items(),1):
            tm=min(g['total_marks'],15.0)
            best_perf='—'
            for p in perf_order:
                if p in g['performances']: best_perf=p; break
            ai_fb=' | '.join(g['ai_feedbacks'][:2]) if g['ai_feedbacks'] else '—'
            tf='; '.join(g['teacher_feedbacks']) if g['teacher_feedbacks'] else '—'
            seen=set(); unique_tips=[]
            for t in g['all_tips']:
                if t not in seen: seen.add(t); unique_tips.append(t)
            tips_str='\n'.join([f"{i+1}. {t}" for i,t in enumerate(unique_tips[:4])])
            row_fill=PatternFill("solid",fgColor="F5F0E8") if idx%2==0 else PatternFill("solid",fgColor="FAF9F6")
            vals=[idx,g['roll_no'],g['student_name'],g['subject'],g['exam'],f"{tm}/15",best_perf,ai_fb,tf,tips_str or '—']
            for ci,val in enumerate(vals,1):
                cell=ws.cell(row=ri,column=ci,value=val)
                cell.font=Font(name="Calibri",size=10); cell.fill=row_fill
                cell.alignment=Alignment(wrap_text=True,vertical="top"); cell.border=thin
            ws.row_dimensions[ri].height=max(40,len(tips_str)//3)
            ri+=1
        output=BytesIO(); wb.save(output); output.seek(0)
        return send_file(output,as_attachment=True,download_name='IIS_EduGrade_Feedback_Report.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return jsonify({'error':str(e),'trace':traceback.format_exc()})

import smtplib, secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# ── Gmail config — yahan apni details daalo ──
SMTP_EMAIL    = "your_gmail@gmail.com"      # apna Gmail
SMTP_PASSWORD = "your_app_password"         # Gmail App Password (not regular password)
APP_URL       = "http://127.0.0.1:5000"

def send_reset_email(to_email, name, token):
    link = f"{APP_URL}/reset-password/{token}"
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "IIS EduGrade AI — Password Reset"
    msg['From']    = SMTP_EMAIL
    msg['To']      = to_email
    html = f"""<html><body style="font-family:sans-serif;background:#faf9f6;padding:2rem">
    <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:2rem;border:1px solid #e8e4dc">
      <h2 style="color:#8B1A1A;font-family:serif">IIS EduGrade AI</h2>
      <p>Hi <strong>{name}</strong>,</p>
      <p>We received a password reset request for your account. Click the button below to reset your password. This link is valid for <strong>1 hour</strong>.</p>
      <a href="{link}" style="display:inline-block;margin:1rem 0;padding:0.75rem 1.5rem;background:#8B1A1A;color:#fff;border-radius:8px;text-decoration:none;font-weight:700">
        Reset My Password
      </a>
      <p style="font-size:0.82rem;color:#7a7268">If you didn't request this, ignore this email. Your password won't change.</p>
      <hr style="border:none;border-top:1px solid #e8e4dc;margin:1rem 0"/>
      <p style="font-size:0.72rem;color:#7a7268">IIS EduGrade AI — IIS University, Jaipur</p>
    </div></body></html>"""
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(SMTP_EMAIL, SMTP_PASSWORD)
        s.sendmail(SMTP_EMAIL, to_email, msg.as_string())

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json()
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'Email required'})
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute('SELECT name FROM users WHERE email=?', (email,)).fetchone()
    if not user:
        return jsonify({'error': 'No account found with this email address'})
    token   = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS password_resets
                       (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT, token TEXT, expires TEXT, used INTEGER DEFAULT 0)''')
        conn.execute('DELETE FROM password_resets WHERE email=?', (email,))
        conn.execute('INSERT INTO password_resets (email,token,expires) VALUES (?,?,?)',
                     (email, token, expires))
        conn.commit()
    try:
        send_reset_email(email, user['name'], token)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Email sending failed: {str(e)}. Check SMTP credentials in app.py.'})

@app.route('/reset-password/<token>')
def reset_password_page(token):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute('SELECT email,expires,used FROM password_resets WHERE token=?',
                         (token,)).fetchone()
    if not r or r['used'] or datetime.now() > datetime.fromisoformat(r['expires']):
        return render_template('reset_password.html', token=token, expired=True)
    return render_template('reset_password.html', token=token, expired=False)

@app.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email','').strip().lower()
    new_password = data.get('new_password','').strip()
    role = data.get('role','teacher')
    if not email or not new_password or len(new_password) < 6:
        return jsonify({'error': 'Valid email and password (min 6 chars) required'})
    table = 'students' if role == 'student' else 'users'
    with sqlite3.connect(DB) as conn:
        existing = conn.execute(f'SELECT id FROM {table} WHERE email=?', (email,)).fetchone()
        if not existing:
            return jsonify({'error': 'Email not found. Please check and try again.'})
        conn.execute(f'UPDATE {table} SET password=? WHERE email=?', (new_password, email))
        conn.commit()
    return jsonify({'success': True})



@app.route('/search-student-history')
def search_student_history():
    if 'name' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.args.get('name', '').strip()
    roll = request.args.get('roll', '').strip()
    if not name and not roll:
        return jsonify({'rows': []})
    query = '''SELECT roll_no, student_name, exam, subject,
                      ROUND(SUM(final_marks), 1) as final_marks
               FROM (SELECT roll_no, student_name, exam, subject,
                            q_number, final_marks,
                            ROW_NUMBER() OVER (
                                PARTITION BY roll_no, subject, q_number
                                ORDER BY id DESC
                            ) as rn
                     FROM evaluations WHERE 1=1'''
    params = []
    if name:
        query += ' AND LOWER(student_name) LIKE ?'
        params.append('%' + name.lower() + '%')
    if roll:
        query += ' AND LOWER(roll_no) LIKE ?'
        params.append('%' + roll.lower() + '%')
    query += ''')
               WHERE rn = 1
               GROUP BY roll_no, student_name, subject
               ORDER BY student_name, subject'''
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        result.append({
            'roll_no': r['roll_no'],
            'student_name': r['student_name'],
            'exam': r['exam'],
            'subject': r['subject'],
            'final_marks': min(float(r['final_marks'] or 0), 15.0)
        })
    return jsonify({'rows': result})


if __name__ == '__main__':
    app.run(debug=True)
