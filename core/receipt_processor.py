import datetime
import os
import mimetypes
import logging
import base64
import io
import json

import dateutil
from PIL import Image
import PyPDF2
import pillow_heif
import openai
import config
from core.splitwise_service import splitwise_service
from core.receipt_info import ReceiptInfo

class ReceiptProcessor:
    def __init__(self):
        self.openai_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    def extract_receipt_info(self, file_path) -> ReceiptInfo:
        """Extract information from receipt using OpenAI's vision model"""
        categories = splitwise_service.get_categories()
        categories_str = ", ".join(cat['name'] for cat in categories)

        # Determine file type
        mime_type, _ = mimetypes.guess_type(file_path)
        is_pdf = mime_type == 'application/pdf'

        # Prepare content for OpenAI API
        content_items = []

        # Common prompt for both image and PDF
        initial_prompt = (
            "Extract the following information from this receipt: "
            "date, total amount, merchant name, currency code, category, and how the expense should be split between two people in the current Splitwise group. If the merchant is part of a store chain (e.g., Jumbo, Albert Heijn), include only the chain name."
            "Receipt is relatively recent, today is " + datetime.datetime.now().strftime('%Y-%m-%d') + "."
            "Return ONLY valid JSON with the following keys: "
            "'date' (in ISO format with as many details as possible), "
            "'total' (as a string, using a dot as decimal separator), "
            "'merchant' (as description), "
            "'currency_code' (e.g., 'EUR', 'USD'), "
            "'notes' (if there are any specific notes like invoice number, payment period, the name of a specific store from the chain, etc.; also include the generic description of the expense if this is something different from groceries), "
            "'category' (one of the following exact category names, choose the most appropriate):\n" +
            categories_str + "\n\n"
            "DO NOT INCLUDE any explanation, markdown, or extra text. "
            "Example: "
            "{\"date\": \"" + datetime.datetime.now().strftime('%Y-%m-%dT%H:%M') + "\", \"total\": \"12.34\", \"merchant\": \"Store Name\", \"currency_code\": \"EUR\", \"category\": \"Food & Drink / Groceries\", \"splitOption\": \"equal\"}"
        )

        content_items.append({
            "type": "text",
            "text": initial_prompt
        })

        if is_pdf:
            # Handle PDF file
            content_item = self._handle_pdf(file_path)
        else:
            content_item = self._handle_image(file_path)
        content_items.append(content_item)

        # Call OpenAI API
        response = self.openai_client.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o as it supports both image and PDF inputs
            messages=[
                {
                    "role": "user",
                    "content": content_items
                }
            ],
            max_tokens=300
        )

        json_str = response.choices[0].message.content
        if json_str.startswith("```json"):
            json_str = json_str[len("```json"):]
        if json_str.endswith("```"):
            json_str = json_str[:-len("```")]
        result = json.loads(json_str)
        # Build strictly typed data class
        try:
            # Normalize date via dataclass constructor
            return ReceiptInfo.from_dict(result)
        except Exception as e:
            raise ValueError(f"Failed to parse receipt info JSON into ReceiptInfo: {e}")

    def _handle_image(self, file_path):
        """Process image files (including HEIC/HEIF)"""
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

    def _handle_pdf(self, file_path):
        """Process PDF files"""
        with open(file_path, 'rb') as file:
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

# Create a singleton instance
receipt_processor = ReceiptProcessor()