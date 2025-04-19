from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from datetime import datetime
import json
import random
import logging
import traceback
import requests

# Configure logging for production
if os.environ.get('FLASK_ENV') == 'production':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('app.log')
        ]
    )
else:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('app.log')
        ]
    )

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')

# Database configuration for production
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///math_exam.db')
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///math_exam.db'

# Ensure the database URL is properly formatted for production
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# DeepSeek API configuration
DEEPSEEK_API_KEY = os.environ.get('OPENROUTER_API_KEY')
DEEPSEEK_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Debug logging for API key
if DEEPSEEK_API_KEY:
    logger.info("OpenRouter API key found in environment variables")
    # Log first 4 characters and last 4 characters of the key for security
    masked_key = DEEPSEEK_API_KEY[:4] + "..." + DEEPSEEK_API_KEY[-4:]
    logger.info(f"API key (masked): {masked_key}")
    logger.info(f"API key length: {len(DEEPSEEK_API_KEY)}")
else:
    logger.warning("OpenRouter API key not found in environment variables")
    logger.warning("Please set OPENROUTER_API_KEY environment variable")

# File paths for storing data
QUESTIONS_FILE = 'questions.json'
TEST_HISTORY_FILE = 'test_history.json'

def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        with open(QUESTIONS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_questions(questions):
    with open(QUESTIONS_FILE, 'w') as f:
        json.dump(questions, f)

def load_test_history():
    if os.path.exists(TEST_HISTORY_FILE):
        with open(TEST_HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_test_history(history):
    with open(TEST_HISTORY_FILE, 'w') as f:
        json.dump(history, f)

# Add custom Jinja2 filter for JSON handling
@app.template_filter('fromjson')
def fromjson_filter(value):
    if value is None:
        return []
    return json.loads(value)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Database Models
class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)  # Store user identifier
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    questions_used = db.Column(db.Text, nullable=False)  # Store question IDs as JSON string

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    options = db.Column(db.String(500), nullable=False)
    correct_answer = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.String(500), nullable=False)
    times_used = db.Column(db.Integer, default=0)  # Track how many times a question has been used
    last_used = db.Column(db.DateTime)  # Track when the question was last used

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
        if 'current_test' not in session:
            return jsonify({'error': 'No test in progress'}), 400
            
        data = request.get_json()
        answers = data.get('answers', {})
        
        # Get user identifier
        user_id = request.remote_addr
        
        # Calculate score
        score = 0
        total_questions = len(session['current_test']['questions'])
        question_ids = []
        
        for question in session['current_test']['questions']:
            question_id = question['id']
            question_ids.append(question_id)
            user_answer = answers.get(str(question_id))
            
            if user_answer is not None and user_answer == question['correct_answer']:
                score += 1
        
        # Store test results in session
        session['test_results'] = {
            'score': score,
            'total_questions': total_questions,
            'percentage': (score / total_questions) * 100,
            'questions': session['current_test']['questions'],
            'answers': answers
        }
        
        # Store test history
        test_history = load_test_history()
        if user_id not in test_history:
            test_history[user_id] = []
        
        test_history[user_id].append({
            'timestamp': datetime.now().isoformat(),
            'score': score,
            'total_questions': total_questions,
            'questions_used': question_ids
        })
        
        # Keep only the last 5 tests per user
        test_history[user_id] = test_history[user_id][-5:]
        save_test_history(test_history)
        
        # Clear current test from session
        session.pop('current_test', None)
        
        return jsonify({
            'score': score,
            'total_questions': total_questions,
            'percentage': (score / total_questions) * 100
        })
        
    except Exception as e:
        logger.error(f"Error submitting test: {str(e)}")
        return jsonify({'error': 'An error occurred while submitting the test'}), 500

@app.route('/results')
def results():
    # Get test results from session
    test_results = session.get('test_results')
    if not test_results:
        flash('No test results found.', 'error')
        return redirect(url_for('start_test'))
    
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
    try:
        # Check if API key is configured
        if not DEEPSEEK_API_KEY:
            logger.warning("OpenRouter API key not found. Using predefined questions.")
            return get_fallback_questions()

        logger.info("Starting question generation process...")
        # Get all questions from the database
        all_questions = Question.query.all()
        logger.info(f"Current number of questions in database: {len(all_questions)}")
        
        # If we don't have enough questions, try to generate more using OpenRouter
        if len(all_questions) < 20:
            try:
                logger.info("Attempting to generate new questions using OpenRouter API...")
                # Generate new questions
                prompt = """
                Generate 20 math questions for Year 9 students with the following requirements:
                1. Mix of different question types:
                   - Algebra (solving equations, expressions)
                   - Word problems (real-world applications)
                   - Number patterns and sequences
                   - Probability and statistics
                   - Geometry (area, perimeter, angles)
                2. Difficulty levels:
                   - 7 easy questions (basic concepts)
                   - 7 medium questions (application of concepts)
                   - 6 challenging questions (complex problems)
                3. Each question should have 4 options
                4. Include detailed explanations showing the step-by-step solution
                5. Format the response as a JSON array
                """
                
                # Make API request to OpenRouter
                headers = {
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "Maths Exam App"
                }
                
                data = {
                    "model": "deepseek/deepseek-chat-v3-0324:free",
                    "messages": [
                        {"role": "system", "content": "You are an experienced math teacher creating challenging and engaging questions."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7
                }

                logger.info("Sending request to OpenRouter API...")
                logger.debug(f"Request headers: {headers}")
                logger.debug(f"Request data: {data}")
                
                response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=10)
                
                logger.info(f"OpenRouter API response status code: {response.status_code}")
                logger.debug(f"Response headers: {dict(response.headers)}")
                
                if response.status_code == 402:
                    logger.error("OpenRouter API returned Payment Required error. Please check your API key and credits.")
                    logger.error(f"Response body: {response.text}")
                    return get_fallback_questions()
                elif response.status_code != 200:
                    logger.error(f"OpenRouter API returned status code {response.status_code}")
                    logger.error(f"Response body: {response.text}")
                    return get_fallback_questions()
                
                # Parse the response
                result = response.json()
                logger.debug(f"Raw API response: {result}")
                
                generated_text = result['choices'][0]['message']['content']
                logger.debug(f"Generated text: {generated_text}")
                
                # Extract JSON from the response
                start_idx = generated_text.find('[')
                end_idx = generated_text.rfind(']') + 1
                if start_idx == -1 or end_idx == 0:
                    logger.error("Failed to parse JSON from OpenRouter response")
                    logger.error(f"Generated text: {generated_text}")
                    return get_fallback_questions()
                
                json_str = generated_text[start_idx:end_idx]
                new_questions = json.loads(json_str)
                logger.info(f"Successfully generated {len(new_questions)} new questions from OpenRouter API")
                
                # Add new questions to database
                for q in new_questions:
                    if not Question.query.filter_by(question_text=q["question"]).first():
                        question = Question(
                            question_text=q["question"],
                            options=",".join(q["options"]),
                            correct_answer=q["correct_answer"],
                            explanation=q["explanation"],
                            times_used=0
                        )
                        db.session.add(question)
                
                db.session.commit()
                logger.info("Successfully added new questions to database")
                all_questions = Question.query.all()
                logger.info(f"Total questions in database after adding new ones: {len(all_questions)}")
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error while calling OpenRouter API: {str(e)}")
                logger.error(traceback.format_exc())
                return get_fallback_questions()
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Error parsing OpenRouter API response: {str(e)}")
                logger.error(traceback.format_exc())
                return get_fallback_questions()
            except Exception as e:
                logger.error(f"Unexpected error while generating questions: {str(e)}")
                logger.error(traceback.format_exc())
                return get_fallback_questions()
        
        # Sort questions by times_used and last_used
        sorted_questions = sorted(
            all_questions,
            key=lambda x: (x.times_used or 0, x.last_used or datetime.min)
        )
        
        # Select 10 questions that have been used the least
        selected_questions = sorted_questions[:10]
        
        # Update usage tracking
        current_time = datetime.utcnow()
        for question in selected_questions:
            question.times_used = (question.times_used or 0) + 1
            question.last_used = current_time
        
        db.session.commit()
        
        # Format questions for the test
        test_questions = []
        for question in selected_questions:
            test_questions.append({
                "id": question.id,
                "question": question.question_text,
                "options": question.options.split(','),
                "correct_answer": question.correct_answer,
                "explanation": question.explanation
            })
        
        logger.info(f"Returning {len(test_questions)} questions for the test")
        return test_questions
        
    except Exception as e:
        logger.error(f"Error in generate_questions: {str(e)}")
        logger.error(traceback.format_exc())
        return get_fallback_questions()

def get_fallback_questions():
    """Return a set of predefined questions when API generation fails"""
    logger.info("Using fallback questions")
    # Fallback question pool with more advanced questions
    question_pool = [
        {
            "id": 1,
            "question": "Solve for x: 3x - 7 = 14",
            "options": ["7", "21", "9", "11"],
            "correct_answer": 0,
            "explanation": "To solve 3x - 7 = 14:\n1. Add 7 to both sides: 3x = 21\n2. Divide both sides by 3: x = 7"
        },
        {
            "id": 2,
            "question": "What is the next number in the sequence: 2, 5, 10, 17, 26, ...?",
            "options": ["35", "37", "39", "41"],
            "correct_answer": 1,
            "explanation": "The pattern is adding consecutive odd numbers:\n2 + 3 = 5\n5 + 5 = 10\n10 + 7 = 17\n17 + 9 = 26\n26 + 11 = 37"
        },
        {
            "id": 3,
            "question": "A rectangle has a length of 12 cm and a width of 8 cm. What is its area?",
            "options": ["96 cm²", "84 cm²", "72 cm²", "64 cm²"],
            "correct_answer": 0,
            "explanation": "Area of rectangle = length × width\n= 12 cm × 8 cm = 96 cm²"
        },
        {
            "id": 4,
            "question": "If a number is increased by 20% and then decreased by 20%, what is the net change?",
            "options": ["No change", "4% decrease", "4% increase", "20% decrease"],
            "correct_answer": 1,
            "explanation": "Let the number be 100\nAfter 20% increase: 100 + 20 = 120\nAfter 20% decrease: 120 - 24 = 96\nNet change = (100 - 96)/100 × 100 = 4% decrease"
        },
        {
            "id": 5,
            "question": "What is the probability of rolling a sum of 7 with two dice?",
            "options": ["1/6", "1/12", "1/36", "1/4"],
            "correct_answer": 0,
            "explanation": "Total possible outcomes = 6 × 6 = 36\nFavorable outcomes for sum 7: (1,6), (2,5), (3,4), (4,3), (5,2), (6,1) = 6\nProbability = 6/36 = 1/6"
        },
        {
            "id": 6,
            "question": "A train travels 300 km in 4 hours. What is its average speed?",
            "options": ["75 km/h", "80 km/h", "85 km/h", "90 km/h"],
            "correct_answer": 0,
            "explanation": "Average speed = Total distance / Total time\n= 300 km / 4 hours = 75 km/h"
        },
        {
            "id": 7,
            "question": "If 2x + 3y = 12 and x - y = 1, what is the value of x?",
            "options": ["3", "4", "5", "6"],
            "correct_answer": 0,
            "explanation": "From x - y = 1, we get y = x - 1\nSubstitute in first equation: 2x + 3(x - 1) = 12\n5x - 3 = 12\n5x = 15\nx = 3"
        },
        {
            "id": 8,
            "question": "What is the area of a circle with radius 7 cm? (Use π = 22/7)",
            "options": ["154 cm²", "147 cm²", "140 cm²", "133 cm²"],
            "correct_answer": 0,
            "explanation": "Area of circle = πr²\n= (22/7) × 7 × 7\n= 22 × 7\n= 154 cm²"
        },
        {
            "id": 9,
            "question": "A shop offers a 15% discount on a $200 item. What is the final price?",
            "options": ["$170", "$175", "$180", "$185"],
            "correct_answer": 0,
            "explanation": "Discount amount = 15% of $200 = $30\nFinal price = $200 - $30 = $170"
        },
        {
            "id": 10,
            "question": "What is the value of 2³ + 3²?",
            "options": ["17", "18", "19", "20"],
            "correct_answer": 0,
            "explanation": "2³ = 8 and 3² = 9\n8 + 9 = 17"
        }
    ]
    
    # Return all 10 questions
    return question_pool

if __name__ == '__main__':
    with app.app_context():
        try:
            # Drop all tables first
            db.drop_all()
            logger.info("Dropped all existing tables")
            
            # Create tables
            db.create_all()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            logger.error(traceback.format_exc())
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 