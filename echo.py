"""Echo: cooperate with your past selves.
Play:       python echo.py [--seed N]
Self-check: python echo.py --test
"""
import random
import sys

DIRS = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0), ".": (0, 0)}
FLIP_H, FLIP_V = str.maketrans("LR", "RL"), str.maketrans("UD", "DU")

# Room legend: # wall, @ start, > exit, a/b pressure plate, A/B door (open while
# anything stands on the matching plate). Each module ships with a hand-made
# solution: one move string per pass; the last pass must reach the exit.
MODULES = [
    (["########",
      "#@a.A.>#",
      "########"], ["R", "RRRRR"]),
    (["############",
      "#@a.A.b.B.>#",
      "############"], ["R", "RRRRR", "R" * 9]),
    (["########",
      "#@..#.>#",
      "#.a.A..#",
      "#...#..#",
      "########"], ["DR", "DRRRRRU"]),
]


class Room:
    def __init__(self, rows):
        self.rows, self.h, self.w = rows, len(rows), len(rows[0])
        for y, row in enumerate(rows):
            for x, c in enumerate(row):
                if c == "@":
                    self.start = (x, y)

    def cell(self, p):
        return self.rows[p[1]][p[0]]

    def open_doors(self, occupied):
        return {self.cell(p) for p in occupied if self.cell(p).islower()}

    def step(self, pos, mv, occupied):
        dx, dy = DIRS[mv]
        n = (pos[0] + dx, pos[1] + dy)
        c = self.cell(n)
        if c == "#" or (c.isupper() and c.lower() not in self.open_doors(occupied)):
            return pos
        return n


def ghost_cells(ghosts, t):
    return [g[min(t, len(g) - 1)] for g in ghosts]


def play(room, ghosts, moves):
    """Run one pass against recorded ghost paths. Returns (path, reached_exit)."""
    pos, path = room.start, [room.start]
    for t, mv in enumerate(moves):
        pos = room.step(pos, mv, ghost_cells(ghosts, t) + [pos])
        path.append(pos)
        if room.cell(pos) == ">":
            return path, True
    return path, False


def solvable(room, solution):
    ghosts = []
    for moves in solution[:-1]:
        ghosts.append(play(room, ghosts, moves)[0])
    return play(room, ghosts, solution[-1])[1]


def variant(rows, solution, flip_h, flip_v):
    if flip_h:
        rows, solution = [r[::-1] for r in rows], [s.translate(FLIP_H) for s in solution]
    if flip_v:
        rows, solution = rows[::-1], [s.translate(FLIP_V) for s in solution]
    return rows, solution


def make_level(seed, rooms=4):
    """A seeded chain of flipped modules. A room is kept only if its stored
    solution replays successfully, so every level can be finished."""
    rng = random.Random(seed)
    picks = [variant(*rng.choice(MODULES), rng.random() < .5, rng.random() < .5)
             for _ in range(rooms)]
    good = [p for p in picks if solvable(Room(p[0]), p[1])]
    return [rows for rows, _ in sorted(good, key=lambda p: len(p[1]))]


def self_test():
    n = 0
    for rows, sol in MODULES:
        for h in (0, 1):
            for v in (0, 1):
                r, s = variant(rows, sol, h, v)
                assert solvable(Room(r), s), (rows, h, v)
                n += 1
    assert all(len(make_level(seed)) == 4 for seed in range(500))
    print(f"ok: {n} module variants solvable, 500 seeds generate full levels")


class Game:
    def __init__(self, seed):
        self.seed, self.i = seed, 0
        self.rooms = [Room(r) for r in make_level(seed)]
        self.restart()

    def restart(self):
        self.ghosts = []
        self.new_pass()

    def new_pass(self):
        self.room = self.rooms[self.i] if self.i < len(self.rooms) else None
        if self.room:
            self.pos, self.path, self.t = self.room.start, [self.room.start], 0

    def commit(self):
        if self.room:
            self.ghosts.append(self.path)
            self.new_pass()

    def beat(self, mv):
        if not self.room:
            return
        self.pos = self.room.step(self.pos, mv, ghost_cells(self.ghosts, self.t) + [self.pos])
        self.path.append(self.pos)
        self.t += 1
        if self.room.cell(self.pos) == ">":
            self.i += 1
            self.restart()


def main(seed):
    import pygame
    pygame.init()
    W, H, T, BEAT = 760, 520, 56, 14
    screen = pygame.display.set_mode((W, H))
    clock, font = pygame.time.Clock(), pygame.font.SysFont("arial", 20)
    BG, INK, VIOLET, LIME = (14, 11, 30), (235, 232, 247), (140, 110, 255), (182, 255, 61)
    COLS = {"a": (255, 196, 64), "b": (255, 90, 160)}
    keymap = [(pygame.K_UP, "U"), (pygame.K_w, "U"), (pygame.K_DOWN, "D"), (pygame.K_s, "D"),
              (pygame.K_LEFT, "L"), (pygame.K_a, "L"), (pygame.K_RIGHT, "R"), (pygame.K_d, "R")]

    def start(s):
        pygame.display.set_caption(f"Echo - seed {s}")
        return Game(s)

    def text(msg, pos, color=INK):
        screen.blit(font.render(msg, True, color), pos)

    def draw(g):
        screen.fill(BG)
        if not g.room:
            text("All rooms cleared. Press N for a new seed.", (W // 2 - 190, H // 2))
            return
        r = g.room
        ox, oy = (W - r.w * T) // 2, (H - r.h * T) // 2
        opened = r.open_doors(ghost_cells(g.ghosts, g.t) + [g.pos])
        cell = lambda p, m=0: pygame.Rect(ox + p[0] * T + m, oy + p[1] * T + m, T - 2 * m, T - 2 * m)
        for y, row in enumerate(r.rows):
            for x, c in enumerate(row):
                if c == "#":
                    pygame.draw.rect(screen, (60, 52, 110), cell((x, y)), 2)
                elif c.islower():
                    pygame.draw.circle(screen, COLS[c], cell((x, y)).center, T // 3, 3)
                elif c.isupper():
                    pygame.draw.rect(screen, COLS[c.lower()], cell((x, y), 6), 2 if c.lower() in opened else 0)
                elif c == ">":
                    pygame.draw.rect(screen, LIME, cell((x, y), 10))
        for p in ghost_cells(g.ghosts, g.t):
            pygame.draw.rect(screen, VIOLET, cell(p, 12), 3, border_radius=4)
        pygame.draw.rect(screen, INK, cell(g.pos, 12), border_radius=4)
        text(f"Room {g.i + 1}/{len(g.rooms)}   Pass {len(g.ghosts) + 1}   Seed {g.seed}", (16, 12))
        text("Space: save run as ghost    R: restart room    N: new seed", (16, H - 34), (150, 144, 190))

    game, frame = start(seed), 0
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE:
                    game.commit()
                elif e.key == pygame.K_r:
                    game.restart()
                elif e.key == pygame.K_n:
                    seed = random.randrange(10 ** 6)
                    game = start(seed)
        frame += 1
        if frame % BEAT == 0:
            keys = pygame.key.get_pressed()
            game.beat(next((m for k, m in keymap if keys[k]), "."))
        draw(game)
        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        main(int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else random.randrange(10 ** 6))
