####################################################
#  Network Programming - Unit 3 Application based on TCP
#  Program Name: pop3client.py
#  學號 (Student ID): D1211110
#  姓名 (Name)      : 陳嘉希
#
#  The program is a POP3 mail client (修改自範例 pop3client.py)。
#  以 TCP socket 直接與 POP3 伺服器對話 (USER/PASS/STAT/LIST/TOP/RETR/DELE/RSET/QUIT)，
#  並以 Python 內建的 email 模組解析、解碼信件內容。
#
#  基本功能:
#    (1) 秀出 mailbox 中有幾封 mail                        (STAT)
#    (2) 列出每封 mail 的寄信時間、主題、寄件人、收件人    (LIST + TOP n 0)
#    (3) 列出第 nn 封信的內容，信件已編碼者自動解碼        (RETR + MIME 解碼)
#    (4) 刪除第 nn 封信                                    (DELE，QUIT 時生效)
#  加分功能:
#    - 取消刪除 (RSET)、依關鍵字搜尋信件、檢視原始信件 (raw source)
#    - 儲存信件 (.eml) 與附件、支援 POP3 over SSL (POP3S, port 995)
#    - -v 顯示 Client/Server 之間的完整 POP3 對話過程
#    - --gui 以 tkinter 圖形介面操作 (GUI)
#
#  Usage:
#    python3 pop3client.py ServerIP                 (文字選單模式)
#    python3 pop3client.py ServerIP --ssl           (POP3S, port 995)
#    python3 pop3client.py ServerIP -p 1100 -v      (指定 port、顯示協定對話)
#    python3 pop3client.py --gui                    (圖形介面)
#    python3 pop3client.py                          (不加參數或直接雙擊也會開啟圖形介面)
#  2026.10.05
####################################################
import argparse
import os
import re
import shutil
import socket
import ssl
import sys
import unicodedata
from dataclasses import dataclass, field
from email import message_from_bytes
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from getpass import getpass
from html.parser import HTMLParser


# 定義全域常數
PORT = 110        # POP3 預設 port
SSL_PORT = 995    # POP3S 預設 port
BUFF_SIZE = 1024  # 接收緩衝區大小 (Byte)
TIMEOUT = 30      # socket 逾時秒數
DEFAULT_SERVER = "140.134.135.42"   # 課程 POP3 Server (GUI 登入畫面預設值)
DEFAULT_USER = "iecs01"             # 本組帳號 (GUI 登入畫面預設值)


class POP3Error(Exception):
    """伺服器回應 -ERR 時丟出的例外。"""


# ============================================================
#  POP3 協定層：以 socket 直接收送 POP3 指令
# ============================================================
class POP3Client:
    def __init__(self, host, port=None, use_ssl=False, verbose=False, log=print):
        self.host = host
        self.use_ssl = use_ssl
        self.port = port or (SSL_PORT if use_ssl else PORT)
        self.verbose = verbose    # True 時印出完整的 C:/S: 對話
        self.log = log
        self.sock = None
        self._buf = bytearray()   # 接收緩衝區，用來切出一行一行的回應

    # ---------- 連線 / 底層收送 ----------
    def connect(self):
        """建立 TCP 連線 (可選 SSL)，回傳伺服器歡迎訊息。"""
        server_ip = socket.gethostbyname(self.host)   # 支援域名解析
        self.log(f"Connecting to {self.host} ({server_ip}) port {self.port}"
                 f"{' with SSL' if self.use_ssl else ''}")
        sock = socket.create_connection((server_ip, self.port), timeout=TIMEOUT)
        if self.use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=self.host)
        self.sock = sock
        return self._check(self._readline())

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send(self, cmd):
        if self.verbose:
            shown = "PASS ****" if cmd.upper().startswith("PASS ") else cmd
            self.log(f"C: {shown}")
        self.sock.sendall((cmd + "\r\n").encode("utf-8"))   # don't forget "\r\n"

    def _readline(self):
        """從 socket 讀取一行 (以 \\n 結尾，去掉行尾的 \\r\\n)，回傳 bytes。"""
        idx = self._buf.find(b"\n")
        while idx < 0:
            chunk = self.sock.recv(BUFF_SIZE)
            if not chunk:
                raise ConnectionError("伺服器已關閉連線")
            start = len(self._buf)
            self._buf += chunk
            idx = self._buf.find(b"\n", start)
        line = bytes(self._buf[:idx])
        del self._buf[:idx + 1]
        return line.rstrip(b"\r")

    def _check(self, line):
        """檢查狀態列：+OK 回傳文字，-ERR 則丟出 POP3Error。"""
        text = line.decode("utf-8", errors="replace")
        if self.verbose:
            self.log(f"S: {text}")
        if not text.startswith("+OK"):
            raise POP3Error(text)
        return text

    def _single(self, cmd):
        """送出指令並讀取單行回應。"""
        self._send(cmd)
        return self._check(self._readline())

    def _multi(self, cmd):
        """送出指令並讀取多行回應 (以單獨一行 "." 結束)。

        依 RFC 1939，以 "." 開頭的資料行會被伺服器多加一個 "." (dot-stuffing)，
        這裡要把它還原。回傳 (狀態列, [每一行的 bytes])。
        """
        status = self._single(cmd)
        lines = []
        while True:
            line = self._readline()
            if line == b".":
                break
            if line.startswith(b".."):
                line = line[1:]
            lines.append(line)
        if self.verbose:
            self.log(f"S: <{len(lines)} lines>")
            self.log("S: .")
        return status, lines

    # ---------- POP3 指令 ----------
    def login(self, user, password):
        self._single(f"USER {user}")
        return self._single(f"PASS {password}")

    def stat(self):
        """STAT -> (信件數, 總位元組數)"""
        tokens = self._single("STAT").split()
        return int(tokens[1]), int(tokens[2])

    def list(self):
        """LIST -> [(信件編號, 大小), ...]  (已標記刪除的信不會出現)"""
        _, lines = self._multi("LIST")
        result = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                result.append((int(parts[0]), int(parts[1])))
        return result

    def top(self, num, n_lines=0):
        """TOP num n -> 信件標頭 + 前 n 行內文 (bytes)"""
        _, lines = self._multi(f"TOP {num} {n_lines}")
        return b"\r\n".join(lines) + b"\r\n"

    def retr(self, num):
        """RETR num -> 整封原始信件 (bytes)"""
        _, lines = self._multi(f"RETR {num}")
        return b"\r\n".join(lines) + b"\r\n"

    def dele(self, num):
        return self._single(f"DELE {num}")

    def rset(self):
        return self._single("RSET")

    def noop(self):
        return self._single("NOOP")

    def quit(self):
        try:
            return self._single("QUIT")
        finally:
            self.close()


# ============================================================
#  信件解析 / 解碼
# ============================================================
# 一些常見但 Python codec 涵蓋不完整的字集，改用相容的超集合來解碼
CHARSET_ALIASES = {"big5": "cp950", "big5-hkscs": "big5hkscs", "x-big5": "cp950",
                   "gb2312": "gb18030", "gbk": "gb18030", "ks_c_5601-1987": "cp949"}


def decode_bytes(data, charset):
    charset = (charset or "utf-8").lower()
    charset = CHARSET_ALIASES.get(charset, charset)
    try:
        return data.decode(charset, errors="replace")
    except LookupError:                  # 不認識的字集
        return data.decode("utf-8", errors="replace")


def decode_mime_header(value):
    """解碼 RFC 2047 編碼的標頭，例如 =?UTF-8?B?5ris6Kmm?= -> 測試"""
    if value is None:
        return ""
    result = []
    for part, charset in decode_header(str(value)):
        if isinstance(part, bytes):
            result.append(decode_bytes(part, charset))
        else:
            result.append(part)
    # 移除折行 (folding) 造成的換行
    return re.sub(r"\s*\r?\n\s*", " ", "".join(result)).strip()


def format_addresses(value):
    """將 From/To 標頭解碼成 "姓名 <email>" 形式 (多個收件人以逗號分隔)。"""
    if not value:
        return ""
    out = []
    for name, addr in getaddresses([str(value)]):
        name = decode_mime_header(name)
        if name and addr:
            out.append(f"{name} <{addr}>")
        else:
            out.append(name or addr)
    return ", ".join(x for x in out if x)


def format_date(value):
    """將 Date 標頭轉成本地時間 YYYY-MM-DD HH:MM:SS。"""
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is not None:
            dt = dt.astimezone()          # 轉換為本機時區
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, IndexError):
        return decode_mime_header(value)


class _HTMLToText(HTMLParser):
    """把 HTML 信件簡單轉成純文字 (僅有 HTML 內文時使用)。"""
    BLOCK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html):
    p = _HTMLToText()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class MailSummary:
    num: int
    size: int
    date: str
    subject: str
    sender: str
    to: str


@dataclass
class Mail:
    num: int
    date: str
    subject: str
    sender: str
    to: str
    cc: str
    body: str
    encodings: list = field(default_factory=list)     # 例: ["text/plain; utf-8; base64"]
    attachments: list = field(default_factory=list)
    raw: bytes = b""


def parse_summary(num, size, header_bytes):
    msg = message_from_bytes(header_bytes)
    return MailSummary(num=num, size=size,
                       date=format_date(msg.get("Date")),
                       subject=decode_mime_header(msg.get("Subject")) or "(無主題)",
                       sender=format_addresses(msg.get("From")),
                       to=format_addresses(msg.get("To")))


def parse_mail(num, raw):
    """解析整封信：解碼標頭、內文 (base64 / quoted-printable / 各種字集) 與附件。"""
    msg = message_from_bytes(raw)
    plain, html, encodings, attachments = [], [], [], []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""   # 自動處理 base64 / QP 解碼

        if filename or "attachment" in disposition:
            name = decode_mime_header(filename) if filename else f"part-{len(attachments) + 1}"
            attachments.append(Attachment(name, ctype, payload))
            continue
        if ctype not in ("text/plain", "text/html"):
            continue

        charset = part.get_content_charset()
        cte = (part.get("Content-Transfer-Encoding") or "7bit").lower()
        encodings.append(f"{ctype}; charset={charset or 'us-ascii'}; {cte}")
        text = decode_bytes(payload, charset)
        (plain if ctype == "text/plain" else html).append(text)

    if plain:
        body = "\n".join(plain)
    elif html:
        body = html_to_text("\n".join(html))
    else:
        body = ""
    body = body.replace("\r\n", "\n")

    return Mail(num=num,
                date=format_date(msg.get("Date")),
                subject=decode_mime_header(msg.get("Subject")) or "(無主題)",
                sender=format_addresses(msg.get("From")),
                to=format_addresses(msg.get("To")),
                cc=format_addresses(msg.get("Cc")),
                body=body.strip("\n"),
                encodings=encodings,
                attachments=attachments,
                raw=raw)


# ============================================================
#  MailBox：在 POP3Client 之上提供 CLI/GUI 共用的操作
# ============================================================
class MailBox:
    def __init__(self, client):
        self.client = client
        self._cache = {}          # num -> MailSummary
        self.deleted = set()      # 本次連線中已標記刪除的信件編號

    def count(self):
        return self.client.stat()

    def summaries(self):
        """取得所有 (未刪除) 信件的摘要。以 TOP n 0 只抓標頭，不下載整封信。"""
        result = []
        for num, size in self.client.list():
            if num not in self._cache:
                try:
                    header = self.client.top(num, 0)
                except POP3Error:          # 少數伺服器不支援 TOP，改用 RETR
                    header = self.client.retr(num)
                self._cache[num] = parse_summary(num, size, header)
            result.append(self._cache[num])
        return result

    def read(self, num):
        return parse_mail(num, self.client.retr(num))

    def delete(self, num):
        reply = self.client.dele(num)
        self.deleted.add(num)
        return reply

    def undelete_all(self):
        reply = self.client.rset()
        self.deleted.clear()
        return reply

    def search(self, keyword):
        kw = keyword.lower()
        return [s for s in self.summaries()
                if kw in s.subject.lower() or kw in s.sender.lower() or kw in s.to.lower()]

    def save(self, num, folder="mails"):
        """把第 num 封信存成 .eml，並把附件存到同一資料夾。回傳存檔路徑列表。"""
        mail = self.read(num)
        os.makedirs(folder, exist_ok=True)
        paths = []
        eml = os.path.join(folder, f"mail_{num}.eml")
        with open(eml, "wb") as f:
            f.write(mail.raw)
        paths.append(eml)
        for att in mail.attachments:
            safe = re.sub(r'[\\/:*?"<>|]', "_", att.filename)
            path = os.path.join(folder, f"mail_{num}_{safe}")
            with open(path, "wb") as f:
                f.write(att.data)
            paths.append(path)
        return paths

    def quit(self):
        return self.client.quit()


def human_size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ============================================================
#  文字選單介面 (CLI)
# ============================================================
def text_width(s):
    """計算字串在終端機上的顯示寬度 (中文字佔 2 格)。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def fit(s, width):
    """把字串截斷 / 補空白成固定顯示寬度。"""
    s = s.replace("\n", " ")
    if text_width(s) > width:
        out, w = "", 0
        for c in s:
            cw = text_width(c)
            if w + cw > width - 1:
                break
            out, w = out + c, w + cw
        s = out + "…"
    return s + " " * (width - text_width(s))


def print_summaries(summaries):
    if not summaries:
        print("(沒有信件)")
        return
    cols = shutil.get_terminal_size((120, 24)).columns
    if cols < 100:
        # 視窗太窄：每封信分多行顯示
        for s in summaries:
            print(f"[{s.num}] {s.date}  ({human_size(s.size)})")
            print(f"    主題  : {s.subject}")
            print(f"    寄件人: {s.sender}")
            print(f"    收件人: {s.to}")
        return
    rest = cols - 4 - 1 - 19 - 1 - 1 - 1
    w_from = w_to = min(32, rest * 3 // 10)
    w_subj = rest - w_from - w_to - 2
    header = (f"{fit('No.', 4)} {fit('寄信時間', 19)} | {fit('寄件人', w_from)} "
              f"{fit('收件人', w_to)} {fit('主題', w_subj)}")
    print(header)
    print("-" * min(cols - 1, text_width(header)))
    for s in summaries:
        print(f"{fit(str(s.num), 4)} {fit(s.date, 19)} | {fit(s.sender, w_from)} "
              f"{fit(s.to, w_to)} {fit(s.subject, w_subj)}")


def print_mail(mail):
    line = "=" * 70
    print(line)
    print(f"第 {mail.num} 封信")
    print(line)
    print(f"寄信時間: {mail.date}")
    print(f"寄件人  : {mail.sender}")
    print(f"收件人  : {mail.to}")
    if mail.cc:
        print(f"副本    : {mail.cc}")
    print(f"主題    : {mail.subject}")
    for enc in mail.encodings:
        print(f"內文編碼: {enc}  (已解碼)")
    print("-" * 70)
    print(mail.body if mail.body else "(沒有文字內容)")
    print("-" * 70)
    if mail.attachments:
        print("附件:")
        for att in mail.attachments:
            print(f"  - {att.filename}  ({att.content_type}, {human_size(len(att.data))})")


def ask_number(prompt):
    s = input(prompt).strip()
    if not s.isdigit():
        print("請輸入正整數編號。")
        return None
    return int(s)


MENU = """
=============== POP3 Mail Client ===============
 1. 顯示信箱中有幾封信
 2. 列出所有信件 (寄信時間 / 主題 / 寄件人 / 收件人)
 3. 閱讀第 n 封信
 4. 刪除第 n 封信
 5. 取消所有刪除 (RSET)
 6. 搜尋信件 (主題 / 寄件人 / 收件人)
 7. 儲存第 n 封信 (.eml) 與附件
 8. 檢視第 n 封信原始內容 (raw source)
 0. 離開 (QUIT，刪除在此時才會生效)
================================================"""
SHORT_MENU = ("\n[1]信件數 [2]信件列表 [3]閱讀 [4]刪除 [5]取消刪除 [6]搜尋 [7]儲存 "
              "[8]原始內容 [h]選單 [0]離開")


def run_cli(args):
    if not args.server:
        print("Usage: python3 pop3client.py ServerIP [-p PORT] [--ssl] [-v] [--gui]")
        sys.exit(1)

    client = POP3Client(args.server, args.port, args.ssl, verbose=args.verbose)
    try:
        greeting = client.connect()
        print(f"Receive message: {greeting}")
    except (OSError, POP3Error) as e:
        print(f"連線失敗: {e}")
        sys.exit(1)

    name = args.user or input("Username: ")
    password = getpass("Password: ")
    try:
        print(f"Receive message: {client.login(name, password)}")
    except POP3Error as e:
        print(f"登入失敗: {e}")
        client.close()
        sys.exit(1)

    box = MailBox(client)
    print(MENU)
    try:
        while True:
            print(SHORT_MENU)
            choice = input("請選擇功能: ").strip().lower()
            try:
                if choice == "1":
                    count, size = box.count()
                    print(f"\n信箱中共有 {count} 封信，總大小 {human_size(size)}")
                    if box.deleted:
                        print(f"(另有 {len(box.deleted)} 封信已標記刪除: "
                              f"{sorted(box.deleted)})")
                elif choice == "2":
                    print()
                    print_summaries(box.summaries())
                elif choice == "3":
                    num = ask_number("要閱讀第幾封信? ")
                    if num is not None:
                        print_mail(box.read(num))
                elif choice == "4":
                    num = ask_number("要刪除第幾封信? ")
                    if num is not None:
                        ok = input(f"確定要刪除第 {num} 封信? (y/N) ").strip().lower()
                        if ok == "y":
                            print(f"Receive message: {box.delete(num)}")
                            print(f"第 {num} 封信已標記刪除，離開 (QUIT) 時才會真正從伺服器刪除。")
                        else:
                            print("已取消。")
                elif choice == "5":
                    print(f"Receive message: {box.undelete_all()}")
                    print("所有標記刪除的信件都已復原。")
                elif choice == "6":
                    kw = input("請輸入關鍵字: ").strip()
                    if kw:
                        print()
                        print_summaries(box.search(kw))
                elif choice == "7":
                    num = ask_number("要儲存第幾封信? ")
                    if num is not None:
                        for p in box.save(num, args.save_dir):
                            print(f"已儲存: {p}")
                elif choice == "8":
                    num = ask_number("要檢視第幾封信的原始內容? ")
                    if num is not None:
                        print(box.client.retr(num).decode("utf-8", errors="replace"))
                elif choice == "0":
                    break
                elif choice == "h":
                    print(MENU)
                else:
                    print("無此選項，請重新輸入。")
                    print(MENU)
            except POP3Error as e:
                print(f"伺服器回應錯誤: {e}")
    except (KeyboardInterrupt, EOFError):
        print()
    except (OSError, ConnectionError) as e:
        print(f"Socket error: {e}")
        client.close()
        print("Connection closed.")
        return

    try:
        print(f"Receive message: {box.quit()}")
    except (OSError, POP3Error) as e:
        print(f"QUIT 失敗: {e}")
    print("Connection closed.")


# ============================================================
#  圖形介面 (GUI, tkinter)
# ============================================================
def run_gui(args):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("POP3 Mail Client")
    root.geometry("1100x720")
    state = {"box": None, "rows": [], "sort": ("num", False), "current": None}

    # ---------------- 登入畫面 ----------------
    login = ttk.Frame(root, padding=30)
    login.pack(expand=True)
    ttk.Label(login, text="POP3 Mail Client", font=("TkDefaultFont", 18, "bold")) \
        .grid(row=0, column=0, columnspan=2, pady=(0, 20))
    v_host = tk.StringVar(value=args.server or DEFAULT_SERVER)
    v_port = tk.StringVar(value=str(args.port or ""))
    v_ssl = tk.BooleanVar(value=args.ssl)
    v_user = tk.StringVar(value=args.user or DEFAULT_USER)
    v_pass = tk.StringVar()
    fields = [("POP3 伺服器", v_host, None), ("Port (空白=預設)", v_port, None),
              ("帳號", v_user, None), ("密碼", v_pass, "*")]
    for i, (label, var, show) in enumerate(fields, start=1):
        ttk.Label(login, text=label).grid(row=i, column=0, sticky="e", padx=6, pady=4)
        e = ttk.Entry(login, textvariable=var, width=32, show=show or "")
        e.grid(row=i, column=1, pady=4)
    ttk.Checkbutton(login, text="使用 SSL (POP3S)", variable=v_ssl) \
        .grid(row=5, column=1, sticky="w", pady=4)
    login_btn = ttk.Button(login, text="登入")
    login_btn.grid(row=6, column=0, columnspan=2, pady=12)

    # ---------------- 主畫面 ----------------
    main = ttk.Frame(root)
    toolbar = ttk.Frame(main, padding=(6, 6))
    toolbar.pack(fill="x")
    status = tk.StringVar(value="")
    ttk.Label(main, textvariable=status, anchor="w", relief="sunken", padding=(6, 2)) \
        .pack(side="bottom", fill="x")

    panes = ttk.PanedWindow(main, orient="vertical")
    panes.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    list_frame = ttk.Frame(panes)
    cols = ("num", "date", "subject", "sender", "to", "size")
    titles = {"num": "No.", "date": "寄信時間", "subject": "主題",
              "sender": "寄件人", "to": "收件人", "size": "大小"}
    widths = {"num": 45, "date": 165, "subject": 320, "sender": 230, "to": 230, "size": 75}
    tree = ttk.Treeview(list_frame, columns=cols, show="headings", selectmode="browse")
    for c in cols:
        tree.heading(c, text=titles[c], command=lambda c=c: sort_by(c))
        tree.column(c, width=widths[c], anchor="center" if c in ("num", "size") else "w",
                    stretch=c in ("subject", "sender", "to"))
    tree.tag_configure("deleted", foreground="gray60")
    ysb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.pack(side="left", fill="both", expand=True)
    ysb.pack(side="right", fill="y")
    panes.add(list_frame, weight=2)

    view = ttk.Frame(panes)
    head = tk.Text(view, height=6, wrap="word", relief="flat", background="#f4f6fa")
    head.pack(fill="x")
    body = ScrolledText(view, wrap="word")
    body.pack(fill="both", expand=True)
    head.tag_configure("key", font=("TkDefaultFont", 10, "bold"))
    for w in (head, body):
        w.configure(state="disabled")
    panes.add(view, weight=3)

    v_search = tk.StringVar()

    def busy(fn):
        """執行網路操作時顯示忙碌游標，並統一處理錯誤。"""
        def wrapper(*a):
            root.config(cursor="watch")
            root.update_idletasks()
            try:
                return fn(*a)
            except POP3Error as e:
                messagebox.showerror("伺服器錯誤", str(e))
            except (OSError, ConnectionError) as e:
                messagebox.showerror("連線錯誤", f"{e}\n\n請重新啟動程式並登入。")
            finally:
                root.config(cursor="")
        return wrapper

    def set_text(widget, chunks):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in chunks:
            widget.insert("end", text, tag)
        widget.configure(state="disabled")

    def update_status():
        box = state["box"]
        count, size = box.count()
        msg = f"信箱中共有 {count} 封信，總大小 {human_size(size)}"
        if box.deleted:
            msg += f"　｜　已標記刪除 {len(box.deleted)} 封 (離開時生效)"
        status.set(msg)

    def fill_tree():
        kw = v_search.get().strip().lower()
        key, reverse = state["sort"]
        rows = [r for r in state["rows"]
                if not kw or kw in r.subject.lower() or kw in r.sender.lower()
                or kw in r.to.lower()]
        rows.sort(key=lambda r: getattr(r, key), reverse=reverse)
        tree.delete(*tree.get_children())
        for r in rows:
            deleted = r.num in state["box"].deleted
            subject = ("[已刪除] " if deleted else "") + r.subject
            tree.insert("", "end", iid=str(r.num), tags=("deleted",) if deleted else (),
                        values=(r.num, r.date, subject, r.sender, r.to, human_size(r.size)))

    def sort_by(col):
        key = {"size": "size", "num": "num"}.get(col, col)
        cur, rev = state["sort"]
        state["sort"] = (key, not rev if cur == key else False)
        fill_tree()

    @busy
    def refresh():
        box = state["box"]
        alive = box.summaries()
        known = {r.num: r for r in state["rows"]}
        for r in alive:
            known[r.num] = r
        # 已標記刪除的信 LIST 不會列出，但仍留在列表中以灰色顯示
        state["rows"] = sorted(known.values(), key=lambda r: r.num)
        fill_tree()
        update_status()

    def selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("提示", "請先在列表中選擇一封信。")
            return None
        return int(sel[0])

    @busy
    def open_mail(_event=None):
        sel = tree.selection()
        if not sel:
            return
        num = int(sel[0])
        if num in state["box"].deleted:
            set_text(head, [(f"第 {num} 封信已標記刪除。", "key")])
            set_text(body, [])
            return
        mail = state["box"].read(num)
        state["current"] = mail
        chunks = []
        for k, v in (("寄信時間", mail.date), ("寄件人", mail.sender), ("收件人", mail.to),
                     ("副本", mail.cc), ("主題", mail.subject)):
            if v:
                chunks += [(f"{k}：", "key"), (v + "\n", None)]
        if mail.encodings:
            chunks += [("內文編碼：", "key"), ("、".join(mail.encodings) + " (已解碼)\n", None)]
        if mail.attachments:
            names = "、".join(f"{a.filename} ({human_size(len(a.data))})"
                             for a in mail.attachments)
            chunks += [("附件：", "key"), (names, None)]
        set_text(head, chunks)
        set_text(body, [(mail.body or "(沒有文字內容)", None)])

    @busy
    def delete_mail():
        num = selected()
        if num is None or num in state["box"].deleted:
            return
        if messagebox.askyesno("刪除信件", f"確定要刪除第 {num} 封信?\n(離開程式時才會真正從伺服器刪除)"):
            state["box"].delete(num)
            fill_tree()
            update_status()

    @busy
    def undelete():
        state["box"].undelete_all()
        fill_tree()
        update_status()

    @busy
    def save_mail():
        num = selected()
        if num is None:
            return
        folder = filedialog.askdirectory(title="選擇儲存資料夾")
        if folder:
            paths = state["box"].save(num, folder)
            messagebox.showinfo("儲存完成", "已儲存:\n" + "\n".join(paths))

    @busy
    def view_source():
        num = selected()
        if num is None:
            return
        raw = state["box"].client.retr(num).decode("utf-8", errors="replace")
        win = tk.Toplevel(root)
        win.title(f"第 {num} 封信原始內容")
        win.geometry("800x600")
        txt = ScrolledText(win, wrap="none", font=("TkFixedFont", 10))
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", raw)
        txt.configure(state="disabled")

    for text, cmd in (("重新整理", refresh), ("刪除", delete_mail), ("取消刪除 (RSET)", undelete),
                      ("儲存信件/附件", save_mail), ("檢視原始碼", view_source)):
        ttk.Button(toolbar, text=text, command=cmd).pack(side="left", padx=3)
    ttk.Entry(toolbar, textvariable=v_search, width=24).pack(side="right", padx=3)
    ttk.Label(toolbar, text="搜尋:").pack(side="right")
    v_search.trace_add("write", lambda *a: fill_tree())
    tree.bind("<<TreeviewSelect>>", open_mail)
    tree.bind("<Delete>", lambda e: delete_mail())

    @busy
    def do_login(_event=None):
        host = v_host.get().strip()
        if not host:
            messagebox.showwarning("登入", "請輸入 POP3 伺服器位址。")
            return
        port = int(v_port.get()) if v_port.get().strip().isdigit() else None
        client = POP3Client(host, port, v_ssl.get(), verbose=args.verbose)
        try:
            client.connect()
            client.login(v_user.get().strip(), v_pass.get())
        except Exception:
            client.close()
            raise
        state["box"] = MailBox(client)
        root.title(f"POP3 Mail Client - {v_user.get()}@{host}")
        login.pack_forget()
        main.pack(fill="both", expand=True)
        refresh()

    login_btn.configure(command=do_login)
    root.bind("<Return>", lambda e: do_login() if state["box"] is None else None)

    def on_close():
        box = state["box"]
        if box is None:
            root.destroy()
            return
        if box.deleted:
            ans = messagebox.askyesnocancel(
                "離開", f"有 {len(box.deleted)} 封信已標記刪除。\n"
                        "是：確認刪除並離開\n否：取消刪除並離開\n取消：返回")
            if ans is None:
                return
            if ans is False:
                try:
                    box.undelete_all()
                except Exception:
                    pass
        try:
            box.quit()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Simple POP3 mail client")
    parser.add_argument("server", nargs="?", help="POP3 伺服器 IP 或網域名稱")
    parser.add_argument("-p", "--port", type=int, help="port (預設 110，SSL 為 995)")
    parser.add_argument("-u", "--user", help="帳號 (未指定則執行時詢問)")
    parser.add_argument("--ssl", action="store_true", help="使用 POP3 over SSL")
    parser.add_argument("-v", "--verbose", action="store_true", help="顯示 POP3 協定對話")
    parser.add_argument("--gui", action="store_true", help="以圖形介面執行")
    parser.add_argument("--save-dir", default="mails", help="儲存信件/附件的資料夾")
    args = parser.parse_args()

    # 指定 --gui，或沒有給伺服器位址 (例如直接雙擊程式) 時，開啟圖形介面
    if args.gui or not args.server:
        try:
            run_gui(args)
        except ImportError:
            print("找不到 tkinter，無法開啟圖形介面，請改用文字模式:")
            print("  python3 pop3client.py ServerIP")
            sys.exit(1)
    else:
        run_cli(args)


if __name__ == '__main__':
    main()
