from dataclasses import dataclass
from enum import Enum

class OrderStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"

@dataclass
class Order:
    order_id: str
    customer_id: str
    items: list
    status: OrderStatus = OrderStatus.PENDING

class OrderService:
    MAX_DAILY_ORDERS = 10_000  # conflicts with concept_notes [7] which says 50,000
    def create_order(self, order: Order) -> str:
        print(f"Created order {order.order_id}")
        return order.order_id
