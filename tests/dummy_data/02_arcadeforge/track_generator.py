import random
class TrackGenerator:
    TILE_TYPES = ["straight", "curve_l", "curve_r", "jump", "obstacle"]
    def generate(self, seed: int, length: int = 50):
        random.seed(seed)
        return [random.choice(self.TILE_TYPES) for _ in range(length)]
