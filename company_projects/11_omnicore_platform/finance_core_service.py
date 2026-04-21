"""
OmniCore Platform — Finance Core Service
Domain: Financial accounting, general ledger, accounts payable/receivable
Language: Python (this file is the ML/analytics sidecar; main Go service handles CRUD)
Author: Timur Seitov (Data Science Lead)
Version: 0.8.3
Last Updated: 2025-02-15
"""

import os
import time
import json
import uuid
import logging
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import torch
import torch.nn as nn
from confluent_kafka import Producer, Consumer, KafkaException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import redis
import structlog

# ─── Configuration ───────────────────────────────────────────────────────────

logger = structlog.get_logger(__name__)

DB_URL = os.environ.get("FINANCE_DB_URL", "postgresql://omni:secret@localhost:5432/omni_finance")
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
ML_MODEL_PATH = os.environ.get("ML_MODEL_PATH", "/models/finance")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
SERVICE_VERSION = "0.8.3"
SERVICE_NAME = "finance-core-ml"

# ─── Domain Enums ─────────────────────────────────────────────────────────────

class TransactionType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class JournalEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"

class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"

class AnomalyType(str, Enum):
    UNUSUAL_AMOUNT = "UNUSUAL_AMOUNT"
    UNUSUAL_TIME = "UNUSUAL_TIME"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    ROUND_TRIPPING = "ROUND_TRIPPING"
    VENDOR_MISMATCH = "VENDOR_MISMATCH"

class CurrencyCode(str, Enum):
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    RUB = "RUB"
    GBP = "GBP"
    CNY = "CNY"
    AED = "AED"

# ─── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class Money:
    """Immutable money value object with currency."""
    amount: Decimal
    currency: CurrencyCode

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))
        self.amount = self.amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract {self.currency} from {other.currency}")
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal) -> "Money":
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def convert_to(self, target_currency: CurrencyCode, exchange_rate: Decimal) -> "Money":
        return Money(self.amount * exchange_rate, target_currency)

    def to_dict(self) -> dict:
        return {"amount": str(self.amount), "currency": self.currency.value}


@dataclass
class JournalLine:
    """Single debit or credit line in a journal entry."""
    line_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    account_code: str = ""
    account_type: AccountType = AccountType.ASSET
    transaction_type: TransactionType = TransactionType.DEBIT
    amount: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.USD
    exchange_rate: Decimal = Decimal("1")
    amount_base: Decimal = Decimal("0")  # always in USD
    description: str = ""
    cost_center: Optional[str] = None
    project_id: Optional[str] = None
    tax_code: Optional[str] = None

    def __post_init__(self):
        if self.amount_base == Decimal("0") and self.amount != Decimal("0"):
            self.amount_base = (self.amount * self.exchange_rate).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )


@dataclass
class JournalEntry:
    """Double-entry accounting journal entry (aggregate root)."""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entry_number: str = ""
    entry_date: date = field(default_factory=date.today)
    posting_date: Optional[date] = None
    status: JournalEntryStatus = JournalEntryStatus.DRAFT
    lines: List[JournalLine] = field(default_factory=list)
    reference_document: Optional[str] = None
    description: str = ""
    created_by: Optional[str] = None
    tenant_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def validate_balance(self) -> bool:
        """Double-entry check: sum of debits must equal sum of credits (in base currency)."""
        total_debit = sum(
            l.amount_base for l in self.lines if l.transaction_type == TransactionType.DEBIT
        )
        total_credit = sum(
            l.amount_base for l in self.lines if l.transaction_type == TransactionType.CREDIT
        )
        epsilon = Decimal("0.01")  # tolerance for floating-point rounding
        return abs(total_debit - total_credit) <= epsilon

    def get_total_amount(self) -> Decimal:
        return sum(
            l.amount_base for l in self.lines if l.transaction_type == TransactionType.DEBIT
        )

    def post(self) -> None:
        if not self.validate_balance():
            raise ValueError(
                f"Journal entry {self.entry_id} is not balanced: "
                f"debits={sum(l.amount_base for l in self.lines if l.transaction_type == TransactionType.DEBIT)}, "
                f"credits={sum(l.amount_base for l in self.lines if l.transaction_type == TransactionType.CREDIT)}"
            )
        self.status = JournalEntryStatus.POSTED
        self.posting_date = date.today()
        self.updated_at = datetime.utcnow()


@dataclass
class AnomalyAlert:
    """Financial anomaly detected by ML pipeline."""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entry_id: str = ""
    anomaly_type: AnomalyType = AnomalyType.UNUSUAL_AMOUNT
    anomaly_score: float = 0.0  # -1 to 1, where negative = more anomalous
    description: str = ""
    amount: Optional[Decimal] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)
    reviewed: bool = False
    reviewer_id: Optional[str] = None
    resolution: Optional[str] = None

    def is_critical(self) -> bool:
        return self.anomaly_score < -0.7

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amount"] = str(self.amount) if self.amount else None
        d["detected_at"] = self.detected_at.isoformat()
        return d


# ─── Exchange Rate Service ─────────────────────────────────────────────────────

class ExchangeRateService:
    """
    Fetches and caches foreign exchange rates.
    Sources: ECB, NBK (National Bank of Kazakhstan), CBR (Central Bank of Russia).
    Falls back to last known rate if source unavailable.
    """

    SUPPORTED_CURRENCIES = [
        "EUR", "GBP", "KZT", "RUB", "CNY", "AED", "TRY", "JPY", "CHF",
        "CAD", "AUD", "SGD", "HKD", "KRW", "SEK", "NOK", "DKK", "PLN",
        "CZK", "HUF", "RON", "BGN", "HRK", "UAH", "BYN", "GEL", "AMD",
        "AZN", "UZS", "KGS", "TJS", "TMT", "MNT", "BDT", "PKR", "INR",
        "THB", "VND", "IDR", "MYR", "PHP", "SAR", "QAR", "KWD", "BHD"
    ]  # 45 currencies total

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.cache_ttl = 3600  # 1 hour

    def get_rate(self, from_currency: str, to_currency: str, as_of: Optional[date] = None) -> Decimal:
        if from_currency == to_currency:
            return Decimal("1")

        cache_key = f"fx:{from_currency}:{to_currency}:{(as_of or date.today()).isoformat()}"
        cached = self.redis.get(cache_key)
        if cached:
            return Decimal(cached.decode())

        rate = self._fetch_rate(from_currency, to_currency, as_of)
        self.redis.setex(cache_key, self.cache_ttl, str(rate))
        return rate

    def _fetch_rate(self, from_currency: str, to_currency: str, as_of: Optional[date] = None) -> Decimal:
        # In production: call ECB/NBK/CBR APIs
        # For now: mock rates based on approximate 2025 values
        mock_rates_to_usd = {
            "EUR": Decimal("1.08"),
            "GBP": Decimal("1.27"),
            "KZT": Decimal("0.00221"),
            "RUB": Decimal("0.0110"),
            "CNY": Decimal("0.138"),
            "AED": Decimal("0.272"),
            "JPY": Decimal("0.00668"),
            "CHF": Decimal("1.12"),
            "CAD": Decimal("0.74"),
        }
        rate_from = mock_rates_to_usd.get(from_currency, Decimal("1"))
        rate_to = mock_rates_to_usd.get(to_currency, Decimal("1"))
        return (rate_from / rate_to).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def get_historical_rates(
        self, currency: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """Returns DataFrame of daily exchange rates for forecasting."""
        dates = pd.date_range(start_date, end_date, freq='D')
        # Simulate slight daily variation around base rate
        base_rate = float(self.get_rate(currency, "USD"))
        rates = base_rate + np.random.normal(0, base_rate * 0.005, len(dates))
        return pd.DataFrame({"date": dates, "rate": rates})


# ─── Anomaly Detection (ML) ───────────────────────────────────────────────────

class FinancialAnomalyDetector:
    """
    Isolation Forest-based anomaly detection for journal entries.
    Features:
      - Transaction amount (log-scaled)
      - Hour of day (time-based anomalies)
      - Day of week
      - Account type pair (encoded)
      - Amount vs historical mean for that account (z-score)
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model = IsolationForest(
            n_estimators=200,
            contamination=0.01,  # expect ~1% anomalies
            random_state=42,
            n_jobs=-1
        )
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.account_stats: Dict[str, Dict] = {}  # mean/std per account
        self.model_path = model_path

        if model_path and os.path.exists(f"{model_path}/isolation_forest.pkl"):
            self._load_model()

    def _extract_features(self, entries: List[Dict]) -> np.ndarray:
        features = []
        for entry in entries:
            amount = float(entry.get("amount_base", 0))
            created_at = pd.Timestamp(entry.get("created_at", datetime.utcnow()))
            account_code = entry.get("account_code", "")

            # Get z-score relative to account history
            stats = self.account_stats.get(account_code, {"mean": amount, "std": 1.0})
            z_score = (amount - stats["mean"]) / max(stats["std"], 1.0)

            features.append([
                np.log1p(abs(amount)),      # log-scale amount
                created_at.hour,            # hour of day
                created_at.dayofweek,       # 0=Monday, 6=Sunday
                z_score,                    # deviation from account norm
                int(amount < 0),            # is negative amount
                amount % 1000 == 0,         # is round number (fraud indicator)
            ])
        return np.array(features, dtype=np.float64)

    def fit(self, historical_entries: List[Dict]) -> None:
        """Train on historical journal entries."""
        if len(historical_entries) < 100:
            logger.warning("Insufficient data for anomaly detection training",
                           count=len(historical_entries))
            return

        # Build per-account stats
        df = pd.DataFrame(historical_entries)
        if "account_code" in df.columns and "amount_base" in df.columns:
            stats = df.groupby("account_code")["amount_base"].agg(["mean", "std"]).to_dict("index")
            self.account_stats = {
                k: {"mean": float(v["mean"]), "std": float(v["std"]) or 1.0}
                for k, v in stats.items()
            }

        features = self._extract_features(historical_entries)
        scaled = self.scaler.fit_transform(features)
        self.model.fit(scaled)
        self.is_fitted = True
        logger.info("Anomaly detector trained", samples=len(historical_entries))

    def predict(self, entries: List[Dict]) -> List[Tuple[bool, float]]:
        """
        Returns list of (is_anomaly, score) tuples.
        Score: -1 = most anomalous, +1 = most normal (IsolationForest convention).
        """
        if not self.is_fitted:
            return [(False, 0.0)] * len(entries)

        features = self._extract_features(entries)
        scaled = self.scaler.transform(features)
        predictions = self.model.predict(scaled)   # 1 = normal, -1 = anomaly
        scores = self.model.score_samples(scaled)  # lower = more anomalous

        return [(pred == -1, float(score)) for pred, score in zip(predictions, scores)]

    def explain_anomaly(self, entry: Dict) -> str:
        """Generate human-readable explanation for why an entry is anomalous."""
        amount = float(entry.get("amount_base", 0))
        created_at = pd.Timestamp(entry.get("created_at", datetime.utcnow()))
        account_code = entry.get("account_code", "")

        reasons = []
        if created_at.hour < 6 or created_at.hour > 22:
            reasons.append(f"Posted at unusual hour: {created_at.hour}:00")

        stats = self.account_stats.get(account_code, {})
        if stats:
            z = (amount - stats["mean"]) / max(stats["std"], 1.0)
            if abs(z) > 3:
                reasons.append(f"Amount ${amount:,.2f} is {abs(z):.1f}σ from mean ${stats['mean']:,.2f}")

        if amount > 0 and amount % 1000 == 0 and amount > 10000:
            reasons.append(f"Suspiciously round amount: ${amount:,.0f}")

        return "; ".join(reasons) if reasons else "Statistical outlier (no specific pattern found)"

    def _load_model(self):
        import pickle
        with open(f"{self.model_path}/isolation_forest.pkl", "rb") as f:
            saved = pickle.load(f)
            self.model = saved["model"]
            self.scaler = saved["scaler"]
            self.account_stats = saved["account_stats"]
            self.is_fitted = True

    def save_model(self):
        import pickle
        os.makedirs(self.model_path, exist_ok=True)
        with open(f"{self.model_path}/isolation_forest.pkl", "wb") as f:
            pickle.dump({
                "model": self.model,
                "scaler": self.scaler,
                "account_stats": self.account_stats,
            }, f)
        logger.info("Anomaly model saved", path=self.model_path)


# ─── LSTM Cash Flow Forecaster ─────────────────────────────────────────────────

class LSTMCashFlowModel(nn.Module):
    """
    LSTM-based model for predicting 30-day cash flow.
    Input: 90-day window of daily account balances (multivariate)
    Output: 30-day forecast of net cash position
    """

    def __init__(self, input_size: int = 8, hidden_size: int = 128, num_layers: int = 2,
                 output_size: int = 30, dropout: float = 0.2):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0
        )
        self.attention = nn.MultiheadAttention(embed_dim=hidden_size, num_heads=4, batch_first=True)
        self.dropout = nn.Dropout(p=dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(64, output_size)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: (batch, seq_len=90, features=8)
        returns: (batch, 30) — 30-day cash forecast
        """
        lstm_out, (h_n, c_n) = self.lstm(x)
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        pooled = attn_out[:, -1, :]  # last timestep
        pooled = self.dropout(pooled)
        return self.fc(pooled)


class CashFlowForecaster:
    """Production wrapper for the LSTM cash flow model."""

    FEATURE_COLUMNS = [
        "operating_balance", "ar_balance", "ap_balance",
        "revenue_7d_ma", "expense_7d_ma", "payroll_scheduled",
        "tax_scheduled", "fx_exposure"
    ]
    SEQUENCE_LENGTH = 90
    FORECAST_HORIZON = 30

    def __init__(self, model_path: Optional[str] = None, device: str = "cpu"):
        self.device = torch.device(device)
        self.model = LSTMCashFlowModel(
            input_size=len(self.FEATURE_COLUMNS),
            hidden_size=128,
            num_layers=2,
            output_size=self.FORECAST_HORIZON
        ).to(self.device)
        self.scaler = StandardScaler()
        self.is_ready = False

        if model_path and os.path.exists(f"{model_path}/cashflow_lstm.pt"):
            self._load(model_path)

    def prepare_features(self, daily_balances: pd.DataFrame) -> torch.Tensor:
        """Prepare 90-day feature window from historical balance data."""
        if len(daily_balances) < self.SEQUENCE_LENGTH:
            pad_rows = self.SEQUENCE_LENGTH - len(daily_balances)
            padding = pd.DataFrame(
                np.zeros((pad_rows, len(self.FEATURE_COLUMNS))),
                columns=self.FEATURE_COLUMNS
            )
            daily_balances = pd.concat([padding, daily_balances], ignore_index=True)

        features = daily_balances[self.FEATURE_COLUMNS].values[-self.SEQUENCE_LENGTH:]
        scaled = self.scaler.transform(features) if self.is_ready else features
        return torch.tensor(scaled, dtype=torch.float32).unsqueeze(0).to(self.device)

    def forecast(self, daily_balances: pd.DataFrame) -> Dict[str, Any]:
        """
        Returns 30-day cash flow forecast with confidence intervals.
        Uses Monte Carlo dropout for uncertainty estimation.
        """
        if not self.is_ready:
            return self._fallback_forecast(daily_balances)

        self.model.eval()
        x = self.prepare_features(daily_balances)

        # Monte Carlo dropout — 50 forward passes for uncertainty
        self.model.train()  # enable dropout
        predictions = []
        with torch.no_grad():
            for _ in range(50):
                pred = self.model(x).cpu().numpy().flatten()
                predictions.append(pred)
        self.model.eval()

        preds = np.array(predictions)  # shape (50, 30)
        mean = preds.mean(axis=0)
        std = preds.std(axis=0)

        forecast_dates = [
            (date.today() + timedelta(days=i+1)).isoformat()
            for i in range(self.FORECAST_HORIZON)
        ]

        return {
            "forecast_horizon_days": self.FORECAST_HORIZON,
            "generated_at": datetime.utcnow().isoformat(),
            "daily_forecast": [
                {
                    "date": d,
                    "net_cash_usd": round(float(mean[i]), 2),
                    "lower_bound_95": round(float(mean[i] - 1.96 * std[i]), 2),
                    "upper_bound_95": round(float(mean[i] + 1.96 * std[i]), 2),
                    "uncertainty": round(float(std[i]), 2)
                }
                for i, d in enumerate(forecast_dates)
            ],
            "summary": {
                "total_30d_net": round(float(mean.sum()), 2),
                "min_daily_balance": round(float(mean.min()), 2),
                "max_daily_balance": round(float(mean.max()), 2),
                "cash_shortfall_risk": float((mean < 0).mean()),  # % of days in deficit
            }
        }

    def _fallback_forecast(self, daily_balances: pd.DataFrame) -> Dict[str, Any]:
        """Simple linear trend fallback when model is not ready."""
        if "operating_balance" in daily_balances.columns and len(daily_balances) >= 7:
            recent = daily_balances["operating_balance"].values[-7:]
            trend = np.polyfit(range(len(recent)), recent, 1)[0]
            last_val = float(recent[-1])
        else:
            trend, last_val = 0.0, 0.0

        forecast_dates = [
            (date.today() + timedelta(days=i+1)).isoformat()
            for i in range(self.FORECAST_HORIZON)
        ]

        return {
            "forecast_horizon_days": self.FORECAST_HORIZON,
            "generated_at": datetime.utcnow().isoformat(),
            "method": "linear_fallback",
            "daily_forecast": [
                {"date": d, "net_cash_usd": round(last_val + trend * (i+1), 2)}
                for i, d in enumerate(forecast_dates)
            ]
        }

    def _load(self, model_path: str):
        import pickle
        self.model.load_state_dict(torch.load(f"{model_path}/cashflow_lstm.pt", map_location=self.device))
        with open(f"{model_path}/cashflow_scaler.pkl", "rb") as f:
            self.scaler = pickle.load(f)
        self.is_ready = True
        logger.info("Cash flow forecaster loaded", path=model_path)


# ─── Kafka Event Publisher ─────────────────────────────────────────────────────

class FinanceEventPublisher:
    """Publishes financial domain events to Kafka topics."""

    TOPIC_JOURNAL_ENTRY = "finance.journal-entry.posted.v1"
    TOPIC_ANOMALY_DETECTED = "finance.anomaly.detected.v1"
    TOPIC_RECONCILIATION = "finance.reconciliation.completed.v1"
    TOPIC_FORECAST = "finance.cashflow.forecasted.v1"

    def __init__(self, bootstrap_servers: str, tenant_id: str):
        self.producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "acks": "all",
            "retries": 5,
            "enable.idempotence": True,
            "compression.type": "snappy",
        })
        self.tenant_id = tenant_id

    def publish_journal_entry_posted(self, entry: JournalEntry) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "JournalEntryPosted",
            "occurred_at": datetime.utcnow().isoformat(),
            "tenant_id": self.tenant_id,
            "aggregate_id": entry.entry_id,
            "payload": {
                "entry_number": entry.entry_number,
                "entry_date": entry.entry_date.isoformat(),
                "total_amount_usd": str(entry.get_total_amount()),
                "lines_count": len(entry.lines),
                "reference_document": entry.reference_document,
            },
            "metadata": {"service": SERVICE_NAME, "version": SERVICE_VERSION}
        }
        self._publish(self.TOPIC_JOURNAL_ENTRY, entry.entry_id, event)
        logger.info("Published JournalEntryPosted", entry_id=entry.entry_id)

    def publish_anomaly_detected(self, alert: AnomalyAlert) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "FinancialAnomalyDetected",
            "occurred_at": datetime.utcnow().isoformat(),
            "tenant_id": self.tenant_id,
            "aggregate_id": alert.alert_id,
            "payload": alert.to_dict(),
            "metadata": {"service": SERVICE_NAME, "version": SERVICE_VERSION}
        }
        self._publish(self.TOPIC_ANOMALY_DETECTED, alert.alert_id, event)
        if alert.is_critical():
            logger.warning("Critical anomaly detected", alert_id=alert.alert_id,
                           score=alert.anomaly_score, type=alert.anomaly_type)

    def _publish(self, topic: str, key: str, payload: dict) -> None:
        try:
            self.producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=json.dumps(payload).encode("utf-8"),
                on_delivery=self._delivery_report
            )
            self.producer.poll(0)
        except KafkaException as e:
            logger.error("Failed to publish event", topic=topic, error=str(e))
            raise

    @staticmethod
    def _delivery_report(err, msg):
        if err:
            logger.error("Kafka delivery failed", error=str(err))
        else:
            logger.debug("Kafka delivery confirmed", topic=msg.topic(), partition=msg.partition())

    def flush(self, timeout: float = 10.0) -> None:
        self.producer.flush(timeout=timeout)


# ─── Reconciliation Engine ─────────────────────────────────────────────────────

class BankReconciliationEngine:
    """
    Automatic bank statement reconciliation.
    Matches bank transactions against journal entries using fuzzy matching.
    Handles: exact match, date tolerance ±3 days, amount tolerance ±$0.01 (rounding).
    """

    DATE_TOLERANCE = timedelta(days=3)
    AMOUNT_TOLERANCE = Decimal("0.01")

    @dataclass
    class BankTransaction:
        txn_id: str
        bank_ref: str
        txn_date: date
        amount: Decimal
        description: str
        is_matched: bool = False

    @dataclass
    class ReconciliationResult:
        matched_count: int
        unmatched_bank_count: int
        unmatched_erp_count: int
        matched_amount: Decimal
        discrepancies: List[Dict]
        reconciliation_date: date
        confidence_score: float  # 0-1, how confident the matching is

    def reconcile(
        self,
        bank_transactions: List[BankTransaction],
        journal_entries: List[JournalEntry],
        account_code: str
    ) -> ReconciliationResult:
        """
        Main reconciliation algorithm.
        1. Exact match by amount + date
        2. Fuzzy match: amount within tolerance + date within ±3 days
        3. Aggregate match: split payments, combined receipts
        """
        matched = []
        discrepancies = []
        matched_amount = Decimal("0")

        # Build lookup index for ERP entries
        erp_index: Dict[Decimal, List[JournalEntry]] = {}
        for entry in journal_entries:
            amount = entry.get_total_amount()
            erp_index.setdefault(amount, []).append(entry)

        unmatched_bank = []
        for bank_txn in bank_transactions:
            match_found = self._find_match(bank_txn, erp_index)
            if match_found:
                matched.append((bank_txn, match_found))
                matched_amount += bank_txn.amount
            else:
                unmatched_bank.append(bank_txn)
                discrepancies.append({
                    "type": "unmatched_bank",
                    "bank_ref": bank_txn.bank_ref,
                    "amount": str(bank_txn.amount),
                    "date": bank_txn.txn_date.isoformat(),
                    "description": bank_txn.description
                })

        matched_erp_ids = {m[1].entry_id for m in matched}
        unmatched_erp = [e for e in journal_entries if e.entry_id not in matched_erp_ids]

        confidence = len(matched) / max(len(bank_transactions), 1)

        return self.ReconciliationResult(
            matched_count=len(matched),
            unmatched_bank_count=len(unmatched_bank),
            unmatched_erp_count=len(unmatched_erp),
            matched_amount=matched_amount,
            discrepancies=discrepancies,
            reconciliation_date=date.today(),
            confidence_score=confidence
        )

    def _find_match(self, bank_txn: BankTransaction, erp_index: Dict) -> Optional[JournalEntry]:
        # Exact amount match
        candidates = erp_index.get(bank_txn.amount, [])
        for entry in candidates:
            if abs((entry.entry_date - bank_txn.txn_date).days) <= self.DATE_TOLERANCE.days:
                return entry

        # Tolerance match (±$0.01 rounding)
        for amount, entries in erp_index.items():
            if abs(amount - bank_txn.amount) <= self.AMOUNT_TOLERANCE:
                for entry in entries:
                    if abs((entry.entry_date - bank_txn.txn_date).days) <= self.DATE_TOLERANCE.days:
                        return entry
        return None


# ─── Main Service Orchestrator ─────────────────────────────────────────────────

class FinanceCoreMLService:
    """
    Main orchestrator for finance-core ML service.
    Runs as a background worker alongside the Go finance-core service.
    Responsibilities:
      - Real-time anomaly detection on incoming journal entries
      - Daily cash flow forecast generation
      - Batch bank reconciliation (scheduled, nightly)
    """

    def __init__(self):
        self.db_engine = create_engine(DB_URL, pool_size=10, max_overflow=5)
        self.redis_client = redis.from_url(REDIS_URL, decode_responses=False)
        self.anomaly_detector = FinancialAnomalyDetector(ML_MODEL_PATH)
        self.cash_forecaster = CashFlowForecaster(ML_MODEL_PATH)
        self.fx_service = ExchangeRateService(self.redis_client)
        self.reconciliation_engine = BankReconciliationEngine()
        self.executor = ThreadPoolExecutor(max_workers=4)

        logger.info("FinanceCoreMLService initialized",
                    environment=ENVIRONMENT, version=SERVICE_VERSION)

    def process_journal_entry_event(self, entry_dict: dict) -> Optional[AnomalyAlert]:
        """Called when a new JournalEntryPosted event arrives from Kafka."""
        try:
            # Run anomaly detection
            results = self.anomaly_detector.predict([entry_dict])
            if results and results[0][0]:  # is_anomaly = True
                is_anomaly, score = results[0]
                explanation = self.anomaly_detector.explain_anomaly(entry_dict)
                alert = AnomalyAlert(
                    entry_id=entry_dict.get("entry_id", ""),
                    anomaly_type=AnomalyType.UNUSUAL_AMOUNT,
                    anomaly_score=score,
                    description=explanation,
                    amount=Decimal(str(entry_dict.get("amount_base", 0)))
                )
                logger.warning("Anomaly detected in journal entry",
                               entry_id=alert.entry_id, score=score,
                               description=explanation)
                return alert
        except Exception as e:
            logger.error("Error in anomaly detection", error=str(e), entry=entry_dict.get("entry_id"))
        return None

    def run_daily_forecast(self, tenant_id: str) -> Dict[str, Any]:
        """Generate 30-day cash flow forecast for a tenant."""
        with Session(self.db_engine) as session:
            rows = session.execute(text("""
                SELECT
                    date_trunc('day', posting_date)::date AS day,
                    SUM(CASE WHEN transaction_type = 'DEBIT' THEN amount_base ELSE 0 END) AS debit_total,
                    SUM(CASE WHEN transaction_type = 'CREDIT' THEN amount_base ELSE 0 END) AS credit_total
                FROM journal_lines jl
                JOIN journal_entries je ON je.entry_id = jl.entry_id
                WHERE je.tenant_id = :tenant_id
                  AND je.status = 'POSTED'
                  AND posting_date >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY 1
                ORDER BY 1
            """), {"tenant_id": tenant_id}).fetchall()

        if not rows:
            return {"error": "No historical data available", "tenant_id": tenant_id}

        df = pd.DataFrame(rows, columns=["date", "debit_total", "credit_total"])
        df["operating_balance"] = df["credit_total"] - df["debit_total"]
        df["revenue_7d_ma"] = df["credit_total"].rolling(7, min_periods=1).mean()
        df["expense_7d_ma"] = df["debit_total"].rolling(7, min_periods=1).mean()
        df["ar_balance"] = 0.0
        df["ap_balance"] = 0.0
        df["payroll_scheduled"] = 0.0
        df["tax_scheduled"] = 0.0
        df["fx_exposure"] = 0.0

        return self.cash_forecaster.forecast(df)

    def health_check(self) -> Dict[str, Any]:
        health = {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {}
        }

        # DB check
        try:
            with Session(self.db_engine) as s:
                s.execute(text("SELECT 1"))
            health["checks"]["database"] = "ok"
        except Exception as e:
            health["checks"]["database"] = f"error: {str(e)}"

        # Redis check
        try:
            self.redis_client.ping()
            health["checks"]["redis"] = "ok"
        except Exception as e:
            health["checks"]["redis"] = f"error: {str(e)}"

        health["checks"]["ml_model"] = "ready" if self.anomaly_detector.is_fitted else "not_trained"
        health["checks"]["forecaster"] = "ready" if self.cash_forecaster.is_ready else "not_trained"

        health["status"] = "healthy" if all(
            v in ("ok", "ready") for v in health["checks"].values()
        ) else "degraded"

        return health


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    service = FinanceCoreMLService()
    logger.info("Finance Core ML service starting",
                environment=ENVIRONMENT, version=SERVICE_VERSION,
                db=DB_URL.split("@")[-1])  # log host only, not credentials
    health = service.health_check()
    logger.info("Health check", **health)
