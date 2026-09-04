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
import math
import array

# ------------------------------------------------------------------
# STEP 1: Settings (yeh values apni zarurat ke hisaab se badal sakte ho)
# ------------------------------------------------------------------
UDP_IP = "0.0.0.0"      # 0.0.0.0 matlab -> is laptop ke kisi bhi network se data lo
UDP_PORT = 4210          # ESP32 code me jo port daala tha, wahi yahan hona chahiye

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 700
ROAD_LEFT = 80            # road ki left boundary (x position)
ROAD_RIGHT = SCREEN_WIDTH - 80  # road ki right boundary (x position)

CAR_WIDTH = 48
CAR_HEIGHT = 86

TILT_SENSITIVITY = 6.0    # jitna zyada, utna tilt se car utni tezi se move hogi
MAX_TILT_ANGLE = 30.0     # is se zyada tilt ko ignore/clip kar denge (safety)

FPS = 60

# Level Progression Milestones:
# Score 50 -> Level 2, 100 -> Level 3, 150 -> Level 4, 250 -> Level 5, 400 -> Level 6, etc.
LEVEL_THRESHOLDS = [
    (1, 0),
    (2, 50),
    (3, 100),
    (4, 150),
    (5, 250),
    (6, 400),
    (7, 600),
    (8, 850),
    (9, 1150),
    (10, 1500),
]

def get_level_for_score(score):
    lvl = 1
    for level_num, score_req in LEVEL_THRESHOLDS:
        if score >= score_req:
            lvl = level_num
        else:
            break
    return lvl

# Enhanced Modern Color Palette (R, G, B)
COLOR_GRASS_1 = (18, 26, 22)
COLOR_ROAD = (38, 41, 48)
COLOR_ROAD_SHOULDER = (28, 30, 36)
COLOR_CURB_RED = (235, 60, 60)
COLOR_CURB_WHITE = (240, 240, 245)
COLOR_ROAD_LINE = (235, 235, 240)
COLOR_ROAD_LINE_DIM = (120, 125, 135)

COLOR_PLAYER_CAR = (30, 144, 255)       # Dodger Blue
COLOR_PLAYER_CAR_DARK = (16, 90, 180)
COLOR_PLAYER_CAR_LIGHT = (90, 190, 255)
COLOR_PLAYER_STRIPE = (255, 255, 255)

ENEMY_PALETTES = [
    {"main": (235, 55, 55), "dark": (150, 25, 25), "light": (255, 110, 110), "stripe": (255, 240, 240)}, # Red
    {"main": (255, 140, 0), "dark": (180, 80, 0), "light": (255, 190, 70), "stripe": (30, 30, 30)},     # Orange
    {"main": (46, 204, 113), "dark": (26, 130, 70), "light": (100, 240, 160), "stripe": (255, 255, 255)},# Emerald
    {"main": (155, 89, 182), "dark": (100, 45, 125), "light": (205, 145, 230), "stripe": (255, 255, 255)},# Purple
    {"main": (241, 196, 15), "dark": (170, 135, 5), "light": (255, 225, 100), "stripe": (20, 20, 20)},   # Yellow
]

COLOR_TEXT = (255, 255, 255)
COLOR_TEXT_DIM = (180, 190, 205)
COLOR_SHADOW = (0, 0, 0)
COLOR_COIN = (255, 215, 0)          # Gold
COLOR_COIN_BORDER = (218, 165, 32)   # Dark goldenrod
COLOR_COIN_INNER = (255, 248, 180)   # Shiny highlight
COLOR_LEVEL = (56, 225, 255)        # Electric Cyan


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
# Audio Sound Effects Manager (Procedurally Synthesized Audio)
# ------------------------------------------------------------------
class SoundManager:
    """
    Real-time procedural audio generator. Zero external files required!
    Generates high quality 16-bit PCM sound effects for coins, level ups,
    crashes, and car engine hum directly in memory.
    """
    def __init__(self):
        self.enabled = False
        self.engine_channel = None
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.sample_rate = 22050
            self.sound_coin = self._generate_coin_sound()
            self.sound_levelup = self._generate_levelup_sound()
            self.sound_crash = self._generate_crash_sound()
            self.sound_engine = self._generate_engine_sound()
            self.enabled = True
        except Exception as e:
            print(f"Audio sound system warning (fallback to silent): {e}")

    def _generate_coin_sound(self):
        # 2-tone melodic gold chime: 988 Hz (B5) -> 1319 Hz (E6)
        samples = array.array('h')
        n1 = int(self.sample_rate * 0.07)
        for i in range(n1):
            t = float(i) / self.sample_rate
            env = 1.0 - (i / n1) * 0.3
            val = math.sin(2.0 * math.pi * 988 * t) * 0.45 * env
            samples.append(int(val * 32767))
            
        n2 = int(self.sample_rate * 0.15)
        for i in range(n2):
            t = float(i) / self.sample_rate
            env = (1.0 - (i / n2)) ** 1.6
            val = math.sin(2.0 * math.pi * 1319 * t) * 0.55 * env
            samples.append(int(val * 32767))
            
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def _generate_levelup_sound(self):
        # Ascending 4-tone celebratory fanfare: C5 (523Hz) -> E5 (659Hz) -> G5 (784Hz) -> C6 (1046Hz)
        samples = array.array('h')
        freqs = [523, 659, 784, 1046]
        note_dur = 0.08
        
        for f in freqs:
            n = int(self.sample_rate * note_dur)
            for i in range(n):
                t = float(i) / self.sample_rate
                env = (1.0 - (i / n) * 0.4)
                val = (math.sin(2 * math.pi * f * t) * 0.35 +
                       math.sin(4 * math.pi * f * t) * 0.15) * env
                samples.append(int(val * 32767))
                
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def _generate_crash_sound(self):
        # Heavy explosive bass impact rumble with noise decay
        samples = array.array('h')
        duration = 0.5
        n = int(self.sample_rate * duration)
        
        for i in range(n):
            t = float(i) / self.sample_rate
            env = math.exp(-6.5 * t)
            noise = (random.random() * 2.0 - 1.0)
            low_freq = math.sin(2.0 * math.pi * max(20, 110 - 70 * t) * t)
            val = (noise * 0.65 + low_freq * 0.35) * env * 0.8
            val = max(-1.0, min(1.0, val))
            samples.append(int(val * 32767))
            
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def _generate_engine_sound(self):
        # Smooth looping engine rumble
        samples = array.array('h')
        duration = 0.3
        n = int(self.sample_rate * duration)
        
        for i in range(n):
            t = float(i) / self.sample_rate
            val = (math.sin(2 * math.pi * 58 * t) * 0.18 +
                   math.sin(2 * math.pi * 116 * t) * 0.12 +
                   (random.random() * 2.0 - 1.0) * 0.04)
            samples.append(int(val * 32767))
            
        snd = pygame.mixer.Sound(buffer=samples.tobytes())
        snd.set_volume(0.20)
        return snd

    def play_coin(self):
        if self.enabled and hasattr(self, 'sound_coin'):
            self.sound_coin.play()

    def play_levelup(self):
        if self.enabled and hasattr(self, 'sound_levelup'):
            self.sound_levelup.play()

    def play_crash(self):
        if self.enabled and hasattr(self, 'sound_crash'):
            self.stop_engine()
            self.sound_crash.play()

    def start_engine(self):
        if self.enabled and hasattr(self, 'sound_engine'):
            if not self.engine_channel or not self.engine_channel.get_busy():
                self.engine_channel = self.sound_engine.play(loops=-1)

    def stop_engine(self):
        if self.engine_channel:
            self.engine_channel.stop()


# ------------------------------------------------------------------
# Visual Effects: Particles & Floating Text
# ------------------------------------------------------------------
class Particle:
    def __init__(self, x, y, vx, vy, color, radius, lifetime):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.color = color
        self.radius = radius
        self.lifetime = lifetime
        self.max_lifetime = lifetime

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.lifetime -= dt

    def draw(self, screen):
        if self.lifetime <= 0:
            return
        alpha_ratio = max(0.0, self.lifetime / self.max_lifetime)
        current_r = max(1, int(self.radius * alpha_ratio))
        s = pygame.Surface((current_r * 2, current_r * 2), pygame.SRCALPHA)
        col = (self.color[0], self.color[1], self.color[2], int(220 * alpha_ratio))
        pygame.draw.circle(s, col, (current_r, current_r), current_r)
        screen.blit(s, (self.x - current_r, self.y - current_r))


class FloatingText:
    def __init__(self, x, y, text, color, font):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.font = font
        self.lifetime = 0.8
        self.max_lifetime = 0.8

    def update(self, dt):
        self.y -= 45 * dt
        self.lifetime -= dt

    def draw(self, screen):
        if self.lifetime <= 0:
            return
        alpha = int(255 * max(0.0, self.lifetime / self.max_lifetime))
        surf = self.font.render(self.text, True, self.color)
        surf.set_alpha(alpha)
        rect = surf.get_rect(center=(int(self.x), int(self.y)))
        screen.blit(surf, rect)


# ------------------------------------------------------------------
# STEP 3: Game ke objects (Player Car, Obstacle Cars, aur Coins)
# ------------------------------------------------------------------
class PlayerCar:
    def __init__(self):
        self.x = SCREEN_WIDTH / 2
        self.y = SCREEN_HEIGHT - 130
        self.width = CAR_WIDTH
        self.height = CAR_HEIGHT
        self.tilt_visual = 0.0

    def update(self, dt, current_angle):
        clipped_angle = max(-MAX_TILT_ANGLE, min(MAX_TILT_ANGLE, current_angle))
        velocity_x = clipped_angle * TILT_SENSITIVITY

        self.x += velocity_x * dt
        self.tilt_visual = clipped_angle

        # Boundary check
        half_w = self.width / 2
        if self.x - half_w < ROAD_LEFT + 8:
            self.x = ROAD_LEFT + 8 + half_w
        if self.x + half_w > ROAD_RIGHT - 8:
            self.x = ROAD_RIGHT - 8 - half_w

    def get_rect(self):
        return pygame.Rect(self.x - self.width / 2, self.y - self.height / 2,
                            self.width, self.height)

    def draw(self, screen):
        rect = self.get_rect()

        # 1. Forward Headlight Beams (Glow on Road)
        headlight_surf = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        beam_left = [(self.x - 16, self.y - 30), (self.x - 38, self.y - 180), (self.x - 4, self.y - 180), (self.x - 10, self.y - 30)]
        beam_right = [(self.x + 10, self.y - 30), (self.x + 4, self.y - 180), (self.x + 38, self.y - 180), (self.x + 16, self.y - 30)]
        pygame.draw.polygon(headlight_surf, (255, 255, 200, 35), beam_left)
        pygame.draw.polygon(headlight_surf, (255, 255, 200, 35), beam_right)
        screen.blit(headlight_surf, (0, 0))

        # 2. Drop Shadow
        shadow_rect = rect.copy()
        shadow_rect.x += 3
        shadow_rect.y += 6
        shadow_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surface, (0, 0, 0, 90), (0, 0, rect.width, rect.height), border_radius=12)
        screen.blit(shadow_surface, shadow_rect.topleft)

        # 3. Tires (4 Wheels)
        tire_color = (20, 20, 24)
        rim_color = (160, 170, 185)
        tires = [
            (rect.x - 3, rect.y + 12, 6, 16),      # Front-Left
            (rect.right - 3, rect.y + 12, 6, 16),  # Front-Right
            (rect.x - 3, rect.bottom - 26, 6, 16), # Rear-Left
            (rect.right - 3, rect.bottom - 26, 6, 16) # Rear-Right
        ]
        for tx, ty, tw, th in tires:
            pygame.draw.rect(screen, tire_color, (tx, ty, tw, th), border_radius=3)
            pygame.draw.rect(screen, rim_color, (tx + 1, ty + 3, tw - 2, th - 6), border_radius=2)

        # 4. Main Aerodynamic Car Body
        pygame.draw.rect(screen, COLOR_PLAYER_CAR, rect, border_radius=14)
        inner_highlight = pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8)
        pygame.draw.rect(screen, COLOR_PLAYER_CAR_LIGHT, inner_highlight, width=2, border_radius=10)

        # 5. Dual White Racing Stripes
        stripe_w = 4
        center_x = rect.centerx
        pygame.draw.rect(screen, COLOR_PLAYER_STRIPE, (center_x - 6, rect.y + 6, stripe_w, rect.height - 12), border_radius=2)
        pygame.draw.rect(screen, COLOR_PLAYER_STRIPE, (center_x + 2, rect.y + 6, stripe_w, rect.height - 12), border_radius=2)

        # 6. Windshield Glass (Curved Front & Rear)
        front_windshield = pygame.Rect(rect.x + 8, rect.y + 20, rect.width - 16, 20)
        pygame.draw.rect(screen, (15, 30, 45), front_windshield, border_radius=6)
        pygame.draw.line(screen, (120, 210, 255), (rect.x + 12, rect.y + 24), (rect.right - 18, rect.y + 34), 2)

        rear_windshield = pygame.Rect(rect.x + 10, rect.bottom - 28, rect.width - 20, 12)
        pygame.draw.rect(screen, (15, 30, 45), rear_windshield, border_radius=4)

        # 7. Roof
        roof_rect = pygame.Rect(rect.x + 10, rect.y + 38, rect.width - 20, 18)
        pygame.draw.rect(screen, COLOR_PLAYER_CAR_DARK, roof_rect, border_radius=4)

        # 8. Rear Spoiler (Wing)
        spoiler_rect = pygame.Rect(rect.x + 4, rect.bottom - 6, rect.width - 8, 5)
        pygame.draw.rect(screen, (20, 20, 25), spoiler_rect, border_radius=2)

        # 9. Headlights & Neon Tail Lights
        pygame.draw.circle(screen, (255, 255, 220), (rect.x + 10, rect.y + 6), 4)
        pygame.draw.circle(screen, (255, 255, 220), (rect.right - 10, rect.y + 6), 4)

        pygame.draw.rect(screen, (255, 50, 50), (rect.x + 7, rect.bottom - 4, 8, 3), border_radius=2)
        pygame.draw.rect(screen, (255, 50, 50), (rect.right - 15, rect.bottom - 4, 8, 3), border_radius=2)


class EnemyCar:
    def __init__(self, speed):
        half_w = CAR_WIDTH / 2
        self.x = random.uniform(ROAD_LEFT + 20 + half_w, ROAD_RIGHT - 20 - half_w)
        self.y = -CAR_HEIGHT - random.uniform(0, 40)
        self.width = CAR_WIDTH
        self.height = CAR_HEIGHT
        self.speed = speed
        self.palette = random.choice(ENEMY_PALETTES)

    def update(self, dt):
        self.y += self.speed * dt

    def get_rect(self):
        return pygame.Rect(self.x - self.width / 2, self.y - self.height / 2,
                            self.width, self.height)

    def draw(self, screen):
        rect = self.get_rect()

        # Shadow
        shadow_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surface, (0, 0, 0, 80), (0, 0, rect.width, rect.height), border_radius=12)
        screen.blit(shadow_surface, (rect.x + 3, rect.y + 5))

        # Tires
        tire_color = (20, 20, 24)
        rim_color = (130, 135, 145)
        tires = [
            (rect.x - 3, rect.y + 12, 6, 16),
            (rect.right - 3, rect.y + 12, 6, 16),
            (rect.x - 3, rect.bottom - 26, 6, 16),
            (rect.right - 3, rect.bottom - 26, 6, 16)
        ]
        for tx, ty, tw, th in tires:
            pygame.draw.rect(screen, tire_color, (tx, ty, tw, th), border_radius=3)
            pygame.draw.rect(screen, rim_color, (tx + 1, ty + 3, tw - 2, th - 6), border_radius=2)

        # Body
        pygame.draw.rect(screen, self.palette["main"], rect, border_radius=14)
        pygame.draw.rect(screen, self.palette["light"], rect.inflate(-6, -6), width=2, border_radius=10)

        # Center Racing Stripe
        center_x = rect.centerx
        pygame.draw.rect(screen, self.palette["stripe"], (center_x - 3, rect.y + 6, 6, rect.height - 12), border_radius=2)

        # Windshield
        windshield = pygame.Rect(rect.x + 8, rect.bottom - 42, rect.width - 16, 20)
        pygame.draw.rect(screen, (20, 25, 30), windshield, border_radius=5)
        pygame.draw.line(screen, (100, 150, 180), (rect.x + 12, rect.bottom - 36), (rect.right - 18, rect.bottom - 26), 2)

        front_window = pygame.Rect(rect.x + 10, rect.y + 18, rect.width - 20, 12)
        pygame.draw.rect(screen, (20, 25, 30), front_window, border_radius=4)

        # Roof
        roof_rect = pygame.Rect(rect.x + 10, rect.y + 32, rect.width - 20, 16)
        pygame.draw.rect(screen, self.palette["dark"], roof_rect, border_radius=4)

        # Rear Spoiler
        spoiler_rect = pygame.Rect(rect.x + 4, rect.y + 2, rect.width - 8, 5)
        pygame.draw.rect(screen, (25, 25, 30), spoiler_rect, border_radius=2)

        # Lights
        pygame.draw.circle(screen, (255, 220, 120), (rect.x + 10, rect.bottom - 6), 4)
        pygame.draw.circle(screen, (255, 220, 120), (rect.right - 10, rect.bottom - 6), 4)

        pygame.draw.rect(screen, (240, 40, 40), (rect.x + 8, rect.y + 4, 8, 3), border_radius=2)
        pygame.draw.rect(screen, (240, 40, 40), (rect.right - 16, rect.y + 4, 8, 3), border_radius=2)

    def is_off_screen(self):
        return self.y - self.height / 2 > SCREEN_HEIGHT + 60


class Coin:
    def __init__(self, x, y, speed):
        self.radius = 13
        self.x = x
        self.y = y
        self.speed = speed
        self.anim_offset = random.uniform(0, 6.28)

    def update(self, dt):
        self.y += self.speed * dt

    def get_rect(self):
        return pygame.Rect(self.x - self.radius, self.y - self.radius,
                            self.radius * 2, self.radius * 2)

    def draw(self, screen, game_time):
        # 3D Spinning Coin Simulation
        spin_scale = abs(math.cos(game_time * 5.0 + self.anim_offset))
        current_w = max(4, int(self.radius * 2 * spin_scale))
        current_h = self.radius * 2

        # Outer Glow Surface
        glow_s = pygame.Surface((self.radius * 4, self.radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(glow_s, (255, 220, 0, 40), (self.radius * 2, self.radius * 2), self.radius + 5)
        screen.blit(glow_s, (self.x - self.radius * 2, self.y - self.radius * 2))

        # Coin Oval (Simulating 3D Rotation)
        coin_rect = pygame.Rect(self.x - current_w // 2, self.y - current_h // 2, current_w, current_h)
        pygame.draw.ellipse(screen, COLOR_COIN_BORDER, coin_rect)

        inner_rect = coin_rect.inflate(-4, -4)
        if inner_rect.width > 2 and inner_rect.height > 2:
            pygame.draw.ellipse(screen, COLOR_COIN, inner_rect)

        # Center Shiny Star / Embossment
        if current_w > 12:
            shine_rect = inner_rect.inflate(-6, -6)
            if shine_rect.width > 2 and shine_rect.height > 2:
                pygame.draw.ellipse(screen, COLOR_COIN_INNER, shine_rect)
                pygame.draw.line(screen, COLOR_COIN_BORDER, (self.x, self.y - 5), (self.x, self.y + 5), 2)

    def is_off_screen(self):
        return self.y - self.radius > SCREEN_HEIGHT + 40


# ------------------------------------------------------------------
# STEP 4: Road Graphics & Scrolling Background
# ------------------------------------------------------------------
class RoadEnvironment:
    def __init__(self):
        self.offset = 0.0
        self.curb_height = 40
        self.dash_gap = 50
        self.dash_height = 28

    def update(self, dt, speed):
        self.offset += speed * dt
        if self.offset > 2000:
            self.offset %= 200

    def draw(self, screen):
        # 1. Roadside Grass
        screen.fill(COLOR_GRASS_1)

        # 2. Road Asphalt Surface
        road_width = ROAD_RIGHT - ROAD_LEFT
        road_rect = pygame.Rect(ROAD_LEFT, 0, road_width, SCREEN_HEIGHT)
        pygame.draw.rect(screen, COLOR_ROAD, road_rect)

        # 3. Shoulder Borders
        pygame.draw.rect(screen, COLOR_ROAD_SHOULDER, (ROAD_LEFT, 0, 10, SCREEN_HEIGHT))
        pygame.draw.rect(screen, COLOR_ROAD_SHOULDER, (ROAD_RIGHT - 10, 0, 10, SCREEN_HEIGHT))

        # 4. Animated Red & White Curbs (Rumble Strips)
        curb_y = -(self.offset % self.curb_height)
        curb_idx = int(self.offset // self.curb_height)
        while curb_y < SCREEN_HEIGHT:
            col = COLOR_CURB_RED if (curb_idx % 2 == 0) else COLOR_CURB_WHITE
            pygame.draw.rect(screen, col, (ROAD_LEFT - 10, curb_y, 10, self.curb_height))
            pygame.draw.rect(screen, col, (ROAD_RIGHT, curb_y, 10, self.curb_height))
            curb_y += self.curb_height
            curb_idx += 1

        # 5. Lane Dividers (Multi-lane dashed road: 3 lanes)
        lane_w = road_width / 3.0
        lane_1_x = ROAD_LEFT + lane_w
        lane_2_x = ROAD_LEFT + lane_w * 2

        line_y = -(self.offset % self.dash_gap)
        while line_y < SCREEN_HEIGHT:
            pygame.draw.rect(screen, COLOR_ROAD_LINE, (lane_1_x - 2, line_y, 4, self.dash_height), border_radius=2)
            pygame.draw.rect(screen, COLOR_ROAD_LINE, (lane_2_x - 2, line_y, 4, self.dash_height), border_radius=2)
            line_y += self.dash_gap


# ------------------------------------------------------------------
# STEP 5: Main Game class (poora game yahan chalta hai)
# ------------------------------------------------------------------
class CarRacingGame:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("MPU6050 Tilt Car Racing")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        self.font_large = pygame.font.SysFont("arial", 44, bold=True)
        self.font_medium = pygame.font.SysFont("arial", 22, bold=True)
        self.font_small = pygame.font.SysFont("arial", 16)
        self.font_tiny = pygame.font.SysFont("arial", 13)

        self.sound_mgr = SoundManager()
        self.reset()

    def reset(self):
        self.player = PlayerCar()
        self.enemies = []
        self.coins = []
        self.particles = []
        self.floating_texts = []
        self.road_env = RoadEnvironment()

        self.score = 0.0
        self.coins_collected = 0
        self.level = 1
        self.level_up_timer = 0.0

        self.enemy_speed = 270.0        # pixels per second
        self.spawn_timer = 0.0
        self.spawn_interval = 1.15       # seconds
        self.coin_spawn_timer = 0.0
        self.coin_spawn_interval = 1.1   # More frequent coin spawning
        self.exhaust_timer = 0.0

        self.game_over = False
        self.elapsed = 0.0
        self.sound_mgr.start_engine()

    def spawn_enemy_if_needed(self, dt):
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_interval:
            self.spawn_timer = 0.0
            self.enemies.append(EnemyCar(self.enemy_speed))

    def spawn_coin_if_needed(self, dt):
        self.coin_spawn_timer += dt
        if self.coin_spawn_timer >= self.coin_spawn_interval:
            self.coin_spawn_timer = 0.0
            lane_w = (ROAD_RIGHT - ROAD_LEFT) / 3.0
            chosen_lane = random.choice([0, 1, 2])
            coin_x = ROAD_LEFT + lane_w * (chosen_lane + 0.5)

            pattern = random.choice(["single", "single", "trail_2", "trail_3"])
            if pattern == "single":
                self.coins.append(Coin(coin_x, -20, self.enemy_speed * 0.88))
            elif pattern == "trail_2":
                self.coins.append(Coin(coin_x, -20, self.enemy_speed * 0.88))
                self.coins.append(Coin(coin_x, -65, self.enemy_speed * 0.88))
            elif pattern == "trail_3":
                self.coins.append(Coin(coin_x, -20, self.enemy_speed * 0.88))
                self.coins.append(Coin(coin_x, -65, self.enemy_speed * 0.88))
                self.coins.append(Coin(coin_x, -110, self.enemy_speed * 0.88))

    def update(self, dt, keyboard_angle_override):
        if self.game_over:
            return

        self.elapsed += dt

        # ---------- Level Upgradation System (Distance Milestone Curve) ----------
        # Score 50 -> Lvl 2, 100 -> Lvl 3, 150 -> Lvl 4, 250 -> Lvl 5, 400 -> Lvl 6, etc.
        new_level = get_level_for_score(self.score)
        if new_level > self.level:
            self.level = new_level
            self.level_up_timer = 2.0
            self.sound_mgr.play_levelup()
            # Level-up visual celebration particles
            for _ in range(35):
                vx = random.uniform(-120, 120)
                vy = random.uniform(-140, 80)
                self.particles.append(Particle(SCREEN_WIDTH / 2, 230, vx, vy, COLOR_LEVEL, random.uniform(3, 6), 1.2))

        if self.level_up_timer > 0:
            self.level_up_timer -= dt

        # ---------- Tilt angle lo (UDP se, ya keyboard fallback se) ----------
        angle, connected = tilt_data.get()
        if not connected:
            angle = keyboard_angle_override

        self.player.update(dt, angle)

        # Car Exhaust / Smoke Particles
        self.exhaust_timer += dt
        if self.exhaust_timer >= 0.05:
            self.exhaust_timer = 0.0
            p_rect = self.player.get_rect()
            self.particles.append(Particle(p_rect.x + 9, p_rect.bottom + 2, random.uniform(-6, 6), random.uniform(50, 90), (180, 190, 200), random.uniform(2, 4), 0.35))
            self.particles.append(Particle(p_rect.right - 9, p_rect.bottom + 2, random.uniform(-6, 6), random.uniform(50, 90), (180, 190, 200), random.uniform(2, 4), 0.35))

        # ---------- Difficulty level ke hisaab se badhao ----------
        self.enemy_speed = 270.0 + (self.level - 1) * 28.0 + self.elapsed * 2.5
        self.spawn_interval = max(0.45, 1.15 - (self.level - 1) * 0.08 - self.elapsed * 0.003)

        self.road_env.update(dt, self.enemy_speed)
        self.spawn_enemy_if_needed(dt)
        self.spawn_coin_if_needed(dt)

        # ---------- Enemies update karo ----------
        for enemy in self.enemies:
            enemy.speed = self.enemy_speed
            enemy.update(dt)

        still_on_screen_enemies = []
        for enemy in self.enemies:
            if enemy.is_off_screen():
                self.score += 2  # ek car cross karne par 2 points (slower progression)
            else:
                still_on_screen_enemies.append(enemy)
        self.enemies = still_on_screen_enemies

        # ---------- Coins update karo ----------
        for coin in self.coins:
            coin.speed = self.enemy_speed * 0.88
            coin.update(dt)

        player_rect = self.player.get_rect()

        # Coin collection check & Sparkles
        still_on_screen_coins = []
        for coin in self.coins:
            if player_rect.colliderect(coin.get_rect()):
                self.coins_collected += 1
                self.score += 5  # Coin collect karne par +5 points
                self.sound_mgr.play_coin()
                # Floating +5 text popup
                self.floating_texts.append(FloatingText(coin.x, coin.y, "+5", COLOR_COIN, self.font_medium))
                # Golden Sparkle particles
                for _ in range(14):
                    vx = random.uniform(-80, 80)
                    vy = random.uniform(-90, 60)
                    self.particles.append(Particle(coin.x, coin.y, vx, vy, COLOR_COIN, random.uniform(2, 5), 0.5))
            elif not coin.is_off_screen():
                still_on_screen_coins.append(coin)
        self.coins = still_on_screen_coins

        # ---------- Update Visual Particles & Floating Texts ----------
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.lifetime > 0]

        for ft in self.floating_texts:
            ft.update(dt)
        self.floating_texts = [ft for ft in self.floating_texts if ft.lifetime > 0]

        # ---------- Collision check karo ----------
        for enemy in self.enemies:
            if player_rect.colliderect(enemy.get_rect()):
                self.game_over = True
                self.sound_mgr.play_crash()
                # Crash particles
                for _ in range(40):
                    vx = random.uniform(-140, 140)
                    vy = random.uniform(-140, 140)
                    self.particles.append(Particle(player_rect.centerx, player_rect.centery, vx, vy, (255, 100, 40), random.uniform(3, 7), 0.9))
                break

        # Time score (slowed down survival bonus: ~0.8 pt/sec)
        self.score += dt * 0.8

    def draw_hud(self):
        angle, connected = tilt_data.get()
        status_text = "ESP32: Connected" if connected else "ESP32: Waiting... (Keys)"
        status_color = (100, 235, 120) if connected else (255, 180, 70)

        # Top Glassmorphism HUD Bar
        hud_surface = pygame.Surface((SCREEN_WIDTH - 24, 66), pygame.SRCALPHA)
        pygame.draw.rect(hud_surface, (18, 22, 28, 210), (0, 0, SCREEN_WIDTH - 24, 66), border_radius=12)
        pygame.draw.rect(hud_surface, (60, 70, 85, 160), (0, 0, SCREEN_WIDTH - 24, 66), width=1, border_radius=12)
        self.screen.blit(hud_surface, (12, 10))

        # Score (Top Left)
        score_label = self.font_tiny.render("SCORE", True, COLOR_TEXT_DIM)
        score_val = self.font_medium.render(f"{int(self.score)}", True, COLOR_TEXT)
        self.screen.blit(score_label, (24, 16))
        self.screen.blit(score_val, (24, 34))

        # Coins Counter (Top Center)
        coin_icon_rect = pygame.Rect(180, 28, 18, 18)
        pygame.draw.circle(self.screen, COLOR_COIN_BORDER, coin_icon_rect.center, 9)
        pygame.draw.circle(self.screen, COLOR_COIN, coin_icon_rect.center, 7)
        pygame.draw.circle(self.screen, COLOR_COIN_INNER, (coin_icon_rect.centerx - 2, coin_icon_rect.centery - 2), 3)

        coins_label = self.font_tiny.render("COINS", True, COLOR_TEXT_DIM)
        coins_val = self.font_medium.render(f"{self.coins_collected}", True, COLOR_COIN)
        self.screen.blit(coins_label, (206, 16))
        self.screen.blit(coins_val, (206, 34))

        # Level Badge (Top Right)
        level_label = self.font_tiny.render("LEVEL", True, COLOR_TEXT_DIM)
        level_val = self.font_medium.render(f"LVL {self.level}", True, COLOR_LEVEL)
        self.screen.blit(level_label, (SCREEN_WIDTH - 95, 16))
        self.screen.blit(level_val, (SCREEN_WIDTH - 95, 34))

        # Bottom Connection & Tilt Bar
        bottom_hud = pygame.Surface((SCREEN_WIDTH - 24, 32), pygame.SRCALPHA)
        pygame.draw.rect(bottom_hud, (18, 22, 28, 190), (0, 0, SCREEN_WIDTH - 24, 32), border_radius=8)
        self.screen.blit(bottom_hud, (12, SCREEN_HEIGHT - 42))

        # Status indicator dot
        pygame.draw.circle(self.screen, status_color, (26, SCREEN_HEIGHT - 26), 5)
        status_surf = self.font_tiny.render(status_text, True, status_color)
        self.screen.blit(status_surf, (36, SCREEN_HEIGHT - 33))

        # Tilt Angle Gauge
        tilt_text = f"Tilt: {angle:+.1f}°"
        tilt_surf = self.font_tiny.render(tilt_text, True, COLOR_TEXT)
        self.screen.blit(tilt_surf, (SCREEN_WIDTH - 120, SCREEN_HEIGHT - 33))

        # Mini Tilt Bar Indicator
        gauge_center_x = SCREEN_WIDTH - 165
        gauge_y = SCREEN_HEIGHT - 26
        pygame.draw.line(self.screen, (70, 80, 95), (gauge_center_x - 25, gauge_y), (gauge_center_x + 25, gauge_y), 3)
        pygame.draw.circle(self.screen, (150, 160, 175), (gauge_center_x, gauge_y), 3)
        indicator_x = gauge_center_x + int((angle / MAX_TILT_ANGLE) * 25)
        indicator_x = max(gauge_center_x - 25, min(gauge_center_x + 25, indicator_x))
        pygame.draw.circle(self.screen, COLOR_LEVEL, (indicator_x, gauge_y), 4)

        # Level Up Animated Banner
        if self.level_up_timer > 0:
            scale = 1.0 + 0.08 * math.sin(self.elapsed * 12.0)
            banner_surf = self.font_large.render(f"★ LEVEL {self.level} ★", True, COLOR_LEVEL)
            banner_rect = banner_surf.get_rect(center=(SCREEN_WIDTH / 2, 210))

            bg_rect = banner_rect.inflate(40, 18)
            s = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            s.fill((12, 16, 24, 225))
            self.screen.blit(s, (bg_rect.x, bg_rect.y))
            pygame.draw.rect(self.screen, COLOR_LEVEL, bg_rect, width=2, border_radius=10)
            self.screen.blit(banner_surf, banner_rect)

    def draw_game_over(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 12, 16, 200))
        self.screen.blit(overlay, (0, 0))

        # Glass Panel Card
        card_w, card_h = 360, 260
        card_rect = pygame.Rect((SCREEN_WIDTH - card_w) / 2, (SCREEN_HEIGHT - card_h) / 2 - 20, card_w, card_h)
        card_s = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        pygame.draw.rect(card_s, (22, 26, 34, 245), (0, 0, card_w, card_h), border_radius=16)
        pygame.draw.rect(card_s, (255, 75, 75, 160), (0, 0, card_w, card_h), width=2, border_radius=16)
        self.screen.blit(card_s, card_rect.topleft)

        title = self.font_large.render("GAME OVER", True, (255, 75, 75))
        title_rect = title.get_rect(center=(SCREEN_WIDTH / 2, card_rect.y + 40))
        self.screen.blit(title, title_rect)

        score_surf = self.font_medium.render(f"Final Score: {int(self.score)}", True, COLOR_TEXT)
        score_rect = score_surf.get_rect(center=(SCREEN_WIDTH / 2, card_rect.y + 95))
        self.screen.blit(score_surf, score_rect)

        stats_surf = self.font_small.render(f"Level Reached: {self.level}   |   Coins: {self.coins_collected}", True, COLOR_COIN)
        stats_rect = stats_surf.get_rect(center=(SCREEN_WIDTH / 2, card_rect.y + 135))
        self.screen.blit(stats_surf, stats_rect)

        # Pulse restart hint
        hint_alpha = int(180 + 75 * math.sin(pygame.time.get_ticks() / 150.0))
        hint_surf = self.font_small.render("Press 'R' to Restart", True, (240, 240, 250))
        hint_surf.set_alpha(hint_alpha)
        hint_rect = hint_surf.get_rect(center=(SCREEN_WIDTH / 2, card_rect.y + 195))
        self.screen.blit(hint_surf, hint_rect)

    def draw(self):
        # 1. Environment & Road
        self.road_env.draw(self.screen)

        # 2. Collectible Coins
        for coin in self.coins:
            coin.draw(self.screen, self.elapsed)

        # 3. Obstacle Cars
        for enemy in self.enemies:
            enemy.draw(self.screen)

        # 4. Particles (Exhaust, Sparkles, Explosions)
        for p in self.particles:
            p.draw(self.screen)

        # 5. Player Car
        self.player.draw(self.screen)

        # 6. Floating Score Popups
        for ft in self.floating_texts:
            ft.draw(self.screen)

        # 7. Modern HUD
        self.draw_hud()

        # 8. Game Over Screen (if active)
        if self.game_over:
            self.draw_game_over()

        pygame.display.flip()

    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0  # dt = seconds since last frame

            keyboard_angle_override = 0.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.sound_mgr.stop_engine()
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.sound_mgr.stop_engine()
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
