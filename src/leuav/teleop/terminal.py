"""键盘输入与终端显示小工具；不含 ROS、PX4 或飞行命令，学员无需修改。"""
import curses
import sys


class RecentKeys:
    """终端没有松键事件：重复按键续期，0.2 秒后自动回中；空格清空方向键。"""
    def __init__(self, hold_s=.2):
        self.hold_s = hold_s
        self.seen = {}

    def press(self, key, now):
        if key == 'space':
            # 回中也记录一次：map_keys 能看到 'space'，0.2 秒内保持全零。
            self.seen = {'space': now}
        else:
            self.seen[key] = now

    def active(self, now):
        self.seen = {key: stamp for key, stamp in self.seen.items()
                     if now-stamp < self.hold_s}
        return frozenset(self.seen)


class Terminal:
    def __enter__(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError('需要交互终端；进入 Docker 时使用 -it')
        self.screen = curses.initscr()
        try:
            curses.noecho()
            curses.cbreak()
            curses.set_escdelay(25)
            self.screen.keypad(True)
            self.screen.nodelay(True)
        except BaseException:
            curses.endwin()
            raise
        return self

    def read_keys(self):
        arrows = {curses.KEY_UP: 'up', curses.KEY_DOWN: 'down',
                  curses.KEY_LEFT: 'left', curses.KEY_RIGHT: 'right'}
        keys = []
        for _ in range(64):
            code = self.screen.getch()
            if code == -1:
                break
            key = arrows.get(code, chr(code).lower() if 0 <= code < 128 else '')
            keys.append('space' if key == ' ' else key)
        return keys

    def draw(self, lines):
        self.screen.erase()
        rows, cols = self.screen.getmaxyx()
        for row, line in enumerate(lines[:max(0, rows-1)]):
            try:
                self.screen.addnstr(row, 0, line, max(0, cols-1))
            except curses.error:
                pass
        self.screen.refresh()

    def __exit__(self, *exc):
        self.screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
