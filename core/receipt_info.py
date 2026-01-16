from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Any, Dict


@dataclass
class ReceiptInfo:
    date: datetime
    total: str
    merchant: str
    currency_code: str
    # optional/extra fields collected from OCR or user corrections
    notes: Optional[str] = None
    category: Optional[str] = None
    split_option: str = "equal"
    users: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # ensure date serializable
        if isinstance(self.date, datetime):
            d['date'] = self.date.isoformat()
        # ensure notes and category are strings for schema consistency
        d['notes'] = self.notes or ""
        d['category'] = self.category or ""
        return d

    def to_summary(self, user_mapping: Optional[Dict[int, str]] = None) -> str:
        """Returns a human-readable summary of the receipt information."""
        if self.split_option == 'equal':
            split_summary = "Split equally"
        else:
            shares = []
            for u in self.users:
                try:
                    owed = float(u.get('owed_share', 0))
                except (ValueError, TypeError):
                    owed = 0
                
                if owed > 0:
                    user_id = u.get('user_id')
                    name = user_mapping.get(user_id) if user_mapping and user_id is not None else None
                    user_label = name if name else f"ID {user_id}"
                    shares.append(f"{user_label} owes {owed}")
            split_summary = "Custom split: " + ", ".join(shares) if shares else "Custom split"

        date_str = self.date.strftime('%B %d, %Y')
        if self.date.hour != 0 or self.date.minute != 0:
            date_str = self.date.strftime('%B %d, %Y, %H:%M')

        lines = [
            f"Merchant: {self.merchant}",
            f"Amount: {self.total} {self.currency_code}",
            f"Date: {date_str}",
            f"Category: {self.category or 'Not available'}",
            f"Notes: {self.notes or 'None'}",
            f"Split: {split_summary}"
        ]
        return "\n".join(f"- {line}" for line in lines)

    @staticmethod
    def get_json_schema() -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO format date"},
                "total": {"type": "string", "description": "Total amount as string"},
                "merchant": {"type": "string"},
                "currency_code": {"type": "string", "description": "3-letter currency code"},
                "notes": {"type": "string", "description": "Specific details or description"},
                "category": {"type": "string"},
                "split_option": {"type": "string", "enum": ["equal", "exact"]},
                "users": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer"},
                            "paid_share": {"type": "string", "description": "Amount this user paid"},
                            "owed_share": {"type": "string", "description": "Amount this user owes"}
                        },
                        "required": ["user_id", "paid_share", "owed_share"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["date", "total", "merchant", "currency_code", "notes", "category", "split_option", "users"],
            "additionalProperties": False
        }

    @staticmethod
    def _coerce_date(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                # try YYYY-MM-DD first
                return datetime.strptime(value, "%Y-%m-%d")
            except Exception:
                try:
                    return datetime.fromisoformat(value)
                except Exception:
                    pass
        # fallback to now
        return datetime.now()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReceiptInfo":
        # Normalize and coerce types
        date = cls._coerce_date(data.get('date'))

        currency_code = data.get('currency_code') or data.get('currencyCode') or 'EUR'
        if isinstance(currency_code, str):
            currency_code = currency_code.upper()

        total_raw = data.get('total', '0')
        try:
            total = str(float(total_raw))
        except Exception:
            total = str(total_raw)

        merchant = data.get('merchant') or 'Unknown'
        notes = data.get('notes')
        category = data.get('category')
        
        # Determine split_option
        split_option = data.get('split_option')
        if not split_option:
            # Fallback for legacy split_equally field
            split_option = 'equal' if data.get('split_equally', True) else 'exact'

        users = data.get('users', [])

        return cls(
            date=date,
            total=total,
            merchant=merchant,
            currency_code=currency_code,
            notes=notes,
            category=category,
            split_option=split_option,
            users=users
        )

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        updated = ReceiptInfo.from_dict({**self.to_dict(), **data})
        self.date = updated.date
        self.total = updated.total
        self.merchant = updated.merchant
        self.currency_code = updated.currency_code
        self.notes = updated.notes
        self.category = updated.category
        self.split_option = updated.split_option
        self.users = updated.users
