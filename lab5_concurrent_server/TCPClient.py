####################################################
#  Network Programming - Unit 5 Concurrent Process
#  Program Name: TCPClient.py
#  學號 (Student ID): D1211110
#  姓名 (Name)      : 陳嘉希
#
#  Lab 2 / Lab 5 的 Client 程式 (修改自範例 5-TCPClient.py)
#    1. 從命令列輸入一個大於 0 的整數 n，將 n-1 傳給 Server 開始通訊
#    2. 收到 Server 傳來的整數 k 時印出 k；若 k > 0 回傳 k-1
#    3. 收到 0 時結束連線並送出 "END" 通知 Server；
#       Server 收到 0 時會送 "END" 過來，Client 收到後結束
#
#  加分功能：
#    - -d 秒數：每次回傳前延遲，方便同時開多個 Client 觀察 Server 並行處理
#    - --gui：圖形介面，可一次啟動多個 Client 同時連線 (每個 Client 一個 thread)
#
#  Usage: python TCPClient.py ServerIP [n] [-p PORT] [-d DELAY]
#         python TCPClient.py --gui
#  2026.10.19
####################################################
import argparse
import socket
import sys
import threading
import time


# 設定要連線的目標遠端 TCP 伺服器連接埠 (Port)
PORT = 6666
# 設定每次接收資料的最大緩衝區大小 (1024 位元組)
BUF_SIZE = 1024			# Receive buffer size
END_MSG = "END"


class LineSocket:
	"""TCP 是位元組串流，這裡以「一行一則訊息」切出完整的訊息。"""
	def __init__(self, sock):
		self.sock = sock
		self.buf = b""

	def send(self, text):
		self.sock.sendall((text + "\n").encode("utf-8"))

	def recv(self):
		while b"\n" not in self.buf:
			data = self.sock.recv(BUF_SIZE)
			if not data:
				return None
			self.buf += data
		line, self.buf = self.buf.split(b"\n", 1)
		return line.decode("utf-8").strip()


def run_client(server, port, n, delay=0.0, out=print):
	"""執行一次完整的 Lab 2 通訊。out 用來輸出訊息 (CLI 用 print，GUI 用自訂函式)。"""
	# 透過網址或 IP 字串解析出正確的目標主機 IP 位址 (DNS 解析)
	serverIP = socket.gethostbyname(server)
	# 建立一個基於 IPv4 (AF_INET) 的 TCP (SOCK_STREAM) 客戶端通訊套接字 (Socket)
	cSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	out(f"Connecting to {serverIP} port {port}")
	cSocket.connect((serverIP, port))			# 向目標伺服器發起三向交握連線要求
	conn = LineSocket(cSocket)
	try:
		out(f"輸入的整數 n = {n}，送出 n-1 = {n - 1}")
		conn.send(str(n - 1))					# 發起訊息傳送：將 n 減一傳給 Server
		while True:
			msg = conn.recv()
			if msg is None:
				out("Server 已關閉連線")
				break
			if msg == END_MSG:					# Server 收到 0，通知 Client 結束
				out("收到 END，Server 通知結束")
				break
			value = int(msg)
			out(f"Receive: {value}")
			if value == 0:						# 收到 0 的一方結束，並通知對方
				conn.send(END_MSG)
				out("收到 0，送出 END 通知 Server 結束")
				break
			if delay:
				time.sleep(delay)
			conn.send(str(value - 1))			# 將收到的值減一回傳
	except socket.error as e:
		# 專門捕捉網路通訊層面的 Socket 相關異常（例如中途斷線或連線被拒絕）
		out(f"Socket error: {e}")
	except ValueError:
		out("收到無法辨識的訊息，結束連線")
	finally:
		out("Closing connection.")
		cSocket.close()


def ask_positive(text):
	"""檢查輸入是否為大於 0 的整數，不是則回傳 None。"""
	try:
		n = int(text)
		return n if n > 0 else None
	except (TypeError, ValueError):
		return None


# ============================================================
#  加分：GUI，可同時啟動多個 Client
# ============================================================
def run_gui(args):
	import queue
	import tkinter as tk
	from tkinter import ttk, messagebox
	from tkinter.scrolledtext import ScrolledText

	root = tk.Tk()
	root.title("Lab 5 TCP Client")
	root.geometry("760x520")
	events = queue.Queue()

	form = ttk.Frame(root, padding=8)
	form.pack(fill="x")
	v_host = tk.StringVar(value=args.server or "127.0.0.1")
	v_port = tk.StringVar(value=str(args.port))
	v_n = tk.StringVar(value=str(args.n or 5))
	v_count = tk.StringVar(value="3")
	v_delay = tk.StringVar(value=str(args.delay or 1))
	fields = (("Server IP", v_host, 16), ("Port", v_port, 6), ("整數 n (>0)", v_n, 6),
			  ("同時連線的 Client 數", v_count, 4), ("每步延遲 (秒)", v_delay, 4))
	for i, (label, var, w) in enumerate(fields):
		ttk.Label(form, text=label).grid(row=i // 3, column=(i % 3) * 2, sticky="e", padx=4, pady=3)
		ttk.Entry(form, textvariable=var, width=w).grid(row=i // 3, column=(i % 3) * 2 + 1, sticky="w")

	logs = {}
	tabs = ttk.Notebook(root)

	def start():
		n = ask_positive(v_n.get())
		if n is None:
			messagebox.showwarning("輸入錯誤", "請輸入大於 0 的整數 n")
			return
		try:
			count = max(1, int(v_count.get()))
			port = int(v_port.get())
			delay = float(v_delay.get() or 0)
		except ValueError:
			messagebox.showwarning("輸入錯誤", "Port、Client 數、延遲必須是數字")
			return
		for _ in range(count):
			cid = f"Client {len(logs) + 1}"
			box = ScrolledText(tabs, font=("TkFixedFont", 10))
			tabs.add(box, text=cid)
			logs[cid] = box
			out = lambda msg, cid=cid: events.put((cid, msg))
			# 每個 Client 一個 thread，讓多個 Client 同時連線到 Server
			threading.Thread(target=client_thread, args=(cid, v_host.get(), port, n, delay, out),
							 daemon=True).start()

	def client_thread(cid, host, port, n, delay, out):
		try:
			run_client(host, port, n, delay, out)
		except OSError as e:
			out(f"連線失敗: {e}")
		out("__DONE__")

	def poll():
		while not events.empty():
			cid, msg = events.get()
			if msg == "__DONE__":
				tabs.tab(logs[cid], text=f"{cid} ✓")
				continue
			logs[cid].insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
			logs[cid].see("end")
		root.after(100, poll)

	ttk.Button(form, text="連線並開始", command=start).grid(row=1, column=5, sticky="w", padx=4)
	tabs.pack(fill="both", expand=True, padx=8, pady=8)
	root.after(100, poll)
	root.mainloop()


def main():
	parser = argparse.ArgumentParser(description="Lab 5 TCP Client")
	parser.add_argument("server", nargs="?", help="Server IP 或網域名稱")
	parser.add_argument("n", nargs="?", help="大於 0 的整數 (未指定則執行時輸入)")
	parser.add_argument("-p", "--port", type=int, default=PORT, help=f"Server port (預設 {PORT})")
	parser.add_argument("-d", "--delay", type=float, default=0.0, help="每次回傳前延遲的秒數")
	parser.add_argument("--gui", action="store_true", help="以圖形介面執行")
	args = parser.parse_args()

	if args.gui:
		run_gui(args)
		return
	# 檢查命令列參數長度是否足夠
	if not args.server:
		print("Usage: python TCPClient.py ServerIP [n] [-p PORT] [-d DELAY]")
		sys.exit(1)

	n = ask_positive(args.n) if args.n else None
	while n is None:							# 從命令列輸入一個大於 0 的整數
		n = ask_positive(input("請輸入一個大於 0 的整數: "))
		if n is None:
			print("輸入錯誤，必須是大於 0 的整數。")
	try:
		run_client(args.server, args.port, n, args.delay)
	except OSError as e:
		print(f"連線失敗: {e}")
# end of main


if __name__ == '__main__':
	main()
