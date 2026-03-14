import os
import requests

BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
FROM_EMAIL = os.environ.get("FROM_EMAIL")

def send_otp(receiver_email, otp):
    url = "https://api.brevo.com/v3/smtp/email"

    payload = {
        "sender": {
            "email": FROM_EMAIL,
            "name": "ReTech"
        },
        "to": [
            {"email": receiver_email}
        ],
        "subject": "ReTech OTP Verification",
        "htmlContent": f"""
            <h3>Your ReTech OTP</h3>
            <p><strong>{otp}</strong></p>
            <p>This OTP is valid for 5 minutes.</p>
        """
    }

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code not in (200, 201):
        print("BREVO API ERROR:", response.text)
        raise Exception("Failed to send OTP")
