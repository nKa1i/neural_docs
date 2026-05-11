import paho.mqtt.client as mqtt
class SensorCollector:
    TOPIC_PREFIX = "ecotrack/sensors/"
    QOS = 1
    def __init__(self, broker_host: str, port: int = 1883):
        self.client = mqtt.Client()
        self.broker = broker_host
        self.port = port
    def on_message(self, client, userdata, msg):
        print(f"Data from {msg.topic}: {msg.payload.decode()}")
    def start(self):
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port)
        self.client.subscribe(f"{self.TOPIC_PREFIX}#", self.QOS)
        self.client.loop_forever()
