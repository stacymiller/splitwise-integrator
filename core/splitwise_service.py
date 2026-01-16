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
        self._current_user_id = None

    def get_current_user_id(self):
        """Get the current user ID, cached"""
        if self._current_user_id is None:
            self._current_user_id = self.client.getCurrentUser().getId()
        return self._current_user_id

    def set_oauth2_token(self, access_token):
        """Set the OAuth2 token in the Splitwise client"""
        self.access_token = access_token
        self.client.setOAuth2AccessToken(access_token)
        self._current_user_id = None  # Reset cached user ID
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

    def get_expenses(self, limit=20):
        """Get the most recent expenses for the current group"""
        expenses = self.client.getExpenses(group_id=int(self.current_group_id), limit=limit)
        return expenses

    def get_representative_examples(self, limit=50):
        """Get representative examples as ReceiptInfo objects"""
        expenses = self.get_expenses(limit=limit)
        
        raw_data = []
        for e in expenses:
            if e.getDeletedAt():
                continue
            
            # Extract basic info
            category_obj = e.getCategory()
            category_name = next((c['name'] for c in self.get_categories() if c['id'] == category_obj.getId()), category_obj.getName())
            
            # Determine split info
            split_info = self._get_split_details(e)
            
            # Create ReceiptInfo object matching the schema
            receipt_info = ReceiptInfo(
                date=ReceiptInfo._coerce_date(e.getDate()),
                total=e.getCost(),
                merchant=e.getDescription(),
                currency_code=e.getCurrencyCode(),
                notes=e.getDetails(),
                category=category_name,
                split_option=split_info["split_option"],
                users=split_info["users"]
            )
            raw_data.append(receipt_info)

        if not raw_data:
            return []

        # Selection Logic: Prioritize variety
        seen_merchants = set()
        seen_categories = set()
        seen_splits = set()
        
        representative = []
        for ri in raw_data:
            m, c, s = ri.merchant, ri.category, ri.split_option
            if m not in seen_merchants or c not in seen_categories or s not in seen_splits:
                representative.append(ri)
                seen_merchants.add(m)
                seen_categories.add(c)
                seen_splits.add(s)
            
            if len(representative) >= 15:
                break
                
        return representative

    def _get_split_details(self, expense: Expense):
        """Internal helper for example generation"""
        is_split_equally = True
        users = expense.getUsers()
        if not users:
            return {"split_option": "equal", "users": []}

        equal_split = float(expense.getCost()) / len(users)

        users_shares = []
        for u in users:
            paid_share = float(u.getPaidShare())
            owed_share = float(u.getOwedShare())
            users_shares.append({
                "user_id": u.getId(),
                "paid_share": paid_share,
                "owed_share": owed_share
            })
            if abs(owed_share - equal_split) > 0.01:
                is_split_equally = False

        return {"split_option": "equal" if is_split_equally else "exact", "users": users_shares}

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
        is_equal = receipt_info.split_option == 'equal'
        expense.setSplitEqually(is_equal)
        if not is_equal:
            for user_data in receipt_info.users:
                user = ExpenseUser()
                user.setId(user_data['user_id'])
                user.setPaidShare(user_data['paid_share'])
                user.setOwedShare(user_data['owed_share'])
                expense.addUser(user)

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
        user_mapping = {u['id']: u['name'] for u in self.get_users()}
        human_readable = f"Receipt Details:\n{receipt_info.to_summary(user_mapping)}"

        return {
            'expense_id': expense_response.getId(),
            'receipt_info': receipt_info.to_dict(),
            'human_readable_confirmation': human_readable
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
