# MINI C64 BASIC V2 — single-window Pygame edition (fixed)
# --------------------------------------------------------
# This file merges Stefano's original with two fixes:
#  1) Correct NEXT handling for nested/unnamed NEXT (no more ?NEXT WITHOUT FOR).
#  2) RUN auto-commits EDIT mode.
#
# Notes:
#  - Minimal, toy interpreter focused on LOGO-like turtle commands and tiny BASIC.
#  - Left pane: console + editor. Right pane: graphics.
#  - Keys: ESC toggles edit/console; Up/Down browse history; Ctrl+Enter/F5 quick RUN in edit.
#
# If anything goes weird on paste, ping me and I will trim/fold as needed.

import os
BACKEND = os.environ.get('MINI64_BACKEND', 'pygame').lower()
if BACKEND == 'fb':
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import sys
import math
import re
import time
import traceback
import faulthandler
import threading
import mmap
import select
try:
    import evdev
    from evdev import ecodes
except Exception:
    evdev = None
    ecodes = None
from collections import deque

# ------------------------------
# Config / Palette
# ------------------------------
def _read_sysfs_int(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except OSError:
        return None

def _read_sysfs_pair(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if ',' in raw:
            a, b = raw.split(',', 1)
            return int(a), int(b)
    except OSError:
        return None
    return None

def _get_fb_config():
    fbdev = os.environ.get('MINI64_FBDEV', '/dev/fb0')
    size = _read_sysfs_pair('/sys/class/graphics/fb0/virtual_size')
    bpp = _read_sysfs_int('/sys/class/graphics/fb0/bits_per_pixel')
    stride = _read_sysfs_int('/sys/class/graphics/fb0/stride')
    if stride is None:
        stride = _read_sysfs_int('/sys/class/graphics/fb0/line_length')
    if size and bpp:
        width, height = size
        if stride is None:
            stride = width * (bpp // 8)
        return fbdev, width, height, bpp, stride
    return fbdev, None, None, None, None

# Auto-detect screen resolution and set proportional dimensions
pygame.init()  # Need to init pygame first to get display info
FB_DEV, FB_W, FB_H, FB_BPP, FB_STRIDE = _get_fb_config()
if BACKEND == 'fb' and FB_W and FB_H:
    SCREEN_W, SCREEN_H = FB_W, FB_H
else:
    display_info = pygame.display.get_desktop_sizes()[0]
    SCREEN_W, SCREEN_H = display_info

# Use 90% of screen size with reasonable minimums
W = max(800, int(SCREEN_W * 0.9))
H = max(600, int(SCREEN_H * 0.9))

# Console pane takes 33% of width
LEFT_W = int(W * 0.33)
# Lower FPS to reduce CPU/GPU load on low-power devices (e.g., Pi Zero 2 W)
FPS = 8
LOG_HEARTBEAT_SEC = 1.0
LOG_STATEMENT_EVERY = 1
LOG_SNAPSHOT_SEC = 10.0
LOG_SNAPSHOT_COUNT = 20
LOG_WATCHDOG_SEC = 20.0
LOG_SLOW_FRAME_SEC = 0.5
# EVENT_STALL_EXIT_SEC = 30.0
IDLE_SLEEP_SEC = 0.02
LOOP_STALL_SEC = 5.0
EVENT_WAIT_MS = 100

C64 = {
    'bg': (24, 24, 70),       # deep blue
    'panel': (14, 18, 56),
    'text': (230, 230, 255),
    'muted': (170, 170, 210),
    'caret': (255, 255, 255),
    'cursor_row': (60, 60, 100),
    'grid': (10, 10, 30)
}

# Turtle pen colors (subset, C64-ish)
PENS = {
    '0': (0, 0, 0),
    '1': (255, 255, 255),
    '2': (136, 0, 0),
    '3': (170, 255, 238),
    '4': (204, 68, 204),
    '5': (0, 204, 85),
    '6': (0, 0, 170),
    '7': (238, 238, 119),
    '8': (221, 136, 85),
    '9': (102, 68, 0),
    '10': (255, 119, 119),
    '11': (51, 51, 51),
    '12': (119, 119, 119),
    '13': (170, 255, 102),
    '14': (0, 136, 255),
    '15': (187, 187, 187),

    'BLACK': (0, 0, 0),
    'WHITE': (255, 255, 255),
    'RED': (200, 64, 64),
    'GREEN': (64, 200, 120),
    'BLUE': (64, 64, 220),
    'YELLOW': (240, 220, 92),
    'CYAN': (100, 220, 220),
    'MAGENTA': (220, 100, 220)
}

# ------------------------------
# Utility
# ------------------------------
def _select_log_path():
    env_path = os.environ.get('MINI64_LOG_PATH')
    if env_path:
        return env_path
    path = 'mini64.log'
    try:
        with open(path, 'a', encoding='utf-8'):
            return path
    except OSError:
        return None

class DebugLog:
    def __init__(self):
        self.path = _select_log_path()
        self.file = None
        self.recent_events = deque(maxlen=LOG_SNAPSHOT_COUNT)
        self.boot_id = _read_boot_id()
        if self.path:
            self.file = open(self.path, 'w', encoding='utf-8', buffering=1)
            self.write('=== MINI64 START ===')
            if self.boot_id:
                self.write(f'BOOT_ID {self.boot_id}')

    def write(self, msg):
        if not self.file:
            return
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        uptime = _read_uptime()
        if uptime is None:
            self.file.write(f'{ts} | {msg}\n')
        else:
            self.file.write(f'{ts} | up={uptime:.2f}s | {msg}\n')
        self.file.flush()

    def event(self, msg):
        self.recent_events.append(msg)
        self.write(msg)

    def close(self):
        if self.file:
            try:
                faulthandler.cancel_dump_traceback_later()
            except Exception:
                pass
            self.write('=== MINI64 STOP ===')
            self.file.close()
            self.file = None

def _read_cpu_sample():
    try:
        with open('/proc/stat', 'r', encoding='utf-8') as f:
            parts = f.readline().split()
        if not parts or parts[0] != 'cpu':
            return None
        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        return (idle, total)
    except OSError:
        return None

def _read_meminfo():
    try:
        info = {}
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(':')] = int(parts[1])
        return info
    except OSError:
        return {}

def _read_boot_id():
    try:
        with open('/proc/sys/kernel/random/boot_id', 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None

def _read_uptime():
    try:
        with open('/proc/uptime', 'r', encoding='utf-8') as f:
            return float(f.readline().split()[0])
    except OSError:
        return None

def _read_cpu_temp_c():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r', encoding='utf-8') as f:
            return float(f.read().strip()) / 1000.0
    except OSError:
        return None

def _read_cpu_freq_mhz():
    try:
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r', encoding='utf-8') as f:
            return float(f.read().strip()) / 1000.0
    except OSError:
        return None

def _read_throttled():
    path = '/sys/devices/platform/soc/soc:firmware/get_throttled'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if raw.startswith('0x'):
            return int(raw, 16)
        return int(raw)
    except OSError:
        return None

class Framebuffer:
    def __init__(self, dev, width, height, bpp, stride, logger=None):
        self.dev = dev
        self.width = width
        self.height = height
        self.bpp = bpp
        self.stride = stride
        self.logger = logger
        if self.bpp != 32:
            raise RuntimeError(f'Unsupported framebuffer bpp: {self.bpp}')
        self.fd = open(self.dev, 'r+b', buffering=0)
        self.mmap = mmap.mmap(self.fd.fileno(), self.stride * self.height, mmap.MAP_SHARED, mmap.PROT_WRITE)

    def blit_surface(self, surface):
        # Convert to RGBX (32bpp) and write line-by-line
        raw = pygame.image.tostring(surface, 'RGBX')
        row_bytes = self.width * 4
        for y in range(self.height):
            start = y * row_bytes
            end = start + row_bytes
            dst = y * self.stride
            self.mmap[dst:dst + row_bytes] = raw[start:end]

    def close(self):
        try:
            self.mmap.close()
        except Exception:
            pass
        try:
            self.fd.close()
        except Exception:
            pass

class KeyEvent:
    def __init__(self, key, unicode='', ctrl=False):
        self.type = pygame.KEYDOWN
        self.key = key
        self.unicode = unicode
        self.ctrl = ctrl

class EvdevInput:
    def __init__(self, logger=None):
        self.logger = logger
        if evdev is None:
            raise RuntimeError('python-evdev not available')
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        keyboards = []
        for dev in devices:
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.KEY_A in caps and ecodes.KEY_Z in caps:
                keyboards.append(dev)
        if not keyboards:
            raise RuntimeError('No keyboard devices found')
        self.device = keyboards[0]
        self.device.grab()
        self.shift = False
        self.ctrl = False

    def _char_from_code(self, code):
        if ecodes is None:
            return ''
        if ecodes.KEY_A <= code <= ecodes.KEY_Z:
            ch = chr(ord('a') + (code - ecodes.KEY_A))
            return ch.upper() if self.shift else ch
        if ecodes.KEY_1 <= code <= ecodes.KEY_9:
            ch = str(code - ecodes.KEY_1 + 1)
            if self.shift:
                return {'1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '6': '^', '7': '&', '8': '*', '9': '('}.get(ch, ch)
            return ch
        if code == ecodes.KEY_0:
            return ')' if self.shift else '0'
        mapping = {
            ecodes.KEY_SPACE: ' ',
            ecodes.KEY_MINUS: '_' if self.shift else '-',
            ecodes.KEY_EQUAL: '+' if self.shift else '=',
            ecodes.KEY_LEFTBRACE: '{' if self.shift else '[',
            ecodes.KEY_RIGHTBRACE: '}' if self.shift else ']',
            ecodes.KEY_BACKSLASH: '|' if self.shift else '\\',
            ecodes.KEY_SEMICOLON: ':' if self.shift else ';',
            ecodes.KEY_APOSTROPHE: '"' if self.shift else '\'',
            ecodes.KEY_COMMA: '<' if self.shift else ',',
            ecodes.KEY_DOT: '>' if self.shift else '.',
            ecodes.KEY_SLASH: '?' if self.shift else '/',
            ecodes.KEY_GRAVE: '~' if self.shift else '`',
        }
        return mapping.get(code, '')

    def poll(self, timeout_ms):
        rlist, _, _ = select.select([self.device.fd], [], [], timeout_ms / 1000.0)
        events = []
        if not rlist:
            return events
        for ev in self.device.read():
            if ev.type != ecodes.EV_KEY:
                continue
            key_event = evdev.categorize(ev)
            if key_event.keystate == key_event.key_down or key_event.keystate == key_event.key_hold:
                code = key_event.scancode
                if code in (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT):
                    self.shift = True
                    continue
                if code in (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL):
                    self.ctrl = True
                    continue
                if code == ecodes.KEY_ENTER:
                    events.append(KeyEvent(pygame.K_RETURN, '\n', self.ctrl))
                    continue
                if code == ecodes.KEY_BACKSPACE:
                    events.append(KeyEvent(pygame.K_BACKSPACE, '', self.ctrl))
                    continue
                if code == ecodes.KEY_DELETE:
                    events.append(KeyEvent(pygame.K_DELETE, '', self.ctrl))
                    continue
                if code == ecodes.KEY_ESC:
                    events.append(KeyEvent(pygame.K_ESCAPE, '', self.ctrl))
                    continue
                if code == ecodes.KEY_UP:
                    events.append(KeyEvent(pygame.K_UP, '', self.ctrl))
                    continue
                if code == ecodes.KEY_DOWN:
                    events.append(KeyEvent(pygame.K_DOWN, '', self.ctrl))
                    continue
                if code == ecodes.KEY_LEFT:
                    events.append(KeyEvent(pygame.K_LEFT, '', self.ctrl))
                    continue
                if code == ecodes.KEY_RIGHT:
                    events.append(KeyEvent(pygame.K_RIGHT, '', self.ctrl))
                    continue
                if code == ecodes.KEY_F5:
                    events.append(KeyEvent(pygame.K_F5, '', self.ctrl))
                    continue
                ch = self._char_from_code(code)
                if ch:
                    events.append(KeyEvent(0, ch, self.ctrl))
            elif key_event.keystate == key_event.key_up:
                code = key_event.scancode
                if code in (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT):
                    self.shift = False
                if code in (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL):
                    self.ctrl = False
        return events

    def close(self):
        try:
            self.device.ungrab()
        except Exception:
            pass

def clamp(v, a, b):
    return max(a, min(b, v))

# ------------------------------
# Console / Editor Pane
# ------------------------------
class Console:
    def __init__(self, rect, font):
        self.rect = pygame.Rect(rect)
        self.font = font
        self.lines = deque(maxlen=2000)
        self.input = ''
        self.history = []
        self.hidx = 0
        self.blink = 0
        self.prog_mode = False
        self.cursor_blink = 0

    def print(self, text=''):
        for ln in str(text).split('\n'):
            self.lines.append(ln)

    def set_prompt(self, p):
        self.prompt = p

    def enter_prog_mode(self):
        self.prog_mode = True

    def exit_prog_mode(self):
        self.prog_mode = False

    def draw(self, surf, app):
        pygame.draw.rect(surf, C64['panel'], self.rect)
        pad = 8
        x = self.rect.x + pad
        y = self.rect.y + pad
        line_h = self.font.get_height() + 2
        max_lines = (self.rect.height - 2*pad) // line_h

        # Check if shutting down
        if app and app.machine.shutting_down:
            # Center the countdown message
            msg = f"TURNING OFF IN {app.machine.shutdown_counter}"
            text_surf = self.font.render(msg, True, C64['text'])
            text_x = self.rect.x + (self.rect.width - text_surf.get_width()) // 2
            text_y = self.rect.y + (self.rect.height - text_surf.get_height()) // 2
            surf.blit(text_surf, (text_x, text_y))
            return

        if self.prog_mode and app:  # show program buffer with cursor highlight
            base = max(0, len(app.prog_lines) - (max_lines - 1))
            view = app.prog_lines[base:]
            rel = app.prog_cursor_line - base

            # highlight row
            for i, ln in enumerate(view):
                yy = y + i*line_h
                if i == rel:
                    pygame.draw.rect(surf, C64['cursor_row'], (x-4, yy-1, self.rect.width-2*pad+8, line_h+2))
            # show text + caret
            for i, ln in enumerate(view):
                disp = ln
                if i == rel:
                    caret_col = clamp(app.prog_cursor_col, 0, len(ln))
                    self.cursor_blink = (self.cursor_blink + 1) % FPS
                    caret_char = '_' if self.cursor_blink < FPS//2 else ' '
                    disp = ln[:caret_col] + caret_char + ln[caret_col:]
                surf.blit(self.font.render(disp, True, C64['text']), (x, y + i*line_h))
            return

        # console mode
        # gather tail
        buf = list(self.lines)[-max_lines+2:]
        for i, ln in enumerate(buf):
            surf.blit(self.font.render(ln, True, C64['text']), (x, y + i*line_h))
        y += (len(buf)) * line_h

        # input line
        self.blink = (self.blink + 1) % FPS
        caret = '_' if (self.blink // (FPS//2)) % 2 == 0 else ' '
        disp = f"> {self.input}{caret}"
        surf.blit(self.font.render(disp, True, C64['text']), (x, y))

    def handle_key(self, ev, app):
        if self.prog_mode:
            return self._handle_prog_key(ev, app)
        else:
            return self._handle_console_key(ev, app)

    def _handle_console_key(self, ev, app):
        if ev.key == pygame.K_BACKSPACE:
            self.input = self.input[:-1]
        elif ev.key == pygame.K_RETURN:
            cmd = self.input.strip()
            self.lines.append(f"> {cmd}")
            if cmd:
                self.history.append(cmd)
            self.hidx = len(self.history)
            self.input = ''
            app.process_line(cmd)
        elif ev.key == pygame.K_UP:
            if self.hidx > 0:
                self.hidx -= 1
                self.input = self.history[self.hidx]
        elif ev.key == pygame.K_DOWN:
            if self.hidx < len(self.history)-1:
                self.hidx += 1
                self.input = self.history[self.hidx]
            else:
                self.hidx = len(self.history)
                self.input = ''
        else:
            if ev.unicode:
                self.input += ev.unicode

    # PATCHED SNIPPET: Auto line numbering on Enter in EDIT MODE
    # This snippet shows only the changed function _handle_prog_key.
    # Paste it over your existing _handle_prog_key in the same file.

    def _handle_prog_key(self, ev, app):
        if ev.key == pygame.K_ESCAPE:
            app.exit_programming_mode()
            return
        # shortcuts first: Ctrl+Enter or F5 -> commit & run
        ctrl_pressed = getattr(ev, 'ctrl', False)
        if (ev.key == pygame.K_RETURN and (ctrl_pressed or (pygame.key.get_mods() & pygame.KMOD_CTRL))) or ev.key == pygame.K_F5:
            app.exit_programming_mode()
            app.run_program()
            return

        if ev.key == pygame.K_RETURN:
            # --- AUTO LINE NUMBERING ---
            line = app.prog_lines[app.prog_cursor_line]
            col = clamp(app.prog_cursor_col, 0, len(line))
            left, right = line[:col], line[col:]

            # Commit the left part to current line
            app.prog_lines[app.prog_cursor_line] = left

            # If current line starts with a number, add next number on the new line
            m = re.match(r'^(\d+)\s*(.*)$', left)
            if m:
                cur_num = int(m.group(1))
                next_num = cur_num + 10  # default BASIC-style step
                # produce the next line with auto number; carry over any right-side text
                new_line = f"{next_num} " + right.lstrip()
            else:
                # no numeric prefix -> behave like a normal text editor
                new_line = right

            # Insert and move cursor
            app.prog_lines.insert(app.prog_cursor_line + 1, new_line)
            app.prog_cursor_line += 1
            app.prog_cursor_col = len(new_line)
            return

        if ev.key == pygame.K_BACKSPACE:
            line = app.prog_lines[app.prog_cursor_line]
            if app.prog_cursor_col > 0:
                app.prog_lines[app.prog_cursor_line] = line[:app.prog_cursor_col-1] + line[app.prog_cursor_col:]
                app.prog_cursor_col -= 1
            else:
                if app.prog_cursor_line > 0:
                    prev = app.prog_lines[app.prog_cursor_line-1]
                    app.prog_cursor_col = len(prev)
                    app.prog_lines[app.prog_cursor_line-1] = prev + line
                    del app.prog_lines[app.prog_cursor_line]
                    app.prog_cursor_line -= 1
            return

        if ev.key == pygame.K_DELETE:
            line = app.prog_lines[app.prog_cursor_line]
            if app.prog_cursor_col < len(line):
                app.prog_lines[app.prog_cursor_line] = line[:app.prog_cursor_col] + line[app.prog_cursor_col+1:]
            else:
                if app.prog_cursor_line < len(app.prog_lines)-1:
                    app.prog_lines[app.prog_cursor_line] = line + app.prog_lines[app.prog_cursor_line+1]
                    del app.prog_lines[app.prog_cursor_line+1]
            return

        if ev.key == pygame.K_LEFT:
            app.prog_cursor_col = max(0, app.prog_cursor_col-1)
            return
        if ev.key == pygame.K_RIGHT:
            app.prog_cursor_col = min(len(app.prog_lines[app.prog_cursor_line]), app.prog_cursor_col+1)
            return
        if ev.key == pygame.K_UP:
            if app.prog_cursor_line > 0:
                app.prog_cursor_line -= 1
                app.prog_cursor_col = min(app.prog_cursor_col, len(app.prog_lines[app.prog_cursor_line]))
            return
        if ev.key == pygame.K_DOWN:
            if app.prog_cursor_line < len(app.prog_lines)-1:
                app.prog_cursor_line += 1
                app.prog_cursor_col = min(app.prog_cursor_col, len(app.prog_lines[app.prog_cursor_line]))
            return

        # insert char
        if ev.unicode:
            line = app.prog_lines[app.prog_cursor_line]
            col = clamp(app.prog_cursor_col, 0, len(line))
            app.prog_lines[app.prog_cursor_line] = line[:col] + ev.unicode + line[col:]
            app.prog_cursor_col += len(ev.unicode)


class MiniC64:
    def __init__(self, surface, console, logger=None):
        self.surf = surface
        self.console = console
        self.logger = logger
        self.reset()

    # ----------------------
    # Program/edit buffers
    # ----------------------
    def reset(self):
        self.variables = {}
        self.program = []  # list of (lineno, raw_line)
        self.labels = {}
        self.for_stack = []
        self.gfx = pygame.Surface((W - LEFT_W, H))
        self.gfx.fill((30, 30, 92))
        # turtle state
        self.x = (W - LEFT_W)//2
        self.y = H//2
        self.heading = 0
        self.pen_down = True
        self.color = PENS['1']
        self.thick = 2
        # editor buffer
        self.prog_lines = [
            '10 REM READY'
        ]
        self.prog_cursor_line = 0
        self.prog_cursor_col = 0
        self.running = False
        self.shutting_down = False
        self.shutdown_time = 0
        self.shutdown_counter = 0
        # Emergency exit tracking
        self.emergency_exit_start = 0
        self.emergency_exit_active = False
        self.last_pc = None
        self.last_line = None
        self.last_cmd = None
        self.last_exec_time = None
        self.statement_count = 0

    def enter_programming_mode(self):
        self.console.enter_prog_mode()
        # fill buffer with current program text
        if self.program:
            txt = []
            for ln, raw in self.program:
                txt.append(f"{ln} {raw}")
            self.prog_lines = txt
        else:
            self.prog_lines = ['10 ']
        self.prog_cursor_line = len(self.prog_lines)-1
        self.prog_cursor_col = len(self.prog_lines[-1])

    def exit_programming_mode(self):
        self.console.exit_prog_mode()
        # parse lines into program table
        prog = []
        for raw in self.prog_lines:
            s = raw.strip()
            if not s:
                continue
            m = re.match(r'^(\d+)\s*(.*)$', s)
            if not m:
                # allow non-numbered lines: ignore in commit
                continue
            ln = int(m.group(1))
            body = m.group(2)
            prog.append((ln, body))
        prog.sort(key=lambda x: x[0])
        self.program = prog
        self.rebuild_labels()
        self.console.print('READY.')

    def rebuild_labels(self):
        self.labels = {ln: idx for idx, (ln, _) in enumerate(self.program)}

    # ----------------------
    # Lexer / executor
    # ----------------------
    def tokenize(self, s):
        # split by spaces but keep quoted strings
        toks = []
        cur = ''
        in_q = False
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '"':
                in_q = not in_q
                cur += ch
            elif not in_q and ch.isspace():
                if cur:
                    toks.append(cur)
                    cur = ''
            else:
                cur += ch
            i += 1
        if cur:
            toks.append(cur)
        return toks

    def num_or_var(self, tok):
        if tok is None:
            return 0
        t = tok.strip()
        # int / float
        try:
            if t.upper().startswith('0X'):
                return int(t, 16)
            if t.endswith('%'):
                return int(t[:-1])
            return float(t) if '.' in t else int(t)
        except Exception:
            return self.variables.get(t.upper(), 0)

    def run_program(self):
        if not self.program:
            self.console.print('READY.')
            return
        self.running = True
        rt = {
            'pc': 0
        }
        try:
            while self.running and rt['pc'] < len(self.program):
                ln, line = self.program[rt['pc']]
                self.last_pc = rt['pc']
                self.last_line = ln
                self.last_exec_time = time.time()
                toks = self.tokenize(line)
                self.last_cmd = toks[0].upper() if toks else None
                self.statement_count += 1
                if self.logger and (self.statement_count % LOG_STATEMENT_EVERY == 0):
                    self.logger.event(f'STMT pc={rt["pc"]} line={ln} cmd="{line}"')
                delta = self.exec_statement(toks, rt)
                if delta is None:
                    rt['pc'] += 1
                else:
                    rt['pc'] += delta
        except Exception:
            if self.logger:
                self.logger.write('EXCEPTION in run_program')
                self.logger.write(traceback.format_exc().strip())
            self.running = False
        self.console.print('READY.')
        self.running = False

    def exec_statement(self, toks, rt):
        if not toks:
            return None
        cmd = toks[0].upper()
        args = toks[1:]
        aliases = {
            'FORWARD': 'FD',
            'BACK': 'BK',
            'BACKWARD': 'BK',
            'RIGHT': 'RT',
            'LEFT': 'LT',
            'MOVE': 'GO',
            'GO': 'GO',
            'PENUP': 'PU',
            'PENDOWN': 'PD',
        }
        cmd = aliases.get(cmd, cmd)

        # --- BASIC keywords ---
        if cmd == 'REM':
            return None
        if cmd == 'LET':
            # LET A = 3
            m = re.match(r'^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)$', ' '.join(args))
            if not m:
                self.console.print('?SYNTAX ERROR'); self.running = False; return None
            var, expr = m.group(1).upper(), m.group(2)
            self.variables[var] = self.num_or_var(expr)
            return None
        if cmd == 'PRINT':
            if not args:
                self.console.print('')
                return None
            
            out = ' '.join(args)
            
            # Check if it's a quoted string
            if out.startswith('"'):
                # Must be properly quoted with no extra content
                if not out.endswith('"') or len(out) < 2:
                    self.console.print('?SYNTAX ERROR'); self.running = False; return None
                # Check for extra content after closing quote
                quote_count = out.count('"')
                if quote_count != 2:
                    self.console.print('?SYNTAX ERROR'); self.running = False; return None
                self.console.print(out[1:-1])
            else:
                # Must be a valid variable or number
                if len(args) > 1:
                    # Multiple arguments without quotes is invalid
                    self.console.print('?SYNTAX ERROR'); self.running = False; return None
                try:
                    result = self.num_or_var(out)
                    self.console.print(str(result))
                except:
                    self.console.print('?SYNTAX ERROR'); self.running = False; return None
            return None
        if cmd == 'GOTO':
            target = int(args[0])
            if target in self.labels:
                return self.labels[target] - rt['pc']
            self.console.print('?UNDEF LINE'); self.running = False; return None
        if cmd == 'END' and (len(args) == 0):
            self.running = False
            return None

        if cmd == 'FOR':
            # FOR I = 1 TO 10 [STEP 2]
            m = re.match(r'^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)\s+TO\s+(.+?)(?:\s+STEP\s+(.+))?$', ' '.join(args), re.IGNORECASE)
            if not m:
                self.console.print('?SYNTAX ERROR'); self.running = False; return None
            var = m.group(1).upper()
            start = self.num_or_var(m.group(2))
            end = self.num_or_var(m.group(3))
            step = self.num_or_var(m.group(4)) if m.group(4) else 1
            self.variables[var] = start
            self.for_stack.append({'var': var, 'end': end, 'step': step, 'return_index': rt['pc'] + 1})
            return None

        if cmd == 'NEXT':
            # Optional variable name after NEXT (e.g., NEXT I). If omitted, use top-of-stack.
            want = args[0].upper() if args else None

            if not self.for_stack:
                self.console.print('?NEXT WITHOUT FOR')
                self.running = False
                return None

            if want:
                # Find the named FOR loop from the inside out
                idx = -1
                for i in range(len(self.for_stack) - 1, -1, -1):
                    if self.for_stack[i]['var'] == want:
                        idx = i
                        break
                if idx == -1:
                    self.console.print('?NEXT WITHOUT FOR')
                    self.running = False
                    return None
                # Keep only up to (and including) the matched loop; discard deeper inner loops
                self.for_stack = self.for_stack[:idx + 1]

            # Use the innermost loop (either the matched one or the top of the stack)
            loop = self.for_stack[-1]
            var = loop['var']
            self.variables[var] = self.num_or_var(var) + loop['step']
            cond = (self.variables[var] <= loop['end']) if (loop['step'] >= 0) else (self.variables[var] >= loop['end'])
            if cond:
                # Jump back to the statement after the FOR
                return loop['return_index'] - rt['pc']
            # Loop finished; pop it
            self.for_stack.pop()
            return None

        # --- Graphics / turtle ---
        if cmd == 'BG':
            c = PENS.get(args[0].upper(), (30, 30, 92))
            self.gfx.fill(c)
            return None
        if cmd == 'PEN':
            self.color = PENS.get(args[0].upper(), self.color)
            return None
        if cmd == 'THICK':
            self.thick = int(float(args[0]))
            return None
        if cmd == 'PU':
            self.pen_down = False; return None
        if cmd == 'PD':
            self.pen_down = True; return None
        if cmd == 'FD':
            d = float(self.num_or_var(args[0]))
            x2 = self.x + math.cos(math.radians(self.heading)) * d
            y2 = self.y + math.sin(math.radians(self.heading)) * d
            if self.pen_down:
                pygame.draw.line(self.gfx, self.color, (self.x, self.y), (x2, y2), self.thick)
            self.x, self.y = x2, y2
            return None
        if cmd == 'BK':
            d = float(self.num_or_var(args[0]))
            return self.exec_statement(['FD', str(-d)], rt)
        if cmd == 'RT':
            a = float(self.num_or_var(args[0]))
            self.heading = (self.heading + a) % 360
            return None
        if cmd == 'LT':
            a = float(self.num_or_var(args[0]))
            self.heading = (self.heading - a) % 360
            return None
        if cmd == 'GO':
            # GO x y
            if len(args) < 2:
                self.console.print('?SYNTAX ERROR')
                self.running = False
                return None
            nx = float(self.num_or_var(args[0])); ny = float(self.num_or_var(args[1]))
            if self.pen_down:
                pygame.draw.line(self.gfx, self.color, (self.x, self.y), (nx, ny), self.thick)
            self.x, self.y = nx, ny
            return None
        if cmd == 'CIRCLE':
            r = int(float(self.num_or_var(args[0])))
            pygame.draw.circle(self.gfx, self.color, (int(self.x), int(self.y)), r, max(1, self.thick))
            return None

        # --- storage ---
        if cmd == 'SAVE':
            if not args:
                self.console.print('?MISSING FILENAME'); return None
            name = args[0].strip('"')
            with open(f"{name}.bas", 'w', encoding='utf-8') as f:
                for ln, raw in self.program:
                    f.write(f"{ln} {raw}\n")
            self.console.print(f'SAVED "{name}.bas"')
            return None
        if cmd == 'LOAD':
            if not args:
                self.console.print('?MISSING FILENAME'); return None
            name = args[0].strip('"')
            try:
                with open(f"{name}.bas", 'r', encoding='utf-8') as f:
                    self.program = []
                    for line in f:
                        m = re.match(r'^(\d+)\s*(.*)$', line.strip())
                        if m:
                            self.program.append((int(m.group(1)), m.group(2)))
                self.rebuild_labels()
                self.console.print('READY.')
            except Exception as e:
                self.console.print('?FILE NOT FOUND')
            return None

        # unknown
        self.console.print('?SYNTAX ERROR')
        self.running = False
        return None

    def draw_turtle(self, screen, offset_x):
        """Draw arrow-shaped triangle cursor showing turtle position and heading"""
        # Calculate triangle points for arrow shape
        cx, cy = self.x + offset_x, self.y
        heading_rad = math.radians(self.heading)
        
        # Front point (sharp tip) - 12 pixels forward
        front_x = cx + math.cos(heading_rad) * 12
        front_y = cy + math.sin(heading_rad) * 12
        
        # Back points (wide base) - 6 pixels back, ±8 pixels perpendicular
        back_angle1 = heading_rad + math.radians(135)  # 135° from heading
        back_angle2 = heading_rad + math.radians(225)  # 225° from heading
        back1_x = cx + math.cos(back_angle1) * 10
        back1_y = cy + math.sin(back_angle1) * 10
        back2_x = cx + math.cos(back_angle2) * 10
        back2_y = cy + math.sin(back_angle2) * 10
        
        # Draw triangle - filled if pen down, outline if pen up
        points = [(front_x, front_y), (back1_x, back1_y), (back2_x, back2_y)]
        if self.pen_down:
            pygame.draw.polygon(screen, (255, 255, 255), points)
        else:
            pygame.draw.polygon(screen, (255, 255, 255), points, 2)

    # ----------------------
    # Command line
    # ----------------------
    def process_line(self, line):
        s = line.strip()
        U = s.upper()

        if U == 'EDIT':
            self.enter_programming_mode(); return
        if U == 'LIST':
            if not self.program:
                self.console.print('(empty)')
            else:
                for ln, raw in self.program:
                    self.console.print(f"{ln} {raw}")
            return
        if U == 'RUN':
            if self.console.prog_mode:
                self.exit_programming_mode()  # commit editor buffer to program
            self.run_program(); return
        if U == 'NEW':
            self.program = []
            self.variables.clear(); self.for_stack.clear(); self.rebuild_labels()
            self.console.print('READY.'); return
        if U == 'DIR' or U == 'FILES':
            bas_files = [f for f in os.listdir('.') if f.lower().endswith('.bas')]
            if bas_files:
                for f in sorted(bas_files):
                    self.console.print(f)
            else:
                self.console.print('?NO FILES FOUND')
            return
        if U == 'CLS':
            # Clear console display and graphics, reset turtle to center
            self.console.lines.clear()
            self.gfx.fill((30, 30, 92))  # Reset to default background color
            self.x = (W - LEFT_W)//2  # Reset turtle to center
            self.y = H//2
            self.console.print('READY.')
            return
        if U == 'BYE':
            # Set shutdown countdown state
            import time
            self.shutdown_time = time.time() + 3
            self.shutdown_counter = 3
            self.shutting_down = True
            return

        # immediate command
        self.exec_statement(self.tokenize(s), {'pc': 0})

# ------------------------------
# App
# ------------------------------
class App:
    def __init__(self):
        pygame.init()
        if BACKEND == 'fb':
            if not (FB_W and FB_H and FB_BPP):
                raise RuntimeError('Framebuffer config not available')
            self.screen = pygame.Surface((W, H))
            self.fb = Framebuffer(FB_DEV, W, H, FB_BPP, FB_STRIDE)
            self.input = EvdevInput()
        else:
            self.screen = pygame.display.set_mode((W, H))
            pygame.display.set_caption('*** MINI 64 BASIC V2 ***')
        self.clock = pygame.time.Clock()
        # Scale font size based on screen resolution
        font_size = max(12, int(H * 0.025))  # ~2.5% of screen height
        self.font = pygame.font.SysFont('consolas', font_size)
        self.console = Console((0, 0, LEFT_W, H), self.font)
        self.logger = DebugLog()
        if self.logger:
            try:
                driver = pygame.display.get_driver()
            except Exception:
                driver = 'UNKNOWN'
            try:
                info = pygame.display.Info()
                video = f'{info.current_w}x{info.current_h}'
            except Exception:
                video = f'{W}x{H}'
            self.logger.write(
                f'PYGAME {pygame.ver} SDL {pygame.get_sdl_version()} DRIVER {driver} '
                f'VIDEO {video} BACKEND {BACKEND}'
            )
        if self.logger and self.logger.file:
            faulthandler.enable(file=self.logger.file, all_threads=True)
            if LOG_WATCHDOG_SEC > 0:
                faulthandler.dump_traceback_later(LOG_WATCHDOG_SEC, repeat=False, file=self.logger.file)
        self.machine = MiniC64(self.screen, self.console, self.logger)
        self.blink_event = pygame.USEREVENT + 1
        self.next_blink_time = time.time() + 0.25
        if BACKEND != 'fb':
            pygame.time.set_timer(self.blink_event, 250)
        self.needs_redraw = True
        # --- editor state owned by App ---
        self.prog_lines = ['10 ']
        self.prog_cursor_line = 0
        self.prog_cursor_col = 3
        # keep interpreter pointing to the same list
        self.machine.prog_lines = self.prog_lines
        self.last_event_time = time.time()
        self.last_heartbeat = time.time()
        self.last_snapshot = time.time()
        self.last_watchdog_arm = time.time()
        self.last_loop_time = time.time()
        self.stall_reported = False
        self.cpu_sample = _read_cpu_sample()
        self._start_stall_watchdog()

    def _cleanup(self):
        if BACKEND == 'fb':
            try:
                self.input.close()
            except Exception:
                pass
            try:
                self.fb.close()
            except Exception:
                pass

    def _start_stall_watchdog(self):
        def _watch():
            while True:
                time.sleep(1.0)
                if not self.logger or not self.logger.file:
                    continue
                age = time.time() - self.last_loop_time
                if age >= LOOP_STALL_SEC:
                    if not self.stall_reported:
                        self.stall_reported = True
                        self.logger.write(f'LOOP_STALL age={age:.2f}s')
                        try:
                            faulthandler.dump_traceback(file=self.logger.file, all_threads=True)
                        except Exception:
                            pass
                else:
                    self.stall_reported = False

        thread = threading.Thread(target=_watch, daemon=True)
        thread.start()

    def enter_programming_mode(self):
        # Build an editable buffer from the current program and switch UI
        if self.machine.program:
            self.prog_lines = [f"{ln} {raw}" for ln, raw in self.machine.program]
        else:
            self.prog_lines = ['10 ']
        self.machine.prog_lines = self.prog_lines  # share list reference
        self.prog_cursor_line = len(self.prog_lines) - 1
        self.prog_cursor_col = len(self.prog_lines[-1])
        self.console.enter_prog_mode()

    def exit_programming_mode(self):
        # Commit the App buffer into the interpreter
        self.machine.prog_lines = self.prog_lines
        self.machine.exit_programming_mode()

    def process_line(self, line: str):
        if self.logger:
            self.logger.event(f'INPUT "{line}" mode={"EDIT" if self.console.prog_mode else "CONSOLE"}')
        self.machine.process_line(line)
        return

    def run_program(self):
        if self.logger:
            self.logger.write('RUN PROGRAM')
        self.machine.run_program()

    def run(self):
        self.console.print(' *** MINI 64 BASIC V2 ***')
        self.console.print(' 38911 BASIC BYTES FREE')
        self.console.print('READY.')
        if self.logger:
            self.logger.write('APP START')
        sep_x = LEFT_W

        while True:
            loop_start = time.time()
            self.last_loop_time = loop_start
            events = []
            if BACKEND == 'fb':
                events = self.input.poll(EVENT_WAIT_MS)
                now = time.time()
                if now >= self.next_blink_time:
                    self.needs_redraw = True
                    self.next_blink_time = now + 0.25
            else:
                ev = pygame.event.wait(EVENT_WAIT_MS)
                if ev is not None:
                    events.append(ev)
                events.extend(pygame.event.get())
            
            # Handle shutdown countdown
            if self.machine.shutting_down:
                remaining = self.machine.shutdown_time - time.time()
                new_counter = max(0, int(remaining) + 1)
                if new_counter != self.machine.shutdown_counter:
                    self.machine.shutdown_counter = new_counter
                    self.needs_redraw = True
                if remaining <= 0:
                    if self.logger:
                        self.logger.write('SHUTDOWN TIMER EXIT')
                        self.logger.close()
                    self._cleanup()
                    pygame.quit()
                    sys.exit()

            # Check for emergency exit (Ctrl+Shift+Q held for 2 seconds)
            keys = pygame.key.get_pressed()
            ctrl_shift_q = keys[pygame.K_LCTRL] and keys[pygame.K_LSHIFT] and keys[pygame.K_q]
            
            if ctrl_shift_q:
                if not self.machine.emergency_exit_active:
                    self.machine.emergency_exit_start = time.time()
                    self.machine.emergency_exit_active = True
                elif time.time() - self.machine.emergency_exit_start >= 2.0:
                    # Force exit after 2 seconds
                    if self.logger:
                        self.logger.write('EMERGENCY EXIT')
                        self.logger.close()
                    self._cleanup()
                    pygame.quit()
                    sys.exit()
            else:
                self.machine.emergency_exit_active = False

            event_count = 0
            for ev in events:
                if ev.type == pygame.NOEVENT:
                    continue
                event_count += 1
                self.last_event_time = time.time()
                if ev.type == pygame.QUIT:
                    if self.logger:
                        self.logger.write('EVENT QUIT')
                        self.logger.close()
                    self._cleanup()
                    pygame.quit(); sys.exit()
                if ev.type == self.blink_event:
                    self.needs_redraw = True
                    continue
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        # toggle edit mode
                        if self.console.prog_mode:
                            if self.logger:
                                self.logger.write('TOGGLE EDIT -> CONSOLE')
                            self.exit_programming_mode()
                        else:
                            if self.logger:
                                self.logger.write('TOGGLE CONSOLE -> EDIT')
                            self.enter_programming_mode()
                        self.needs_redraw = True
                        continue
                    self.console.handle_key(ev, self)
                    self.needs_redraw = True

            if IDLE_SLEEP_SEC and event_count == 0 and not self.machine.running and not self.machine.shutting_down:
                time.sleep(IDLE_SLEEP_SEC)

            if self.machine.running:
                self.needs_redraw = True

            did_redraw = False
            draw_start = loop_start
            flip_start = loop_start
            flip_end = loop_start
            if self.needs_redraw:
                did_redraw = True
                draw_start = time.time()
                self.screen.fill(C64['bg'])

                # left pane
                self.console.draw(self.screen, self)

                # right pane border
                pygame.draw.line(self.screen, (10, 10, 10), (sep_x, 0), (sep_x, H), 3)
                # blit gfx
                self.screen.blit(self.machine.gfx, (sep_x, 0))
                # draw turtle cursor
                self.machine.draw_turtle(self.screen, sep_x)

                flip_start = time.time()
                if BACKEND == 'fb':
                    self.fb.blit_surface(self.screen)
                    flip_end = time.time()
                else:
                    pygame.display.flip()
                    flip_end = time.time()
                self.clock.tick(FPS)
                self.needs_redraw = False
            now = time.time()
            self.last_loop_time = now
            if self.logger and LOG_WATCHDOG_SEC > 0:
                try:
                    faulthandler.cancel_dump_traceback_later()
                except Exception:
                    pass
                faulthandler.dump_traceback_later(LOG_WATCHDOG_SEC, repeat=False, file=self.logger.file)
                self.last_watchdog_arm = now
            if self.logger and (now - self.last_heartbeat) >= LOG_HEARTBEAT_SEC:
                self.last_heartbeat = now
                load1 = None
                if hasattr(os, 'getloadavg'):
                    try:
                        load1 = os.getloadavg()[0]
                    except OSError:
                        load1 = None
                mem = _read_meminfo()
                mem_total = mem.get('MemTotal')
                mem_avail = mem.get('MemAvailable')
                mem_used = None
                if mem_total and mem_avail is not None:
                    mem_used = mem_total - mem_avail
                cpu_pct = None
                new_sample = _read_cpu_sample()
                if self.cpu_sample and new_sample:
                    idle_delta = new_sample[0] - self.cpu_sample[0]
                    total_delta = new_sample[1] - self.cpu_sample[1]
                    if total_delta > 0:
                        cpu_pct = 100.0 * (1.0 - (idle_delta / total_delta))
                if new_sample:
                    self.cpu_sample = new_sample
                last_evt_age = now - self.last_event_time
                cpu_temp = _read_cpu_temp_c()
                cpu_freq = _read_cpu_freq_mhz()
                throttled = _read_throttled()
                self.logger.write(
                    'HEARTBEAT mode={mode} running={running} pc={pc} line={line} cmd={cmd} '
                    'fps={fps:.1f} last_event_age={evt:.2f}s events={events} load1={load} cpu={cpu} '
                    'temp_c={temp} freq_mhz={freq} throttled={throt} mem_used_kb={mem}'.format(
                        mode='EDIT' if self.console.prog_mode else 'CONSOLE',
                        running=self.machine.running,
                        pc=self.machine.last_pc,
                        line=self.machine.last_line,
                        cmd=self.machine.last_cmd,
                        fps=self.clock.get_fps(),
                        evt=last_evt_age,
                        events=event_count,
                        load=f'{load1:.2f}' if load1 is not None else 'NA',
                        cpu=f'{cpu_pct:.1f}%' if cpu_pct is not None else 'NA',
                        temp=f'{cpu_temp:.1f}' if cpu_temp is not None else 'NA',
                        freq=f'{cpu_freq:.0f}' if cpu_freq is not None else 'NA',
                        throt=f'0x{throttled:x}' if throttled is not None else 'NA',
                        mem=mem_used if mem_used is not None else 'NA',
                    )
                )
                # If we have seen no events for a long time, assume input stack wedged and exit
                # if EVENT_STALL_EXIT_SEC and last_evt_age > EVENT_STALL_EXIT_SEC:
                #     self.logger.write(f'EVENT_STALL_EXIT age={last_evt_age:.2f}s -> quitting')
                #     self.logger.close()
                #     pygame.quit()
                #     sys.exit(1)
            if self.logger:
                loop_end = now
                pump_to_draw = draw_start - loop_start
                draw_to_flip = flip_start - draw_start
                flip_time = flip_end - flip_start
                loop_time = loop_end - loop_start
                if loop_time >= LOG_SLOW_FRAME_SEC:
                    self.logger.write(
                        'SLOW_FRAME total={total:.3f}s pump={pump:.3f}s draw={draw:.3f}s flip={flip:.3f}s'.format(
                            total=loop_time,
                            pump=pump_to_draw,
                            draw=draw_to_flip,
                            flip=flip_time,
                        )
                    )
            if self.logger and (now - self.last_snapshot) >= LOG_SNAPSHOT_SEC:
                self.last_snapshot = now
                if self.logger.recent_events:
                    recent = ' | '.join(self.logger.recent_events)
                else:
                    recent = 'NA'
                self.logger.write(f'SNAPSHOT recent="{recent}"')


if __name__ == '__main__':
    App().run()

    App().run()
