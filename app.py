import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import logging
import traceback
import requests
from dotenv import load_dotenv
import secrets
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
QUESTIONS_FILE = os.path.join(DATA_DIR, 'questions.json')
TESTS_FILE = os.path.join(DATA_DIR, 'tests.json')

def load_json_file(file_path, default=[]):
    """Load data from a JSON file"""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {file_path}: {str(e)}")
    return default

def save_json_file(file_path, data):
    """Save data to a JSON file"""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving to {file_path}: {str(e)}")
        return False

def init_data():
    """Initialize data files if they don't exist"""
    if not os.path.exists(QUESTIONS_FILE):
        save_json_file(QUESTIONS_FILE, [])
    if not os.path.exists(TESTS_FILE):
        save_json_file(TESTS_FILE, [])

# Initialize data files
init_data()

# Add fromjson filter to Jinja2
@app.template_filter('fromjson')
def fromjson_filter(value):
    return json.loads(value)

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_test', methods=['GET'])
def start_test():
    try:
        logger.info("Starting new test generation")
        
        # Generate or get questions
        try:
            questions = generate_questions()
            if not questions:
                logger.error("No questions generated")
                flash('Failed to generate questions. Please try again.', 'error')
                return redirect(url_for('index'))
            logger.info(f"Generated {len(questions)} questions")
        except Exception as e:
            logger.error(f"Error generating questions: {str(e)}", exc_info=True)
            flash('An error occurred while generating questions. Please try again.', 'error')
            return redirect(url_for('index'))
        
        try:
            # Create a new test
            tests = load_json_file(TESTS_FILE)
            test_id = len(tests) + 1
            test = {
                'id': test_id,
                'score': 0,
                'total_questions': len(questions),
                'percentage': 0.0,
                'completed': False,
                'questions_used': [q['id'] for q in questions],
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Save questions to questions.json
            existing_questions = load_json_file(QUESTIONS_FILE)
            for q in questions:
                if 'id' not in q:
                    q['id'] = len(existing_questions) + 1
                    existing_questions.append(q)
            save_json_file(QUESTIONS_FILE, existing_questions)
            
            # Save test to tests.json
            tests.append(test)
            save_json_file(TESTS_FILE, tests)
            
            logger.info(f"Created new test with ID: {test_id}")
            return render_template('test.html', test_id=test_id, questions=questions)
            
        except Exception as e:
            logger.error(f"Error creating test: {str(e)}", exc_info=True)
            flash('An error occurred while creating the test. Please try again.', 'error')
            return redirect(url_for('index'))
            
    except Exception as e:
        logger.error(f"Unexpected error in start_test: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('index'))

@app.route('/submit_test', methods=['POST'])
def submit_test():
    try:
        # Get test ID from form
        test_id = int(request.form.get('test_id'))
        if not test_id:
            logger.error("No test_id provided in form data")
            return "Test ID not provided", 400
            
        logger.info(f"Processing submission for test {test_id}")
        
        # Get test from tests.json
        tests = load_json_file(TESTS_FILE)
        test = next((t for t in tests if t['id'] == test_id), None)
        if not test:
            logger.error(f"Test {test_id} not found")
            return "Test not found", 404
            
        # Get answers from form
        answers = {}
        for key, value in request.form.items():
            if key.startswith('answer_'):
                question_id = int(key.replace('answer_', ''))
                answers[question_id] = value
                
        logger.info(f"Collected answers: {answers}")
        
        # Calculate score
        score = 0
        results = {}
        
        # Get questions from questions.json
        questions = load_json_file(QUESTIONS_FILE)
        for q_id in test['questions_used']:
            question = next((q for q in questions if q['id'] == q_id), None)
            if not question:
                continue
                
            user_answer = answers.get(q_id)
            correct = user_answer == question['correct_answer']
            
            if correct:
                score += 1
                
            results[q_id] = {
                'question': question['question'],
                'user_answer': user_answer,
                'correct_answer': question['correct_answer'],
                'is_correct': correct,
                'explanation': question['explanation']
            }
            
        logger.info(f"Calculated score: {score}/{len(test['questions_used'])}")
        
        # Update test with score
        test['score'] = score
        test['percentage'] = (score / len(test['questions_used'])) * 100
        test['completed'] = True
        
        # Save updated test
        tests = [t if t['id'] != test_id else test for t in tests]
        save_json_file(TESTS_FILE, tests)
        
        # Save test results to session
        session['test_results'] = {
            'test_id': test_id,
            'score': score,
            'total_questions': len(test['questions_used']),
            'percentage': test['percentage'],
            'timestamp': test['timestamp'],
            'results': results
        }
        
        return render_template('results.html', test=test, results=results)
        
    except Exception as e:
        logger.error(f"Unexpected error in submit_test: {str(e)}", exc_info=True)
        return "An error occurred while submitting the test", 500

@app.route('/results')
def results():
    # Get test results from session
    test_results = session.get('test_results')
    if not test_results:
        flash('No test results found.', 'error')
        return redirect(url_for('start_test'))
    
    # Get the test from tests.json
    tests = load_json_file(TESTS_FILE)
    test = next((t for t in tests if t['id'] == test_results['test_id']), None)
    if test is None:
        flash('Test not found', 'error')
        return redirect(url_for('index'))
    
    return render_template('results.html', test=test, results=test_results['results'])

def generate_questions():
    try:
        # Check if we have enough questions in questions.json
        existing_questions = load_json_file(QUESTIONS_FILE)
        if len(existing_questions) >= 10:
            # Select 10 random questions
            selected_questions = random.sample(existing_questions, 10)
            return [{
                'id': q['id'],
                'question_text': q['question'],
                'options': q['options'],
                'correct_answer': q['correct_answer'],
                'explanation': q['explanation']
            } for q in selected_questions]

        # If not enough questions, generate new ones using OpenRouter
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            logger.warning("Please set OPENROUTER_API_KEY environment variable")
            return get_fallback_questions()

        logger.info("OpenRouter API key found in environment variables")
        logger.info(f"API key (masked): {api_key[:3]}...{api_key[-4:]}")

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
                    "question_text": "The question text",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_answer": "A",  // Must be A, B, C, or D
                    "explanation": "Step-by-step explanation of the solution"
                }
                
                Do not include any additional text, explanations, or formatting. Return ONLY the JSON array.'''
            }]
        }

        logger.debug(f"API request data: {json.dumps(data, indent=2)}")

        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers=headers,
            json=data
        )

        logger.debug(f"API response status code: {response.status_code}")
        logger.debug(f"API response headers: {response.headers}")
        logger.debug(f"API response text: {response.text}")

        if response.status_code == 200:
            try:
                response_data = response.json()
                logger.debug(f"Raw API response: {json.dumps(response_data, indent=2)}")
                
                # Check if response has the expected structure
                if 'choices' not in response_data:
                    logger.error("Invalid API response structure: missing 'choices'")
                    logger.error(f"Response keys: {list(response_data.keys())}")
                    logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                    return get_fallback_questions()
                
                if not response_data['choices']:
                    logger.error("Empty choices array in API response")
                    logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                    return get_fallback_questions()
                
                if 'message' not in response_data['choices'][0]:
                    logger.error("Invalid choice structure: missing 'message'")
                    logger.error(f"Choice structure: {json.dumps(response_data['choices'][0], indent=2)}")
                    return get_fallback_questions()
                
                # Extract the generated text from the response
                generated_text = response_data['choices'][0]['message']['content']
                logger.debug(f"Generated text: {generated_text}")
                
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
                    logger.error("Generated questions is not a list")
                    logger.error(f"Questions type: {type(questions)}")
                    return get_fallback_questions()
                
                if len(questions) != 10:
                    logger.error(f"Expected 10 questions, got {len(questions)}")
                    return get_fallback_questions()
                
                # Validate each question
                for i, q in enumerate(questions):
                    if not all(key in q for key in ['question_text', 'options', 'correct_answer', 'explanation']):
                        logger.error(f"Question {i+1} missing required fields")
                        logger.error(f"Question structure: {json.dumps(q, indent=2)}")
                        return get_fallback_questions()
                    
                    if not isinstance(q['options'], list) or len(q['options']) != 4:
                        logger.error(f"Question {i+1} has invalid options")
                        logger.error(f"Options: {q['options']}")
                        return get_fallback_questions()
                    
                    if q['correct_answer'] not in ['A', 'B', 'C', 'D']:
                        logger.error(f"Question {i+1} has invalid correct_answer")
                        logger.error(f"Correct answer: {q['correct_answer']}")
                        return get_fallback_questions()
                
                logger.info(f"Successfully generated and validated {len(questions)} questions")
                return questions
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing generated text: {str(e)}")
                logger.error(f"Generated text that failed to parse: {generated_text}")
                return get_fallback_questions()
            except Exception as e:
                logger.error(f"Error processing API response: {str(e)}")
                logger.error(f"Full response: {json.dumps(response_data, indent=2)}")
                return get_fallback_questions()
        else:
            logger.error(f"API request failed with status {response.status_code}")
            logger.error(f"Response: {response.text}")
            return get_fallback_questions()

    except Exception as e:
        logger.error(f"Unexpected error in generate_questions: {str(e)}", exc_info=True)
        return get_fallback_questions()

def get_fallback_questions():
    """Return a set of predefined questions when API generation fails"""
    logger.info("Using fallback questions")
    # Fallback question pool with grade 7/8 level questions
    question_pool = [
        {
            "id": 1,
            "question_text": "Solve for x: 2(3x - 5) = 4x + 8",
            "options": ["9", "7", "5", "3"],
            "correct_answer": "A",
            "explanation": "To solve 2(3x - 5) = 4x + 8:\n1. Distribute: 6x - 10 = 4x + 8\n2. Subtract 4x: 2x - 10 = 8\n3. Add 10: 2x = 18\n4. Divide by 2: x = 9"
        },
        {
            "id": 2,
            "question_text": "What is the volume of a cylinder with radius 4 cm and height 10 cm? (Use π = 3.14)",
            "options": ["502.4 cm³", "401.92 cm³", "314 cm³", "251.2 cm³"],
            "correct_answer": "A",
            "explanation": "Volume of cylinder = πr²h\n= 3.14 × 4² × 10\n= 3.14 × 16 × 10\n= 502.4 cm³"
        },
        {
            "id": 3,
            "question_text": "A bag contains 5 red marbles, 3 blue marbles, and 2 green marbles. What is the probability of drawing a blue marble?",
            "options": ["3/10", "1/3", "3/8", "1/2"],
            "correct_answer": "A",
            "explanation": "Total marbles = 5 + 3 + 2 = 10\nBlue marbles = 3\nProbability = 3/10"
        },
        {
            "id": 4,
            "question_text": "If 3 pens cost $12, how much would 5 pens cost?",
            "options": ["$20", "$18", "$15", "$24"],
            "correct_answer": "A",
            "explanation": "Cost per pen = $12 ÷ 3 = $4\nCost for 5 pens = 5 × $4 = $20"
        },
        {
            "id": 5,
            "question_text": "A shirt originally priced at $40 is on sale for 25% off. What is the sale price?",
            "options": ["$30", "$35", "$32", "$28"],
            "correct_answer": "A",
            "explanation": "Discount = 25% of $40 = $10\nSale price = $40 - $10 = $30"
        },
        {
            "id": 6,
            "question_text": "In a right triangle, if one angle is 30°, what is the measure of the other acute angle?",
            "options": ["60°", "45°", "90°", "30°"],
            "correct_answer": "A",
            "explanation": "Sum of angles in a triangle = 180°\nRight angle = 90°\nOther acute angle = 180° - 90° - 30° = 60°"
        },
        {
            "id": 7,
            "question_text": "Simplify: (2x² + 3x - 5) + (x² - 4x + 2)",
            "options": ["3x² - x - 3", "3x² + 7x - 3", "x² - x - 3", "3x² - x + 3"],
            "correct_answer": "A",
            "explanation": "Combine like terms:\n(2x² + x²) + (3x - 4x) + (-5 + 2)\n= 3x² - x - 3"
        },
        {
            "id": 8,
            "question_text": "What is the area of a triangle with base 8 cm and height 6 cm?",
            "options": ["24 cm²", "48 cm²", "32 cm²", "16 cm²"],
            "correct_answer": "A",
            "explanation": "Area of triangle = (base × height) ÷ 2\n= (8 × 6) ÷ 2\n= 48 ÷ 2\n= 24 cm²"
        },
        {
            "id": 9,
            "question_text": "If a recipe calls for 2 cups of flour for 12 cookies, how many cups are needed for 30 cookies?",
            "options": ["5 cups", "4 cups", "6 cups", "3 cups"],
            "correct_answer": "A",
            "explanation": "Flour per cookie = 2 cups ÷ 12 = 1/6 cup\nFor 30 cookies = 30 × 1/6 = 5 cups"
        },
        {
            "id": 10,
            "question_text": "A bank offers 5% simple interest per year. If you deposit $1000, how much interest will you earn in 3 years?",
            "options": ["$150", "$157.63", "$165", "$175"],
            "correct_answer": "A",
            "explanation": "Simple Interest = Principal × Rate × Time\n= $1000 × 0.05 × 3\n= $150"
        }
    ]
    return question_pool

def load_env():
    """Load environment variables from .env file if it exists"""
    try:
        # Try to load from .env file first
        load_dotenv()
        logger.info("Successfully loaded .env file")
    except Exception as e:
        # If .env file doesn't exist, that's okay - we'll use environment variables
        logger.info("No .env file found, using environment variables")
    
    # Set default values for required environment variables
    required_vars = {
        'FLASK_APP': 'app.py',
        'FLASK_DEBUG': '0',
        'SECRET_KEY': os.getenv('SECRET_KEY', secrets.token_hex(32)),
        'OPENROUTER_API_KEY': os.getenv('OPENROUTER_API_KEY'),
        'PORT': os.getenv('PORT', '5000')
    }
    
    # Check for missing required variables
    missing_vars = [var for var, value in required_vars.items() if value is None]
    if missing_vars:
        logger.warning(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Set Flask configuration
    app.config['SECRET_KEY'] = required_vars['SECRET_KEY']
    
    # Log configuration (without sensitive values)
    logger.info("Application configuration:")
    logger.info(f"FLASK_APP: {required_vars['FLASK_APP']}")
    logger.info(f"FLASK_DEBUG: {required_vars['FLASK_DEBUG']}")
    logger.info(f"PORT: {required_vars['PORT']}")
    logger.info("SECRET_KEY and OPENROUTER_API_KEY are set")

# Load environment variables
load_env()

if __name__ == '__main__':
    try:
        # Load environment variables
        load_env()
        
        # Initialize data files
        init_data()
        
        # Start the application
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {str(e)}", exc_info=True)
        raise 