"""
One-time OAuth2 setup for Gmail API access.
Run this once: python src/auth_setup.py
It opens a browser for Google sign-in and saves the token.
"""

import os
import yaml
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

def setup_auth():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    scopes = config['gmail']['scopes']

    for account in config['gmail']['accounts']:
        email = account['email']
        creds_path = os.path.join(os.path.dirname(__file__), '..', account['credentials_path'])
        token_path = os.path.join(os.path.dirname(__file__), '..', account['token_path'])

        print(f"\nSetting up auth for account: {email}")

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("Refreshing expired token...")
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_path):
                    print(f"ERROR: {creds_path} not found.")
                    print("Download your OAuth2 client secret from Google Cloud Console")
                    print("and save it as credentials/client_secret.json")
                    continue

                print(f"Opening browser for Google sign-in — please sign into {email} ...")
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes)
                creds = flow.run_local_server(port=0)

            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            print(f"Token saved to {token_path}")
        else:
            print(f"Token for {email} is already valid.")

    print("\nGmail API authentication is ready for all accounts!")

if __name__ == '__main__':
    setup_auth()
