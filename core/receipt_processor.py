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
        
        # Get group members
        users = splitwise_service.get_users()
        users_list_str = "\n".join([f"- {u['name']} (ID: {u['id']})" for u in users])
        
        # Get representative examples from past transactions
        examples = splitwise_service.get_representative_examples()
        examples_str = ""
        if examples:
            formatted_examples = [ex.to_dict() for ex in examples]
            examples_str = "\nEXAMPLES OF PAST TRANSACTIONS (use these for consistency):\n"
            examples_str += json.dumps(formatted_examples, indent=2, ensure_ascii=False) + "\n"

        # Determine file type
        mime_type, _ = mimetypes.guess_type(file_path)
        is_pdf = mime_type == 'application/pdf'

        # Common prompt
        initial_prompt = (
            "Extract information from this receipt and determine the Splitwise expense details.\n\n"
            "GROUP MEMBERS:\n" + users_list_str + "\n\n"
            "CONSISTENCY RULES:\n"
            "1. Merchant Name: Use the chain name (e.g., 'Jumbo', 'Albert Heijn') if applicable.\n"
            "2. Category: Select from: " + categories_str + "\n"
            "3. Split Behavior: Follow patterns from examples if provided. Determine who paid and how it should be split among the group members listed above.\n"
            + examples_str +
            "\nToday is " + datetime.datetime.now().strftime('%Y-%m-%d') + ".\n"
        )

        content_items = [{"type": "text", "text": initial_prompt}]
        if is_pdf:
            content_items.append(self._handle_pdf(file_path))
        else:
            content_items.append(self._handle_image(file_path))

        # Define the expected JSON schema for Structured Outputs
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_info",
                "strict": True,
                "schema": ReceiptInfo.get_json_schema()
            }
        }

        # Call OpenAI API
        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content_items}],
            response_format=response_format,
            max_tokens=500
        )

        result = json.loads(response.choices[0].message.content)
        try:
            return ReceiptInfo.from_dict(result)
        except Exception as e:
            raise ValueError(f"Failed to parse receipt info: {e}")

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