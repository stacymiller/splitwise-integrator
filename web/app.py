import os
import secrets
import logging
import json
import base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from werkzeug.utils import secure_filename
import config
from bot.telegram_bot import TelegramBot
from core.receipt_processor import receipt_processor
from core.splitwise_service import splitwise_service
from core.receipt_info import ReceiptInfo

# Initialize Flask app
app = Flask(__name__, template_folder='../templates')
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['TEMPLATES_AUTO_RELOAD'] = config.TEMPLATES_AUTO_RELOAD
app.secret_key = secrets.token_hex(16)  # Required for session management

def is_authenticated():
    """Check if the user is authenticated with Splitwise"""
    return 'oauth2_access_token' in session

def set_oauth2_token():
    """Set the OAuth2 token in the Splitwise client"""
    if is_authenticated():
        splitwise_service.set_oauth2_token(session['oauth2_access_token'])
        return True
    return False

@app.route('/authorize')
def authorize():
    """Initiate the OAuth2 authorization flow"""
    # Generate the authorization URL
    redirect_uri = url_for('callback', _external=True)
    auth_url, state = splitwise_service.get_oauth2_authorize_url(redirect_uri)

    # Store the state in the session
    session['oauth2_state'] = state

    # Redirect the user to the authorization URL
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Handle the OAuth2 callback for both web app and Telegram users"""
    # Get the authorization code and state from the request
    code = request.args.get('code')
    state = request.args.get('state')

    if not code:
        return jsonify({'error': 'Missing code parameter'}), 400

    # Try to parse the state as JSON to extract user_id for Telegram flow
    user_id = None
    is_telegram_flow = False
    redirect_uri = f"{config.WEB_APP_URL}/callback"

    try:
        # First check if this is a Telegram flow by trying to parse the state as base64-encoded JSON
        # Decode the base64 string, then parse the JSON
        decoded_state = base64.b64decode(state).decode('utf-8')
        state_data = json.loads(decoded_state)
        if isinstance(state_data, dict) and 'user_id' in state_data:
            user_id = state_data['user_id']
            is_telegram_flow = True
    except (json.JSONDecodeError, TypeError, base64.binascii.Error):
        # If state is not valid base64-encoded JSON or doesn't contain user_id, assume it's a web app flow
        pass

    if is_telegram_flow:
        # Telegram bot flow
        if not user_id:
            return jsonify({'error': 'Missing user_id in state parameter'}), 400

        # Exchange the authorization code for an access token
        access_token = splitwise_service.get_oauth2_access_token(code, redirect_uri)

        if not access_token:
            return jsonify({'error': 'Failed to get access token'}), 400

        # Notify the Telegram bot that the user has authenticated
        try:
            TelegramBot.notify_user_authenticated(user_id, access_token)
        except Exception as e:
            logging.error(f"Error notifying Telegram bot: {str(e)}")

        # Return a success page for Telegram users
        return render_template('telegram_success.html')
    else:
        # Web app flow
        # Verify the state
        if state != session.get('oauth2_state'):
            return jsonify({'error': 'Invalid state parameter'}), 400

        # Exchange the authorization code for an access token
        redirect_uri = url_for('callback', _external=True)
        access_token = splitwise_service.get_oauth2_access_token(code, redirect_uri)

        if not access_token:
            return jsonify({'error': 'Failed to get access token'}), 400

        # Store the access token in the session
        session['oauth2_access_token'] = access_token

        # Set the access token in the Splitwise client
        splitwise_service.set_oauth2_token(access_token)

        # Redirect to the group selection page
        return redirect(url_for('index'))


@app.route('/select_group')
def select_group():
    """Show the group selection page"""
    # Check if the user is authenticated
    if not is_authenticated():
        return redirect(url_for('authorize'))

    # Set the OAuth2 token in the Splitwise client
    set_oauth2_token()

    # Get the list of groups
    groups = splitwise_service.get_groups()

    return render_template('select_group.html', groups=groups)

@app.route('/set_group', methods=['POST'])
def set_group():
    """Set the selected group"""
    # Check if the user is authenticated
    if not is_authenticated():
        return redirect(url_for('authorize'))

    # Get the selected group ID from the form
    group_id = request.form.get('group_id')
    if not group_id:
        return jsonify({'error': 'No group selected'}), 400

    # Store the selected group ID in the session
    session['splitwise_group_id'] = group_id

    # Set the group ID in the Splitwise service
    splitwise_service.set_current_group_id(group_id)

    # Redirect to the index page
    return redirect(url_for('index'))

@app.route('/check_auth')
def check_auth():
    """Check if a Telegram user is authenticated"""
    # Get the user_id from the request
    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'Missing user_id parameter'}), 400

    # Check if there's a temporary session for this user
    session_key = f"telegram_auth_{user_id}"
    if session_key in session:
        # Get the access token from the temporary session
        auth_data = session[session_key]
        access_token = auth_data.get('access_token')

        # Remove the temporary session
        session.pop(session_key, None)

        return jsonify({
            'authenticated': True,
            'access_token': access_token
        })

    # No temporary session found
    return jsonify({'authenticated': False})

@app.route('/telegram_logout')
def telegram_logout():
    """Logout a Telegram user"""
    # This endpoint is no longer needed as logout is handled by the bot
    # using context.user_data, but we keep it for backward compatibility
    return jsonify({'success': True, 'message': 'Logout is now handled by the bot'})

@app.route('/logout')
def logout():
    """Log out the user by clearing the session"""
    # Clear the session
    session.clear()

    # Redirect to the index page
    return redirect(url_for('index'))

@app.route('/categories')
def get_categories():
    """Return the list of categories as JSON"""
    if is_authenticated():
        set_oauth2_token()
    categories = splitwise_service.get_categories()
    result = [dict(id=c['id'], name=c['name']) for c in sorted(categories, key=lambda c: c['name'].lower())]
    return jsonify(result)

@app.route('/')
def index():
    try:
        # Check if the user is authenticated
        authenticated = is_authenticated()
        if authenticated:
            # Set the OAuth2 token in the Splitwise client
            set_oauth2_token()

            # Check if a group has been selected
            if 'splitwise_group_id' in session:
                # Set the group ID in the Splitwise service
                splitwise_service.set_current_group_id(session['splitwise_group_id'])
            elif not request.path.startswith('/select_group'):
                # If no group has been selected, redirect to the group selection page
                return redirect(url_for('select_group'))

        return render_template('index.html', authenticated=authenticated)
    except Exception as e:
        return f"Error rendering template: {str(e)}", 500

@app.route('/correct')
def correct():
    """Render a minimal Telegram Web App page to correct receipt fields.
    Expects an optional base64-url-encoded JSON in `data` query parameter to prefill fields.
    """
    try:
        return render_template('telegram_correction.html')
    except Exception as e:
        return f"Error rendering correction template: {str(e)}", 500

@app.route('/upload', methods=['POST'])
def upload_file():
    # Check if the user is authenticated
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated with Splitwise'}), 401

    # Set the OAuth2 token in the Splitwise client
    set_oauth2_token()

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        # Generate a unique filename to avoid collisions
        unique_prefix = secrets.token_urlsafe(10)
        filename = secure_filename(file.filename)
        unique_filename = f"{unique_prefix}-{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        # Return initial status to show progress spinner
        response = jsonify({
            'status': 'processing',
            'message': 'Parsing receipt details...',
            'filepath': filepath  # Return the actual filepath for subsequent requests
        })
        response.status_code = 202  # Accepted
        return response

@app.route('/process_receipt', methods=['POST'])
def process_receipt():
    # Check if the user is authenticated
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated with Splitwise'}), 401

    # Set the OAuth2 token in the Splitwise client
    set_oauth2_token()

    # Get the filepath from the request
    filepath = request.json.get('filepath')
    if not filepath:
        return jsonify({'error': 'No filepath provided'}), 400

    # Extract information from the image
    receipt_info = receipt_processor.extract_receipt_info(filepath)
    logging.info(f"Receipt info: {receipt_info}")

    if receipt_info:
        try:
            # Return status update for Splitwise processing
            response = jsonify({
                'status': 'processing',
                'message': 'Sending receipt to Splitwise...',
                'receipt_info': receipt_info.to_dict()
            })
            response.status_code = 202  # Accepted
            return response
        except Exception as e:
            error_message = str(e)
            return jsonify({'error': error_message}), 500
    else:
        return jsonify({'error': 'Could not extract information from receipt'}), 400

@app.route('/create_expense', methods=['POST'])
def create_expense():
    # Check if the user is authenticated
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated with Splitwise'}), 401

    # Set the OAuth2 token in the Splitwise client
    set_oauth2_token()

    # Get the receipt info and filepath from the request
    data = request.json
    receipt_info_data = data.get('receipt_info')
    filepath = data.get('filepath')

    if not receipt_info_data or not filepath:
        return jsonify({'error': 'Missing receipt information or filepath'}), 400

    try:
        # Convert incoming dict to ReceiptInfo
        receipt_info = ReceiptInfo.from_dict(receipt_info_data)
        # Create the expense using the Splitwise service
        result = splitwise_service.create_expense(receipt_info, filepath)

        return jsonify({
            'success': True,
            'expense_id': result['expense_id'],
            'receipt_info': result['receipt_info'],
            'human_readable_confirmation': result['human_readable_confirmation']
        })
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
