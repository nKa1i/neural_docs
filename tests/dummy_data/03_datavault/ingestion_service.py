from kafka import KafkaConsumer
import clickhouse_driver

class IngestionService:
    BATCH_SIZE = 1000
    FLUSH_INTERVAL_SEC = 5

    def __init__(self, kafka_topic: str, ch_table: str):
        self.topic = kafka_topic
        self.table = ch_table

    def run(self):
        consumer = KafkaConsumer(self.topic)
        batch = []
        for msg in consumer:
            batch.append(msg.value)
            if len(batch) >= self.BATCH_SIZE:
                self._flush(batch)
                batch = []

    def _flush(self, batch):
        # write to ClickHouse
        pass
