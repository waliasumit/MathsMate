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
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///maths_exam.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add fromjson filter to Jinja2
@app.template_filter('fromjson')
def fromjson_filter(value):
    return json.loads(value)

db = SQLAlchemy(app)

# Database Models
class TestQuestion(db.Model):
    __tablename__ = 'test_questions'
    test_id = db.Column(db.Integer, db.ForeignKey('test.id'), primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), primary_key=True)
    test = db.relationship('Test', backref=db.backref('test_questions', lazy=True))
    question = db.relationship('Question', backref=db.backref('test_questions', lazy=True))

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    questions_used = db.Column(db.Text)  # Store as JSON string
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    options = db.Column(db.String(500), nullable=False)
    correct_answer = db.Column(db.String(50), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False, default='medium')
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

@app.route('/start_test', methods=['GET'])
def start_test():
    try:
        # Generate or get questions
        questions = generate_questions()
        
        # Create a new test with required fields
        test = Test(
            score=0,
            total_questions=len(questions),
            percentage=0.0,
            completed=False,
            questions_used=json.dumps([])  # Initialize with empty list
        )
        db.session.add(test)
        db.session.commit()
        
        # Add questions to the test
        for q in questions:
            # If the question is from the database, it will have an id
            # If it's newly generated, we need to save it first
            if 'id' not in q:
                question = Question(
                    question_text=q['question'],
                    options=json.dumps(q['options']),
                    correct_answer=q['correct_answer'],
                    explanation=q['explanation']
                )
                db.session.add(question)
                db.session.commit()
                q['id'] = question.id
            
            test_question = TestQuestion(test_id=test.id, question_id=q['id'])
            db.session.add(test_question)
            
            # Update questions_used list
            questions_used = json.loads(test.questions_used)
            questions_used.append(q['id'])
            test.questions_used = json.dumps(questions_used)
        
        db.session.commit()
        
        # Get the questions with their IDs for the template
        test_questions = TestQuestion.query.filter_by(test_id=test.id).all()
        questions_with_ids = []
        for tq in test_questions:
            question = Question.query.get(tq.question_id)
            questions_with_ids.append({
                'id': question.id,
                'question_text': question.question_text,
                'options': json.loads(question.options),
                'correct_answer': question.correct_answer,
                'explanation': question.explanation
            })
        
        return render_template('test.html', test_id=test.id, questions=questions_with_ids)
        
    except Exception as e:
        app.logger.error(f"Error in start_test: {str(e)}", exc_info=True)
        return "An error occurred while starting the test. Please try again.", 500

@app.route('/submit_test', methods=['POST'])
def submit_test():
    try:
        # Get test ID from form
        test_id = request.form.get('test_id')
        if not test_id:
            app.logger.error("No test_id provided in form data")
            return "Test ID not provided", 400
            
        app.logger.info(f"Processing submission for test {test_id}")
        
        # Get test from database
        test = Test.query.get(test_id)
        if not test:
            app.logger.error(f"Test {test_id} not found in database")
            return "Test not found", 404
            
        # Get answers from form
        answers = {}
        for key, value in request.form.items():
            if key.startswith('answer_'):
                question_id = key.replace('answer_', '')
                try:
                    answers[int(question_id)] = value
                except ValueError as e:
                    app.logger.error(f"Error converting answer for question {question_id}: {str(e)}")
                    return f"Invalid answer format for question {question_id}", 400
                    
        app.logger.info(f"Collected answers: {answers}")
        
        # Calculate score
        score = 0
        results = {}
        
        # Get all questions for this test through TestQuestion relationship
        test_questions = TestQuestion.query.filter_by(test_id=test.id).all()
        for tq in test_questions:
            question = tq.question
            user_answer = answers.get(question.id)
            
            # Detailed logging for debugging
            app.logger.debug("="*50)
            app.logger.debug(f"Question ID: {question.id}")
            app.logger.debug(f"Question text: {question.question_text}")
            app.logger.debug(f"Raw user answer: {user_answer}")
            app.logger.debug(f"Raw correct answer: {question.correct_answer}")
            app.logger.debug(f"User answer type: {type(user_answer)}")
            app.logger.debug(f"Correct answer type: {type(question.correct_answer)}")
            
            # Get the options for this question
            options = json.loads(question.options)
            app.logger.debug(f"Options: {options}")
            
            # Convert both answers to strings and strip whitespace for comparison
            user_answer_str = str(user_answer).strip() if user_answer else None
            correct_answer_str = str(question.correct_answer).strip()
            
            app.logger.debug(f"Raw correct answer: '{correct_answer_str}'")
            app.logger.debug(f"Raw correct answer type: {type(correct_answer_str)}")
            
            # Extract the option letter from the correct answer (e.g., "A) 50" -> "A")
            correct_option_letter = correct_answer_str.split(')')[0].strip()
            app.logger.debug(f"Correct option letter: '{correct_option_letter}'")
            
            # Convert option letters to indices (A->0, B->1, C->2, D->3)
            option_letter_to_index = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
            
            # Get the correct answer index
            correct_answer_index = option_letter_to_index.get(correct_option_letter)
            
            # Get the user's answer index by finding the selected option in the options array
            user_answer_index = None
            if user_answer_str:
                # Find the index of the user's selected option in the options array
                for i, option in enumerate(options):
                    if str(option).strip() == user_answer_str:
                        user_answer_index = i
                        break
            
            app.logger.debug("="*50)
            app.logger.debug(f"Question ID: {question.id}")
            app.logger.debug(f"Question text: {question.question_text}")
            app.logger.debug(f"Options array: {options}")
            app.logger.debug(f"Correct answer string: '{correct_answer_str}'")
            app.logger.debug(f"Extracted correct option letter: '{correct_option_letter}'")
            app.logger.debug(f"Correct answer index: {correct_answer_index}")
            app.logger.debug(f"User's selected option: '{user_answer_str}'")
            app.logger.debug(f"User's answer index: {user_answer_index}")
            app.logger.debug("="*50)
            
            # Compare the user's answer index with the correct answer index
            correct = user_answer_index is not None and user_answer_index == correct_answer_index
            app.logger.debug(f"Is correct: {correct}")
            
            if correct:
                score += 1
            results[question.id] = {
                'question': question.question_text,
                'user_answer': options[user_answer_index] if user_answer_index is not None else "Not answered",
                'correct_answer': question.correct_answer,
                'is_correct': correct,
                'explanation': question.explanation
            }
            
        app.logger.info(f"Calculated score: {score}/{len(test_questions)}")
        
        # Update test with score
        test.score = score
        test.percentage = (score / len(test_questions)) * 100
        test.completed = True
        
        try:
            db.session.commit()
            app.logger.info("Successfully updated test in database")
        except Exception as e:
            app.logger.error(f"Database error while updating test: {str(e)}")
            db.session.rollback()
            return "Error saving test results", 500
            
        # Save test results to session
        session['test_results'] = {
            'test_id': test.id,
            'score': score,
            'total_questions': len(test_questions),
            'percentage': test.percentage,
            'timestamp': test.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'results': results
        }
        
        return render_template('results.html', test=test, results=results)
        
    except Exception as e:
        app.logger.error(f"Unexpected error in submit_test: {str(e)}", exc_info=True)
        return "An error occurred while submitting the test", 500

@app.route('/results')
def results():
    # Get test results from session
    test_results = session.get('test_results')
    if not test_results:
        flash('No test results found.', 'error')
        return redirect(url_for('start_test'))
    
    # Get the test from the database
    test = Test.query.get(test_results['test_id'])
    if test is None:
        flash('Test not found in database', 'error')
        return redirect(url_for('index'))
    
    return render_template('results.html', test=test, results=test_results['results'])

# Initialize database
def init_db():
    with app.app_context():
        db.drop_all()
        db.create_all()
        app.logger.info("Database initialized successfully")

def generate_questions():
    try:
        # Check if we have enough questions in the database
        existing_questions = Question.query.all()
        if len(existing_questions) >= 10:
            # Select 10 random questions
            selected_questions = random.sample(existing_questions, 10)
            return [{
                'id': q.id,
                'question': q.question_text,
                'options': json.loads(q.options),
                'correct_answer': q.correct_answer,
                'explanation': q.explanation
            } for q in selected_questions]

        # If not enough questions, generate new ones using OpenRouter
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            app.logger.warning("Please set OPENROUTER_API_KEY environment variable")
            return get_fallback_questions()

        app.logger.info("OpenRouter API key found in environment variables")
        app.logger.info(f"API key (masked): {api_key[:3]}...{api_key[-4:]}")

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'http://localhost:5000',
            'X-Title': 'Maths Exam'
        }

        data = {
            'model': 'deepseek/deepseek-r1:free',
            'messages': [{
                'role': 'user',
                'content': '''Generate 10 multiple choice math questions for grade 5 students. 
                Each question should have 4 options (A, B, C, D) and include an explanation.
                Format each question as a JSON object with these fields:
                - question: The question text
                - options: Array of 4 options [A, B, C, D]
                - correct_answer: The correct option (A, B, C, or D)
                - explanation: Explanation of the solution
                Return ONLY the JSON array, with no additional text or explanation.'''
            }]
        }

        app.logger.debug(f"API request data: {json.dumps(data, indent=2)}")

        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers=headers,
            json=data
        )

        app.logger.debug(f"API response status code: {response.status_code}")
        app.logger.debug(f"API response headers: {response.headers}")
        app.logger.debug(f"API response text: {response.text}")

        if response.status_code == 200:
            try:
                response_data = response.json()
                app.logger.debug(f"Raw API response: {json.dumps(response_data, indent=2)}")
                
                # Check if response has the expected structure
                if 'choices' not in response_data or not response_data['choices']:
                    app.logger.error("Invalid API response structure: missing 'choices'")
                    app.logger.error(f"Response keys: {response_data.keys()}")
                    app.logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                    return get_fallback_questions()
                
                # Extract the generated text from the response
                generated_text = response_data['choices'][0]['message']['content']
                app.logger.debug(f"Generated text: {generated_text}")
                
                # Try to find JSON array in the text
                try:
                    # First try to parse the entire text as JSON
                    questions = json.loads(generated_text)
                except json.JSONDecodeError:
                    # If that fails, try to extract JSON from between ```json and ```
                    if '```json' in generated_text and '```' in generated_text:
                        json_str = generated_text.split('```json')[1].split('```')[0].strip()
                        questions = json.loads(json_str)
                    else:
                        # If no JSON markers, try to find the first [ and last ]
                        start = generated_text.find('[')
                        end = generated_text.rfind(']')
                        if start != -1 and end != -1:
                            json_str = generated_text[start:end+1]
                            questions = json.loads(json_str)
                        else:
                            raise json.JSONDecodeError("No JSON array found in response", generated_text, 0)
                
                app.logger.info(f"Successfully generated {len(questions)} questions")
                
                # Save questions to database
                for q in questions:
                    question = Question(
                        question_text=q['question'],
                        options=json.dumps(q['options']),
                        correct_answer=q['correct_answer'],
                        explanation=q['explanation']
                    )
                    db.session.add(question)
                
                db.session.commit()
                return questions
                
            except json.JSONDecodeError as e:
                app.logger.error(f"Error parsing generated text: {str(e)}")
                app.logger.error(f"Generated text that failed to parse: {generated_text}")
                return get_fallback_questions()
            except Exception as e:
                app.logger.error(f"Error processing API response: {str(e)}")
                app.logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                return get_fallback_questions()
        else:
            app.logger.error(f"API request failed with status {response.status_code}")
            app.logger.error(f"Response: {response.text}")
            return get_fallback_questions()

    except Exception as e:
        app.logger.error(f"Unexpected error in generate_questions: {str(e)}", exc_info=True)
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

def load_env():
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
    except Exception as e:
        logging.error(f"Error loading .env file: {str(e)}")

# Load environment variables
load_env()

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Start the application
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 