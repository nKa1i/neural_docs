package io.neonphantom.engine;
public class EntitySystem {
    private static final int MAX_ENTITIES = 512;
    private static final float ENEMY_BASE_DAMAGE = 45.0f; // hardcoded high damage
    public void spawnEnemy(String type, float x, float y) {
        System.out.println("Spawning " + type + " at (" + x + "," + y + ")");
    }
}
