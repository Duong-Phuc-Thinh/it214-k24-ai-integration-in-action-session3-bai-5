# Báo Cáo Thiết Kế Hạ Tầng Config Server & Eureka Server (Hệ thống AutoRent)

## 1. Giới thiệu Hệ thống
Chúng tôi chọn xây dựng hệ thống **AutoRent - Hệ thống cho thuê xe tự lái thông minh**. Hệ thống bao gồm 4 service nghiệp vụ chính và 2 thành phần hạ tầng cốt lõi:
- **Config Server**: Quản lý tập trung toàn bộ cấu hình.
- **Eureka Server**: Đăng ký và khám phá dịch vụ (Service Discovery).

### 4 Service Nghiệp Vụ:
1. **car-service (Cổng quản lý xe):** Quản lý đội xe, trạng thái xe, bảng giá và đồng bộ hóa thông tin xe.
2. **booking-service (Cổng đặt xe):** Quản lý quy trình đặt xe, hợp đồng thuê xe, áp dụng chính sách khuyến mãi.
3. **payment-service (Cổng thanh toán):** Kết nối cổng thanh toán trực tuyến (VNPay, Momo), quản lý giao dịch và hoàn tiền.
4. **notification-service (Cổng thông báo):** Gửi email, SMS xác nhận đặt xe, thông báo nhắc nhở hạn trả xe.

---

## 2. Thiết kế Cấu hình Tập trung (Config Server)
Toàn bộ cấu hình được lưu trữ tại một Git Repository giả lập dưới dạng các file JSON định dạng `<service-name>-<profile>.json`. Mỗi service sở hữu ít nhất 3 cấu hình quan trọng:

### Bảng Giá Trị Cấu Hình:
| Service | File Cấu Hình | Thuộc Tính Cấu Hình | Giá Trị | Ý Nghĩa |
|---|---|---|---|---|
| **car-service** | `car-service-dev.json` | `spring.datasource.url` | `jdbc:mysql://localhost:3306/autorent_car_dev` | Chuỗi kết nối DB xe |
| | | `car.pricing.weekend-multiplier` | `1.35` | Hệ số tăng giá cuối tuần (Feature flag/Rule) |
| | | `car.sync.interval-seconds` | `60` | Chu kỳ đồng bộ trạng thái xe (giây) |
| **booking-service**| `booking-service-dev.json` | `spring.datasource.url` | `jdbc:mysql://localhost:3306/autorent_booking_dev` | Chuỗi kết nối DB đặt vé |
| | | `booking.max-days-allowed` | `30` | Số ngày thuê xe tối đa cho phép |
| | | `booking.discount.member-rate` | `0.10` | Tỷ lệ giảm giá cho khách hàng thân thiết (10%) |
| **payment-service**| `payment-service-dev.json` | `payment.gateway.url` | `https://api.sandbox.vnpay.vn/payment` | API Endpoint của cổng thanh toán |
| | | `payment.timeout-ms` | `5000` | Thời gian timeout kết nối thanh toán (ms) |
| | | `payment.enable-sandbox` | `true` | Cờ bật/tắt chế độ test sandbox |
| **notification-service**| `notification-service-dev.json`| `notification.email.sender` | `noreply@autorent.com` | Email người gửi hệ thống |
| | | `notification.retry.max-attempts` | `3` | Số lần thử lại tối đa nếu gửi lỗi |
| | | `notification.template.booking-success`| `Dear {name}, booking {id} confirmed!` | Mẫu thông báo đặt xe thành công |

---

## 3. Sơ Đồ Kiến Trúc Hệ Thống

```text
+-------------------------------------------------------------------------+
|                                GIT REPO                                 |
|  (Chứa các file cấu hình: car-service-dev.json, booking-service-dev...)  |
+-------------------------------------------------------------------------+
                                     │
                                     ▼ (1. Pull Configs)
+-------------------------------------------------------------------------+
|                         CONFIG SERVER (Port: 8888)                      |
|                - Cung cấp REST APIs lấy cấu hình tập trung              |
+-------------------------------------------------------------------------+
         ▲                            ▲                           ▲
         │ (2. Get Configs)           │ (2. Get Configs)          │ (2. Get Configs)
         │                            │                           │
+───────────────────+        +───────────────────+       +────────────────────+
|    car-service    |        |  booking-service  |       |   payment-service  |
|    (Port: 8081)   |        |    (Port: 8082)   |       |    (Port: 8083)    |
+───────────────────+        +───────────────────+       +────────────────────+
         │                            │                           │
         │ (3. Register)              │ (3. Register)             │ (3. Register)
         ▼                            ▼                           ▼
+-------------------------------------------------------------------------+
|                         EUREKA SERVER (Port: 8761)                      |
|                - Quản lý danh sách dịch vụ & Live instances            |
+-------------------------------------------------------------------------+
         ▲                                                        ▲
         │ (4. Discover: "payment-service" / "car-service")       │
         └────────────────────────────────────────────────────────┘
                         (5. Gọi API trực tiếp qua lại)
```

---

## 4. Hướng dẫn chạy Chương trình giả lập
Chương trình viết hoàn toàn bằng **Python (Standard Library)** không yêu cầu cài đặt thư viện ngoài (Zero-dependency).

### Yêu cầu:
- Python 3.x đã cài đặt.

### Các bước chạy:
1. Mở Terminal / CMD tại thư mục chứa source code.
2. Chạy lệnh:
   ```bash
   python main.py
   ```
3. Chương trình sẽ tự động:
   - Khởi tạo thư mục chứa cấu hình Git repo giả lập (`config_repo`).
   - Khởi động **Config Server** tại cổng `8888`.
   - Khởi động **Eureka Discovery Server** tại cổng `8761`.
   - Khởi động tuần tự **4 Microservices** nghiệp vụ (với cổng ngẫu nhiên hoặc chỉ định, hỗ trợ chạy nhiều instance).
   - Thực hiện quy trình: tải cấu hình từ Config Server -> Đăng ký lên Eureka -> Gửi heartbeat định kỳ -> Giả lập hành vi giao dịch (booking-service khám phá và gọi car-service, payment-service).
   - Bấm `Ctrl + C` để dừng chương trình một cách an toàn.
