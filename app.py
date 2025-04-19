from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from datetime import datetime
import json
import random
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')

# Handle database URL for Render
database_url = os.environ.get('DATABASE_URL', 'sqlite:///maths_exam.db')
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add custom Jinja2 filter for JSON handling
@app.template_filter('fromjson')
def fromjson_filter(value):
    if value is None:
        return []
    return json.loads(value)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Error handler for 500 errors
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {str(error)}")
    logger.error(traceback.format_exc())
    return render_template('500.html'), 500

# Error handler for 404 errors
@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 Error: {str(error)}")
    return render_template('404.html'), 404

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_test')
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
def view_test_result():
    # Get the test index from the form
    test_index = request.form.get('test_index')
    if test_index is None:
        flash('No test index provided', 'error')
        return redirect(url_for('index'))
    
    # Get test history from session
    test_history = session.get('test_history', [])
    try:
        test_index = int(test_index)
        if 0 <= test_index < len(test_history):
            session['test_results'] = test_history[test_index]
            return redirect(url_for('results'))
        else:
            flash('Invalid test index', 'error')
    except ValueError:
        flash('Invalid test index format', 'error')
    
    return redirect(url_for('index'))

def generate_questions():
    # Question pool with more questions to ensure variety
    question_pool = [
        {
            "id": 1,
            "question": "What is 12 × 4?",
            "options": ["36", "48", "42", "56"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "12 × 4 = 48. You can break it down as (10 × 4) + (2 × 4) = 40 + 8 = 48"
        },
        {
            "id": 2,
            "question": "What is 15 ÷ 3?",
            "options": ["3", "4", "5", "6"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "15 ÷ 3 = 5. You can think of it as how many times 3 fits into 15"
        },
        {
            "id": 3,
            "question": "What is 7 × 8?",
            "options": ["42", "48", "56", "64"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "7 × 8 = 56. This is a common multiplication fact that's good to memorize"
        },
        {
            "id": 4,
            "question": "What is 24 ÷ 6?",
            "options": ["3", "4", "5", "6"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "24 ÷ 6 = 4. You can think of it as how many times 6 fits into 24"
        },
        {
            "id": 5,
            "question": "What is 9 × 6?",
            "options": ["45", "54", "63", "72"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "9 × 6 = 54. You can use the trick: 10 × 6 = 60, then subtract 6 to get 54"
        },
        {
            "id": 6,
            "question": "What is 36 ÷ 9?",
            "options": ["3", "4", "5", "6"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "36 ÷ 9 = 4. You can think of it as how many times 9 fits into 36"
        },
        {
            "id": 7,
            "question": "What is 11 × 5?",
            "options": ["45", "50", "55", "60"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "11 × 5 = 55. You can break it down as (10 × 5) + (1 × 5) = 50 + 5 = 55"
        },
        {
            "id": 8,
            "question": "What is 63 ÷ 7?",
            "options": ["7", "8", "9", "10"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "63 ÷ 7 = 9. You can think of it as how many times 7 fits into 63"
        },
        {
            "id": 9,
            "question": "What is 8 × 7?",
            "options": ["48", "56", "64", "72"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "8 × 7 = 56. This is another common multiplication fact that's good to memorize"
        },
        {
            "id": 10,
            "question": "What is 45 ÷ 5?",
            "options": ["7", "8", "9", "10"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "45 ÷ 5 = 9. You can think of it as how many times 5 fits into 45"
        },
        {
            "id": 11,
            "question": "What is 13 × 4?",
            "options": ["42", "48", "52", "56"],
            "correct_answer": 2,  # Index of correct answer (0-based)
            "explanation": "13 × 4 = 52. You can break it down as (10 × 4) + (3 × 4) = 40 + 12 = 52"
        },
        {
            "id": 12,
            "question": "What is 72 ÷ 8?",
            "options": ["8", "9", "10", "11"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "72 ÷ 8 = 9. You can think of it as how many times 8 fits into 72"
        },
        {
            "id": 13,
            "question": "What is 6 × 9?",
            "options": ["45", "54", "63", "72"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "6 × 9 = 54. This is the same as 9 × 6, showing that multiplication is commutative"
        },
        {
            "id": 14,
            "question": "What is 81 ÷ 9?",
            "options": ["8", "9", "10", "11"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "81 ÷ 9 = 9. You can think of it as how many times 9 fits into 81"
        },
        {
            "id": 15,
            "question": "What is 14 × 3?",
            "options": ["36", "42", "48", "54"],
            "correct_answer": 1,  # Index of correct answer (0-based)
            "explanation": "14 × 3 = 42. You can break it down as (10 × 3) + (4 × 3) = 30 + 12 = 42"
        }
    ]
    
    # Get the last test's questions from session if it exists
    last_test_questions = session.get('last_test_questions', [])
    
    # Filter out questions that were in the last test (80% new questions)
    available_questions = [q for q in question_pool if q['id'] not in last_test_questions]
    
    # If we don't have enough new questions, add some from the last test
    if len(available_questions) < 8:  # 80% of 10 questions
        # Get questions from last test that we can reuse
        reusable_questions = [q for q in question_pool if q['id'] in last_test_questions]
        # Add enough questions to reach 8 new questions
        available_questions.extend(reusable_questions[:8 - len(available_questions)])
    
    # Select 10 random questions from the available pool
    selected_questions = random.sample(available_questions, min(10, len(available_questions)))
    
    # Store the IDs of the selected questions for the next test
    session['last_test_questions'] = [q['id'] for q in selected_questions]
    
    # Assign new IDs to avoid conflicts
    for i, question in enumerate(selected_questions):
        question["id"] = i + 1
    
    return selected_questions

if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            logger.error(traceback.format_exc())
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 