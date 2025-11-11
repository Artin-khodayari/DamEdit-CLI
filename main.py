import curses
import sys
import os
import json
import locale
from typing import List, Optional, Tuple

locale.setlocale(locale.LC_ALL, "")

CONFIG_FILE = "config.json"

CP_DEFAULT = 1
CP_HEADER = 2
CP_GUTTER = 3
CP_SEARCH_HL = 4
CP_SELECTED_LINE = 5
CP_STATUS_ERR = 6
CP_STATUS_OK = 7
CP_STATUS_INFO = 8

DEFAULT_CONFIG = {
    "theme": {
        "header_fg": "white", "header_bg": "blue",
        "default_fg": "white", "default_bg": "black",
        "gutter_fg": "yellow",
        "search_fg": "black", "search_bg": "yellow",
        "selected_fg": "black", "selected_bg": "cyan",
        "status_ok_fg": "green", "status_err_fg": "red", "status_info_fg": "white"
    }
}

COLOR_NAMES = {
    "black": curses.COLOR_BLACK,
    "red": curses.COLOR_RED,
    "green": curses.COLOR_GREEN,
    "yellow": curses.COLOR_YELLOW,
    "blue": curses.COLOR_BLUE,
    "magenta": curses.COLOR_MAGENTA,
    "cyan": curses.COLOR_CYAN,
    "white": curses.COLOR_WHITE,
    "default": -1
}

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception:
            pass
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Ensure theme exists
        if "theme" not in cfg:
            cfg["theme"] = DEFAULT_CONFIG["theme"].copy()
        # fill missing keys
        for k, v in DEFAULT_CONFIG["theme"].items():
            if k not in cfg["theme"]:
                cfg["theme"][k] = v
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()

def write_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def color_from_name(name: str) -> int:
    if not name:
        return -1
    return COLOR_NAMES.get(name.lower(), -1)

def read_file(path: str) -> Tuple[List[str], bool]:
    if not os.path.exists(path):
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "rb") as f:
        raw = f.read()
    # Normalize CRLF -> LF internally
    if b"\r\n" in raw:
        raw = raw.replace(b"\r\n", b"\n")
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if lines and lines[-1] == "" and not trailing:
        lines.pop()
    return lines, trailing

def write_file(path: str, lines: List[str], trailing: bool) -> None:
    txt = "\n".join(lines)
    if trailing:
        txt += "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)

class EditorState:
    def __init__(self, filename: str, cfg: dict):
        self.filename = filename
        self.cfg = cfg
        self.lines, self.trailing_nl = read_file(filename)
        self.top = 0
        self.sel = 0
        self.window_h = 0
        self.window_w = 0
        self.modified = False
        self.search_term: Optional[str] = None
        self.search_matches: List[int] = []
        self.match_index = -1
        self.status_msg = "Press q to quit, h for help"
        self.status_type = "info"

    def total(self) -> int:
        return len(self.lines)

    def selected_index(self) -> int:
        return self.top + self.sel

    def clamp(self) -> None:
        if self.window_h <= 0:
            return
        max_top = max(0, self.total() - self.window_h)
        if self.top < 0:
            self.top = 0
        if self.top > max_top:
            self.top = max_top
        if self.sel < 0:
            self.sel = 0
        if self.sel >= self.window_h:
            self.sel = self.window_h - 1
        if self.selected_index() >= self.total():
            if self.total() == 0:
                self.top = 0; self.sel = 0
            else:
                last = self.total() - 1
                self.top = max(0, last - (self.window_h - 1))
                self.sel = last - self.top

def set_status(st: EditorState, msg: str, tp: str = "info") -> None:
    st.status_msg = msg
    st.status_type = tp

def find_positions(line: str, term: Optional[str]) -> List[Tuple[int,int]]:
    if not term:
        return []
    low = line.lower(); t = term.lower()
    res = []
    i = 0; lt = len(t)
    while i <= len(line) - lt:
        if low[i:i+lt] == t:
            res.append((i, i+lt)); i += lt
        else:
            i += 1
    return res

def init_color_pairs(cfg: dict) -> None:
    theme = cfg.get("theme", {})
    curses.use_default_colors()
    def pair(idn: int, fg_name: str, bg_name: str):
        fg = color_from_name(theme.get(fg_name, "default"))
        bg = color_from_name(theme.get(bg_name, "default"))
        try:
            curses.init_pair(idn, fg, bg)
        except Exception:
            curses.init_pair(idn, -1, -1)
    pair(CP_DEFAULT, "default_fg", "default_bg")
    pair(CP_HEADER, "header_fg", "header_bg")
    pair(CP_GUTTER, "gutter_fg", "default_bg")
    pair(CP_SEARCH_HL, "search_fg", "search_bg")
    pair(CP_SELECTED_LINE, "selected_fg", "selected_bg")
    pair(CP_STATUS_ERR, "status_err_fg", "header_bg")
    pair(CP_STATUS_OK, "status_ok_fg", "header_bg")
    pair(CP_STATUS_INFO, "status_info_fg", "header_bg")

def prompt_input(stdscr, st: EditorState, prompt: str, initial: str = "") -> Optional[str]:
    curses.echo()
    h, w = stdscr.getmaxyx()
    win = curses.newwin(1, max(10, w - 1), h - 1, 0)
    win.bkgd(' ', curses.color_pair(CP_HEADER))
    win.erase()
    txt = prompt + initial
    try:
        win.addnstr(0, 0, prompt, w - 1, curses.color_pair(CP_HEADER))
        win.addnstr(0, len(prompt), initial, w - 1 - len(prompt), curses.color_pair(CP_HEADER))
        win.refresh()
        inp_bytes = win.getstr(0, len(prompt) + len(initial))
        inp = inp_bytes.decode(locale.getpreferredencoding(), errors="replace")
    except Exception:
        inp = None
    curses.noecho()
    return inp

def recompute_search(st: EditorState) -> None:
    st.search_matches = []
    if not st.search_term:
        st.match_index = -1; return
    t = st.search_term.lower()
    for i, ln in enumerate(st.lines):
        if t in ln.lower():
            st.search_matches.append(i)
    if not st.search_matches:
        st.match_index = -1
    else:
        sel = st.selected_index()
        for idx, li in enumerate(st.search_matches):
            if li >= sel:
                st.match_index = idx; break
        else:
            st.match_index = 0

def goto_search_match(st: EditorState, forward: bool = True) -> None:
    if not st.search_matches:
        set_status(st, "No matches", "err"); return
    if st.match_index == -1:
        st.match_index = 0
    else:
        st.match_index = (st.match_index + (1 if forward else -1)) % len(st.search_matches)
    target = st.search_matches[st.match_index]
    half = st.window_h // 2
    st.top = max(0, target - half)
    st.sel = target - st.top
    st.clamp()
    set_status(st, f"Match {st.match_index+1}/{len(st.search_matches)} at {target+1}")

def draw(stdscr, st: EditorState) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    st.window_h = max(1, h - 2)
    st.window_w = w
    st.clamp()
    # header
    hdr = f" Dam cEditor: {os.path.basename(st.filename)} "
    if st.modified: hdr += "[MODIFIED] "
    try:
        stdscr.addnstr(0, 0, hdr.ljust(w), w, curses.color_pair(CP_HEADER) | curses.A_BOLD)
    except curses.error:
        pass
    # content
    for row in range(st.window_h):
        idx = st.top + row
        y = row + 1
        if idx >= st.total():
            try: stdscr.addnstr(y, 0, "~", w, curses.color_pair(CP_DEFAULT))
            except curses.error: pass
            continue
        line = st.lines[idx]
        matches = find_positions(line, st.search_term)
        is_sel = (row == st.sel)
        base_attr = curses.color_pair(CP_SELECTED_LINE) if is_sel else curses.color_pair(CP_DEFAULT)
        gutter = f"|{idx+1:5d}| "
        try:
            gutter_attr = curses.color_pair(CP_GUTTER) | (curses.A_BOLD if is_sel else 0)
            stdscr.addnstr(y, 0, gutter[:w], w, gutter_attr)
        except curses.error:
            pass
        x = len(gutter)
        cur = 0
        for s, e in matches:
            if x >= w: break
            seg = line[cur:s]
            if seg:
                try:
                    stdscr.addnstr(y, x, seg, w - x, base_attr)
                except curses.error:
                    pass
                x += min(len(seg), max(0, w - x))
            if x >= w: break
            mseg = line[s:e]
            try:
                stdscr.addnstr(y, x, mseg, w - x, curses.color_pair(CP_SEARCH_HL) | curses.A_BOLD)
            except curses.error:
                pass
            x += min(len(mseg), max(0, w - x))
            cur = e
        if x < w and cur < len(line):
            tail = line[cur:]
            try:
                stdscr.addnstr(y, x, tail, w - x, base_attr)
            except curses.error:
                pass
        if is_sel and x < w:
            try:
                stdscr.addnstr(y, x, " " * (w - x), w - x, base_attr)
            except curses.error:
                pass
    # status
    sy = h - 1
    left = f" q:quit s:save e:edit /:find n/N:next/prev g:goto r:reload t:themes | Line {st.selected_index()+1}/{st.total()}"
    try:
        stdscr.addnstr(sy, 0, left.ljust(w), w, curses.color_pair(CP_HEADER))
    except curses.error:
        pass
    if st.status_msg:
        msg = f" {st.status_msg} "
        msg_x = max(0, w - len(msg))
        if msg_x > len(left):
            colorp = CP_STATUS_INFO
            if st.status_type == "err": colorp = CP_STATUS_ERR
            elif st.status_type == "ok": colorp = CP_STATUS_OK
            try:
                stdscr.addnstr(sy, msg_x, msg, w - msg_x, curses.color_pair(colorp) | curses.A_BOLD)
            except curses.error:
                pass
    stdscr.refresh()

def theme_editor(stdscr, st: EditorState) -> None:
    curses.curs_set(1)
    cfg = st.cfg
    theme = cfg.setdefault("theme", {}).copy()
    keys = list(theme.keys())
    idx = 0
    while True:
        stdscr.erase()
        stdscr.addnstr(0, 0, "Theme Editor (↑/↓ select, Enter edit, s save, q quit)", curses.A_BOLD)
        for i, k in enumerate(keys):
            v = theme[k]
            marker = ">" if i == idx else " "
            try:
                stdscr.addstr(i + 2, 2, f"{marker} {k}: {v}")
            except curses.error:
                pass
        stdscr.refresh()
        try:
            ch = stdscr.get_wch()
        except Exception:
            continue
        if ch in ("q", 27):
            break
        elif ch == curses.KEY_UP:
            idx = max(0, idx - 1)
        elif ch == curses.KEY_DOWN:
            idx = min(len(keys) - 1, idx + 1)
        elif ch == "\n":
            key = keys[idx]
            curval = theme.get(key, "")
            newv = prompt_input(stdscr, st, f"New value for {key}: ")
            if newv is not None:
                theme[key] = newv.strip()
        elif ch in ("s", "S"):
            # apply
            cfg["theme"] = theme.copy()
            write_config(cfg)
            set_status(st, "Theme saved to config.json", "ok")
            curses.curs_set(0)
            return
    curses.curs_set(0)

def main_curses(stdscr, filename: str) -> None:
    cfg = load_config()
    stdscr.keypad(True)
    curses.curs_set(0)
    try:
        curses.start_color()
        curses.use_default_colors()
    except Exception:
        pass
    init_color_pairs(cfg)
    st = EditorState(filename, cfg)
    recompute_search(st)
    while True:
        draw(stdscr, st)
        try:
            key = stdscr.get_wch()
        except KeyboardInterrupt:
            break
        except Exception:
            continue
        ch = key if isinstance(key, str) else None
        if ch == "q" or key == 27:
            if st.modified:
                ans = prompt_input(stdscr, st, "Modified. Quit without saving? (y/N): ")
                if ans and ans.lower() == "y":
                    break
                else:
                    continue
            break
        if key == curses.KEY_UP or ch == "k":
            if st.sel > 0: st.sel -= 1
            elif st.top > 0: st.top -= 1
            set_status(st, "")
        elif key == curses.KEY_DOWN or ch == "j":
            if st.selected_index() + 1 < st.total():
                if st.sel + 1 < st.window_h: st.sel += 1
                else: st.top += 1
            set_status(st, "")
        elif key == curses.KEY_PPAGE:
            page = max(1, st.window_h - 1); st.top = max(0, st.top - page); set_status(st, "")
        elif key == curses.KEY_NPAGE:
            page = max(1, st.window_h - 1); st.top = min(max(0, st.total() - st.window_h), st.top + page); set_status(st, "")
        elif ch == "g":
            n = prompt_input(stdscr, st, "Go to line: ")
            if n and n.strip().isdigit():
                ln = int(n.strip()) - 1
                ln = max(0, min(ln, max(0, st.total() - 1)))
                st.top = max(0, ln - st.window_h // 2); st.sel = ln - st.top; st.clamp()
                set_status(st, f"Jumped to {ln+1}", "ok")
            elif n is not None:
                set_status(st, "Invalid line", "err")
        elif ch == "e":
            idx = st.selected_index()
            if 0 <= idx < st.total():
                cur = st.lines[idx]
                new = prompt_input(stdscr, st, f"Edit line {idx+1}: ", cur)
                if new is not None and new != cur:
                    st.lines[idx] = new; st.modified = True; set_status(st, "Line updated", "ok")
                    if st.search_term: recompute_search(st)
                else:
                    set_status(st, "Edit cancelled")
            else:
                set_status(st, "Nothing to edit", "err")
        elif ch == "s":
            try:
                write_file(st.filename, st.lines, st.trailing_nl)
                st.modified = False; set_status(st, "Saved", "ok")
            except Exception as e:
                set_status(st, f"Save error: {e}", "err")
        elif ch == "/":
            term = prompt_input(stdscr, st, "Search (empty to clear): ", st.search_term or "")
            if term is None:
                set_status(st, "Search cancelled")
            else:
                t = term.strip()
                if t == "":
                    st.search_term = None; recompute_search(st); set_status(st, "Search cleared")
                else:
                    st.search_term = t; recompute_search(st)
                    if st.search_matches:
                        goto_search_match(st, True)
                    else:
                        set_status(st, f"No matches for '{t}'", "err")
        elif ch == "n":
            goto_search_match(st, True)
        elif ch == "N":
            goto_search_match(st, False)
        elif ch == "r":
            if st.modified:
                ans = prompt_input(stdscr, st, "Reload (unsaved changes will be lost) (y/N): ")
                if not (ans and ans.lower() == "y"):
                    set_status(st, "Reload cancelled"); continue
            try:
                st.lines, st.trailing_nl = read_file(st.filename); st.modified = False; set_status(st, "Reloaded", "ok")
                if st.search_term: recompute_search(st)
            except Exception as e:
                set_status(st, f"Reload error: {e}", "err")
        elif ch == "t":
            curses.curs_set(0)
            theme_editor(stdscr, st)
            # reload color pairs after editing theme
            cfg2 = load_config(); st.cfg = cfg2
            init_color_pairs(cfg2)
            set_status(st, "Applied theme from config.json", "ok")
            curses.curs_set(1)
        elif key == curses.KEY_RESIZE:
            set_status(st, "Resized")
            pass

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 main.py <filename>", file=sys.stderr); sys.exit(1)
    try:
        curses.wrapper(main_curses, sys.argv[1])
    except curses.error as e:
        print("Terminal does not support curses or colors.", file=sys.stderr)
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExit.", file=sys.stderr)

if __name__ == "__main__":
    main()
