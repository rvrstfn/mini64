# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Mini C64 BASIC V2 interpreter implemented in Python using Pygame. It's a single-file educational project that recreates a simplified BASIC programming environment with turtle graphics capabilities, mimicking the classic Commodore 64 experience.

## Running the Application

```bash
python mini64.py
```

The application requires Pygame to be installed:
```bash
pip install pygame
```

## Architecture

### Core Components

- **App class** (`lines 583-660`): Main application controller that manages the Pygame window, event handling, and coordinates between the console and interpreter
- **Console class** (`lines 77-267`): Handles the left pane UI with dual-mode text interface (console mode and edit mode)  
- **MiniC64 class** (`lines 269-578`): The BASIC interpreter that executes commands, manages program state, variables, and turtle graphics

### Key Features

**Dual Interface Modes:**
- Console mode: Interactive BASIC command line (ESC to toggle)
- Edit mode: Program editor with auto line numbering on Enter

**BASIC Language Support:**
- Core commands: `LET`, `PRINT`, `GOTO`, `FOR`/`NEXT`, `REM`, `END`
- Program management: `LIST`, `RUN`, `NEW`, `EDIT`  
- File operations: `SAVE "filename"`, `LOAD "filename"` (saves as .bas files)
- Turtle graphics: `FD`, `BK`, `RT`, `LT`, `GO`, `CIRCLE`, `PEN`, `PU`/`PD`, `BG`, `THICK`

**Visual Layout:**
- Left pane (320px): Console/editor interface
- Right pane: Graphics canvas for turtle drawing
- C64-inspired color palette and styling

### Program Flow

1. Programs are stored as `(line_number, code)` tuples in `self.program`
2. Edit mode uses `self.prog_lines` for live text editing
3. Variable storage in `self.variables` dict, FOR loops tracked in `self.for_stack`
4. Graphics rendered to separate `self.gfx` surface with turtle state (position, heading, pen)

### Key Implementation Details

- Tokenization splits commands while preserving quoted strings
- FOR/NEXT loop nesting with proper variable matching and stack unwinding
- Auto-commit on RUN when in edit mode
- Keyboard shortcuts: Ctrl+Enter or F5 for quick run in edit mode
- Auto line numbering increments by 10 when pressing Enter after numbered lines

## File Format

Programs save/load as .bas files with format:
```
10 REM COMMENT
20 FOR I = 1 TO 10
30 PRINT "HELLO"
40 NEXT I
```