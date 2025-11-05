# Flask Login Starter

A modern, secure Flask starter application with built-in authentication, SQLAlchemy integration, and a clean, responsive UI.

## Features

- User authentication system with Flask-Login
- SQLAlchemy database integration
- Secure password hashing
- Responsive Bootstrap 5 UI
- Form validation with WTForms
- Flash message support
- Testing setup with pytest
- Development and Production configurations
- Environment variable support
- Custom error handling
- Modern CSS with CSS variables

## Prerequisites

- Python 3.x
- pip (Python package manager)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd flask-login-starter
   ```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the root directory and add your configuration:
   ```
   FLASK_ENV=development
   SECRET_KEY=your-secret-key
   DATABASE_URL=your-database-url  # Required for production
   ```

## Database Setup

1. The application will automatically create a SQLite database in development mode
2. To create an admin user, run:
   ```bash
   python create_admin.py
   ```

## Running the Application

### Development

To run the application in development mode, use:

```bash
flask run
```
### Production

To run the application in production mode, use:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

## Testing

Run the test suite using pytest:

```bash
pytest
```
For coverage report:

```bash
pytest --cov=app
```

## Project Structure
flask-login-starter/
├── app.py # Application entry point
├── config.py # Configuration settings
├── models.py # Database models
├── forms.py # Form definitions
├── routes.py # Route handlers
├── requirements.txt # Project dependencies
├── static/
│ └── css/ # CSS stylesheets
├── templates/
│ ├── base.html # Base template
│ ├── login.html # Login page
│ └── index.html # Home page
└── tests/ # Test directory
```

## Configuration

The application supports three environments:
- Development (default)
- Testing
- Production

Configuration is handled in `config.py` and can be extended based on requirements.

## Security Features

- Password hashing using Werkzeug
- CSRF protection with Flask-WTF
- Secure session handling
- Environment-based configurations
- SQL injection prevention through SQLAlchemy

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.