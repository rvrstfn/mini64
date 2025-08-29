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

import pygame
import sys
import math
import re
import os
from collections import deque

# ------------------------------
# Config / Palette
# ------------------------------
W, H = 960, 720
LEFT_W = 320
FPS = 60

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

        # status/title
        title = '*** MINI C64 BASIC V2 *** ' + ('EDIT MODE' if self.prog_mode else 'READY.')
        surf.blit(self.font.render(title, True, C64['text']), (x, y))
        y += line_h

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
        if (ev.key == pygame.K_RETURN and (pygame.key.get_mods() & pygame.KMOD_CTRL)) or ev.key == pygame.K_F5:
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
        self.thick = 2
        # editor buffer
        self.prog_lines = [
            '10 REM READY'
        ]
        self.prog_cursor_line = 0
        self.prog_cursor_col = 0
        self.running = False

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
        while self.running and rt['pc'] < len(self.program):
            ln, line = self.program[rt['pc']]
            delta = self.exec_statement(self.tokenize(line), rt)
            if delta is None:
                rt['pc'] += 1
            else:
                rt['pc'] += delta
        self.console.print('READY.')
        self.running = False

    def exec_statement(self, toks, rt):
        if not toks:
            return None
        cmd = toks[0].upper()
        args = toks[1:]

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
            out = ' '.join(args)
            if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
                self.console.print(out[1:-1])
            else:
                self.console.print(str(self.num_or_var(out)))
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
                self.console.print('USAGE: SAVE "NAME"'); return None
            name = args[0].strip('"')
            with open(f"{name}.bas", 'w', encoding='utf-8') as f:
                for ln, raw in self.program:
                    f.write(f"{ln} {raw}\n")
            self.console.print(f'SAVED {name}.bas')
            return None
        if cmd == 'LOAD':
            if not args:
                self.console.print('USAGE: LOAD "NAME"'); return None
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
                self.console.print(f'?LOAD ERROR {e}')
            return None

        # unknown
        self.console.print('?SYNTAX ERROR')
        self.running = False
        return None

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

        # immediate command
        self.exec_statement(self.tokenize(s), {'pc': 0})

# ------------------------------
# App
# ------------------------------
class App:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption('*** MINI C64 BASIC V2 ***')
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('consolas', 18)
        self.console = Console((0, 0, LEFT_W, H), self.font)
        self.machine = MiniC64(self.screen, self.console)
        # --- editor state owned by App ---
        self.prog_lines = ['10 ']
        self.prog_cursor_line = 0
        self.prog_cursor_col = 3
        # keep interpreter pointing to the same list
        self.machine.prog_lines = self.prog_lines

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
        self.machine.process_line(line)
        return

    def run_program(self):
        self.machine.run_program()

    def run(self):
        # header shown in status bar; no need to log it
        self.console.print(' 38911 BASIC BYTES FREE')
        self.console.print('READY.')
        sep_x = LEFT_W

        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        # toggle edit mode
                        if self.console.prog_mode:
                            self.exit_programming_mode()
                        else:
                            self.enter_programming_mode()
                        continue
                    self.console.handle_key(ev, self)

            self.screen.fill(C64['bg'])

            # left pane
            self.console.draw(self.screen, self)

            # right pane border
            pygame.draw.line(self.screen, (10, 10, 10), (sep_x, 0), (sep_x, H), 3)
            # blit gfx
            self.screen.blit(self.machine.gfx, (sep_x, 0))

            pygame.display.flip()
            self.clock.tick(FPS)


if __name__ == '__main__':
    App().run()

    App().run()
