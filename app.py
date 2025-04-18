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