# Lab 5 – Concurrent Server

> 學號：D1211110　姓名：陳嘉希

修改 Lab 2 的 Server：main thread 每收到一個 Client 的連線，就產生一個新的 thread（`ServerThread`）與該 Client 溝通，main thread 則回去 `accept()` 等待下一個連線，因此可以同時處理多個 Client。

## 檔案

| 檔案 | 說明 |
|---|---|
| `TCPServer.py` | Concurrent Server（每個 Client 一個 thread） |
| `TCPClient.py` | Client：輸入 n > 0，送出 n-1 開始互相減一 |
| `Lab5_SequenceDiagram.pptx` | 一、循序圖（Lab 2 基本流程、Lab 5 多執行緒流程、執行結果） |
| `screenshots/` | 執行結果截圖 |

## 執行方式

```
python TCPServer.py                 # 視窗 1：啟動 Server (port 6666)
python TCPClient.py 127.0.0.1 5     # 視窗 2、3、4…：可同時開多個 Client
python TCPClient.py 127.0.0.1       # 不給 n 時會要求輸入
```

選項：
- `-p PORT`：指定 port。
- `-d 秒數`：每一步延遲，方便觀察多個 Client 同時進行，例如 `python TCPServer.py -d 1`。
- `--gui`：圖形介面。Server 會即時顯示每個 thread 的狀態；Client 可以一次啟動多個連線。

## 通訊規則（Lab 2）

1. Client 送出 n-1。
2. 收到整數 k 的一方印出 k；若 k > 0，回傳 k-1。
3. 收到 0 的一方結束連線，並送出 `END` 通知對方也結束。

每則訊息佔一行（例如 `4\n`、`END\n`），避免 TCP 串流把兩則訊息黏在一起。

## 加分功能

- **GUI：** Server 監看畫面和 Client 多連線畫面（`--gui`）。
- **輸出不交錯：** 多個 thread 同時輸出時用 `Lock` 保護。
- **連線統計：** 以 `Lock` 保護的共享計數器，顯示目前連線數和累計服務數。
- **延遲選項：** `-d` 延遲選項，以及正確的輸入檢查（n 必須是大於 0 的整數）。
- **Ctrl+C：** Server 可以用 Ctrl+C 正常結束，Windows 也適用。
