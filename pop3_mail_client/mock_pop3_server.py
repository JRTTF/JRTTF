####################################################
#  Network Programming - Unit 3 Application based on TCP
#  Program Name: mock_pop3_server.py
#  一個簡易的 POP3 測試伺服器 (RFC 1939 子集)，信箱內預先放入幾封
#  不同編碼的測試信 (UTF-8/Big5、Base64/Quoted-Printable、HTML、附件)，
#  方便在沒有真實郵件伺服器時測試 pop3client.py。
#
#  另外在 port 2525 提供簡易 SMTP，寄來的信會直接放進同一個信箱。
#
#  Usage: python3 mock_pop3_server.py [port]      (預設 POP3 port 1100，SMTP port 2525)
#         帳號: test   密碼: 1234
#  2026.10.05
####################################################
import base64
import socketserver
import sys
import threading
from email.charset import Charset, BASE64, QP
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

USER, PASSWORD = "test", "1234"


def _text(body, charset, cte):
    cs = Charset(charset)
    cs.body_encoding = cte
    return MIMEText(body, "plain", cs)


def _addr(name, addr, charset="utf-8"):
    return formataddr((name, addr), charset)


def _big5(text):
    """產生 Big5 + Base64 的 RFC 2047 編碼字串，例如 =?big5?B?...?="""
    return f"=?big5?B?{base64.b64encode(text.encode('big5')).decode()}?="


def build_mails():
    mails = []

    # 1. 純英文 7bit 信件
    m = MIMEText("Hi,\n\nThis is a plain ASCII test mail.\n.Line starting with a dot.\n\nBye.")
    m["From"] = "Alice <alice@example.com>"
    m["To"] = "test@example.com"
    m["Subject"] = "Hello from Alice"
    m["Date"] = "Mon, 28 Sep 2026 09:15:22 +0800"
    mails.append(m)

    # 2. 中文主旨 (UTF-8 Base64) + 內文 Base64
    m = _text("同學好：\n\n本週的網路程式設計作業是撰寫 POP3 Mail Client，\n"
              "請於下週一前上傳 iLearn。\n\n助教 敬上", "utf-8", BASE64)
    m["From"] = _addr("網路程式設計助教", "ta@nps.example.edu.tw")
    m["To"] = _addr("測試同學", "test@example.com")
    m["Subject"] = Header("【公告】POP3 作業繳交說明", "utf-8")
    m["Date"] = "Wed, 30 Sep 2026 14:03:10 +0800"
    mails.append(m)

    # 3. Big5 主旨 + 內文 Quoted-Printable
    m = _text("您好：\n\n這封信使用 Big5 編碼與 Quoted-Printable 傳輸編碼，\n"
              "用來測試信件解碼功能是否正確。\n\n系統管理員", "big5", QP)
    m["From"] = f"{_big5('系統管理員')} <admin@example.com>"
    m["To"] = f"{_big5('測試同學')} <test@example.com>"
    m["Cc"] = "bob@example.com"
    m["Subject"] = _big5("Big5 編碼測試信")
    m["Date"] = "Thu, 01 Oct 2026 08:30:00 +0800"
    mails.append(m)

    # 4. multipart：純文字 + HTML + 附件
    m = MIMEMultipart("mixed")
    alt = MIMEMultipart("alternative")
    alt.attach(_text("附件是期中考範圍，請參考。\n\n王老師", "utf-8", BASE64))
    alt.attach(MIMEText("<p>附件是<b>期中考範圍</b>，請參考。</p><p>王老師</p>", "html", "utf-8"))
    m.attach(alt)
    att = MIMEApplication("第 1 章 ~ 第 5 章\nTCP/UDP Socket Programming\n".encode("utf-8"),
                          _subtype="octet-stream")
    att.add_header("Content-Disposition", "attachment", filename=("utf-8", "", "期中考範圍.txt"))
    m.attach(att)
    m["From"] = _addr("王老師", "wang@nps.example.edu.tw")
    m["To"] = ", ".join([_addr("測試同學", "test@example.com"), "classmate@example.com"])
    m["Subject"] = Header("期中考範圍 (含附件)", "utf-8")
    m["Date"] = "Fri, 02 Oct 2026 16:45:31 +0800"
    mails.append(m)

    # 5. 只有 HTML 內文
    m = MIMEText("<html><body><h2>電子報 10 月號</h2><p>本月主題：<i>Socket 程式設計</i>"
                 "</p><ul><li>TCP 三向交握</li><li>POP3 / SMTP 協定</li></ul></body></html>",
                 "html", "utf-8")
    m["From"] = _addr("系電子報", "news@example.com")
    m["To"] = "test@example.com"
    m["Subject"] = Header("系電子報 10 月號", "utf-8")
    m["Date"] = "Sun, 04 Oct 2026 20:00:00 +0800"
    mails.append(m)

    return [msg.as_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") for msg in mails]


MAILBOX = build_mails()
LOCK = threading.Lock()


class POP3Handler(socketserver.StreamRequestHandler):
    def send(self, line):
        self.wfile.write(line.encode("utf-8") + b"\r\n")

    def send_multi(self, data):
        for line in data.split(b"\r\n"):
            if line.startswith(b"."):
                line = b"." + line         # dot-stuffing
            self.wfile.write(line + b"\r\n")
        self.wfile.write(b".\r\n")

    def handle(self):
        print(f"[+] connection from {self.client_address}")
        self.send("+OK Mock POP3 server ready")
        user, authed, deleted = None, False, set()

        def get(arg):
            try:
                n = int(arg)
            except (TypeError, ValueError):
                return None
            if 1 <= n <= len(MAILBOX) and n not in deleted:
                return n
            return None

        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            parts = raw.decode("utf-8", "replace").strip().split()
            if not parts:
                continue
            cmd, args = parts[0].upper(), parts[1:]
            print(f"    C: {cmd} {' '.join(args) if cmd != 'PASS' else '****'}")

            if cmd == "QUIT":
                with LOCK:
                    for n in sorted(deleted, reverse=True):
                        del MAILBOX[n - 1]
                self.send(f"+OK Bye ({len(deleted)} messages deleted)")
                break
            if cmd == "CAPA":
                self.send("+OK Capability list follows")
                self.send_multi(b"USER\r\nTOP\r\nUIDL")
            elif not authed:
                if cmd == "USER" and args:
                    user = args[0]
                    self.send(f"+OK User {user} accepted")
                elif cmd == "PASS" and user == USER and args and args[0] == PASSWORD:
                    authed = True
                    self.send(f"+OK Logged in, {len(MAILBOX)} messages")
                else:
                    self.send("-ERR Authentication failed")
            elif cmd == "STAT":
                alive = [i for i in range(1, len(MAILBOX) + 1) if i not in deleted]
                self.send(f"+OK {len(alive)} {sum(len(MAILBOX[i - 1]) for i in alive)}")
            elif cmd == "LIST":
                if args:
                    n = get(args[0])
                    self.send(f"+OK {n} {len(MAILBOX[n - 1])}" if n else "-ERR No such message")
                else:
                    alive = [i for i in range(1, len(MAILBOX) + 1) if i not in deleted]
                    self.send(f"+OK {len(alive)} messages")
                    self.send_multi("\r\n".join(f"{i} {len(MAILBOX[i - 1])}"
                                                for i in alive).encode())
            elif cmd == "UIDL":
                alive = [i for i in range(1, len(MAILBOX) + 1) if i not in deleted]
                self.send("+OK")
                self.send_multi("\r\n".join(f"{i} uid{abs(hash(MAILBOX[i - 1]))}"
                                            for i in alive).encode())
            elif cmd in ("RETR", "TOP"):
                n = get(args[0] if args else None)
                if not n:
                    self.send("-ERR No such message")
                    continue
                data = MAILBOX[n - 1].rstrip(b"\r\n")
                if cmd == "TOP":
                    nlines = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
                    head, _, body = data.partition(b"\r\n\r\n")
                    data = head + b"\r\n" + b"".join(
                        b"\r\n" + line for line in body.split(b"\r\n")[:nlines])
                self.send(f"+OK {len(MAILBOX[n - 1])} octets")
                self.send_multi(data)
            elif cmd == "DELE":
                n = get(args[0] if args else None)
                if n:
                    deleted.add(n)
                    self.send(f"+OK Message {n} deleted")
                else:
                    self.send("-ERR No such message")
            elif cmd == "RSET":
                deleted.clear()
                self.send("+OK")
            elif cmd == "NOOP":
                self.send("+OK")
            else:
                self.send("-ERR Unknown command")
        print(f"[-] connection closed {self.client_address}")


class SMTPHandler(socketserver.StreamRequestHandler):
    """極簡 SMTP：收下任何收件人的信，放進 MAILBOX。"""
    def send(self, line):
        self.wfile.write(line.encode("utf-8") + b"\r\n")

    def handle(self):
        print(f"[+] SMTP connection from {self.client_address}")
        self.send("220 Mock SMTP server ready")
        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            cmd = line[:4].upper()
            print(f"    C: {line}")
            if cmd == "EHLO":
                self.send("250-mock.local Hello")
                self.send("250 8BITMIME")
            elif cmd == "HELO":
                self.send("250 mock.local Hello")
            elif cmd in ("MAIL", "RCPT", "RSET", "NOOP"):
                self.send("250 OK")
            elif cmd == "DATA":
                self.send("354 End data with <CR><LF>.<CR><LF>")
                lines = []
                while True:
                    data = self.rfile.readline().rstrip(b"\r\n")
                    if data == b".":
                        break
                    lines.append(data[1:] if data.startswith(b"..") else data)
                with LOCK:
                    MAILBOX.append(b"\r\n".join(lines) + b"\r\n")
                self.send(f"250 OK: queued as {len(MAILBOX)}")
            elif cmd == "QUIT":
                self.send("221 Bye")
                break
            else:
                self.send("502 Command not implemented")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1100
    smtp = Server(("0.0.0.0", 2525), SMTPHandler)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    with Server(("0.0.0.0", port), POP3Handler) as srv:
        print(f"Mock POP3 server listening on port {port}  (user={USER}, pass={PASSWORD})")
        print("Mock SMTP server listening on port 2525")
        srv.serve_forever()
