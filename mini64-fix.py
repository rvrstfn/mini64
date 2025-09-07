# MINI C64 BASIC V2 — single-window Pygame edition (fixed)
# --------------------------------------------------------
# This file merges Stefano's original with two fixes:
#  1) Correct NEXT handling for nested/unnamed NEXT (no more ?NEXT WITHOUT FOR).
#  2) RUN auto-commits EDIT mode.
#
# Plus Pi-console patches:
#  - Auto-detect native resolution and go fullscreen (kmsdrm) to avoid blank screen.
#  - Silence ALSA underruns by disabling mixer and using SDL_AUDIODRIVER=dummy.
#
# Notes:
#  - Minimal, toy interpreter focused on LOGO-like turtle commands and tiny BASIC.
#  - Left pane: console + editor. Right pane: graphics.
#  - Keys: ESC toggles edit/console; Up/Down browse history; Ctrl+Enter/F5 quick RUN in edit.

import pygame
import sys
import math
import re
import os
from collections import deque

# ------------------------------
# Config / Palette
# ------------------------------
W, H = 0, 0  # 0=auto-detect native panel size at runtime
LEFT_W = 320
FPS = 60

C64 = {
    'bg': (24, 24, 70),       # deep blue
    'panel': (14, 18, 56),
    'text': (230, 230, 255),
    'muted': (170, 170, 210),
    'caret': (255, 255, 255),
    'cursor': (255, 255, 255),
    'warn': (255, 220, 120),
    'error': (255, 120, 120),
    'green': (120, 255, 120),
    'blue': (120, 180, 255),
}

PENS = {
    '1': (255,255,255), '2': (255,255,0), '3': (255,0,255), '4': (0,255,255),
    '5': (0,255,0), '6': (255,0,0), '7': (0,0,255), '8': (255,128,0)
}

# ------------------------------
# Helpers
# ------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def tokenize(line):
    # very small tokenizer: numbers, identifiers, strings, ops
    toks = []
    i = 0
    s = line.rstrip('\n')
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c in ',:+-*/()=<>':
            toks.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < len(s) and s[j] != '"': j += 1
            toks.append(('STR', s[i+1:j]))
            i = j + 1
            continue
        if c.isdigit():
            j = i + 1
            while j < len(s) and s[j].isdigit(): j += 1
            toks.append(('NUM', int(s[i:j])))
            i = j
            continue
        # ident
        j = i + 1
        while j < len(s) and (s[j].isalnum() or s[j]=='_'): j += 1
        toks.append(('ID', s[i:j].upper()))
        i = j
    return toks

# ------------------------------
# UI pieces
# ------------------------------
class Console:
    def __init__(self, rect, font):
        self.x, self.y, self.w, self.h = rect
        self.font = font
        self.lines = deque(maxlen=1000)
        self.input = ''
        self.hist = []
        self.hpos = 0
        self.edit_mode = False
        self.caret = True
        self.caret_tick = 0

    def print(self, text, color=C64['text']):
        for ln in text.split('\n'):
            self.lines.append((ln, color))

    def prompt(self):
        return 'READY.' if not self.edit_mode else 'EDIT>'

    def draw(self, surf):
        panel = pygame.Surface((self.w, self.h))
        panel.fill(C64['panel'])
        # history
        y = 8
        for (ln, color) in list(self.lines)[-((self.h-48)//20):]:
            img = self.font.render(ln, True, color)
            panel.blit(img, (8, y))
            y += 20
        # input
        hint = self.prompt() + ' ' + self.input
        img = self.font.render(hint, True, C64['text'])
        panel.blit(img, (8, self.h - 32))
        if self.caret:
            panel.fill(C64['caret'], (8 + img.get_width() + 3, self.h - 32, 10, 18))
        surf.blit(panel, (0, 0))

    def tick(self):
        self.caret_tick = (self.caret_tick + 1) % 30
        if self.caret_tick == 0:
            self.caret = not self.caret

# ------------------------------
# Editor events (subset)
# ------------------------------
class Editor:
    def handle_event(self, app, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            app.exit_programming_mode()
            return
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_F5,) or (ev.key == pygame.K_RETURN and (ev.mod & pygame.KMOD_CTRL)):
            app.commit_and_run()
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                line = app.prog_lines[app.prog_cursor_line]
                if app.prog_cursor_col > 0:
                    app.prog_lines[app.prog_cursor_line] = line[:app.prog_cursor_col-1] + line[app.prog_cursor_col:]
                    app.prog_cursor_col -= 1
                return
            if ev.key == pygame.K_DELETE:
                line = app.prog_lines[app.prog_cursor_line]
                if app.prog_cursor_col < len(line):
                    app.prog_lines[app.prog_cursor_line] = line[:app.prog_cursor_col] + line[app.prog_cursor_col+1:]
                return
            if ev.key == pygame.K_LEFT:
                app.prog_cursor_col = max(0, app.prog_cursor_col - 1)
                return
            if ev.key == pygame.K_RIGHT:
                app.prog_cursor_col = min(len(app.prog_lines[app.prog_cursor_line]), app.prog_cursor_col + 1)
                return
            if ev.key == pygame.K_UP:
                app.prog_cursor_line = max(0, app.prog_cursor_line - 1)
                app.prog_cursor_col = min(app.prog_cursor_col, len(app.prog_lines[app.prog_cursor_line]))
                return
            if ev.key == pygame.K_DOWN:
                app.prog_cursor_line = min(len(app.prog_lines) - 1, app.prog_cursor_line + 1)
                app.prog_cursor_col = min(app.prog_cursor_col, len(app.prog_lines[app.prog_cursor_line]))
                return
            if ev.key == pygame.K_HOME:
                app.prog_cursor_col = 0; return
            if ev.key == pygame.K_END:
                app.prog_cursor_col = len(app.prog_lines[app.prog_cursor_line]); return
            if ev.key == pygame.K_RETURN:
                # split line
                line = app.prog_lines[app.prog_cursor_line]
                app.prog_lines[app.prog_cursor_line] = line[:app.prog_cursor_col]
                app.prog_lines.insert(app.prog_cursor_line + 1, line[app.prog_cursor_col:])
                app.prog_cursor_line += 1
                app.prog_cursor_col = 0
                return
        if ev.type == pygame.TEXTINPUT:
            if ev.text:
                line = app.prog_lines[app.prog_cursor_line]
                col = clamp(app.prog_cursor_col, 0, len(line))
                app.prog_lines[app.prog_cursor_line] = line[:col] + ev.text + line[col:]
                app.prog_cursor_col += len(ev.text)

# ------------------------------
# MiniC64 (tiny BASIC + turtle)
# ------------------------------
class MiniC64:
    def __init__(self, surface, console):
        self.surf = surface
        self.console = console
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
        self.thickness = 2

    # ----------------------
    # Console I/O
    # ----------------------
    def say(self, msg, color=C64['text']):
        self.console.print(msg, color)

    # ----------------------
    # Interpreter core
    # ----------------------
    def set_program(self, lines):
        self.program = lines[:]
        self.labels = {}
        for i, (ln, raw) in enumerate(self.program):
            toks = tokenize(raw)
            if toks and toks[0] == ('ID', 'LABEL') and len(toks) >= 2 and toks[1][0]=='ID':
                self.labels[toks[1][1]] = i

    def run(self):
        ip = 0
        self.for_stack.clear()
        while ip < len(self.program):
            ln, raw = self.program[ip]
            toks = tokenize(raw)
            step_ip = 1

            def expect(tok):
                if not toks or toks[0][0] != tok:
                    raise RuntimeError('SYNTAX ERROR')
                return toks.pop(0)

            def read_number():
                t = expect('NUM')
                return t[1]

            def read_id():
                t = expect('ID'); return t[1]

            if not toks:
                ip += step_ip; continue

            t0 = toks.pop(0)
            if t0 == ('ID','REM'):
                ip += step_ip; continue

            if t0 == ('ID','PRINT'):
                out = []
                while toks:
                    t = toks.pop(0)
                    if t[0]=='STR': out.append(t[1])
                    elif t[0]=='NUM': out.append(str(t[1]))
                    elif t == ',': out.append(' ')
                self.say(''.join(out))
            elif t0 == ('ID','LET'):
                name = read_id(); expect('='); val = read_number()
                self.variables[name] = val
            elif t0 == ('ID','IF'):
                a = read_number(); op = toks.pop(0); b = read_number(); expect(('ID','THEN'))
                cond = (op == ('<')) and (a < b) or (op == ('>')) and (a > b) or (op == ('=')) and (a == b)
                if not cond:
                    ip += step_ip; continue
                # if true, execute rest as immediate
                if toks and toks[0][0]=='ID' and toks[0][1]=='GOTO':
                    toks.pop(0); label = read_id(); ip = self.labels.get(label, ip+1); continue
            elif t0 == ('ID','GOTO'):
                label = read_id(); ip = self.labels.get(label, ip+1); continue
            elif t0 == ('ID','LABEL'):
                pass
            elif t0 == ('ID','FOR'):
                var = read_id(); expect('='); start = read_number(); expect('TO'); end = read_number()
                step = 1
                if toks and toks[0] == ('ID','STEP'):
                    toks.pop(0); step = read_number()
                self.variables[var] = start
                self.for_stack.append((var, end, step, ip))