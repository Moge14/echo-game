"""Echo: cooperate with your past selves.

Every run you save becomes a ghost that replays your exact movements. Ghosts
hold pressure plates down, and you can stand on their heads to reach ledges
that are too high to jump to alone.

Play:       python echo.py                  the 20-room campaign
            python echo.py --seed N         a random run of 6 rooms (same seed, same run)
            python echo.py --room N         start the campaign at room N
Self-check: python echo.py --test

Controls:   Left/Right or A/D  run          Up or W   jump (hold = higher)
            Space              save this run as a ghost
            Z                  retry this run (keeps your ghosts)
            R                  restart the room (clears your ghosts)
            N                  new random run           C   back to the campaign
            Esc                quit

Tip: Space works in mid-air too. A ghost frozen over a pit is a stepping stone.
"""
import math
import random
import sys

# ---------------------------------------------------------------------------
# Physics. Everything runs on a fixed 60 Hz step, so a run always replays the
# same way, which is what makes ghosts (and the self-check) trustworthy.
# ---------------------------------------------------------------------------
T = 32                       # tile size in pixels
PW, PH = 22, 28              # body size
GRAV, MAXFALL = 0.55, 12.0
JUMP_V, MAXV = 10.0, 3.3
COYOTE, BUFFER = 6, 6        # forgiving jump timing, in frames
RELEASE_GRAV = 2.5           # let go of jump early = shorter hop
FLIP_H = str.maketrans("LR", "RL")

# ---------------------------------------------------------------------------
# Room legend:  # wall   @ start   > exit   a/b/c pressure plate
#               A/B/C door (open while anything stands on the matching plate)
#               . air (a gap in the bottom row is a pit)
# Each module is (name, room, solution). The solution is one input script per
# pass; the last pass must reach the exit, and --test replays all of them. Script tokens are KEYS+FRAMES, for example
# "R40 RJ12 .20" = run right 40 frames, jump right 12, wait 20.
# ---------------------------------------------------------------------------
MODULES = [
    # 1. Hold the door: A plate and a door: leave a ghost on the plate.
    ("Hold the door",
     [
      "################",
      "#.....A........#",
      "#.....A........#",
      "#.....A........#",
      "#.....A........#",
      "#@..a.A......>.#",
      "################"],
     ["R35 .10", "R130"]),

    # 2. Stairway: Climb the stairs to a plate on a floating ledge.
    ("Stairway",
     [
      "##################",
      "#............A...#",
      "#............A...#",
      "#............A...#",
      "#........a...A...#",
      "#......####..A...#",
      "#............A...#",
      "#....#.......A...#",
      "#@.#.#.......A..>#",
      "##################"],
     ["R10 RJ25 R14 RJ25 R12 .10", "R10 RJ25 R200"]),

    # 3. Boost: The exit is on a high block: step on your own ghost to reach it.
    ("Boost",
     [
      "################",
      "#..............#",
      "#..............#",
      "#..............#",
      "#............>.#",
      "#........#######",
      "#........#######",
      "#@.......#######",
      "################"],
     ["R200", "R30 RJ36 R4 RJ30 R70"]),

    # 4. Mind the gap: Jump the pit, press the plate, jump the pit again.
    ("Mind the gap",
     [
      "####################",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#.@.........a..A..>#",
      "#######...##########"],
     ["R44 RJ36 R14 .12", "R44 RJ36 R120"]),

    # 5. In series: Two plates, two doors, and a crate to hop over.
    ("In series",
     [
      "########################",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#@..a...A..#..b...B..>.#",
      "########################"],
     ["R35 .10", "R90 RJ36 R3 .10", "R90 RJ36 R103"]),

    # 6. Tower: A taller block needs two ghosts stacked up.
    ("Tower",
     [
      "##################",
      "#................#",
      "#................#",
      "#................#",
      "#.............>..#",
      "#..........#######",
      "#..........#######",
      "#..........#######",
      "#@.........#######",
      "##################"],
     ["R250", "R60 RJ36 R10", ".30 R60 RJ36 R4 RJ30 R70"]),

    # 7. Wait for it: A ghost only holds the door while it stands on the plate, so race it.
    ("Wait for it",
     [
      "######################",
      "#.........A..........#",
      "#.........A..........#",
      "#.........A..........#",
      "#.........A..........#",
      "#.........A..........#",
      "#.........A..........#",
      "#@..a..#..A........>.#",
      "######################"],
     ["R30", "R48 RJ3 .3 R21 .3 R93"]),

    # 8. Over the top: Use a ghost as a step, put another on the plate, then climb over the wall.
    ("Over the top",
     [
      "####################",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#.........a....A...#",
      "#.......####...A...#",
      "#.......####...A...#",
      "#@......####...A..>#",
      "####################"],
     ["R63", "RJ3 R3 .3 L3 .3 R3 .6 R3 L3 .3 R6 .3 RJ9 R24 .9", "RJ3 .3 R12 .3 R3 .6 R3 L3 .9 RJ9 R51 .3 R48 .3"]),

    # 9. Island hop: Two pits and a plate on the island between them.
    ("Island hop",
     [
      "######################",
      "#................A...#",
      "#................A...#",
      "#................A...#",
      "#................A...#",
      "#................A...#",
      "#................A...#",
      "#@.......a.......A..>#",
      "#####...###...########"],
     ["R42 RJ3 R3 .3 RJ9 R12", "R42 RJ3 .3 R3 .3 RJ9 R39 RJ3 R6 .3 R3 .3 R60 .2"]),

    # 10. Crate yard: Hop the crates; each plate opens the next door.
    ("Crate yard",
     [
      "########################",
      "#......A.........B.....#",
      "#......A.........B.....#",
      "#......A.........B.....#",
      "#......A.........B.....#",
      "#......A.##......B.....#",
      "#@.a.#.A.##.b.#..B...>.#",
      "########################"],
     ["R18 L3", "RJ12 .3 R6 .6 LJ3 R6 RJ6 R6 RJ3 R3 RJ6 R3 RJ6 .3 L3 RJ9 .3 R30 .3 R3 L6 .3", "RJ12 R6 .6 LJ3 R6 RJ6 R6 RJ6 R3 RJ18 .6 R9 L6 .3 R21 RJ3 R3 .3 RJ3 .3 R69"]),

    # 11. Ledge key: Plate b sits on a block you have to climb.
    ("Ledge key",
     [
      "######################",
      "#......A........B....#",
      "#......A........B....#",
      "#......A........B....#",
      "#......A........B....#",
      "#......A...b....B....#",
      "#......A..###...B....#",
      "#@.a...A..###...B..>.#",
      "######################"],
     ["R18 L3", "RJ12 R6 .6 LJ3 R3 RJ9 R15 RJ27 R15", "RJ12 .3 R6 .6 R3 RJ9 R15 RJ27 R39 .6 R3 .3 R42"]),

    # 12. Mid-air: The pit is too wide. Press Space while you are mid-jump to freeze a ghost in the air, then use it as a stepping stone.
    ("Mid-air",
     [
      "########################",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#@...................>.#",
      "########.....###########"],
     ["RJ3 R3 RJ18 .3 RJ6 R3 RJ6 .3 R3 RJ3 R3 RJ3 R3 .3 LJ3 .3 R3 LJ6 RJ15 .3 R3 RJ3 .3", "RJ30 R6 L3 .3 R6 .3 R9 L9 R3 L3 R9 RJ21 R96"]),

    # 13. Tower climb: Climb the ledges, then boost yourself up the last wall.
    ("Tower climb",
     [
      "################",
      "#..............#",
      "#..............#",
      "#............>.#",
      "#..........#####",
      "#..........#####",
      "#..........#####",
      "#.......###....#",
      "#..............#",
      "#..###.........#",
      "#@.............#",
      "################"],
     ["RJ9 .3 R18 .6 RJ3 R12 L3 LJ3 RJ9 R33", "RJ9 .3 R18 .6 RJ9 R12 RJ3 R9 L3 RJ3 R12 RJ9 R26"]),

    # 14. Sprint: The first door only stays open while its ghost is on the plate. Be quick.
    ("Sprint",
     [
      "########################",
      "#.....A............B...#",
      "#.....A............B...#",
      "#.....A............B...#",
      "#.....A............B...#",
      "#.....A............B...#",
      "#.....A............B...#",
      "#@.a..A..#......b..B..>#",
      "###########...##########"],
     ["R18", "R66 RJ3 .3 R3 .3 R12 .3 L3 R6 RJ3 R3 RJ6 R27 .9", "R66 RJ3 .3 R3 .3 R12 .3 L3 R6 .3 RJ3 R3 .3 R3 RJ6 R80"]),

    # 15. Skyscraper: Three ghosts stacked make a staircase.
    ("Skyscraper",
     [
      "##############",
      "#............#",
      "#............#",
      "#............#",
      "#............#",
      "#.........>..#",
      "#......#######",
      "#......#######",
      "#......#######",
      "#......#######",
      "#@.....#######",
      "##############"],
     ["R51", "RJ3 R18", "RJ6 .3 RJ3 L3 R6 .6", "RJ15 R9 RJ12 R33 .2"]),

    # 16. Obstacle course: Pits, an island and a crate between you and the exit.
    ("Obstacle course",
     [
      "########################",
      "#....A...............B.#",
      "#....A...............B.#",
      "#....A...............B.#",
      "#....A...............B.#",
      "#....A...............B.#",
      "#....A...............B.#",
      "#....A.............#.B.#",
      "#@.a.A.....b.......#.B>#",
      "#######...###...########"],
     ["R18", "R60 .3 RJ3 R9 RJ6 R12", "R60 .3 RJ3 R9 RJ6 R36 .3 RJ3 R45 RJ12 R18 .3 R9 .1"]),

    # 17. Long span: Two mid-air ghosts bridge a very wide pit.
    ("Long span",
     [
      "########################",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#......................#",
      "#@...................>.#",
      "#####........###########"],
     ["RJ3 R3 RJ18 .3 RJ3 R3 .3 LJ3 L3 R3 L3 RJ18 R6 .3", "RJ30 R6 .6 L3 .3 R6 RJ6 .3 RJ6 .3 L3 RJ3 R12 L9", "RJ30 R6 .9 RJ3 .9 R9 L12 R27 .3 R3 RJ3 R78"]),

    # 18. Triple lock: Three plates, three doors, three ghosts.
    ("Triple lock",
     [
      "########################",
      "#.....A....B....C......#",
      "#.....A....B....C......#",
      "#.....A....B....C......#",
      "#.....A....B....C......#",
      "#.....A....B....C......#",
      "#@.a..A.b#.B.c#.C....>.#",
      "########################"],
     ["R18", "R72", "R66 RJ3 R3 .3 R36", "R66 RJ3 .3 R3 .3 R12 .6 R21 RJ3 .3 R15 .3 R3 .3 R45"]),

    # 19. Penthouse: The plate is on top of a tall block: stack two ghosts, then leave a third on the plate.
    ("Penthouse",
     [
      "##################",
      "#.............A..#",
      "#.............A..#",
      "#.............A..#",
      "#.............A..#",
      "#.............A..#",
      "#.........a...A..#",
      "#.......#####.A..#",
      "#.......#####.A..#",
      "#.......#####.A..#",
      "#@......#####.A.>#",
      "##################"],
     ["R63", "RJ3 R15 L3 .6 R3 .3 R3 .6", "RJ6 .3 RJ3 .3 R3 L3 R3 .6 R3 L3 .3 RJ9 R24", "RJ6 .3 RJ3 .3 R3 L3 R3 .6 R3 L3 .3 RJ9 .3 R60 .3 R6 RJ9 R3"]),

    # 20. Finale: A mid-air bridge, a boost, a plate on the roof and a door at the end.
    ("Finale",
     [
      "########################",
      "#..................A...#",
      "#..................A...#",
      "#..................A...#",
      "#..................A...#",
      "#..................A...#",
      "#..................A...#",
      "#..............a...A...#",
      "#.............####.A...#",
      "#.............####.A...#",
      "#@............####.A.>.#",
      "#####.....##############"],
     ["RJ3 R3 RJ18 .3 RJ3 R3 .3 LJ3 L3 R3 L3 RJ15 R9", "RJ15 R15 .3 L3 .6 RJ3 .3 RJ6 .9 R51", "RJ15 R15 L3 .3 L3 .6 RJ9 .9 R33 RJ3 R3 .3 R3 .3 RJ9 R24", "RJ15 R15 L3 .3 L3 RJ9 .9 R33 RJ3 R3 .3 R3 .3 RJ9 R51 .3 R21"]),
]


def seq(spec):
    """'R40 RJ12 .20' -> one key string per frame."""
    out = []
    for tok in spec.split():
        keys = tok.rstrip("0123456789")
        out += [keys.replace(".", "")] * int(tok[len(keys):])
    return out


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class Room:
    def __init__(self, rows, name=""):
        self.name = name
        assert len({len(r) for r in rows}) == 1, "room rows must be the same width"
        self.rows, self.h, self.w = rows, len(rows), len(rows[0])
        self.solid, self.plates, self.doors = set(), {}, {}
        self.start = self.exit = None
        for y, row in enumerate(rows):
            for x, c in enumerate(row):
                if c == "#":
                    self.solid.add((x, y))
                elif c == "@":
                    self.start = (x, y)
                elif c == ">":
                    self.exit = (x, y)
                elif c in "abc":
                    self.plates.setdefault(c, []).append((x, y))
                elif c in "ABC":
                    self.doors.setdefault(c, []).append((x, y))

    def is_solid(self, tx, ty):
        if tx < 0 or tx >= self.w or ty < 0:
            return True
        return ty < self.h and (tx, ty) in self.solid


class Run:
    """One pass through a room: the live player plus the ghosts of earlier passes."""

    def __init__(self, room, ghosts):
        self.room, self.ghosts = room, ghosts
        self.x = room.start[0] * T + (T - PW) / 2
        self.y = (room.start[1] + 1) * T - PH
        self.vx = self.vy = 0.0
        self.on_ground, self.on = False, None     # standing on tiles / on ghost #n
        self.coyote = self.buffer = 0
        self.jump_prev = False
        self.t, self.path = 0, [(self.x, self.y)]
        self.done = self.dead = False
        self.events = []

    # -- helpers -----------------------------------------------------------
    def ghost_at(self, i, t):
        g = self.ghosts[i]
        return g[min(t, len(g) - 1)]

    def door_state(self, t):
        """Which plates are pressed and which door tiles are solid at time t."""
        room = self.room
        bodies = [(*self.ghost_at(i, t), PW, PH) for i in range(len(self.ghosts))]
        bodies.append((self.x, self.y, PW, PH))
        pressed = set()
        for c, cells in room.plates.items():
            for cx, cy in cells:
                sensor = (cx * T, (cy + 1) * T - 6, T, 6)
                if any(overlap(sensor, b) for b in bodies):
                    pressed.add(c)
        closed = []
        for c, cells in room.doors.items():
            if c.lower() in pressed:
                continue
            for cx, cy in cells:
                r = (cx * T, cy * T, T, T)
                # a door never closes on someone standing in the doorway
                if not any(overlap(r, b) for b in bodies):
                    closed.append(r)
        return pressed, closed

    def _hits(self, closed):
        x0, x1 = math.floor(self.x / T), math.floor((self.x + PW - 1e-6) / T)
        y0, y1 = math.floor(self.y / T), math.floor((self.y + PH - 1e-6) / T)
        rects = [(tx * T, ty * T, T, T) for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)
                 if self.room.is_solid(tx, ty)]
        return rects + list(closed)

    # -- one frame ---------------------------------------------------------
    def step(self, keys):
        t = self.t
        _, closed = self.door_state(t)

        if self.on is not None:                    # ride the ghost we stand on
            a, b = self.ghost_at(self.on, t), self.ghost_at(self.on, t + 1)
            self.x += b[0] - a[0]
            self.y += b[1] - a[1]
        old_bottom = self.y + PH

        d = ("R" in keys) - ("L" in keys)
        if d:
            a = 0.75 if self.on_ground else 0.5
            self.vx += max(-a, min(a, d * MAXV - self.vx))
        else:
            a = 0.9 if self.on_ground else 0.12
            self.vx -= max(-a, min(a, self.vx))

        held = "J" in keys
        press = held and not self.jump_prev
        self.jump_prev = held
        self.buffer = BUFFER if press else max(0, self.buffer - 1)
        self.coyote = COYOTE if self.on_ground else max(0, self.coyote - 1)
        if self.buffer and self.coyote:
            self.vy = -JUMP_V
            self.buffer = self.coyote = 0
            self.on_ground, self.on = False, None
            self.events.append(("jump", self.x + PW / 2, self.y + PH))
        self.vy = min(self.vy + GRAV * (RELEASE_GRAV if self.vy < 0 and not held else 1.0), MAXFALL)

        self.x += self.vx
        for r in self._hits(closed):
            if overlap((self.x, self.y, PW, PH), r):
                self.x = r[0] - PW if self.x + PW / 2 < r[0] + r[2] / 2 else r[0] + r[2]
                self.vx = 0.0

        self.y += self.vy
        landed, impact = False, 0.0
        for r in self._hits(closed):
            if overlap((self.x, self.y, PW, PH), r):
                if self.y + PH / 2 < r[1] + r[3] / 2:
                    self.y = r[1] - PH
                    if self.vy > 0:
                        landed, impact = True, self.vy
                        self.vy = 0.0
                else:
                    self.y = r[1] + r[3]
                    self.vy = max(self.vy, 0.0)

        on = None                                  # ghosts are one-way platforms
        if not landed and self.vy >= 0:
            best = None
            for i in range(len(self.ghosts)):
                (gx, gy), (px, py) = self.ghost_at(i, t + 1), self.ghost_at(i, t)
                if self.x < gx + PW and gx < self.x + PW and self.y + PH >= gy \
                        and (i == self.on or old_bottom <= py + 1.0) and (best is None or gy < best[0]):
                    best = (gy, i)
            if best:
                self.y, on = best[0] - PH, best[1]
                landed, impact = True, self.vy
                self.vy = 0.0
        if landed and not self.on_ground and impact > 3:
            self.events.append(("land", self.x + PW / 2, self.y + PH, impact))
        self.on_ground, self.on = landed, on

        self.t += 1
        self.path.append((self.x, self.y))
        ex, ey = self.room.exit
        if overlap((self.x, self.y, PW, PH), (ex * T + 6, ey * T + 4, T - 12, T - 4)):
            self.done = True
        elif self.y > self.room.h * T + 60:
            self.dead = True
        return self.done


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------
def solvable(room, solution):
    """Replay a hand-made solution with the real physics."""
    ghosts = []
    for n, spec in enumerate(solution):
        run = Run(room, ghosts)
        for keys in seq(spec):
            if run.step(keys):
                break
        if n == len(solution) - 1:
            return run.done
        if run.done or run.dead:
            return False
        ghosts.append(run.path)
    return False


def variant(rows, solution, flip):
    if flip:
        rows, solution = [r[::-1] for r in rows], [s.translate(FLIP_H) for s in solution]
    return rows, solution


def make_level(seed, rooms=6):
    """seed None: the whole campaign, in order. Otherwise a seeded random run of
    `rooms` different modules, mirrored at random, easiest first. A room is only
    used if its stored solution replays successfully."""
    if seed is None:
        return [(name, rows) for name, rows, _ in MODULES]
    rng = random.Random(seed)
    out = []
    for i in sorted(rng.sample(range(len(MODULES)), rooms)):
        name, rows, sol = MODULES[i]
        rows, sol = variant(rows, sol, rng.random() < .5)
        if solvable(Room(rows), sol):
            out.append((name, rows))
    return out


def self_test():
    n = 0
    assert len({m[0] for m in MODULES}) == len(MODULES), "room names must be unique"
    for name, rows, sol in MODULES:
        room = Room(rows, name)
        assert room.start and room.exit and room.w <= 24 and room.h <= 14, name
        for flip in (0, 1):
            r, s = variant(rows, sol, flip)
            assert solvable(Room(r), s), (name, flip)
            n += 1
    # the module designs depend on these jump heights
    room = Room(MODULES[0][1])
    for script, low, high in (("J1 J60", 2.4, 2.8), ("J1 .60", 0.7, 1.4)):
        run, top = Run(room, []), 0.0
        for keys in seq(".5") + seq(script):
            run.step(keys)
            top = max(top, room.start[1] * T + T - PH - run.y)
        assert low <= top / T <= high, (script, top / T)
    assert len(make_level(None)) == len(MODULES)
    assert all(len(make_level(seed)) == 6 for seed in range(300))
    print(f"ok: {len(MODULES)} rooms, {n} variants solvable, jump heights in range, 300 seeded runs build")


# ---------------------------------------------------------------------------
# Game state (no pygame in here, so it can be tested anywhere)
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, seed, first=0):
        self.seed, self.i = seed, first
        self.rooms = [Room(rows, name) for name, rows in make_level(seed)]
        self.clear_timer, self.note, self.note_t, self.events = 0, "", 0, []
        self.restart()

    @property
    def room(self):
        return self.rooms[self.i] if self.i < len(self.rooms) else None

    def say(self, msg, frames=70):
        self.note, self.note_t = msg, frames

    def restart(self):
        self.ghosts = []
        self.retry()

    def retry(self):
        self.run = Run(self.room, self.ghosts) if self.room else None

    def commit(self):
        if self.run and not self.clear_timer and self.run.t >= 5:
            midair = not self.run.on_ground
            self.ghosts.append(self.run.path)
            self.say(f"Ghost {len(self.ghosts)} saved" + (" (frozen mid-air!)" if midair else ""))
            self.retry()

    def update(self, keys):
        self.note_t = max(0, self.note_t - 1)
        if not self.run:
            return
        if self.clear_timer:
            self.clear_timer -= 1
            if not self.clear_timer:
                self.i += 1
                self.restart()
            return
        self.run.step(keys)
        self.events += self.run.events
        self.run.events = []
        if self.run.done:
            self.clear_timer = 50
        elif self.run.dead:
            self.say("You fell. Try again.")
            self.retry()


# ---------------------------------------------------------------------------
# Pygame front end
# ---------------------------------------------------------------------------
def main(seed, first=0):
    import pygame
    pygame.init()
    W, H, TOP, BOT = 800, 560, 44, 40
    screen = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 19)
    big = pygame.font.SysFont("arial", 46, bold=True)

    BG1, BG2 = (22, 16, 48), (8, 6, 20)
    INK, VIOLET, LIME = (238, 235, 250), (150, 120, 255), (182, 255, 61)
    TILE, TILE_TOP, MUTED = (44, 36, 92), (112, 98, 196), (150, 144, 190)
    COLS = {"a": (255, 196, 64), "b": (255, 90, 160), "c": (80, 220, 200)}

    bg = pygame.Surface((W, H))
    for y in range(H):
        f = y / H
        pygame.draw.line(bg, tuple(int(BG1[k] + (BG2[k] - BG1[k]) * f) for k in range(3)), (0, y), (W, y))
    star_rng = random.Random(7)
    for _ in range(70):
        sx, sy = star_rng.randrange(W), star_rng.randrange(H)
        pygame.draw.circle(bg, (70, 60, 130), (sx, sy), star_rng.choice((1, 1, 2)))

    ghost_img = pygame.Surface((PW, PH), pygame.SRCALPHA)
    pygame.draw.rect(ghost_img, (*VIOLET, 105), (0, 0, PW, PH), border_radius=6)
    pygame.draw.rect(ghost_img, (*VIOLET, 230), (0, 0, PW, PH), 2, border_radius=6)
    trail_imgs = []
    for k in range(6):
        s = pygame.Surface((PW - k * 2, PH - k * 2), pygame.SRCALPHA)
        pygame.draw.rect(s, (*VIOLET, 70 - k * 11), s.get_rect(), border_radius=5)
        trail_imgs.append(s)

    layers = {}

    def layer(room):
        """The walls never change, so draw them once per room."""
        if id(room) not in layers:
            s = pygame.Surface((room.w * T, room.h * T), pygame.SRCALPHA)
            for y in range(room.h):
                for x in range(room.w):
                    if (x, y) in room.solid:
                        r = pygame.Rect(x * T, y * T, T, T)
                        pygame.draw.rect(s, TILE, r)
                        pygame.draw.rect(s, (60, 50, 118), r, 1)
                        if not room.is_solid(x, y - 1):
                            pygame.draw.rect(s, TILE_TOP, (r.x, r.y, T, 4))
                    else:
                        pygame.draw.rect(s, (255, 255, 255, 7), (x * T, y * T, T, T), 1)
            layers[id(room)] = s
        return layers[id(room)]

    def text(msg, pos, color=INK, f=font, center=False):
        img = f.render(msg, True, color)
        screen.blit(img, (pos[0] - img.get_width() // 2, pos[1]) if center else pos)

    def start(s, first=0):
        pygame.display.set_caption("Echo - campaign" if s is None else f"Echo - seed {s}")
        return Game(s, first)

    game, frame = start(seed, first), 0
    particles, door_open, squash, facing = [], {}, 0, 1

    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                return
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE:
                    game.commit()
                elif e.key == pygame.K_z and game.run and not game.clear_timer:
                    game.retry()
                elif e.key == pygame.K_r and game.room:
                    game.restart()
                elif e.key == pygame.K_n:
                    game, door_open = start(random.randrange(10 ** 6)), {}
                elif e.key == pygame.K_c:
                    game, door_open = start(None), {}

        k = pygame.key.get_pressed()
        keys = ("L" if k[pygame.K_LEFT] or k[pygame.K_a] else "") + \
               ("R" if k[pygame.K_RIGHT] or k[pygame.K_d] else "") + \
               ("J" if k[pygame.K_UP] or k[pygame.K_w] else "")
        if ("R" in keys) != ("L" in keys):
            facing = 1 if "R" in keys else -1
        game.update(keys)
        frame += 1

        for ev in game.events:
            n, ex, ey = (5, 0, 0) if ev[0] == "jump" else (7, 0, 0)
            if ev[0] == "land":
                squash = 7
            for _ in range(n):
                particles.append([ev[1], ev[2], random.uniform(-1.6, 1.6), random.uniform(-1.4, -0.2), 22, INK])
        game.events = []
        for p in particles:
            p[0] += p[2]; p[1] += p[3]; p[3] += 0.08; p[4] -= 1
        particles = [p for p in particles if p[4] > 0]
        squash = max(0, squash - 1)

        # ---- draw ----
        screen.blit(bg, (0, 0))
        room, run = game.room, game.run
        if not room:
            text("All rooms cleared!", (W // 2, H // 2 - 40), LIME, big, True)
            text("N: new random run     C: play the campaign again", (W // 2, H // 2 + 28), MUTED, font, True)
        else:
            ox = (W - room.w * T) // 2
            oy = TOP + (H - TOP - BOT - room.h * T) // 2
            screen.blit(layer(room), (ox, oy))
            t = run.t
            pressed, closed = run.door_state(t)

            for c, cells in room.plates.items():
                for cx, cy in cells:
                    down = c in pressed
                    h = 3 if down else 7
                    pygame.draw.rect(screen, COLS[c], (ox + cx * T + 4, oy + (cy + 1) * T - h, T - 8, h), border_radius=2)
                    if down:
                        pygame.draw.circle(screen, COLS[c], (ox + cx * T + T // 2, oy + (cy + 1) * T - 4), T // 2 + 2, 2)
            for c, cells in room.doors.items():
                for cx, cy in cells:
                    target = 1.0 if c.lower() in pressed else 0.0
                    o = door_open[(id(room), cx, cy)] = door_open.get((id(room), cx, cy), 0.0) * 0.8 + target * 0.2
                    bar = round((1 - o) * T)
                    if bar > 1:
                        pygame.draw.rect(screen, COLS[c.lower()], (ox + cx * T + 6, oy + cy * T, T - 12, bar), border_radius=3)
                        pygame.draw.rect(screen, INK, (ox + cx * T + 6, oy + cy * T, T - 12, bar), 1, border_radius=3)
                    pygame.draw.rect(screen, COLS[c.lower()], (ox + cx * T + 4, oy + cy * T, T - 8, 3))
            ex, ey = room.exit
            pulse = 1 + 0.08 * math.sin(frame * 0.12)
            ew, eh = int((T - 10) * pulse), int((T - 2) * pulse)
            pygame.draw.rect(screen, LIME, (ox + ex * T + (T - ew) // 2, oy + (ey + 1) * T - eh, ew, eh), border_radius=6)
            pygame.draw.rect(screen, INK, (ox + ex * T + (T - ew) // 2, oy + (ey + 1) * T - eh, ew, eh), 2, border_radius=6)

            for i in range(len(run.ghosts)):
                for j in range(5, 0, -1):          # fading trail
                    gx, gy = run.ghost_at(i, max(0, t - j * 3))
                    img = trail_imgs[j]
                    screen.blit(img, (ox + gx + (PW - img.get_width()) / 2, oy + gy + (PH - img.get_height()) / 2))
                gx, gy = run.ghost_at(i, t)
                screen.blit(ghost_img, (ox + gx, oy + gy))
                nx = run.ghost_at(i, t + 1)[0]
                gf = 1 if nx >= gx else -1
                for dx in (-4, 4):
                    pygame.draw.rect(screen, INK, (ox + gx + PW / 2 + dx + gf * 2 - 1, oy + gy + 8, 3, 5))

            for p in particles:
                pygame.draw.rect(screen, p[5], (ox + p[0], oy + p[1], 3, 3))

            st = min(0.28, abs(run.vy) * 0.03)
            w, h = PW * (1 - st * 0.5), PH * (1 + st)
            if squash:
                w, h = PW * (1 + squash * 0.04), PH * (1 - squash * 0.04)
            body = pygame.Rect(0, 0, w, h)
            body.midbottom = (ox + run.x + PW / 2, oy + run.y + PH)
            pygame.draw.rect(screen, INK, body, border_radius=6)
            for dx in (-4, 4):
                pygame.draw.rect(screen, BG2, (body.centerx + dx + facing * 2 - 1, body.y + h * 0.28, 3, 5))

            text(f"Room {game.i + 1}/{len(game.rooms)}  {room.name}    Run {len(game.ghosts) + 1}", (16, 12))
            label = "Campaign" if game.seed is None else f"Seed {game.seed}"
            text(label, (W - 16 - font.size(label)[0], 12), MUTED)
            if game.note_t:
                text(game.note, (W // 2, 12), LIME, font, True)
            text("Up/W jump    Space save run as ghost    Z retry run    R restart room    N random run",
                 (W // 2, H - 30), MUTED, font, True)
            if game.clear_timer:
                text("ROOM CLEAR", (W // 2, H // 2 - 30), LIME, big, True)

        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        arg = lambda flag: int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else None
        main(arg("--seed"), max(0, (arg("--room") or 1) - 1))
