"""Text alerts for design requests - supports email-to-SMS (no platform) or Twilio"""
# Carrier email-to-SMS gateways (no signup needed - uses your existing email)
CARRIER_GATEWAYS = {
    'verizon': 'vtext.com',
    'att': 'txt.att.net',
    'tmobile': 'tmomail.net',
    'sprint': 'messaging.sprintpcs.com',
    'uscellular': 'email.uscc.net',
    'cricket': 'sms.cricketwireless.net',
    'boost': 'sms.myboostmobile.com',
    'virgin': 'vmobl.com',
    'metro': 'mymetropcs.com',
}


def send_design_request_alert(app, customer_name, request_id):
    """Send text to admin when a new design request is submitted.
    Uses email-to-SMS (no platform) if carrier is set, otherwise Twilio if configured."""
    phone = ''.join(c for c in str(app.config.get('ADMIN_PHONE', '7852491464')) if c.isdigit())
    if len(phone) != 10:
        return False
    base_url = app.config.get('ADMIN_BASE_URL', 'http://localhost:5000')
    msg = f"Purposefully Made KC: New design request from {customer_name}! View: {base_url}/admin/custom-design-requests/{request_id}"

    # Option 1: Email-to-SMS (no extra platform - uses your existing Flask-Mail)
    carrier = app.config.get('ADMIN_PHONE_CARRIER', '').lower()
    if carrier and carrier in CARRIER_GATEWAYS and app.config.get('MAIL_SERVER'):
        try:
            from flask_mail import Message
            mail = app.extensions.get('mail')
            if mail:
                gateway = CARRIER_GATEWAYS[carrier]
                to_email = f"{phone}@{gateway}"
                email_msg = Message(
                    subject='Design Request',
                    body=msg,
                    recipients=[to_email]
                )
                mail.send(email_msg)
                return True
        except Exception:
            pass

    # Option 2: Twilio (if configured)
    if app.config.get('TWILIO_ACCOUNT_SID') and app.config.get('TWILIO_AUTH_TOKEN') and app.config.get('TWILIO_PHONE_NUMBER'):
        try:
            from twilio.rest import Client
            client = Client(app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
            client.messages.create(to='+1' + phone, from_=app.config['TWILIO_PHONE_NUMBER'], body=msg)
            return True
        except Exception:
            pass
    return False
