Welcome to the development guide for the Transcription API project. This document provides step-by-step instructions to set up your development environment and best practices for contributing to the project.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Setting Up the Development Environment](#setting-up-the-development-environment)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Create a Virtual Environment](#2-create-a-virtual-environment)
  - [3. Install Dependencies](#3-install-dependencies)
  - [4. Configure Environment Variables](#4-configure-environment-variables)
  - [5. Set Up Django Settings](#5-set-up-django-settings)
  - [6. Apply Migrations](#6-apply-migrations)
  - [7. Create a Superuser](#7-create-a-superuser)
  - [8. Run the Development Server](#8-run-the-development-server)
  - [9. Development Workflow](#9-development-workflow)

---

## Prerequisites

Before you begin, ensure you have the following installed on your system:

- Python 3.8 or higher
- Git
- pip (Python package installer)
- Virtualenv (optional but recommended)

## Project Structure

```
transcribe_project/
├── manage.py
├── transcribe_project/
│ ├── init.py
│ ├── settings.py
│ ├── urls.py
│ └── wsgi.py
├── transcribe_app/
│ ├── init.py
│ ├── admin.py
│ ├── apps.py
│ ├── migrations/
│ ├── models.py
│ ├── serializers.py
│ ├── tests.py
│ ├── transcribe_utils.py
│ ├── urls.py
│ └── views.py
├── templates/
│ └── registration/
│ └── login.html
└── requirements.txt
```

## Setting Up the Development Environment

### 1. Clone the Repository

Clone the project repository to your local machine:

```bash
git clone https://github.com/yourusername/transcribe_project.git
cd transcribe_project
```

### 2. Create a Virtual Environment
It's recommended to use a virtual environment to manage your Python dependencies.

```
python3 -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
```

### 3. Install Dependencies
Install the required Python packages using pip:

```
pip install -r requirements.txt
```

If requirements.txt does not exist, install the dependencies manually:
```
pip3 install django djangorestframework drf-yasg django-cors-headers numpy torch openai-whisper
```

### 4. Configure Environment Variables
Set the necessary environment variables for the Whisper model:

- WHISPER_SERVER_USE: Set to false to use local models.
- WHISPER_MODEL_FAST: The name of the fast Whisper model (e.g., small).
- WHISPER_MODEL_SMART: The name of the smart Whisper model (e.g., medium).

Create a .env file in the root directory:
```
WHISPER_SERVER_USE=false
WHISPER_MODEL_FAST=small
WHISPER_MODEL_SMART=medium
```

Load the environment variables:

```
export $(grep -v '^#' .env | xargs)
```

### 5. Set Up Django Settings
Ensure your settings.py file is correctly configured.

- SECRET_KEY: Generate a secret key for your Django project.
```
# transcribe_project/settings.py
SECRET_KEY = 'your-unique-secret-key'
```

Generate a secret key:
```
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

- DEBUG: Set to True for development.
```
DEBUG = True
```

- ALLOWED_HOSTS: Allow all hosts during development.
```
ALLOWED_HOSTS = ['*']
```

- INSTALLED_APPS: Ensure all necessary apps are included.
```
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_yasg',
    'corsheaders',
    'transcribe_app',
]
```

- MIDDLEWARE: Include required middleware.
```
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

- TEMPLATES: Configure template directories.
```
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
```

- DATABASES: Use SQLite for development.
```
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

- Static Files: Configure static files settings.
```
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
```

### 6. Apply Migrations
Run Django migrations to set up your database schema:

```
python3 manage.py makemigrations
python3 manage.py migrate
```

### 7. Create a Superuser
Create an admin account to access the Django admin interface:

```
python3 manage.py createsuperuser
```

Provide a username, email, and password when prompted.

### 8. Run the Development Server
Start the Django development server:
```
python3 manage.py runserver 0.0.0.0:5040
```

### 9. Development Workflow

#### Running the Application
- Ensure your virtual environment is activated.
- Run the development server using python3 manage.py runserver.

#### Accessing the Swagger UI
- Open your browser and navigate to http://localhost:5040/swagger/ to view the Swagger UI.
- If you need to log in, use the superuser credentials you created earlier.

#### Testing the API Endpoints
- Use tools like curl or Postman to test the API endpoints.
- For example, to test the transcribe endpoint:
```
curl -X POST http://localhost:5040/transcribe -H "Content-Type: application/json" -d '{"tenant_id": "test_tenant", "chunk_id": "12345", "audio": "base64-encoded-audio-data"}'
```
