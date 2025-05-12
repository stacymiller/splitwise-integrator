# Splitwise Receipt Uploader

A simple web application that allows you to upload receipt photos and automatically create expenses in Splitwise using OCR powered by OpenAI's GPT-4 Vision model.

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root with the following variables:
```
# Splitwise API credentials
SPLITWISE_CONSUMER_KEY=your_consumer_key
SPLITWISE_CONSUMER_SECRET=your_consumer_secret
SPLITWISE_GROUP_ID=your_group_id

# OpenAI API credentials
OPENAI_API_KEY=your_openai_api_key
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to `http://localhost:5001`

5. Authenticate with Splitwise using OAuth2:
   - Click the "Login with Splitwise" button
   - You will be redirected to Splitwise to authorize the application
   - After authorization, you will be redirected back to the application

## How to Get API Credentials

### Splitwise API
1. Go to https://secure.splitwise.com/oauth_clients
2. Create a new OAuth application
   - Set the name and description for your application
   - Set the redirect URI to `http://localhost:5001/callback`
   - Set the OAuth version to "OAuth2"
3. After creating the application, you'll get a consumer key and consumer secret
4. Add these to your `.env` file
5. Get your group ID from the URL when viewing the group in Splitwise (e.g., `https://secure.splitwise.com/groups/33308485` - the group ID is 1234567)

### OpenAI API
1. Go to https://platform.openai.com/api-keys
2. Create a new API key

## Features

- Simple drag-and-drop interface for uploading receipt photos
- Automatic extraction of date, total amount, and merchant name using GPT-4 Vision
- Automatic creation of expenses in your specified Splitwise group
- Equal splitting of expenses among group members

## Notes

- The application currently supports image files (JPG, PNG)
- Maximum file size is 16MB
- The OCR is performed using OpenAI's GPT-4 Vision model
- All expenses are split equally among group members 
