from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
import json
import requests
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///maths_exam.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD')

# Add custom Jinja2 filter for JSON handling
@app.template_filter('fromjson')
def fromjson_filter(value):
    if value is None:
        return []
    return json.loads(value)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(100), unique=True)
    email_verification_sent_at = db.Column(db.DateTime)
    tests = db.relationship('Test', backref='user', lazy=True)

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    score = db.Column(db.Float)
    questions = db.Column(db.Text)  # JSON string of questions
    answers = db.Column(db.Text)    # JSON string of user answers
    feedback = db.Column(db.Text)   # JSON string of feedback

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('signup'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('signup'))
        
        user = User(username=username, email=email)
        user.password_hash = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()
        
        # Send verification email
        if send_verification_email(user):
            flash('Registration successful! Please check your email to verify your account.', 'success')
        else:
            flash('Registration successful, but we could not send the verification email. Please contact support.', 'warning')
        
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        email = URLSafeTimedSerializer(app.config['SECRET_KEY']).loads(
            token, salt='email-verification', max_age=86400  # 24 hours
        )
        user = User.query.filter_by(email=email).first()
        
        if user:
            if user.email_verified:
                flash('Your email is already verified. You can now login.', 'info')
                return redirect(url_for('login'))
            
            user.email_verified = True
            user.email_verification_token = None
            db.session.commit()
            
            flash('Your email has been verified! You can now login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid verification link.', 'error')
            return redirect(url_for('signup'))
            
    except Exception as e:
        flash('The verification link is invalid or has expired.', 'error')
        return redirect(url_for('signup'))

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    
    if user:
        if user.email_verified:
            flash('Your email is already verified.', 'info')
            return redirect(url_for('login'))
        
        # Check if we should allow resending (e.g., not too frequent)
        if user.email_verification_sent_at:
            time_since_last = datetime.utcnow() - user.email_verification_sent_at
            if time_since_last < timedelta(minutes=5):
                flash('Please wait a few minutes before requesting another verification email.', 'warning')
                return redirect(url_for('login'))
        
        if send_verification_email(user):
            flash('Verification email has been resent. Please check your inbox.', 'success')
        else:
            flash('Could not send verification email. Please try again later.', 'error')
    else:
        flash('Email not found.', 'error')
    
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.email_verified:
                flash('Please verify your email address before logging in. Check your inbox for the verification link.', 'warning')
                return render_template('login.html', email=email, show_resend=True)
            
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Redirect to home page
    return redirect(url_for('index'))

@app.route('/start_test')
@login_required
def start_test():
    questions = generate_questions()
    # Store questions in session
    session['current_test'] = {
        'questions': questions,
        'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return render_template('test.html', questions=questions)

@app.route('/submit_test', methods=['POST'])
def submit_test():
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        if 'current_test' not in session:
            return jsonify({'error': 'No test in progress. Please start a new test.'}), 400
        
        answers = data.get('answers', {})
        current_test = session['current_test']
        questions = current_test['questions']
        
        # Initialize results
        score = 0
        total_questions = len(questions)
        feedback = []
        
        # Process each question
        for question in questions:
            q_id = f"q_{question['id']}"
            user_answer = answers.get(q_id)
            
            if user_answer is None:
                feedback.append({
                    'question': question['question'],
                    'user_answer': 'Not answered',
                    'correct_answer': question['options'][question['correct_answer']],
                    'explanation': question['explanation'],
                    'is_correct': False
                })
                continue
            
            # Find the index of the user's answer in the options list
            try:
                user_answer_index = question['options'].index(user_answer)
                is_correct = user_answer_index == question['correct_answer']
                
                if is_correct:
                    score += 1
                
                feedback.append({
                    'question': question['question'],
                    'user_answer': user_answer,
                    'correct_answer': question['options'][question['correct_answer']],
                    'explanation': question['explanation'],
                    'is_correct': is_correct
                })
            except ValueError:
                feedback.append({
                    'question': question['question'],
                    'user_answer': 'Invalid answer',
                    'correct_answer': question['options'][question['correct_answer']],
                    'explanation': question['explanation'],
                    'is_correct': False
                })
        
        # Calculate percentage score
        percentage = (score / total_questions) * 100
        
        # Create test result
        test_result = {
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'score': score,
            'total': total_questions,
            'percentage': percentage,
            'feedback': feedback
        }
        
        # Store in session
        session['test_results'] = test_result
        
        if 'test_history' not in session:
            session['test_history'] = []
        
        # Add to test history, keeping only the last 5 tests
        session['test_history'] = [test_result] + session['test_history'][:4]
        
        # Clear current test
        session.pop('current_test', None)
        
        return jsonify(test_result)
        
    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/results')
@login_required
def results():
    # Get test results from session
    test_results = session.get('test_results')
    if not test_results:
        flash('No test results found.', 'error')
        return redirect(url_for('start_test'))
    
    # Ensure the test_results has all required fields
    if 'answered' not in test_results:
        test_results['answered'] = test_results.get('total', 0)
    
    return render_template('results.html', results=test_results)

@app.route('/view_test_result', methods=['POST'])
@login_required
def view_test_result():
    # Get the test index from the form
    test_index = request.form.get('test_index')
    if test_index is None:
        flash('No test index provided', 'error')
        return redirect(url_for('index'))
    
    # Get test history from session
    test_history = session.get('test_history', [])
    if not test_history:
        flash('No test history found', 'error')
        return redirect(url_for('index'))
    
    try:
        # Convert to integer and get the test result
        test_index = int(test_index)
        if test_index < 0 or test_index >= len(test_history):
            flash('Invalid test index', 'error')
            return redirect(url_for('index'))
        
        # Get the test result and set it as the current test result
        test_result = test_history[test_index]
        session['test_results'] = test_result
        
        return redirect(url_for('results'))
    except ValueError:
        flash('Invalid test index format', 'error')
        return redirect(url_for('index'))

def generate_questions():
    """Generate a set of diverse math questions for Year 7 level."""
    # Simple question pool with clear structure
    question_pool = [
        {
            "id": 1,
            "question": "Solve: 3x + 5 = 20",
            "options": ["3", "5", "7", "15"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "Subtract 5 from both sides: 3x = 15, then divide by 3: x = 5"
        },
        {
            "id": 2,
            "question": "If 2x - 3 = 11, what is the value of x?",
            "options": ["5", "7", "8", "9"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "Add 3 to both sides: 2x = 14, then divide by 2: x = 7"
        },
        {
            "id": 3,
            "question": "Solve: 4(x + 2) = 24",
            "options": ["2", "4", "6", "8"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "Divide both sides by 4: x + 2 = 6, then subtract 2: x = 4"
        },
        {
            "id": 4,
            "question": "If 5x + 3 = 3x + 9, what is the value of x?",
            "options": ["2", "3", "4", "5"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "Subtract 3x from both sides: 2x + 3 = 9, then subtract 3: 2x = 6, then divide by 2: x = 3"
        },
        {
            "id": 5,
            "question": "A store sells shirts for $25 each. If they have a 20% discount, what is the final price?",
            "options": ["$15", "$18", "$20", "$22"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "20% of $25 is $5 (25 × 0.2 = 5). So the discounted price is $25 - $5 = $20"
        },
        {
            "id": 6,
            "question": "A train travels 120 kilometers in 2 hours. What is its speed in kilometers per hour?",
            "options": ["40", "50", "60", "70"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "Speed = Distance ÷ Time = 120 ÷ 2 = 60 km/h"
        },
        {
            "id": 7,
            "question": "If a rectangle has a length of 8cm and a width of 5cm, what is its area?",
            "options": ["13cm²", "26cm²", "40cm²", "45cm²"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "Area = length × width = 8 × 5 = 40cm²"
        },
        {
            "id": 8,
            "question": "A recipe requires 3/4 cup of sugar for 6 servings. How much sugar is needed for 8 servings?",
            "options": ["1 cup", "1 1/4 cups", "1 1/2 cups", "2 cups"],
            "correct_answer": 0,  # Index of correct answer (0-based)
            "explanation": "If 6 servings need 3/4 cup, then 1 serving needs 3/4 ÷ 6 = 1/8 cup. For 8 servings: 1/8 × 8 = 1 cup"
        },
        {
            "id": 9,
            "question": "What is the next number in the sequence: 2, 4, 8, 16, ...?",
            "options": ["20", "24", "32", "36"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "The pattern is multiplying by 2 each time: 2×2=4, 4×2=8, 8×2=16, 16×2=32"
        },
        {
            "id": 10,
            "question": "What is the next number in the sequence: 3, 6, 12, 24, ...?",
            "options": ["30", "36", "48", "54"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "The pattern is multiplying by 2 each time: 3×2=6, 6×2=12, 12×2=24, 24×2=48"
        }
    ]
    
    # Select 5 random questions
    selected_questions = random.sample(question_pool, 5)
    
    # Assign new IDs to avoid conflicts
    for i, question in enumerate(selected_questions):
        question["id"] = i + 1
    
    return selected_questions

def evaluate_test(questions, answers):
    score = 0
    feedback = []
    
    for q in questions:
        q_id = str(q['id'])
        user_answer = answers.get(f'q_{q_id}')
        is_correct = user_answer == q['correct']
        
        if is_correct:
            score += 1
        
        feedback.append({
            'question': q['question'],
            'user_answer': user_answer,
            'correct_answer': q['correct'],
            'explanation': q['explanation'],
            'is_correct': is_correct
        })
    
    return (score / len(questions)) * 100, feedback

def send_verification_email(user):
    """Send verification email to user."""
    token = URLSafeTimedSerializer(app.config['SECRET_KEY']).dumps(user.email, salt='email-verification')
    user.email_verification_token = token
    user.email_verification_sent_at = datetime.utcnow()
    db.session.commit()

    verification_url = url_for('verify_email', token=token, _external=True)
    
    msg = MIMEMultipart()
    msg['From'] = app.config['MAIL_USERNAME']
    msg['To'] = user.email
    msg['Subject'] = 'Verify your email address'
    
    body = f"""
    Hello {user.username},
    
    Please verify your email address by clicking the link below:
    {verification_url}
    
    This link will expire in 24 hours.
    
    If you did not create an account, please ignore this email.
    
    Best regards,
    Your Maths Test Team
    """
    
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
        server.starttls()
        server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))) 