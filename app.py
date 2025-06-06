import logging
import os
import mimetypes
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, session, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import splitwise
from splitwise.expense import Expense
from splitwise.user import ExpenseUser
from PIL import Image
import openai
import json
import requests
import secrets
import base64
import io
import PyPDF2
import pillow_heif

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = secrets.token_hex(16)  # Required for session management

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Splitwise client
splitwise_client = splitwise.Splitwise(
    os.getenv('SPLITWISE_CONSUMER_KEY'),
    os.getenv('SPLITWISE_CONSUMER_SECRET')
)

# Initialize OpenAI client
openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Load categories
CATEGORIES = []
def init_categories():
    for category in splitwise_client.getCategories():
        CATEGORIES.append({'id': category.getId(), 'name': category.getName(), 'object': category})
        for subcat in category.getSubcategories():
            CATEGORIES.append({'id': subcat.getId(), 'name': f'{category.getName()} / {subcat.getName()}', 'object': subcat})

USERS = []
def init_users():
    user_ids = os.getenv('SPLITWISE_PARTNER_IDS').split(',')
    for user_id in user_ids:
        splitwise_user = splitwise_client.getUser(int(user_id))
        user = ExpenseUser()
        user.setId(splitwise_user.getId())
        USERS.append({'id': splitwise_user.getId(), 'name': splitwise_user.getFirstName() + ' ' + splitwise_user.getLastName(), 'object': user})

def get_category(category_name) -> splitwise.Category:
    if not CATEGORIES:
        init_categories()
    for cat in CATEGORIES:
        if category_name in cat['name']:
            return cat['object']
    return None

def attach_receipt_to_expense(expense_id, receipt_path):
    """Attach a receipt to an existing expense using the Splitwise API"""
    url = f"https://secure.splitwise.com/api/v3.0/update_expense/{expense_id}"
    print(url)

    # Get the access token from the session
    access_token = session.get('oauth2_access_token')
    if not access_token:
        raise Exception("Not authenticated with Splitwise")

    headers = {
        "Authorization": f"Bearer {access_token['access_token']}",
        "Accept": "application/json"
    }

    with open(receipt_path, 'rb') as receipt_file:
        files = {
            "receipt": receipt_file
        }

        response = requests.post(url, headers=headers, files=files)

        if response.status_code != 200:
            raise Exception(f"Failed to attach receipt: {response.text}")

        return response.json()

def extract_receipt_info(file_path):
    """Extract information from receipt using OpenAI's vision model"""
    if not CATEGORIES:
        init_categories()
    categories_str = ", ".join(cat['name'] for cat in CATEGORIES)

    # Determine file type
    mime_type, _ = mimetypes.guess_type(file_path)
    is_pdf = mime_type == 'application/pdf'

    # Prepare content for OpenAI API
    content_items = []

    # Common prompt for both image and PDF
    initial_prompt = (
        "Extract the following information from this receipt: "
        "date, total amount, merchant name, currency code, and category. If the merchant is part of the store chain, like Jumbo or Albert Heijn, include only the chain name."
        "Return ONLY valid JSON with the following keys: "
        "'date' (in ISO format with as many details as possible), "
        "'total' (as a string, using a dot as decimal separator), "
        "'merchant' (as description), "
        "'currency_code' (e.g., 'EUR', 'USD'), "
        "'notes' (if there are any specific notes like invoice number, payment period, the name of a specific store from the chain, etc.; also include the generic description of the expense if this is something different from groceries)"
        "'category' (one of the following exact category names, choose the most appropriate):\n" +
        categories_str + "\n\n"
        "DO NOT INCLUDE any explanation, markdown, or extra text. "
        "Example: "
        "{\"date\": \"2024-01-01T16:45\", \"total\": \"12.34\", \"merchant\": \"Store Name\", \"currency_code\": \"EUR\", \"category\": \"Food & Drink / Groceries\"}"
    )

    content_items.append({
        "type": "text",
        "text": initial_prompt
    })

    if is_pdf:
        # Handle PDF file
        content_item = handle_pdf(file_path)
    else:
        content_item = handle_image(file_path)
    content_items.append(content_item)

    # Call OpenAI API
    response = openai_client.chat.completions.create(
        model="gpt-4o",  # Using gpt-4o as it supports both image and PDF inputs
        messages=[
            {
                "role": "user",
                "content": content_items
            }
        ],
        max_tokens=300
    )

    try:
        json_str = response.choices[0].message.content
        if json_str.startswith("```json"):
            json_str = json_str[len("```json"):]
        if json_str.endswith("```"):
            json_str = json_str[:-len("```")]
        return json.loads(json_str)
    except:
        logging.error(f"Error parsing response: {response.choices[0].message.content}")
        return None


def handle_image(file_path):
    file_lower = file_path.lower()
    if file_lower.endswith('.heic') or file_lower.endswith('.heif'):
        try:
            heif_file = pillow_heif.read_heif(file_path)
            img = Image.frombytes(
                heif_file.mode,
                heif_file.size,
                heif_file.data,
                "raw",
                heif_file.mode,
                heif_file.stride,
            )
        except Exception as e:
            logging.error(f"Error processing HEIC file: {str(e)}")
            raise ValueError(f"Failed to process HEIC file: {str(e)}")
    else:
        img = Image.open(file_path)
    try:
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_str}"
            }
        }
    finally:
        img.close()


def handle_pdf(file_path):
    with open(file_path, 'rb') as file:
        # Read the PDF file
        # pdf_reader = PyPDF2.PdfReader(file)

        # Encode the PDF file as base64
        file.seek(0)
        pdf_bytes = file.read()
        pdf_base64 = base64.b64encode(pdf_bytes).decode()

        # Add the data URL prefix required by OpenAI API
        pdf_data_url = f"data:application/pdf;base64,{pdf_base64}"

        # Add the PDF file to the content items
        return {
            "type": "file",
            "file": {
                "filename": os.path.basename(file_path),
                "file_data": pdf_data_url
            }
        }


def is_authenticated():
    """Check if the user is authenticated with Splitwise"""
    return 'oauth2_access_token' in session

def set_oauth2_token():
    """Set the OAuth2 token in the Splitwise client"""
    if is_authenticated():
        splitwise_client.setOAuth2AccessToken(session['oauth2_access_token'])
        return True
    return False

@app.route('/authorize')
def authorize():
    """Initiate the OAuth2 authorization flow"""
    # Generate the authorization URL
    redirect_uri = url_for('callback', _external=True)
    auth_url, state = splitwise_client.getOAuth2AuthorizeURL(redirect_uri)

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
    access_token = splitwise_client.getOAuth2AccessToken(code, redirect_uri)

    if not access_token:
        return jsonify({'error': 'Failed to get access token'}), 400

    # Store the access token in the session
    session['oauth2_access_token'] = access_token

    # Set the access token in the Splitwise client
    splitwise_client.setOAuth2AccessToken(access_token)

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
    if not CATEGORIES:
        # Initialize categories if not already done
        if is_authenticated():
            set_oauth2_token()
        init_categories()
    result = [dict(id=c['id'], name=c['name']) for c in sorted(CATEGORIES, key=lambda c: c['name'].lower())]
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
    receipt_info = extract_receipt_info(filepath)
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
            if hasattr(e, 'http_body'):
                error_message = json.loads(e.http_body)
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
        # Create expense object
        expense = Expense()
        expense.setCost(receipt_info['total'])
        expense.setDescription(receipt_info['merchant'])

        # Handle date format from the form (YYYY-MM-DDThh:mm) or from LLM (ISO format)
        try:
            # Try parsing as ISO format first
            timestamp = datetime.fromisoformat(receipt_info['date'])
        except ValueError:
            # If that fails, try parsing as YYYY-MM-DDThh:mm
            timestamp = datetime.strptime(receipt_info['date'], '%Y-%m-%dT%H:%M')

        timestamp = timestamp.astimezone()
        expense.setDate(timestamp.isoformat(timespec='seconds'))

        expense.setGroupId(int(os.getenv('SPLITWISE_GROUP_ID')))
        expense.setCurrencyCode(receipt_info['currency_code'])
        expense.setSplitEqually(True)

        if 'notes' in receipt_info and receipt_info['notes']:
            expense.setDetails(receipt_info['notes'])

        # Set category if available
        if 'category' in receipt_info and receipt_info['category']:
            category = get_category(receipt_info['category'])
            expense.setCategory(category)

        # Create the expense
        expense_response, errors = splitwise_client.createExpense(expense)

        if errors:
            return jsonify({'error': str(errors)}), 500

        # Attach the receipt to the expense
        try:
            attach_receipt_to_expense(expense_response.getId(), filepath)
        except Exception as e:
            # Log the error but don't fail the whole request
            print(f"Failed to attach receipt: {str(e)}")

        # Create a human-readable confirmation message
        human_readable = f"""
Receipt Details:
- Merchant: {receipt_info['merchant']}
- Amount: {receipt_info['total']} {receipt_info['currency_code']}
- Date: {timestamp.strftime('%B %d, %Y, %H:%M')}
- Category: {receipt_info.get('category', 'Not available')}
- Notes: {receipt_info.get('notes', 'Not available')}
"""

        return jsonify({
            'success': True,
            'expense_id': expense_response.getId(),
            'receipt_info': receipt_info,
            'human_readable_confirmation': human_readable.strip()
        })
    except Exception as e:
        error_message = str(e)
        if hasattr(e, 'http_body'):
            error_message = json.loads(e.http_body)
        return jsonify({'error': error_message}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) 
