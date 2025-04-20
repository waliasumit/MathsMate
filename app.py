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
import secrets

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
        app.logger.info("Starting new test generation")
        
        # Generate or get questions
        try:
            questions = generate_questions()
            if not questions:
                app.logger.error("No questions generated")
                flash('Failed to generate questions. Please try again.', 'error')
                return redirect(url_for('index'))
            app.logger.info(f"Generated {len(questions)} questions")
        except Exception as e:
            app.logger.error(f"Error generating questions: {str(e)}", exc_info=True)
            flash('An error occurred while generating questions. Please try again.', 'error')
            return redirect(url_for('index'))
        
        try:
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
            app.logger.info(f"Created new test with ID: {test.id}")
        except Exception as e:
            app.logger.error(f"Error creating test: {str(e)}", exc_info=True)
            flash('An error occurred while creating the test. Please try again.', 'error')
            return redirect(url_for('index'))
        
        try:
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
                    app.logger.debug(f"Saved new question with ID: {question.id}")
                
                test_question = TestQuestion(test_id=test.id, question_id=q['id'])
                db.session.add(test_question)
                
                # Update questions_used list
                questions_used = json.loads(test.questions_used)
                questions_used.append(q['id'])
                test.questions_used = json.dumps(questions_used)
            
            db.session.commit()
            app.logger.info(f"Added {len(questions)} questions to test {test.id}")
        except Exception as e:
            app.logger.error(f"Error adding questions to test: {str(e)}", exc_info=True)
            # Clean up the test if question addition fails
            db.session.rollback()
            if test.id:
                Test.query.filter_by(id=test.id).delete()
                db.session.commit()
            flash('An error occurred while setting up the test. Please try again.', 'error')
            return redirect(url_for('index'))
        
        try:
            # Get the questions with their IDs for the template
            test_questions = TestQuestion.query.filter_by(test_id=test.id).all()
            if not test_questions:
                app.logger.error(f"No questions found for test {test.id}")
                flash('No questions found for the test. Please try again.', 'error')
                return redirect(url_for('index'))
            
            questions_with_ids = []
            for tq in test_questions:
                question = Question.query.get(tq.question_id)
                if not question:
                    app.logger.error(f"Question {tq.question_id} not found")
                    continue
                questions_with_ids.append({
                    'id': question.id,
                    'question_text': question.question_text,
                    'options': json.loads(question.options),
                    'correct_answer': question.correct_answer,
                    'explanation': question.explanation
                })
            
            if not questions_with_ids:
                app.logger.error("No valid questions found for the template")
                flash('No valid questions found. Please try again.', 'error')
                return redirect(url_for('index'))
            
            app.logger.info(f"Successfully prepared {len(questions_with_ids)} questions for test {test.id}")
            return render_template('test.html', test_id=test.id, questions=questions_with_ids)
            
        except Exception as e:
            app.logger.error(f"Error preparing questions for template: {str(e)}", exc_info=True)
            flash('An error occurred while preparing the test. Please try again.', 'error')
            return redirect(url_for('index'))
            
    except Exception as e:
        app.logger.error(f"Unexpected error in start_test: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('index'))

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
                'content': '''Generate 10 multiple choice math questions for grade 7/8 students. 
                Each question should have 4 options (A, B, C, D) and include an explanation.
                Questions should cover topics like:
                - Algebra (linear equations, expressions)
                - Geometry (angles, area, volume)
                - Statistics and probability
                - Ratios and proportions
                - Percentages and interest
                - Basic trigonometry
                
                IMPORTANT: Return ONLY a JSON array of questions. Each question must be a JSON object with these exact fields:
                {
                    "question": "The question text",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_answer": "A",  // Must be A, B, C, or D
                    "explanation": "Step-by-step explanation of the solution"
                }
                
                Do not include any additional text, explanations, or formatting. Return ONLY the JSON array.'''
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
                if 'choices' not in response_data:
                    app.logger.error("Invalid API response structure: missing 'choices'")
                    app.logger.error(f"Response keys: {list(response_data.keys())}")
                    app.logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                    return get_fallback_questions()
                
                if not response_data['choices']:
                    app.logger.error("Empty choices array in API response")
                    app.logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                    return get_fallback_questions()
                
                if 'message' not in response_data['choices'][0]:
                    app.logger.error("Invalid choice structure: missing 'message'")
                    app.logger.error(f"Choice structure: {json.dumps(response_data['choices'][0], indent=2)}")
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
                
                # Validate the questions structure
                if not isinstance(questions, list):
                    app.logger.error("Generated questions is not a list")
                    app.logger.error(f"Questions type: {type(questions)}")
                    return get_fallback_questions()
                
                if len(questions) != 10:
                    app.logger.error(f"Expected 10 questions, got {len(questions)}")
                    return get_fallback_questions()
                
                # Validate each question
                for i, q in enumerate(questions):
                    if not all(key in q for key in ['question', 'options', 'correct_answer', 'explanation']):
                        app.logger.error(f"Question {i+1} missing required fields")
                        app.logger.error(f"Question structure: {json.dumps(q, indent=2)}")
                        return get_fallback_questions()
                    
                    if not isinstance(q['options'], list) or len(q['options']) != 4:
                        app.logger.error(f"Question {i+1} has invalid options")
                        app.logger.error(f"Options: {q['options']}")
                        return get_fallback_questions()
                    
                    if q['correct_answer'] not in ['A', 'B', 'C', 'D']:
                        app.logger.error(f"Question {i+1} has invalid correct_answer")
                        app.logger.error(f"Correct answer: {q['correct_answer']}")
                        return get_fallback_questions()
                
                app.logger.info(f"Successfully generated and validated {len(questions)} questions")
                
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
    # Fallback question pool with grade 7/8 level questions
    question_pool = [
        {
            "id": 1,
            "question": "Solve for x: 2(3x - 5) = 4x + 8",
            "options": ["9", "7", "5", "3"],
            "correct_answer": 0,
            "explanation": "To solve 2(3x - 5) = 4x + 8:\n1. Distribute: 6x - 10 = 4x + 8\n2. Subtract 4x: 2x - 10 = 8\n3. Add 10: 2x = 18\n4. Divide by 2: x = 9"
        },
        {
            "id": 2,
            "question": "What is the volume of a cylinder with radius 4 cm and height 10 cm? (Use π = 3.14)",
            "options": ["502.4 cm³", "401.92 cm³", "314 cm³", "251.2 cm³"],
            "correct_answer": 0,
            "explanation": "Volume of cylinder = πr²h\n= 3.14 × 4² × 10\n= 3.14 × 16 × 10\n= 502.4 cm³"
        },
        {
            "id": 3,
            "question": "A bag contains 5 red marbles, 3 blue marbles, and 2 green marbles. What is the probability of drawing a blue marble?",
            "options": ["3/10", "1/3", "3/8", "1/2"],
            "correct_answer": 0,
            "explanation": "Total marbles = 5 + 3 + 2 = 10\nBlue marbles = 3\nProbability = 3/10"
        },
        {
            "id": 4,
            "question": "If 3 pens cost $12, how much would 5 pens cost?",
            "options": ["$20", "$18", "$15", "$24"],
            "correct_answer": 0,
            "explanation": "Cost per pen = $12 ÷ 3 = $4\nCost for 5 pens = 5 × $4 = $20"
        },
        {
            "id": 5,
            "question": "A shirt originally priced at $40 is on sale for 25% off. What is the sale price?",
            "options": ["$30", "$35", "$32", "$28"],
            "correct_answer": 0,
            "explanation": "Discount = 25% of $40 = $10\nSale price = $40 - $10 = $30"
        },
        {
            "id": 6,
            "question": "In a right triangle, if one angle is 30°, what is the measure of the other acute angle?",
            "options": ["60°", "45°", "90°", "30°"],
            "correct_answer": 0,
            "explanation": "Sum of angles in a triangle = 180°\nRight angle = 90°\nOther acute angle = 180° - 90° - 30° = 60°"
        },
        {
            "id": 7,
            "question": "Simplify: (2x² + 3x - 5) + (x² - 4x + 2)",
            "options": ["3x² - x - 3", "3x² + 7x - 3", "x² - x - 3", "3x² - x + 3"],
            "correct_answer": 0,
            "explanation": "Combine like terms:\n(2x² + x²) + (3x - 4x) + (-5 + 2)\n= 3x² - x - 3"
        },
        {
            "id": 8,
            "question": "What is the area of a triangle with base 8 cm and height 6 cm?",
            "options": ["24 cm²", "48 cm²", "32 cm²", "16 cm²"],
            "correct_answer": 0,
            "explanation": "Area of triangle = (base × height) ÷ 2\n= (8 × 6) ÷ 2\n= 48 ÷ 2\n= 24 cm²"
        },
        {
            "id": 9,
            "question": "If a recipe calls for 2 cups of flour for 12 cookies, how many cups are needed for 30 cookies?",
            "options": ["5 cups", "4 cups", "6 cups", "3 cups"],
            "correct_answer": 0,
            "explanation": "Flour per cookie = 2 cups ÷ 12 = 1/6 cup\nFor 30 cookies = 30 × 1/6 = 5 cups"
        },
        {
            "id": 10,
            "question": "A bank offers 5% simple interest per year. If you deposit $1000, how much interest will you earn in 3 years?",
            "options": ["$150", "$157.63", "$165", "$175"],
            "correct_answer": 0,
            "explanation": "Simple Interest = Principal × Rate × Time\n= $1000 × 0.05 × 3\n= $150"
        }
    ]
    return question_pool

def load_env():
    """Load environment variables from .env file if it exists"""
    try:
        # Try to load from .env file first
        load_dotenv()
        app.logger.info("Successfully loaded .env file")
    except Exception as e:
        # If .env file doesn't exist, that's okay - we'll use environment variables
        app.logger.info("No .env file found, using environment variables")
    
    # Set default values for required environment variables
    required_vars = {
        'FLASK_APP': 'app.py',
        'FLASK_DEBUG': '0',
        'SECRET_KEY': os.getenv('SECRET_KEY', secrets.token_hex(32)),
        'DATABASE_URL': os.getenv('DATABASE_URL', 'sqlite:///maths_exam.db'),
        'OPENROUTER_API_KEY': os.getenv('OPENROUTER_API_KEY'),
        'PORT': os.getenv('PORT', '5000')
    }
    
    # Check for missing required variables
    missing_vars = [var for var, value in required_vars.items() if value is None]
    if missing_vars:
        app.logger.warning(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Set Flask configuration
    app.config['SECRET_KEY'] = required_vars['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = required_vars['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Log configuration (without sensitive values)
    app.logger.info("Application configuration:")
    app.logger.info(f"FLASK_APP: {required_vars['FLASK_APP']}")
    app.logger.info(f"FLASK_DEBUG: {required_vars['FLASK_DEBUG']}")
    app.logger.info(f"DATABASE_URL: {required_vars['DATABASE_URL']}")
    app.logger.info(f"PORT: {required_vars['PORT']}")
    app.logger.info("SECRET_KEY and OPENROUTER_API_KEY are set")

# Load environment variables
load_env()

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Start the application
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 