####################################################
#  Network Programming - Unit 5 Concurrent Process
#  Program Name: TCPServer.py
#  學號 (Student ID): D1211110
#  姓名 (Name)      : 陳嘉希
#
#  Lab 5 任務一：Concurrent Server (修改自 Lab 2 的 Server 與範例 5-TCPServer.py)
#  Server 的 main thread 收到 Client 的連線後，立即產生一個新的 thread
#  (ServerThread) 與該 Client 溝通，main thread 則回去繼續等待新的連線，
#  因此可以同時服務多個 Client。
#
#  Lab 2 通訊規則 (每個 thread 與自己的 Client 之間)：
#    1. Client 送出 n-1 開始
#    2. 收到整數 k 的一方印出 k；若 k > 0 回傳 k-1 給對方
#    3. 收到 0 的一方結束連線，並送出 "END" 通知對方也結束
#    訊息格式：每則訊息一行，例如 "4\n"、"END\n"
#
#  加分功能：
#    - 列印時以 Lock 保護，多個 thread 同時輸出不會交錯
#    - 即時顯示目前連線數 / 已服務的 Client 總數 (以 Lock 保護的共享計數器)
#    - -d 秒數：每次回傳前延遲，方便觀察多個 Client 同時進行
#    - --gui：以 tkinter 圖形介面即時顯示每個連線 thread 的狀態與紀錄
#
#  Usage: python TCPServer.py [-p PORT] [-d DELAY] [--gui]
#  2026.10.19
####################################################
import argparse
import socket
import threading
import time
from datetime import datetime


# 設定伺服器監聽的連接埠 (Port) 與等待佇列最大長度 (backlog)
PORT = 6666
backlog = 5
# 設定每次接收資料的最大緩衝區大小 (1024 位元組)
BUF_SIZE = 1024			# Receive buffer size
END_MSG = "END"			# 收到 0 的一方送出此訊息，通知對方結束


# ---------- 多個 thread 共用的資源，以 Lock 保護 (臨界區) ----------
print_lock = threading.Lock()
stats_lock = threading.Lock()
stats = {"active": 0, "total": 0}


def log(msg):
	"""加上時間後印出；用 Lock 避免多個 thread 的輸出互相交錯。"""
	with print_lock:
		print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def update_stats(delta):
	"""連線數 +1 / -1，回傳 (目前連線數, 累計服務數)。"""
	with stats_lock:
		stats["active"] += delta
		if delta > 0:
			stats["total"] += 1
		return stats["active"], stats["total"]


class LineSocket:
	"""TCP 是位元組串流，這裡以「一行一則訊息」切出完整的訊息。"""
	def __init__(self, sock):
		self.sock = sock
		self.buf = b""

	def send(self, text):
		self.sock.sendall((text + "\n").encode("utf-8"))

	def recv(self):
		"""收到一則訊息 (字串)；對方關閉連線時回傳 None。"""
		while b"\n" not in self.buf:
			data = self.sock.recv(BUF_SIZE)
			if not data:
				return None
			self.buf += data
		line, self.buf = self.buf.split(b"\n", 1)
		return line.decode("utf-8").strip()


# 定義一個專門處理個別客戶端連線的執行緒類別
class ServerThread(threading.Thread):
	def __init__(self, t_name, client_sc, rip, rport, delay=0.0, monitor=None):
		# 呼叫父類別 (Thread) 的建構子並指派執行緒名稱；設為 daemon，Server 結束時一併結束
		super().__init__(name=t_name, daemon=True)
		self.client = client_sc		# 客戶端的 Socket 物件
		self.rip = rip				# 客戶端遠端 IP
		self.rport = rport			# 客戶端遠端 Port
		self.delay = delay			# 每次回傳前的延遲秒數 (觀察並行用)
		self.monitor = monitor		# GUI 監看介面 (可為 None)
		self.start()				# 物件一建立就立刻啟動執行緒 (同範例 5-TCPServer.py)
	# end for __init__()

	def report(self, status, value=None, text=None):
		"""印出訊息，並在有 GUI 時同步更新畫面。"""
		name = self.name
		if text:
			log(f"{name} ({self.rip}:{self.rport}) {text}")
		if self.monitor:
			self.monitor.update(name, f"{self.rip}:{self.rport}", status, value, text)

	def run(self):
		active, total = update_stats(+1)
		self.report("連線中", text=f"開始服務 (目前連線數: {active}, 累計: {total})")
		conn = LineSocket(self.client)
		try:
			while True:
				msg = conn.recv()
				if msg is None:							# 對方未送 END 就斷線
					self.report("對方已斷線", text="Client 已關閉連線")
					break
				if msg == END_MSG:						# 對方收到 0，通知我們結束
					self.report("結束", text="收到 END，Client 通知結束")
					break
				try:
					value = int(msg)
				except ValueError:
					self.report("錯誤", text=f"收到無法辨識的訊息: {msg!r}，結束連線")
					break

				self.report("通訊中", value, f"Receive: {value}")
				if value == 0:							# 收到 0 的一方結束，並通知對方
					conn.send(END_MSG)
					self.report("結束", 0, "收到 0，送出 END 通知 Client 結束")
					break
				if self.delay:
					time.sleep(self.delay)
				conn.send(str(value - 1))				# 將收到的值減一回傳
		except OSError as e:
			self.report("錯誤", text=f"Socket error: {e}")
		finally:
			# 關閉該客戶端的通訊通口，釋放連線資源
			self.client.close()
			active, _ = update_stats(-1)
			log(f"{self.name} closed (目前連線數: {active})")
	# end run()
# end for ServerThread


def serve(port, delay, monitor=None, stop_event=None):
	"""main thread：不斷 accept 新連線，每個連線交給一個新的 ServerThread。"""
	# 建立一個基於 IPv4 (AF_INET) 的 TCP (SOCK_STREAM) 監聽套接字 (Socket)
	srvSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	# 啟用 Socket 埠號重用機制，防止伺服器重啟時出現 Address already in use
	srvSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	srvSocket.bind(('', port))
	srvSocket.listen(backlog)
	# accept() 每秒逾時一次，讓 Ctrl+C (Windows) 與 GUI 關閉能即時結束
	srvSocket.settimeout(1.0)
	log(f"Starting up server on port: {port}  (按 Ctrl+C 結束)")

	count = 0
	try:
		while not (stop_event and stop_event.is_set()):
			log(f"Number of threads: {threading.active_count()}，Waiting for client connection...")
			while True:
				try:
					client, (rip, rport) = srvSocket.accept()	# 阻塞等待客戶端連線
					break
				except socket.timeout:
					if stop_event and stop_event.is_set():
						return
			client.settimeout(None)		# 與 Client 通訊的 socket 使用一般的阻塞模式
			count += 1
			t_name = f"Thread {count}"
			log(f"Got connection from {rip}:{rport}. Create thread: {t_name}")
			ServerThread(t_name, client, rip, rport, delay, monitor)	# 一建立就自動 start()
			# main thread 不等這個 Client 結束，直接回到迴圈開頭等待下一個連線
	except KeyboardInterrupt:
		log("Server 結束")
	finally:
		srvSocket.close()
# end of serve


# ============================================================
#  加分：GUI 監看介面
# ============================================================
class Monitor:
	"""以 tkinter 顯示每個 thread 的狀態。ServerThread 從別的 thread 呼叫 update()，
	資料先放進 queue，再由 GUI 的 main loop 取出更新畫面 (tkinter 不是 thread-safe)。"""
	def __init__(self, port, delay):
		import queue
		import tkinter as tk
		from tkinter import ttk
		from tkinter.scrolledtext import ScrolledText
		self.tk, self.queue = tk, queue.Queue()
		self.stop_event = threading.Event()

		self.root = root = tk.Tk()
		root.title(f"Concurrent Server - port {port}")
		root.geometry("860x560")
		self.status = tk.StringVar(value="啟動中...")
		ttk.Label(root, textvariable=self.status, padding=6, font=("TkDefaultFont", 11, "bold")).pack(fill="x")

		cols = ("thread", "client", "status", "value")
		self.tree = ttk.Treeview(root, columns=cols, show="headings", height=8)
		for c, title, w in zip(cols, ("Thread", "Client IP:Port", "狀態", "最後收到的值"), (120, 200, 160, 140)):
			self.tree.heading(c, text=title)
			self.tree.column(c, width=w, anchor="center")
		self.tree.tag_configure("done", foreground="gray50")
		self.tree.tag_configure("live", foreground="#0a7d2c")
		self.tree.pack(fill="x", padx=6)
		self.logbox = ScrolledText(root, height=16, font=("TkFixedFont", 10))
		self.logbox.pack(fill="both", expand=True, padx=6, pady=6)

		self.server = threading.Thread(target=serve, args=(port, delay, self, self.stop_event),
									   name="MainServer", daemon=True)
		root.protocol("WM_DELETE_WINDOW", self.close)
		root.after(100, self.poll)

	def update(self, name, client, status, value, text):
		self.queue.put((name, client, status, value, text))

	def poll(self):
		while not self.queue.empty():
			name, client, status, value, text = self.queue.get()
			shown = "" if value is None else value
			if self.tree.exists(name):
				old = self.tree.item(name, "values")
				shown = shown if value is not None else old[3]
				self.tree.item(name, values=(name, client, status, shown))
			else:
				self.tree.insert("", "end", iid=name, values=(name, client, status, shown))
			self.tree.item(name, tags=("done",) if status in ("結束", "對方已斷線", "錯誤") else ("live",))
			if text:
				self.logbox.insert("end", f"[{datetime.now():%H:%M:%S}] {name} {client}  {text}\n")
				self.logbox.see("end")
		with stats_lock:
			active, total = stats["active"], stats["total"]
		self.status.set(f"等待連線中…　目前連線數: {active}　累計服務: {total}　"
						f"執行緒數: {threading.active_count()}")
		self.root.after(100, self.poll)

	def run(self):
		self.server.start()
		self.root.mainloop()

	def close(self):
		self.stop_event.set()
		self.root.destroy()


def main():
	parser = argparse.ArgumentParser(description="Lab 5 Concurrent TCP Server")
	parser.add_argument("-p", "--port", type=int, default=PORT, help=f"監聽 port (預設 {PORT})")
	parser.add_argument("-d", "--delay", type=float, default=0.0, help="每次回傳前延遲的秒數")
	parser.add_argument("--gui", action="store_true", help="以圖形介面顯示各連線狀態")
	args = parser.parse_args()

	if args.gui:
		Monitor(args.port, args.delay).run()
	else:
		serve(args.port, args.delay)
# end of main


if __name__ == '__main__':
	main()
