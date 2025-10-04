import splitwise
from splitwise.expense import Expense
from splitwise.user import ExpenseUser
import requests
from datetime import datetime
import config
from core.receipt_info import ReceiptInfo

class SplitwiseService:
    def __init__(self):
        self.client = splitwise.Splitwise(
            config.SPLITWISE_CONSUMER_KEY,
            config.SPLITWISE_CONSUMER_SECRET
        )
        self.categories = []
        self.users = []
        self.access_token = None
        self.current_group_id = config.SPLITWISE_GROUP_ID  # Default group ID from config

    def set_oauth2_token(self, access_token):
        """Set the OAuth2 token in the Splitwise client"""
        self.access_token = access_token
        self.client.setOAuth2AccessToken(access_token)
        return True

    def set_current_group_id(self, group_id):
        """Set the current group ID"""
        self.current_group_id = group_id
        # Clear the users list to force reloading with the new group
        self.users = []
        return True

    def get_oauth2_authorize_url(self, redirect_uri, state=None):
        """Get the OAuth2 authorization URL"""
        return self.client.getOAuth2AuthorizeURL(redirect_uri, state)

    def get_oauth2_access_token(self, code, redirect_uri):
        """Exchange the authorization code for an access token"""
        return self.client.getOAuth2AccessToken(code, redirect_uri)

    def get_current_user(self):
        """Get the current user"""
        return self.client.getCurrentUser()

    def init_categories(self):
        """Initialize categories from Splitwise"""
        self.categories = []
        for category in self.client.getCategories():
            self.categories.append({'id': category.getId(), 'name': category.getName(), 'object': category})
            for subcat in category.getSubcategories():
                self.categories.append({'id': subcat.getId(), 'name': f'{category.getName()} / {subcat.getName()}', 'object': subcat})
        return self.categories

    def get_categories(self):
        """Get all categories"""
        if not self.categories:
            self.init_categories()
        return self.categories

    def get_category_by_name(self, category_name):
        """Get a category by name"""
        if not self.categories:
            self.init_categories()
        for cat in self.categories:
            if category_name in cat['name']:
                return cat['object']
        return None

    def init_users(self):
        """Initialize users from the specified group"""
        self.users = []
        group = self.client.getGroup(int(self.current_group_id))
        for splitwise_user in group.members:
            user = ExpenseUser()
            user.setId(splitwise_user.getId())
            self.users.append({
                'id': splitwise_user.getId(), 
                'name': splitwise_user.getFirstName() + ' ' + splitwise_user.getLastName(), 
                'object': user
            })
        return self.users

    def get_users(self):
        """Get all users in the group"""
        if not self.users:
            self.init_users()
        return self.users

    def get_groups(self):
        """Get all groups the user belongs to, sorted by number of participants (from one to many)"""
        groups = self.client.getGroups()
        # Sort groups by number of members (from one to many)
        sorted_groups = sorted(groups, key=lambda g: len(g.getMembers()))
        return [{'id': g.getId(), 'name': g.getName(), 'members_count': len(g.getMembers()), 'object': g} for g in sorted_groups]

    def create_expense(self, receipt_info: ReceiptInfo, filepath=None):
        """Create an expense in Splitwise"""
        # Create expense object
        expense = Expense()
        expense.setCost(receipt_info.total)
        expense.setDescription(receipt_info.merchant)

        if isinstance(receipt_info.date, datetime):
            expense.setDate(receipt_info.date.isoformat(timespec='seconds'))
        else:
            # fallback
            expense.setDate(str(receipt_info.date))

        expense.setGroupId(int(self.current_group_id))
        expense.setCurrencyCode(receipt_info.currency_code)

        # Handle split options
        split_option = receipt_info.splitOption
        if split_option:
            if not self.users:
                self.init_users()

            users = [user_data['object'] for user_data in self.users]

            if split_option == 'equal':
                # Split equally (default)
                expense.setSplitEqually(True)
            else:
                expense.setSplitEqually(False)
                if len(users) != 2:
                    raise ValueError(f'The group {self.current_group_id} contains {len(users)}. Custom splits are currently supported only for 2 users. Please adjust the split in the Splitwise app.')

                current_user_id = self.client.getCurrentUser().getId()
                current_user = [user for user in users if user.getId() == current_user_id]
                if not current_user:
                    raise ValueError(f'Could not find current user {current_user_id} among the members of the group {[user["id"] for user in self.users]}')

                current_user = current_user[0]
                other_user = [user for user in users if user.getId() != current_user_id][0]
                expense.addUser(current_user)
                expense.addUser(other_user)

                if split_option == 'youPaid' and receipt_info.theyOwe is not None:
                    current_user.setPaidShare(receipt_info.total)
                    current_user.setOwedShare(float(receipt_info.total) - float(receipt_info.theyOwe))
                    other_user.setPaidShare(0)
                    other_user.setOwedShare(receipt_info.theyOwe)
                elif split_option == 'theyPaid' and receipt_info.youOwe is not None:
                    current_user.setPaidShare(0)
                    current_user.setOwedShare(receipt_info.youOwe)
                    other_user.setPaidShare(receipt_info.total)
                    other_user.setOwedShare(float(receipt_info.total) - float(receipt_info.youOwe))
                elif split_option == 'percentage' and receipt_info.yourPercentage is not None:
                    your_percentage = float(receipt_info.yourPercentage)
                    their_percentage = 100 - your_percentage

                    total_amount = float(receipt_info.total)
                    your_share = (your_percentage / 100) * total_amount
                    their_share = (their_percentage / 100) * total_amount

                    current_user.setPaidShare(receipt_info.total)
                    current_user.setOwedShare(your_share)
                    other_user.setPaidShare(0)
                    other_user.setOwedShare(their_share)
                else:
                    # Default to equal split if split option is not recognized
                    expense.setSplitEqually(True)
        else:
            # Default to equal split if no split option is provided
            expense.setSplitEqually(True)

        if receipt_info.notes:
            expense.setDetails(receipt_info.notes)

        # Set category if available
        if receipt_info.category:
            category = self.get_category_by_name(receipt_info.category)
            expense.setCategory(category)

        # Create the expense
        expense_response, errors = self.client.createExpense(expense)

        if errors:
            raise Exception(str(errors))

        # Attach the receipt to the expense if filepath is provided
        if filepath:
            try:
                self.attach_receipt_to_expense(expense_response.getId(), filepath)
            except Exception as e:
                # Log the error but don't fail the whole request
                print(f"Failed to attach receipt: {str(e)}")

        # Create a human-readable confirmation message
        split_info = "Split equally (50/50)"
        if receipt_info.splitOption:
            if receipt_info.splitOption == 'youPaid' and receipt_info.theyOwe is not None:
                split_info = f"You paid, they owe {receipt_info.theyOwe} {receipt_info.currency_code}"
            elif receipt_info.splitOption == 'theyPaid' and receipt_info.youOwe is not None:
                split_info = f"They paid, you owe {receipt_info.youOwe} {receipt_info.currency_code}"
            elif receipt_info.splitOption == 'percentage' and receipt_info.yourPercentage is not None:
                your_percentage = float(receipt_info.yourPercentage)
                their_percentage = 100 - your_percentage
                split_info = f"Split by percentage: You {your_percentage}%, They {their_percentage}%"

        human_readable = f"""
Receipt Details:
- Merchant: {receipt_info.merchant}
- Amount: {receipt_info.total} {receipt_info.currency_code}
- Date: {receipt_info.date.strftime('%B %d, %Y, %H:%M')}
- Category: {receipt_info.category or 'Not available'}
- Notes: {receipt_info.notes or 'Not available'}
- Split: {split_info}
"""

        return {
            'expense_id': expense_response.getId(),
            'receipt_info': receipt_info.to_dict(),
            'human_readable_confirmation': human_readable.strip()
        }

    def attach_receipt_to_expense(self, expense_id, receipt_path):
        """Attach a receipt to an existing expense using the Splitwise API"""
        url = f"https://secure.splitwise.com/api/v3.0/update_expense/{expense_id}"

        if not self.access_token:
            raise Exception("Not authenticated with Splitwise")

        headers = {
            "Authorization": f"Bearer {self.access_token['access_token']}",
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

# Create a singleton instance
splitwise_service = SplitwiseService()
