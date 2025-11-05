# Polaris

Make Volunteers your north Star

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
