import os
from dotenv import load_dotenv

load_dotenv()

# Gmail Configuration
GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
GMAIL_TOKEN_FILE = 'token.json'
GMAIL_CREDENTIALS_FILE = 'credentials.json'

# Job Application Keywords - customize as needed
JOB_KEYWORDS = [
    'applied',
    'application received',
    'thank you for applying',
    'job application',
    'submitted',
    'application submitted',
    'confirm your application',
    'received your application'
]

# Databricks Configuration
DATABRICKS_HOST = os.getenv('DATABRICKS_HOST')
DATABRICKS_TOKEN = os.getenv('DATABRICKS_TOKEN')
DATABRICKS_HTTP_PATH = os.getenv('DATABRICKS_HTTP_PATH', '/sql/1.0/warehouses/default')
DATABRICKS_CATALOG = os.getenv('DATABRICKS_CATALOG', 'default')
DATABRICKS_SCHEMA = os.getenv('DATABRICKS_SCHEMA', 'job_applications')
DATABRICKS_TABLE = os.getenv('DATABRICKS_TABLE', 'applications')

# API Configuration
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', 8000))
