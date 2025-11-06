# Polaris

Make Volunteers your north Star

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Polaris
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

4. Create a `.env` file in the root directory:
   ```bash
   # Copy the example file
   cp .env.example .env
   # Then edit .env and fill in your values
   ```

   See [Environment Configuration](#environment-configuration) below for details.

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

## Environment Configuration

Polaris uses environment variables for configuration. Copy `.env.example` to `.env` and customize the values.

### Required Variables (Production Only)

- **SECRET_KEY**: A secure random key for Flask sessions. Generate with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- **DATABASE_URL**: PostgreSQL connection string (e.g., `postgresql://user:password@localhost/dbname`)

### Optional Variables

Most variables have sensible defaults for development. See `.env.example` for:
- Monitoring and logging configuration
- Email alert settings
- Slack/Webhook integrations
- Sentry error tracking

**Note**: The application validates required environment variables at startup in production mode only.

## Development Tools

### Setup

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

### Code Formatting and Quality

The project uses several tools to maintain code quality:

- **black**: Code formatter
- **isort**: Import sorter
- **flake8**: Linter
- **mypy**: Type checker (optional)

### Pre-commit Hooks

Install pre-commit hooks to automatically format and lint code before commits:

```bash
pre-commit install
```

Hooks will run automatically on `git commit`. To run manually:

```bash
# Run on all files
pre-commit run --all-files

# Run on staged files only
pre-commit run
```

### Manual Tool Usage

You can also run tools manually:

```bash
# Format code
black .

# Sort imports
isort .

# Lint code
flake8 .

# Type check
mypy .
```

### Editor Configuration

The project includes `.editorconfig` for consistent formatting across editors. Most modern editors support EditorConfig automatically.

## Testing

Run the test suite using pytest:

```bash
pytest
```

For coverage report:

```bash
pytest --cov=flask_app --cov-report=html
```
