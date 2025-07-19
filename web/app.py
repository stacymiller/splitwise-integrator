import os
import secrets
import logging
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from werkzeug.utils import secure_filename
import config
from core.receipt_processor import receipt_processor
from core.splitwise_service import splitwise_service

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
    """Handle the OAuth2 callback"""
    # Get the authorization code from the request
    code = request.args.get('code')
    state = request.args.get('state')

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

    # Redirect to the index page
    return redirect(url_for('index'))

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

        return render_template('index.html', authenticated=authenticated)
    except Exception as e:
        return f"Error rendering template: {str(e)}", 500

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
                'receipt_info': receipt_info
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
    receipt_info = data.get('receipt_info')
    filepath = data.get('filepath')

    if not receipt_info or not filepath:
        return jsonify({'error': 'Missing receipt information or filepath'}), 400

    try:
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