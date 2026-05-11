package io.codereviewpro.webhook;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/webhook")
public class WebhookHandler {
    private static final String SUPPORTED_EVENTS = "pull_request,push";
    @PostMapping("/github")
    public String handleGithub(@RequestBody String payload,
                                @RequestHeader("X-GitHub-Event") String event) {
        System.out.println("Event: " + event);
        return "{\"status\":\"queued\"}";
    }
}
