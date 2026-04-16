package ai.mindmap.render;
import java.util.List;
import java.util.Map;
public class NodeRenderer {
    public static final int MAX_DEPTH = 5;
    public String renderToMarkdown(Map<String, Object> node, int depth) {
        String indent = "  ".repeat(depth);
        return indent + "- " + node.get("label");
    }
}
