import boto3
from typing import Optional
from Tara.settings.default import *


def send_otp_email(to_email: str, otp_code: str, name: Optional[str] = None) -> None:
    """
    Send an OTP email using AWS SES with a professional HTML template.

    Args:
        to_email (str): Recipient's email address
        otp_code (str): The OTP code to send
        name (str, optional): Recipient's name for personalization
    """
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    sender_email = 'admin@tarafirst.com'  # Your verified SES sender email

    # Create HTML email template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Your OTP Code</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 0;
                background-color: #f4f4f4;
            }}
            .container {{
                max-width: 600px;
                margin: 20px auto;
                padding: 20px;
                background-color: #ffffff;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            .header {{
                text-align: center;
                padding: 20px 0;
                background-color: #007bff;
                color: white;
                border-radius: 5px 5px 0 0;
            }}
            .header h1 {{
                color: #f8f9fa;
            }}
            .content {{
                padding: 20px;
            }}
            .otp-code {{
                font-size: 32px;
                font-weight: bold;
                text-align: center;
                letter-spacing: 5px;
                color: #007bff;
                margin: 20px 0;
                padding: 15px;
                background-color: #f8f9fa;
                border-radius: 5px;
            }}
            .footer {{
                text-align: center;
                padding: 20px;
                color: #666;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Your OTP Code</h1>
            </div>
            <div class="content">
                <p>Hello {name if name else 'there'},</p>
                <p>Your One-Time Password (OTP) for account activation is:</p>
                <div class="otp-code">{otp_code}</div>
                <p>This OTP will expire in 10 minutes.</p>
                <p>If you didn't request this OTP, please ignore this email.</p>
            </div>
            <div class="footer">
                <p>This is an automated message, please do not reply to this email.</p>
                <p>&copy; 2024 TaraFirst. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Create plain text version for email clients that don't support HTML
    text_content = f"""
    Hello {name if name else 'there'},

    Your One-Time Password (OTP) for account activation is: {otp_code}

    This OTP will expire in 10 minutes.

    If you didn't request this OTP, please ignore this email.

    This is an automated message, please do not reply to this email.
    © 2024 TaraFirst. All rights reserved.
    """
    to_email = "contact@tarafirst.com"
    try:
        response = ses_client.send_email(
            Source=sender_email,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {
                    'Data': 'Your Account Activation OTP',
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': text_content,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': html_content,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        print(f"Email sent successfully! Message ID: {response['MessageId']}")
        return response
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        raise