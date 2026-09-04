"""
===================================================================
ESP32 + MPU6050 Tilt-Controlled Car Racing Game (Laptop Dashboard)
===================================================================
KAAM (What this does):
- Background me ek UDP server chalta hai jo ESP32 se aane wala tilt
  angle continuously receive karta hai.
- Us tilt angle ke basis par car ko left/right move karta hai.
- Ek simple "endless car racing" game hai: upar se obstacle cars
  aati hain, unse bachte hue jitni der tak zinda raho utna score
  badhta jaata hai.

CONTROLS:
- MPU6050 ko left-right tilt karo -> car left-right move karegi.
- Agar sensor connect nahi hai to Keyboard Left/Right arrow keys
  se bhi test kar sakte ho (fallback control).
- 'R' key dabao game-over ke baad restart karne ke liye.
- 'ESC' ya window band karke exit karo.

SETUP STEPS (pehle yeh karo):
1. Python install hona chahiye (3.8+).
2. Terminal me yeh command chalao dependencies install karne ke liye:
       pip install pygame
3. Neeche UDP_PORT wahi rakho jo ESP32 ke code me daala tha (4210).
4. Windows Firewall / Mac Firewall me is Python script ko
   "allow" karna pad sakta hai UDP traffic receive karne ke liye
   (pehli baar chalane par ek popup aayega, "Allow" pe click karo).
5. Yeh script chalao:
       python car_racing_game.py
6. Fir ESP32 ko power do -- wo apne aap data bhejna shuru kar dega.
===================================================================
"""

import socket
import threading
import random
import pygame
import sys

# ------------------------------------------------------------------
# STEP 1: Settings (yeh values apni zarurat ke hisaab se badal sakte ho)
# ------------------------------------------------------------------
UDP_IP = "0.0.0.0"      # 0.0.0.0 matlab -> is laptop ke kisi bhi network se data lo
UDP_PORT = 4210          # ESP32 code me jo port daala tha, wahi yahan hona chahiye

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 700
ROAD_LEFT = 90            # road ki left boundary (x position)
ROAD_RIGHT = SCREEN_WIDTH - 90  # road ki right boundary (x position)

CAR_WIDTH = 50
CAR_HEIGHT = 90

TILT_SENSITIVITY = 6.0    # jitna zyada, utna tilt se car utni tezi se move hogi
MAX_TILT_ANGLE = 30.0     # is se zyada tilt ko ignore/clip kar denge (safety)

FPS = 60

# Colors (R, G, B)
COLOR_BG = (30, 32, 38)
COLOR_ROAD = (55, 58, 68)
COLOR_ROAD_LINE = (230, 230, 230)
COLOR_PLAYER_CAR = (66, 165, 245)   # blue
COLOR_ENEMY_CAR = (239, 83, 80)     # red
COLOR_TEXT = (255, 255, 255)
COLOR_SHADOW = (0, 0, 0)


# ------------------------------------------------------------------
# STEP 2: Shared data jo UDP thread aur Game thread dono use karenge
# ------------------------------------------------------------------
class SharedTiltData:
    """
    Yeh class ek 'safe box' ki tarah hai jisme latest tilt angle store
    hota hai. Ek thread (UDP listener) ismein value likhta hai, aur
    doosra thread (game loop) ismein se value padhta hai.
    """
    def __init__(self):
        self.angle = 0.0
        self.connected = False
        self.lock = threading.Lock()

    def update(self, new_angle):
        with self.lock:
            self.angle = new_angle
            self.connected = True

    def get(self):
        with self.lock:
            return self.angle, self.connected


tilt_data = SharedTiltData()


def udp_listener_thread():
    """
    Yeh function background me chalta rehta hai (alag thread me) aur
    ESP32 se aane wale UDP packets ko continuously receive karta hai.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"UDP server shuru ho gaya -> {UDP_IP}:{UDP_PORT} par sun raha hoon...")

    while True:
        try:
            data, addr = sock.recvfrom(1024)  # max 1024 bytes ek packet me
            text = data.decode("utf-8").strip()
            angle = float(text)
            tilt_data.update(angle)
        except (ValueError, UnicodeDecodeError):
            # Agar galat/corrupt data aaya to usko ignore kar do, crash mat karo
            continue
        except OSError:
            break


# ------------------------------------------------------------------
# STEP 3: Game ke objects (Player Car aur Obstacle Cars)
# ------------------------------------------------------------------
class PlayerCar:
    def __init__(self):
        self.x = SCREEN_WIDTH / 2
        self.y = SCREEN_HEIGHT - 140
        self.width = CAR_WIDTH
        self.height = CAR_HEIGHT

    def update(self, dt, current_angle):
        # Tilt angle ko car ki horizontal speed me convert karo
        # (angle jitna zyada, car utni tezi se us taraf jaayegi)
        clipped_angle = max(-MAX_TILT_ANGLE, min(MAX_TILT_ANGLE, current_angle))
        velocity_x = clipped_angle * TILT_SENSITIVITY

        self.x += velocity_x * dt

        # Car ko road ke andar hi rakho (boundary check)
        half_w = self.width / 2
        if self.x - half_w < ROAD_LEFT:
            self.x = ROAD_LEFT + half_w
        if self.x + half_w > ROAD_RIGHT:
            self.x = ROAD_RIGHT - half_w

    def get_rect(self):
        return pygame.Rect(self.x - self.width / 2, self.y - self.height / 2,
                            self.width, self.height)

    def draw(self, screen):
        rect = self.get_rect()
        # halka sa shadow effect
        shadow_rect = rect.copy()
        shadow_rect.y += 6
        pygame.draw.rect(screen, COLOR_SHADOW, shadow_rect, border_radius=10)
        pygame.draw.rect(screen, COLOR_PLAYER_CAR, rect, border_radius=10)
        # windshield (thoda design ke liye)
        windshield = pygame.Rect(rect.x + 10, rect.y + 12, rect.width - 20, 22)
        pygame.draw.rect(screen, (200, 230, 255), windshield, border_radius=4)


class EnemyCar:
    def __init__(self, speed):
        half_w = CAR_WIDTH / 2
        self.x = random.uniform(ROAD_LEFT + half_w, ROAD_RIGHT - half_w)
        self.y = -CAR_HEIGHT
        self.width = CAR_WIDTH
        self.height = CAR_HEIGHT
        self.speed = speed

    def update(self, dt):
        self.y += self.speed * dt

    def get_rect(self):
        return pygame.Rect(self.x - self.width / 2, self.y - self.height / 2,
                            self.width, self.height)

    def draw(self, screen):
        rect = self.get_rect()
        pygame.draw.rect(screen, COLOR_ENEMY_CAR, rect, border_radius=10)
        windshield = pygame.Rect(rect.x + 10, rect.y + rect.height - 34, rect.width - 20, 22)
        pygame.draw.rect(screen, (60, 20, 20), windshield, border_radius=4)

    def is_off_screen(self):
        return self.y - self.height / 2 > SCREEN_HEIGHT


# ------------------------------------------------------------------
# STEP 4: Road ki scrolling lines banane ke liye helper
# ------------------------------------------------------------------
class RoadLines:
    def __init__(self):
        self.offset = 0.0
        self.line_gap = 60
        self.line_height = 30

    def update(self, dt, speed):
        self.offset += speed * dt
        if self.offset > self.line_gap:
            self.offset -= self.line_gap

    def draw(self, screen):
        center_x = SCREEN_WIDTH / 2
        y = -self.line_gap + self.offset
        while y < SCREEN_HEIGHT:
            pygame.draw.rect(screen, COLOR_ROAD_LINE,
                              (center_x - 4, y, 8, self.line_height))
            y += self.line_gap


# ------------------------------------------------------------------
# STEP 5: Main Game class (poora game yahan chalta hai)
# ------------------------------------------------------------------
class CarRacingGame:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("MPU6050 Tilt Car Racing")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        self.font_large = pygame.font.SysFont("arial", 48, bold=True)
        self.font_medium = pygame.font.SysFont("arial", 26)
        self.font_small = pygame.font.SysFont("arial", 18)

        self.reset()

    def reset(self):
        self.player = PlayerCar()
        self.enemies = []
        self.road_lines = RoadLines()
        self.score = 0.0
        self.enemy_speed = 260.0        # pixels per second
        self.spawn_timer = 0.0
        self.spawn_interval = 1.2        # seconds
        self.game_over = False
        self.elapsed = 0.0

    def spawn_enemy_if_needed(self, dt):
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_interval:
            self.spawn_timer = 0.0
            self.enemies.append(EnemyCar(self.enemy_speed))

    def update(self, dt, keyboard_angle_override):
        if self.game_over:
            return

        self.elapsed += dt

        # ---------- Tilt angle lo (UDP se, ya keyboard fallback se) ----------
        angle, connected = tilt_data.get()
        if not connected:
            # Agar ESP32 se abhi tak koi data nahi aaya, to keyboard use karo
            angle = keyboard_angle_override

        self.player.update(dt, angle)

        # ---------- Difficulty dheere dheere badhao ----------
        self.enemy_speed = 260.0 + self.elapsed * 8.0
        self.spawn_interval = max(0.5, 1.2 - self.elapsed * 0.01)

        self.road_lines.update(dt, self.enemy_speed)
        self.spawn_enemy_if_needed(dt)

        # ---------- Enemies update karo ----------
        for enemy in self.enemies:
            enemy.speed = self.enemy_speed
            enemy.update(dt)

        # off-screen ho chuki enemies hata do, aur score badhao
        still_on_screen = []
        for enemy in self.enemies:
            if enemy.is_off_screen():
                self.score += 10  # ek car cross karne par 10 points
            else:
                still_on_screen.append(enemy)
        self.enemies = still_on_screen

        # ---------- Collision check karo ----------
        player_rect = self.player.get_rect()
        for enemy in self.enemies:
            if player_rect.colliderect(enemy.get_rect()):
                self.game_over = True
                break

        # Time ke hisaab se bhi thoda score milta rahe
        self.score += dt * 5

    def draw_road(self):
        self.screen.fill(COLOR_BG)
        road_rect = pygame.Rect(ROAD_LEFT - 10, 0, (ROAD_RIGHT - ROAD_LEFT) + 20, SCREEN_HEIGHT)
        pygame.draw.rect(self.screen, COLOR_ROAD, road_rect)
        self.road_lines.draw(self.screen)

    def draw_hud(self):
        angle, connected = tilt_data.get()
        status_text = "ESP32: Connected" if connected else "ESP32: Waiting... (Arrow keys se test karo)"
        status_color = (120, 220, 120) if connected else (240, 190, 90)

        score_surf = self.font_medium.render(f"Score: {int(self.score)}", True, COLOR_TEXT)
        self.screen.blit(score_surf, (16, 16))

        status_surf = self.font_small.render(status_text, True, status_color)
        self.screen.blit(status_surf, (16, 50))

        angle_surf = self.font_small.render(f"Tilt: {angle:.1f} deg", True, COLOR_TEXT)
        self.screen.blit(angle_surf, (16, 72))

    def draw_game_over(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))

        title = self.font_large.render("GAME OVER", True, (255, 90, 90))
        title_rect = title.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 - 50))
        self.screen.blit(title, title_rect)

        score_surf = self.font_medium.render(f"Final Score: {int(self.score)}", True, COLOR_TEXT)
        score_rect = score_surf.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 + 10))
        self.screen.blit(score_surf, score_rect)

        hint_surf = self.font_small.render("'R' dabao restart karne ke liye", True, (200, 200, 200))
        hint_rect = hint_surf.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2 + 50))
        self.screen.blit(hint_surf, hint_rect)

    def draw(self):
        self.draw_road()
        for enemy in self.enemies:
            enemy.draw(self.screen)
        self.player.draw(self.screen)
        self.draw_hud()
        if self.game_over:
            self.draw_game_over()
        pygame.display.flip()

    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0  # dt = seconds since last frame

            keyboard_angle_override = 0.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if event.key == pygame.K_r and self.game_over:
                        self.reset()

            # Keyboard fallback (agar sensor abhi connect nahi hua)
            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT]:
                keyboard_angle_override = -15.0
            if keys[pygame.K_RIGHT]:
                keyboard_angle_override = 15.0

            self.update(dt, keyboard_angle_override)
            self.draw()


# ------------------------------------------------------------------
# STEP 6: Program yahan se shuru hota hai
# ------------------------------------------------------------------
if __name__ == "__main__":
    # UDP listener ko background thread me shuru karo, taaki game
    # (foreground) smoothly chalta rahe aur data bhi milta rahe.
    listener = threading.Thread(target=udp_listener_thread, daemon=True)
    listener.start()

    game = CarRacingGame()
    game.run()
