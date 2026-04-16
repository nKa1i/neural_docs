# NeonPhantom — core loop (prototype)
class GameManager:
    VERSION = "0.3-alpha"
    MAX_POSSESSIONS = 3

    def start_level(self, level_id: int):
        print(f"Loading level {level_id}")

    def possess_enemy(self, enemy_id: int, possession_count: int) -> bool:
        if possession_count >= self.MAX_POSSESSIONS:
            return False
        return True
