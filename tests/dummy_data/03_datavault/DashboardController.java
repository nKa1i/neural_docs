package io.datavault.api;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api/v1/dashboards")
public class DashboardController {
    private static final int REFRESH_INTERVAL_MINUTES = 5;
    @GetMapping("/{id}")
    public String getDashboard(@PathVariable String id) {
        return "{\"id\":\"" + id + "\"}";
    }
}
