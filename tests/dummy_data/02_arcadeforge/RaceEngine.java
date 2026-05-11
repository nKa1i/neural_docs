package com.arcadeforge.engine;
public class RaceEngine {
    public static final int MAX_PLAYERS = 4;
    public static final int TRACK_SEED_RANGE = 999999;
    public void generateTrack(int seed) {
        System.out.println("Generating track with seed: " + seed);
    }
    public boolean validateTrack(int[][] grid) {
        // TODO: pathfinding validation — risk of unpassable tracks
        return true;
    }
}
