package io.logiflow.api;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api/v1/shipments")
public class ShipmentController {
    private static final int MAX_WEIGHT_KG = 1000;
    @PostMapping
    public String createShipment(@RequestBody String body) {
        return "{\"status\":\"created\"}";
    }
}
