"""Echo: cooperate with your past selves.

Every run you save becomes a ghost that replays your exact movements. Ghosts
hold pressure plates down, and you can stand on their heads to reach ledges
that are too high to jump to alone.

Play:       python echo.py [--seed N]
Self-check: python echo.py --test

Controls:   Left/Right or A/D  run          Up or W   jump (hold = higher)
            Space              save this run as a ghost
            Z                  retry this run (keeps your ghosts)
            R                  restart the room (clears your ghosts)
            N                  new random seed          Esc   quit
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
# Room legend:  # wall   @ start   > exit   a/b pressure plate
#               A/B door (open while anything stands on the matching plate)
#               . air (a gap in the bottom row is a pit)
# Each module ships with a hand-made solution: one input script per pass, the
# last pass must reach the exit. Script tokens are KEYS+FRAMES, for example
# "R40 RJ12 .20" = run right 40 frames, jump right 12, wait 20.
# ---------------------------------------------------------------------------
MODULES = [
    # 1. A plate and a door: leave a ghost on the plate.
    (["################",
      "#.....A........#",
      "#.....A........#",
      "#.....A........#",
      "#.....A........#",
      "#@..a.A......>.#",
      "################"],
     ["R35 .10", "R130"]),

    # 2. Climb the stairs to a plate on a floating ledge.
    (["##################",
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

    # 3. The exit is on a high block: step on your own ghost to reach it.
    (["################",
      "#..............#",
      "#..............#",
      "#..............#",
      "#............>.#",
      "#........#######",
      "#........#######",
      "#@.......#######",
      "################"],
     ["R200", "R30 RJ36 R4 RJ30 R70"]),

    # 4. Jump the pit, press the plate, jump the pit again.
    (["####################",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#..............A...#",
      "#.@.........a..A..>#",
      "#######...##########"],
     ["R44 RJ36 R14 .12", "R44 RJ36 R120"]),

    # 5. Two plates, two doors, and a crate to hop over.
    (["########################",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#.......A.........B....#",
      "#@..a...A..#..b...B..>.#",
      "########################"],
     ["R35 .10", "R90 RJ36 R3 .10", "R90 RJ36 R103"]),

    # 6. A taller block needs two ghosts stacked up.
    (["##################",
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
    def __init__(self, rows):
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
                elif c in "ab":
                    self.plates.setdefault(c, []).append((x, y))
                elif c in "AB":
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


def make_level(seed, rooms=4):
    """A seeded chain of modules, mirrored at random and sorted easiest first.
    A room is kept only if its stored solution replays successfully."""
    rng = random.Random(seed)
    picks = [variant(*rng.choice(MODULES), rng.random() < .5) for _ in range(rooms)]
    good = [p for p in picks if solvable(Room(p[0]), p[1])]
    return [rows for rows, _ in sorted(good, key=lambda p: len(p[1]))]


def self_test():
    n = 0
    for rows, sol in MODULES:
        for flip in (0, 1):
            r, s = variant(rows, sol, flip)
            assert solvable(Room(r), s), (rows[0], flip)
            n += 1
    # the module designs depend on these jump heights
    room = Room(MODULES[0][0])
    for script, low, high in (("J1 J60", 2.4, 2.8), ("J1 .60", 0.7, 1.4)):
        run, top = Run(room, []), 0.0
        for keys in seq(".5") + seq(script):
            run.step(keys)
            top = max(top, room.start[1] * T + T - PH - run.y)
        assert low <= top / T <= high, (script, top / T)
    assert all(len(make_level(seed)) == 4 for seed in range(300))
    print(f"ok: {n} module variants solvable, jump heights in range, 300 seeds generate full levels")


# ---------------------------------------------------------------------------
# Game state (no pygame in here, so it can be tested anywhere)
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, seed):
        self.seed, self.i = seed, 0
        self.rooms = [Room(r) for r in make_level(seed)]
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
            self.ghosts.append(self.run.path)
            self.say(f"Ghost {len(self.ghosts)} saved")
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
def main(seed):
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
    COLS = {"a": (255, 196, 64), "b": (255, 90, 160)}

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

    def start(s):
        pygame.display.set_caption(f"Echo - seed {s}")
        return Game(s)

    game, frame = start(seed), 0
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
                    seed = random.randrange(10 ** 6)
                    game, door_open = start(seed), {}

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
            text("Press N for a new seed", (W // 2, H // 2 + 28), MUTED, font, True)
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

            text(f"Room {game.i + 1}/{len(game.rooms)}    Run {len(game.ghosts) + 1}    Ghosts {len(game.ghosts)}", (16, 12))
            text(f"Seed {game.seed}", (W - 16 - font.size(f"Seed {game.seed}")[0], 12), MUTED)
            if game.note_t:
                text(game.note, (W // 2, 12), LIME, font, True)
            text("Up/W jump    Space save run as ghost    Z retry run    R restart room    N new seed",
                 (W // 2, H - 30), MUTED, font, True)
            if game.clear_timer:
                text("ROOM CLEAR", (W // 2, H // 2 - 30), LIME, big, True)

        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        main(int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else random.randrange(10 ** 6))
