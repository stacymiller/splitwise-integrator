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
    splitOption: Optional[str] = None  # 'equal' | 'youPaid' | 'theyPaid' | 'percentage'
    theyOwe: Optional[float] = None
    youOwe: Optional[float] = None
    yourPercentage: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # ensure date serializable
        if isinstance(self.date, datetime):
            d['date'] = self.date.isoformat()
        return d

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
        splitOption = data.get('splitOption') or data.get('split_option')

        def _to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except Exception:
                try:
                    return float(str(v).replace(',', '.'))
                except Exception:
                    return None

        theyOwe = _to_float(data.get('theyOwe'))
        youOwe = _to_float(data.get('youOwe'))
        yourPercentage = _to_float(data.get('yourPercentage'))

        return cls(
            date=date,
            total=total,
            merchant=merchant,
            currency_code=currency_code,
            notes=notes,
            category=category,
            splitOption=splitOption,
            theyOwe=theyOwe,
            youOwe=youOwe,
            yourPercentage=yourPercentage,
        )

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        updated = ReceiptInfo.from_dict({**self.to_dict(), **data})
        self.date = updated.date
        self.total = updated.total
        self.merchant = updated.merchant
        self.currency_code = updated.currency_code
        self.notes = updated.notes
        self.category = updated.category
        self.splitOption = updated.splitOption
        self.theyOwe = updated.theyOwe
        self.youOwe = updated.youOwe
        self.yourPercentage = updated.yourPercentage
