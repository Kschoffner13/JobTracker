import base64
import re
from typing import Optional, Dict, Any
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.api_python_client import discovery
from datetime import datetime
import config


class GmailMonitor:
    def __init__(self):
        self.service = None
        self.authenticate()
    
    def authenticate(self):
        """Authenticate with Gmail API using OAuth2"""
        creds = None
        
        # Load existing token if available
        if config.GMAIL_TOKEN_FILE and os.path.exists(config.GMAIL_TOKEN_FILE):
            creds = OAuthCredentials.from_authorized_user_file(config.GMAIL_TOKEN_FILE)
        
        # If no valid credentials, run the auth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.GMAIL_CREDENTIALS_FILE,
                    config.GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for future use
            with open(config.GMAIL_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        
        self.service = discovery.build('gmail', 'v1', credentials=creds)
    
    def get_messages_with_keywords(self) -> list:
        """Fetch recent emails containing job application keywords"""
        try:
            # Build search query with keywords
            keyword_query = ' OR '.join(config.JOB_KEYWORDS)
            query = f"({keyword_query}) is:unread"
            
            # Search for messages
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=10
            ).execute()
            
            messages = results.get('messages', [])
            return messages
        
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []
    
    def get_message_details(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Extract details from a single email message"""
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message['payload']['headers']
            
            # Extract basic info
            email_data = {
                'message_id': message_id,
                'from': self._get_header(headers, 'From'),
                'to': self._get_header(headers, 'To'),
                'subject': self._get_header(headers, 'Subject'),
                'date': self._get_header(headers, 'Date'),
                'timestamp': datetime.now().isoformat()
            }
            
            # Extract body
            body = self._get_message_body(message)
            email_data['body'] = body
            
            # Extract relevant information
            email_data['extracted_info'] = self._extract_job_info(body, email_data['subject'])
            
            return email_data
        
        except Exception as e:
            print(f"Error getting message details: {e}")
            return None
    
    def _get_header(self, headers: list, name: str) -> str:
        """Extract a specific header value"""
        for header in headers:
            if header['name'] == name:
                return header['value']
        return ''
    
    def _get_message_body(self, message: dict) -> str:
        """Extract the body text from a message"""
        try:
            if 'parts' in message['payload']:
                parts = message['payload']['parts']
                data = parts[0]['body'].get('data', '')
            else:
                data = message['payload']['body'].get('data', '')
            
            if data:
                text = base64.urlsafe_b64decode(data).decode('utf-8')
                return text
            return ''
        
        except Exception as e:
            print(f"Error extracting message body: {e}")
            return ''
    
    def _extract_job_info(self, body: str, subject: str) -> Dict[str, str]:
        """Extract relevant job application information from email"""
        info = {
            'company': self._extract_company(body, subject),
            'job_title': self._extract_job_title(body, subject),
            'application_status': self._extract_status(body),
            'application_url': self._extract_url(body),
            'keywords_found': self._find_keywords(body)
        }
        return info
    
    def _extract_company(self, body: str, subject: str) -> str:
        """Try to extract company name from email"""
        # Look in subject first
        subject_lower = subject.lower()
        for word in subject_lower.split():
            if len(word) > 3 and word not in config.JOB_KEYWORDS:
                return word.strip('.,')
        
        # Look for common patterns in body
        patterns = [
            r'(?:from|at|company|employer):\s*([A-Za-z\s&.,-]+)',
            r'(?:welcome to|thank you at)\s*([A-Za-z\s&.,-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return 'Unknown'
    
    def _extract_job_title(self, body: str, subject: str) -> str:
        """Try to extract job title from email"""
        patterns = [
            r'(?:position|role|title|applied for):\s*([A-Za-z\s-]+)',
            r'(?:for the|for)?\s*(?:position of|role of)?\s*([A-Za-z\s-]+?)(?:\s+(?:at|with|position|role))',
        ]
        for pattern in patterns:
            match = re.search(pattern, body + ' ' + subject, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return 'Not specified'
    
    def _extract_status(self, body: str) -> str:
        """Extract application status"""
        body_lower = body.lower()
        
        if 'rejected' in body_lower or 'not selected' in body_lower:
            return 'rejected'
        elif 'interview' in body_lower or 'next step' in body_lower:
            return 'interview'
        elif 'confirm' in body_lower or 'confirm your application' in body_lower:
            return 'pending'
        else:
            return 'received'
    
    def _extract_url(self, body: str) -> str:
        """Extract first URL from email"""
        url_pattern = r'https?://[^\s]+'
        match = re.search(url_pattern, body)
        return match.group(0) if match else ''
    
    def _find_keywords(self, body: str) -> list:
        """Find which job keywords are present in the email"""
        found = []
        body_lower = body.lower()
        for keyword in config.JOB_KEYWORDS:
            if keyword in body_lower:
                found.append(keyword)
        return found


import os
