package kz.ecotrack.gateway;
public class SensorGateway {
    private static final String PROTOCOL = "MQTT"; // code uses MQTT, config says CoAP
    private static final int HEARTBEAT_INTERVAL_SEC = 60;
    public void registerSensor(String sensorId, double lat, double lon) {
        System.out.println("Registered: " + sensorId + " at " + lat + "," + lon);
    }
}
