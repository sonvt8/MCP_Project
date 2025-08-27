# MCP OpenStack — Tool tra cứu VM theo ID (requests-based)

## Tóm tắt

Dự án này cung cấp một **MCP Server** để hệ thống Chat Bot (LLM side = “blackbox”) có thể gọi **tool** lấy thông tin máy ảo (VM) của OpenStack theo **instance_id**.  
Server sử dụng **transport SSE** và expose **tool** `get_server_by_id`. Phần gọi API OpenStack dùng thư viện **requests** (đã kiểm thử trên hệ thống hiện tại).

```
├─ mcp_openstack_requests.py         # MCP server (SSE), expose tool get_server_by_id
├─ openstack_client_requests.py      # Lớp gọi API OpenStack (requests) + hợp nhất kết quả
├─ test_openstack_client_requests.py # CLI test: nhập instance_id, in JSON kết quả
└─ env.example                      # Mẫu biến môi trường
```

---

## 1) Tích hợp vào Chat Bot (LLM là “blackbox”)

### Kiến trúc tổng quan

- **MCP Server** lắng nghe tại `MCP_HOST:MCP_PORT` (mặc định `0.0.0.0:8083`).
- Expose **01 tool**:
  - `get_server_by_id(params: { instance_id: string, project_id?: string, region?: string }) -> JSON`
- Khi Chat Bot cần thông tin VM, LLM client sẽ “discover” tool và gọi theo **JSON Schema** do server sinh ra (không cần mã tích hợp đặc thù phía chúng ta).

### Cài đặt & chạy MCP Server

1. Yêu cầu: Python ≥ 3.9
2. Cài thư viện:

```bash
pip install -r requirements.txt
```

3. Tạo file `.env` (hoặc export env trực tiếp). Có thể copy từ `env.example` và chỉnh giá trị thật:

```ini
# ----- OpenStack -----
OS_HOST=your_host_here
OS_USERNAME=admin
OS_PASSWORD=your_password_here
OS_PROJECT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
OS_USER_DOMAIN_NAME=Default
# Giữ false nếu hạ tầng đang dùng HTTP/SSL tự ký; production khuyến nghị true
OS_VERIFY_SSL=false
# Tuỳ chọn
OS_REQUEST_TIMEOUT=60

# ----- MCP -----
MCP_HOST=0.0.0.0
MCP_PORT=8083
LOG_LEVEL=INFO
```

4. Chạy server:

```bash
python mcp_openstack_requests.py
```

Server sẽ khởi động SSE và lắng nghe lời gọi tool.

### Tool (schema đầu vào/đầu ra)

**Tên:** `get_server_by_id`

**Input (Pydantic model)**

- `instance_id: str` (**bắt buộc**) — ID của VM cần tra cứu
- `project_id: Optional[str]` — nếu không truyền, dùng `OS_PROJECT_ID` từ ENV
- `region: Optional[str]` — (không dùng trong biến thể requests; giữ để tương thích trong tương lai)

**Validation gợi ý:** `instance_id` được trim và không rỗng (raise `ValidationError` nếu sai).

**Output (JSON chuẩn hóa):**

```json
{
  "instance_id": "…",
  "name": "…",
  "status": "ACTIVE",
  "project": { "id": "…", "name": "…" },
  "flavor": {
    "id": "…",
    "name": "…",
    "vcpus": null,
    "ram_mb": null,
    "disk_gb": null
  },
  "image": { "id": "…", "name": "…" },
  "boot_from_volume": true,
  "volumes": [
    {
      "id": "…",
      "name": "…",
      "size_gb": 80,
      "status": "in-use",
      "bootable": true,
      "device": "/dev/vda"
    }
  ],
  "interfaces": [
    {
      "port_id": "…",
      "net_id": "…",
      "mac": "fa:16:3e:…",
      "fixed_ips": ["10.0.0.5"],
      "allowed_address_pairs": ["10.0.0.20"]
    }
  ],
  "availability_zone": "nova",
  "host": "…",
  "hypervisor_hostname": "…",
  "security_groups": ["default"],
  "tags": [],
  "metadata": {},
  "created": "…",
  "updated": "…",
  "server_group": { "id": "…", "name": "…" },
  "raw": {
    "nova": {
      /* payload gốc từ Nova */
    }
  }
}
```

### Ví dụ tool call (minh họa phía client MCP)

```json
{
  "name": "get_server_by_id",
  "arguments": { "instance_id": "5f3b0f2a-xxxx-xxxx-xxxx-xxxxxxxxxxxx" }
}
```

- Nếu input không hợp lệ, server trả về **validation error**; chương trình **không dừng**.
- Tool handler là async; phần `requests` blocking được bọc bằng `asyncio.to_thread` để **không chặn event loop** và server vẫn phản hồi các yêu cầu khác.

---

## 2) Vì sao có `test_openstack_client_requests.py`?

### Mục đích

- Phần LLM/Chat Bot là “blackbox”, ta **không test end-to-end** được.
- Mục tiêu là **chắc chắn lớp gọi OpenStack API** hoạt động đúng.
- File `test_openstack_client_requests.py` là **CLI test độc lập**, tái sử dụng thẳng `OpenStackRequestsClient` để kiểm chứng:
  - Auth Keystone v3
  - Lấy thông tin VM từ Nova
  - Lấy interfaces/ports từ Nova/Neutron (fixed IPs, allowed address pairs)
  - Lấy volumes từ Cinder (phát hiện boot-from-volume)
  - Tra cứu server group (nếu bật)
  - Tra cứu image (Glance) để điền `image.name`

Khi CLI test **pass**, có thể tự tin rằng MCP tool (dùng lại cùng class) sẽ trả dữ liệu đúng cho Chat Bot.

### Cách chạy file test

1. Chuẩn bị `.env` giống hệt khi chạy MCP server.
2. Chạy:

```bash
python test_openstack_client_requests.py <INSTANCE_ID> --log-level DEBUG
# Hoặc lưu JSON
python test_openstack_client_requests.py <INSTANCE_ID> --save result.json
```

- In ra JSON kết quả hoặc block lỗi dạng:

```json
{
  "error": {
    "type": "OpenStackError",
    "message": "…",
    "http_status": 404,
    "details": {}
  }
}
```

- Trả **exit code != 0** khi lỗi → phù hợp cho CI.

---

## Tham số cấu hình chính

- **OpenStack:** `OS_HOST`, `OS_USERNAME`, `OS_PASSWORD`, `OS_PROJECT_ID`, `OS_USER_DOMAIN_NAME`, `OS_VERIFY_SSL`, `OS_REQUEST_TIMEOUT`
- **MCP:** `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`
- Biến môi trường được nạp từ `.env` (qua `python-dotenv`) nếu có; có thể override bằng env thực tế của tiến trình.

---

## Vận hành & bảo mật

- Production khuyến nghị `OS_VERIFY_SSL=true` với chứng chỉ hợp lệ.
- Có thể giới hạn số lệnh đồng thời bằng semaphore/ThreadPool nếu cần (mở rộng sau).

---

## FAQ ngắn

- **Chat Bot cần gì để gọi được tool này?**  
  Chỉ cần client MCP hỗ trợ **SSE** và có khả năng “discover + call” tool theo JSON Schema. Tool đã có schema rõ ràng qua Pydantic.

- **Tại sao dùng `requests` chứ không `aiohttp`?**  
  `requests` đã được kiểm thử OK trên hệ thống hiện tại. MCP vẫn chạy async, bọc lời gọi blocking bằng `asyncio.to_thread` để server không bị chặn.

- **Có thể đổi sang `aiohttp` sau này không?**  
  Có. Kiến trúc tách lớp (MCP server ↔ client OpenStack) cho phép thay thế client mà không ảnh hưởng giao diện tool.

---

## 3) Luồng tương tác end‑to‑end (ví dụ dễ hiểu)

> Mục tiêu của phần này là giúp người đọc **hình dung toàn cảnh**: từ lúc người dùng chat, đến khi hệ thống gọi OpenStack và trả kết quả về.

### Kịch bản ví dụ

1. **Người dùng** gõ vào Chat Bot:  
   _“Cho tôi thông tin server có id **5f3b0f2a-1111-2222-3333-abcdefabcdef** trong project **a12b-c34d**.”_

2. **Chat Bot (MCP Client)** phân tích câu hỏi, “discover” được MCP Server của chúng ta có tool phù hợp: **`get_server_by_id`**.  
   Chat Bot tự động dựng lời gọi tool theo **JSON Schema** (được MCP Server công bố từ Pydantic model):

   ```json
   {
     "name": "get_server_by_id",
     "arguments": {
       "instance_id": "5f3b0f2a-1111-2222-3333-abcdefabcdef",
       "project_id": "a12b-c34d"
     }
   }
   ```

3. **MCP Server** nhận call → **validate** input bằng Pydantic.

   - Nếu thiếu/sai kiểu, MCP trả về **validation error** (Chat Bot thấy lỗi và có thể tự sửa tham số).
   - Nếu hợp lệ, MCP gọi hàm tool `get_server_by_id(...)`.

4. **Tool handler** khởi tạo `OpenStackRequestsClient` bằng các biến trong `.env`/ENV (ví dụ `OS_HOST`, `OS_USERNAME`, `OS_PASSWORD`, `OS_PROJECT_ID`…), rồi thực hiện chuỗi gọi OpenStack (tối giản hoá):

   - **Keystone v3**: lấy token (`POST /v3/auth/tokens`)
   - **Nova**: lấy info VM (`GET /v2.1/{project_id}/servers/{instance_id}`)
   - **Nova**: lấy interfaces của VM (`GET /v2.1/servers/{instance_id}/os-interface`)
   - **Neutron**: với mỗi `port_id`, lấy `allowed_address_pairs`, `fixed_ips` (`GET /v2.0/ports/{port_id}`)
   - **Cinder v3**: với mỗi volume attach, lấy thông tin volume/thiết bị (`GET /v3/{project_id}/volumes/{volume_id}`) để phát hiện **boot-from-volume**
   - **Glance v2**: (tuỳ có `image_id`) lấy `image.name` (`GET /v2/images/{image_id}`)
   - **Nova** (tuỳ tuỳ môi trường): kiểm tra **server group**

   Mọi dữ liệu được **chuẩn hoá** thành 1 JSON gọn cho LLM.

5. **MCP Server** trả JSON kết quả về cho **MCP Client (Chat Bot)**, ví dụ rút gọn:

   ```json
   {
     "instance_id": "5f3b0f2a-1111-2222-3333-abcdefabcdef",
     "name": "prod-web-01",
     "status": "ACTIVE",
     "project": { "id": "a12b-c34d", "name": "Production" },
     "interfaces": [
       {
         "port_id": "xyz",
         "fixed_ips": ["10.0.10.5"],
         "allowed_address_pairs": ["10.0.10.20"]
       }
     ],
     "volumes": [
       {
         "id": "vol-123",
         "device": "/dev/vda",
         "size_gb": 80,
         "bootable": true
       }
     ],
     "boot_from_volume": true,
     "image": { "id": "img-456", "name": "ubuntu-22.04" }
   }
   ```

6. **Chat Bot** dùng JSON đó để soạn câu trả lời thân thiện:  
   _“Server **prod-web-01** đang **ACTIVE**, IP **10.0.10.5**, boot từ volume **/dev/vda (80GB)**, image **ubuntu-22.04**. Cấu hình security/network hợp lệ.”_

### Sơ đồ chuỗi (sequence – rút gọn)

```
User -> ChatBot(LLM/MCP Client): "Thông tin server id 5f3b..., project a12b..."
ChatBot -> MCP Server: call get_server_by_id {instance_id, project_id}
MCP Server -> OpenStack (Keystone): Auth token
MCP Server -> OpenStack (Nova): GET server
MCP Server -> OpenStack (Nova): GET server/os-interface
MCP Server -> OpenStack (Neutron): GET ports/{port_id}
MCP Server -> OpenStack (Cinder): GET volumes/{volume_id}
MCP Server -> OpenStack (Glance): GET images/{image_id}
MCP Server -> ChatBot: JSON kết quả đã chuẩn hoá
ChatBot -> User: Câu trả lời tự nhiên (dựa trên JSON)
```

### Lưu ý lỗi & hành vi mong đợi

- **VM không tồn tại** → MCP trả:
  ```json
  {
    "error": {
      "type": "OpenStackError",
      "message": "Nova server fetch failed: 404 ...",
      "http_status": 404
    }
  }
  ```
  Chat Bot sẽ diễn giải lại: _“Không tìm thấy server với id …”_
- **Thiếu tham số** (ví dụ quên `instance_id`) → **validation error** thay vì crash.
- **Timeout/Network** → lỗi được gói trong `error.type="OpenStackError"` hoặc `UnexpectedError`; Chat Bot có thể gợi ý thử lại.
