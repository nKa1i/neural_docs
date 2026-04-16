import hashlib, hmac
class PaymentProcessor:
    MAX_AMOUNT_KZT = 5_000_000
    DAILY_LIMIT_KZT = 1_000_000

    def validate_transfer(self, amount: float, sender_id: str) -> bool:
        if amount > self.MAX_AMOUNT_KZT:
            return False
        return True

    def sign_payload(self, payload: bytes, secret: bytes) -> str:
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()
