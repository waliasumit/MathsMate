# Year 7 Maths Test Application

A web application for Year 7 students to practice mathematics based on the NSW curriculum. The application generates random questions using the DeepSeek model, tracks user progress, and provides detailed feedback.

## Features

- User authentication (signup/login)
- Random question generation using DeepSeek model
- 20 questions per test session
- Detailed feedback and explanations
- Progress tracking
- Test history dashboard
- Areas for improvement analysis

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd maths-test-app
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the required packages:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
Create a `.env` file in the root directory with the following content:
```
FLASK_APP=app.py
FLASK_ENV=development
DEEPSEEK_API_KEY=your_deepseek_api_key
```

## Running the Application

1. Initialize the database:
```bash
flask db init
flask db migrate
flask db upgrade
```

2. Run the application:
```bash
flask run
```

3. Open your web browser and navigate to `http://localhost:5000`

## Usage

1. Sign up for a new account or log in with existing credentials
2. Start a new test from the dashboard
3. Answer the 20 questions
4. Submit the test to receive detailed feedback
5. View your progress and test history in the dashboard

## Project Structure

```
maths-test-app/
├── app.py              # Main application file
├── requirements.txt    # Python dependencies
├── .env               # Environment variables
├── templates/         # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── signup.html
│   ├── test.html
│   ├── results.html
│   └── dashboard.html
└── README.md          # This file
```

## Contributing

1. Fork the repository
2. Create a new branch for your feature
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 